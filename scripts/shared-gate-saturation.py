#!/usr/bin/env python3
"""P4-W2: one bounded Issue-read experiment; raw snapshots are immutable.

Authorization checks dispatched to the target include rejected checks. App check
records only exist for admitted requests. Neither is a general Git-attempt count.
"""
import concurrent.futures
from collections import Counter
from datetime import datetime, timezone
import hashlib
import http.client
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import threading
import time
import uuid

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("gate", ROOT / "scripts/validate-shared-gate.py")
gate = importlib.util.module_from_spec(spec)
spec.loader.exec_module(gate)
require = gate.require
SUFFIXES = ("upstream_rq_active", "upstream_rq_active_overflow", "upstream_rq_total",
            "upstream_rq_pending_active", "upstream_rq_pending_overflow")
GUARD = "envoy.reloadable_features.skip_pending_overflow_count_on_active_rq"
HAPROXY_FIELDS = ("stot", "req_tot", "qcur", "qmax", "scur", "smax", "econ", "eresp",
                  "wretr", "wredis", "hrsp_2xx", "hrsp_4xx", "hrsp_5xx", "cli_abrt", "srv_abrt")
DIRECT = 13000
GATED = 18080
ADMIN = 19000
REQUEST_KEYS = {"status", "error_class", "semantic_result", "start_monotonic", "end_monotonic", "duration_seconds"}
EVENT_KEYS = {
    "run_start": {"record", "schema_version", "run_id", "phase", "timestamp_utc", "scenario", "scenario_sha256",
                  "max_attempts", "operation_type", "client_timeout_seconds", "retry_policy"},
    "run_end": {"record", "run_id", "completed", "timestamp_utc"},
    "operation_start": {"record", "operation_id", "monotonic"},
    "attempt": {"record", "operation_id", "attempt_id", "attempt_index"} | REQUEST_KEYS,
    "operation": {"record", "operation_id", "attempt_count", "outcome", "start_monotonic", "end_monotonic"},
    "target_sample": {"record", "monotonic", "stats"},
    "sentinel": {"record", "read", "health"},
    "guard": {"record", "start_monotonic", "end_monotonic", "snapshot"},
}


def utc():
    return datetime.now(timezone.utc).isoformat()


def save(path, value):
    with Path(path).open("x") as f:
        json.dump(value, f, indent=2)
        f.write("\n")


def read(path):
    return json.loads(Path(path).read_text())


def rows(path):
    return [json.loads(line) for line in Path(path).read_text().splitlines()]


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True).encode()).hexdigest()


def scenario(value):
    require(set(value) == {"max_requests", "hold_ms", "logical_operations", "concurrency"}, "scenario keys differ")
    bounds = {"max_requests": (1, 8), "hold_ms": (100, 2000),
              "logical_operations": (2, 64), "concurrency": (2, 32)}
    for key, (low, high) in bounds.items():
        require(type(value[key]) is int and low <= value[key] <= high, f"unbounded scenario {key}")
    require(value["max_requests"] < value["concurrency"] <= value["logical_operations"], "scenario cannot pressure capacity")
    return value


def admin(path):
    c = http.client.HTTPConnection("127.0.0.1", ADMIN, timeout=3)
    try:
        c.request("GET", path)
        response = c.getresponse()
        require(response.status == 200, "target admin read failed")
        return response.read().decode()
    finally:
        c.close()


def stats(cluster):
    data = {}
    prefixes = [f"cluster.{name}." for name in (cluster["name"], cluster.get("altStatName")) if name]
    for line in admin("/stats").splitlines():
        if ": " not in line:
            continue
        key, value = line.rsplit(": ", 1)
        if any(key.startswith(prefix) for prefix in prefixes) and key.rsplit(".", 1)[-1] in SUFFIXES:
            require(value.isdigit(), "non-integer target stat")
            data[key] = int(value)
    require(len(data) == len(SUFFIXES) and {k.rsplit('.', 1)[-1] for k in data} == set(SUFFIXES),
            "narrow matcher did not expose required target stats")
    return data


def by_suffix(data):
    return {k.rsplit(".", 1)[-1]: v for k, v in data.items()}


