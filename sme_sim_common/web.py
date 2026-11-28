"""Web helpers shared by the simulators: mounting the common static assets and the product's own static
directory, turning exceptions into HTTP errors, and the standard app (:func:`make_base_app`, design §7.2 / §8.2.1).

``make_base_app`` generalises sme-modbus-sim 085fe59 ``web.py`` (``create_app``: config / xlsx / templates /
device CRUD routes, ``/ws`` snapshot + seq dedup) and sme-bac-sim v0.4.0 ``web.py`` (missing-static fallback).
"""

from __future__ import annotations

import contextlib
from pathlib import Path
from typing import Any, List, Optional, Union

from pydantic import ValidationError
from starlette.exceptions import HTTPException
from starlette.staticfiles import StaticFiles

__all__ = ["COMMON_PREFIX", "STATIC_DIR", "VERSION_TOKEN", "FEATURES", "MAX_IMPORT_BYTES", "mount_common", "mount_product_static",
           "bad", "error_response", "make_base_app"]

#: URL prefix of the shared assets. Deliberately not nested under the product's ``/static`` (Starlette matches
#: mounts in registration order, so a nested path would be swallowed by the product mount).
COMMON_PREFIX = "/sme-sim-common"
#: On-disk location of the shared assets (shell/, brand/, vendor/, i18n/).
STATIC_DIR = Path(__file__).resolve().parent / "static"
#: Literal token in the product's ``index.html`` replaced by the sme-sim-common version when ``GET /`` is served
#: (``?v=`` cache busting of the shared assets and shell.js ``data-common-version``).
VERSION_TOKEN = "__SME_SIM_COMMON_VERSION__"
XLSX_TYPE = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
#: Optional standard route groups of :func:`make_base_app`.
FEATURES = ("xlsx", "templates", "devices", "simulation")
#: Default cap on the request body of ``POST /api/config/import`` (all parts together), in bytes.
MAX_IMPORT_BYTES = 10 * 1024 * 1024


def mount_common(app, prefix: str = COMMON_PREFIX) -> None:
    """Serve the package's ``static/`` (shell, brand, vendor, common i18n) under ``prefix``."""
    app.mount(prefix, StaticFiles(packages=[("sme_sim_common", "static")]), name="sme-sim-common")


def mount_product_static(app, static_dir: Union[str, Path], path: str = "/static", name: str = "static") -> bool:
    """Mount the product's static directory if it exists (a source checkout without a built UI still serves the
    API). Returns whether it was mounted."""
    d = Path(static_dir)
    if not d.is_dir():
        return False
    app.mount(path, StaticFiles(directory=d), name=name)
    return True


def bad(status: int, msg: Union[str, BaseException], *, errors: Optional[List[str]] = None) -> HTTPException:
    """Build an ``HTTPException`` (``raise bad(400, e)``). A pydantic ``ValidationError`` becomes a compact
    ``"loc: message; ..."`` text without the ``Value error, `` prefix; other exceptions use ``str(e)``.
    With ``errors`` the detail is ``{"message": ..., "errors": [...]}`` (Excel import row errors)."""
    if errors is not None:
        return HTTPException(status_code=status, detail={"message": str(msg), "errors": list(errors)})
    if isinstance(msg, ValidationError):
        parts = []
        for err in msg.errors():
            loc, text = ".".join(str(x) for x in err["loc"]), str(err["msg"]).removeprefix("Value error, ")
            parts.append(f"{loc}: {text}" if loc else text)
        detail = "; ".join(parts)
    else:
        detail = str(msg)
    return HTTPException(status_code=status, detail=detail)


def error_response(request, exc: HTTPException):
    """JSON body for an ``HTTPException``: ``{"detail": ..., "error": message}``. ``detail`` keeps the FastAPI
    shape the existing UIs read; ``error`` is the design §7.2 field. When the detail carries ``errors``
    (``bad(..., errors=[...])``) they are also put at the top level (``{"errors": [...]}``)."""
    from starlette.responses import JSONResponse, Response

    if exc.status_code in (204, 304):
        return Response(status_code=exc.status_code, headers=exc.headers)
    detail = exc.detail
    msg = detail.get("message", "") if isinstance(detail, dict) else str(detail)
    body = {"detail": detail, "error": msg}
    if isinstance(detail, dict) and "errors" in detail:
        body["errors"] = detail["errors"]
    return JSONResponse(body, status_code=exc.status_code, headers=exc.headers)


