"""A minimal, dependency-free HTTP app used for Phase 13's Linux Docker
adapter integration tests and live verification — the containerized
equivalent of the Django/Waitress test app used for the Windows adapter.
Deliberately tiny: no framework, just the standard library, so building its
image needs nothing from PyPI.
"""

import os
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

PORT = int(os.environ.get("PORT", "8000"))
MODE = os.environ.get("MODE", "unset")


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):  # noqa: N802
        if self.path == "/health":
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b"ok")
            return
        self.send_response(200)
        self.end_headers()
        self.wfile.write(f"sample-docker-app mode={MODE}\n".encode())

    def log_message(self, format, *args):  # noqa: A002
        pass  # keep container logs quiet during automated tests


if __name__ == "__main__":
    server = ThreadingHTTPServer(("0.0.0.0", PORT), Handler)
    server.serve_forever()
