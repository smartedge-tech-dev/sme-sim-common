"""MCP (Model Context Protocol) server skeleton: a product registers tools, each usually wrapping one of its HTTP
API operations, and serves them over MCP without writing protocol plumbing.

Install the optional extra ``sme-sim-common[mcp]`` (the official ``mcp`` Python SDK). This module imports without
it; :meth:`McpRegistry.mount`, :meth:`McpRegistry.server` and :meth:`McpRegistry.run_stdio` raise
:class:`McpUnavailable` when the SDK is missing.

Typical use (after ``app = make_base_app(...)``)::

    from sme_sim_common.mcp_server import McpRegistry, register_base_tools

    mcp = McpRegistry("sme-ocpp-sim", version=__version__)
    register_base_tools(mcp, app)                      # get_version / get_state / export_config / set_simulation
    mcp.register_http_tool("list_chargers", "List the simulated charge points.", "GET", "/api/chargers")
    mcp.mount(app, host=args.host)                     # POST /mcp (streamable HTTP), same port as the web UI

Transports: streamable HTTP mounted on the product's FastAPI app (:meth:`McpRegistry.mount`) and stdio
(:meth:`McpRegistry.run_stdio`).
"""

from __future__ import annotations

import contextlib
import inspect
import json
import logging
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable, Dict, List, Mapping, Optional, Union

from pydantic import BaseModel, ValidationError

__all__ = ["McpUnavailable", "ToolError", "McpTool", "McpRegistry", "register_base_tools", "asgi_request",
           "DEFAULT_PATH"]

log = logging.getLogger("sme_sim_common.mcp")

#: Default URL path of the MCP endpoint on the product's app.
DEFAULT_PATH = "/mcp"

Handler = Callable[[Any], Union[Any, Awaitable[Any]]]


class McpUnavailable(RuntimeError):
    """The ``mcp`` SDK is not installed (``pip install sme-sim-common[mcp]``)."""


class ToolError(Exception):
    """Raise from a tool handler to return an MCP tool error (``isError: true``) with this message."""


def _sdk():
    try:
        import mcp_types
        from mcp.server.lowlevel import Server
        from mcp.shared.exceptions import MCPError
    except ImportError as e:  # pragma: no cover - exercised only without the extra
        raise McpUnavailable("MCP support needs the optional extra: pip install 'sme-sim-common[mcp]'") from e
    return mcp_types, Server, MCPError


@dataclass
class McpTool:
    """One registered tool. ``model`` is set when the input schema came from a pydantic model; the handler then
    receives a validated model instance instead of the raw ``arguments`` dict."""

    name: str
    description: str
    input_schema: Dict[str, Any]
    handler: Handler
    model: Optional[type] = None
    read_only: Optional[bool] = None
    destructive: Optional[bool] = None
    extra: Dict[str, Any] = field(default_factory=dict)

    def describe(self) -> Dict[str, Any]:
        """The tool as listed by ``tools/list`` (MCP wire names)."""
        d: Dict[str, Any] = {"name": self.name, "description": self.description, "inputSchema": self.input_schema}
        ann = {k: v for k, v in (("readOnlyHint", self.read_only), ("destructiveHint", self.destructive))
               if v is not None}
        if ann:
            d["annotations"] = ann
        return d


def _schema_of(input_schema: Union[None, Mapping[str, Any], type]) -> tuple[Dict[str, Any], Optional[type]]:
    if input_schema is None:
        return {"type": "object", "properties": {}}, None
    if isinstance(input_schema, type) and issubclass(input_schema, BaseModel):
        return input_schema.model_json_schema(), input_schema
    if isinstance(input_schema, Mapping):
        schema = dict(input_schema)
        if schema.get("type") != "object":
            raise ValueError("an MCP tool input schema must have type 'object' at the root")
        return schema, None
    raise TypeError("input_schema must be a JSON schema dict, a pydantic model class or None")


def _validate_schema(schema: Dict[str, Any], args: Dict[str, Any]) -> None:
    """Check ``args`` against a dict input schema; a violation is a :class:`ToolError`. Skipped when
    ``jsonschema`` is missing (it comes with the ``mcp`` extra)."""
    try:
        import jsonschema
    except ImportError:  # pragma: no cover
        return
    errors = sorted(jsonschema.Draft202012Validator(schema).iter_errors(args), key=lambda e: list(e.path))
    if errors:
        raise ToolError("; ".join(f"{'.'.join(map(str, e.path)) or 'arguments'}: {e.message}" for e in errors))


