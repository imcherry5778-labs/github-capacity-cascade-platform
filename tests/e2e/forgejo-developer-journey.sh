#!/usr/bin/env bash
# shellcheck disable=SC2016 # jq programs intentionally use single quotes and jq variables.
# Forgejo developer journey E2E. create의 원격 developer command만 선택적으로 측정한다.
#
#   create          fixture developer identity를 준비하고 developer operation 1-10을 수행한 뒤 state를 기록한다.
#   verify [label]  기록된 state가 유지되는지 developer read path(clone/fetch/PR/Issue)로 확인한다.
#   write           recovery 이후 같은 developer/PAT로 새 Git commit과 Issue를 생성한다.
#
# Admin capability는 create의 fixture identity 생성에만 사용한다. 모든 developer operation은
# 일반(non-admin) developer의 access token으로 수행한다. Developer operation은 Git Smart HTTP
# request 수가 아니라 개발자가 의도한 행동 단위로 센다.
#
# Env:
#   FORGEJO_URL                               e.g. http://127.0.0.1:13000
#   JOURNEY_DIR                               state/work directory (gitignored runtime output)
#   FORGEJO_ADMIN_USERNAME, FORGEJO_ADMIN_PASSWORD   create에서만 필요
set -euo pipefail

MODE="${1:?usage: forgejo-developer-journey.sh create|verify [label]}"
LABEL="${2:-$MODE}"
: "${FORGEJO_URL:?}" "${JOURNEY_DIR:?}"
API="$FORGEJO_URL/api/v1"
export REPO=journey FEATURE_BRANCH=feature/journey
umask 077

# 사용자 global/system Git config와 credential helper에서 격리한다.
export GIT_CONFIG_NOSYSTEM=1 GIT_CONFIG_GLOBAL=/dev/null GIT_TERMINAL_PROMPT=0
export GIT_AUTHOR_NAME="Journey Developer" GIT_AUTHOR_EMAIL=journey@example.com
export GIT_COMMITTER_NAME="$GIT_AUTHOR_NAME" GIT_COMMITTER_EMAIL="$GIT_AUTHOR_EMAIL"
GIT_TIMEOUT_SECONDS="${JOURNEY_GIT_TIMEOUT_SECONDS:-65}"
GIT_KILL_AFTER_SECONDS="${JOURNEY_GIT_KILL_AFTER_SECONDS:-5}"

operations=0
pass() { operations=$((operations + 1)); printf '[journey:%s] PASS %s\n' "$LABEL" "$*"; }
fail() {
  # Message는 고정된 설명만 허용한다. 응답 본문과 credential은 출력하지 않는다.
  if [[ -n "${RESULT_FILE:-}" ]]; then printf '%s' "${2:-semantic_error}" >"$RESULT_DIR/error_class"; fi
  printf '[journey:%s] FAIL %s\n' "$LABEL" "$1" >&2
  exit 1
}

mono() { awk '{print $1}' /proc/uptime; }
duration_between() { awk -v start="$1" -v end="$2" 'BEGIN {printf "%.6f", end-start}'; }
utc() { date -u +%Y-%m-%dT%H:%M:%SZ; }
emit() { jq -nc "$@" >>"$RESULT_FILE"; }

aux_event() { # kind name outcome [operation_id]
  [[ -n "${RESULT_FILE:-}" ]] || return 0
  AUX_INDEX=$((AUX_INDEX + 1))
  emit --arg run "$RUN_ID" --arg id "$RUN_ID-event-$AUX_INDEX" --arg kind "$1" \
    --arg name "$2" --arg outcome "$3" --arg op "${4:-}" --arg ts "$(utc)" \
    '{record:"auxiliary_event",run_id:$run,event_id:$id,kind:$kind,name:$name,outcome:$outcome,
      operation_id:(if $op == "" then null else $op end),
      attempt_id:(if $op == "" then null else ($op + "-attempt-1") end),timestamp_utc:$ts}'
}

