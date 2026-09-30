"""Local HTTP ext_authz fixture. Never retain header values, path or body."""
import json
import os
from pathlib import Path
import re
import threading
import time
import uuid
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

LOG_LOCK = threading.Lock()


def correlation(value):
    return value if re.fullmatch(r"[a-zA-Z0-9-]{1,128}", value or "") else None


def hold_ms():
    # Fixed experiment configuration, never a request header/query parameter.
    path = os.environ.get("CHECK_HOLD_FILE")
    value = int(Path(path).read_text()) if path else 0
    if not 0 <= value <= 2000:
        raise ValueError("fixture hold must be between 0 and 2000 ms")
    return value


class CheckHandler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, *_args):
        pass

    def check(self):
        # Only names/booleans/counts survive serialization. Do not read request bodies.
        names = sorted({name.lower() for name in self.headers})
        # The supported provider stamps this non-secret value on the check copy.
        # Inspect all duplicates without retaining any value.
        credentials_absent = self.headers.get_all("authorization") == ["p4-check-without-credentials"] and not any(
            n in names for n in ("cookie", "proxy-authorization"))
        body_absent = self.headers.get("Content-Length", "0") == "0" and "transfer-encoding" not in names
        hop = self.headers.get("x-shared-gate-hop") == "haproxy"
        deny = self.headers.get("x-gate-test-deny") == "true"
        allowed = body_absent and credentials_absent and hop and not deny
        if allowed:
            time.sleep(hold_ms() / 1000)
        record = {
            "record": "authorization_check", "check_id": str(uuid.uuid4()),
            "timestamp_utc": datetime.now(timezone.utc).isoformat(),
            "operation_id": correlation(self.headers.get("x-operation-id")),
            "attempt_id": correlation(self.headers.get("x-attempt-id")),
            "decision": "ALLOW" if allowed else "DENY", "header_names": names,
            "credential_values_absent": credentials_absent, "body_absent": body_absent,
            "haproxy_hop": hop, "controlled_deny": deny,
        }
        # A JSON line and its newline must remain one serialized record even
        # when held requests finish together on different handler threads.
        with LOG_LOCK:
            print(json.dumps(record, separators=(",", ":")), flush=True)
        self.send_response(200 if allowed else 403)
        self.send_header("Content-Length", "0")
        self.send_header("x-gate-decision", record["decision"])
        self.end_headers()
        if not body_absent:
            self.close_connection = True

    do_GET = do_POST = do_PUT = do_PATCH = do_DELETE = do_HEAD = do_OPTIONS = check


if __name__ == "__main__":
    server = ThreadingHTTPServer(("0.0.0.0", 8080), CheckHandler)
    server.daemon_threads = True
    server.serve_forever()