def haproxy():
    import csv
    import io
    name = gate.pod("app=haproxy")["metadata"]["name"]
    text = gate.kube("-n", "shared-gate", "exec", name, "-c", "haproxy", "--", "wget", "-qO-",
                     "http://127.0.0.1:8404/stats;csv")
    inventory = [{"pxname": row["pxname"], "svname": row["svname"], "status": row["status"]} |
                 {k: int(row[k]) if row.get(k, "").isdigit() else None for k in HAPROXY_FIELDS}
                 for row in csv.DictReader(io.StringIO(text.removeprefix("# ")))
                 if row["pxname"] == "ext_authz"]
    require(inventory, "HAProxy inventory absent")
    return inventory


def server_counter(inventory):
    servers = [r for r in inventory if r["svname"] == "app"]
    require(len(servers) == 1, "HAProxy backend server absent/ambiguous")
    return servers[0]


def backend_requests(row):
    # Count completed HTTP check responses, including target 503 rejections.
    return sum(row[k] for k in ("hrsp_2xx", "hrsp_4xx", "hrsp_5xx"))


def pod_guard(data):
    active = data["status"].get("containerStatuses", []) + [
        c for c in data["status"].get("initContainerStatuses", [])
        if c["name"] in {a["name"] for a in gate.active_containers(data)}]
    return {"name": data["metadata"]["name"], "uid": data["metadata"]["uid"],
            "phase": data["status"].get("phase"), "reason": data["status"].get("reason"),
            "ready": any(c["type"] == "Ready" and c["status"] == "True" for c in data["status"].get("conditions", [])),
            "containers": [{"name": c["name"], "ready": c["ready"], "restarts": c["restartCount"],
                            "last_termination": c.get("lastState", {}).get("terminated", {}).get("reason")}
                           for c in active]}


def guard_snapshot():
    pods = json.loads(gate.kube("get", "pods", "-A", "-o", "json"))["items"]
    selected = {}
    for ns, label in (("forgejo", "app.kubernetes.io/name"), ("postgres", "app.kubernetes.io/name"),
                      ("shared-gate", "app"), ("shared-gate", "istio")):
        for pod in pods:
            value = pod["metadata"].get("labels", {}).get(label)
            if pod["metadata"]["namespace"] == ns and value in {"forgejo", "postgres", "ext-authz-sim", "haproxy", "p4-ingress"}:
                require(value not in selected, "confounder pod inventory ambiguous")
                selected[value] = pod_guard(pod)
    require(set(selected) == {"forgejo", "postgres", "ext-authz-sim", "haproxy", "p4-ingress"}, "confounder pod absent")
    nodes = [{"name": n["metadata"]["name"], "conditions": {c["type"]: c["status"] for c in n["status"]["conditions"]
               if c["type"] in {"Ready", "MemoryPressure", "DiskPressure", "PIDPressure"}}}
             for n in json.loads(gate.kube("get", "nodes", "-o", "json"))["items"]]
    query = """SELECT json_build_object('query_ok',1=1,'connections',(SELECT count(*) FROM pg_stat_activity),
      'max_connections',current_setting('max_connections')::int,
      'superuser_reserved',current_setting('superuser_reserved_connections')::int,
      'reserved',current_setting('reserved_connections')::int,
      'states',(SELECT json_agg(s) FROM (SELECT coalesce(state,'background') state,count(*) connections
                FROM pg_stat_activity GROUP BY state) s));"""
    db = json.loads(gate.kube("-n", "postgres", "exec", "postgres-0", "-c", "postgres", "--",
                             "psql", "-U", "postgres", "-d", "forgejo", "-tA", "-c", query))
    return {"pods": selected, "nodes": nodes, "postgres": db}


def metrics():
    try:
        data = json.loads(subprocess.check_output(
            ["kubectl", "--request-timeout=10s", "get", "--raw", "/apis/metrics.k8s.io/v1beta1/pods"],
            text=True, timeout=15, stderr=subprocess.DEVNULL))
        return {"available": True, "pods": [{"namespace": p["metadata"]["namespace"], "name": p["metadata"]["name"],
                 "timestamp": p["timestamp"], "window": p["window"], "containers": p["containers"]}
                for p in data["items"] if p["metadata"]["namespace"] in {"forgejo", "postgres", "shared-gate"}]}
    except (subprocess.SubprocessError, json.JSONDecodeError):
        return {"available": False, "reason": "existing runtime metrics API unavailable"}


