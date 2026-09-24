#!/usr/bin/env bash
# Forgejo developer journey E2E. Correctness PASS/FAIL만 판정하며 latency/SLO는 측정하지 않는다.
#
#   create          fixture developer identity를 준비하고 developer operation 1-10을 수행한 뒤 state를 기록한다.
#   verify [label]  기록된 state가 유지되는지 developer read path(clone/fetch/PR/Issue)로 확인한다.
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

operations=0
pass() { operations=$((operations + 1)); printf '[journey:%s] PASS %s\n' "$LABEL" "$*"; }
fail() { printf '[journey:%s] FAIL %s\n' "$LABEL" "$*" >&2; exit 1; }

# request CURL_CONFIG_LINE METHOD PATH EXPECTED_STATUS [JSON_BODY]
# Credential과 body는 process substitution으로 전달해 process argv에 남기지 않는다.
request() {
  local auth="$1" method="$2" path="$3" expected="$4" body="${5-}" status
  local response="$JOURNEY_DIR/response.json"
  local -a args=(-sS --max-time 60 -o "$response" -w '%{http_code}' -X "$method" -H 'Accept: application/json')
  # Process substitution은 fd 수명이 해당 command에 묶이므로 curl command line에서 직접 만든다.
  if [[ -n "$body" ]]; then
    status="$(curl "${args[@]}" -H 'Content-Type: application/json' --data-binary @<(printf '%s' "$body") \
      -K <(printf '%s\n' "$auth") "$API$path")" || fail "$method $path: curl error"
  else
    status="$(curl "${args[@]}" -K <(printf '%s\n' "$auth") "$API$path")" || fail "$method $path: curl error"
  fi
  if [[ "$status" != "$expected" ]]; then
    fail "$method $path: expected HTTP $expected, got $status: $(head -c 300 "$response")"
  fi
  cat "$response"
}

expect_json() { # JSON JQ_FILTER DESCRIPTION  (filter는 env.* 로 state를 참조한다)
  jq -e "$2" >/dev/null <<<"$1" || fail "$3: unexpected response $(jq -c . <<<"$1" | head -c 300)"
}

dev_git() {
  local basic
  basic="$(printf '%s:%s' "$DEV_USER" "$DEV_TOKEN" | base64 | tr -d '\n')"
  GIT_CONFIG_COUNT=1 GIT_CONFIG_KEY_0=http.extraHeader GIT_CONFIG_VALUE_0="Authorization: Basic $basic" git "$@"
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
  local _ json
  for _ in $(seq 1 120); do
    json="$(request "$DEV_AUTH" GET "/repos/$DEV_USER/$REPO" 200)"
    if jq -e '.empty == false' >/dev/null <<<"$json"; then return 0; fi
    sleep 0.5
  done
  fail "Forgejo did not finish processing the initial push within 60s (repository still empty)"
}

read_pull_request() {
  local pr
  pr="$(request "$DEV_AUTH" GET "/repos/$DEV_USER/$REPO/pulls/$PR_NUMBER" 200)"
  expect_json "$pr" '.number == (env.PR_NUMBER | tonumber) and .title == env.PR_TITLE and .state == "open"
    and .base.ref == "main" and .head.ref == env.FEATURE_BRANCH and .head.sha == env.FEATURE_SHA' "pull request read"
}

read_issue() {
  local issue
  issue="$(request "$DEV_AUTH" GET "/repos/$DEV_USER/$REPO/issues/$ISSUE_NUMBER" 200)"
  expect_json "$issue" '.number == (env.ISSUE_NUMBER | tonumber) and .title == env.ISSUE_TITLE and .state == "open"
    and .pull_request == null' "issue read"
}

