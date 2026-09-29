#!/usr/bin/env python3
"""Deterministic API/Git failure and incomplete-record checks; no cluster required."""

import importlib.util
import json
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "tests/e2e/forgejo-developer-journey.sh"
VALIDATOR = ROOT / "scripts/validate-operation-results.py"
spec = importlib.util.spec_from_file_location("results_validator", VALIDATOR)
module = importlib.util.module_from_spec(spec)
sys.dont_write_bytecode = True
spec.loader.exec_module(module)

CURL_STUB = r'''#!/usr/bin/env bash
set -euo pipefail
original=("$@")
out= url= method=GET
while (($#)); do
  case "$1" in
    -o|-X|-w|-H|-K|--max-time|--data-binary) key="$1"; shift; if [[ "$key" == -o ]]; then out="$1"; elif [[ "$key" == -X ]]; then method="$1"; fi ;;
    http://*) url="$1" ;;
  esac
  shift
done
status=200 body='{}'
case "$url" in
  */admin/users) status=201 ;;
  */users/*/tokens) status=201; body='{"sha1":"secret-test-token"}' ;;
  */api/v1/user) body="{\"login\":\"$DEV_USER\",\"is_admin\":false}" ;;
  */user/repos)
    if [[ "$TEST_MODE" == api_failure ]]; then status=503; body='{"secret":"credential-bearing-response"}'
    elif [[ "$TEST_MODE" == api_timeout ]]; then printf 000; exit 28
    elif [[ "$TEST_MODE" == api_status_then_timeout ]]; then printf 200; exit 28
    elif [[ "$TEST_MODE" == api_partial_real ]]; then exec "$REAL_CURL" "${original[@]}"
    elif [[ "$TEST_MODE" == api_interrupt ]]; then kill -TERM "$PPID"; exit 143
    elif [[ "$TEST_MODE" == api_semantic_failure ]]; then status=201; body="{\"private\":false,\"owner\":{\"login\":\"$DEV_USER\"},\"clone_url\":\"$CLONE_URL\"}"
    else status=201; body="{\"private\":true,\"owner\":{\"login\":\"$DEV_USER\"},\"clone_url\":\"$CLONE_URL\"}"
    fi ;;
  */info/refs\?*) if [[ "$TEST_MODE" == assertion_delay ]]; then sleep 0.5; fi; status=401 ;;
  */repos/*) status=404 ;;
esac
if [[ "$TEST_MODE" == command_delay && "$url" == */user/repos ]]; then sleep 0.4; fi
printf '%s' "$body" >"$out"
printf '%s' "$status"
'''

GIT_STUB = r'''#!/usr/bin/env bash
if [[ " ${*} " == *" push "* ]]; then
  echo credential-bearing-response >&2
  if [[ "$TEST_MODE" == git_timeout ]]; then exit 124; fi
  if [[ "$TEST_MODE" == git_killed_early ]]; then exit 137; fi
  if [[ "$TEST_MODE" == git_timeout_kill ]]; then trap '' TERM; while :; do sleep 1; done; fi
  exit 128
fi
exec "$REAL_GIT" "$@"
'''

JQ_STUB = r'''#!/usr/bin/env bash
if [[ " $* " == *operation_start* ]]; then sleep 1.1; fi
exec "$REAL_JQ" "$@"
'''


class PartialResponse(BaseHTTPRequestHandler):
    def do_POST(self):
        self.send_response(200)
        self.send_header("Content-Length", "100")
        self.end_headers()
        self.wfile.write(b"{}")
        self.wfile.flush()
        self.close_connection = True

    def log_message(self, *_args):
        pass


def cli(path):
    return subprocess.run(["python3", str(VALIDATOR), "validate", str(path)], capture_output=True, text=True)


def write_rows(path, rows):
    path.write_text("\n".join(json.dumps(row) for row in rows) + "\n")


