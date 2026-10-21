#!/usr/bin/env python3
"""P4-W1 rendering and narrow runtime evidence. Raw proxy config is never retained."""
import csv
import hashlib
import importlib.util
import io
import json
import os
from pathlib import Path
import re
import subprocess
import sys

sys.dont_write_bytecode = True

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "experiments/fixtures/shared-gate"
spec = importlib.util.spec_from_file_location("operations", ROOT / "scripts/validate-operation-results.py")
operations = importlib.util.module_from_spec(spec)
spec.loader.exec_module(operations)
CHECK_KEYS = {"record", "check_id", "timestamp_utc", "operation_id", "attempt_id", "decision",
              "header_names", "credential_values_absent", "body_absent", "haproxy_hop", "controlled_deny"}


def require(condition, message):
    if not condition:
        raise ValueError(message)


def pins():
    return dict(line.split("=", 1) for line in (ROOT / "versions.env").read_text().splitlines()
                if line and not line.startswith("#"))


def command(*args):
    return subprocess.check_output(args, text=True, timeout=60)


def kube(*args):
    return command("kubectl", "--request-timeout=30s", *args)


def proxy_config(pod, kind):
    return json.loads(command(str(ROOT / f'.tmp/p4-tools/istio-{pins()["ISTIO_VERSION"]}/bin/istioctl'),
                              "proxy-config", kind, pod, "-n", "shared-gate", "-o", "json"))


def render(directory):
    out = Path(directory)
    out.mkdir(parents=True, exist_ok=True)
    values = pins() | {"EXT_AUTHZ_IMAGE": os.environ.get("EXT_AUTHZ_IMAGE", "ext-authz-sim:static")}
    for name in ("istio.yaml", "resources.yaml"):
        source = (FIXTURE / name).read_text()
        for key, value in values.items():
            source = source.replace(f"@{key}@", value)
        require("@ISTIO_" not in source and "@EXT_AUTHZ_" not in source and "@HAPROXY_" not in source, "unrendered pin")
        (out / name).write_text(source)


def owned_image_node():
    """Read-only diagnostics must have the same ownership proof as the fixture."""
    owner = Path(os.environ["LOCAL_CLUSTER_OWNERSHIP_MARKER"]).read_text().strip()
    current = command("docker", "ps", "-aq", "--no-trunc", "--filter",
                      "label=k3d.cluster=capacity-cascade-local", "--filter", "label=k3d.role=server").strip()
    require(owner and current == owner, "image inspection requires invocation-owned server")
    node = command("docker", "inspect", "--format", "{{.Name}}", owner).strip().lstrip("/")
    nodes = json.loads(kube("get", "nodes", "-o", "json"))["items"]
    require([n["metadata"]["name"] for n in nodes] == [node], "fixture requires one owned Kubernetes node")
    return node


def image_inventory(node):
    images = json.loads(command("docker", "exec", node, "crictl", "images", "-o", "json"))["images"]
    # Never retain full CRI inspect output (image config/environment).
    return [{"id": i["id"], "tags": i.get("repoTags", [])} for i in images]


def match_image(images, reference, image_id):
    matches = [i for i in images if reference in i["tags"]]
    require(len(matches) == 1, "exact fixture image reference absent/ambiguous in node CRI")
    require(matches[0]["id"] == image_id, "fixture Docker/CRI image ID mismatch")
    return matches[0]


