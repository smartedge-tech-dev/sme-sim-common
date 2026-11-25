"""PyInstaller smoke app for sme-sim-common (not collected by pytest).

Mounts the common static files, starts uvicorn on a free localhost port in a background thread,
requests /sme-sim-common/shell/shell.js once and exits 0 on HTTP 200 (1 otherwise).
Built by .github/workflows/ci.yml (job pyinstaller-smoke) with tests/pyinstaller_smoke/smoke.spec.
"""
import socket
import sys
import threading
import time
import urllib.request

import uvicorn
from fastapi import FastAPI

from sme_sim_common.web import COMMON_PREFIX, mount_common

app = FastAPI()
mount_common(app)


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def main() -> int:
    port = _free_port()
    # Pass the app object (not an import string); uvicorn still resolves its loop / protocol
    # implementations by name, which is what the PyInstaller hook has to collect.
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning"))
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    deadline = time.monotonic() + 30
    while not server.started:
        if not thread.is_alive() or time.monotonic() > deadline:
            print("smoke: server did not start", file=sys.stderr)
            return 1
        time.sleep(0.1)
    url = f"http://127.0.0.1:{port}{COMMON_PREFIX}/shell/shell.js"
    try:
        with urllib.request.urlopen(url, timeout=10) as resp:
            status, body = resp.status, resp.read()
    except Exception as exc:  # noqa: BLE001 - report any failure as a smoke failure
        print(f"smoke: GET {url} failed: {exc!r}", file=sys.stderr)
        status, body = 0, b""
    finally:
        server.should_exit = True
        thread.join(timeout=10)
    ok = status == 200 and b"Shell" in body
    print(f"smoke: GET {url} -> {status}, {len(body)} bytes, {'OK' if ok else 'FAIL'}")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