def check_prefixes_and_inventory(temp, rows):
    first_start = next(i for i, row in enumerate(rows) if row["record"] == "operation_start")
    first_attempt = next(i for i, row in enumerate(rows) if row["record"] == "attempt")
    first_assertion = next(i for i, row in enumerate(rows) if row["record"] == "auxiliary_event" and row["kind"] == "assertion")
    for name, stop, expected_attempts in (("start", first_start, 0), ("attempt", first_attempt, 1),
                                          ("assertion", first_assertion, 1)):
        path = temp / f"prefix-{name}.jsonl"
        write_rows(path, rows[:stop + 1])
        result = module.validate(path)
        assert result["completion"] == result["validity"] == "incomplete", result
        assert result["attempt_count"] == expected_attempts, result
        assert not any(metric["family"] in {"developer_operations_total", "developer_operation_duration_seconds"}
                       for metric in result["metrics"]), result
        assert cli(path).returncode == 2
        if expected_attempts:
            metric = next(m for m in result["metrics"] if m["family"] == "developer_operation_attempts_total")
            duration = next(m for m in result["metrics"] if m["family"] == "developer_operation_attempt_duration_seconds")
            assert metric["count"] == duration["duration_count"] == 1
            assert duration["duration_sum_seconds"] == rows[first_attempt]["duration_seconds"]
    open_with_end = temp / "open-with-run-end.jsonl"
    write_rows(open_with_end, rows[:first_attempt + 1] + [dict(rows[-1], completion="interrupted", validity="valid")])
    open_result = module.validate(open_with_end)
    assert open_result["completion"] == "interrupted" and open_result["validity"] == "incomplete"
    assert open_result["attempt_count"] == 1 and cli(open_with_end).returncode == 2

    first = next(row for row in rows if row["record"] == "operation_start")
    attempt = rows[first_attempt]
    end = next(row for row in rows if row["record"] == "operation")
    success_rows = [rows[0]]
    for index, typ in enumerate(sorted(module.OP_TYPES), 1):
        op_id = first["operation_id"].rsplit("-", 1)[0] + f"-{index}"
        success_rows.extend((dict(first, operation_id=op_id, operation_type=typ),
                             dict(attempt, operation_id=op_id, attempt_id=op_id + "-attempt-1"),
                             dict(end, operation_id=op_id, operation_type=typ)))
    success_rows.append(dict(rows[-1], completion="success", validity="valid"))
    planned = temp / "planned.jsonl"
    write_rows(planned, success_rows)
    assert module.validate(planned)["validity"] == "valid" and cli(planned).returncode == 0
    duplicate = [dict(row) for row in success_rows]
    missing = "private_repository_create"
    for row in duplicate:
        if row.get("operation_type") == missing:
            row["operation_type"] = "git_clone"
    duplicate_path = temp / "duplicate-type.jsonl"
    write_rows(duplicate_path, duplicate)
    assert cli(duplicate_path).returncode == 1
    try:
        module.validate(duplicate_path)
    except ValueError:
        pass
    else:
        raise AssertionError("duplicate git_clone and missing private_repository_create accepted")

    contradiction = temp / "false-success.jsonl"
    write_rows(contradiction, rows[:-1] + [dict(rows[-1], completion="success", validity="valid")])
    assert cli(contradiction).returncode == 1
    invalid = temp / "complete-invalid.jsonl"
    write_rows(invalid, rows[:-1] + [dict(rows[-1], validity="invalid")])
    assert module.validate(invalid)["validity"] == "invalid" and cli(invalid).returncode == 2


