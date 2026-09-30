#!/usr/bin/env bash
# One owned source cluster -> coordinated checkpoint -> fresh owned restore cluster.
set -euo pipefail
umask 077
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
# shellcheck source=versions.env
source "$ROOT/versions.env"
MODE="${1:-recovery}"
[[ "$MODE" == recovery || "$MODE" == upgrade ]] || { echo "usage: local-recover.sh [recovery|upgrade]" >&2; exit 1; }
export PATH="$ROOT/.tmp/bin:$PATH" KUBECONFIG="$ROOT/.tmp/kubeconfig" PYTHONDONTWRITEBYTECODE=1
URL=http://127.0.0.1:13000
CHECKPOINT_ID="$(date -u +%Y%m%dT%H%M%SZ)-$(od -An -N3 -tx1 /dev/urandom | tr -d ' \n')"
RAW="$(mktemp -d)"
MARKER="$(mktemp)"
RESULTS="$ROOT/results/local/$MODE-$CHECKPOINT_ID"
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
    if [[ "$MODE" == upgrade ]]; then
      python3 "$ROOT/scripts/validate-upgrade.py" finalize "$RESULTS" || rc=1
    else
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
assert_no_pods() {
  local pods
  pods="$(kubectl --request-timeout=10s -n forgejo get pod -o name "$@")" || fail "cannot inspect Forgejo writer absence"
  [[ -z "$pods" ]] || fail "Forgejo writer/helper remains"
}
assert_no_credentials() {
  local rc=0
  "$@" || rc=$?
  [[ "$rc" == 1 ]] || fail "credential scan found exposure or could not inspect evidence"
}
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
  local command=doctor
  [[ "$MODE" != upgrade ]] || command=doctor-upgrade
  if [[ "$stage" == source ]]; then
    python3 "$ROOT/scripts/validate-recovery.py" "$command" "$dir" - "$RESULTS/doctor-source.json" ||
      fail "unexpected source doctor finding"
  else
    python3 "$ROOT/scripts/validate-recovery.py" "$command" "$dir" "$RESULTS/doctor-source.json" \
      "$RESULTS/doctor-$stage.json" || fail "$stage doctor differs from healthy source"
  fi
}
wait_paused_app() {
  local i
  for ((i=0;i<120;i++)); do
    if app_json | jq -e --arg rev "$FORGEJO_VALUES_REVISION" --arg chart "$FORGEJO_CHART_VERSION" \
      --argjson parameters "${IMAGE_PARAMETERS:-[]}" \
      --arg digest "$FORGEJO_CHART_DIGEST" '
      .spec.sources[0].targetRevision == $chart and .spec.sources[1].targetRevision == $rev and
      .spec.syncPolicy.automated == {enabled:false,prune:false,selfHeal:true} and
      (.spec.sources[0].helm.parameters // []) == $parameters and
      .status.sync.comparedTo.sources == .spec.sources and
      .status.sync.status == "Synced" and .status.health.status == "Healthy" and
      .status.sync.revisions == [$digest,$rev] and
      .status.operationState.phase == "Succeeded" and .operation == null' >/dev/null 2>&1; then
      return 0
    fi
    sleep 2
  done
  fail "paused Application manual sync did not reach Synced/Healthy"
}

# W3 uses the same checkpoint/restore lifecycle; only the controlled version transition differs.
upgrade_preflight() {
  [[ "$(uname -m)" == x86_64 && "$FORGEJO_IMAGE_TAG" == 15.0.9-rootless &&
     "$FORGEJO_UPGRADE_FROM_IMAGE_TAG" == 15.0.8-rootless ]] || fail "unsupported W3 pair/platform"
  local version expected hash url
  for version in 15.0.8 15.0.9; do
    url="https://codeberg.org/forgejo/forgejo/raw/branch/forgejo/release-notes-published/$version.md"
    curl -fsSL --max-time 45 --retry 0 "$url" >"$RAW/notes-$version" || fail "official release notes unavailable"
    expected=d0ca357d547734c72b2956ba5fd36784ce3a37f1c2fb3c1c28cf870ff25dd7d4
    [[ "$version" != 15.0.9 ]] || expected=6aa9580cab5d0fbfde65a16077d873ba660a9ba2cda9d8e30d37e7af8a02c51c
    hash="$(sha256sum "$RAW/notes-$version" | awk '{print $1}')"
    [[ "$hash" == "$expected" ]] || fail "official release notes changed; revalidation required"
    jq -nc --arg version "$version" --arg url "$url" --arg hash "$hash" \
      '{version:$version,url:$url,sha256:$hash,reviewed:true}' >>"$RESULTS/upstream.jsonl"
  done
  curl -fsSL --max-time 45 --retry 0 https://forgejo.org/docs/v15.0/admin/upgrade/ >"$RAW/upgrade-guide" ||
    fail "official upgrade guide unavailable"
  phase upstream_revalidated
}
upgrade_regressions() {
  local baseline="${UPGRADE_BASELINE_RESULT:-}" recovered="${UPGRADE_RECOVERY_RESULT:-}"
  local -a files
  if [[ -z "$baseline" && -z "$recovered" ]]; then
    touch "$RAW/regression-start"
    "$ROOT/scripts/local-run.sh" || fail "P1/P2/P3-W1 regression failed"
    mapfile -t files < <(find "$ROOT/results/local" -name baseline-summary.json -newer "$RAW/regression-start")
    [[ "${#files[@]}" == 1 ]] || fail "baseline regression result ambiguous"
    baseline="${files[0]}"
    touch "$RAW/recovery-start"
    "$ROOT/scripts/local-recover.sh" || fail "P3-W2 regression failed"
    mapfile -t files < <(find "$ROOT/results/local" -path '*/recovery-*/result.json' -newer "$RAW/recovery-start")
    [[ "${#files[@]}" == 1 ]] || fail "recovery regression result ambiguous"
    recovered="${files[0]}"
  fi
  [[ -s "$baseline" && -s "$recovered" ]] || fail "both explicit regression results are required"
  python3 "$ROOT/scripts/validate-upgrade.py" regressions "$RESULTS" "$baseline" "$recovered" \
    "$SOURCE_SHA" "$SOURCE_DIRTY" || fail "regression evidence differs from current source"
  phase regression_verified
}
select_image() {
  CURRENT_TAG="$1" CURRENT_DIGEST="$2"
  IMAGE_PARAMETERS="$(jq -nc --arg tag "$1" --arg digest "$2" \
    '[{name:"image.tag",value:$tag},{name:"image.digest",value:$digest}]')"
  python3 - "$ROOT/platform/argocd/forgejo-local.yaml" "$RAW/paused-app.yaml" "$1" "$2" <<'PY'
from pathlib import Path
import sys
source = Path(sys.argv[1]).read_text()
assert source.count("    automated:\n") == 1 and source.count("        releaseName: forgejo\n") == 1
source = source.replace("    automated:\n", "    automated:\n      enabled: false\n")
source = source.replace("        releaseName: forgejo\n", "        releaseName: forgejo\n" +
    "        parameters:\n          - name: image.tag\n            value: " + sys.argv[3] +
    "\n          - name: image.digest\n            value: " + sys.argv[4] + "\n")
Path(sys.argv[2]).write_text(source)
PY
  kubectl -n argocd apply -f "$RAW/paused-app.yaml" >/dev/null
  app_json | jq -e --argjson p "$IMAGE_PARAMETERS" '
    .spec.syncPolicy.automated == {enabled:false,prune:false,selfHeal:true} and
    .spec.sources[0].helm.parameters == $p and .operation == null' >/dev/null || fail "maintenance image ownership ambiguous"
  kubectl -n argocd patch application forgejo-local --type=merge \
    -p='{"operation":{"initiatedBy":{"username":"local-upgrade"},"sync":{"syncStrategy":{"hook":{}}}}}' >/dev/null
  wait_paused_app
  kubectl -n forgejo rollout status deployment/forgejo --timeout=300s >/dev/null
}
database_authority() {
  # Tables/columns were first inspected on the selected v15.0.8 runtime, then checked against
  # the official gitea_migrations / forgejo_migrations_legacy / forgejo_migrations sources.
  kubectl -n postgres exec postgres-0 -c postgres -- env PGOPTIONS='-c default_transaction_read_only=on' \
    psql -v ON_ERROR_STOP=1 -U forgejo -d forgejo -tA -c "
    SELECT json_build_object(
      'catalog',(SELECT json_agg(row_to_json(c) ORDER BY table_name,ordinal_position)
        FROM (SELECT table_name,column_name,data_type,ordinal_position FROM information_schema.columns
          WHERE table_schema='public' AND table_name IN ('version','forgejo_version','forgejo_migration')) c),
      'version',(SELECT json_agg(row_to_json(v) ORDER BY id) FROM version v),
      'forgejo_version',(SELECT json_agg(row_to_json(v) ORDER BY id) FROM forgejo_version v),
      'forgejo_migration',(SELECT json_agg(id ORDER BY id) FROM forgejo_migration));"
}
credential_unchanged() {
  [[ "$(sha256sum "$RAW/journey/credentials.env" | awk '{print $1}')" == "$CREDENTIAL_SHA" ]] || fail "PAT credential substituted"
  [[ "$(sha256sum "$RAW/cookies" | awk '{print $1}')" == "$(cat "$RAW/cookie.sha")" ]] || fail "session cookie substituted"
}
upgrade_snapshot() {
  local stage="$1" pod
  pod="$(kubectl -n forgejo get pod -l app.kubernetes.io/name=forgejo -o jsonpath='{.items[0].metadata.name}')"
  credential_unchanged
  jq -n --arg stage "$stage" --arg sha "$SOURCE_SHA" --argjson dirty "$SOURCE_DIRTY" \
    --arg version "$(curl -fsS --max-time 15 "$URL/api/v1/version" | jq -r .version)" \
    --arg tag "$CURRENT_TAG" --arg digest "$CURRENT_DIGEST" --arg server "$(server_id)" \
    --arg chart "$FORGEJO_CHART_VERSION" --arg argo "$ARGOCD_VERSION" \
    --arg pg_version "$POSTGRES_VERSION" --arg pat "$CREDENTIAL_SHA" --arg cookie "$(cat "$RAW/cookie.sha")" \
    --argjson database "$(database_authority)" --argjson storage "$(storage_pair)" \
    --argjson pod "$(kubectl -n forgejo get pod "$pod" -o json)" \
    --argjson pg "$(kubectl -n postgres get pod postgres-0 -o json)" --argjson app "$(app_json)" \
    '{stage:$stage,source_sha:$sha,source_dirty:$dirty,version:$version,tag:$tag,digest:$digest,
      server_id:$server,storage:$storage,database_authority:$database,
      image_id:($pod.status.containerStatuses[]|select(.name=="forgejo")|.imageID),
      image_spec:($pod.spec.containers[]|select(.name=="forgejo")|.image),
      init_image_ids:[$pod.status.initContainerStatuses[].imageID],
      init_image_specs:[$pod.spec.initContainers[].image],
      postgres_image_spec:$pg.spec.containers[0].image,postgres_image_id:$pg.status.containerStatuses[0].imageID,
      postgres_version:$pg_version,chart_version:$chart,chart_digest:$app.status.sync.revisions[0],
      argo_version:$argo,argo_values_revision:$app.status.sync.revisions[1],
      argo_sources:$app.spec.sources,autosync:$app.spec.syncPolicy.automated,
      pat_file_sha256:$pat,cookie_file_sha256:$cookie,session_login_count:1}' >"$RESULTS/runtime-$stage.json"
  python3 "$ROOT/scripts/validate-upgrade.py" runtime "$RESULTS/runtime-$stage.json" || fail "$stage runtime identity/authority incomplete"
  phase "${stage}_runtime_verified"
}
upgrade_and_mark() {
  # A remains stopped until the complete bundle has been revalidated.
  python3 "$ROOT/scripts/validate-recovery.py" bundle "$RAW" >/dev/null
  assert_no_pods -l app.kubernetes.io/name=forgejo
  phase upgrade_writer_absent
  A_VERSION="$FORGEJO_VERSION" A_IMAGE_ID="$FORGEJO_IMAGE_ID"
  stop_pf
  select_image "$FORGEJO_IMAGE_TAG" "$FORGEJO_UPGRADE_TO_IMAGE_DIGEST"
  phase b_started
  start_pf
  health
  SOURCE_POD="$(kubectl -n forgejo get pod -l app.kubernetes.io/name=forgejo -o jsonpath='{.items[0].metadata.name}')"
  FORGEJO_VERSION="$(curl -fsS --max-time 15 "$URL/api/v1/version" | jq -r .version)"
  FORGEJO_IMAGE_ID="$(kubectl -n forgejo get pod "$SOURCE_POD" -o jsonpath='{.status.containerStatuses[0].imageID}')"
  doctor_snapshot upgraded "$SOURCE_POD"
  upgrade_snapshot b
  journey verify post-upgrade
  protected_session
  phase b_continuity
  journey write b-only
  # shellcheck source=/dev/null
  source "$RAW/journey/post-write.env"
  journey verify b-marker
  [[ "$(api_main)" == "$POST_SHA" ]] || fail "B-only commit absent from Forgejo API"
  [[ "$(kubectl -n postgres exec postgres-0 -c postgres -- psql -U forgejo -d forgejo -tA -c \
    "SELECT count(*) FROM issue i JOIN repository r ON r.id=i.repo_id JOIN \"user\" u ON u.id=r.owner_id WHERE u.lower_name='$DEV_USER' AND r.lower_name='journey' AND i.index=$POST_ISSUE_NUMBER AND i.name='$POST_ISSUE_TITLE' AND NOT i.is_pull;")" == 1 ]] || fail "B-only Issue not persisted"
  [[ "$(kubectl -n forgejo exec "$SOURCE_POD" -c forgejo -- git --git-dir="/data/git/gitea-repositories/$DEV_USER/journey.git" rev-parse refs/heads/main)" == "$POST_SHA" ]] || fail "B-only commit not persisted"
  jq -n --arg commit "$POST_SHA" --arg issue "$POST_ISSUE_NUMBER" --arg title "$POST_ISSUE_TITLE" \
    '{commit:$commit,issue_number:($issue|tonumber),issue_title:$title,api:true,database:true,filesystem:true}' >"$RESULTS/b-marker.json"
  phase b_marker_persisted
  wait_paused_app
  timeout -k 5s 150s kubectl -n forgejo exec "$SOURCE_POD" -c forgejo -- \
    forgejo manager flush-queues --config /data/gitea/conf/app.ini --timeout 2m >"$RAW/b-flush.log" 2>&1 || fail "B queue flush failed"
  phase b_queue_flushed
  kubectl -n forgejo scale deployment/forgejo --replicas=0 >/dev/null
  kubectl -n forgejo wait "pod/$SOURCE_POD" --for=delete --timeout=180s >/dev/null
  assert_no_pods -l app.kubernetes.io/name=forgejo
  phase b_stopped
  # Keep the original fixture state and credentials; remove only B's client bookkeeping.
  rm "$RAW/journey/post-write.env"
  git -C "$RAW/journey/work" reset --hard "$MAIN_SHA" >/dev/null
  FORGEJO_VERSION="$A_VERSION" FORGEJO_IMAGE_ID="$A_IMAGE_ID"
}
rollback_marker_absence() {
  local commit issue status repo rc=0
  credential_unchanged
  commit="$(jq -r .commit "$RESULTS/b-marker.json")"
  issue="$(jq -r .issue_number "$RESULTS/b-marker.json")"
  repo="/data/git/gitea-repositories/$DEV_USER/journey.git"
  status="$(curl -sS --max-time 15 --config <(printf 'header = "Authorization: token %s"\n' "$DEV_TOKEN") \
    -o "$RAW/absent-issue" -w '%{http_code}' "$URL/api/v1/repos/$DEV_USER/journey/issues/$issue")"
  [[ "$status" == 404 ]] || fail "B-only Issue restored"
  [[ "$(api_main)" == "$MAIN_SHA" ]] || fail "restored API main differs from checkpoint"
  [[ "$(kubectl -n postgres exec postgres-0 -c postgres -- psql -U forgejo -d forgejo -tA -c \
    "SELECT count(*) FROM issue i JOIN repository r ON r.id=i.repo_id JOIN \"user\" u ON u.id=r.owner_id WHERE u.lower_name='$DEV_USER' AND r.lower_name='journey' AND i.index=$issue;")" == 0 ]] || fail "B-only Issue restored in database"
  [[ "$(kubectl -n forgejo exec "$TARGET_POD" -c forgejo -- git --git-dir="$repo" rev-parse refs/heads/main)" == "$MAIN_SHA" ]] || fail "restored main differs from checkpoint"
  # git cat-file exit 1 alone is ambiguous: validate the original objects first, then inventory all objects.
  kubectl -n forgejo exec "$TARGET_POD" -c forgejo -- git --git-dir="$repo" cat-file -e "$MAIN_SHA^{commit}"
  kubectl -n forgejo exec "$TARGET_POD" -c forgejo -- git --git-dir="$repo" cat-file --batch-all-objects --batch-check='%(objectname)' >"$RAW/restored-objects"
  [[ -s "$RAW/restored-objects" ]] || fail "restored repository object inventory missing"
  grep -qFx "$commit" "$RAW/restored-objects" || rc=$?
  [[ "$rc" == 1 ]] || fail "B-only commit object restored or inventory unreadable"
  [[ "$(database_authority | jq -Sc .)" == "$(jq -Sc .database_authority "$RESULTS/runtime-a.json")" ]] || fail "rollback database authority differs from A"
  jq -n --arg main "$MAIN_SHA" --arg commit "$commit" --argjson issue "$issue" \
    '{restored_main:$main,absent_commit:$commit,absent_issue:$issue,api:true,database:true,filesystem:true,before_new_write:true}' >"$RESULTS/marker-absence.json"
  phase marker_absence
}
upgrade_post_write() {
  credential_unchanged
  journey verify post-rollback-write
  [[ "$(api_main)" == "$POST_SHA" ]] || fail "post-rollback API main differs"
  jq -n --arg sha "$POST_SHA" --arg issue "$POST_ISSUE_NUMBER" --arg title "$POST_ISSUE_TITLE" \
    '{commit:$sha,issue_number:($issue|tonumber),issue_title:$title,api:true,database:true,filesystem:true}' >"$RESULTS/post-write.json"
  phase post_rollback_write_verified
}
api_main() {
  curl -fsS --max-time 15 --config <(printf 'header = "Authorization: token %s"\n' "$DEV_TOKEN") \
    "$URL/api/v1/repos/$DEV_USER/journey/branches/main" | jq -er .commit.id
}

[[ ! -e "$ROOT/.tmp/kubeconfig" ]] || fail "pre-existing local runtime output"
SOURCE_SHA="$(git -C "$ROOT" rev-parse HEAD)"
SOURCE_DIRTY=false
[[ -z "$(git -C "$ROOT" status --porcelain)" ]] || SOURCE_DIRTY=true
[[ "$SOURCE_DIRTY" == false ]] ||
  log "source checkout has uncommitted work; exact-head CI will be clean"
if [[ "$MODE" == upgrade ]]; then
  upgrade_preflight
  upgrade_regressions
  LOCAL_DEFER_FORGEJO_START=1 LOCAL_CLUSTER_OWNERSHIP_MARKER="$MARKER" "$ROOT/scripts/local-up.sh"
  assert_no_pods
  [[ "$(kubectl -n postgres exec postgres-0 -c postgres -- psql -U forgejo -d forgejo -tA -c \
    "SELECT count(*) FROM information_schema.tables WHERE table_schema='public';")" == 0 ]] || fail "fresh A database not empty"
  claims="$(kubectl -n forgejo get pvc -o name)" || fail "cannot inspect fresh A storage"
  [[ -z "$claims" ]] || fail "fresh A Forgejo storage already exists"
  phase fresh_a_prepared
  select_image "$FORGEJO_UPGRADE_FROM_IMAGE_TAG" "$FORGEJO_UPGRADE_FROM_IMAGE_DIGEST"
else
  LOCAL_CLUSTER_OWNERSHIP_MARKER="$MARKER" "$ROOT/scripts/local-up.sh"
fi
SOURCE_SERVER="$(server_id)"
if [[ "$MODE" == recovery ]]; then assert_normal_app; else wait_paused_app; fi
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
CREDENTIAL_SHA="$(sha256sum "$RAW/journey/credentials.env" | awk '{print $1}')"
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
FORGEJO_VERSION="$(curl -fsS --max-time 15 "$URL/api/v1/version" | jq -r .version)"
expected_version="$(printf '%s' "$FORGEJO_IMAGE_TAG" | sed 's/-rootless$//')"
[[ "$MODE" != upgrade ]] || expected_version="${FORGEJO_UPGRADE_FROM_IMAGE_TAG%-rootless}"
[[ "$FORGEJO_VERSION" == "$expected_version"* ]] || fail "Forgejo version drift"
doctor_snapshot source "$SOURCE_POD"
if [[ "$MODE" == upgrade ]]; then upgrade_snapshot a; fi
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
if [[ "$MODE" == recovery ]]; then assert_normal_app; else wait_paused_app; fi
kubectl -n argocd patch application forgejo-local --type=json \
  -p='[{"op":"add","path":"/spec/syncPolicy/automated/enabled","value":false}]' >/dev/null
app_json | jq -e '.spec.syncPolicy.automated == {enabled:false,prune:false,selfHeal:true} and .operation == null' >/dev/null ||
  fail "Argo autosync stop not confirmed"
phase autosync_stopped
timeout -k 5s 150s kubectl -n forgejo exec "$SOURCE_POD" -c forgejo -- \
  forgejo manager flush-queues --config /data/gitea/conf/app.ini --timeout 2m >"$RAW/flush.log" 2>&1 ||
  fail "Forgejo queue flush failed"
phase queue_flushed
kubectl -n forgejo scale deployment/forgejo --replicas=0 >/dev/null
kubectl -n forgejo wait "pod/$SOURCE_POD" --for=delete --timeout=180s >/dev/null
assert_no_pods -l app.kubernetes.io/name=forgejo
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
if [[ "$MODE" == upgrade ]]; then
  jq --slurpfile runtime "$RESULTS/runtime-a.json" '. + {database_authority:$runtime[0].database_authority}' \
    "$RESULTS/checkpoint.json" >"$RAW/checkpoint-evidence.json"
  mv "$RAW/checkpoint-evidence.json" "$RESULTS/checkpoint.json"
fi
phase bundle_validated
if [[ "$MODE" == upgrade ]]; then upgrade_and_mark; fi

stop_pf
LOCAL_CLUSTER_OWNERSHIP_MARKER="$MARKER" "$ROOT/scripts/local-down.sh"
phase source_cleaned
: >"$MARKER"
LOCAL_RESTORE_SECRETS_FILE="$RAW/secrets.json" LOCAL_CLUSTER_OWNERSHIP_MARKER="$MARKER" "$ROOT/scripts/local-up.sh"
TARGET=1
TARGET_SERVER="$(server_id)"
[[ "$TARGET_SERVER" != "$SOURCE_SERVER" ]] || fail "source cluster reused"
assert_no_pods
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
assert_no_pods
if [[ "$MODE" == upgrade ]]; then
  phase restore_complete
  select_image "$FORGEJO_UPGRADE_FROM_IMAGE_TAG" "$FORGEJO_UPGRADE_FROM_IMAGE_DIGEST"
else
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
fi
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
if [[ "$MODE" == upgrade ]]; then upgrade_snapshot rollback; fi
phase target_doctor_verified
journey verify post-restore
phase retained_state
phase same_pat
[[ "$(sha256sum "$RAW/cookies" | awk '{print $1}')" == "$(cat "$RAW/cookie.sha")" ]] ||
  fail "session cookie changed before restore verification"
protected_session
phase same_session
if [[ "$MODE" == upgrade ]]; then rollback_marker_absence; fi
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
if [[ "$MODE" == upgrade ]]; then
  upgrade_post_write
  doctor_snapshot post-write "$TARGET_POD"
  wait_paused_app
  patterns="$RAW/credential-patterns"
  printf '%s\n' "$DEV_TOKEN" "$DEV_PASSWORD" \
    "$(kubectl -n forgejo get secret forgejo-admin -o jsonpath='{.data.password}' | base64 -d)" \
    "$(kubectl -n forgejo get secret forgejo-db -o jsonpath='{.data.password}' | base64 -d)" \
    "$(kubectl -n postgres get secret postgres-credentials -o jsonpath='{.data.superuser-password}' | base64 -d)" >"$patterns"
  awk 'NF == 7 && ($0 !~ /^#/ || $0 ~ /^#HttpOnly_/) {print $7}' "$RAW/cookies" >>"$patterns"
  ! grep -q '^$' "$patterns" || fail "credential inventory empty"
  assert_no_credentials grep -rFq -f "$patterns" "$RESULTS"
  assert_no_credentials git -C "$ROOT" grep --untracked -qF -f "$patterns"
  phase credential_hygiene
  phase maintenance_a_retained
  DONE=1
  exit 0
fi
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
