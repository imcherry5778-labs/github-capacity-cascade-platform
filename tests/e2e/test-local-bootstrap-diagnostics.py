#!/usr/bin/env python3
"""Deterministic bootstrap-failure diagnostics ordering, ownership and cleanup cases.

Real local-run/up/down/verify scripts run in a temporary root; k3d, docker, kubectl, curl and sha256sum are
stubs that record calls. No real cluster or Docker access is used.
"""

import json
import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
SCRIPTS = ("local-run.sh", "local-up.sh", "local-down.sh", "local-verify.sh")
OWNED = "server-owned"
POD_SECRET = "POD-SPEC-SECRET-VALUE"
KUBECONFIG_SECRET = "KUBECONFIG-PRIVATE-KEY"
SECRET_PAYLOAD = "SECRET-OBJECT-PAYLOAD"
DIAG = "kubectl --request-timeout=15s"

STUB = r"""#!/usr/bin/env bash
set -u
name="$(basename "$0")"
printf '%s %s\n' "$name" "$*" >>"$STUB_LOG"
server="$STUB_STATE/server"
case "$name" in
  k3d)
    case "$1 $2" in
      "cluster list") if [[ -s "$server" ]]; then echo '[{"name":"capacity-cascade-local"}]'; else echo '[]'; fi ;;
      "cluster create") echo "$STUB_SERVER_ID" >"$server" ;;
      "cluster get") [[ -s "$server" ]]; exit $? ;;
      "cluster delete") [[ "${STUB_DELETE_FAIL:-0}" == 0 ]] || { echo "simulated delete failure" >&2; exit 1; }; rm -f "$server" ;;
      "kubeconfig get") printf 'apiVersion: v1\nusers:\n- user:\n    client-key-data: %s\n' "$STUB_KUBECONFIG_SECRET" ;;
    esac ;;
  docker)
    [[ ! -e "$STUB_STATE/docker-fail" ]] || { echo "simulated docker failure" >&2; exit 1; }
    if [[ "$*" == *"-aq"*"label=k3d.role=server"* ]]; then cat "$server" 2>/dev/null; exit 0; fi
    if [[ -s "$server" && "$1" == ps ]]; then echo k3d-capacity-cascade-local-server-0; fi ;;
  curl)
    while (($#)); do if [[ "$1" == -o ]]; then echo manifest >"$2"; fi; shift; done ;;
  sha256sum) cat >/dev/null ;;
  kubectl)
    args=" $* "
    if [[ "$args" == *" rollout status deployment/${STUB_FAIL_ROLLOUT:-none} "* ]]; then
      case "${STUB_ON_FAIL:-}" in
        replace) echo server-other >"$server" ;;
        docker-fail) touch "$STUB_STATE/docker-fail" ;;
      esac
      echo "error: timed out waiting for the condition" >&2
      exit "${STUB_ROLLOUT_RC:-1}"
    fi
    if [[ "$args" == *" secret"* || "$args" == *" configmap"* ]] && [[ "$args" == *" get "* ]]; then echo "$STUB_SECRET_PAYLOAD"; exit 0; fi
    if [[ "$args" == *" --request-timeout=15s "* ]]; then
      [[ "${STUB_DIAG_FAIL:-0}" == 0 ]] || { echo "simulated API failure" >&2; exit 1; }
      case "$args" in
        *" get nodes "*) cat "$STUB_FIXTURES/nodes.json" ;;
        *" get deployments,statefulsets,jobs "*) cat "$STUB_FIXTURES/workloads.json" ;;
        *" get pods "*) cat "$STUB_FIXTURES/pods.json" ;;
        *" get events "*) cat "$STUB_FIXTURES/events.json" ;;
        *" logs "*) echo "log tail line" ;;
      esac
      exit 0
    fi
    if [[ "$args" == *" get crd "* ]]; then echo '{"status":{"conditions":[{"type":"Established","status":"True"}]}}'; fi ;;
esac
exit 0
"""