def image_check(directory, scheduled=False):
    out = Path(directory)
    node = owned_image_node()
    reference = "docker.io/library/" + os.environ["EXT_AUTHZ_IMAGE"]
    data = {"node": node, "reference": reference, "images": image_inventory(node)}
    if scheduled:
        target = pod("app=ext-authz-sim")
        app = next(c for c in target["spec"]["containers"] if c["name"] == "app")
        data["pod"] = {"name": target["metadata"]["name"], "node": target["spec"]["nodeName"],
                       "image": app["image"], "pull_policy": app["imagePullPolicy"]}
    # Write observations even if validation fails; no successful result is synthesized.
    (out / ("image-scheduled.json" if scheduled else "image-import.json")).write_text(json.dumps(data, indent=2))
    match_image(data["images"], reference, json.loads((out / "app-image.json").read_text())["image_id"])
    if scheduled:
        require(data["pod"]["node"] == node and data["pod"]["image"] == os.environ["EXT_AUTHZ_IMAGE"] and
                data["pod"]["pull_policy"] == "Never", "scheduled fixture image/node/pull policy differs")


IMAGE_HINTS = ("ErrImageNeverPull", "not present with pull policy of Never", "no such file or directory",
               "not found", "failed to import", "Successfully imported", "naming to", "exporting to image",
               "unpacking", "image garbage collection", "ImageGCFailed", "FreeDiskSpaceFailed",
               "DiskPressure", "eviction", "no space left", "failed to get image", "RemoveImage")


def image_hints(message):
    return [hint for hint in IMAGE_HINTS if hint.lower() in (message or "").lower()]


def image_diagnostics(directory, workdir):
    out, work = Path(directory), Path(workdir)
    node = owned_image_node()
    data = {"node": node, "image": os.environ.get("EXT_AUTHZ_IMAGE"), "logs": {}}
    # Only these fixed, credential-free build/import commands are retained. No Pod/app logs,
    # environment, Docker inspect config, kubeconfig or raw node log is exported.
    for name in ("build", "import"):
        path = work / f"{name}.log"
        if path.exists():
            text = path.read_text(errors="replace")
            text = text.replace(str(ROOT), "<repository>")
            text = re.sub(r"/(?:home|Users|tmp|var|run|k3d)/[^\s\"'<>]*", "<path>", text)
            text = re.sub(r"\x1b\[[0-9;]*m", "", text)
            (out / f"image-{name}.log").write_text(text)
            exit_path = work / f"{name}.exit"
            data["logs"][name] = {"exit_code": int(exit_path.read_text()) if exit_path.exists() else None,
                                  "hints": image_hints(text)}
    # Persist each stage independently so a later diagnostic failure cannot erase earlier evidence.
    def save():
        (out / "image-failure.json").write_text(json.dumps(data, indent=2))
    save()
    data["images"] = image_inventory(node)
    data["ctr_references"] = command("docker", "exec", node, "ctr", "-n", "k8s.io", "images", "ls", "-q").splitlines()
    save()
    pods = json.loads(kube("-n", "shared-gate", "get", "pods", "-l", "app=ext-authz-sim", "-o", "json"))
    data["pods"] = [{"name": p["metadata"]["name"], "node": p["spec"].get("nodeName"),
                     "images": [{"name": c["name"], "image": c["image"], "pull_policy": c["imagePullPolicy"]}
                                for c in p["spec"]["containers"]],
                     "waiting": [{"name": c["name"], "reason": c.get("state", {}).get("waiting", {}).get("reason"),
                                  "hints": image_hints(c.get("state", {}).get("waiting", {}).get("message"))}
                                 for c in p["status"].get("containerStatuses", [])]}
                    for p in pods["items"]]
    events = json.loads(kube("-n", "shared-gate", "get", "events", "-o", "json"))["items"]
    data["events"] = [{"reason": e.get("reason"), "object": e["involvedObject"]["name"],
                       "timestamp": e.get("lastTimestamp"), "count": e.get("count"),
                       "hints": image_hints(e.get("message"))} for e in events
                      if e["involvedObject"]["name"].startswith("ext-authz-sim-")]
    save()
    # Project node/containerd messages onto fixed hints; never retain raw node logs.
    for label, args in (("kubelet", ("docker", "logs", "--since", "10m", node)),
                        ("containerd", ("docker", "exec", node, "tail", "-n", "1000",
                                        "/var/lib/rancher/k3s/agent/containerd/containerd.log"))):
        log = subprocess.run(args, text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=10)
        data[label] = [{"hints": image_hints(line), "fixture_reference": data["image"] in line if data["image"] else False}
                       for line in log.stdout.splitlines() if image_hints(line)]
        save()