def safe_logs(target, ingress):
    checks = [json.loads(line) for line in gate.kube("-n", "shared-gate", "logs", target, "-c", "app").splitlines()]
    if checks:
        gate.validate_checks(checks)
    proxies = {}
    for label, name in (("target", target), ("ingress", ingress)):
        records = []
        for line in gate.kube("-n", "shared-gate", "logs", name, "-c", "istio-proxy").splitlines():
            if not line.startswith("{"):
                continue
            row = json.loads(line)
            if row.get("record") != "proxy_request":
                continue
            require(set(row) == {"record", "status", "details", "upstream_cluster", "upstream_host"}, "unsafe proxy log")
            row["status"] = int(row["status"])
            records.append(row)
        proxies[label] = records
    return {"checks": checks, "proxies": proxies}


def request(port, path, headers, expected=None):
    start = time.monotonic()
    c = http.client.HTTPConnection("127.0.0.1", port, timeout=10)
    status = None
    error = "none"
    semantic = False
    try:
        c.request("GET", path, headers=headers)
        r = c.getresponse()
        status = r.status
        body = r.read()  # Memory only; no credential/body/path survives recording.
        if status == 200:
            if expected is None:
                semantic = True
            else:
                try:
                    value = json.loads(body)
                    semantic = value.get("number") == expected[0] and value.get("title") == expected[1] and \
                        value.get("state") == "open" and value.get("pull_request") is None
                except (ValueError, AttributeError):
                    semantic = False
        error = "none" if semantic else ("http_status" if status != 200 else "semantic_error")
    except TimeoutError:
        error = "timeout"
    except (OSError, http.client.HTTPException):
        error = "transport"
    finally:
        c.close()
    end = time.monotonic()
    return {"status": status, "error_class": error, "semantic_result": semantic,
            "start_monotonic": start, "end_monotonic": end, "duration_seconds": end - start}


def configuration(config, target, ingress):
    cluster = gate.target_cluster(gate.proxy_config(target, "clusters"), config["max_requests"])
    hold = int(gate.kube("-n", "shared-gate", "exec", target, "-c", "app", "--", "cat", "/config/hold-ms"))
    require(hold == config["hold_ms"], "actual app hold differs")
    routes = [r for c in gate.proxy_config(ingress, "routes") for h in c.get("virtualHosts", [])
              for r in h.get("routes", []) if r.get("route", {}).get("cluster") ==
              "outbound|3000||forgejo-http.forgejo.svc.cluster.local"]
    require(routes and all(r["route"].get("retryPolicy", {}).get("numRetries", 0) == 0 for r in routes), "route retry changed")
    hp = gate.pod("app=haproxy")["metadata"]["name"]
    hp_config = gate.kube("-n", "shared-gate", "exec", hp, "-c", "haproxy", "--", "cat", "/config/haproxy.cfg")
    require("retries 0" in hp_config and "maxconn" not in hp_config and "rate-limit" not in hp_config, "HAProxy policy drift")
    boot = gate.proxy_config(target, "bootstrap")["bootstrap"]
    matcher = boot["statsConfig"]["statsMatcher"]
    # Retain only this workload's annotation and selected actual target stat names.
    annotation = gate.pod("app=ext-authz-sim")["metadata"]["annotations"]["proxy.istio.io/config"]
    runtime_guard = json.loads(admin("/runtime?format=json")).get("entries", {}).get(GUARD)
    return {"cluster": cluster, "hold_ms": hold, "stat_names": sorted(stats(cluster)),
            "proxy_config_annotation": annotation, "actual_stats_matcher": matcher,
            "runtime_guard": {"name": GUARD, "admin_entry": runtime_guard}, "route_retries": 0,
            "haproxy_retries": 0, "haproxy_config_sha256": hashlib.sha256(hp_config.encode()).hexdigest(),
            "pod_uids": {label: gate.pod(selector)["metadata"]["uid"] for label, selector in
                         (("target", "app=ext-authz-sim"), ("ingress", "istio=p4-ingress"), ("haproxy", "app=haproxy"))}}