create() {
  : "${FORGEJO_ADMIN_USERNAME:?}" "${FORGEJO_ADMIN_PASSWORD:?}"
  rm -rf "$JOURNEY_DIR"
  mkdir -p "$JOURNEY_DIR"
  local run_id dev_password token_json user_json repo_json branch_json pr_json issue_json work clone initial_sha
  run_id="$(date -u +%Y%m%d%H%M%S)-$(od -An -N3 -tx1 /dev/urandom | tr -d ' \n')"
  export RUN_ID="$run_id" DEV_USER="dev-$run_id"
  export CLONE_URL="$FORGEJO_URL/$DEV_USER/$REPO.git"

  # 1. Disposable developer identity (fixture: admin이 계정만 만들고, token은 developer 본인이 발급)
  dev_password="$(od -An -N18 -tx1 /dev/urandom | tr -d ' \n')"
  request "user = \"$FORGEJO_ADMIN_USERNAME:$FORGEJO_ADMIN_PASSWORD\"" POST /admin/users 201 \
    "$(DEV_PASSWORD="$dev_password" jq -nc '{username: env.DEV_USER, email: (env.DEV_USER + "@example.com"),
      password: env.DEV_PASSWORD, must_change_password: false}')" >/dev/null
  token_json="$(request "user = \"$DEV_USER:$dev_password\"" POST "/users/$DEV_USER/tokens" 201 \
    '{"name":"journey","scopes":["write:repository","write:issue","write:user"]}')"
  DEV_TOKEN="$(jq -r .sha1 <<<"$token_json")"
  unset dev_password token_json
  DEV_AUTH="header = \"Authorization: token $DEV_TOKEN\""
  printf 'DEV_USER=%q\nDEV_TOKEN=%q\n' "$DEV_USER" "$DEV_TOKEN" >"$JOURNEY_DIR/credentials.env"
  user_json="$(request "$DEV_AUTH" GET /user 200)"
  expect_json "$user_json" '.login == env.DEV_USER and .is_admin == false' "developer identity"
  pass "1 developer identity ready ($DEV_USER, non-admin, token auth)"

  # 2. Private repository
  repo_json="$(request "$DEV_AUTH" POST /user/repos 201 \
    "$(jq -nc '{name: env.REPO, private: true, auto_init: false, default_branch: "main"}')")"
  expect_json "$repo_json" '.private == true and .owner.login == env.DEV_USER and .clone_url == env.CLONE_URL' \
    "private repository create"
  expect_anonymous_denied
  pass "2 private repository ready ($DEV_USER/$REPO, anonymous read denied)"

  # 3. Initial Git push
  work="$JOURNEY_DIR/work"
  git init -q -b main "$work"
  printf '# journey %s\n' "$RUN_ID" >"$work/README.md"
  git -C "$work" add README.md
  git -C "$work" commit -q -m "journey: initial commit"
  git -C "$work" remote add origin "$CLONE_URL"
  dev_git -C "$work" push -q origin main
  initial_sha="$(git -C "$work" rev-parse HEAD)"
  expect_remote_ref "$work" refs/heads/main "$initial_sha" "initial push"
  wait_initial_push_processed
  export INITIAL_SHA="$initial_sha"
  branch_json="$(request "$DEV_AUTH" GET "/repos/$DEV_USER/$REPO/branches/main" 200)"
  expect_json "$branch_json" '.commit.id == env.INITIAL_SHA' "initial push branch read"
  pass "3 initial push main=$initial_sha (Forgejo push processing complete)"

  # 4. Authenticated clone
  clone="$JOURNEY_DIR/clone"
  dev_git clone -q "$CLONE_URL" "$clone"
  [[ "$(git -C "$clone" rev-parse HEAD)" == "$initial_sha" ]] || fail "clone HEAD mismatch"
  cmp -s "$work/README.md" "$clone/README.md" || fail "clone content mismatch"
  pass "4 authenticated clone"

  # 5. Fetch (다른 working copy가 main에 push한 새 commit을 fetch)
  printf 'second commit %s\n' "$RUN_ID" >>"$work/README.md"
  git -C "$work" commit -q -am "journey: second commit"
  dev_git -C "$work" push -q origin main
  export MAIN_SHA
  MAIN_SHA="$(git -C "$work" rev-parse HEAD)"
  dev_git -C "$clone" fetch -q origin
  [[ "$(git -C "$clone" rev-parse origin/main)" == "$MAIN_SHA" ]] || fail "fetch did not observe main=$MAIN_SHA"
  git -C "$clone" merge -q --ff-only origin/main
  pass "5 fetch main=$MAIN_SHA"

  # 6. Feature branch push
  git -C "$clone" switch -q -c "$FEATURE_BRANCH"
  printf 'feature %s\n' "$RUN_ID" >"$clone/feature.txt"
  git -C "$clone" add feature.txt
  git -C "$clone" commit -q -m "journey: feature change"
  dev_git -C "$clone" push -q origin "$FEATURE_BRANCH"
  export FEATURE_SHA
  FEATURE_SHA="$(git -C "$clone" rev-parse HEAD)"
  expect_remote_ref "$clone" "refs/heads/$FEATURE_BRANCH" "$FEATURE_SHA" "feature branch push"
  pass "6 feature branch push $FEATURE_BRANCH=$FEATURE_SHA"

  # 7-8. Pull Request create/read
  export PR_TITLE="journey pull request $RUN_ID"
  pr_json="$(request "$DEV_AUTH" POST "/repos/$DEV_USER/$REPO/pulls" 201 \
    "$(jq -nc '{base: "main", head: env.FEATURE_BRANCH, title: env.PR_TITLE, body: "developer journey"}')")"
  export PR_NUMBER
  PR_NUMBER="$(jq -r .number <<<"$pr_json")"
  pass "7 pull request create #$PR_NUMBER"
  read_pull_request
  pass "8 pull request read #$PR_NUMBER"

  # 9-10. Issue create/read
  export ISSUE_TITLE="journey issue $RUN_ID"
  issue_json="$(request "$DEV_AUTH" POST "/repos/$DEV_USER/$REPO/issues" 201 \
    "$(jq -nc '{title: env.ISSUE_TITLE, body: "developer journey"}')")"
  export ISSUE_NUMBER
  ISSUE_NUMBER="$(jq -r .number <<<"$issue_json")"
  pass "9 issue create #$ISSUE_NUMBER"
  read_issue
  pass "10 issue read #$ISSUE_NUMBER"

  printf '%s=%q\n' RUN_ID "$RUN_ID" MAIN_SHA "$MAIN_SHA" FEATURE_SHA "$FEATURE_SHA" \
    PR_NUMBER "$PR_NUMBER" PR_TITLE "$PR_TITLE" ISSUE_NUMBER "$ISSUE_NUMBER" ISSUE_TITLE "$ISSUE_TITLE" \
    >"$JOURNEY_DIR/state.env"
}

