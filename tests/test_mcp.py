import asyncio
import json
import logging

import pytest
from pydantic import BaseModel, Field
from starlette.testclient import TestClient

from sme_sim_common.config import parse_text
from sme_sim_common.mcp_server import McpRegistry, ToolError, asgi_request, register_base_tools
from sme_sim_common.web import bad, make_base_app

from _sim_fixture import YAML, Config, Engine

pytest.importorskip("mcp")
from mcp.client import Client  # noqa: E402

ACCEPT = {"Accept": "application/json, text/event-stream", "MCP-Protocol-Version": "2025-11-25"}


class AddArgs(BaseModel):
    a: int = Field(description="first addend")
    b: int = 0


def make_registry() -> McpRegistry:
    reg = McpRegistry("sme-test-sim", version="9.9")

    @reg.tool(input_schema=AddArgs)
    async def add(args: AddArgs):
        """Add two integers."""
        return {"sum": args.a + args.b}

    reg.register_tool("echo", "Echo a text.", {"type": "object", "properties": {"text": {"type": "string"}},
                                               "required": ["text"]}, lambda args: args["text"])
    reg.register_tool("fail_tool", "Always fails.", None, lambda args: (_ for _ in ()).throw(ToolError("nope")))
    reg.register_tool("fail_http", "HTTP style failure.", None, lambda args: (_ for _ in ()).throw(bad(404, "gone")))

    def boom(args):
        raise RuntimeError("kaboom")

    reg.register_tool("boom", "Unexpected failure.", None, boom)
    return reg


@pytest.fixture
def app_env(tmp_path):
    engine = Engine(parse_text(YAML, Config), config_text=YAML, config_path=tmp_path / "site.yaml")
    app = make_base_app(engine, title="Test Sim", version="9.9")
    reg = make_registry()
    names = register_base_tools(reg, app)
    reg.mount(app)
    with TestClient(app, base_url="http://127.0.0.1") as client:
        yield client, engine, reg, names


def run(coro):
    return asyncio.run(coro)


async def with_client(reg, fn):
    async with Client(reg.server()) as client:
        return await fn(client)


# ---- registration / schema

def test_schema_output():
    reg = make_registry()
    tools = {t["name"]: t for t in reg.list_tools()}
    assert set(tools) == {"add", "echo", "fail_tool", "fail_http", "boom"}
    add = tools["add"]
    assert add["description"] == "Add two integers."
    assert add["inputSchema"]["type"] == "object"
    assert add["inputSchema"]["required"] == ["a"]
    assert add["inputSchema"]["properties"]["a"]["description"] == "first addend"
    assert tools["boom"]["inputSchema"] == {"type": "object", "properties": {}}
    assert tools["echo"]["inputSchema"]["required"] == ["text"]


def test_registration_errors():
    reg = make_registry()
    with pytest.raises(ValueError, match="already registered"):
        reg.register_tool("echo", "again", None, lambda a: a)
    with pytest.raises(ValueError, match="type 'object'"):
        reg.register_tool("x", "x", {"type": "string"}, lambda a: a)
    with pytest.raises(TypeError):
        reg.register_tool("y", "y", 42, lambda a: a)


def test_http_tool_read_only_hint(app_env):
    _, _, reg, names = app_env
    tools = {t["name"]: t for t in reg.list_tools()}
    assert names == ["get_version", "get_state", "export_config", "set_simulation"]
    assert tools["get_state"]["annotations"] == {"readOnlyHint": True}
    assert tools["set_simulation"]["annotations"] == {"destructiveHint": False}
    assert set(tools["set_simulation"]["inputSchema"]["properties"]) == {"running", "time_scale"}


# ---- in-process MCP client (SDK Client connected to the low-level Server)

def test_client_lists_tools():
    res = run(with_client(make_registry(), lambda c: c.list_tools()))
    by_name = {t.name: t for t in res.tools}
    assert by_name["add"].input_schema["required"] == ["a"]
    assert by_name["echo"].description == "Echo a text."


def test_client_call_success():
    res = run(with_client(make_registry(), lambda c: c.call_tool("add", {"a": 2, "b": 3})))
    assert not res.is_error
    assert json.loads(res.content[0].text) == {"sum": 5}
    assert res.structured_content == {"sum": 5}
    res = run(with_client(make_registry(), lambda c: c.call_tool("echo", {"text": "hi"})))
    assert res.content[0].text == "hi" and not res.is_error


@pytest.mark.parametrize("name,args,text", [
    ("fail_tool", {}, "nope"),
    ("fail_http", {}, "gone"),
    ("add", {"a": "not a number"}, "a: "),
    ("boom", {}, "kaboom"),
])
def test_client_call_errors(name, args, text, caplog):
    with caplog.at_level(logging.ERROR, logger="sme_sim_common.mcp"):
        res = run(with_client(make_registry(), lambda c: c.call_tool(name, args)))
    assert res.is_error
    assert text in res.content[0].text
    assert ("MCP tool boom failed" in caplog.text) == (name == "boom")


def test_http_unknown_tool_is_protocol_error(app_env):
    c, *_ = app_env
    err = rpc(c, "tools/call", {"name": "nope", "arguments": {}}).json()["error"]
    assert err["code"] == -32602 and "unknown tool" in err["message"]


# ---- streamable HTTP mounted on the product app

def rpc(client, method, params=None, id_=1, **headers):
    r = client.post("/mcp", json={"jsonrpc": "2.0", "id": id_, "method": method, "params": params or {}},
                    headers={**ACCEPT, **headers})
    return r


