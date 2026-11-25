import io

import pytest
import yaml
from starlette.responses import PlainTextResponse
from starlette.routing import Route, Router
from starlette.testclient import TestClient

import sme_sim_common
from sme_sim_common.config import parse_text
from sme_sim_common.templates import TemplateRegistry
from sme_sim_common.web import VERSION_TOKEN, make_base_app

from _sim_fixture import YAML, Config, Engine, Point
from test_xlsx import SCHEMA


@pytest.fixture
def env(tmp_path, monkeypatch):
    cfg_file = tmp_path / "site.yaml"
    cfg_file.write_text(YAML, encoding="utf-8")
    static = tmp_path / "static"
    static.mkdir()
    (static / "index.html").write_text(
        f'<script src="/sme-sim-common/shell/shell.js?v={VERSION_TOKEN}" data-common-version="{VERSION_TOKEN}">'
        "</script>", encoding="utf-8")
    (static / "app.js").write_text("// app", encoding="utf-8")
    monkeypatch.setenv("SME_TEST_SIM_TEMPLATES", str(tmp_path / "tpl"))
    reg = TemplateRegistry(Point, app_name="sme-test-sim")
    reg.register("meter", "Meter", {"n": 1}, lambda p: [{"name": f"m{i}"} for i in range(p["n"])])
    engine = Engine(parse_text(YAML, Config), config_text=YAML, config_path=cfg_file)
    router = Router([Route("/api/protocol/ping", lambda r: PlainTextResponse("pong"))])
    app = make_base_app(engine, static_dir=static, product_routers=[router], title="Test Sim", version="9.9",
                        xlsx=SCHEMA, templates=reg)
    with TestClient(app) as client:
        yield client, engine, cfg_file, reg


def test_index_injects_version_and_static(env):
    c, *_ = env
    html = c.get("/").text
    assert VERSION_TOKEN not in html and html.count(sme_sim_common.__version__) == 2
    assert c.get("/static/app.js").text == "// app"
    assert c.get("/sme-sim-common/i18n/common.js").status_code == 200
    assert c.get("/api/protocol/ping").text == "pong"
    assert c.get("/api/version").json() == {"name": "Test Sim", "version": "9.9",
                                            "common_version": sme_sim_common.__version__}


def test_missing_static_falls_back(tmp_path):
    app = make_base_app(Engine(Config()), static_dir=tmp_path / "nope", title="X", manage_engine=False)
    with TestClient(app) as c:
        r = c.get("/")
        assert r.status_code == 200 and "web UI not built" in r.text
        assert c.get("/static/app.js").status_code == 404


def test_state_config_put_and_errors(env):
    c, engine, *_ = env
    assert c.get("/api/state").json()["devices"] == ["pcs1"]
    assert c.get("/api/config").text == YAML
    new = YAML.replace("pcs1", "pcs2")
    assert c.put("/api/config", content=new).json() == {"ok": True}
    assert engine.config_text == new and engine.state.keys() == {"pcs2"}
    r = c.put("/api/config", content="devices: [{name: x, bogus: 1}]")
    assert r.status_code == 400 and "bogus" in r.json()["error"] and r.json()["detail"] == r.json()["error"]
    r = c.put("/api/config", content="devices: [{name: boom}]")  # build failure: old config kept
    assert r.status_code == 400 and "boom" in r.json()["error"] and engine.config_text == new
    assert c.put("/api/config", content="a: [").status_code == 400


def test_save_is_atomic_and_keeps_comments(env, monkeypatch):
    c, engine, cfg_file, _ = env
    text = YAML.replace("pcs1", "pcs9")
    c.put("/api/config", content=text)
    r = c.post("/api/config/save")
    assert r.json() == {"ok": True, "path": str(cfg_file)}
    assert [f.name for f in cfg_file.parent.iterdir() if f.suffix == ".tmp"] == []  # temp file replaced
    saved = cfg_file.read_text(encoding="utf-8")
    assert saved == text and "# site comment" in saved and "# inline comment" in saved


def test_save_without_path(tmp_path):
    app = make_base_app(Engine(Config()), manage_engine=False)
    with TestClient(app) as c:
        r = c.post("/api/config/save")
        assert r.status_code == 400 and "nothing to save" in r.json()["error"]


def test_simulation(env):
    c, engine, *_ = env
    assert c.post("/api/simulation", json={"running": False, "time_scale": 5}).json() == \
        {"running": False, "time_scale": 5.0}
    assert c.post("/api/simulation", json={"time_scale": -1}).status_code == 400
    assert c.post("/api/simulation", content="[1]").status_code == 400


