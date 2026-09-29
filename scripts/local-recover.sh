#!/usr/bin/env bash
# One owned source cluster -> coordinated checkpoint -> fresh owned restore cluster.
set -euo pipefail
umask 077
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
# shellcheck source=versions.env
source "$ROOT/versions.env"
export PATH="$ROOT/.tmp/bin:$PATH" KUBECONFIG="$ROOT/.tmp/kubeconfig"
URL=http://127.0.0.1:13000
CHECKPOINT_ID="$(date -u +%Y%m%dT%H%M%SZ)-$(od -An -N3 -tx1 /dev/urandom | tr -d ' \n')"
RAW="$(mktemp -d)"
MARKER="$(mktemp)"
RESULTS="$ROOT/results/local/recovery-$CHECKPOINT_ID"
mkdir -p "$ROOT/results/local"
mkdir -m 0700 "$RESULTS"
PHASES="$RESULTS/phases.jsonl"
PF_PID="" DONE=0 TARGET=0
log() { printf '[recovery] %s\n' "$*"; }
fail() {
  jq -nc --arg reason "$*" --arg time "$(date -u +%Y-%m-%dT%H:%M:%SZ)" \
    '{record:"failure",reason:$reason,timestamp_utc:$time}' >>"$PHASES"
  echo "[recovery] FAIL $*" >&2
  exit 1
}
phase() {
  jq -nc --arg phase "$1" --arg time "$(date -u +%Y-%m-%dT%H:%M:%SZ)" \
    '{phase:$phase,success:true,timestamp_utc:$time}' >>"$PHASES"
  log "$1"
}
stop_pf() {
  if [[ -n "$PF_PID" ]]; then
    kill "$PF_PID" 2>/dev/null || true
    wait "$PF_PID" 2>/dev/null || true
    PF_PID=""
  fi
}
cleanup() {
  local rc="$1" cleanup_rc=0
  trap - EXIT
  set +e
  stop_pf
  if [[ -s "$MARKER" ]]; then
    LOCAL_CLUSTER_OWNERSHIP_MARKER="$MARKER" "$ROOT/scripts/local-down.sh"
    cleanup_rc=$?
    if [[ "$cleanup_rc" -eq 0 && "$TARGET" == 1 ]]; then phase target_cleaned; fi
  fi
  rm -rf "$RAW"
  if [[ ! -e "$RAW" ]]; then phase raw_cleaned; fi
  rm -f "$MARKER"
  if [[ "$rc" -eq 0 && "$cleanup_rc" -ne 0 ]]; then rc="$cleanup_rc"; fi
  if [[ "$rc" -eq 0 && "$DONE" == 1 ]]; then
    jq -s --slurpfile doctor "$RESULTS/doctor-target.json" \
      --arg id "$CHECKPOINT_ID" --arg sha "$SOURCE_SHA" \
      --argjson dirty "$SOURCE_DIRTY" --arg forgejo_version "$FORGEJO_VERSION" \
      --arg forgejo_image "$FORGEJO_IMAGE_ID" --arg postgres_image "$POSTGRES_IMAGE_ID" \
      --arg postgres_version "$POSTGRES_VERSION" \
      --arg chart_version "$FORGEJO_CHART_VERSION" --arg chart_digest "$FORGEJO_CHART_DIGEST" \
      --arg values "$FORGEJO_VALUES_REVISION" \
      --arg source_server "$SOURCE_SERVER" --arg target_server "$TARGET_SERVER" \
      --argjson source_storage "$SOURCE_STORAGE" --argjson target_storage "$TARGET_STORAGE" \
      --argjson components "$COMPONENTS" \
      '{schema_version:1,checkpoint_id:$id,source_sha:$sha,source_dirty:$dirty,completed:true,
        runtime:{forgejo_version:$forgejo_version,forgejo_image_id:$forgejo_image,
          postgres_image_id:$postgres_image,postgres_version:$postgres_version,chart_version:$chart_version,
          chart_digest:$chart_digest,argo_values_revision:$values},
        source_server_id:$source_server,target_server_id:$target_server,
        source_storage:$source_storage,target_storage:$target_storage,components:$components,
        phases:(map({(.phase):.success})|add),pat_identity:"pre_backup_token",
        session_identity:"pre_backup_cookie",
        doctor:{selected_integrity_checks:($doctor[0].selected|map(.name)),
          applicable_status:"pass",paths_status:$doctor[0].paths.status,
          paths_finding:$doctor[0].paths.finding,gc_lfs_status:"not_applicable",
          lfs_start_server:$doctor[0].effective_config.lfs_start_server},
        restore_completed_before_start:true,
        argo_policy:{enabled:true,selfHeal:true,prune:false}}' "$PHASES" >"$RESULTS/result.json"
    python3 "$ROOT/scripts/validate-recovery.py" result "$RESULTS/result.json" || rc=1
  fi
  exit "$rc"
}
trap 'cleanup $?' EXIT

