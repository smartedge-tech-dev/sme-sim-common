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

__all__ = ["COMMON_PREFIX", "STATIC_DIR", "VERSION_TOKEN", "FEATURES", "mount_common", "mount_product_static",
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
    shape the existing UIs read; ``error`` is the design §7.2 field."""
    from starlette.responses import JSONResponse, Response

    if exc.status_code in (204, 304):
        return Response(status_code=exc.status_code, headers=exc.headers)
    detail = exc.detail
    msg = detail.get("message", "") if isinstance(detail, dict) else str(detail)
    return JSONResponse({"detail": detail, "error": msg}, status_code=exc.status_code, headers=exc.headers)


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


def make_base_app(engine, *, config_path: Optional[Union[str, Path]] = None,
                  static_dir: Optional[Union[str, Path]] = None, product_routers=(),
                  features: Optional[dict] = None, title: str = "SME Sim", version: Optional[str] = None,
                  config_model: Optional[type] = None, xlsx=None, templates=None,
                  devices_attr: str = "devices", device_key: str = "name", device_model: Optional[type] = None,
                  duplicate_hook=None, manage_engine: bool = True):
    """FastAPI app with the standard routes; the product adds its protocol routes through ``product_routers``
    (FastAPI ``APIRouter`` objects, Starlette ``Router`` objects, or plain route objects; matched before the mounts).

    ``engine`` follows :class:`sme_sim_common.engine.EngineProtocol`. Always present: ``GET /``, ``/static``
    (when ``static_dir`` exists), ``/sme-sim-common``, ``GET /api/version``, ``GET /api/state``,
    ``GET|PUT /api/config`` (YAML text), ``POST /api/config/save`` (``engine.config_text`` written atomically),
    ``WS /ws``. Per feature:

    * ``xlsx`` (needs ``xlsx=XlsxSchema``): ``GET /api/config/xlsx``, ``GET /api/config/xlsx-template``,
      ``POST /api/config/import`` (multipart field ``file``)
    * ``templates`` (needs ``templates=TemplateRegistry``): ``GET /api/templates``, ``POST /api/templates/reload``,
      ``POST /api/templates/from-device/{device}``
    * ``devices`` (a device = one item of the config's top-level list ``devices_attr``, identified by
      ``device_key``): ``POST /api/devices``, ``POST /api/devices/{name}/duplicate``, ``DELETE /api/devices/{name}``,
      ``GET|PUT /api/devices/{name}/config``. Edits re-dump the config (``exclude_unset``; comments are lost) and
      reload it. ``duplicate_hook(engine, dev: dict, new_name, body: dict) -> dict`` adjusts the copy (e.g. a
      free Modbus unit id).
    * ``simulation`` (engine has ``set_running``): ``POST /api/simulation`` ``{"running", "time_scale"}``

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
            try:
                engine.set_running(body.get("running"), body.get("time_scale"))
            except (TypeError, ValueError) as e:
                raise bad(400, e) from None
            return JSONResponse({"running": getattr(engine, "running", None),
                                 "time_scale": getattr(engine, "time_scale", None)})

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

        async def config_import(request: Request):
            form = await request.form()
            file = form.get("file")
            if not isinstance(file, UploadFile):
                raise bad(400, "multipart field 'file' (the .xlsx workbook) is required")
            cfg, msgs = xlsx.import_xlsx(await file.read(), engine.config)
            if cfg is None:
                raise bad(400, f"{len(msgs)} error(s) in {file.filename or 'the workbook'}", errors=msgs)
            try:
                await engine.reload(cfg, to_yaml(cfg))
            except Exception as e:
                raise bad(400, "the imported configuration cannot be applied", errors=[str(e)]) from None
            engine.log_event("config", f"Excel workbook imported ({file.filename})")
            return JSONResponse({"ok": True, "warnings": msgs})

        routes += [Route("/api/config/xlsx", config_xlsx),
                   Route("/api/config/xlsx-template", config_xlsx_template),
                   Route("/api/config/import", config_import, methods=["POST"])]

    # ---- devices (= items of the top-level list ``devices_attr``)

    def device_items() -> list:
        return list(getattr(engine.config, devices_attr, None) or [])

    def device_key_of(d) -> Any:
        return d.get(device_key) if isinstance(d, dict) else getattr(d, device_key, None)

    def device_or_404(name: str):
        for i, d in enumerate(device_items()):
            if str(device_key_of(d)) == name:
                return i, d
        raise bad(404, f"unknown device {name!r}")

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
        def name_free(name: Any, skip: Optional[str] = None) -> None:
            if any(device_key_of(d) == name and str(device_key_of(d)) != skip for d in device_items()):
                raise bad(409, f"device {name!r} already exists")

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
            dev = parse_device(await json_object(request, "a device object"))
            name_free(dev.get(device_key))
            await apply_devices([dump_item(d) for d in device_items()] + [dev])
            engine.log_event("config", f"device {dev.get(device_key)} added")
            return JSONResponse({"ok": True, "name": dev.get(device_key), "device": dev})

        async def device_duplicate(request: Request):
            device = request.path_params["device"]
            _, src = device_or_404(device)
            body = await json_object(request)
            names = {str(device_key_of(d)) for d in device_items()}
            name = body.get("name") or next(
                n for n in (f"{device}_copy", *(f"{device}_copy{i}" for i in range(2, 10000))) if n not in names)
            name_free(name)
            dev = {**dump_item(src), device_key: name}
            if duplicate_hook is not None:
                dev = duplicate_hook(engine, dev, name, body)
            dev = parse_device(dev)
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
            i, _ = device_or_404(device)
            try:
                data = yaml.safe_load((await request.body()).decode("utf-8"))
            except yaml.YAMLError as e:
                raise bad(400, f"invalid YAML: {e}") from None
            dev = parse_device(data)
            name_free(dev.get(device_key), skip=device)
            items = [dump_item(d) for d in device_items()]
            items[i] = dev
            await apply_devices(items)
            new = dev.get(device_key)
            engine.log_event("config", f"device {device} updated"
                                       + (f" (renamed to {new})" if str(new) != device else ""))
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

    from fastapi import APIRouter

    api_routers = [r for r in product_routers if isinstance(r, APIRouter)]
    for r in product_routers:
        if not isinstance(r, APIRouter):
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
    for r in api_routers:
        app.include_router(r)
    app.state.engine = engine
    app.state.features = on
    mount_common(app)
    if static is not None:
        mount_product_static(app, static)
    return app