def _is_loopback(host: Optional[str]) -> bool:
    if host is None:
        return True
    h = host.strip("[]").lower()
    if h == "localhost":
        return True
    import ipaddress

    try:
        ip = ipaddress.ip_address(h)
    except ValueError:
        return False
    return ip.is_loopback or bool(getattr(ip, "ipv4_mapped", None) and ip.ipv4_mapped.is_loopback)


def _error_text(e: BaseException) -> str:
    from starlette.exceptions import HTTPException

    if isinstance(e, ValidationError):
        from .web import bad

        return str(bad(400, e).detail)
    if isinstance(e, HTTPException):
        d = e.detail
        return d.get("message", str(d)) if isinstance(d, dict) else str(d)
    return str(e) or type(e).__name__


class McpRegistry:
    """Tools of one product's MCP server.

    ``name`` / ``version`` are the server info sent to clients (use the dist name and the product version);
    ``instructions`` is optional guidance for the model using the tools."""

    def __init__(self, name: str, version: Optional[str] = None, *, instructions: Optional[str] = None):
        self.name = name
        self.version = version
        self.instructions = instructions
        self._tools: Dict[str, McpTool] = {}
        self._app: Any = None  # set by mount() / register_base_tools(); target of register_http_tool

    # ---- registration

    def register_tool(self, name: str, description: str,
                      input_schema: Union[None, Mapping[str, Any], type] = None,
                      handler: Optional[Handler] = None, *, read_only: Optional[bool] = None,
                      destructive: Optional[bool] = None) -> Any:
        """Register a tool. ``input_schema`` is a JSON schema dict (``type: object``), a pydantic model class
        (the handler then gets a validated instance) or ``None`` (no arguments; the handler gets ``{}``).
        ``handler(arguments)`` may be sync or async. Its result becomes the tool result: ``str`` as text,
        ``dict`` as JSON text plus ``structuredContent``, a pydantic model as its JSON dump, ``None`` as ``"ok"``,
        anything else as JSON text. Raise :class:`ToolError` (or ``bad(...)`` / ``HTTPException``, ``ValueError``,
        ``TypeError``, ``KeyError``, ``LookupError``, a pydantic ``ValidationError``) for a tool error; any other
        exception is logged and returned as a tool error too.

        Without ``handler`` it returns a decorator. ``read_only`` / ``destructive`` are MCP tool annotation hints.
        A duplicate name is a ``ValueError``."""
        if handler is None:
            def deco(fn: Handler) -> Handler:
                self.register_tool(name, description, input_schema, fn, read_only=read_only,
                                   destructive=destructive)
                return fn

            return deco
        if not name or not isinstance(name, str):
            raise ValueError("tool name must be a non-empty string")
        if name in self._tools:
            raise ValueError(f"tool {name!r} is already registered")
        schema, model = _schema_of(input_schema)
        self._tools[name] = McpTool(name, description, schema, handler, model, read_only, destructive)
        return handler

    def tool(self, name: Optional[str] = None, description: Optional[str] = None,
             input_schema: Union[None, Mapping[str, Any], type] = None, **hints: Any):
        """Decorator form of :meth:`register_tool`; ``name`` defaults to the function name and ``description`` to
        its docstring."""
        def deco(fn: Handler) -> Handler:
            doc = inspect.getdoc(fn) or ""
            self.register_tool(name or fn.__name__, description if description is not None else doc,
                               input_schema, fn, **hints)
            return fn

        return deco

    def register_http_tool(self, name: str, description: str, method: str, path: str,
                           input_schema: Union[None, Mapping[str, Any], type] = None, *,
                           body: Optional[str] = "json", app: Any = None, read_only: Optional[bool] = None,
                           destructive: Optional[bool] = None) -> None:
        """Register a tool that calls ``method path`` on the product's own app in-process (no socket, the same
        validation and hooks as the web UI). ``{param}`` placeholders in ``path`` are filled from the arguments
        of the same name. The remaining arguments are sent as the JSON body (``body="json"``), as the text of
        the argument named ``body`` (``body="text"``, e.g. YAML for ``PUT /api/config``), or as query parameters
        (``body=None``; the default for ``GET`` / ``DELETE``). A response status >= 400 is a tool error with the
        response's ``error`` message. ``app`` defaults to the app given to :meth:`mount` /
        :func:`register_base_tools`. ``read_only`` defaults to ``True`` for ``GET``."""
        import re

        method = method.upper()
        placeholders = re.findall(r"{(\w+)}", path)
        if method in ("GET", "HEAD", "DELETE") and body == "json":
            body = None
        if read_only is None and method in ("GET", "HEAD"):
            read_only = True

        async def handler(args: Any) -> Any:
            data = (args.model_dump(mode="json", exclude_unset=True) if isinstance(args, BaseModel)
                    else dict(args or {}))
            target = app if app is not None else self._app
            if target is None:
                raise ToolError("MCP registry is not attached to an app (call mount(app) first)")
            from urllib.parse import quote, urlencode

            url = path
            for p in placeholders:
                if p not in data:
                    raise ToolError(f"missing argument {p!r}")
                url = url.replace("{" + p + "}", quote(str(data.pop(p)), safe=""))
            content: Optional[bytes] = None
            ctype = None
            if body == "json":
                content, ctype = json.dumps(data, default=str).encode("utf-8"), "application/json"
            elif body == "text":
                content, ctype = str(data.pop("body", "")).encode("utf-8"), "text/plain; charset=utf-8"
                if data:
                    raise ToolError(f"unexpected argument(s) {sorted(data)} (only 'body' and path parameters)")
            elif data:
                query = {k: json.dumps(v) if isinstance(v, (dict, bool)) else v
                         for k, v in data.items() if v is not None}
                if query:
                    url += "?" + urlencode(query, doseq=True)
            status, headers, raw = await asgi_request(target, method, url, content, ctype)
            ctype_resp = headers.get("content-type", "")
            if status < 400 and not (ctype_resp.startswith(("text/", "application/json", "application/x-yaml"))
                                     or not ctype_resp):
                raise ToolError(f"{method} {path} returned {ctype_resp}, which this tool cannot return as text")
            text = raw.decode("utf-8", errors="replace")
            parsed: Any = text
            if headers.get("content-type", "").startswith("application/json"):
                with contextlib.suppress(ValueError):
                    parsed = json.loads(text)
            if status >= 400:
                msg: Any = parsed
                if isinstance(parsed, dict):
                    msg = parsed.get("error") or parsed.get("detail") or text
                    if parsed.get("errors"):
                        msg = f"{msg}: " + "; ".join(str(e) for e in parsed["errors"])
                raise ToolError(f"HTTP {status}: {msg or text}")
            return parsed

        self.register_tool(name, description, input_schema, handler, read_only=read_only, destructive=destructive)

    # ---- introspection / direct calls (also what the MCP handlers use)

    @property
    def tools(self) -> List[McpTool]:
        return list(self._tools.values())

    def list_tools(self) -> List[Dict[str, Any]]:
        """``tools/list`` entries (MCP wire names: ``name`` / ``description`` / ``inputSchema`` / ``annotations``)."""
        return [t.describe() for t in self._tools.values()]

    async def call_tool(self, name: str, arguments: Optional[Mapping[str, Any]] = None) -> Any:
        """Validate ``arguments`` and run the handler; returns its raw result. Unknown tools are ``KeyError``;
        handler errors propagate (the MCP layer turns them into tool errors)."""
        tool = self._tools[name]
        args: Any = dict(arguments or {})
        if tool.model is not None:
            args = tool.model.model_validate(args)
        else:
            _validate_schema(tool.input_schema, args)
        res = tool.handler(args)
        if inspect.isawaitable(res):
            res = await res
        return res

    # ---- MCP SDK

    def server(self):
        """A low-level ``mcp`` ``Server`` serving the registered tools (built on each call)."""
        types, Server, MCPError = _sdk()

        async def on_list_tools(ctx, params) -> Any:
            return types.ListToolsResult(tools=[types.Tool.model_validate(t.describe()) for t in self.tools])

        async def on_call_tool(ctx, params) -> Any:
            if params.name not in self._tools:
                raise MCPError(types.INVALID_PARAMS, f"unknown tool {params.name!r}")
            try:
                res = await self.call_tool(params.name, params.arguments)
            except (ToolError, ValidationError, ValueError, TypeError, LookupError) as e:
                return _error_result(types, _error_text(e))
            except Exception as e:  # noqa: BLE001 - any handler failure is a tool error, not a dropped request
                from starlette.exceptions import HTTPException

                if not isinstance(e, HTTPException):
                    log.exception("MCP tool %s failed", params.name)
                return _error_result(types, _error_text(e))
            return _result(types, res)

        return Server(self.name, version=self.version or "", instructions=self.instructions,
                      on_list_tools=on_list_tools, on_call_tool=on_call_tool)

    def mount(self, app: Any, path: str = DEFAULT_PATH, *, host: Optional[str] = None,
              json_response: bool = True) -> None:
        """Serve the tools over MCP streamable HTTP at ``path`` on the FastAPI / Starlette ``app`` (same port as
        the web UI). Call before the app starts; the MCP session manager runs inside the app's lifespan.

        ``host`` is the bind address (``args.host``): on a loopback host (the default) requests whose ``Host`` /
        ``Origin`` header is not loopback are refused (DNS-rebinding protection); on any other host the check is
        off. Stateless mode: no MCP session ids, every request stands alone, so a simulator restart does not
        break a connected client. ``json_response`` answers with plain JSON instead of an SSE stream."""
        _sdk()
        from mcp.server.streamable_http_manager import StreamableHTTPSessionManager
        from mcp.server.transport_security import TransportSecuritySettings
        from starlette.routing import Route

        if not path.startswith("/"):
            raise ValueError("path must start with '/'")
        if _is_loopback(host):
            security = TransportSecuritySettings(
                enable_dns_rebinding_protection=True,
                allowed_hosts=["127.0.0.1", "127.0.0.1:*", "localhost", "localhost:*", "[::1]", "[::1]:*"],
                allowed_origins=["http://127.0.0.1", "http://127.0.0.1:*", "http://localhost", "http://localhost:*",
                                 "http://[::1]", "http://[::1]:*"])
        else:
            security = TransportSecuritySettings(enable_dns_rebinding_protection=False)
        self._app = app
        state: Dict[str, Any] = {}

        async def endpoint(scope, receive, send) -> None:
            manager = state.get("manager")
            if manager is None:
                from starlette.responses import JSONResponse

                await JSONResponse({"error": "MCP endpoint not running"}, status_code=503)(scope, receive, send)
                return
            await manager.handle_request(scope, receive, send)

        class _Endpoint:  # an ASGI app instance, not a function: Starlette passes (scope, receive, send) through
            __call__ = staticmethod(endpoint)

        app.router.routes.insert(0, Route(path, _Endpoint(), methods=["GET", "POST", "DELETE"]))
        inner = app.router.lifespan_context

        @contextlib.asynccontextmanager
        async def lifespan(a):
            # A session manager runs once only, so each lifespan entry (e.g. repeated TestClient blocks) gets a
            # fresh one.
            manager = StreamableHTTPSessionManager(self.server(), json_response=json_response, stateless=True,
                                                   security_settings=security)
            async with inner(a) as st:
                async with manager.run():
                    state["manager"] = manager
                    try:
                        yield st
                    finally:
                        state.pop("manager", None)

        app.router.lifespan_context = lifespan
        log.debug("MCP endpoint mounted at %s (%d tools)", path, len(self._tools))

    async def run_stdio(self, app: Any = None) -> None:
        """Serve the tools over stdio (a local client launches the product as a subprocess). When ``app`` is
        given its lifespan runs around the server (``make_base_app`` starts / stops the engine there) and HTTP
        tools target it. stdout carries the protocol: root log handlers writing to stdout are switched to stderr."""
        _sdk()
        from mcp.server.stdio import stdio_server

        if app is not None:
            self._app = app
        import sys

        for h in logging.getLogger().handlers:  # stdout carries the protocol: move stdout log handlers to stderr
            if isinstance(h, logging.StreamHandler) and getattr(h, "stream", None) is sys.stdout:
                h.setStream(sys.stderr)
        server = self.server()
        lifespan = app.router.lifespan_context(app) if app is not None else contextlib.nullcontext()
        async with lifespan:
            async with stdio_server() as (read, write):
                await server.run(read, write, server.create_initialization_options())


