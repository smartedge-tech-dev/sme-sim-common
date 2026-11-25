"""Web helpers shared by the simulators: mounting the common static assets and the product's own static
directory, and turning exceptions into HTTP errors."""

from __future__ import annotations

from pathlib import Path
from typing import Union

from pydantic import ValidationError
from starlette.exceptions import HTTPException
from starlette.staticfiles import StaticFiles

__all__ = ["COMMON_PREFIX", "STATIC_DIR", "mount_common", "mount_product_static", "bad"]

#: URL prefix of the shared assets. Deliberately not nested under the product's ``/static`` (Starlette matches
#: mounts in registration order, so a nested path would be swallowed by the product mount).
COMMON_PREFIX = "/sme-sim-common"
#: On-disk location of the shared assets (shell/, brand/, vendor/, i18n/).
STATIC_DIR = Path(__file__).resolve().parent / "static"


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


def bad(status: int, msg: Union[str, BaseException]) -> HTTPException:
    """Build an ``HTTPException`` (``raise bad(400, e)``). A pydantic ``ValidationError`` becomes a compact
    ``"loc: message; ..."`` text without the ``Value error, `` prefix; other exceptions use ``str(e)``."""
    if isinstance(msg, ValidationError):
        parts = []
        for err in msg.errors():
            loc, text = ".".join(str(x) for x in err["loc"]), str(err["msg"]).removeprefix("Value error, ")
            parts.append(f"{loc}: {text}" if loc else text)
        detail = "; ".join(parts)
    else:
        detail = str(msg)
    return HTTPException(status_code=status, detail=detail)


# make_base_app: implemented in batch 3