def test_device_crud(env):
    c, engine, *_ = env
    r = c.post("/api/devices", json={"name": "d2", "unit": 2})
    assert r.json()["ok"] and [d.name for d in engine.config.devices] == ["pcs1", "d2"]
    assert c.post("/api/devices", json={"name": "d2"}).status_code == 409
    assert c.post("/api/devices", json={"name": "d3", "nope": 1}).status_code == 400
    r = c.post("/api/devices/pcs1/duplicate", json={})
    assert r.json()["name"] == "pcs1_copy" and r.json()["device"]["points"][0]["value"] == 1.5
    assert c.post("/api/devices/pcs1/duplicate", json={"name": "d2"}).status_code == 409
    assert c.post("/api/devices/nope/duplicate", json={}).status_code == 404
    cfg_yaml = c.get("/api/devices/d2/config").text
    assert yaml.safe_load(cfg_yaml) == {"name": "d2", "unit": 2}
    r = c.put("/api/devices/d2/config", content="name: d2b\nunit: 7\n")
    assert r.json() == {"ok": True, "name": "d2b"}
    assert c.put("/api/devices/d2b/config", content="name: pcs1\n").status_code == 409
    assert c.put("/api/devices/d2b/config", content="name: [").status_code == 400
    assert c.delete("/api/devices/pcs1_copy").json() == {"ok": True}
    assert c.delete("/api/devices/pcs1_copy").status_code == 404
    assert [d.name for d in engine.config.devices] == ["pcs1", "d2b"]
    assert "d2b" in engine.config_text


def test_duplicate_hook(tmp_path):
    def hook(engine, dev, name, body):
        return {**dev, "unit": max(d.unit for d in engine.config.devices) + 1}

    eng = Engine(parse_text(YAML, Config))
    with TestClient(make_base_app(eng, duplicate_hook=hook, manage_engine=False)) as c:
        assert c.post("/api/devices/pcs1/duplicate").json()["device"]["unit"] == 2


def test_templates(env):
    c, engine, _, reg = env
    assert [t["name"] for t in c.get("/api/templates").json()] == ["meter"]
    r = c.post("/api/templates/from-device/pcs1", json={"name": "pcs_tpl"})
    assert r.json()["ok"]
    assert c.post("/api/templates/from-device/pcs1", json={"name": "pcs_tpl"}).status_code == 409
    assert c.post("/api/templates/from-device/zz", json={"name": "x"}).status_code == 404
    assert c.post("/api/templates/from-device/pcs1", json={"name": "bad name!"}).status_code == 400
    body = c.post("/api/templates/reload").json()
    assert body["loaded"] == ["pcs_tpl"] and body["errors"] == []


def test_xlsx_routes(env):
    c, engine, *_ = env
    r = c.get("/api/config/xlsx")
    assert r.status_code == 200 and 'filename="e.xlsx"' in r.headers["content-disposition"]
    assert c.get("/api/config/xlsx-template").status_code == 200
    data = r.content
    r2 = c.post("/api/config/import", files={"file": ("book.xlsx", io.BytesIO(data), "application/octet-stream")})
    assert r2.json() == {"ok": True, "warnings": []} and engine.state == {"pcs1": {"p": 1.5}}
    r3 = c.post("/api/config/import", files={"file": ("x.xlsx", io.BytesIO(b"junk"), "application/octet-stream")})
    assert r3.status_code == 400 and r3.json()["detail"]["errors"] and "1 error(s)" in r3.json()["error"]
    assert c.post("/api/config/import", data={"x": "1"}).status_code == 400


def test_features_off(tmp_path):
    app = make_base_app(Engine(Config()), features={"xlsx": False, "templates": False, "devices": False,
                                                     "simulation": False}, manage_engine=False)
    with TestClient(app) as c:
        for method, url in (("get", "/api/config/xlsx"), ("get", "/api/templates"), ("post", "/api/devices"),
                            ("post", "/api/simulation"), ("get", "/api/devices/x/config")):
            assert getattr(c, method)(url).status_code in (404, 405), url
        assert c.get("/api/state").status_code == 200
    with pytest.raises(ValueError, match="dependency"):
        make_base_app(Engine(Config()), features={"xlsx": True})
    with pytest.raises(ValueError, match="unknown feature"):
        make_base_app(Engine(Config()), features={"faults": True})


def test_ws_snapshot_reload_and_log(env):
    c, engine, *_ = env
    with c.websocket_connect("/ws") as ws:
        first = ws.receive_json()
        assert first["type"] == "snapshot" and first["data"]["devices"] == ["pcs1"]
        c.put("/api/config", content=YAML.replace("pcs1", "zz"))
        msgs = [ws.receive_json() for _ in range(2)]
        types = [m["type"] for m in msgs]
        assert "snapshot" in types  # the reload broadcast is answered with a fresh snapshot
        snap = next(m for m in msgs if m["type"] == "snapshot")
        assert snap["data"]["devices"] == ["zz"]
        c.post("/api/simulation", json={"running": False})
        nxt = ws.receive_json()
        while nxt["type"] != "simulation":
            nxt = ws.receive_json()
        assert nxt == {"type": "simulation", "running": False, "time_scale": 1.0}
    assert engine.subscribers == 0


def test_fastapi_app_and_api_router(env, tmp_path):
    from fastapi import APIRouter, FastAPI

    router = APIRouter()

    @router.get("/api/ping")
    def ping():
        return {"pong": True}

    engine = Engine(parse_text(YAML, Config), config_text=YAML)
    app = make_base_app(engine, product_routers=[router], title="Test Sim")
    assert isinstance(app, FastAPI)
    with TestClient(app) as c:
        assert c.get("/api/ping").json() == {"pong": True}
        assert c.get("/api/version").status_code == 200