def container(name, ready, restarts=0, state=None, last=None, image="quay.io/example:1"):
    status = {"name": name, "image": image, "ready": ready, "restartCount": restarts,
              "state": state or {"running": {"startedAt": "2026-10-14T00:00:00Z"}}, "lastState": last or {}}
    return status


def pod(name, phase, statuses, conditions=(), namespace="argocd"):
    return {
        "metadata": {"namespace": namespace, "name": name},
        "spec": {"nodeName": "k3d-server-0",
                 "containers": [{"name": "main", "env": [{"name": "REDIS_PASSWORD", "value": POD_SECRET}]}]},
        "status": {"phase": phase, "conditions": list(conditions), "containerStatuses": statuses},
    }


FIXTURES = {
    "nodes.json": {"items": [{
        "metadata": {"name": "k3d-server-0"}, "spec": {"taints": [{"key": "node.kubernetes.io/memory-pressure", "effect": "NoSchedule"}]},
        "status": {"allocatable": {"cpu": "2", "memory": "4Gi", "pods": "110"},
                   "conditions": [{"type": "MemoryPressure", "status": "True"}, {"type": "Ready", "status": "True"}]},
    }]},
    "workloads.json": {"items": [{
        "kind": "Deployment", "metadata": {"namespace": "argocd", "name": "argocd-redis"}, "spec": {"replicas": 1},
        "status": {"conditions": [{"type": "Available", "status": "False", "reason": "MinimumReplicasUnavailable"},
                                  {"type": "Progressing", "status": "False", "reason": "ProgressDeadlineExceeded"}]},
    }]},
    "pods.json": {"items": [
        pod("argocd-redis-1", "Running", [container("redis", False, 3,
            {"waiting": {"reason": "CrashLoopBackOff", "message": "back-off restarting failed container"}},
            {"terminated": {"reason": "Error", "exitCode": 1}})]),
        pod("argocd-repo-server-1", "Running", [container("repo-server", False)],
            [{"type": "Ready", "status": "False", "reason": "ContainersNotReady"}]),
        pod("argocd-applicationset-1", "Pending", [container("controller", False, 0,
            {"waiting": {"reason": "ErrImagePull", "message": "failed to pull image quay.io/example:1"}})]),
        pod("argocd-application-controller-0", "Pending", [],
            [{"type": "PodScheduled", "status": "False", "reason": "Unschedulable",
              "message": "0/1 nodes are available: 1 Insufficient memory."}]),
        pod("postgres-0", "Running", [container("postgres", True)], namespace="postgres"),
    ]},
    "events.json": {"items": [
        {"type": "Warning", "reason": "Unhealthy", "count": 4, "lastTimestamp": "2026-10-14T00:02:00Z",
         "metadata": {"namespace": "argocd"}, "involvedObject": {"kind": "Pod", "name": "argocd-repo-server-1"},
         "message": "Readiness probe failed: connection refused"},
        {"type": "Warning", "reason": "FailedScheduling", "lastTimestamp": "2026-10-14T00:01:00Z",
         "metadata": {"namespace": "argocd"}, "involvedObject": {"kind": "Pod", "name": "argocd-application-controller-0"},
         "message": "0/1 nodes are available: 1 Insufficient memory."},
        {"type": "Normal", "reason": "Pulled", "lastTimestamp": "2026-10-14T00:00:30Z",
         "metadata": {"namespace": "postgres"}, "involvedObject": {"kind": "Pod", "name": "postgres-0"}, "message": "ignored"},
    ]},
}


