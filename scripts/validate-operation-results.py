#!/usr/bin/env python3
"""Validate sanitized developer journey JSONL and derive the four project metrics."""

import json
import math
import sys
from collections import Counter, defaultdict
from pathlib import Path


ERROR_CLASSES = {"none", "command_error", "transport_error", "http_status", "timeout", "semantic_error"}
OP_TYPES = {
    "private_repository_create", "git_push_initial", "git_clone", "git_fetch",
    "git_push_feature", "pull_request_create", "pull_request_read", "issue_create", "issue_read",
}
AUX_KINDS = {"fixture", "readiness", "settle", "assertion", "seed"}
EXPECTED_KEYS = {
    "run_start": {"record", "schema_version", "run_id", "phase", "started_at_utc", "scenario",
                  "parameters", "measurement_boundary", "source_sha", "dirty", "environment",
                  "tool_versions", "argo_values_revision", "forgejo_chart_version",
                  "forgejo_chart_digest", "runtime_images"},
    "operation_start": {"record", "run_id", "operation_id", "operation_type", "timestamp_utc"},
    "attempt": {"record", "run_id", "attempt_id", "operation_id", "attempt_index",
                "timestamp_utc", "duration_seconds", "exit_code", "http_status", "error_class"},
    "operation": {"record", "run_id", "operation_id", "operation_type", "outcome",
                  "attempt_count", "duration_seconds", "semantic_result"},
    "auxiliary_event": {"record", "run_id", "event_id", "kind", "name", "outcome",
                        "operation_id", "attempt_id", "timestamp_utc"},
    "run_end": {"record", "run_id", "completion", "validity", "ended_at_utc"},
}


def require(condition, message):
    if not condition:
        raise ValueError(message)


def duration(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value) and value >= 0