def auth_filter(listeners):
    filters = [f["typedConfig"] for listener in listeners
               for chain in listener.get("filterChains", []) for network in chain.get("filters", [])
               for f in network.get("typedConfig", {}).get("httpFilters", [])
               if f.get("name") == "envoy.filters.http.ext_authz"]
    require(filters, "ingress ext_authz filter absent")
    expected = {"x-operation-id", "x-attempt-id", "x-gate-test-deny"}
    for f in filters:
        require({p.get("exact") for p in f["allowedHeaders"]["patterns"]} == expected, "check header allowlist drift")
        require(not f.get("withRequestBody"), "check body buffering enabled")
        require(not f.get("failureModeAllow", False), "ext_authz is fail-open")
        require(f["httpService"]["serverUri"]["cluster"] ==
                "outbound|8080||haproxy.shared-gate.svc.cluster.local", "HAProxy provider bypassed")
        require(f["httpService"]["authorizationRequest"]["headersToAdd"] ==
                [{"key": "authorization", "value": "p4-check-without-credentials"}],
                "check credential replacement absent")
    return {"allowed_headers": sorted(expected), "with_request_body": False, "failure_mode_allow": False,
            "cluster": filters[0]["httpService"]["serverUri"]["cluster"],
            "authorization_check_value": "p4-check-without-credentials"}


def target_cluster(clusters, max_requests=1024):
    targets = [c for c in clusters if c.get("name", "").startswith("inbound|8080||")]
    require(len(targets) == 1, "target inbound cluster absent/ambiguous")
    cluster = targets[0]
    require(any(t.get("maxRequests") == max_requests for t in cluster["circuitBreakers"]["thresholds"]), "inbound maxRequests differs")
    return {key: cluster[key] for key in ("name", "type", "circuitBreakers")} | {"altStatName": cluster.get("altStatName")}


def log_fields(listeners):
    formats = [log["typedConfig"]["logFormat"]["jsonFormat"] for listener in listeners
               for chain in listener.get("filterChains", []) for network in chain.get("filters", [])
               for log in network.get("typedConfig", {}).get("accessLog", [])
               if log.get("name") == "envoy.access_loggers.file"]
    fields = {"record", "status", "details", "upstream_cluster", "upstream_host"}
    require(formats and all(set(f) == fields and f["record"] == "proxy_request" for f in formats),
            "proxy log allowlist differs")
    return sorted(fields)


def pod(label):
    data = json.loads(kube("-n", "shared-gate", "get", "pods", "-l", label, "-o", "json"))["items"]
    require(len(data) == 1, "fixture pod inventory is ambiguous")
    return data[0]


def active_containers(data):
    # Selected Istio can inject a Kubernetes native sidecar (restartable init).
    return data["spec"]["containers"] + [c for c in data["spec"].get("initContainers", [])
                                         if c.get("restartPolicy") == "Always"]


def identity(data):
    statuses = {c["name"]: c for c in data["status"].get("initContainerStatuses", []) + data["status"]["containerStatuses"]}
    return {"uid": data["metadata"]["uid"], "containers": [
        {"name": c["name"], "image": c["image"], "image_id": statuses[c["name"]]["imageID"],
         "ready": statuses[c["name"]]["ready"], "native_sidecar": c.get("restartPolicy") == "Always"}
        for c in active_containers(data)]}


