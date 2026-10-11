from __future__ import annotations

import json
import os
import subprocess
import sys
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import urlsplit


class Handler(BaseHTTPRequestHandler):
    def _respond(self, status: int, payload: bytes, content_type: str = "application/json") -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(payload)))
        if urlsplit(self.path).path == "/cookies":
            self.send_header("Set-Cookie", "rf_secret=discard; Path=/; HttpOnly")
            self.send_header("Set-Cookie", "preview_ok=keep; Path=/")
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(payload)

    def do_GET(self) -> None:
        if urlsplit(self.path).path == "/__pid":
            payload = json.dumps({"pid": os.getpid(), "child_pid": CHILD_PID}).encode()
        elif urlsplit(self.path).path == "/headers":
            payload = json.dumps(
                {
                    "cookie": self.headers.get("cookie", ""),
                    "tailscale": self.headers.get("tailscale-user-login", ""),
                    "forwarded": self.headers.get("x-forwarded-for", ""),
                }
            ).encode()
        else:
            payload = b"<!doctype html><title>Fake preview</title><h1>Preview ready</h1>"
            self._respond(200, payload, "text/html; charset=utf-8")
            return
        self._respond(200, payload)

    def do_HEAD(self) -> None:
        self._respond(200, b"")

    def do_POST(self) -> None:
        length = int(self.headers.get("content-length", "0"))
        payload = self.rfile.read(length)
        self._respond(200, payload)

    def do_PUT(self) -> None:
        self.do_POST()

    def do_PATCH(self) -> None:
        self.do_POST()

    def do_DELETE(self) -> None:
        self._respond(200, b"deleted", "text/plain")

    def do_OPTIONS(self) -> None:
        self.send_response(204)
        self.send_header("Allow", "GET, HEAD, POST, PUT, PATCH, DELETE, OPTIONS")
        self.end_headers()

    def log_message(self, format: str, *args: object) -> None:
        return


CHILD_PID: int | None = None


def main() -> None:
    global CHILD_PID
    if "--spawn-child" in sys.argv:
        child = subprocess.Popen(
            [sys.executable, "-c", "import time; time.sleep(3600)"],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            shell=False,
        )
        CHILD_PID = child.pid
    server = HTTPServer(("127.0.0.1", int(os.environ["PORT"])), Handler)
    try:
        server.serve_forever(poll_interval=0.1)
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