def validate(path):
    records = [json.loads(line) for line in Path(path).read_text().splitlines()]
    require(records and records[0].get("record") == "run_start", "missing run_start")
    start = records[0]
    require(start["schema_version"] == 1, "unsupported schema_version")
    require(set(start) == EXPECTED_KEYS["run_start"], "run_start fields differ from sanitized allowlist")
    require(start["phase"] in {"warmup", "measured"}, "invalid phase")
    require(isinstance(start["dirty"], bool) and len(start["source_sha"]) == 40, "source provenance")
    parameters = start["parameters"]
    require(set(parameters) == {"concurrency", "max_attempts", "client_retry", "api_timeout_seconds",
                                "git_timeout_seconds", "git_kill_after_seconds"}, "parameter fields")
    require(parameters["concurrency"] == 1 and parameters["max_attempts"] == 1 and
            parameters["client_retry"] is False and parameters["api_timeout_seconds"] == 60 and
            duration(parameters["git_timeout_seconds"]) and parameters["git_timeout_seconds"] > 0 and
            duration(parameters["git_kill_after_seconds"]) and parameters["git_kill_after_seconds"] > 0,
            "parameter drift")
    require(start["measurement_boundary"] == "loopback kubectl port-forward client command", "measurement boundary")
    require(isinstance(start["environment"], dict) and isinstance(start["tool_versions"], dict), "environment fields")
    require(isinstance(start["runtime_images"], dict), "runtime image identity")
    run_id = start["run_id"]
    require(isinstance(run_id, str) and run_id, "run_id")
    operations = {}
    attempts = {}
    event_ids = set()
    ended = None
    for index, rec in enumerate(records[1:], 1):
        kind = rec.get("record")
        require(kind in EXPECTED_KEYS and kind != "run_start", f"record {index}: unknown kind")
        require(set(rec) == EXPECTED_KEYS[kind], f"record {index}: fields differ from sanitized allowlist")
        require(rec["run_id"] == run_id, f"record {index}: cross-run reference")
        require(ended is None, "record after run_end")
        if kind == "operation_start":
            op = rec["operation_id"]
            require(op not in operations and op.startswith(run_id + "-operation-"), "duplicate/invalid operation_id")
            require(rec["operation_type"] in OP_TYPES, "unbounded operation type")
            operations[op] = {"start": rec, "end": None}
        elif kind == "attempt":
            op = rec["operation_id"]
            aid = rec["attempt_id"]
            require(op in operations and operations[op]["end"] is None, "attempt without open operation")
            require(aid == op + "-attempt-1" and aid not in attempts and rec["attempt_index"] == 1, "attempt identity/index")
            require(duration(rec["duration_seconds"]), "invalid attempt duration")
            require(type(rec["exit_code"]) is int and rec["exit_code"] >= 0, "invalid exit code")
            require(rec["http_status"] is None or type(rec["http_status"]) is int and 100 <= rec["http_status"] <= 599, "HTTP status")
            require(rec["error_class"] in ERROR_CLASSES, "unbounded error class")
            attempts[aid] = rec
        elif kind == "operation":
            op = rec["operation_id"]
            require(op in operations and operations[op]["end"] is None, "operation end without start")
            require(rec["operation_type"] == operations[op]["start"]["operation_type"], "operation type changed")
            require(rec["attempt_count"] == 1 and op + "-attempt-1" in attempts, "attempt count mismatch")
            require(duration(rec["duration_seconds"]), "invalid operation duration")
            require(rec["outcome"] in {"success", "failed"} and type(rec["semantic_result"]) is bool, "operation outcome")
            require((rec["outcome"] == "success") == rec["semantic_result"], "semantic outcome mismatch")
            require(abs(rec["duration_seconds"] - attempts[op + "-attempt-1"]["duration_seconds"]) < 0.00001, "command duration mismatch")
            if rec["outcome"] == "success":
                attempt = attempts[op + "-attempt-1"]
                require(attempt["exit_code"] == 0 and attempt["error_class"] == "none", "successful operation has failed attempt")
            operations[op]["end"] = rec
        elif kind == "auxiliary_event":
            require(rec["event_id"] not in event_ids and rec["event_id"].startswith(run_id + "-event-"), "event_id")
            event_ids.add(rec["event_id"])
            require(rec["kind"] in AUX_KINDS and rec["outcome"] in {"success", "failed"}, "auxiliary event dimension")
            require(rec["operation_id"] is None or rec["operation_id"] in operations, "auxiliary event reference")
            require(rec["attempt_id"] is None if rec["operation_id"] is None else
                    rec["attempt_id"] == rec["operation_id"] + "-attempt-1" and rec["attempt_id"] in attempts,
                    "auxiliary attempt reference")
        elif kind == "run_end":
            require(index == len(records) - 1, "run_end is not final")
            require(rec["completion"] in {"success", "failed", "interrupted"}, "completion")
            require(rec["validity"] in {"valid", "invalid"}, "validity")
            ended = rec
    complete = ended is not None and all(op["end"] is not None for op in operations.values())
    if ended and ended["completion"] == "success":
        inventory = Counter(op["start"]["operation_type"] for op in operations.values())
        require(complete and inventory == Counter({typ: 1 for typ in OP_TYPES}) and
                all(op["end"]["outcome"] == "success" for op in operations.values()), "false success")
    metrics = defaultdict(lambda: {"count": 0, "duration_sum_seconds": 0.0, "duration_count": 0, "durations_seconds": []})
    for op in operations.values():
        if op["end"] is None:
            continue
        typ = op["end"]["operation_type"]
        outcome = op["end"]["outcome"]
        for family, rec, label in (
            ("developer_operations_total", op["end"], outcome),
            ("developer_operation_duration_seconds", op["end"], outcome),
        ):
            key = (family, typ, label)
            metrics[key]["count"] += 1
            if family.endswith("duration_seconds"):
                metrics[key]["duration_sum_seconds"] += rec["duration_seconds"]
                metrics[key]["duration_count"] += 1
                metrics[key]["durations_seconds"].append(rec["duration_seconds"])
    for attempt in attempts.values():
        typ = operations[attempt["operation_id"]]["start"]["operation_type"]
        attempt_outcome = "success" if attempt["exit_code"] == 0 and attempt["error_class"] == "none" else "failed"
        for family in ("developer_operation_attempts_total", "developer_operation_attempt_duration_seconds"):
            key = (family, typ, attempt_outcome)
            metrics[key]["count"] += 1
            if family.endswith("duration_seconds"):
                metrics[key]["duration_sum_seconds"] += attempt["duration_seconds"]
                metrics[key]["duration_count"] += 1
                metrics[key]["durations_seconds"].append(attempt["duration_seconds"])
    return {
        "run_id": run_id, "phase": start["phase"], "source_sha": start["source_sha"],
        "completion": ended["completion"] if ended else "incomplete",
        "validity": ended["validity"] if ended and complete else "incomplete",
        "operation_count": len(operations), "attempt_count": len(attempts),
        "metrics": [dict(family=k[0], operation_type=k[1], outcome=k[2], **v)
                    for k, v in sorted(metrics.items())],
    }