operation_begin() { # bounded operation type; one client attempt, no retry
  [[ -n "${RESULT_FILE:-}" ]] || return 0
  OP_INDEX=$((OP_INDEX + 1))
  OP_ID="$RUN_ID-operation-$OP_INDEX"
  ATTEMPT_ID="$OP_ID-attempt-1"
  OP_TYPE="$1"
  OP_ACTIVE=1 ATTEMPT_ACTIVE=1
  OP_TIMESTAMP="$(utc)"
  rm -f "$RESULT_DIR/http_status" "$RESULT_DIR/error_class" "$RESULT_DIR/command_exit" \
    "$RESULT_DIR/command_start" "$RESULT_DIR/command_end" "$RESULT_DIR/command_timestamp"
  emit --arg run "$RUN_ID" --arg id "$OP_ID" --arg type "$OP_TYPE" --arg ts "$OP_TIMESTAMP" \
    '{record:"operation_start",run_id:$run,operation_id:$id,operation_type:$type,timestamp_utc:$ts}'
}

attempt_finish() { # command exit code
  [[ -n "${RESULT_FILE:-}" && "$ATTEMPT_ACTIVE" == 1 ]] || return 0
  # No command_start means no client attempt was observed. Keep the operation open.
  [[ -f "$RESULT_DIR/command_start" ]] || return 0
  local rc="$1" status="" class="none" command_end
  command_end="$(cat "$RESULT_DIR/command_end" 2>/dev/null || mono)"
  OP_DURATION="$(duration_between "$(cat "$RESULT_DIR/command_start")" "$command_end")"
  [[ ! -f "$RESULT_DIR/http_status" ]] || status="$(cat "$RESULT_DIR/http_status")"
  [[ ! -f "$RESULT_DIR/command_exit" ]] || rc="$(cat "$RESULT_DIR/command_exit")"
  class="$(cat "$RESULT_DIR/error_class" 2>/dev/null || true)"
  if [[ "$rc" -ne 0 || -n "$class" ]]; then
    [[ -n "$class" ]] || class=command_error
    [[ "$rc" -ne 124 && "$rc" -ne 28 ]] || class=timeout
  else
    class=none
  fi
  emit --arg run "$RUN_ID" --arg id "$ATTEMPT_ID" --arg op "$OP_ID" \
    --arg ts "$(cat "$RESULT_DIR/command_timestamp")" \
    --argjson rc "$rc" --argjson duration "$OP_DURATION" --arg status "$status" --arg class "$class" \
    '{record:"attempt",run_id:$run,attempt_id:$id,operation_id:$op,attempt_index:1,
      timestamp_utc:$ts,duration_seconds:$duration,exit_code:$rc,
      http_status:(if $status == "" or $status == "000" then null else ($status|tonumber) end),error_class:$class}'
  ATTEMPT_ACTIVE=0
}

operation_finish() { # outcome semantic_result
  [[ -n "${RESULT_FILE:-}" && "$OP_ACTIVE" == 1 ]] || return 0
  emit --arg run "$RUN_ID" --arg id "$OP_ID" --arg type "$OP_TYPE" --arg outcome "$1" \
    --argjson duration "$OP_DURATION" --argjson semantic "$2" \
    '{record:"operation",run_id:$run,operation_id:$id,operation_type:$type,outcome:$outcome,
      attempt_count:1,duration_seconds:$duration,semantic_result:$semantic}'
  OP_ACTIVE=0
}

operation_success() {
  [[ -n "${RESULT_FILE:-}" ]] || return 0
  attempt_finish 0
  aux_event assertion "$OP_TYPE" success "$OP_ID"
  operation_finish success true
}