def test_http_initialize_and_list(app_env):
    c, *_ = app_env
    r = rpc(c, "initialize", {"protocolVersion": "2025-11-25", "capabilities": {},
                              "clientInfo": {"name": "pytest", "version": "0"}},
            **{"MCP-Protocol-Version": "2025-11-25"})
    assert r.status_code == 200, r.text
    info = r.json()["result"]
    assert info["serverInfo"]["name"] == "sme-test-sim"
    assert "tools" in info["capabilities"]
    r = rpc(c, "tools/list", id_=2)
    assert r.status_code == 200, r.text
    names = [t["name"] for t in r.json()["result"]["tools"]]
    assert {"add", "get_state", "set_simulation"} <= set(names)


def test_http_base_tools_wrap_routes(app_env):
    c, engine, *_ = app_env
    r = rpc(c, "tools/call", {"name": "get_version", "arguments": {}})
    res = r.json()["result"]
    assert not res["isError"]
    assert res["structuredContent"]["name"] == "Test Sim"
    res = rpc(c, "tools/call", {"name": "export_config", "arguments": {}}).json()["result"]
    assert res["content"][0]["text"] == engine.config_text
    res = rpc(c, "tools/call", {"name": "set_simulation", "arguments": {"time_scale": 4}}).json()["result"]
    assert not res["isError"], res
    assert engine.time_scale == 4
    res = rpc(c, "tools/call", {"name": "set_simulation", "arguments": {"time_scale": -1}}).json()["result"]
    assert res["isError"] and res["content"][0]["text"].startswith("HTTP 400")


def test_http_rejects_foreign_host(app_env):
    c, *_ = app_env
    r = c.post("/mcp", json={"jsonrpc": "2.0", "id": 1, "method": "tools/list", "params": {}},
               headers={**ACCEPT, "Host": "evil.example"})
    assert r.status_code in (400, 403, 421)


def test_non_loopback_host_allows_any_host(tmp_path):
    engine = Engine(parse_text(YAML, Config), config_text=YAML)
    app = make_base_app(engine)
    reg = make_registry()
    reg.mount(app, host="0.0.0.0")
    with TestClient(app, base_url="http://sim.lan:8080") as c:
        r = rpc(c, "tools/call", {"name": "echo", "arguments": {"text": "x"}})
        assert r.status_code == 200, r.text
        assert r.json()["result"]["content"][0]["text"] == "x"


def test_mount_survives_lifespan_restart(tmp_path):
    engine = Engine(parse_text(YAML, Config), config_text=YAML)
    app = make_base_app(engine)
    reg = make_registry()
    reg.mount(app)
    for _ in range(2):
        with TestClient(app, base_url="http://127.0.0.1") as c:
            assert rpc(c, "tools/list").status_code == 200


def test_healthz(app_env):
    c, *_ = app_env
    r = c.get("/healthz")
    assert r.status_code == 200
    assert r.json()["status"] == "ok" and r.json()["version"] == "9.9"


def test_asgi_request_and_http_tool_path_params(app_env):
    c, engine, reg, _ = app_env
    app = c.app
    status, headers, body = run(asgi_request(app, "GET", "/api/version"))
    assert status == 200 and headers["content-type"].startswith("application/json")
    reg.register_http_tool("missing", "404 route", "GET", "/api/nothing/{id}")
    res = rpc(c, "tools/call", {"name": "missing", "arguments": {"id": "a b"}}).json()["result"]
    assert res["isError"] and "HTTP 404" in res["content"][0]["text"]
    res = rpc(c, "tools/call", {"name": "missing", "arguments": {}}).json()["result"]
    assert res["isError"] and "missing argument 'id'" in res["content"][0]["text"]


def test_http_tool_decodes_path_params_and_query(tmp_path):
    from starlette.responses import JSONResponse
    from starlette.routing import Route

    async def item(request):
        return JSONResponse({"id": request.path_params["id"], "tags": request.query_params.getlist("tag")})

    engine = Engine(parse_text(YAML, Config), config_text=YAML)
    app = make_base_app(engine, product_routers=[Route("/api/items/{id}", item)])
    reg = McpRegistry("t")
    reg.register_http_tool("item", "one item", "GET", "/api/items/{id}")
    reg.mount(app)
    with TestClient(app, base_url="http://127.0.0.1") as c:
        res = rpc(c, "tools/call", {"name": "item", "arguments": {"id": "a b é", "tag": ["x", "y"],
                                                                  "skip": None}}).json()["result"]
    assert res["structuredContent"] == {"id": "a b é", "tags": ["x", "y"]}, res


def test_dict_schema_is_validated():
    res = run(with_client(make_registry(), lambda c: c.call_tool("echo", {})))
    assert res.is_error and "'text' is a required property" in res.content[0].text
    res = run(with_client(make_registry(), lambda c: c.call_tool("echo", {"text": 3})))
    assert res.is_error and "text: 3 is not of type 'string'" in res.content[0].text


@pytest.mark.parametrize("host,loop", [(None, True), ("127.0.0.2", True), ("[::1]", True), ("LOCALHOST", True),
                                       ("::ffff:127.0.0.1", True), ("0.0.0.0", False), ("sim.lan", False)])
def test_is_loopback(host, loop):
    from sme_sim_common.mcp_server import _is_loopback

    assert _is_loopback(host) is loop