def summarize(directory):
    paths = sorted(Path(directory).glob("*/events.jsonl"))
    require(len(paths) == 6, "baseline needs exactly six runs")
    runs = [validate(path) for path in paths]
    require(sum(run["phase"] == "warmup" for run in runs) == 1, "one warmup required")
    measured = [run for run in runs if run["phase"] == "measured"]
    require(len(measured) == 5, "five measured runs required")
    require(all(run["completion"] == "success" and run["validity"] == "valid" for run in runs), "unhealthy baseline run")
    require(len({run["source_sha"] for run in runs}) == 1, "mixed source commits")
    require(all(json.loads(path.read_text().splitlines()[0])["parameters"]["git_timeout_seconds"] == 65 and
                json.loads(path.read_text().splitlines()[0])["parameters"]["git_kill_after_seconds"] == 5
                for path in paths), "baseline Git timeout drift")
    metrics = defaultdict(lambda: {"count": 0, "duration_sum_seconds": 0.0, "duration_count": 0, "durations_seconds": []})
    for run in measured:
        for metric in run["metrics"]:
            key = metric["family"], metric["operation_type"], metric["outcome"]
            item = metrics[key]
            item["count"] += metric["count"]
            item["duration_sum_seconds"] += metric["duration_sum_seconds"]
            item["duration_count"] += metric["duration_count"]
            item["durations_seconds"].extend(metric["durations_seconds"])
    result = []
    for key, item in sorted(metrics.items()):
        durations = item.pop("durations_seconds")
        item["duration_sum_seconds"] = round(item["duration_sum_seconds"], 6)
        if durations:
            item["min_seconds"] = min(durations)
            item["max_seconds"] = max(durations)
            item["mean_seconds"] = round(sum(durations) / len(durations), 6)
        result.append(dict(family=key[0], operation_type=key[1], outcome=key[2], **item))
    starts = []
    ends = []
    for path in paths:
        rows = [json.loads(line) for line in path.read_text().splitlines()]
        if rows[0]["phase"] == "measured":
            starts.append(rows[0]["started_at_utc"])
            ends.append(rows[-1]["ended_at_utc"])
    return {"schema_version": 1, "source_sha": measured[0]["source_sha"],
            "plan": {"warmup": 1, "measured": 5, "concurrency": 1, "max_attempts": 1,
                     "api_timeout_seconds": 60, "git_timeout_seconds": 65, "git_kill_after_seconds": 5},
            "measured_window_utc": {"start": min(starts), "end": max(ends)},
            "measured_run_ids": [run["run_id"] for run in measured],
            "operation_samples": sum(run["operation_count"] for run in measured),
            "attempt_samples": sum(run["attempt_count"] for run in measured),
            "metrics": result}


def main():
    if len(sys.argv) != 3 or sys.argv[1] not in {"validate", "summarize"}:
        raise SystemExit("usage: validate-operation-results.py validate EVENTS.jsonl | summarize BASELINE_DIR")
    if sys.argv[1] == "summarize":
        print(json.dumps(summarize(sys.argv[2]), indent=2, sort_keys=True))
        return 0
    result = validate(sys.argv[2])
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0 if result["validity"] == "valid" else 2


if __name__ == "__main__":
    try:
        sys.exit(main())
    except (ValueError, KeyError, json.JSONDecodeError) as exc:
        print(f"invalid result: {exc}", file=sys.stderr)
        sys.exit(1)