def runtime():
    target, ingress, haproxy = pod("app=ext-authz-sim"), pod("istio=p4-ingress"), pod("app=haproxy")
    names = [d["metadata"]["name"] for d in (target, ingress, haproxy)]
    require({c["name"] for c in active_containers(target)} == {"app", "istio-proxy"}, "target sidecar absent")
    require([c["name"] for c in active_containers(haproxy)] == ["haproxy"], "HAProxy has injected sidecar")
    images = pins()
    for data in (target, ingress):
        require(next(c["image"] for c in active_containers(data) if c["name"] == "istio-proxy") == images["ISTIO_PROXY_IMAGE"], "proxy pin drift")
    require(haproxy["spec"]["containers"][0]["image"] == images["HAPROXY_IMAGE"], "HAProxy pin drift")
    pilot = json.loads(kube("-n", "istio-system", "get", "pods", "-l", "app=istiod", "-o", "json"))["items"]
    require(len(pilot) == 1 and pilot[0]["spec"]["containers"][0]["image"] == images["ISTIO_PILOT_IMAGE"], "pilot pin drift")
    ingress_listeners = proxy_config(names[1], "listeners")
    auth = auth_filter(ingress_listeners)
    proxy_logs = {"ingress": log_fields(ingress_listeners), "target": log_fields(proxy_config(names[0], "listeners"))}
    routes = [r for config in proxy_config(names[1], "routes") for host in config.get("virtualHosts", [])
              for r in host.get("routes", []) if r.get("route", {}).get("cluster") ==
              "outbound|3000||forgejo-http.forgejo.svc.cluster.local"]
    require(routes and all(r["route"].get("retryPolicy", {}).get("numRetries", 0) == 0 for r in routes),
            "Forgejo ingress route absent or retries enabled")
    cluster = target_cluster(proxy_config(names[0], "clusters"))
    version = json.loads(kube("-n", "shared-gate", "exec", names[0], "-c", "istio-proxy", "--", "pilot-agent", "request", "GET", "server_info"))
    require(version["version"].startswith(images["ISTIO_PROXY_COMMIT"] + "/"), "proxy build commit differs")
    stats = kube("-n", "shared-gate", "exec", names[0], "-c", "istio-proxy", "--", "pilot-agent", "request", "GET", "stats")
    selected_stats = {}
    observed_stat_names = []
    stat_prefixes = [f"cluster.{name}." for name in (cluster["name"], cluster.get("altStatName")) if name]
    for line in stats.splitlines():
        if ": " in line:
            observed_stat_names.append(line.rsplit(": ", 1)[0])
        if any(line.startswith(prefix) for prefix in stat_prefixes):
            key, value = line.rsplit(": ", 1)
            if value.isdigit():
                selected_stats[key] = int(value)
    config = kube("-n", "shared-gate", "exec", names[2], "-c", "haproxy", "--", "cat", "/config/haproxy.cfg")
    haproxy_version = kube("-n", "shared-gate", "exec", names[2], "-c", "haproxy", "--", "haproxy", "-v").splitlines()[0]
    require("3.4.6" in haproxy_version, "unexpected HAProxy version")
    return {"istio_version": images["ISTIO_VERSION"], "pilot": identity(pilot[0]),
            "target": identity(target), "ingress": identity(ingress), "haproxy": identity(haproxy),
            "envoy_version": version["version"], "auth_filter": auth, "inbound_cluster": cluster,
            "proxy_build_commit": images["ISTIO_PROXY_COMMIT"], "upstream_recipe_envoy_commit": images["ENVOY_RECIPE_COMMIT"],
            "forgejo_route": {"cluster": routes[0]["route"]["cluster"], "num_retries": 0},
            "proxy_log_fields": proxy_logs,
            "target_stat_inventory": selected_stats, "candidate_overflow_present":
            any(key.endswith(".upstream_rq_active_overflow") for key in selected_stats),
            "observed_proxy_stat_names": sorted(set(observed_stat_names)),
            "haproxy_version": haproxy_version, "haproxy_config_sha256": hashlib.sha256(config.encode()).hexdigest()}


