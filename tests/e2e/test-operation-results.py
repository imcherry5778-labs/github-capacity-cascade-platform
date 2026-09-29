#!/usr/bin/env python3
"""Deterministic API/Git failure and incomplete-record checks; no cluster required."""

import importlib.util
import json
import os
import shutil
import subprocess
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "tests/e2e/forgejo-developer-journey.sh"
VALIDATOR = ROOT / "scripts/validate-operation-results.py"
spec = importlib.util.spec_from_file_location("results_validator", VALIDATOR)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)

CURL_STUB = r'''#!/usr/bin/env bash
set -euo pipefail
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
    elif [[ "$TEST_MODE" == api_timeout ]]; then exit 28
    elif [[ "$TEST_MODE" == api_interrupt ]]; then kill -TERM "$PPID"; exit 143
    elif [[ "$TEST_MODE" == api_semantic_failure ]]; then status=201; body="{\"private\":false,\"owner\":{\"login\":\"$DEV_USER\"},\"clone_url\":\"$CLONE_URL\"}"
    else status=201; body="{\"private\":true,\"owner\":{\"login\":\"$DEV_USER\"},\"clone_url\":\"$CLONE_URL\"}"
    fi ;;
  */info/refs\?*) status=401 ;;
  */repos/*) status=404 ;;
esac
printf '%s' "$body" >"$out"
printf '%s' "$status"
'''

GIT_STUB = r'''#!/usr/bin/env bash
if [[ " ${*} " == *" push "* ]]; then
  echo credential-bearing-response >&2
  if [[ "$TEST_MODE" == git_timeout ]]; then exit 124; fi
  exit 128
fi
exec "$REAL_GIT" "$@"
'''


def run_failure(mode):
    with tempfile.TemporaryDirectory() as temp:
        temp = Path(temp)
        bindir = temp / "bin"
        bindir.mkdir()
        (bindir / "curl").write_text(CURL_STUB)
        (bindir / "git").write_text(GIT_STUB)
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
        env = dict(os.environ, PATH=f"{bindir}:{os.environ['PATH']}", REAL_GIT=shutil.which("git"),
                   TEST_MODE=mode, FORGEJO_URL="http://127.0.0.1:13000",
                   JOURNEY_DIR=str(temp / "journey"), RESULTS_ROOT=str(temp / "results"),
                   RESULT_CONTEXT_FILE=str(context), RESULT_PHASE="measured",
                   FORGEJO_ADMIN_USERNAME="admin", FORGEJO_ADMIN_PASSWORD="secret-admin-password")
        proc = subprocess.run(["bash", str(SCRIPT), "create"], env=env, capture_output=True, text=True, timeout=15)
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
        rows = [json.loads(line) for line in contents.splitlines()]
        attempt = next(row for row in rows if row["record"] == "attempt" and
                       (not mode.startswith("git_") or row["operation_id"].endswith("operation-2")))
        if mode == "api_failure":
            assert attempt["http_status"] == 503 and attempt["exit_code"] == 0
            assert attempt["error_class"] == "http_status"
        elif mode == "api_timeout":
            assert attempt["http_status"] is None and attempt["exit_code"] == 28
            assert attempt["error_class"] == "timeout"
        elif mode == "api_interrupt":
            assert attempt["http_status"] is None and attempt["exit_code"] != 0
        elif mode == "api_semantic_failure":
            assert attempt["http_status"] == 201 and attempt["exit_code"] == 0
            assert attempt["error_class"] == "none"
            assert next(row for row in rows if row["record"] == "operation")["semantic_result"] is False
        elif mode == "git_timeout":
            assert attempt["http_status"] is None and attempt["exit_code"] == 124
            assert attempt["error_class"] == "timeout"
        else:
            assert attempt["http_status"] is None and attempt["exit_code"] == 128
            assert attempt["error_class"] == "command_error"
            assert result["operation_count"] == 2 and result["attempt_count"] == 2
        # SIGKILL처럼 run_end를 기록할 기회가 없었던 파일은 success로 해석할 수 없다.
        incomplete = temp / "incomplete.jsonl"
        incomplete.write_text("\n".join(contents.splitlines()[:-1]) + "\n")
        assert module.validate(incomplete)["completion"] == "incomplete"
        if mode == "git_failure":
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


for scenario in ("api_failure", "api_timeout", "api_interrupt", "api_semantic_failure", "git_failure", "git_timeout"):
    run_failure(scenario)
print("PASS deterministic API status/semantic/timeout/interruption, Git failure/timeout, incomplete run and credential hygiene")