def prepare(config, target):
    gate.kube("-n", "shared-gate", "patch", "sidecar", "ext-authz-sim", "--type=merge", "-p",
              json.dumps({"spec": {"inboundConnectionPool": {"http": {"http2MaxRequests": config["max_requests"]}}}}))
    gate.kube("-n", "shared-gate", "patch", "configmap", "ext-authz-hold", "--type=merge", "-p",
              json.dumps({"data": {"hold-ms": str(config["hold_ms"])}}))
    deadline = time.monotonic() + 180
    while time.monotonic() < deadline:
        hold = int(gate.kube("-n", "shared-gate", "exec", target, "-c", "app", "--", "cat", "/config/hold-ms"))
        try:
            gate.target_cluster(gate.proxy_config(target, "clusters"), config["max_requests"])
            if hold == config["hold_ms"]:
                return
        except ValueError:
            pass
        time.sleep(1)
    raise ValueError("bounded configuration convergence timeout")


def measure(directory, config, max_attempts, target, ingress, path, auth, expected, frozen_sha):
    directory.mkdir()
    run_id = str(uuid.uuid4())
    lock = threading.Lock()
    def emit(record):
        with lock, (directory / "events.jsonl").open("a") as f:
            f.write(json.dumps(record, separators=(",", ":")) + "\n")
    emit({"record": "run_start", "schema_version": 1, "run_id": run_id, "phase": directory.name,
          "timestamp_utc": utc(), "scenario": config, "scenario_sha256": frozen_sha, "max_attempts": max_attempts,
          "operation_type": "authenticated_private_issue_read", "client_timeout_seconds": 10,
          "retry_policy": "immediate once on failure" if max_attempts == 2 else "none"})
    actual = configuration(config, target, ingress)
    save(directory / "configuration.json", actual)
    cluster = actual["cluster"]
    require(by_suffix(stats(cluster))["upstream_rq_active"] == 0, "previous requests still outstanding")
    before_logs = safe_logs(target, ingress)
    before = {"stats": stats(cluster), "haproxy": haproxy(), "guard": guard_snapshot(),
              "metrics": metrics(), "timestamp_utc": utc()}
    save(directory / "before.json", before)
    stop = threading.Event()
    start = threading.Event()
    def stat_monitor():
        start.wait()
        while not stop.is_set():
            emit({"record": "target_sample", "monotonic": time.monotonic(), "stats": stats(cluster)})
            stop.wait(.05)
    def sentinel_monitor():
        start.wait()
        while not stop.is_set():
            emit({"record": "sentinel", "read": request(DIRECT, path, auth, expected),
                  "health": request(DIRECT, "/api/healthz", {})})
            stop.wait(.1)
    def guard_monitor():
        start.wait()
        while not stop.is_set():
            begin = time.monotonic()
            snapshot = guard_snapshot()
            emit({"record": "guard", "start_monotonic": begin, "end_monotonic": time.monotonic(), "snapshot": snapshot})
            stop.wait(.5)
    def operation(index):
        start.wait()
        op_id = f"{run_id}-operation-{index}"
        begin = time.monotonic()
        emit({"record": "operation_start", "operation_id": op_id, "monotonic": begin})
        count = 0
        for count in range(1, max_attempts + 1):
            attempt_id = f"{op_id}-attempt-{count}"
            result = request(GATED, path, auth | {"x-operation-id": op_id, "x-attempt-id": attempt_id}, expected)
            emit({"record": "attempt", "operation_id": op_id, "attempt_id": attempt_id, "attempt_index": count} | result)
            if result["semantic_result"]:
                break
        emit({"record": "operation", "operation_id": op_id, "attempt_count": count,
              "outcome": "success" if result["semantic_result"] else "failed", "start_monotonic": begin,
              "end_monotonic": time.monotonic()})
    try:
        with concurrent.futures.ThreadPoolExecutor(max_workers=3) as monitors, \
             concurrent.futures.ThreadPoolExecutor(max_workers=config["concurrency"]) as clients:
            monitoring = [monitors.submit(f) for f in (stat_monitor, sentinel_monitor, guard_monitor)]
            work = [clients.submit(operation, i) for i in range(1, config["logical_operations"] + 1)]
            start.set()
            try:
                for f in work:
                    f.result(timeout=180)
            finally:
                stop.set()
            for f in monitoring:
                f.result(timeout=60)
        # Access logs flush asynchronously. Bound the wait; don't include another load.
        time.sleep(1)
        require(by_suffix(stats(cluster))["upstream_rq_active"] == 0, "final outstanding requests remain")
        require(configuration(config, target, ingress) == actual, "runtime changed during measured run")
        after = {"stats": stats(cluster), "haproxy": haproxy(), "guard": guard_snapshot(),
                 "metrics": metrics(), "timestamp_utc": utc()}
        save(directory / "after.json", after)
        after_logs = safe_logs(target, ingress)
        log_delta = {"checks": after_logs["checks"][len(before_logs["checks"]):],
                     "proxies": {k: v[len(before_logs["proxies"][k]):] for k, v in after_logs["proxies"].items()}}
        save(directory / "path.json", log_delta)
        emit({"record": "run_end", "run_id": run_id, "completed": True, "timestamp_utc": utc()})
    except BaseException:
        emit({"record": "run_failure", "run_id": run_id, "completed": False, "timestamp_utc": utc()})
        raise
    summary = validate_measurement(directory)
    save(directory / "summary.json", summary)
    return summary