on_result_exit() {
  local rc="$1" completion=failed validity=invalid
  [[ -n "${RESULT_FILE:-}" && "${RUN_FINISHED:-0}" == 0 ]] || return 0
  if [[ "${OP_ACTIVE:-0}" == 1 ]]; then
    if [[ "${ATTEMPT_ACTIVE:-0}" == 1 ]]; then attempt_finish "$rc"; else aux_event assertion "$OP_TYPE" failed "$OP_ID"; fi
    if [[ "${ATTEMPT_ACTIVE:-0}" == 0 ]]; then
      operation_finish failed false
      validity=valid
    fi
  fi
  [[ "$rc" -ne 130 && "$rc" -ne 143 ]] || completion=interrupted
  emit --arg run "$RUN_ID" --arg completion "$completion" --arg validity "$validity" --arg ts "$(utc)" \
    '{record:"run_end",run_id:$run,completion:$completion,validity:$validity,ended_at_utc:$ts}'
}
trap 'on_result_exit $?' EXIT
trap 'exit 130' INT
trap 'exit 143' TERM

result_start() {
  [[ -n "${RESULTS_ROOT:-}" ]] || return 0
  RESULT_DIR="$RESULTS_ROOT/$RUN_ID"
  mkdir -p "$RESULTS_ROOT"
  mkdir -m 0700 "$RESULT_DIR" || fail "result directory create failed" command_error
  RESULT_FILE="$RESULT_DIR/events.jsonl"
  ( set -o noclobber; : >"$RESULT_FILE" ) || fail "result already exists" command_error
  OP_INDEX=0 AUX_INDEX=0 OP_ACTIVE=0 ATTEMPT_ACTIVE=0 RUN_FINISHED=0
  emit --arg run "$RUN_ID" --arg phase "${RESULT_PHASE:-measured}" --arg ts "$(utc)" \
    --argjson git_timeout "$GIT_TIMEOUT_SECONDS" --argjson kill_after "$GIT_KILL_AFTER_SECONDS" \
    --slurpfile context "$RESULT_CONTEXT_FILE" \
    '({record:"run_start",schema_version:1,run_id:$run,phase:$phase,started_at_utc:$ts,
      scenario:"local_healthy_developer_journey",parameters:{concurrency:1,max_attempts:1,client_retry:false,
        api_timeout_seconds:60,git_timeout_seconds:$git_timeout,git_kill_after_seconds:$kill_after},
      measurement_boundary:"loopback kubectl port-forward client command"} + $context[0])'
}

result_finish() {
  [[ -n "${RESULT_FILE:-}" ]] || return 0
  emit --arg run "$RUN_ID" --arg ts "$(utc)" \
    '{record:"run_end",run_id:$run,completion:"success",validity:"valid",ended_at_utc:$ts}'
  RUN_FINISHED=1
}

# request CURL_CONFIG_LINE METHOD PATH EXPECTED_STATUS [JSON_BODY]
# Credential과 body는 mode 0600 파일로 준비해 process argv에 남기지 않는다.
request() {
  local auth="$1" method="$2" path="$3" expected="$4" body="${5-}" status rc command_end
  local response="$JOURNEY_DIR/response.json" auth_file="$JOURNEY_DIR/request-auth" body_file="$JOURNEY_DIR/request-body"
  local -a args=(-s --retry 0 --max-time 60 -o "$response" -w '%{http_code}' -X "$method" -H 'Accept: application/json')
  printf '%s\n' "$auth" >"$auth_file"
  if [[ -n "$body" ]]; then
    printf '%s' "$body" >"$body_file"
    args+=(-H 'Content-Type: application/json' --data-binary "@$body_file")
  fi
  args+=(-K "$auth_file" "$API$path")
  if [[ -n "${RESULT_FILE:-}" && "${OP_ACTIVE:-0}" == 1 && "${ATTEMPT_ACTIVE:-0}" == 1 ]]; then
    printf '%s' "$(utc)" >"$RESULT_DIR/command_timestamp"
    printf '%s' "$(mono)" >"$RESULT_DIR/command_start"
  fi
  if status="$(curl "${args[@]}")"; then
    rc=0
  else
    rc=$?
  fi
  command_end="$(mono)"
  if [[ -n "${RESULT_FILE:-}" && "${OP_ACTIVE:-0}" == 1 && "${ATTEMPT_ACTIVE:-0}" == 1 ]]; then
    printf '%s' "$command_end" >"$RESULT_DIR/command_end"
    printf '%s' "$rc" >"$RESULT_DIR/command_exit"
    printf '%s' "$status" >"$RESULT_DIR/http_status"
  fi
  if [[ "$rc" -ne 0 ]]; then
    if [[ "$rc" -eq 28 ]]; then fail "$method $path: curl error" timeout; fi
    fail "$method $path: curl error" transport_error
  fi
  if [[ "$status" != "$expected" ]]; then
    fail "$method $path: expected HTTP $expected, got $status" http_status
  fi
  cat "$response"
}