def _result(types, res: Any):
    if isinstance(res, BaseModel):
        res = res.model_dump(mode="json")
    if res is None:
        return types.CallToolResult(content=[types.TextContent(text="ok")])
    if isinstance(res, str):
        return types.CallToolResult(content=[types.TextContent(text=res)])
    text = json.dumps(res, ensure_ascii=False, indent=2, default=str)
    structured = res if isinstance(res, dict) else None
    return types.CallToolResult(content=[types.TextContent(text=text)], structured_content=structured)


def _error_result(types, msg: str):
    return types.CallToolResult(content=[types.TextContent(text=msg)], is_error=True)


async def asgi_request(app: Any, method: str, path: str, content: Optional[bytes] = None,
                       content_type: Optional[str] = None) -> tuple[int, Dict[str, str], bytes]:
    """Call ``app`` (an ASGI app) in-process with one HTTP request; returns ``(status, headers, body)``. Header
    names are lower case. Used by :meth:`McpRegistry.register_http_tool`; no lifespan is run (the app is
    already running when a tool is called)."""
    from urllib.parse import unquote, urlsplit

    parts = urlsplit(path)
    body = content or b""
    headers = [(b"host", b"127.0.0.1"), (b"content-length", str(len(body)).encode())]
    if content_type:
        headers.append((b"content-type", content_type.encode("latin-1")))
    scope = {"type": "http", "asgi": {"version": "3.0"}, "http_version": "1.1", "method": method,
             "scheme": "http", "path": unquote(parts.path), "raw_path": parts.path.encode(),
             "query_string": parts.query.encode(), "root_path": "", "headers": headers,
             "client": ("127.0.0.1", 0), "server": ("127.0.0.1", 0)}
    sent = False
    status = 500
    resp_headers: Dict[str, str] = {}
    chunks: List[bytes] = []

    async def receive():
        nonlocal sent
        if not sent:
            sent = True
            return {"type": "http.request", "body": body, "more_body": False}
        return {"type": "http.disconnect"}

    async def send(msg):
        nonlocal status
        if msg["type"] == "http.response.start":
            status = msg["status"]
            for k, v in msg.get("headers", []):
                resp_headers[k.decode("latin-1").lower()] = v.decode("latin-1")
        elif msg["type"] == "http.response.body":
            chunks.append(msg.get("body", b""))

    await app(scope, receive, send)
    return status, resp_headers, b"".join(chunks)