def validate_guard(snapshots):
    require(snapshots, "confounder samples absent")
    first = snapshots[0]
    for snapshot in snapshots:
        require(set(snapshot["pods"]) == set(first["pods"]), "confounder inventory changed")
        for key, pod in snapshot["pods"].items():
            initial = first["pods"][key]
            require(pod["ready"] and pod["phase"] == "Running" and not pod["reason"], f"{key} not healthy")
            require(pod["uid"] == initial["uid"] and pod["containers"] == initial["containers"], f"{key} restart/replacement")
            require(all(c["ready"] and c["last_termination"] not in {"OOMKilled", "Error"} for c in pod["containers"]), f"{key} container failure")
        require(snapshot["nodes"] and all(n["conditions"] == {"Ready": "True", "MemoryPressure": "False",
                "DiskPressure": "False", "PIDPressure": "False"} for n in snapshot["nodes"]), "node unhealthy/pressured")
        db = snapshot["postgres"]
        require(db["query_ok"] and db["connections"] < db["max_connections"] - db["reserved"] - db["superuser_reserved"],
                "PostgreSQL connection exhaustion")


def validate_measurement(directory):
    directory = Path(directory)
    events = rows(directory / "events.jsonl")
    require(events, "experiment records absent")
    for event in events:
        require(event.get("record") in EVENT_KEYS and set(event) == EVENT_KEYS[event["record"]], "experiment record allowlist differs")
        if event["record"] == "sentinel":
            require(set(event["read"]) == set(event["health"]) == REQUEST_KEYS, "sentinel record allowlist differs")
    require(events[0]["record"] == "run_start" and events[-1]["record"] == "run_end" and
            events[-1]["completed"] is True and events[-1]["run_id"] == events[0]["run_id"], "incomplete experiment")
    require(sum(e["record"] == "run_start" for e in events) == sum(e["record"] == "run_end" for e in events) == 1,
            "duplicated experiment lifecycle")
    plan = events[0]
    require(plan["schema_version"] == 1, "unknown experiment schema")
    config = scenario(plan["scenario"])
    require(plan["scenario_sha256"] == digest(config), "scenario fingerprint differs")
    require(plan["max_attempts"] in {1, 2}, "retry unbounded")
    before, after = read(directory / "before.json"), read(directory / "after.json")
    actual = read(directory / "configuration.json")
    require(actual["hold_ms"] == config["hold_ms"] and actual["route_retries"] == actual["haproxy_retries"] == 0,
            "scenario runtime drift")
    require(any(t.get("maxRequests") == config["max_requests"] for t in actual["cluster"]["circuitBreakers"]["thresholds"]),
            "capacity proof missing")
    attempts = [e for e in events if e["record"] == "attempt"]
    require(all(a["error_class"] in {"none", "http_status", "semantic_error", "timeout", "transport"} and
                (a["status"] is None or type(a["status"]) is int and 100 <= a["status"] <= 599) and
                type(a["semantic_result"]) is bool for a in attempts), "unsafe attempt result")
    operations = [e for e in events if e["record"] == "operation"]
    starts = [e for e in events if e["record"] == "operation_start"]
    require(len(operations) == len(starts) == config["logical_operations"] and
            len({e["operation_id"] for e in operations}) == len(operations), "logical demand differs")
    require({e["operation_id"] for e in starts} == {e["operation_id"] for e in operations}, "operation start correlation differs")
    require(len({e["attempt_id"] for e in attempts}) == len(attempts), "duplicated attempts")
    for operation in operations:
        selected = [a for a in attempts if a["operation_id"] == operation["operation_id"]]
        require(len(selected) == operation["attempt_count"] <= plan["max_attempts"] and selected, "attempt count invalid")
        require([a["attempt_index"] for a in selected] == list(range(1, len(selected) + 1)), "attempt sequence invalid")
        require(all(a["attempt_id"] == f'{operation["operation_id"]}-attempt-{a["attempt_index"]}' and
                    a["end_monotonic"] >= a["start_monotonic"] and
                    abs(a["duration_seconds"] - (a["end_monotonic"] - a["start_monotonic"])) < .00001
                    for a in selected), "attempt ID/timing differs")
        require(all(not a["semantic_result"] for a in selected[:-1]), "retry after success")
        require((operation["outcome"] == "success") == selected[-1]["semantic_result"], "operation outcome differs")
    require(set(a["operation_id"] for a in attempts) == set(o["operation_id"] for o in operations), "orphan attempt")
    if plan["max_attempts"] == 1:
        require(len(attempts) == len(operations), "no-retry attempt count differs")
    samples = [e for e in events if e["record"] == "target_sample"]
    delta = {k: after["stats"][k] - v for k, v in before["stats"].items()}
    require(set(before["stats"]) == set(after["stats"]) == set(actual["stat_names"]), "target stat inventory changed")
    counters = by_suffix(delta)
    require(all(v >= 0 for v in counters.values()), "target counter reset")
    require(counters["upstream_rq_active_overflow"] > 0, "no authoritative active-request overflow")
    require(counters["upstream_rq_pending_overflow"] == 0, "pending overflow is a competing mechanism")
    peak = max((by_suffix(s["stats"])["upstream_rq_active"] for s in samples), default=0)
    require(peak > 0, "outstanding target pressure not sampled")
    failed = [a for a in attempts if not a["semantic_result"]]
    require(failed and all(a["error_class"] == "http_status" for a in failed), "gated impact absent or transport/semantic confounder")
    sentinels = [e for e in events if e["record"] == "sentinel"]
    require(sentinels and all(e["read"]["semantic_result"] and e["health"]["semantic_result"] for e in sentinels),
            "direct path also failed")
    require(any(e["read"]["start_monotonic"] <= a["end_monotonic"] and
                a["start_monotonic"] <= e["read"]["end_monotonic"] for e in sentinels for a in failed),
            "no direct sentinel overlaps gated impact")
    guards = [e["snapshot"] for e in events if e["record"] == "guard"]
    require(guards, "during-run confounder snapshot absent")
    validate_guard([before["guard"]] + guards + [after["guard"]])
    hp_before, hp_after = server_counter(before["haproxy"]), server_counter(after["haproxy"])
    hp_delta = {k: hp_after[k] - hp_before[k] for k in HAPROXY_FIELDS if hp_after[k] is not None and hp_before[k] is not None}
    require(hp_after["status"] in {"UP", "no check"} and hp_after["qcur"] == hp_after["qmax"] == 0 and
            all(hp_delta[k] == 0 for k in ("econ", "eresp", "wretr", "wredis", "cli_abrt", "srv_abrt")), "HAProxy competing limit/error/retry")
    check_count = backend_requests(hp_after) - backend_requests(hp_before)
    require(check_count == len(attempts), "attempt/check dispatch correlation differs")
    path = read(directory / "path.json")
    require(len(path["proxies"]["target"]) == check_count == len(path["proxies"]["ingress"]), "proxy request counts differ")
    rejections = [r for r in path["proxies"]["target"] if r["status"] == 503 and "overflow" in r["details"]]
    require(len(rejections) == counters["upstream_rq_active_overflow"] == len(failed), "target rejection/client impact count differs")
    require(all(r["details"] == "ext_authz_error" and r["upstream_host"] in {None, "-"}
                for r in path["proxies"]["ingress"] if r["status"] != 200), "ingress impact not attributable to ext_authz")
    check_rows = path["checks"]
    if check_rows:
        gate.validate_checks(check_rows)
    require(all(set(r) == {"record", "status", "details", "upstream_cluster", "upstream_host"}
                for rs in path["proxies"].values() for r in rs), "unsafe proxy evidence")
    attempt_ids = {a["attempt_id"]: a for a in attempts}
    require(len(check_rows) == counters["upstream_rq_total"], "admitted app/target count differs")
    require(all(c["decision"] == "ALLOW" and c["attempt_id"] in attempt_ids and
                c["operation_id"] == attempt_ids[c["attempt_id"]]["operation_id"] for c in check_rows), "app check correlation differs")
    require(len(check_rows) + len(rejections) == check_count, "admission accounting differs")
    require(len({c["attempt_id"] for c in check_rows}) == len(check_rows), "duplicate app checks for one HTTP attempt")
    entry = actual["runtime_guard"]["admin_entry"]
    if entry is not None:
        require(str(entry["final_value"]).lower() in {"true", "1"}, "runtime guard contradicts selected behavior")
    return {"logical_operations": len(operations), "attempts": len(attempts), "authorization_checks": check_count,
            "haproxy_backend_requests": check_count, "target_inbound_requests": len(path["proxies"]["target"]),
            "admitted_app_checks": len(check_rows), "client_status_distribution": dict(Counter(str(a["status"]) for a in attempts)),
            "operation_outcomes": dict(Counter(o["outcome"] for o in operations)),
            "active_request_peak": peak, "target_stat_delta": delta, "haproxy_counter_delta": hp_delta,
            "direct_sentinels": len(sentinels), "confounder_snapshots": len(guards) + 2,
            "runtime_guard_effective_behavior": "active overflow without pending overflow; guard unchanged",
            "validity": "valid", "mechanism": "verified", "scenario_sha256": plan["scenario_sha256"]}


