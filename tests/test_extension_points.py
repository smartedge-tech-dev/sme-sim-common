"""Extension points added before 1.0.0 for the BACnetSim / ModbusSim migrations."""

import argparse
import asyncio
import io
import logging
import threading
import typing
from pathlib import Path
from typing import List, Optional, Union

import pytest
from starlette.testclient import TestClient

from sme_sim_common import cli
from sme_sim_common.config import StrictModel, parse_text
from sme_sim_common.engine import BaseEngine, EngineProtocol
from sme_sim_common.web import STATIC_DIR, make_base_app

from _sim_fixture import YAML, Config, Engine
from test_xlsx import SCHEMA


# ---------------------------------------------------------------- an int-keyed product (BACnet-like)

class IntDev(StrictModel):
    device_id: int
    name: str = ""


class IntCfg(StrictModel):
    devices: List[IntDev] = []


class IntEngine(BaseEngine):
    def _build(self, config):
        ids = [d.device_id for d in config.devices]
        if len(ids) != len(set(ids)):
            raise ValueError("duplicate device_id")
        return ids

    def snapshot(self):
        return {"devices": list(self.state)}


def free_id(engine, body):
    if not body.get("device_id"):
        used = {d.device_id for d in engine.config.devices}
        n = 1001
        while n in used:
            n += 1
        body = {**body, "device_id": n}
    return body


def int_client(**kw):
    eng = IntEngine(IntCfg(devices=[IntDev(device_id=7, name="a")]))
    return eng, TestClient(make_base_app(eng, device_key="device_id", manage_engine=False, **kw))


def test_int_key_inferred_and_create_hook():
    eng, c = int_client(create_hook=free_id)
    with c:
        r = c.post("/api/devices", json={"name": "b"})
        assert r.json()["name"] == 1001 and r.json()["device"] == {"device_id": 1001, "name": "b"}
        assert c.post("/api/devices", json={}).json()["name"] == 1002
        assert c.post("/api/devices", json={"device_id": 7}).status_code == 409
        assert "name: a" in c.get("/api/devices/7/config").text
        assert c.get("/api/devices/abc/config").status_code == 404
        assert c.get("/api/devices/8/config").status_code == 404
        r = c.put("/api/devices/7/config", content="device_id: 7\nname: renamed\n")
        assert r.json() == {"ok": True, "name": 7} and "renamed to" not in eng.events[-1]["message"]
        assert c.put("/api/devices/7/config", content="device_id: 1001\n").status_code == 409
        assert c.delete("/api/devices/1002").json() == {"ok": True}
        assert [d.device_id for d in eng.config.devices] == [7, 1001]


def test_int_key_duplicate_default_and_explicit():
    eng, c = int_client()
    with c:
        assert c.post("/api/devices/7/duplicate").json()["name"] == 8  # max + 1
        assert c.post("/api/devices/7/duplicate", json={"device_id": "50"}).json()["name"] == 50
        assert c.post("/api/devices/7/duplicate", json={"device_id": 8}).status_code == 409
        assert c.post("/api/devices/7/duplicate", json={"device_id": "x"}).status_code == 400
        assert [d.device_id for d in eng.config.devices] == [7, 8, 50]


def test_duplicate_hook_runs_before_free_check_and_sets_key():
    seen = []

    def hook(engine, dev, new_key, body):
        seen.append(new_key)
        return {**dev, "device_id": 5000, "name": dev["name"] + "-copy"}

    eng, c = int_client(duplicate_hook=hook)
    with c:
        r = c.post("/api/devices/7/duplicate", json={"device_id": 7})  # taken, but the hook re-keys it
        assert r.status_code == 200 and r.json()["name"] == 5000 and r.json()["device"]["name"] == "a-copy"
        assert seen == [7]


def test_explicit_key_type_and_str_duplicate_hook():
    def hook(engine, dev, name, body):  # rename a taken requested name
        return {**dev, "name": f"{name}_new"} if name == "pcs1" else dev

    eng = Engine(parse_text(YAML, Config))
    with TestClient(make_base_app(eng, key_type=str, duplicate_hook=hook, manage_engine=False)) as c:
        assert c.post("/api/devices/pcs1/duplicate", json={"name": "pcs1"}).json()["name"] == "pcs1_new"
        assert c.post("/api/devices/pcs1/duplicate").json()["name"] == "pcs1_copy"


# ---------------------------------------------------------------- simulation_hook

