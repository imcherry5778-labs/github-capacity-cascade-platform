"""Reject missing mechanism, control, freeze and bounded-retry evidence."""
import copy
import importlib.util
import http.client
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location("saturation", ROOT / "scripts/shared-gate-saturation.py")
s = importlib.util.module_from_spec(spec)
spec.loader.exec_module(s)
spec = importlib.util.spec_from_file_location("app", ROOT / "cmd/ext-authz-sim/main.py")
app = importlib.util.module_from_spec(spec)
spec.loader.exec_module(app)


def fixture():
    config = {"max_requests": 1, "hold_ms": 100, "logical_operations": 2, "concurrency": 2}
    cluster = {"name": "inbound|8080||", "circuitBreakers": {"thresholds": [{"maxRequests": 1}]}}
    stats = {"cluster.inbound_8080." + k: 0 for k in s.SUFFIXES}
    pod = {"uid": "pod-1", "name": "pod", "phase": "Running", "reason": None, "ready": True,
           "containers": [{"name": "app", "ready": True, "restarts": 0, "last_termination": None}]}
    guard = {"pods": {k: copy.deepcopy(pod) for k in ("forgejo", "postgres", "ext-authz-sim", "haproxy", "p4-ingress")},
             "nodes": [{"name": "node", "conditions": {"Ready": "True", "MemoryPressure": "False",
                        "DiskPressure": "False", "PIDPressure": "False"}}],
             "postgres": {"query_ok": True, "connections": 10, "max_connections": 100, "reserved": 0, "superuser_reserved": 3}}
    hp = {"pxname": "ext_authz", "svname": "app", "status": "no check"} | {k: 0 for k in s.HAPROXY_FIELDS}
    before = {"stats": stats, "guard": guard, "haproxy": [hp]}
    after = copy.deepcopy(before)
    after["stats"]["cluster.inbound_8080.upstream_rq_total"] = 1
    after["stats"]["cluster.inbound_8080.upstream_rq_active_overflow"] = 1
    after["haproxy"][0].update(hrsp_2xx=1, hrsp_5xx=1, stot=2)
    result = {"status": 200, "error_class": "none", "semantic_result": True,
              "start_monotonic": 1, "end_monotonic": 2, "duration_seconds": 1}
    events = [{"record": "run_start", "schema_version": 1, "run_id": "run", "phase": "no-retry", "scenario": config,
               "scenario_sha256": s.digest(config), "max_attempts": 1, "timestamp_utc": "2026-10-01T00:00:00Z",
               "operation_type": "authenticated_private_issue_read", "client_timeout_seconds": 10, "retry_policy": "none"}]
    for i in (1, 2):
        events += [{"record": "operation_start", "operation_id": f"op-{i}", "monotonic": 1},
                   {"record": "attempt", "operation_id": f"op-{i}", "attempt_id": f"op-{i}-attempt-1", "attempt_index": 1} |
                   (result if i == 1 else result | {"status": 403, "error_class": "http_status", "semantic_result": False}),
                   {"record": "operation", "operation_id": f"op-{i}", "attempt_count": 1,
                    "outcome": "success" if i == 1 else "failed", "start_monotonic": 1, "end_monotonic": 2}]
    events += [{"record": "target_sample", "monotonic": 1.5, "stats": stats | {"cluster.inbound_8080.upstream_rq_active": 1}},
               {"record": "sentinel", "read": result, "health": result},
               {"record": "guard", "start_monotonic": 1, "end_monotonic": 2, "snapshot": guard},
               {"record": "run_end", "run_id": "run", "completed": True, "timestamp_utc": "2026-10-01T00:00:01Z"}]
    proxy = {"record": "proxy_request", "status": 200, "details": "via_upstream", "upstream_cluster": cluster["name"], "upstream_host": "127.0.0.1:8080"}
    check = {"record": "authorization_check", "check_id": "check-1", "timestamp_utc": "2026-10-01T00:00:00Z",
             "operation_id": "op-1", "attempt_id": "op-1-attempt-1", "decision": "ALLOW", "header_names": ["authorization"],
             "credential_values_absent": True, "body_absent": True, "haproxy_hop": True, "controlled_deny": False}
    path = {"checks": [check], "proxies": {
        "target": [proxy, proxy | {"status": 503, "details": "upstream_reset_before_response_started{overflow}", "upstream_host": None}],
        "ingress": [proxy, proxy | {"status": 403, "details": "ext_authz_error", "upstream_host": None}]}}
    actual = {"hold_ms": 100, "route_retries": 0, "haproxy_retries": 0, "cluster": cluster,
              "stat_names": sorted(stats), "runtime_guard": {"admin_entry": None}}
    return {"events.jsonl": events, "before.json": before, "after.json": after,
            "configuration.json": actual, "path.json": path}