def run(out):
    out = Path(out)
    directory = out / "saturation"
    directory.mkdir()
    source = read(out / "source.json")
    config = scenario(read(ROOT / "experiments/fixtures/shared-gate/saturation.json"))
    save(directory / "calibration-plan.json", {"source": source, "scenario": config, "timestamp_utc": utc(),
         "freeze_rule": "single bounded candidate; freeze unchanged only after target proof and confounder guard pass; otherwise stop"})
    target = gate.pod("app=ext-authz-sim")["metadata"]["name"]
    ingress = gate.pod("istio=p4-ingress")["metadata"]["name"]
    path = f'/api/v1/repos/{os.environ["DEV_USER"]}/journey/issues/{os.environ["ISSUE_NUMBER"]}'
    auth = {"Authorization": f'token {os.environ["DEV_TOKEN"]}'}
    expected = (int(os.environ["ISSUE_NUMBER"]), os.environ["ISSUE_TITLE"])
    # Admin traffic has no credentials. Temporary port-forward log stays outside artifacts.
    with (ROOT / ".tmp/p4-w2-admin.log").open("w") as log:
        pf = subprocess.Popen(["kubectl", "-n", "shared-gate", "port-forward", "--address", "127.0.0.1",
                               target, f"{ADMIN}:15000"], stdout=log, stderr=log)
        try:
            deadline = time.monotonic() + 30
            while True:
                try:
                    admin("/server_info")
                    break
                except OSError:
                    require(pf.poll() is None and time.monotonic() < deadline, "target admin unavailable")
                    time.sleep(.1)
            prepare(config, target)
            calibration = measure(directory / "calibration", config, 1, target, ingress, path, auth, expected, digest(config))
            frozen = {"source": source, "scenario": config, "scenario_sha256": digest(config), "timestamp_utc": utc(),
                      "calibration_validity": calibration["validity"], "configuration": configuration(config, target, ingress),
                      "runtime_provenance": read(out / "runtime.json"), "max_attempts": {"no-retry": 1, "retry": 2}}
            save(directory / "frozen.json", frozen)
            for label, attempts in (("no-retry", 1), ("retry", 2)):
                require(read(directory / "frozen.json") == frozen, "frozen scenario changed")
                require(configuration(config, target, ingress) == frozen["configuration"], "runtime changed after freeze")
                summary = measure(directory / label, config, attempts, target, ingress, path, auth, expected, frozen["scenario_sha256"])
                print(f'[saturation:{label}] logical={summary["logical_operations"]} attempts={summary["attempts"]} checks={summary["authorization_checks"]} active_overflow={by_suffix(summary["target_stat_delta"])["upstream_rq_active_overflow"]}', flush=True)
        finally:
            pf.terminate()
            pf.wait(timeout=10)
            (ROOT / ".tmp/p4-w2-admin.log").unlink(missing_ok=True)