server_id() {
  local id
  id="$(docker ps -aq --no-trunc --filter label=k3d.cluster=capacity-cascade-local --filter label=k3d.role=server)" ||
    fail "cannot inspect cluster server identity"
  [[ -n "$id" && "$id" != *$'\n'* ]] || fail "ambiguous cluster server identity"
  printf '%s' "$id"
}
storage() {
  local namespace="$1" claim="$2" pvc pv_name pv
  pvc="$(kubectl -n "$namespace" get pvc "$claim" -o json)"
  pv_name="$(jq -r '.spec.volumeName // empty' <<<"$pvc")"
  [[ -n "$pv_name" ]] || fail "$claim PV missing"
  pv="$(kubectl get pv "$pv_name" -o json)"
  jq -nc --arg pvc "$(jq -r .metadata.uid <<<"$pvc")" --arg pv "$pv_name" \
    --arg pv_uid "$(jq -r .metadata.uid <<<"$pv")" \
    '{pvc_uid:$pvc,pv_name:$pv,pv_uid:$pv_uid}'
}
storage_pair() {
  local f p
  f="$(storage forgejo forgejo-data)"
  p="$(storage postgres data-postgres-0)"
  jq -nc --argjson forgejo "$f" --argjson postgres "$p" '{forgejo:$forgejo,postgres:$postgres}'
}
app_json() { kubectl --request-timeout=10s -n argocd get application forgejo-local -o json; }
assert_normal_app() {
  app_json | jq -e --arg rev "$FORGEJO_VALUES_REVISION" --arg chart "$FORGEJO_CHART_VERSION" \
    --arg digest "$FORGEJO_CHART_DIGEST" '
    .spec.sources[0].targetRevision == $chart and .spec.sources[1].targetRevision == $rev and
    .spec.syncPolicy.automated == {prune:false,selfHeal:true} and
    .status.sync.status == "Synced" and .status.health.status == "Healthy" and
    .status.sync.revisions == [$digest,$rev] and
    .status.operationState.phase == "Succeeded" and .operation == null' >/dev/null ||
    fail "Application source/policy/operation is not stable"
}
start_pf() {
  stop_pf
  kubectl -n forgejo port-forward --address 127.0.0.1 svc/forgejo-http 13000:3000 >"$RAW/port-forward.log" 2>&1 &
  PF_PID=$!
}
health() {
  local i
  for ((i=0;i<90;i++)); do
    if curl -fsS --max-time 3 "$URL/api/healthz" >/dev/null 2>&1; then return 0; fi
    sleep 2
  done
  fail "Forgejo healthz unavailable"
}
journey() {
  FORGEJO_URL="$URL" JOURNEY_DIR="$RAW/journey" "$ROOT/tests/e2e/forgejo-developer-journey.sh" "$@"
}
protected_session() {
  local status
  status="$(curl -sS --max-time 15 -b "$RAW/cookies" -o "$RAW/protected.html" \
    -w '%{http_code}' "$URL/user/settings")"
  [[ "$status" == 200 ]] || fail "web session invalid"
  grep -qF "$DEV_USER" "$RAW/protected.html" || fail "protected page lacks developer identity"
}
session_login() {
  local csrf status
  curl -fsS --max-time 15 -c "$RAW/cookies" -b "$RAW/cookies" \
    "$URL/user/login" >"$RAW/login.html"
  csrf="$(python3 - "$RAW/login.html" <<'PY'
from html.parser import HTMLParser
from pathlib import Path
import sys
class CSRF(HTMLParser):
    value = ""
    def handle_starttag(self, tag, attrs):
        attributes = dict(attrs)
        if tag == "input" and attributes.get("name") == "_csrf":
            self.value = attributes.get("value", "")
parser = CSRF()
parser.feed(Path(sys.argv[1]).read_text())
print(parser.value)
PY
)"
  DEV_PASSWORD="$DEV_PASSWORD" DEV_USER="$DEV_USER" CSRF="$csrf" python3 - <<'PY' >"$RAW/login-form"