class EvidenceTests(unittest.TestCase):
    def validate(self, data):
        with tempfile.TemporaryDirectory() as directory:
            for file, value in data.items():
                p = Path(directory) / file
                if file.endswith('jsonl'):
                    p.write_text(''.join(json.dumps(e) + '\n' for e in value))
                else:
                    s.save(p, value)
            return s.validate_measurement(directory)

    def test_valid_rejection_and_dispatch_are_distinct_from_admitted_app(self):
        summary = self.validate(fixture())
        self.assertEqual(summary['authorization_checks'], 2)
        self.assertEqual(summary['admitted_app_checks'], 1)
        self.assertEqual(summary['client_status_distribution'], {'200': 1, '403': 1})

    def test_missing_or_competing_mechanism_rejected(self):
        for field, value in [('upstream_rq_active_overflow', 0), ('upstream_rq_pending_overflow', 1)]:
            data = fixture()
            data['after.json']['stats']['cluster.inbound_8080.' + field] = value
            with self.assertRaises(ValueError):
                self.validate(data)

    def test_failed_or_non_overlapping_sentinel_rejected(self):
        for change in ({'semantic_result': False}, {'start_monotonic': 3, 'end_monotonic': 4}):
            data = fixture()
            next(e for e in data['events.jsonl'] if e['record'] == 'sentinel')['read'].update(change)
            with self.assertRaises(ValueError):
                self.validate(data)

    def test_confounders_fail_closed(self):
        for component in ('forgejo', 'postgres', 'ext-authz-sim', 'haproxy'):
            data = fixture()
            data['after.json']['guard']['pods'][component]['containers'][0]['restarts'] = 1
            with self.assertRaises(ValueError):
                self.validate(data)
        data = fixture()
        data['after.json']['guard']['postgres']['connections'] = 97
        with self.assertRaises(ValueError):
            self.validate(data)
        data = fixture()
        data['after.json']['haproxy'][0]['qmax'] = 1
        with self.assertRaises(ValueError):
            self.validate(data)

    def test_missing_during_run_control_and_unbounded_retry_rejected(self):
        for record in ('guard', 'target_sample', 'run_end'):
            data = fixture()
            data['events.jsonl'] = [e for e in data['events.jsonl'] if e['record'] != record]
            with self.assertRaises(ValueError):
                self.validate(data)
        data = fixture()
        data['events.jsonl'][0]['max_attempts'] = 3
        with self.assertRaises(ValueError):
            self.validate(data)

    def test_changed_frozen_demand_rejected(self):
        data = fixture()
        data['events.jsonl'][0]['scenario']['hold_ms'] = 200
        with self.assertRaises(ValueError):
            self.validate(data)
        data = fixture()
        data['configuration.json']['cluster']['circuitBreakers']['thresholds'][0]['maxRequests'] = 2
        with self.assertRaises(ValueError):
            self.validate(data)

    def test_unexpected_record_values_not_retained_as_valid(self):
        data = fixture()
        data['events.jsonl'][1]['request_body'] = 'private-body'
        with self.assertRaises(ValueError):
            self.validate(data)

    def test_runtime_guard_and_orphan_check_rejected(self):
        data = fixture()
        data['configuration.json']['runtime_guard']['admin_entry'] = {'final_value': 'false'}
        with self.assertRaises(ValueError):
            self.validate(data)
        data = fixture()
        data['path.json']['checks'][0]['attempt_id'] = 'orphan'
        with self.assertRaises(ValueError):
            self.validate(data)

    def test_hold_is_fixed_bounded_config(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'hold-ms'
            with patch.dict(os.environ, {'CHECK_HOLD_FILE': str(path)}):
                for invalid in ('-1', '2001', 'not-an-int'):
                    path.write_text(invalid)
                    with self.assertRaises(ValueError):
                        app.hold_ms()
                path.write_text('1000')
                self.assertEqual(app.hold_ms(), 1000)

    def test_forgejo_issue_null_pull_request_is_success(self):
        response = unittest.mock.Mock(status=200)
        response.read.return_value = json.dumps({'number': 2, 'title': 'issue', 'state': 'open', 'pull_request': None}).encode()
        connection = unittest.mock.Mock()
        connection.getresponse.return_value = response
        with patch.object(http.client, 'HTTPConnection', return_value=connection):
            self.assertTrue(s.request(13000, '/fixture', {}, (2, 'issue'))['semantic_result'])
            response.read.return_value = json.dumps({'number': 2, 'title': 'issue', 'state': 'open', 'pull_request': {}}).encode()
            self.assertFalse(s.request(13000, '/fixture', {}, (2, 'issue'))['semantic_result'])


if __name__ == '__main__':
    unittest.main()