verify() {
  # shellcheck source=/dev/null
  source "$JOURNEY_DIR/credentials.env"
  # shellcheck source=/dev/null
  source "$JOURNEY_DIR/state.env"
  export DEV_USER RUN_ID MAIN_SHA FEATURE_SHA PR_NUMBER PR_TITLE ISSUE_NUMBER ISSUE_TITLE
  export CLONE_URL="$FORGEJO_URL/$DEV_USER/$REPO.git"
  DEV_AUTH="header = \"Authorization: token $DEV_TOKEN\""
  local clone="$JOURNEY_DIR/clone" fresh json

  json="$(request "$DEV_AUTH" GET /user 200)"
  expect_json "$json" '.login == env.DEV_USER and .is_admin == false' "developer identity"
  json="$(request "$DEV_AUTH" GET "/repos/$DEV_USER/$REPO" 200)"
  expect_json "$json" '.private == true' "private repository read"
  expect_anonymous_denied
  pass "developer token and private repository retained (anonymous read denied)"

  fresh="$(mktemp -d "$JOURNEY_DIR/verify-clone.XXXXXX")"
  dev_git clone -q "$CLONE_URL" "$fresh"
  [[ "$(git -C "$fresh" rev-parse HEAD)" == "$MAIN_SHA" ]] || fail "clone main mismatch"
  [[ "$(git -C "$fresh" rev-parse "origin/$FEATURE_BRANCH")" == "$FEATURE_SHA" ]] || fail "clone feature branch mismatch"
  [[ "$(head -n 1 "$fresh/README.md")" == "# journey $RUN_ID" ]] || fail "repository content mismatch"
  pass "authenticated clone main=$MAIN_SHA $FEATURE_BRANCH=$FEATURE_SHA content retained"

  dev_git -C "$clone" fetch -q origin
  [[ "$(git -C "$clone" rev-parse origin/main)" == "$MAIN_SHA" ]] || fail "fetch main mismatch"
  [[ "$(git -C "$clone" rev-parse "origin/$FEATURE_BRANCH")" == "$FEATURE_SHA" ]] || fail "fetch feature branch mismatch"
  pass "fetch in existing clone"

  read_pull_request
  pass "pull request #$PR_NUMBER retained"
  read_issue
  pass "issue #$ISSUE_NUMBER retained"
}

case "$MODE" in
  create) create ;;
  verify) verify ;;
  *) fail "unknown mode: $MODE" ;;
esac
printf '[journey:%s] PASS %d developer operations/checks\n' "$LABEL" "$operations"