import os
from urllib.parse import urlencode
fields = {"user_name": os.environ["DEV_USER"], "password": os.environ["DEV_PASSWORD"]}
if os.environ["CSRF"]:
    fields["_csrf"] = os.environ["CSRF"]
print(urlencode(fields), end="")
PY
  status="$(curl -sS --max-time 15 -c "$RAW/cookies" -b "$RAW/cookies" \
    -H 'Content-Type: application/x-www-form-urlencoded' --data-binary "@$RAW/login-form" \
    -o "$RAW/login-response" -w '%{http_code}' "$URL/user/login")"
  [[ "$status" == 302 || "$status" == 303 ]] || fail "developer login failed"
  protected_session
  sha256sum "$RAW/cookies" | awk '{print $1}' >"$RAW/cookie.sha"
}
helper_start() {
  jq -nc --arg image "code.forgejo.org/forgejo/forgejo:$FORGEJO_IMAGE_TAG" '
    {apiVersion:"v1",kind:"Pod",metadata:{name:"recovery-data-helper",namespace:"forgejo",
      labels:{"app.kubernetes.io/part-of":"recovery"}},
     spec:{restartPolicy:"Never",containers:[{name:"helper",image:$image,
       command:["sh","-c","sleep 3600"],volumeMounts:[{name:"data",mountPath:"/data"}]}],
       volumes:[{name:"data",persistentVolumeClaim:{claimName:"forgejo-data"}}]}}' |
    kubectl apply -f - >/dev/null
  kubectl -n forgejo wait pod/recovery-data-helper --for=condition=Ready --timeout=180s >/dev/null
}
helper_stop() { kubectl -n forgejo delete pod recovery-data-helper --wait=true >/dev/null; }
component() {
  local name="$1"
  [[ -s "$RAW/$name" ]] || fail "$name is empty"
  jq -nc --arg filename "$name" --argjson size "$(stat -c %s "$RAW/$name")" \
    --arg sha "$(sha256sum "$RAW/$name" | awk '{print $1}')" \
    '{filename:$filename,size:$size,sha256:$sha,result:"success"}'
}
doctor_snapshot() {
  local stage="$1" pod="$2" check rc
  local dir="$RAW/doctor-$stage"
  mkdir -m 0700 "$dir"
  kubectl -n forgejo exec "$pod" -c forgejo -- cat /data/gitea/conf/app.ini >"$dir/app.ini" ||
    fail "$stage doctor config unavailable"
  kubectl -n forgejo exec "$pod" -c forgejo -- env >"$dir/env.txt" ||
    fail "$stage doctor environment unavailable"
  jq -nc --arg version "$FORGEJO_VERSION" --arg image "$FORGEJO_IMAGE_ID" \
    '{forgejo_version:$version,forgejo_image_id:$image}' >"$dir/metadata.json"
  kubectl -n forgejo exec "$pod" -c forgejo -- \
    forgejo doctor check --list --config /data/gitea/conf/app.ini >"$dir/inventory.txt" 2>&1 ||
    fail "$stage doctor inventory unavailable"
  for check in paths check-db-version check-db-consistency check-user-type synchronize-repo-heads; do
    if kubectl -n forgejo exec "$pod" -c forgejo -- \
      forgejo doctor check --run "$check" --config /data/gitea/conf/app.ini \
      >"$dir/$check.txt" 2>&1; then rc=0; else rc=$?; fi
    printf '%s\n' "$rc" >"$dir/$check.exit"
  done
  if [[ "$stage" == source ]]; then
    python3 "$ROOT/scripts/validate-recovery.py" doctor "$dir" - "$RESULTS/doctor-source.json" ||
      fail "unexpected source doctor finding"
  else
    python3 "$ROOT/scripts/validate-recovery.py" doctor "$dir" "$RESULTS/doctor-source.json" \
      "$RESULTS/doctor-target.json" || fail "target doctor differs from healthy source"
  fi
}
wait_paused_app() {
  local i
  for ((i=0;i<120;i++)); do
    if app_json | jq -e --arg rev "$FORGEJO_VALUES_REVISION" --arg chart "$FORGEJO_CHART_VERSION" \
      --arg digest "$FORGEJO_CHART_DIGEST" '
      .spec.sources[0].targetRevision == $chart and .spec.sources[1].targetRevision == $rev and
      .spec.syncPolicy.automated == {enabled:false,prune:false,selfHeal:true} and
      .status.sync.status == "Synced" and .status.health.status == "Healthy" and
      .status.sync.revisions == [$digest,$rev] and
      .status.operationState.phase == "Succeeded" and .operation == null' >/dev/null 2>&1; then
      return 0
    fi
    sleep 2
  done
  fail "paused Application manual sync did not reach Synced/Healthy"
}