def test_simulation_hook():
    calls = []

    async def hook(engine, rest):
        if rest.get("set_time") == "bad":
            raise ValueError("set_time: not ISO 8601")
        calls.append(rest)
        return {"sim_time": rest.get("set_time")}

    eng = Engine(parse_text(YAML, Config))
    with TestClient(make_base_app(eng, simulation_hook=hook, manage_engine=False)) as c:
        n = len(eng.events)
        r = c.post("/api/simulation", json={"set_time": "2026-01-01T00:00:00"})
        assert r.json() == {"running": True, "time_scale": 1.0, "sim_time": "2026-01-01T00:00:00"}
        assert len(eng.events) == n  # set_running skipped: no standard field given
        r = c.post("/api/simulation", json={"running": False, "set_time": "t"})
        assert r.json() == {"running": False, "time_scale": 1.0, "sim_time": "t"}
        assert calls == [{"set_time": "2026-01-01T00:00:00"}, {"set_time": "t"}]
        assert c.post("/api/simulation", json={"set_time": "bad"}).status_code == 400


# ---------------------------------------------------------------- import_hooks + error body

def test_import_hooks_dispatch_and_warning_log():
    got = {}

    def yaml_import(engine, files):
        got.update(files)
        text = next(iter(files.values())).decode("utf-8")
        return parse_text(text, Config), [f"w{i}" for i in range(1, 8)], text

    def csv_import(engine, files):
        return None, ["row 2: bad"]

    def zip_import(engine, files):
        raise ValueError("not a zip file")

    eng = Engine(parse_text(YAML, Config))
    app = make_base_app(eng, xlsx=SCHEMA, manage_engine=False,
                        import_hooks={".yaml": yaml_import, "csv": csv_import, ".ZIP": zip_import})
    with TestClient(app) as c:
        text = YAML.replace("pcs1", "imp1")
        r = c.post("/api/config/import", files=[("file", ("site.YAML", io.BytesIO(text.encode()), "text/yaml")),
                                                 ("file", ("extra.yaml", io.BytesIO(b"x"), "text/yaml"))])
        assert r.json()["ok"] and len(r.json()["warnings"]) == 7
        assert eng.config_text == text and list(got) == ["site.YAML", "extra.yaml"]
        msg = eng.events[-1]["message"]
        assert "7 warning(s)" in msg and "w5" in msg and "w6" not in msg and "site.YAML" in msg
        r = c.post("/api/config/import", files={"file": ("ede.csv", io.BytesIO(b"x"), "text/csv")})
        assert r.status_code == 400 and r.json()["errors"] == ["row 2: bad"] == r.json()["detail"]["errors"]
        r = c.post("/api/config/import", files={"file": ("ede.zip", io.BytesIO(b"x"), "application/zip")})
        assert r.status_code == 400 and "not a zip" in r.json()["error"] and "errors" not in r.json()
        # anything else still goes to the XlsxSchema
        r = c.post("/api/config/import", files={"file": ("book.xlsx", io.BytesIO(b"junk"), "x")})
        assert r.status_code == 400 and r.json()["errors"]
        data = c.get("/api/config/xlsx").content
        r = c.post("/api/config/import", files={"file": ("book.xlsx", io.BytesIO(data), "x")})
        assert r.json() == {"ok": True, "warnings": []}
        assert eng.events[-1]["message"] == "Excel workbook imported (book.xlsx)"


def test_import_hooks_without_xlsx():
    eng = Engine(parse_text(YAML, Config))
    hooks = {".json": lambda engine, files: (parse_text(YAML, Config), [])}
    with TestClient(make_base_app(eng, import_hooks=hooks, manage_engine=False)) as c:
        assert c.get("/api/config/xlsx").status_code in (404, 405)
        ok = c.post("/api/config/import", files={"file": ("a.json", io.BytesIO(b"{}"), "application/json")})
        assert ok.json() == {"ok": True, "warnings": []}
        r = c.post("/api/config/import", files={"file": ("a.txt", io.BytesIO(b"x"), "text/plain")})
        assert r.status_code == 400 and ".json" in r.json()["error"]


# ---------------------------------------------------------------- APIRouter flattening

def test_api_router_routes_are_flattened():
    from fastapi import APIRouter, Depends
    from fastapi.routing import APIRoute

    def token() -> str:
        return "t0"

    router = APIRouter(prefix="/api/bacnet")

    @router.get("/devices/{device_id}")
    def get_dev(device_id: int, tok: str = Depends(token)):
        return {"id": device_id, "tok": tok}

    eng = Engine(parse_text(YAML, Config))
    app = make_base_app(eng, product_routers=[router], manage_engine=False)
    mine = [r for r in app.routes if getattr(r, "endpoint", None) is get_dev]
    assert len(mine) == 1 and isinstance(mine[0], APIRoute) and mine[0].path == "/api/bacnet/devices/{device_id}"
    with TestClient(app) as c:
        assert c.get("/api/bacnet/devices/3").json() == {"id": 3, "tok": "t0"}
        assert c.get("/api/bacnet/devices/x").status_code == 422


