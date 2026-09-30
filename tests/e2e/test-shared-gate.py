"""Credential/body exclusion and fail-closed configuration checks."""
import contextlib
import concurrent.futures
import http.client
import importlib.util
import io
import json
from pathlib import Path
import threading
import unittest

ROOT = Path(__file__).resolve().parents[2]


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, ROOT / path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


app = load("app", "cmd/ext-authz-sim/main.py")
evidence = load("evidence", "scripts/validate-shared-gate.py")


class CheckTests(unittest.TestCase):
    def test_concurrent_checks_keep_json_lines_separate(self):
        server = app.ThreadingHTTPServer(("127.0.0.1", 0), app.CheckHandler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        output = io.StringIO()

        def send(index):
            connection = http.client.HTTPConnection(*server.server_address, timeout=3)
            try:
                connection.request("GET", "/", headers={"x-shared-gate-hop": "haproxy",
                                   "Authorization": "p4-check-without-credentials", "x-operation-id": f"op-{index}"})
                response = connection.getresponse()
                response.read()
                return response.status
            finally:
                connection.close()

        with contextlib.redirect_stdout(output):
            thread.start()
            try:
                with concurrent.futures.ThreadPoolExecutor(max_workers=4) as clients:
                    self.assertEqual(list(clients.map(send, range(16))), [200] * 16)
            finally:
                server.shutdown()
                thread.join()
                server.server_close()
        checks = [json.loads(line) for line in output.getvalue().splitlines()]
        evidence.validate_checks(checks)
        self.assertEqual(len(checks), 16)
        self.assertEqual(len({c["operation_id"] for c in checks}), 16)

    def check(self, headers=None, body=None):
        server = app.ThreadingHTTPServer(("127.0.0.1", 0), app.CheckHandler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            thread.start()
            connection = http.client.HTTPConnection(*server.server_address, timeout=3)
            connection.request("POST", "/path?token=never-record-this", body=body, headers=headers or {})
            response = connection.getresponse()
            status = response.status
            self.assertEqual(response.read(), b"")
            connection.close()
            server.shutdown()
            thread.join()
            server.server_close()
        return status, output.getvalue()

    def test_allow_and_safe_correlation(self):
        status, text = self.check({"x-shared-gate-hop": "haproxy", "Authorization": "p4-check-without-credentials", "x-operation-id": "operation-1",
                                   "x-attempt-id": "operation-1-attempt-1"})
        self.assertEqual(status, 200)
        record = json.loads(text)
        evidence.validate_checks([record])
        self.assertEqual(record["operation_id"], "operation-1")
        self.assertNotIn("never-record-this", text)

    def test_controlled_deny(self):
        status, text = self.check({"x-shared-gate-hop": "haproxy", "Authorization": "p4-check-without-credentials", "x-gate-test-deny": "true"})
        self.assertEqual(status, 403)
        self.assertTrue(json.loads(text)["controlled_deny"])

    def test_credentials_and_body_fail_closed_without_values(self):
        status, text = self.check({"x-shared-gate-hop": "haproxy", "Authorization": "secret-pat-sentinel",
                                   "Cookie": "secret-cookie-sentinel", "x-operation-id": "secret/invalid"},
                                  body="secret-body-sentinel")
        self.assertEqual(status, 403)
        for value in ("secret-pat-sentinel", "secret-cookie-sentinel", "secret-body-sentinel", "secret/invalid"):
            self.assertNotIn(value, text)
        with self.assertRaises(ValueError):
            evidence.validate_checks([json.loads(text)])

    def test_haproxy_bypass_rejected(self):
        status, _ = self.check()
        self.assertEqual(status, 403)

    def test_actual_authorization_rejected_without_body(self):
        status, text = self.check({"x-shared-gate-hop": "haproxy", "Authorization": "private-pat-sentinel"})
        self.assertEqual(status, 403)
        row = json.loads(text)
        self.assertFalse(row["credential_values_absent"])
        self.assertTrue(row["body_absent"])
        self.assertNotIn("private-pat-sentinel", text)

    def test_body_rejected_with_safe_authorization(self):
        status, text = self.check({"x-shared-gate-hop": "haproxy", "Authorization": "p4-check-without-credentials"},
                                  body="private-body-sentinel")
        self.assertEqual(status, 403)
        row = json.loads(text)
        self.assertTrue(row["credential_values_absent"])
        self.assertFalse(row["body_absent"])
        self.assertNotIn("private-body-sentinel", text)

    def test_missing_capacity_is_not_evidence(self):
        for clusters in ([], [{"name": "inbound|8080||", "circuitBreakers": {"thresholds": [{"maxRequests": 1}]}}]):
            with self.assertRaises(ValueError):
                evidence.target_cluster(clusters)

    def test_missing_ext_authz_is_not_evidence(self):
        with self.assertRaises(ValueError):
            evidence.auth_filter([])

    def test_native_sidecar_is_running_inventory(self):
        data = {"spec": {"containers": [{"name": "app"}], "initContainers": [
            {"name": "istio-init"}, {"name": "istio-proxy", "restartPolicy": "Always"}]}}
        self.assertEqual({c["name"] for c in evidence.active_containers(data)}, {"app", "istio-proxy"})


if __name__ == "__main__":
    unittest.main()