[[ ! -e "$ROOT/.tmp/kubeconfig" ]] || fail "pre-existing local runtime output"
SOURCE_SHA="$(git -C "$ROOT" rev-parse HEAD)"
SOURCE_DIRTY=false
[[ -z "$(git -C "$ROOT" status --porcelain --untracked-files=no)" ]] || SOURCE_DIRTY=true
[[ "$SOURCE_DIRTY" == false ]] ||
  log "source checkout has uncommitted work; exact-head CI will be clean"
LOCAL_CLUSTER_OWNERSHIP_MARKER="$MARKER" "$ROOT/scripts/local-up.sh"
SOURCE_SERVER="$(server_id)"
assert_normal_app
start_pf
health
phase source_ready
RECOVERY_FIXTURE=1 FORGEJO_ADMIN_USERNAME="$(kubectl -n forgejo get secret forgejo-admin -o jsonpath='{.data.username}' | base64 -d)" \
  FORGEJO_ADMIN_PASSWORD="$(kubectl -n forgejo get secret forgejo-admin -o jsonpath='{.data.password}' | base64 -d)" \
  journey create
# shellcheck source=/dev/null
source "$RAW/journey/credentials.env"
# shellcheck source=/dev/null
source "$RAW/journey/state.env"
journey verify pre-backup
session_login
phase fixture_ready

SOURCE_STORAGE="$(storage_pair)"
SOURCE_POD="$(kubectl -n forgejo get pod -l app.kubernetes.io/name=forgejo -o jsonpath='{.items[0].metadata.name}')"
[[ "$(kubectl -n forgejo get pod "$SOURCE_POD" -o json | jq -r \
  '.spec.containers[] | select(.name=="forgejo") | .volumeMounts[] | select(.name=="data") | .mountPath')" == /data ]] ||
  fail "persistent application root is not /data"
kubectl -n forgejo exec "$SOURCE_POD" -c forgejo -- ls -1A /data >"$RAW/persistent-root-inventory.txt"
[[ -s "$RAW/persistent-root-inventory.txt" ]] || fail "persistent application root empty"
FORGEJO_IMAGE_ID="$(kubectl -n forgejo get pod "$SOURCE_POD" -o jsonpath='{.status.containerStatuses[0].imageID}')"
POSTGRES_IMAGE_ID="$(kubectl -n postgres get pod postgres-0 -o jsonpath='{.status.containerStatuses[0].imageID}')"
POSTGRES_VERSION="$(kubectl -n postgres exec postgres-0 -c postgres -- psql --version)"
FORGEJO_VERSION="$(curl -fsS "$URL/api/v1/version" | jq -r .version)"
expected_version="$(printf '%s' "$FORGEJO_IMAGE_TAG" | sed 's/-rootless$//')"
[[ "$FORGEJO_VERSION" == "$expected_version"* ]] || fail "Forgejo version drift"
doctor_snapshot source "$SOURCE_POD"
phase source_doctor_calibrated
[[ "$(kubectl -n postgres exec postgres-0 -c postgres -- psql -U postgres -d postgres -tA -c \
  "SELECT string_agg(rolname, ',' ORDER BY rolname) FROM pg_roles WHERE rolcanlogin AND rolname !~ '^pg_';")" == forgejo,postgres ]] ||
  fail "PostgreSQL global role inventory differs from local bootstrap"
