"""Portable Windows entrypoint; preserves the existing Python server verbatim.

PyInstaller bundles the server, scripts/guardian.py, HTML and icons as data.
No elevation, startup task, service, new listener or remote endpoint.
"""
from __future__ import annotations

import os
import sys
import threading
import time
import urllib.request
import webbrowser

from control_center.server import main as server_main


def _port(argv: list[str]) -> int:
    for idx, value in enumerate(argv):
        if value == "--port" and idx + 1 < len(argv):
            try:
                return int(argv[idx + 1])
            except ValueError:
                break
        if value.startswith("--port="):
            try:
                return int(value.split("=", 1)[1])
            except ValueError:
                break
    return 8765


def _open_when_ready(port: int) -> None:
    url = f"http://127.0.0.1:{port}/"
    for _ in range(60):
        try:
            with urllib.request.urlopen(url + "api/health", timeout=0.4) as response:
                if response.status == 200:
                    webbrowser.open(url)
                    return
        except OSError:
            pass
        time.sleep(0.5)


def main() -> None:
    if os.environ.get("GUARDIAN_NO_BROWSER") != "1":
        threading.Thread(target=_open_when_ready, args=(_port(sys.argv[1:]),),
                         name="guardian-browser-opener", daemon=True).start()
    server_main()


if __name__ == "__main__":
    main()
