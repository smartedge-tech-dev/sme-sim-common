import pytest
from pydantic import ValidationError
from starlette.applications import Starlette
from starlette.responses import PlainTextResponse
from starlette.routing import Route
from starlette.testclient import TestClient

from sme_sim_common.config import StrictModel
from sme_sim_common.web import COMMON_PREFIX, STATIC_DIR, bad, mount_common, mount_product_static


def _app(tmp_path, product_first):
    static = tmp_path / "static"
    (static / "shell").mkdir(parents=True)
    (static / "app.js").write_text("// product", encoding="utf-8")
    (static / "shell" / "shell.js").write_text("// product shell", encoding="utf-8")
    app = Starlette(routes=[Route("/api/ping", lambda r: PlainTextResponse("pong"))])
    if product_first:
        assert mount_product_static(app, static)
        mount_common(app)
    else:
        mount_common(app)
        assert mount_product_static(app, static)
    return TestClient(app)


@pytest.mark.parametrize("product_first", [False, True])
def test_common_and_product_static(tmp_path, product_first):
    c = _app(tmp_path, product_first)
    for path in ("shell/shell.js", "shell/shell.css", "vendor/vendor.js", "i18n/common.js", "brand/company-logo.svg"):
        r = c.get(f"{COMMON_PREFIX}/{path}")
        assert r.status_code == 200, path
        assert r.content == (STATIC_DIR / path).read_bytes()
    assert c.get("/static/app.js").text == "// product"
    assert c.get("/static/shell/shell.js").text == "// product shell"  # no clash with the common shell
    assert c.get("/api/ping").text == "pong"
    assert c.get(f"{COMMON_PREFIX}/nope.js").status_code == 404


def test_missing_product_static_is_skipped(tmp_path):
    app = Starlette()
    assert mount_product_static(app, tmp_path / "missing") is False
    assert app.routes == []


class M(StrictModel):
    port: int


def test_bad():
    e = bad(404, "no such device")
    assert (e.status_code, e.detail) == (404, "no such device")
    try:
        M.model_validate({"port": "x", "junk": 1})
    except ValidationError as ve:
        e = bad(400, ve)
    assert e.status_code == 400
    assert e.detail.startswith("port: ") and "; junk: " in e.detail
    assert bad(400, ValueError("boom")).detail == "boom"