def _list_item_model(model_cls, attr: str):
    """The pydantic item model of ``model_cls.<attr>: List[Item]`` (``Optional`` unwrapped), or ``None``."""
    from typing import get_args

    from pydantic import BaseModel

    f = getattr(model_cls, "model_fields", {}).get(attr)
    stack = [f.annotation] if f is not None else []
    while stack:
        t = stack.pop()
        if isinstance(t, type) and issubclass(t, BaseModel):
            return t
        stack.extend(get_args(t))
    return None


def _key_type(item_model, attr: str) -> type:
    """``int`` or ``str``: the type of the device key field ``attr`` of ``item_model`` (``Optional`` unwrapped;
    ``str`` when unknown)."""
    from typing import get_args

    f = getattr(item_model, "model_fields", {}).get(attr) if item_model is not None else None
    stack = [f.annotation] if f is not None else []
    while stack:
        t = stack.pop()
        if t is int or t is str:
            return t
        stack.extend(get_args(t))
    return str


def _accepts_kw(fn, name: str) -> bool:
    """Whether ``fn`` takes the keyword argument ``name`` (by name or through ``**kwargs``)."""
    import inspect

    try:
        params = inspect.signature(fn).parameters.values()
    except (TypeError, ValueError):  # builtins / C callables without a signature
        return False
    return any(p.kind is p.VAR_KEYWORD or (p.name == name and p.kind in (p.POSITIONAL_OR_KEYWORD, p.KEYWORD_ONLY))
               for p in params)


async def _call(fn, *args, **kwargs):
    """Call a product hook; sync or async."""
    import inspect

    res = fn(*args, **kwargs)
    if inspect.isawaitable(res):
        res = await res
    return res


