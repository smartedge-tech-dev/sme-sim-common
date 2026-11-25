import argparse

import pytest

from sme_sim_common import cli


def parser(port=8090):
    return cli.add_common_args(argparse.ArgumentParser(prog="sme-x-sim"), default_http_port=port,
                               app_name="sme-x-sim", version="1.2.3")


def test_defaults_come_from_product():
    a = parser(8090).parse_args([])
    assert (a.config, a.host, a.http_port, a.no_browser, a.verbose, a.templates_dir) == \
        (None, "127.0.0.1", 8090, False, False, None)
    assert parser(8091).parse_args([]).http_port == 8091


def test_all_args_and_port_alias():
    a = parser().parse_args(["-c", "s.yaml", "--host", "0.0.0.0", "--http-port", "9000", "--no-browser", "-v",
                             "--templates-dir", "t"])
    assert (a.config, a.host, a.http_port, a.no_browser, a.verbose, a.templates_dir) == \
        ("s.yaml", "0.0.0.0", 9000, True, True, "t")
    assert parser().parse_args(["--port", "7000"]).http_port == 7000
    assert "--port" not in parser().format_help() and "SME_X_SIM_TEMPLATES" in parser().format_help()


def test_version(capsys):
    with pytest.raises(SystemExit):
        parser().parse_args(["--version"])
    assert "sme-x-sim 1.2.3" in capsys.readouterr().out


def test_run_web(monkeypatch, capsys):
    import uvicorn

    calls, opened = [], []
    monkeypatch.setattr(uvicorn, "run", lambda app, **kw: calls.append((app, kw)))
    monkeypatch.setattr(cli.threading, "Timer", lambda d, fn: type("T", (), {"start": lambda self: fn()})())
    monkeypatch.setattr(cli.webbrowser, "open", opened.append)
    cli.run_web("APP", parser().parse_args([]), name="X")
    assert calls == [("APP", {"host": "127.0.0.1", "port": 8090, "log_level": "warning"})]
    assert opened == ["http://127.0.0.1:8090/"] and "WARNING" not in capsys.readouterr().err
    cli.run_web("APP", parser().parse_args(["--host", "0.0.0.0", "--no-browser"]))
    assert len(opened) == 1 and "WARNING" in capsys.readouterr().err


def test_validate(tmp_path, capsys):
    good = tmp_path / "ok.yaml"
    good.write_text("a: 1\n", encoding="utf-8")
    import yaml

    def load(p):
        return yaml.safe_load(p.read_text(encoding="utf-8"))

    built = []
    assert cli.run_validate([str(good)], prog="x", load=load, build=lambda c, p: built.append(c),
                            summary=lambda c: f"{len(c)} keys") == 0
    assert built == [{"a": 1}] and "OK (1 keys)" in capsys.readouterr().out

    def boom(c, p):
        raise ValueError("bad behavior")

    assert cli.run_validate([str(good)], prog="x", load=load, build=boom) == 2
    assert "bad behavior" in capsys.readouterr().err
    assert cli.run_validate([str(tmp_path / "missing.yaml")], prog="x", load=load) == 2
