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
from unittest.mock import patch
import tempfile
import tarfile
import hashlib

ROOT = Path(__file__).resolve().parents[2]


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, ROOT / path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


app = load("app", "cmd/ext-authz-sim/main.py")
evidence = load("evidence", "scripts/validate-shared-gate.py")


class CheckTests(unittest.TestCase):
    def test_export_config_identity_is_not_docker_index_identity(self):
        config = b'{"os":"linux","architecture":"amd64"}'
        expected = "sha256:" + hashlib.sha256(config).hexdigest()
        for name in ("blobs/sha256/config", "config.json"):
            with tempfile.TemporaryDirectory() as directory:
                path = Path(directory) / "image.tar"
                with tarfile.open(path, "w") as archive:
                    for filename, content in ((name, config), ("manifest.json", json.dumps([
                            {"Config": name, "RepoTags": ["ext-authz-sim:test"]}]).encode())):
                        header = tarfile.TarInfo(filename)
                        header.size = len(content)
                        archive.addfile(header, io.BytesIO(content))
                self.assertEqual(evidence.archive_config_digest(path, "ext-authz-sim:test"), expected)
                with self.assertRaisesRegex(ValueError, "absent"):
                    evidence.archive_config_digest(path, "ext-authz-sim:wrong-tag")

    def test_exact_node_cri_reference_and_config_id_required(self):
        reference = "docker.io/library/ext-authz-sim:test"
        images = [{"id": "sha256:expected", "tags": [reference]}]
        self.assertEqual(evidence.match_image(images, reference, "sha256:expected"), images[0])
        for inventory in ([], [{"id": "sha256:expected", "tags": ["ext-authz-sim:test"]}],
                          [{"id": "sha256:other", "tags": [reference]}], images + images):
            with self.assertRaises(ValueError):
                evidence.match_image(inventory, reference, "sha256:expected")

    def test_failed_image_check_retains_inventory_without_claiming_success(self):
        with tempfile.TemporaryDirectory() as directory, patch.dict(evidence.os.environ, {"EXT_AUTHZ_IMAGE": "ext-authz-sim:test"}), \
                patch.object(evidence, "owned_image_node", return_value="owned-node"), \
                patch.object(evidence, "image_inventory", return_value=[]):
            (Path(directory) / "app-image.json").write_text(json.dumps({"image_id": "sha256:index", "config_digest": "sha256:expected"}))
            with self.assertRaisesRegex(ValueError, "absent"):
                evidence.image_check(directory)
            result = json.loads((Path(directory) / "image-import.json").read_text())
            self.assertEqual(result["images"], [])
            self.assertNotIn("completed", result)

    def test_scheduled_image_must_match_owned_node_and_never_pull(self):
        with tempfile.TemporaryDirectory() as directory, patch.dict(evidence.os.environ, {"EXT_AUTHZ_IMAGE": "ext-authz-sim:test"}), \
                patch.object(evidence, "owned_image_node", return_value="owned-node"), \
                patch.object(evidence, "image_inventory", return_value=[{"id": "sha256:expected", "tags": ["docker.io/library/ext-authz-sim:test"]}]), \
                patch.object(evidence, "pod") as target:
            (Path(directory) / "app-image.json").write_text(json.dumps({"image_id": "sha256:index", "config_digest": "sha256:expected"}))
            target.return_value = {"metadata": {"name": "fixture"}, "spec": {"nodeName": "other-node", "containers": [
                {"name": "app", "image": "ext-authz-sim:test", "imagePullPolicy": "Never"}]}}
            with self.assertRaisesRegex(ValueError, "scheduled"):
                evidence.image_check(directory, scheduled=True)
            target.return_value["spec"]["nodeName"] = "owned-node"
            evidence.image_check(directory, scheduled=True)
            target.return_value["spec"]["containers"][0]["imagePullPolicy"] = "Always"
            with self.assertRaisesRegex(ValueError, "scheduled"):
                evidence.image_check(directory, scheduled=True)

    def test_node_message_hints_exclude_raw_credentials_and_paths(self):
        message = 'ErrImageNeverPull /home/private/person token=secret-sentinel not present with pull policy of Never'
        hints = evidence.image_hints(message)
        self.assertEqual(hints, ["ErrImageNeverPull", "not present with pull policy of Never"])
        self.assertNotIn("secret-sentinel", json.dumps(hints))

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