[[ "$(kubectl -n postgres exec postgres-0 -c postgres -- psql -U postgres -d postgres -tA -c \
  "SELECT pg_get_userbyid(datdba) FROM pg_database WHERE datname='forgejo';")" == forgejo ]] ||
  fail "Forgejo database owner differs from local bootstrap"
[[ "$(kubectl -n postgres exec postgres-0 -c postgres -- psql -U postgres -d postgres -tA -c \
  "SELECT COALESCE(datacl::text,'DEFAULT') FROM pg_database WHERE datname='forgejo';")" == DEFAULT ]] ||
  fail "Forgejo database grants differ from local bootstrap"
[[ "$(kubectl -n postgres exec postgres-0 -c postgres -- psql -U postgres -d postgres -tA -c \
  "SELECT count(*) FROM pg_auth_members m JOIN pg_roles r ON r.oid=m.member WHERE r.rolname='forgejo';")" == 0 ]] ||
  fail "Forgejo role membership differs from local bootstrap"
phase postgres_bootstrap_inventoried
assert_normal_app
kubectl -n argocd patch application forgejo-local --type=json \
  -p='[{"op":"add","path":"/spec/syncPolicy/automated/enabled","value":false}]' >/dev/null
app_json | jq -e '.spec.syncPolicy.automated == {enabled:false,prune:false,selfHeal:true} and .operation == null' >/dev/null ||
  fail "Argo autosync stop not confirmed"
phase autosync_stopped
kubectl -n forgejo exec "$SOURCE_POD" -c forgejo -- \
  forgejo manager flush-queues --config /data/gitea/conf/app.ini --timeout 2m >"$RAW/flush.log" 2>&1 ||
  fail "Forgejo queue flush failed"
kubectl -n forgejo scale deployment/forgejo --replicas=0 >/dev/null
kubectl -n forgejo wait "pod/$SOURCE_POD" --for=delete --timeout=180s >/dev/null
[[ -z "$(kubectl -n forgejo get pod -l app.kubernetes.io/name=forgejo -o name)" ]] ||
  fail "Forgejo writer remains running"
phase forgejo_stopped

kubectl -n postgres exec postgres-0 -c postgres -- pg_dump -U forgejo -d forgejo -Fc >"$RAW/database.dump"
helper_start
kubectl -n forgejo exec recovery-data-helper -c helper -- tar -C /data -cf - . >"$RAW/application-data.tar"
helper_stop
kubectl -n forgejo get secret forgejo-admin forgejo-db forgejo-inline-config -o json >"$RAW/forgejo-secrets.json"
kubectl -n postgres get secret postgres-credentials -o json >"$RAW/postgres-secret.json"
jq -s '[.[0].items[],.[1]] |
  map({apiVersion:"v1",kind:"Secret",metadata:{name:.metadata.name,namespace:.metadata.namespace},
       type:.type,data:.data})' "$RAW/forgejo-secrets.json" "$RAW/postgres-secret.json" >"$RAW/secrets.json"
COMPONENTS="$(jq -nc --argjson db "$(component database.dump)" \
  --argjson data "$(component application-data.tar)" --argjson secrets "$(component secrets.json)" \
  '{"database.dump":$db,"application-data.tar":$data,"secrets.json":$secrets}')"