expect_json() { # JSON JQ_FILTER DESCRIPTION  (filter는 env.* 로 state를 참조한다)
  jq -e "$2" >/dev/null <<<"$1" || fail "$3: unexpected response" semantic_error
}

dev_git() {
  local basic rc class git_start git_end
  basic="$(printf '%s:%s' "$DEV_USER" "$DEV_TOKEN" | base64 | tr -d '\n')"
  if [[ -n "${RESULT_FILE:-}" && "${OP_ACTIVE:-0}" == 1 && "${ATTEMPT_ACTIVE:-0}" == 1 ]]; then
    printf '%s' "$(utc)" >"$RESULT_DIR/command_timestamp"
  fi
  git_start="$(mono)"
  if [[ -n "${RESULT_FILE:-}" && "${OP_ACTIVE:-0}" == 1 && "${ATTEMPT_ACTIVE:-0}" == 1 ]]; then
    printf '%s' "$git_start" >"$RESULT_DIR/command_start"
  fi
  if GIT_CONFIG_COUNT=2 GIT_CONFIG_KEY_0=http.extraHeader GIT_CONFIG_VALUE_0="Authorization: Basic $basic" \
    GIT_CONFIG_KEY_1=credential.helper GIT_CONFIG_VALUE_1='' \
    timeout --signal=TERM --kill-after="${GIT_KILL_AFTER_SECONDS}s" "${GIT_TIMEOUT_SECONDS}s" git "$@" 2>"$JOURNEY_DIR/git.stderr"; then
    rc=0
  else
    rc=$?
  fi
  git_end="$(mono)"
  if [[ -n "${RESULT_FILE:-}" && "${OP_ACTIVE:-0}" == 1 && "${ATTEMPT_ACTIVE:-0}" == 1 ]]; then
    printf '%s' "$git_end" >"$RESULT_DIR/command_end"
    printf '%s' "$rc" >"$RESULT_DIR/command_exit"
  fi
  [[ "$rc" -ne 0 ]] || return 0
  class=command_error
  if [[ "$rc" -eq 124 ]] || { [[ "$rc" -eq 137 ]] &&
    awk -v duration="$(duration_between "$git_start" "$git_end")" -v limit="$GIT_TIMEOUT_SECONDS" \
      'BEGIN {exit !(duration >= limit)}'; }; then
    class=timeout
  fi
  fail "Git command failed (exit $rc)" "$class"
}

expect_remote_ref() { # REPO_DIR REF SHA DESCRIPTION
  local actual
  actual="$(dev_git -C "$1" ls-remote origin "$2" | awk '{print $1}')"
  [[ "$actual" == "$3" ]] || fail "$4: remote $2 is '$actual', expected $3"
}

expect_anonymous_denied() {
  local status
  request "" GET "/repos/$DEV_USER/$REPO" 404 >/dev/null
  status="$(curl -sS --max-time 60 -o /dev/null -w '%{http_code}' "$CLONE_URL/info/refs?service=git-upload-pack")"
  [[ "$status" == 401 ]] || fail "anonymous Git HTTP read of private repository: expected 401, got $status"
}