def make_base_app(engine, *, config_path: Optional[Union[str, Path]] = None,
                  static_dir: Optional[Union[str, Path]] = None, product_routers=(),
                  features: Optional[dict] = None, title: str = "SME Sim", version: Optional[str] = None,
                  config_model: Optional[type] = None, xlsx=None, templates=None,
                  devices_attr: str = "devices", device_key: str = "name", device_model: Optional[type] = None,
                  duplicate_hook=None, manage_engine: bool = True, key_type: Optional[type] = None,
                  create_hook=None, simulation_hook=None, import_hooks: Optional[dict] = None,
                  max_import_bytes: int = MAX_IMPORT_BYTES):
    """FastAPI app with the standard routes; the product adds its protocol routes through ``product_routers``
    (FastAPI ``APIRouter`` objects, Starlette ``Router`` objects, or plain route objects; matched before the mounts).
    Their routes are flattened into ``app.routes`` (FastAPI ``APIRoute`` objects, dependency injection intact).

    ``engine`` follows :class:`sme_sim_common.engine.EngineProtocol`. Always present: ``GET /``, ``/static``
    (when ``static_dir`` exists), ``/sme-sim-common``, ``GET /api/version``, ``GET /api/state``,
    ``GET|PUT /api/config`` (YAML text), ``POST /api/config/save`` (``engine.config_text`` written atomically),
    ``WS /ws``. Per feature:

    * ``xlsx`` (needs ``xlsx=XlsxSchema``): ``GET /api/config/xlsx``, ``GET /api/config/xlsx-template``,
      ``POST /api/config/import`` (multipart field ``file``). ``import_hooks`` maps file extensions
      (``".csv"``, ``".yaml"`` ...) to ``hook(engine, files: dict[filename, bytes]) -> (config | None, messages)``
      or ``(config, messages, config_text)`` (sync or async); the extension of the first ``file`` part picks the
      hook and every ``file`` part is passed. ``config`` ``None`` = ``messages`` are errors (400). Other files go
      to ``xlsx``. ``POST /api/config/import`` exists when ``xlsx`` is on or ``import_hooks`` is given. A request
      body larger than ``max_import_bytes`` (default :data:`MAX_IMPORT_BYTES`) is refused with 413 before it is
      parsed.
    * ``templates`` (needs ``templates=TemplateRegistry``): ``GET /api/templates``, ``POST /api/templates/reload``,
      ``POST /api/templates/from-device/{device}``
    * ``devices`` (a device = one item of the config's top-level list ``devices_attr``, identified by
      ``device_key``): ``POST /api/devices``, ``POST /api/devices/{name}/duplicate``, ``DELETE /api/devices/{name}``,
      ``GET|PUT /api/devices/{name}/config``. Edits re-dump the config (``exclude_unset``; comments are lost) and
      reload it. The ``{name}`` path parameter is converted to ``key_type`` (default: the type of the
      ``device_key`` field of the device model, ``int`` or ``str``). ``create_hook(engine, body: dict) -> dict``
      completes a new device before validation (e.g. a free key). ``duplicate_hook(engine, dev: dict, new_key,
      body: dict) -> dict`` adjusts the copy (e.g. a free Modbus unit id) and may change its key; it runs before
      the "key already exists" check. Without a hook the copy's key is ``body["name"]`` (or ``body[device_key]``)
      or, for ``str`` keys, ``{key}_copy`` / ``{key}_copy2`` ..., for ``int`` keys the largest key + 1. A hook that
      accepts a ``src_key`` keyword (or ``**kwargs``) also gets the source device's key: ``duplicate_hook(engine,
      dev, new_key, body, *, src_key)``; ``dev`` is a fresh copy (the source's dump with the new key), the source
      device itself is never passed. Unknown devices are 404 ``unknown device <key>`` (``int`` keys unquoted).
      Responses carry the key as ``name``.
    * ``simulation`` (engine has ``set_running``): ``POST /api/simulation`` ``{"running", "time_scale"}``.
      ``simulation_hook(engine, rest: dict) -> dict | None`` (sync or async) receives the other fields after
      ``running`` / ``time_scale`` were applied (``set_running`` is then skipped when neither is given); a dict
      result is merged into the response.

    ``features`` maps a feature name to ``False`` to switch it off (default: on when its dependency is given).
    ``config_model`` defaults to ``type(engine.config)``, ``config_path`` to ``engine.config_path``.
    ``GET /`` serves ``static_dir/index.html`` with :data:`VERSION_TOKEN` replaced by the common version.
    Errors are ``bad()`` exceptions rendered by :func:`error_response`.
    """
    import asyncio
    import json
    from contextlib import asynccontextmanager

    import yaml
    from fastapi import FastAPI
    from starlette.datastructures import UploadFile
    from starlette.requests import Request
    from starlette.responses import HTMLResponse, JSONResponse, PlainTextResponse, Response
    from starlette.routing import Route, WebSocketRoute
    from starlette.websockets import WebSocket, WebSocketDisconnect

    from . import __version__ as common_version
    from .config import atomic_write_text, parse_text
    from .xlsx import XlsxUnavailable, to_yaml

    model_cls = config_model or type(engine.config)
    save_path = config_path if config_path is not None else getattr(engine, "config_path", None)
    static = Path(static_dir) if static_dir is not None else None
    item_model = device_model or _list_item_model(model_cls, devices_attr)
    unknown = set(features or {}) - set(FEATURES)
    if unknown:
        raise ValueError(f"unknown feature(s) {sorted(unknown)}; known: {list(FEATURES)}")
    available = {"xlsx": xlsx is not None, "templates": templates is not None, "devices": item_model is not None,
                 "simulation": hasattr(engine, "set_running")}
    on = {k: bool((features or {}).get(k, available[k])) for k in FEATURES}
    for k in FEATURES:
        if on[k] and not available[k]:
            raise ValueError(f"feature {k!r} is enabled but its dependency is missing")

    def yaml_response(text: str) -> PlainTextResponse:
        return PlainTextResponse(text, media_type="application/x-yaml")

    async def json_object(request: Request, what: str = "a JSON object") -> dict:
        body = await request.body()
        try:
            data = json.loads(body or b"{}")
        except ValueError as e:
            raise bad(400, f"invalid JSON: {e}") from None
        if not isinstance(data, dict):
            raise bad(400, f"expected {what}")
        return data

    async def apply(cfg, text: Optional[str] = None) -> None:
        try:
            await engine.reload(cfg, text)
        except HTTPException:
            raise
        except Exception as e:  # validation, behavior compile, bind errors: the old config keeps running
            raise bad(400, e) from None

    # ---- core

    async def api_version(request: Request):
        return JSONResponse({"name": title, "version": version, "common_version": common_version})

    async def api_state(request: Request):
        return JSONResponse(engine.snapshot())

    async def config_get(request: Request):
        return yaml_response(engine.config_text)

    async def config_put(request: Request):
        text = (await request.body()).decode("utf-8")
        try:
            cfg = parse_text(text, model_cls)
        except (yaml.YAMLError, ValueError) as e:  # pydantic ValidationError is a ValueError
            raise bad(400, e) from None
        await apply(cfg, text)
        return JSONResponse({"ok": True})

    async def config_save(request: Request):
        if not save_path:
            raise bad(400, "no config file (started without -c); nothing to save to")
        try:
            atomic_write_text(save_path, engine.config_text)
        except OSError as e:
            raise bad(400, f"cannot write {save_path}: {e.strerror or e}") from None
        engine.log_event("config", f"configuration saved to {save_path}")
        return JSONResponse({"ok": True, "path": str(save_path)})

    routes: list = [Route("/api/version", api_version), Route("/api/state", api_state),
                    Route("/api/config", config_get, methods=["GET"]),
                    Route("/api/config", config_put, methods=["PUT"]),
                    Route("/api/config/save", config_save, methods=["POST"])]

    # ---- simulation

    if on["simulation"]:
        async def simulation(request: Request):
            body = await json_object(request)
            std = ("running", "time_scale")
            rest = {k: v for k, v in body.items() if k not in std}
            extra = None
            try:
                if simulation_hook is None or any(k in body for k in std):
                    engine.set_running(body.get("running"), body.get("time_scale"))
                if simulation_hook is not None:
                    extra = await _call(simulation_hook, engine, rest)
            except (TypeError, ValueError) as e:
                raise bad(400, e) from None
            resp = {"running": getattr(engine, "running", None), "time_scale": getattr(engine, "time_scale", None)}
            if isinstance(extra, dict):
                resp.update(extra)
            return JSONResponse(resp)

        routes.append(Route("/api/simulation", simulation, methods=["POST"]))

    # ---- xlsx

    if on["xlsx"]:
        def attachment(data: bytes, name: str) -> Response:
            return Response(data, media_type=XLSX_TYPE,
                            headers={"Content-Disposition": f'attachment; filename="{name}"'})

        async def config_xlsx(request: Request):
            try:
                data, warnings = xlsx.export_xlsx(engine.config)
            except XlsxUnavailable as e:
                raise bad(501, e) from None
            except ValueError as e:
                raise bad(400, e) from None
            resp = attachment(data, xlsx.export_file)
            if warnings:
                resp.headers["X-Warnings"] = json.dumps(warnings, ensure_ascii=True)
            return resp

        async def config_xlsx_template(request: Request):
            try:
                return attachment(xlsx.blank_template(), xlsx.template_file)
            except XlsxUnavailable as e:
                raise bad(501, e) from None

        routes += [Route("/api/config/xlsx", config_xlsx),
                   Route("/api/config/xlsx-template", config_xlsx_template)]

    # ---- import (xlsx and / or the product's import_hooks, chosen by file extension)

    hooks = {(k if k.startswith(".") else f".{k}").lower(): v for k, v in (import_hooks or {}).items()}
    if on["xlsx"] or hooks:
        async def capped_body(request: Request) -> None:
            too_big = bad(413, f"the upload is larger than {max_import_bytes} bytes (import size limit)")
            with contextlib.suppress(ValueError):
                if int(request.headers.get("content-length", "")) > max_import_bytes:
                    raise too_big
            body = bytearray()
            async for chunk in request.stream():
                body += chunk
                if len(body) > max_import_bytes:
                    raise too_big
            request._body = bytes(body)  # request.form() parses the cached body

        async def config_import(request: Request):
            await capped_body(request)
            form = await request.form()
            files = [f for f in form.getlist("file") if isinstance(f, UploadFile)]
            if not files:
                raise bad(400, "multipart field 'file' (the file to import) is required")
            first = files[0]
            ext = Path(first.filename or "").suffix.lower()
            text = None
            if ext in hooks:
                uploads = {(f.filename or f"upload-{i}"): await f.read() for i, f in enumerate(files)}
                try:
                    res = tuple(await _call(hooks[ext], engine, uploads))
                except HTTPException:
                    raise
                except Exception as e:  # parse / decode / zip errors of the product's importer
                    raise bad(400, e) from None
                cfg, msgs = res[0], res[1]
                text = res[2] if len(res) > 2 else None
                what = f"configuration imported from {', '.join(uploads)}"
            elif on["xlsx"]:
                cfg, msgs = xlsx.import_xlsx(await first.read(), engine.config)
                what = f"Excel workbook imported ({first.filename})"
            else:
                raise bad(400, f"cannot import {first.filename or 'the file'!r}: supported {', '.join(sorted(hooks))}")
            msgs = [str(m) for m in (msgs or [])]
            if cfg is None:
                raise bad(400, f"{len(msgs)} error(s) in {first.filename or 'the workbook'}", errors=msgs)
            try:
                await engine.reload(cfg, text if text is not None else to_yaml(cfg))
            except Exception as e:
                raise bad(400, "the imported configuration cannot be applied", errors=[str(e)]) from None
            if msgs:
                what += f", {len(msgs)} warning(s): " + "; ".join(msgs[:5]) + (" ..." if len(msgs) > 5 else "")
            engine.log_event("config", what)
            return JSONResponse({"ok": True, "warnings": msgs})

        routes.append(Route("/api/config/import", config_import, methods=["POST"]))

    # ---- devices (= items of the top-level list ``devices_attr``)

    def device_items() -> list:
        return list(getattr(engine.config, devices_attr, None) or [])

    def device_key_of(d) -> Any:
        return d.get(device_key) if isinstance(d, dict) else getattr(d, device_key, None)

    ktype = key_type or _key_type(item_model, device_key)

    def device_or_404(name: str):
        if ktype is str:
            match = lambda k: str(k) == name  # noqa: E731
        else:
            try:
                key = ktype(name)
            except (TypeError, ValueError):
                raise bad(404, f"unknown device {name!r}") from None
            match = lambda k: k == key  # noqa: E731
        for i, d in enumerate(device_items()):
            if match(device_key_of(d)):
                return i, d
        raise bad(404, f"unknown device {name!r}" if ktype is str else f"unknown device {key!r}")

    def dump_item(d) -> dict:
        return d.model_dump(mode="json", exclude_unset=True, exclude_none=True)

    if on["templates"]:
        async def templates_list(request: Request):
            return JSONResponse(templates.catalog())

        async def templates_reload(request: Request):
            errors = templates.load_user_templates()
            tdir = templates.templates_dir()
            engine.log_event("config", f"user templates reloaded from {tdir} "
                                       f"({len(templates.user_templates)} loaded, {len(errors)} with errors)")
            return JSONResponse({"dir": str(tdir), "loaded": sorted(templates.user_templates), "errors": errors,
                                 "templates": templates.catalog()})

        async def template_from_device(request: Request):
            device = request.path_params["device"]
            _, dev = device_or_404(device)
            body = await json_object(request)
            name = body.get("name")
            if not isinstance(name, str) or not name:
                raise bad(400, "name: required")
            try:
                text = templates.device_as_template(dev, name, body.get("title"), body.get("description"))
            except ValueError as e:
                raise bad(400, e) from None
            path = templates.templates_dir() / f"{name}.yaml"
            if path.exists() and not body.get("overwrite"):
                raise bad(409, f"{path} already exists (set overwrite to replace it)")
            try:
                path.parent.mkdir(parents=True, exist_ok=True)
                atomic_write_text(path, text)
            except OSError as e:
                raise bad(400, f"cannot write {path}: {e.strerror or e}") from None
            mine = [e for e in templates.load_user_templates() if Path(e["path"]) == path]
            if mine:
                raise bad(400, f"saved {path} but it does not load: {mine[0]['error']}")
            engine.log_event("config", f"device {device} saved as user template {name!r} ({path})")
            return JSONResponse({"ok": True, "name": name, "path": str(path)})

        routes += [Route("/api/templates", templates_list),
                   Route("/api/templates/reload", templates_reload, methods=["POST"]),
                   Route("/api/templates/from-device/{device}", template_from_device, methods=["POST"])]

    if on["devices"]:
        def name_free(name: Any, skip_index: Optional[int] = None) -> None:
            if any(device_key_of(d) == name and j != skip_index for j, d in enumerate(device_items())):
                raise bad(409, f"device {name!r} already exists")

        def coerce_key(value: Any) -> Any:
            if ktype is str or isinstance(value, ktype):
                return value
            try:
                return ktype(value)
            except (TypeError, ValueError):
                raise bad(400, f"{device_key}: {value!r} is not a valid {ktype.__name__}") from None

        async def run_hook(fn, *args, **kwargs):
            try:
                return await _call(fn, *args, **kwargs)
            except (TypeError, ValueError, KeyError) as e:
                raise bad(400, e) from None

        def parse_device(data: Any) -> dict:
            if not isinstance(data, dict):
                raise bad(400, "a device is a JSON / YAML object")
            try:
                return dump_item(item_model.model_validate(data))
            except ValueError as e:
                raise bad(400, e) from None

        async def apply_devices(items: list) -> None:
            data = engine.config.model_dump(mode="json", exclude_unset=True, exclude_none=True)
            data[devices_attr] = items
            try:
                cfg = model_cls.model_validate(data)
            except ValueError as e:
                raise bad(400, e) from None
            await apply(cfg, to_yaml(cfg))

        async def device_create(request: Request):
            body = await json_object(request, "a device object")
            if create_hook is not None:
                body = await run_hook(create_hook, engine, body)
            dev = parse_device(body)
            key = dev.get(device_key)
            name_free(key)
            await apply_devices([dump_item(d) for d in device_items()] + [dev])
            engine.log_event("config", f"device {key} added")
            return JSONResponse({"ok": True, "name": key, "device": dev})

        async def device_duplicate(request: Request):
            device = request.path_params["device"]
            _, src = device_or_404(device)
            body = await json_object(request)
            keys = [device_key_of(d) for d in device_items()]
            requested = body.get(device_key)
            if requested in (None, "") and ktype is str:
                requested = body.get("name")
            if requested not in (None, ""):
                name = coerce_key(requested)
            elif ktype is str:
                base, names = str(device_key_of(src)), {str(k) for k in keys}
                name = next(n for n in (f"{base}_copy", *(f"{base}_copy{i}" for i in range(2, 10000)))
                            if n not in names)
            else:
                name = max((k for k in keys if isinstance(k, ktype)), default=0) + 1
            dev = {**dump_item(src), device_key: name}
            if duplicate_hook is not None:
                kw = {"src_key": device_key_of(src)} if _accepts_kw(duplicate_hook, "src_key") else {}
                res = await run_hook(duplicate_hook, engine, dev, name, body, **kw)
                if res is not None:
                    dev = res
            if not isinstance(dev, dict):
                raise bad(400, "duplicate_hook must return a device object")
            name = dev.get(device_key, name)
            name_free(name)
            dev = parse_device(dev)
            name = dev.get(device_key)
            await apply_devices([dump_item(d) for d in device_items()] + [dev])
            engine.log_event("config", f"device {device} duplicated as {name}")
            return JSONResponse({"ok": True, "name": name, "device": dev})

        async def device_delete(request: Request):
            device = request.path_params["device"]
            i, _ = device_or_404(device)
            items = [dump_item(d) for d in device_items()]
            del items[i]
            await apply_devices(items)
            engine.log_event("config", f"device {device} deleted")
            return JSONResponse({"ok": True})

        async def device_config_get(request: Request):
            _, d = device_or_404(request.path_params["device"])
            return yaml_response(yaml.safe_dump(dump_item(d), allow_unicode=True, sort_keys=False))

        async def device_config_put(request: Request):
            device = request.path_params["device"]
            i, old = device_or_404(device)
            try:
                data = yaml.safe_load((await request.body()).decode("utf-8"))
            except yaml.YAMLError as e:
                raise bad(400, f"invalid YAML: {e}") from None
            dev = parse_device(data)
            new = dev.get(device_key)
            name_free(new, skip_index=i)
            items = [dump_item(d) for d in device_items()]
            items[i] = dev
            await apply_devices(items)
            engine.log_event("config", f"device {device} updated"
                                       + (f" (renamed to {new})" if new != device_key_of(old) else ""))
            return JSONResponse({"ok": True, "name": new})

        routes += [Route("/api/devices", device_create, methods=["POST"]),
                   Route("/api/devices/{device}/duplicate", device_duplicate, methods=["POST"]),
                   Route("/api/devices/{device}", device_delete, methods=["DELETE"]),
                   Route("/api/devices/{device}/config", device_config_get, methods=["GET"]),
                   Route("/api/devices/{device}/config", device_config_put, methods=["PUT"])]

    # ---- live updates: first a snapshot, then the engine's messages ("reload" -> a fresh snapshot)

    async def ws_endpoint(sock: WebSocket):
        await sock.accept()
        q = engine.subscribe()
        seen = 0

        def snap() -> dict:
            nonlocal seen
            data = engine.snapshot()
            seen = max((e.get("seq", 0) for e in data.get("events", []) if isinstance(e, dict)), default=seen)
            return {"type": "snapshot", "data": data}

        async def pump() -> None:
            await sock.send_json(snap())
            while True:
                msg = await q.get()
                if msg.get("type") == "reload":
                    msg = snap()
                elif msg.get("type") == "log" and msg.get("event", {}).get("seq", 0) <= seen:
                    continue  # already contained in a snapshot sent after it was logged
                await sock.send_json(msg)

        sender = asyncio.create_task(pump())
        try:
            while True:
                m = await sock.receive()
                if m["type"] == "websocket.disconnect":
                    break
        except (WebSocketDisconnect, RuntimeError):
            pass
        finally:
            sender.cancel()
            with contextlib.suppress(BaseException):
                await sender
            engine.unsubscribe(q)

    routes.append(WebSocketRoute("/ws", ws_endpoint))

    # ---- page

    async def index(request: Request):
        page = static / "index.html" if static is not None else None
        if page is not None and page.is_file():
            html = page.read_text(encoding="utf-8").replace(VERSION_TOKEN, common_version)
            return HTMLResponse(html, headers={"Cache-Control": "no-cache"})
        name = f"{title} {version}" if version else title
        return PlainTextResponse(f"{name}: web UI not built; the REST API is at /api/state")

    routes.append(Route("/", index))

    # APIRouter / Router routes are flattened into app.routes (no include_router wrapper): FastAPI APIRoute
    # objects keep their prefix, dependencies and validation.
    for r in product_routers:
        routes.extend(getattr(r, "routes", None) or [r])

    @asynccontextmanager
    async def lifespan(_app):
        if manage_engine:
            await engine.start()
        try:
            yield
        finally:
            if manage_engine:
                await engine.stop()

    app = FastAPI(title=title, version=version or "0", routes=routes, lifespan=lifespan,
                  exception_handlers={HTTPException: error_response})
    app.state.engine = engine
    app.state.features = on
    mount_common(app)
    if static is not None:
        mount_product_static(app, static)
    return app
