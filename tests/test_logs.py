import argparse
import io
import json
import logging

import pytest

from sme_sim_common import cli
from sme_sim_common.logs import JsonFormatter, setup_logging


@pytest.fixture
def restore_root():
    root = logging.getLogger()
    handlers, level = list(root.handlers), root.level
    yield
    root.handlers[:] = handlers
    root.setLevel(level)


def test_json_format(restore_root):
    buf = io.StringIO()
    setup_logging(log_format="json", stream=buf)
    log = logging.getLogger("sme_test.json")
    log.info("hello %s", "world", extra={"device": "m1", "obj": object()})
    try:
        raise ValueError("bad")
    except ValueError:
        log.exception("failed")
    first, second = (json.loads(line) for line in buf.getvalue().splitlines())
    assert first["level"] == "INFO" and first["logger"] == "sme_test.json"
    assert first["message"] == "hello world" and first["device"] == "m1"
    assert first["ts"].endswith("+00:00") and "obj" in first
    assert second["level"] == "ERROR" and "ValueError: bad" in second["exc"]


def test_text_format_and_level(restore_root):
    buf = io.StringIO()
    setup_logging(verbose=True, stream=buf)
    setup_logging(verbose=True, log_format=None, stream=buf)  # replaces, does not duplicate
    assert logging.getLogger().level == logging.DEBUG and len(logging.getLogger().handlers) == 1
    logging.getLogger("sme_test.text").debug("dbg")
    assert buf.getvalue().rstrip().endswith("DEBUG sme_test.text: dbg")
    with pytest.raises(ValueError, match="unknown log format"):
        setup_logging(log_format="xml", stream=buf)


def test_json_formatter_is_one_line():
    rec = logging.LogRecord("x", logging.WARNING, __file__, 1, "a\nb", None, None)
    assert "\n" not in JsonFormatter().format(rec)


def test_cli_log_format_flag(monkeypatch):
    ap = cli.add_common_args(argparse.ArgumentParser(), default_http_port=1, app_name="sme-x", log_format=True)
    assert ap.parse_args([]).log_format is None
    assert ap.parse_args(["--log-format", "json"]).log_format == "json"
    plain = cli.add_common_args(argparse.ArgumentParser(), default_http_port=1, app_name="sme-x")
    assert not hasattr(plain.parse_args([]), "log_format")

    calls = []
    import uvicorn
    monkeypatch.setattr(uvicorn, "run", lambda app, **kw: calls.append(kw))
    args = ap.parse_args(["--log-format", "json", "--no-browser"])
    cli.run_web(object(), args)
    args = ap.parse_args(["--no-browser"])
    cli.run_web(object(), args)
    assert calls[0]["log_config"] is None and "log_config" not in calls[1]
