"""Disposable Bot API stub for the isolated release.

The synthetic request is acknowledged in memory. Logs contain only an accepted-request counter.
"""

import json
from http.server import BaseHTTPRequestHandler, HTTPServer

SEND_PATH = "/bot0:fake-test-token/sendMessage"


class Handler(BaseHTTPRequestHandler):
    accepted = 0

    def do_POST(self):
        if self.path != SEND_PATH:
            self.send_error(404)
            return
        try:
            length = int(self.headers.get("Content-Length", "0"))
            if not 0 < length <= 8192:
                raise ValueError
            body = json.loads(self.rfile.read(length))
            chat_id = body["chat_id"]
            if type(chat_id) is not int or chat_id <= 0 or not isinstance(body["text"], str):
                raise ValueError
        except (ValueError, TypeError, KeyError):
            self.send_error(400)
            return

        type(self).accepted += 1
        response = json.dumps(
            {
                "ok": True,
                "result": {
                    "message_id": self.accepted,
                    "chat": {"type": "private", "id": chat_id},
                },
            }
        ).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(response)))
        self.end_headers()
        self.wfile.write(response)
        print(f"synthetic_send_count={self.accepted}")

    def log_message(self, format, *args):
        pass


if __name__ == "__main__":
    with HTTPServer(("0.0.0.0", 8080), Handler) as server:
        server.serve_forever()