# Forgejo는 첫 push의 repository 상태 전환(IsEmpty=false)을 push_update queue에서 비동기로 처리하고,
# empty repository에는 Pull Request를 허용하지 않는다(CanEnablePulls). Developer operation을 retry하지 않고,
# 이 platform-side 처리 완료만 bounded wait로 확인한다.
wait_initial_push_processed() {
  local deadline remaining curl_timeout sleep_for json status response
  response="$JOURNEY_DIR/response.json"
  deadline=$((SECONDS + 60))
  while (( SECONDS < deadline )); do
    remaining=$((deadline - SECONDS))
    curl_timeout=$((remaining < 5 ? remaining : 5))
    if status="$(curl -sS --max-time "$curl_timeout" -o "$response" -w '%{http_code}' -X GET \
      -H 'Accept: application/json' -K <(printf '%s\n' "$DEV_AUTH") "$API/repos/$DEV_USER/$REPO" 2>/dev/null)"; then
      if [[ "$status" != 200 ]]; then
        fail "initial push settle: expected HTTP 200, got $status" http_status
      fi
      json="$(cat "$response")"
      if jq -e '.empty == false' >/dev/null <<<"$json"; then return 0; fi
    fi
    remaining=$((deadline - SECONDS))
    (( remaining > 0 )) || break
    sleep_for=$((remaining < 1 ? remaining : 1))
    sleep "$sleep_for"
  done
  fail "Forgejo did not finish processing the initial push within 60s (repository still empty)"
}

read_pull_request() {
  local pr
  if [[ "$MODE" == create ]]; then operation_begin pull_request_read; fi
  pr="$(request "$DEV_AUTH" GET "/repos/$DEV_USER/$REPO/pulls/$PR_NUMBER" 200)"
  if [[ "$MODE" == create ]]; then attempt_finish 0; fi
  expect_json "$pr" '.number == (env.PR_NUMBER | tonumber) and .title == env.PR_TITLE and .state == "open"
    and .base.ref == "main" and .head.ref == env.FEATURE_BRANCH and .head.sha == env.FEATURE_SHA' "pull request read"
  if [[ "$MODE" == create ]]; then operation_success; fi
}

read_issue() {
  local issue
  if [[ "$MODE" == create ]]; then operation_begin issue_read; fi
  issue="$(request "$DEV_AUTH" GET "/repos/$DEV_USER/$REPO/issues/$ISSUE_NUMBER" 200)"
  if [[ "$MODE" == create ]]; then attempt_finish 0; fi
  expect_json "$issue" '.number == (env.ISSUE_NUMBER | tonumber) and .title == env.ISSUE_TITLE and .state == "open"
    and .pull_request == null' "issue read"
  if [[ "$MODE" == create ]]; then operation_success; fi
}

