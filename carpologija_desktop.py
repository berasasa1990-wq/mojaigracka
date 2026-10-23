
import os
import sys
import time
import socket
import signal
import subprocess
import webview

PROJECT = "/Users/bera1990/OnlineShopProject"
PYTHON = os.path.join(PROJECT, "venv", "bin", "python")
PORT = 8765
URL = f"http://127.0.0.1:{PORT}"

def main():
    server = subprocess.Popen(
        [
            PYTHON,
            "manage.py",
            "runserver",
            f"127.0.0.1:{PORT}",
            "--noreload",
        ],
        cwd=PROJECT,
        start_new_session=True,
    )

    try:
        ready = False

        for _ in range(100):
            if server.poll() is not None:
                raise RuntimeError("Django server nije pokrenut.")

            try:
                with socket.create_connection(
                    ("127.0.0.1", PORT), timeout=0.2
                ):
                    ready = True
                    break
            except OSError:
                time.sleep(0.2)

        if not ready:
            raise RuntimeError("Django server nije spreman.")

        webview.create_window(
            "Carpologija Local",
            URL,
            width=1440,
            height=900,
            min_size=(900, 600),
        )

        webview.start(gui="cocoa", debug=False)

    finally:
        if server.poll() is None:
            os.killpg(server.pid, signal.SIGTERM)
            try:
                server.wait(timeout=5)
            except subprocess.TimeoutExpired:
                os.killpg(server.pid, signal.SIGKILL)

if __name__ == "__main__":
    main()
