"""Command line helpers shared by the simulators (design §7.1).

Generalised from sme-modbus-sim 085fe59 ``__main__.py`` (``--http-port`` / ``--no-browser`` / ``--templates-dir``
/ ``validate``) and sme-bac-sim v0.4.0 ``__main__.py`` (``--port``, kept as a hidden alias).
"""

from __future__ import annotations

import argparse
import sys
import threading
import webbrowser
from pathlib import Path
from typing import Any, Callable, Optional, Sequence

__all__ = ["LOCAL_HOSTS", "add_common_args", "browser_url", "run_web", "add_validate_args", "run_validate"]

LOCAL_HOSTS = ("127.0.0.1", "localhost", "::1")


def add_common_args(ap: argparse.ArgumentParser, *, default_http_port: int, app_name: str,
                    version: Optional[str] = None, templates: bool = True,
                    open_browser: bool = True, log_format: bool = False) -> argparse.ArgumentParser:
    """Add ``-c/--config``, ``--host`` (127.0.0.1), ``--http-port`` (hidden alias ``--port``), ``--no-browser`` /
    ``--browser``, ``--version``, ``-v/--verbose`` and (``templates=True``) ``--templates-dir``. The product passes
    its own default port (series port table in the README); ``app_name`` is the dist name (``sme-modbus-sim``).
    ``open_browser`` is the default of ``args.no_browser`` (inverted): ``False`` = only ``--browser`` opens it.
    ``log_format=True`` adds ``--log-format {text,json}`` (default ``None`` = not given, so a config file value can
    apply; pass the result to :func:`sme_sim_common.logs.setup_logging`)."""
    if version is not None:
        ap.add_argument("--version", action="version", version=f"{app_name} {version}")
    ap.add_argument("-c", "--config", help="YAML / JSON config file")
    ap.add_argument("--host", default="127.0.0.1", help="web UI host (use 0.0.0.0 to expose on the LAN)")
    ap.add_argument("--http-port", dest="http_port", type=int, default=default_http_port,
                    help=f"web UI port (default {default_http_port})")
    ap.add_argument("--port", dest="http_port", type=int, default=argparse.SUPPRESS, help=argparse.SUPPRESS)
    grp = ap.add_mutually_exclusive_group()
    grp.add_argument("--no-browser", dest="no_browser", action="store_true",
                     help="do not open the web UI in a browser" + (" (default)" if not open_browser else ""))
    grp.add_argument("--browser", dest="no_browser", action="store_false",
                     help="open the web UI in a browser" + (" (default)" if open_browser else ""))
    ap.set_defaults(no_browser=not open_browser)
    if templates:
        from .templates import env_var_for

        env = env_var_for(app_name)
        ap.add_argument("--templates-dir",
                        help=f"user template directory (default: ${env} or ~/.{app_name}/templates)")
    ap.add_argument("-v", "--verbose", action="store_true", help="debug logging")
    if log_format:
        from .logs import LOG_FORMATS

        ap.add_argument("--log-format", dest="log_format", choices=LOG_FORMATS, default=None,
                        help="log output: text (default) or json (one JSON object per line)")
    return ap


def browser_url(host: str, port: int) -> str:
    """URL to open locally for a bind address (a wildcard bind is opened on 127.0.0.1)."""
    h = "127.0.0.1" if host in ("0.0.0.0", "::", "") else host
    if ":" in h and not h.startswith("["):
        h = f"[{h}]"
    return f"http://{h}:{port}/"


def run_web(app: Any, args: argparse.Namespace, *, name: Optional[str] = None, delay: float = 1.5) -> None:
    """Serve ``app`` with uvicorn (``log_level="warning"``) on ``args.host`` / ``args.http_port``.

    Prints the URL, warns when the host is not loopback (the UI has no authentication) and opens the browser
    unless ``--no-browser``. With ``args.log_format == "json"`` uvicorn keeps no handlers of its own, so its logs
    go through the root handler of :func:`sme_sim_common.logs.setup_logging` (JSON too)."""
    import uvicorn

    url = browser_url(args.host, args.http_port)
    print(f"{name + ' ' if name else ''}web UI: {url}", flush=True)
    if args.host not in LOCAL_HOSTS:
        print(f"WARNING: the web UI listens on {args.host}, reachable from other hosts; it has no "
              f"authentication. Use --host 127.0.0.1 unless you need LAN access.", file=sys.stderr, flush=True)
    if not getattr(args, "no_browser", False):
        threading.Timer(delay, lambda: webbrowser.open(url)).start()
    extra = {"log_config": None} if getattr(args, "log_format", None) == "json" else {}
    uvicorn.run(app, host=args.host, port=args.http_port, log_level="warning", **extra)


def add_validate_args(ap: argparse.ArgumentParser, *, templates: bool = True) -> argparse.ArgumentParser:
    """Arguments of the ``validate CONFIG`` / ``validate -c CONFIG`` subcommand (``-c`` matches ``run``)."""
    ap.add_argument("config", nargs="?", help="YAML / JSON config file to check")
    ap.add_argument("-c", "--config", dest="config_opt", metavar="CONFIG",
                    help="same as the positional CONFIG (the flag ``run`` uses)")
    if templates:
        ap.add_argument("--templates-dir", help="user template directory")
    return ap


def run_validate(argv: Sequence[str], *, prog: str, load: Callable[[Path], Any],
                 build: Optional[Callable[[Any, Path], Any]] = None,
                 before: Optional[Callable[[argparse.Namespace], None]] = None,
                 summary: Optional[Callable[[Any], str]] = None) -> int:
    """``<prog> validate CONFIG``: ``load(path)`` the config, then ``build(cfg, path)`` once (e.g. construct the
    Engine to compile behaviors). Returns 0 when valid, 2 on a config error (message on stderr).
    ``before(args)`` runs first (e.g. load user templates from ``--templates-dir``)."""
    ap = add_validate_args(argparse.ArgumentParser(prog=f"{prog} validate", description="check a config file"))
    args = ap.parse_args(list(argv))
    if args.config is None and args.config_opt is None:
        ap.error("a config file is required (CONFIG or -c/--config CONFIG)")
    if args.config is not None and args.config_opt is not None and args.config != args.config_opt:
        ap.error(f"conflicting config files: {args.config!r} and -c {args.config_opt!r}")
    args.config = args.config if args.config is not None else args.config_opt
    path = Path(args.config)
    try:
        if before is not None:
            before(args)
        cfg = load(path)
        if build is not None:
            build(cfg, path)
    except Exception as e:  # file, YAML, validation or build error
        print(f"{path}: invalid\n{e}", file=sys.stderr)
        return 2
    print(f"{path}: OK" + (f" ({summary(cfg)})" if summary else ""))
    return 0
