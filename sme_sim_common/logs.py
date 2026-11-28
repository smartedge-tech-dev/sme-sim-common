"""Logging setup shared by the simulators: the plain text format the products used so far, or one JSON object per
line (``log_format: json``) for log collectors (Docker, Loki, Azure Monitor ...).

``setup_logging(verbose=args.verbose, log_format=args.log_format)`` replaces the product's
``logging.basicConfig(...)`` call; :func:`sme_sim_common.cli.add_common_args` (``log_format=True``) adds the
``--log-format {text,json}`` flag and :func:`sme_sim_common.cli.run_web` routes uvicorn's own logs through the
same handler when the format is ``json``.
"""

from __future__ import annotations

import datetime as _dt
import json
import logging
import sys
from typing import Any, Optional, TextIO

__all__ = ["LOG_FORMATS", "TEXT_FORMAT", "JsonFormatter", "setup_logging"]

#: Accepted values of ``log_format``.
LOG_FORMATS = ("text", "json")
#: The text format of the existing products (``2026-11-28 10:00:00,123 INFO sme_ocpp_sim.engine: ...``).
TEXT_FORMAT = "%(asctime)s %(levelname)s %(name)s: %(message)s"

# Attributes every LogRecord has; anything else on a record came from ``extra={...}`` and is emitted as a field.
_STD_ATTRS = frozenset(vars(logging.LogRecord("", 0, "", 0, "", None, None))) | {"message", "asctime", "taskName"}


class JsonFormatter(logging.Formatter):
    """One JSON object per record: ``ts`` (ISO 8601 UTC), ``level``, ``logger``, ``message``, ``exc`` (traceback,
    when there is one) and every ``extra={...}`` field (an extra named like a fixed key is dropped). Values
    that are not JSON serialisable are written with ``str()``."""

    def format(self, record: logging.LogRecord) -> str:
        out: dict[str, Any] = {
            "ts": _dt.datetime.fromtimestamp(record.created, _dt.timezone.utc).isoformat(timespec="milliseconds"),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        for k, v in vars(record).items():
            if k not in _STD_ATTRS and not k.startswith("_") and k not in out:
                out[k] = v
        if record.exc_info:
            out["exc"] = self.formatException(record.exc_info)
        elif record.exc_text:
            out["exc"] = record.exc_text
        if record.stack_info:
            out["stack"] = self.formatStack(record.stack_info)
        try:
            return json.dumps(out, ensure_ascii=False, default=str)
        except (TypeError, ValueError):  # non-str dict keys, circular references in an extra value
            return json.dumps({k: v if isinstance(v, (str, int, float, bool, type(None))) else repr(v)
                               for k, v in out.items()}, ensure_ascii=False)


def setup_logging(*, verbose: bool = False, log_format: Optional[str] = "text", level: Optional[int] = None,
                  stream: Optional[TextIO] = None, fmt: str = TEXT_FORMAT) -> logging.Handler:
    """Configure the root logger with one stream handler (stdout by default) and return it. ``level`` defaults
    to ``DEBUG`` with ``verbose`` else ``INFO``. ``log_format`` is ``"text"`` (``fmt``) or ``"json"``
    (:class:`JsonFormatter`); ``None`` = ``"text"``. Existing root handlers are replaced, so calling it twice
    (e.g. once more after the config file was read) is safe. An unknown format is a ``ValueError``."""
    log_format = (log_format or "text").lower()
    if log_format not in LOG_FORMATS:
        raise ValueError(f"unknown log format {log_format!r}; expected one of {list(LOG_FORMATS)}")
    handler = logging.StreamHandler(stream if stream is not None else sys.stdout)
    handler.setFormatter(JsonFormatter() if log_format == "json" else logging.Formatter(fmt))
    root = logging.getLogger()
    for h in list(root.handlers):
        root.removeHandler(h)
    root.addHandler(handler)
    root.setLevel(level if level is not None else (logging.DEBUG if verbose else logging.INFO))
    return handler