create() {
  : "${FORGEJO_ADMIN_USERNAME:?}" "${FORGEJO_ADMIN_PASSWORD:?}"
  rm -rf "$JOURNEY_DIR"
  mkdir -p "$JOURNEY_DIR"
  local run_id dev_password token_json user_json repo_json branch_json pr_json issue_json work clone initial_sha
  run_id="$(date -u +%Y%m%d%H%M%S)-$(od -An -N3 -tx1 /dev/urandom | tr -d ' \n')"
  export RUN_ID="$run_id" DEV_USER="dev-$run_id"
  export CLONE_URL="$FORGEJO_URL/$DEV_USER/$REPO.git"
  result_start
  aux_event readiness argo_application success
  aux_event readiness forgejo_health success

  # 1. Disposable developer identity (fixture: admin이 계정만 만들고, token은 developer 본인이 발급)
  dev_password="$(od -An -N18 -tx1 /dev/urandom | tr -d ' \n')"
  request "user = \"$FORGEJO_ADMIN_USERNAME:$FORGEJO_ADMIN_PASSWORD\"" POST /admin/users 201 \
    "$(DEV_PASSWORD="$dev_password" jq -nc '{username: env.DEV_USER, email: (env.DEV_USER + "@example.com"),
      password: env.DEV_PASSWORD, must_change_password: false}')" >/dev/null
  token_json="$(request "user = \"$DEV_USER:$dev_password\"" POST "/users/$DEV_USER/tokens" 201 \
    '{"name":"journey","scopes":["write:repository","write:issue","write:user"]}')"
  DEV_TOKEN="$(jq -r .sha1 <<<"$token_json")"
  DEV_AUTH="header = \"Authorization: token $DEV_TOKEN\""
  printf 'DEV_USER=%q\nDEV_TOKEN=%q\n' "$DEV_USER" "$DEV_TOKEN" >"$JOURNEY_DIR/credentials.env"
  if [[ "${RECOVERY_FIXTURE:-0}" == 1 ]]; then
    printf 'DEV_PASSWORD=%q\n' "$dev_password" >>"$JOURNEY_DIR/credentials.env"
  fi
  unset dev_password token_json
  user_json="$(request "$DEV_AUTH" GET /user 200)"
  expect_json "$user_json" '.login == env.DEV_USER and .is_admin == false' "developer identity"
  aux_event fixture developer_identity success
  pass "1 developer identity ready ($DEV_USER, non-admin, token auth)"

  # 2. Private repository
  operation_begin private_repository_create
  repo_json="$(request "$DEV_AUTH" POST /user/repos 201 \
    "$(jq -nc '{name: env.REPO, private: true, auto_init: false, default_branch: "main"}')")"
  attempt_finish 0
  expect_json "$repo_json" '.private == true and .owner.login == env.DEV_USER and .clone_url == env.CLONE_URL' \
    "private repository create"
  expect_anonymous_denied
  operation_success
  pass "2 private repository ready ($DEV_USER/$REPO, anonymous read denied)"

  # 3. Initial Git push
  work="$JOURNEY_DIR/work"
  git init -q -b main "$work"
  printf '# journey %s\n' "$RUN_ID" >"$work/README.md"
  git -C "$work" add README.md
  git -C "$work" commit -q -m "journey: initial commit"
  git -C "$work" remote add origin "$CLONE_URL"
  aux_event fixture initial_commit success
  operation_begin git_push_initial
  dev_git -C "$work" push -q origin main
  attempt_finish 0
  initial_sha="$(git -C "$work" rev-parse HEAD)"
  expect_remote_ref "$work" refs/heads/main "$initial_sha" "initial push"
  wait_initial_push_processed
  aux_event settle initial_push_processed success "${OP_ID:-}"
  export INITIAL_SHA="$initial_sha"
  branch_json="$(request "$DEV_AUTH" GET "/repos/$DEV_USER/$REPO/branches/main" 200)"
  expect_json "$branch_json" '.commit.id == env.INITIAL_SHA' "initial push branch read"
  operation_success
  pass "3 initial push main=$initial_sha (Forgejo push processing complete)"

  # 4. Authenticated clone
  clone="$JOURNEY_DIR/clone"
  operation_begin git_clone
  dev_git clone -q "$CLONE_URL" "$clone"
  attempt_finish 0
  [[ "$(git -C "$clone" rev-parse HEAD)" == "$initial_sha" ]] || fail "clone HEAD mismatch"
  cmp -s "$work/README.md" "$clone/README.md" || fail "clone content mismatch"
  operation_success
  pass "4 authenticated clone"

  # 5. Fetch (다른 working copy가 main에 push한 새 commit을 fetch)
  printf 'second commit %s\n' "$RUN_ID" >>"$work/README.md"
  git -C "$work" commit -q -am "journey: second commit"
  dev_git -C "$work" push -q origin main
  aux_event seed second_commit_push success
  export MAIN_SHA
  MAIN_SHA="$(git -C "$work" rev-parse HEAD)"
  operation_begin git_fetch
  dev_git -C "$clone" fetch -q origin
  attempt_finish 0
  [[ "$(git -C "$clone" rev-parse origin/main)" == "$MAIN_SHA" ]] || fail "fetch did not observe main=$MAIN_SHA"
  git -C "$clone" merge -q --ff-only origin/main
  operation_success
  pass "5 fetch main=$MAIN_SHA"

  # 6. Feature branch push
  git -C "$clone" switch -q -c "$FEATURE_BRANCH"
  printf 'feature %s\n' "$RUN_ID" >"$clone/feature.txt"
  git -C "$clone" add feature.txt
  git -C "$clone" commit -q -m "journey: feature change"
  aux_event fixture feature_commit success
  operation_begin git_push_feature
  dev_git -C "$clone" push -q origin "$FEATURE_BRANCH"
  attempt_finish 0
  export FEATURE_SHA
  FEATURE_SHA="$(git -C "$clone" rev-parse HEAD)"
  expect_remote_ref "$clone" "refs/heads/$FEATURE_BRANCH" "$FEATURE_SHA" "feature branch push"
  operation_success
  pass "6 feature branch push $FEATURE_BRANCH=$FEATURE_SHA"

  # 7-8. Pull Request create/read
  export PR_TITLE="journey pull request $RUN_ID"
  operation_begin pull_request_create
  pr_json="$(request "$DEV_AUTH" POST "/repos/$DEV_USER/$REPO/pulls" 201 \
    "$(jq -nc '{base: "main", head: env.FEATURE_BRANCH, title: env.PR_TITLE, body: "developer journey"}')")"
  attempt_finish 0
  expect_json "$pr_json" '.number > 0 and .title == env.PR_TITLE and .state == "open"' "pull request create"
  export PR_NUMBER
  PR_NUMBER="$(jq -r .number <<<"$pr_json")"
  operation_success
  pass "7 pull request create #$PR_NUMBER"
  read_pull_request
  pass "8 pull request read #$PR_NUMBER"

  # 9-10. Issue create/read
  export ISSUE_TITLE="journey issue $RUN_ID"
  operation_begin issue_create
  issue_json="$(request "$DEV_AUTH" POST "/repos/$DEV_USER/$REPO/issues" 201 \
    "$(jq -nc '{title: env.ISSUE_TITLE, body: "developer journey"}')")"
  attempt_finish 0
  expect_json "$issue_json" '.number > 0 and .title == env.ISSUE_TITLE and .state == "open"' "issue create"
  export ISSUE_NUMBER
  ISSUE_NUMBER="$(jq -r .number <<<"$issue_json")"
  operation_success
  pass "9 issue create #$ISSUE_NUMBER"
  read_issue
  pass "10 issue read #$ISSUE_NUMBER"

  printf '%s=%q\n' RUN_ID "$RUN_ID" MAIN_SHA "$MAIN_SHA" FEATURE_SHA "$FEATURE_SHA" \
    PR_NUMBER "$PR_NUMBER" PR_TITLE "$PR_TITLE" ISSUE_NUMBER "$ISSUE_NUMBER" ISSUE_TITLE "$ISSUE_TITLE" \
    >"$JOURNEY_DIR/state.env"
  result_finish
}

