"""Launch a disposable local server and execute the optional Playwright UI suite."""

import os
from pathlib import Path
import socket
import subprocess
import sys
import time
from urllib.request import urlopen


def main():
    root = Path(__file__).resolve().parents[1]
    (root / "runs").mkdir(exist_ok=True)
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    server = subprocess.Popen(
        [sys.executable, "-B", "ui/server.py"], cwd=root,
        env=dict(os.environ, PORT=str(port)),
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )
    try:
        for _ in range(100):
            try:
                with urlopen(f"http://127.0.0.1:{port}/healthz", timeout=1):
                    break
            except OSError:
                if server.poll() is not None:
                    raise RuntimeError("Web server exited during startup") from None
                time.sleep(0.1)
        else:
            raise RuntimeError("Web server did not start")
        return subprocess.run(
            [os.environ.get("NODE_BIN", "node"), "tools/check_web_ui.cjs"], cwd=root,
            env=dict(os.environ, BASE_URL=f"http://127.0.0.1:{port}"), timeout=120,
        ).returncode
    finally:
        server.terminate()
        server.wait(timeout=10)


if __name__ == "__main__":
    sys.exit(main())