def capture(directory):
    out = Path(directory)
    target, ingress, haproxy = (pod(label)["metadata"]["name"] for label in
                                ("app=ext-authz-sim", "istio=p4-ingress", "app=haproxy"))
    checks = [json.loads(line) for line in kube("-n", "shared-gate", "logs", target, "-c", "app").splitlines()]
    # Derived snapshots are immutable; append-only app log is the raw check authority.
    with (out / "checks.jsonl").open("x") as f:
        for row in checks:
            require(set(row) == CHECK_KEYS, "unsafe check fields")
            f.write(json.dumps(row) + "\n")
    validate_checks(checks)
    proxies = {}
    for label, name in (("target", target), ("ingress", ingress)):
        records = []
        for line in kube("-n", "shared-gate", "logs", name, "-c", "istio-proxy").splitlines():
            if not line.startswith("{"):
                continue
            row = json.loads(line)
            if row.get("record") == "proxy_request":
                require(set(row) == {"record", "status", "details", "upstream_cluster", "upstream_host"}, "unsafe proxy log")
                row["status"] = int(row["status"])
                records.append(row)
        proxies[label] = records
    csv_text = kube("-n", "shared-gate", "exec", haproxy, "-c", "haproxy", "--",
                    "wget", "-qO-", "http://127.0.0.1:8404/stats;csv")
    reader = csv.DictReader(io.StringIO(csv_text.removeprefix("# ")))
    counters = [{key: row[key] for key in ("pxname", "svname", "stot", "hrsp_2xx", "hrsp_4xx", "hrsp_5xx")}
                for row in reader if row["pxname"] == "ext_authz"]
    require(counters, "HAProxy backend stats absent")
    return {"proxy_requests": proxies, "haproxy_backend": counters}


def validate_checks(rows):
    require(rows and len({r["check_id"] for r in rows}) == len(rows), "check IDs absent/duplicated")
    for r in rows:
        require(set(r) == CHECK_KEYS and r["record"] == "authorization_check", "check allowlist violation")
        require(r["body_absent"] and r["credential_values_absent"] and r["haproxy_hop"], "check leaks body/credentials or bypasses HAProxy")
        require(not {"cookie", "proxy-authorization", "transfer-encoding"}.intersection(r["header_names"]), "unsafe check header")
        require(r["decision"] in {"ALLOW", "DENY"}, "check decision invalid")