jq -n --arg id "$CHECKPOINT_ID" --arg sha "$SOURCE_SHA" --argjson dirty "$SOURCE_DIRTY" \
  --arg server "$SOURCE_SERVER" \
  --arg version "$FORGEJO_VERSION" --arg forgejo_image "$FORGEJO_IMAGE_ID" \
  --arg postgres_image "$POSTGRES_IMAGE_ID" --arg postgres_version "$POSTGRES_VERSION" \
  --arg chart "$FORGEJO_CHART_DIGEST" \
  --arg values "$FORGEJO_VALUES_REVISION" --arg user "$DEV_USER" --arg main "$MAIN_SHA" \
  --arg feature "$FEATURE_SHA" --arg pull "$PR_NUMBER" --arg issue "$ISSUE_NUMBER" \
  --argjson storage "$SOURCE_STORAGE" --argjson components "$COMPONENTS" \
  --argjson root_entries "$(jq -R -s 'split("\n") | map(select(length>0))' "$RAW/persistent-root-inventory.txt")" \
  '{schema_version:1,checkpoint_id:$id,source_sha:$sha,source_dirty:$dirty,source_server_id:$server,
    source_storage:$storage,forgejo_version:$version,forgejo_image_id:$forgejo_image,
    postgres_image_id:$postgres_image,postgres_version:$postgres_version,
    forgejo_chart_digest:$chart,argo_values_revision:$values,
    persistent_root:"/data",persistent_root_entries:$root_entries,
    postgres_bootstrap:"postgres-initdb role/database owner forgejo; no other login roles",
    fixture:{user:$user,repository:"journey",main_sha:$main,feature_sha:$feature,
      pull_number:$pull,issue_number:$issue,pat_precheck:true,session_precheck:true},
    components:$components,backup_complete:true}' >"$RAW/manifest.json"
python3 "$ROOT/scripts/validate-recovery.py" bundle "$RAW" >/dev/null
cp "$RAW/manifest.json" "$RESULTS/checkpoint.json"
phase bundle_validated

stop_pf
LOCAL_CLUSTER_OWNERSHIP_MARKER="$MARKER" "$ROOT/scripts/local-down.sh"
phase source_cleaned
: >"$MARKER"
LOCAL_RESTORE_SECRETS_FILE="$RAW/secrets.json" LOCAL_CLUSTER_OWNERSHIP_MARKER="$MARKER" "$ROOT/scripts/local-up.sh"
TARGET=1
TARGET_SERVER="$(server_id)"
[[ "$TARGET_SERVER" != "$SOURCE_SERVER" ]] || fail "source cluster reused"
[[ -z "$(kubectl -n forgejo get pod -o name)" ]] || fail "Forgejo started on un-restored target"
phase target_prepared

# The initdb script recreated role, database, owner and password on new PG storage.
# This PVC has the exact claim contract from the pinned chart's rendered manifest.
kubectl -n forgejo apply -f - >/dev/null <<'YAML'
apiVersion: v1
kind: PersistentVolumeClaim
metadata:
  name: forgejo-data
  namespace: forgejo
  annotations:
    helm.sh/resource-policy: keep
spec:
  accessModes: [ReadWriteOnce]
  volumeMode: Filesystem
  resources:
    requests:
      storage: 10Gi
YAML
helper_start
TARGET_STORAGE="$(storage_pair)"
jq -e --argjson source "$SOURCE_STORAGE" --argjson target "$TARGET_STORAGE" -n '
  all(["forgejo","postgres"][]; . as $name |
    $source[$name].pvc_uid != $target[$name].pvc_uid and
    $source[$name].pv_name != $target[$name].pv_name and
    $source[$name].pv_uid != $target[$name].pv_uid)' >/dev/null ||
  fail "fresh storage identity not proven"
jq -n --arg server "$TARGET_SERVER" --argjson storage "$TARGET_STORAGE" \
  '{target_server_id:$server,target_storage:$storage}' >"$RESULTS/target-identity.json"
python3 "$ROOT/scripts/validate-recovery.py" bundle "$RAW" >/dev/null
kubectl -n postgres exec -i postgres-0 -c postgres -- \
  pg_restore -U forgejo -d forgejo --exit-on-error --no-owner <"$RAW/database.dump" >"$RAW/pg-restore.log" 2>&1 ||
  fail "PostgreSQL restore failed"
phase database_restored
kubectl -n forgejo exec -i recovery-data-helper -c helper -- \
  tar -C /data -xf - <"$RAW/application-data.tar" >"$RAW/data-restore.log" 2>&1 ||
  fail "application data restore failed"
kubectl -n forgejo exec recovery-data-helper -c helper -- test -f /data/gitea/conf/app.ini ||
  fail "restored app.ini missing"