def run_failure(mode):
    with tempfile.TemporaryDirectory() as temp:
        temp = Path(temp)
        bindir = temp / "bin"
        bindir.mkdir()
        (bindir / "curl").write_text(CURL_STUB)
        (bindir / "git").write_text(GIT_STUB)
        if mode == "logger_delay":
            (bindir / "jq").write_text(JQ_STUB)
            (bindir / "jq").chmod(0o755)
        (bindir / "curl").chmod(0o755)
        (bindir / "git").chmod(0o755)
        context = temp / "context.json"
        context.write_text(json.dumps({
            "source_sha": "0" * 40, "dirty": False,
            "environment": {"kind": "test"}, "tool_versions": {},
            "argo_values_revision": "1" * 40,
            "forgejo_chart_version": "test", "forgejo_chart_digest": "sha256:test",
            "runtime_images": {},
        }))
        server = None
        forgejo_url = "http://127.0.0.1:13000"
        if mode == "api_partial_real":
            server = ThreadingHTTPServer(("127.0.0.1", 0), PartialResponse)
            threading.Thread(target=server.serve_forever, daemon=True).start()
            forgejo_url = f"http://127.0.0.1:{server.server_port}"
        env = dict(os.environ, PATH=f"{bindir}:{os.environ['PATH']}", REAL_GIT=shutil.which("git"),
                   REAL_CURL=shutil.which("curl"), REAL_JQ=shutil.which("jq"),
                   TEST_MODE=mode, FORGEJO_URL=forgejo_url,
                   JOURNEY_DIR=str(temp / "journey"), RESULTS_ROOT=str(temp / "results"),
                   RESULT_CONTEXT_FILE=str(context), RESULT_PHASE="measured",
                   FORGEJO_ADMIN_USERNAME="admin", FORGEJO_ADMIN_PASSWORD="secret-admin-password")
        if mode == "git_timeout_kill":
            env["JOURNEY_GIT_TIMEOUT_SECONDS"] = "0.2"
            env["JOURNEY_GIT_KILL_AFTER_SECONDS"] = "0.2"
        started = time.monotonic()
        try:
            proc = subprocess.run(["bash", str(SCRIPT), "create"], env=env, capture_output=True, text=True, timeout=15)
        finally:
            if server:
                server.shutdown()
                server.server_close()
        wall_seconds = time.monotonic() - started
        assert proc.returncode != 0, (mode, proc.stdout, proc.stderr)
        files = list((temp / "results").glob("*/events.jsonl"))
        assert len(files) == 1, (files, proc.stdout, proc.stderr)
        contents = files[0].read_text()
        assert "secret-test-token" not in contents and "secret-admin-password" not in contents
        assert "credential-bearing-response" not in contents and "credential-bearing-response" not in proc.stderr
        try:
            result = module.validate(files[0])
        except ValueError as exc:
            raise AssertionError((mode, str(exc), contents, proc.stderr)) from exc
        expected_completion = "interrupted" if mode == "api_interrupt" else "failed"
        assert result["completion"] == expected_completion and result["validity"] == "valid", result
        assert cli(files[0]).returncode == 0, (mode, contents)
        rows = [json.loads(line) for line in contents.splitlines()]
        attempt = next(row for row in rows if row["record"] == "attempt" and
                       (not mode.startswith("git_") or row["operation_id"].endswith("operation-2")))
        if mode == "api_failure":
            assert attempt["http_status"] == 503 and attempt["exit_code"] == 0
            assert attempt["error_class"] == "http_status"
        elif mode == "api_timeout":
            assert attempt["http_status"] is None and attempt["exit_code"] == 28
            assert attempt["error_class"] == "timeout"
        elif mode == "api_status_then_timeout":
            assert attempt["http_status"] == 200 and attempt["exit_code"] == 28
            assert attempt["error_class"] == "timeout"
        elif mode == "api_partial_real":
            assert attempt["http_status"] == 200 and attempt["exit_code"] == 18
            assert attempt["error_class"] == "transport_error"
        elif mode == "api_interrupt":
            assert attempt["http_status"] is None and attempt["exit_code"] != 0
        elif mode == "api_semantic_failure":
            assert attempt["http_status"] == 201 and attempt["exit_code"] == 0
            assert attempt["error_class"] == "none"
            assert next(row for row in rows if row["record"] == "operation")["semantic_result"] is False
        elif mode == "git_timeout":
            assert attempt["http_status"] is None and attempt["exit_code"] == 124
            assert attempt["error_class"] == "timeout"
        elif mode == "git_timeout_kill":
            assert attempt["http_status"] is None and attempt["exit_code"] == 137
            assert attempt["error_class"] == "timeout"
        elif mode == "git_killed_early":
            assert attempt["http_status"] is None and attempt["exit_code"] == 137
            assert attempt["error_class"] == "command_error"
        else:
            if mode in {"logger_delay", "command_delay", "assertion_delay"}:
                assert attempt["exit_code"] == 0 and attempt["error_class"] == "none"
                assert wall_seconds >= {"logger_delay": 1.1, "command_delay": 0.4,
                                        "assertion_delay": 0.5}[mode], (mode, wall_seconds)
                if mode == "command_delay":
                    assert attempt["duration_seconds"] >= 0.35, attempt
                else:
                    assert attempt["duration_seconds"] < 0.4, attempt
            else:
                assert attempt["http_status"] is None and attempt["exit_code"] == 128
                assert attempt["error_class"] == "command_error"
                assert result["operation_count"] == 2 and result["attempt_count"] == 2
        # SIGKILL처럼 run_end를 기록할 기회가 없었던 파일은 success로 해석할 수 없다.
        incomplete = temp / "incomplete.jsonl"
        incomplete.write_text("\n".join(contents.splitlines()[:-1]) + "\n")
        assert module.validate(incomplete)["completion"] == "incomplete"
        if mode == "git_failure":
            check_prefixes_and_inventory(temp, rows)
            broken = [dict(row) for row in rows]
            event = next(row for row in broken if row["record"] == "auxiliary_event" and row["attempt_id"])
            event["attempt_id"] = "missing-attempt"
            invalid = temp / "invalid.jsonl"
            invalid.write_text("\n".join(json.dumps(row) for row in broken) + "\n")
            try:
                module.validate(invalid)
            except ValueError:
                pass
            else:
                raise AssertionError("broken event-to-attempt reference accepted")
            # P1/P2 regression invokes create without RESULT_*; it must remain usable.
            legacy_env = dict(env)
            for key in ("RESULTS_ROOT", "RESULT_CONTEXT_FILE", "RESULT_PHASE"):
                legacy_env.pop(key)
            legacy = subprocess.run(["bash", str(SCRIPT), "create"], env=legacy_env,
                                    capture_output=True, text=True, timeout=15)
            assert legacy.returncode != 0 and "unbound variable" not in legacy.stderr, legacy.stderr
            assert "private repository ready" in legacy.stdout, legacy.stdout


for scenario in ("api_failure", "api_timeout", "api_status_then_timeout", "api_partial_real",
                 "api_interrupt", "api_semantic_failure", "logger_delay", "command_delay",
                 "assertion_delay", "git_failure", "git_timeout", "git_timeout_kill", "git_killed_early"):
    run_failure(scenario)
print("PASS deterministic R1-R4 prefixes/inventory/CLI/timing/curl, Git timeout/kill-after and credential hygiene")