# ---------------------------------------------------------------- i18n / CLI

def test_export_xlsx_string_in_three_languages():
    js = (STATIC_DIR / "i18n" / "common.js").read_text(encoding="utf-8")
    for text in ("Export Excel workbook (.xlsx)", "Excel ブック（.xlsx）をエクスポート", "导出 Excel 工作簿（.xlsx）"):
        assert f'"common.config.export_xlsx": "{text}"' in js


def test_cli_open_browser_default():
    def p(**kw):
        return cli.add_common_args(argparse.ArgumentParser(), default_http_port=1, app_name="sme-x-sim", **kw)

    assert p().parse_args([]).no_browser is False
    assert p().parse_args(["--no-browser"]).no_browser is True
    assert p(open_browser=False).parse_args([]).no_browser is True
    assert p(open_browser=False).parse_args(["--browser"]).no_browser is False
    with pytest.raises(SystemExit):
        p().parse_args(["--browser", "--no-browser"])


# ---------------------------------------------------------------- engine

def test_config_path_type_and_logger(caplog):
    assert typing.get_type_hints(EngineProtocol)["config_path"] == Union[str, Path, None]

    class Named(Engine):
        logger_name = "sme_x_sim.engine"

    e = Named(Config(), config_path="site.yaml")
    assert e.config_path == Path("site.yaml") and e.logger.name == "sme_x_sim.engine"
    assert Engine(Config()).logger.name == "sme_sim_common.engine"
    with caplog.at_level(logging.INFO, logger="sme_x_sim.engine"):
        e.log_event("warning", "hello")
    assert [(r.name, r.levelno, r.message) for r in caplog.records] == [("sme_x_sim.engine", logging.WARNING, "hello")]


def test_wake_runs_on_tick_without_advancing_time():
    class W(Engine):
        def __init__(self, *a, **k):
            self.on_ticks = 0
            super().__init__(*a, **k)

        def _on_tick(self):
            self.on_ticks += 1

    async def main():
        e = W(parse_text(YAML, Config))
        e.wake()  # not started: no-op
        e.tick_seconds = 0.3
        await e.start()
        await asyncio.sleep(0.05)
        assert (e.on_ticks, len(e.steps)) == (1, 1)  # the first tick
        t = threading.Thread(target=e.wake)
        t.start()
        t.join()
        await asyncio.sleep(0.05)
        assert (e.on_ticks, len(e.steps)) == (2, 1)  # scanned, simulated time unchanged
        e.wake()
        e.wake()  # coalesced
        await asyncio.sleep(0.1)  # t ~ 0.2
        assert (e.on_ticks, len(e.steps)) == (3, 1)
        await asyncio.sleep(0.2)  # t ~ 0.4: the regular tick at 0.3 kept its schedule
        assert len(e.steps) == 2 and e.on_ticks == 4
        await e.stop()
        e.wake()  # after stop: harmless

    asyncio.run(main())


# ---------------------------------------------------------------- duplicate_hook src_key / 404 text

def test_duplicate_hook_gets_src_key():
    calls = []

    def hook(engine, dev, new_key, body, *, src_key):  # first free key after the source
        calls.append((src_key, new_key, dict(dev)))
        used, n = {d.device_id for d in engine.config.devices}, src_key + 1
        while n in used:
            n += 1
        return {**dev, "device_id": n}

    eng, c = int_client(duplicate_hook=hook)
    with c:
        for k in (100, 8):
            c.post("/api/devices", json={"device_id": k, "name": f"d{k}"})
        assert c.post("/api/devices/7/duplicate").json()["name"] == 9  # not 101 (largest + 1)
        assert calls == [(7, 101, {"device_id": 101, "name": "a"})]  # dev = copy with the default key
        assert [(d.device_id, d.name) for d in eng.config.devices][0] == (7, "a")  # source unchanged

    seen = []
    eng, c = int_client(duplicate_hook=lambda e, d, k, b, **kw: seen.append(kw) or d)
    with c:
        assert c.post("/api/devices/7/duplicate").json()["name"] == 8 and seen == [{"src_key": 7}]


def test_unknown_device_404_text():
    eng, c = int_client()
    with c:
        r = c.get("/api/devices/1008/config")
        assert r.status_code == 404 and "unknown device 1008" in r.text and "'1008'" not in r.text
        assert "unknown device 'abc'" in c.get("/api/devices/abc/config").text  # not convertible: as typed
    eng = Engine(parse_text(YAML, Config))
    with TestClient(make_base_app(eng, key_type=str, manage_engine=False)) as c:
        assert "unknown device 'nope'" in c.delete("/api/devices/nope").text