class _SimulationArgs(BaseModel):
    running: Optional[bool] = None
    time_scale: Optional[float] = None


def register_base_tools(registry: McpRegistry, app: Any, *, prefix: str = "") -> List[str]:
    """Register the generic tools of a :func:`sme_sim_common.web.make_base_app` app (each wraps the HTTP route of
    the same meaning) and attach ``app`` to ``registry``. Returns the tool names:

    * ``get_version`` - ``GET /api/version``
    * ``get_state`` - ``GET /api/state`` (the engine snapshot the web UI shows)
    * ``export_config`` - ``GET /api/config`` (the running configuration as YAML text)
    * ``set_simulation`` - ``POST /api/simulation`` ``{"running", "time_scale"}`` (start / stop / speed), only
      when the app has the ``simulation`` feature

    ``prefix`` is prepended to every name (e.g. ``"ocpp_"``) if the product wants a namespace."""
    registry._app = app
    names = []

    def add(name: str, *a: Any, **kw: Any) -> None:
        registry.register_http_tool(prefix + name, *a, **kw)
        names.append(prefix + name)

    add("get_version", "Product name, product version and sme-sim-common version of this simulator.",
        "GET", "/api/version")
    add("get_state", "Current simulator state: the snapshot the web UI shows (devices, values, status).",
        "GET", "/api/state")
    add("export_config", "The running configuration as YAML text (what 'Save' would write).",
        "GET", "/api/config")
    features = getattr(getattr(app, "state", None), "features", None) or {}
    if features.get("simulation"):
        add("set_simulation", "Start or stop the simulation and/or change its speed. "
            "running: true = start, false = stop; time_scale: simulated seconds per real second.",
            "POST", "/api/simulation", _SimulationArgs, destructive=False)
    return names