class LocalBootstrapDiagnosticsTest(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        base = Path(temp.name)
        self.root = base / "root"
        (self.root / "scripts").mkdir(parents=True)
        for script in SCRIPTS:
            shutil.copy2(REPO / "scripts" / script, self.root / "scripts" / script)
        shutil.copy2(REPO / "versions.env", self.root / "versions.env")
        tools = self.root / "scripts" / "install-tools.sh"
        tools.write_text("#!/usr/bin/env bash\nexit 0\n")
        tools.chmod(0o755)
        bin_dir = self.root / ".tmp" / "bin"
        bin_dir.mkdir(parents=True)
        for name in ("k3d", "docker", "kubectl", "curl", "sha256sum"):
            (bin_dir / name).write_text(STUB)
            (bin_dir / name).chmod(0o755)
        self.state = base / "state"
        fixtures = base / "fixtures"
        lock_dir = base / "lock"
        for directory in (self.state, fixtures, lock_dir):
            directory.mkdir()
        for name, value in FIXTURES.items():
            (fixtures / name).write_text(json.dumps(value))
        self.log = base / "calls.log"
        self.log.touch()
        self.env = {
            "PATH": os.environ["PATH"], "HOME": str(base), "TMPDIR": str(lock_dir),
            "STUB_LOG": str(self.log), "STUB_STATE": str(self.state), "STUB_FIXTURES": str(fixtures),
            "STUB_SERVER_ID": OWNED, "STUB_KUBECONFIG_SECRET": KUBECONFIG_SECRET,
            "STUB_SECRET_PAYLOAD": SECRET_PAYLOAD, "STUB_FAIL_ROLLOUT": "argocd-redis", "STUB_ROLLOUT_RC": "7",
        }

    def run_script(self, script, **env):
        result = subprocess.run([str(self.root / "scripts" / script)], cwd=self.root, env={**self.env, **env},
                                stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, timeout=120)
        self.calls = self.log.read_text().splitlines()
        self.output = result.stdout
        return result.returncode

    def index(self, prefix):
        return next((i for i, call in enumerate(self.calls) if call.startswith(prefix)), None)

    def diagnostic_calls(self):
        return [call for call in self.calls if call.startswith(DIAG)]

    def server(self):
        path = self.state / "server"
        return path.read_text().strip() if path.exists() else None

    def assert_no_secret_access(self):
        self.assertFalse([c for c in self.calls if c.startswith("kubectl") and " get " in f" {c} " and
                          (" secret" in c or " configmap" in c)])
        for value in (POD_SECRET, KUBECONFIG_SECRET, SECRET_PAYLOAD):
            self.assertNotIn(value, self.output)

    def test_owned_bootstrap_failure_diagnoses_before_cleanup(self):
        self.assertEqual(self.run_script("local-run.sh"), 7)
        pods, delete = self.index(f"{DIAG} get pods"), self.index("k3d cluster delete")
        self.assertIsNotNone(pods)
        self.assertIsNotNone(delete)
        self.assertLess(pods, delete)
        self.assertLess(self.output.index("----- bootstrap diagnostics -----"), self.output.index("deleting k3d cluster"))
        for signal in ("node k3d-server-0 MemoryPressure=True", "taints=node.kubernetes.io/memory-pressure:NoSchedule",
                       "Deployment argocd/argocd-redis", "ProgressDeadlineExceeded", "healthy pods: 1",
                       "container redis image=quay.io/example:1 ready=false restarts=3 state=waiting:CrashLoopBackOff back-off restarting",
                       "last=terminated:Error:1", "state=waiting:ErrImagePull", "failed to pull image",
                       "condition PodScheduled=False Unschedulable 0/1 nodes are available: 1 Insufficient memory.",
                       "condition Ready=False ContainersNotReady", "Readiness probe failed",
                       "event 2026-10-14T00:01:00Z Warning argocd Pod/argocd-application-controller-0 FailedScheduling",
                       "logs argocd/argocd-redis-1/redis previous=true", "logs argocd/argocd-repo-server-1/repo-server previous=false"):
            self.assertIn(signal, self.output)
        self.assertNotIn("postgres-0", self.output.split("healthy pods: 1")[1].split("event ")[0])
        self.assertNotIn("Pulled", self.output)
        self.assertNotIn("logs argocd/argocd-applicationset-1", self.output)
        self.assertTrue(all("--request-timeout=15s" in c for c in self.calls[self.index("kubectl -n argocd rollout status deployment/argocd-redis") + 1:]
                            if c.startswith("kubectl")))
        self.assert_no_secret_access()
        self.assertIsNone(self.server())
        self.assertFalse((self.root / ".tmp" / "kubeconfig").exists())

    def test_diagnostics_failure_keeps_exit_code_and_cleanup(self):
        self.assertEqual(self.run_script("local-run.sh", STUB_DIAG_FAIL="1"), 7)
        self.assertIn("bootstrap diagnostics incomplete", self.output)
        self.assertLess(self.index(f"{DIAG} get nodes"), self.index("k3d cluster delete"))
        self.assertIsNone(self.server())
        self.assertIn("PASS removed runtime output", self.output)

    def test_without_ownership_marker_no_inspection(self):
        # Caller environment의 server_id는 ownership 증거가 아니다.
        self.assertEqual(self.run_script("local-up.sh", server_id=OWNED), 7)
        self.assertEqual(self.diagnostic_calls(), [])
        self.assertNotIn("bootstrap diagnostics", self.output)
        self.assertIsNone(self.index("k3d cluster delete"))
        self.assertEqual(self.server(), OWNED)

    def test_replaced_cluster_not_inspected_or_deleted(self):
        self.assertEqual(self.run_script("local-run.sh", STUB_ON_FAIL="replace"), 7)
        self.assertIn("is not the cluster created by this invocation; not inspecting", self.output)
        self.assertIn("was not created by this invocation", self.output)
        self.assertEqual(self.diagnostic_calls(), [])
        self.assertIsNone(self.index("k3d cluster delete"))
        self.assertEqual(self.server(), "server-other")

    def test_uninspectable_ownership_not_inspected_or_deleted(self):
        self.assertEqual(self.run_script("local-run.sh", STUB_ON_FAIL="docker-fail"), 7)
        self.assertIn("[local-up] cannot inspect cluster ownership; not inspecting", self.output)
        self.assertIn("cannot inspect cluster ownership; leaving cluster", self.output)
        self.assertEqual(self.diagnostic_calls(), [])
        self.assertIsNone(self.index("k3d cluster delete"))
        self.assertEqual(self.server(), OWNED)

    def test_successful_bootstrap_has_no_failure_diagnostics(self):
        marker = self.state / "marker"
        self.assertEqual(self.run_script("local-up.sh", STUB_FAIL_ROLLOUT="none", LOCAL_DEFER_FORGEJO_START="1",
                                         LOCAL_CLUSTER_OWNERSHIP_MARKER=str(marker)), 0)
        self.assertEqual(marker.read_text().strip(), OWNED)
        self.assertEqual(self.diagnostic_calls(), [])
        self.assertNotIn("bootstrap diagnostics", self.output)

    def test_post_bootstrap_failure_does_not_repeat_bootstrap_diagnostics(self):
        # Bootstrap 성공 뒤 baseline(gitops contract)이 실패해도 bootstrap 진단은 실행하지 않고 owned cleanup은 수행한다.
        self.assertNotEqual(self.run_script("local-run.sh", STUB_FAIL_ROLLOUT="none", LOCAL_DEFER_FORGEJO_START="1"), 0)
        self.assertEqual(self.diagnostic_calls(), [])
        self.assertIsNotNone(self.index("k3d cluster delete"))
        self.assertIsNone(self.server())

    def test_cleanup_failure_remains_observable(self):
        self.assertEqual(self.run_script("local-run.sh", STUB_DELETE_FAIL="1"), 7)
        self.assertLess(self.index(f"{DIAG} get pods"), self.index("k3d cluster delete"))
        self.assertIn("k3d cluster delete capacity-cascade-local failed", self.output)
        self.assertIn("FAIL cleanup incomplete", self.output)
        self.assertEqual(self.server(), OWNED)
        self.assertFalse((self.root / ".tmp" / "kubeconfig").exists())


if __name__ == "__main__":
    unittest.main()