def result(out, exploratory=False):
    out = Path(out)
    directory = out / "saturation"
    frozen = read(directory / "frozen.json")
    source = read(out / "source.json")
    require(frozen["source"] == source and (exploratory or not source["dirty"]), "final experiment source differs/dirty")
    require(read(directory / "calibration-plan.json")["scenario"] == frozen["scenario"], "calibration/freeze differs")
    validate_measurement(directory / "calibration")
    require(rows(directory / "calibration" / "events.jsonl")[-1]["timestamp_utc"] < frozen["timestamp_utc"],
            "freeze preceded calibration completion")
    summaries = {label: validate_measurement(directory / label) for label in ("no-retry", "retry")}
    for label in summaries:
        require(read(directory / label / "configuration.json") == frozen["configuration"], "measured topology drift")
        first = rows(directory / label / "events.jsonl")[0]
        require(first["timestamp_utc"] > frozen["timestamp_utc"] and first["scenario"] == frozen["scenario"] and
                first["max_attempts"] == frozen["max_attempts"][label], "run started before freeze or demand changed")
    a, b = summaries["no-retry"], summaries["retry"]
    require(a["logical_operations"] == b["logical_operations"] and b["attempts"] > a["attempts"] and
            b["authorization_checks"] > a["authorization_checks"] and
            b["target_inbound_requests"] > a["target_inbound_requests"], "retry amplification not measured")
    healthy = gate.result(out, exploratory)
    return {"source_sha": source["sha"], "source_dirty": source["dirty"], "completed": True,
            "acceptance": "verified" if not source["dirty"] else "not verified", "scenario": frozen["scenario"],
            "scenario_sha256": frozen["scenario_sha256"], "runs": summaries,
            "healthy_gate_operations": healthy["gated_operations"], "same_cluster_removal": read(out / "removal.json"),
            "amplification": {"attempt_ratio": b["attempts"] / a["attempts"],
                              "check_ratio": b["authorization_checks"] / a["authorization_checks"]},
            "limitations": ["Local Linux/amd64 loopback port-forward proof; no Azure support or SLO claim",
                            "Authorization checks are dispatched HTTP checks, including inbound rejections; app checks count admissions",
                            "Gauge samples may miss brief peaks; config limit is not inferred from peak",
                            "Retry amplification establishes increased request workload; no mitigation benefit claim"]}


if __name__ == "__main__":
    try:
        if sys.argv[1] == "run":
            run(sys.argv[2])
        elif sys.argv[1] == "result":
            print(json.dumps(result(sys.argv[2], "--exploratory" in sys.argv), indent=2))
        else:
            raise ValueError("unknown mode")
    except (ValueError, KeyError, subprocess.SubprocessError, json.JSONDecodeError) as exc:
        print(f"invalid saturation evidence: {exc}", file=sys.stderr)
        sys.exit(1)