verify() {
  # shellcheck source=/dev/null
  source "$JOURNEY_DIR/credentials.env"
  # shellcheck source=/dev/null
  source "$JOURNEY_DIR/state.env"
  export DEV_USER RUN_ID MAIN_SHA FEATURE_SHA PR_NUMBER PR_TITLE ISSUE_NUMBER ISSUE_TITLE
  export CLONE_URL="$FORGEJO_URL/$DEV_USER/$REPO.git"
  DEV_AUTH="header = \"Authorization: token $DEV_TOKEN\""
  local clone="$JOURNEY_DIR/clone" fresh json expected_main="$MAIN_SHA"
  if [[ -f "$JOURNEY_DIR/post-write.env" ]]; then
    # shellcheck source=/dev/null
    source "$JOURNEY_DIR/post-write.env"
    export POST_ISSUE_NUMBER POST_ISSUE_TITLE
    expected_main="$POST_SHA"
  fi

  json="$(request "$DEV_AUTH" GET /user 200)"
  expect_json "$json" '.login == env.DEV_USER and .is_admin == false' "developer identity"
  json="$(request "$DEV_AUTH" GET "/repos/$DEV_USER/$REPO" 200)"
  expect_json "$json" '.private == true' "private repository read"
  expect_anonymous_denied
  pass "developer token and private repository retained (anonymous read denied)"

  fresh="$(mktemp -d "$JOURNEY_DIR/verify-clone.XXXXXX")"
  dev_git clone -q "$CLONE_URL" "$fresh"
  [[ "$(git -C "$fresh" rev-parse HEAD)" == "$expected_main" ]] || fail "clone main mismatch"
  git -C "$fresh" merge-base --is-ancestor "$MAIN_SHA" "$expected_main" || fail "original main commit missing"
  [[ "$(git -C "$fresh" rev-parse "origin/$FEATURE_BRANCH")" == "$FEATURE_SHA" ]] || fail "clone feature branch mismatch"
  [[ "$(head -n 1 "$fresh/README.md")" == "# journey $RUN_ID" ]] || fail "repository content mismatch"
  pass "authenticated clone main=$expected_main $FEATURE_BRANCH=$FEATURE_SHA content retained"

  dev_git -C "$clone" fetch -q origin
  [[ "$(git -C "$clone" rev-parse origin/main)" == "$expected_main" ]] || fail "fetch main mismatch"
  [[ "$(git -C "$clone" rev-parse "origin/$FEATURE_BRANCH")" == "$FEATURE_SHA" ]] || fail "fetch feature branch mismatch"
  pass "fetch in existing clone"

  read_pull_request
  pass "pull request #$PR_NUMBER retained"
  read_issue
  pass "issue #$ISSUE_NUMBER retained"
  if [[ -f "$JOURNEY_DIR/post-write.env" ]]; then
    json="$(request "$DEV_AUTH" GET "/repos/$DEV_USER/$REPO/issues/$POST_ISSUE_NUMBER" 200)"
    expect_json "$json" '.number == (env.POST_ISSUE_NUMBER | tonumber) and .title == env.POST_ISSUE_TITLE' "post-restore issue"
    pass "post-restore issue #$POST_ISSUE_NUMBER retained"
  fi
}