def result(directory, exploratory=False):
    out = Path(directory)
    source = json.loads((out / "source.json").read_text())
    require(exploratory or not source["dirty"], "dirty run is not final proof")
    runtime_data = json.loads((out / "runtime.json").read_text())
    require(runtime_data["inbound_cluster"]["circuitBreakers"]["thresholds"][0]["maxRequests"] == 1024, "capacity evidence drift")
    checks = [json.loads(line) for line in (out / "checks.jsonl").read_text().splitlines()]
    validate_checks(checks)
    runs = {}
    for label in ("gated", "post-removal"):
        paths = list((out / label).glob("*/events.jsonl"))
        require(len(paths) == 1, "journey inventory differs")
        validated = operations.validate(paths[0])
        require(validated["validity"] == "valid" and validated["completion"] == "success" and
                validated["operation_count"] == validated["attempt_count"] == 9, "journey failed")
        rows = [json.loads(line) for line in paths[0].read_text().splitlines()]
        require(rows[0]["source_sha"] == source["sha"] and rows[0]["dirty"] == source["dirty"], "journey source drift")
        require(rows[0]["parameters"]["client_retry"] is False and rows[0]["parameters"]["max_attempts"] == 1, "client retries enabled")
        runs[label] = rows
    correlation_counts = {}
    for attempt in (row for row in runs["gated"] if row["record"] == "attempt"):
        matched = [c for c in checks if c["attempt_id"] == attempt["attempt_id"] and
                   c["operation_id"] == attempt["operation_id"]]
        require(matched and all(c["decision"] == "ALLOW" for c in matched), "developer attempt did not traverse gate")
        correlation_counts[attempt["attempt_id"]] = len(matched)
    baseline = json.loads((out / "direct-baseline.json").read_text())
    require(baseline["source_sha"] == source["sha"] and baseline["operation_samples"] == baseline["attempt_samples"] == 45, "direct baseline differs")
    deny = json.loads((out / "deny.json").read_text())
    require(deny == {"status": 403, "decision_header": "DENY", "body_bytes": 0,
                     "sentinel_credentials_and_body_sent": True}, "controlled DENY proof failed")
    require(any(c["controlled_deny"] and c["decision"] == "DENY" for c in checks), "DENY check absent")
    path = json.loads((out / "path.json").read_text())
    require(any(r["details"] == "ext_authz_denied" and r["status"] == 403 and
                r["upstream_host"] in {None, "-"} for r in path["proxy_requests"]["ingress"]), "DENY did not prevent original upstream request")
    target_names = {runtime_data["inbound_cluster"]["name"], runtime_data["inbound_cluster"].get("altStatName")} - {None}
    require(any(r["upstream_cluster"] in target_names for r in path["proxy_requests"]["target"]), "inbound Envoy path absent")
    require(any(r["svname"] == "app" and int(r["stot"]) >= len(checks) for r in path["haproxy_backend"]), "HAProxy hop count differs")
    removal = json.loads((out / "removal.json").read_text())
    require(set(removal) == {"namespaces_absent", "istio_crds_absent", "owned_cluster_resources_absent",
                            "reliability_endpoint_absent", "stable_forgejo_spec_and_uid_unchanged",
                            "argo_synced_healthy", "same_owned_cluster"} and all(v is True for v in removal.values()),
            "fixture removal proof failed")
    phases = [json.loads(line)["phase"] for line in (out / "phases.jsonl").read_text().splitlines()]
    healthy_phases = ["start", "direct-baseline", "install", "configuration", "deny", "gated", "remove", "post-removal"]
    require(phases in (healthy_phases, healthy_phases[:6] + ["saturation"] + healthy_phases[6:]), "lifecycle order differs")
    return {"source_sha": source["sha"], "source_dirty": source["dirty"], "completed": True,
            "acceptance": "verified" if not source["dirty"] else "not verified",
            "authorization_checks": len(checks), "attempt_check_counts": correlation_counts,
            "direct_operations": 45, "gated_operations": 9, "post_removal_operations": 9,
            "limitations": ["Local Linux/amd64 HTTP port-forward proof; Azure API selection remains REVALIDATE",
                            "No saturation, calibration, retry amplification or overflow-signal validation in P4-W1"]}


if __name__ == "__main__":
    try:
        mode = sys.argv[1]
        if mode == "render":
            render(sys.argv[2])
        elif mode == "image-check":
            image_check(sys.argv[2], "scheduled" in sys.argv[3:])
        elif mode == "image-diagnostics":
            image_diagnostics(sys.argv[2], sys.argv[3])
        elif mode == "runtime":
            print(json.dumps(runtime(), indent=2))
        elif mode == "capture":
            print(json.dumps(capture(sys.argv[2]), indent=2))
        elif mode == "probe":
            target = pod("app=ext-authz-sim")["metadata"]["name"]
            rows = [json.loads(line) for line in kube("-n", "shared-gate", "logs", target, "-c", "app").splitlines()]
            validate_checks(rows)
            require(any(r["controlled_deny"] and r["decision"] == "DENY" for r in rows), "sentinel DENY absent")
        elif mode == "result":
            print(json.dumps(result(sys.argv[2], "--exploratory" in sys.argv), indent=2))
        else:
            raise ValueError("unknown mode")
    except (ValueError, KeyError, StopIteration, json.JSONDecodeError) as exc:
        print(f"invalid shared-gate evidence: {exc}", file=sys.stderr)
        sys.exit(1)