helper_stop
phase application_data_restored
for secret in forgejo-admin forgejo-db forgejo-inline-config; do
  actual="$(kubectl -n forgejo get secret "$secret" -o json | jq -Sc .data | sha256sum | awk '{print $1}')"
  expected="$(jq -Sc --arg name "$secret" '.[]|select(.metadata.name==$name and .metadata.namespace=="forgejo")|.data' "$RAW/secrets.json" | sha256sum | awk '{print $1}')"
  [[ "$actual" == "$expected" ]] || fail "$secret continuity failed"
done
phase secrets_restored
[[ -z "$(kubectl -n forgejo get pod -o name)" ]] || fail "Forgejo started before complete restore"
python3 - "$ROOT/platform/argocd/forgejo-local.yaml" "$RAW/paused-app.yaml" <<'PY'
from pathlib import Path
import sys
source = Path(sys.argv[1]).read_text()
assert source.count("    automated:\n") == 1
Path(sys.argv[2]).write_text(source.replace("    automated:\n", "    automated:\n      enabled: false\n"))
PY
kubectl -n argocd apply -f "$RAW/paused-app.yaml" >/dev/null
app_json | jq -e '.spec.syncPolicy.automated == {enabled:false,prune:false,selfHeal:true} and .operation == null' >/dev/null ||
  fail "target Application not paused before manual sync"
kubectl -n argocd patch application forgejo-local --type=merge \
  -p='{"operation":{"initiatedBy":{"username":"local-recovery"},"sync":{"syncStrategy":{"hook":{}}}}}' >/dev/null
wait_paused_app
kubectl -n forgejo rollout status deployment/forgejo --timeout=300s >/dev/null
phase forgejo_started
start_pf
health
phase healthz

TARGET_POD="$(kubectl -n forgejo get pod -l app.kubernetes.io/name=forgejo -o jsonpath='{.items[0].metadata.name}')"
[[ "$(kubectl -n forgejo get pod "$TARGET_POD" -o jsonpath='{.status.containerStatuses[0].imageID}')" == "$FORGEJO_IMAGE_ID" ]] ||
  fail "Forgejo imageID differs from checkpoint"
[[ "$(kubectl -n postgres get pod postgres-0 -o jsonpath='{.status.containerStatuses[0].imageID}')" == "$POSTGRES_IMAGE_ID" ]] ||
  fail "PostgreSQL imageID differs from checkpoint"
[[ "$(curl -fsS "$URL/api/v1/version" | jq -r .version)" == "$FORGEJO_VERSION" ]] ||
  fail "Forgejo version differs from checkpoint"
doctor_snapshot target "$TARGET_POD"
phase target_doctor_verified
journey verify post-restore
phase retained_state
phase same_pat
[[ "$(sha256sum "$RAW/cookies" | awk '{print $1}')" == "$(cat "$RAW/cookie.sha")" ]] ||
  fail "session cookie changed before restore verification"
protected_session
phase same_session
journey write
journey verify post-write
phase new_write
# shellcheck source=/dev/null
source "$RAW/journey/post-write.env"
[[ "$(kubectl -n postgres exec postgres-0 -c postgres -- psql -U forgejo -d forgejo -tA -c \
  "SELECT count(*) FROM issue i JOIN repository r ON r.id=i.repo_id JOIN \"user\" u ON u.id=r.owner_id WHERE u.lower_name='$DEV_USER' AND r.lower_name='journey' AND i.is_pull=false;")" == 2 ]] ||
  fail "new Issue not present in restored PostgreSQL"
phase database_write
[[ "$(kubectl -n forgejo exec "$TARGET_POD" -c forgejo -- \
  git --git-dir="/data/git/gitea-repositories/$DEV_USER/journey.git" rev-parse refs/heads/main)" == "$POST_SHA" ]] ||
  fail "new main commit not present on restored persistent volume"
phase filesystem_write
kubectl -n argocd patch application forgejo-local --type=json \
  -p='[{"op":"remove","path":"/spec/syncPolicy/automated/enabled"}]' >/dev/null
"$ROOT/scripts/local-verify.sh" gitops-ready
assert_normal_app
phase argo_return
journey verify post-reconciliation
phase post_reconcile_state
stop_pf
"$ROOT/scripts/local-verify.sh" runtime
phase regression
DONE=1