write_after_restore() {
  # shellcheck source=/dev/null
  source "$JOURNEY_DIR/credentials.env"
  # shellcheck source=/dev/null
  source "$JOURNEY_DIR/state.env"
  export DEV_USER RUN_ID MAIN_SHA
  DEV_AUTH="header = \"Authorization: token $DEV_TOKEN\""
  local work="$JOURNEY_DIR/work" issue kind=restored
  [[ "$LABEL" != b-only ]] || kind=b-only
  [[ ! -e "$JOURNEY_DIR/post-write.env" ]] || fail "post-restore write already recorded"
  printf '%s write %s\n' "$kind" "$RUN_ID" >"$work/$kind.txt"
  git -C "$work" add "$kind.txt"
  git -C "$work" commit -q -m "journey: $kind write"
  POST_SHA="$(git -C "$work" rev-parse HEAD)"
  dev_git -C "$work" push -q origin main
  expect_remote_ref "$work" refs/heads/main "$POST_SHA" "post-restore push"
  pass "post-restore main push=$POST_SHA"
  export POST_ISSUE_TITLE="$kind issue $RUN_ID"
  issue="$(request "$DEV_AUTH" POST "/repos/$DEV_USER/$REPO/issues" 201 \
    "$(jq -nc '{title: env.POST_ISSUE_TITLE, body: "post-restore developer write"}')")"
  POST_ISSUE_NUMBER="$(jq -r .number <<<"$issue")"
  [[ "$POST_ISSUE_NUMBER" =~ ^[0-9]+$ ]] || fail "post-restore issue number"
  printf 'POST_SHA=%q\nPOST_ISSUE_NUMBER=%q\nPOST_ISSUE_TITLE=%q\n' \
    "$POST_SHA" "$POST_ISSUE_NUMBER" "$POST_ISSUE_TITLE" >"$JOURNEY_DIR/post-write.env"
  pass "post-restore issue #$POST_ISSUE_NUMBER"
}

case "$MODE" in
  create) create ;;
  verify) verify ;;
  write) write_after_restore ;;
  *) fail "unknown mode: $MODE" ;;
esac
printf '[journey:%s] PASS %d developer operations/checks\n' "$LABEL" "$operations"
