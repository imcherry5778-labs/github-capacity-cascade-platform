# AGENTS.md

이 저장소는 SRE / Platform Engineering case study다. 작업자는 기능 수보다 **합의된 milestone contract의 최소·검증 가능한 변경**을 우선한다.

## 1. Source of truth

**현재 상태와 normative contract를 섞지 않는다.**

현재 repository 상태의 authority:

- GitHub `main`, actual PR/HEAD, CI/check, review state

현재 work unit의 normative contract:

1. ChatGPT가 해당 unit 시작 전에 확정한 scope/non-goals/acceptance
2. P0 repository documents

Current official upstream은 REVALIDATE의 evidence source다. Upstream과 normative contract가 충돌하면 구현자가 조용히 contract를 바꾸지 않고 중단/보고해 specification을 먼저 보정한다.

Archive/legacy repository는 historical reference일 뿐 current contract가 아니다. 과거 agent 설명이나 local unmerged work를 source of truth로 사용하지 않는다.

## 2. Roles

### ChatGPT

Milestone 시작 전에 architecture relevance, scope/non-goals, safety, REVALIDATE result, acceptance/evidence를 정의한다.

Exact-head CI/review 뒤 actual PR/diff/HEAD/check/review thread를 독립 검토하고, 문제가 없을 때 검토한 exact HEAD를 기준으로 squash merge한다.

### Local AI Agent

Repository implementation executor. **각 새 milestone은 새 세션**에서 시작하고 actual Git/GitHub state를 독립 확인한다. Agent는 merge하지 않는다.

### GitHub

Remote source of truth, PR change-management boundary, exact-head CI/review surface.

## 3. Empty-repository bootstrap exception

완전히 빈 새 repository에서 Git ref를 만들기 위한 **최소 bootstrap commit**만 일반 PR cycle의 1회성 예외다. Bootstrap commit에는 implementation이나 milestone 완료 claim을 넣지 않는다.

P0 specification 자체는 bootstrap 이후 feature branch / PR / exact-head review 경계를 따른다. P0 merge 이후 `main` direct implementation push와 force-push를 금지한다.

## 4. Fresh milestone start

Fresh Local AI Agent는 먼저 확인한다.

- repository/remote URL
- `git status`
- current branch
- `git fetch --all --prune`
- local/remote `main` SHA
- local/remote branches
- `git worktree list`
- 이전 milestone PR state/final head

예상하지 못한 dirty worktree를 임의 reset/stash하지 않는다.

### Previous milestone cleanup

이전 milestone이 실제 merge된 경우에만 그 작업의 worktree/local branch/remote branch를 정리한다.

Remote branch 삭제 전:

1. PR `merged` 확인
2. final PR head SHA 확인
3. remote branch HEAD 확인
4. 보존할 unique work 부재 확인
5. exact branch name 하나만 삭제

Wildcard/prefix/bulk branch deletion을 금지한다.

## 5. Implementation cycle

Cleanup 뒤 clean/synchronized `main`에서 새 feature branch를 만든다.

1. current upstream preflight
2. 합의 scope 구현
3. 직접 영향받는 local/static test
4. self-review
5. commit
6. push
7. PR 생성

다음 milestone capability를 선제 구현하지 않는다. 한 PR은 가능한 한 하나의 capability다.

## 6. Exact-head review / fix

PR exact-head CI/review 후 ChatGPT가 actual PR, base/head SHA, diff, CI/check, review status/thread를 다시 본다.

문제가 있으면 **같은 local branch / remote branch / PR**에서 수정한다. HEAD가 바뀔 때마다 영향받는 test/CI를 다시 검증한다.

## 7. Merge / next baseline

Local AI Agent는 merge하지 않는다.

ChatGPT가 검토한 exact PR HEAD를 기준으로 squash merge하고, merge 후 PR merged state와 새 `main` SHA를 확인한다.

그 SHA가 다음 milestone의 단일 기준점이다.

방금 merge된 feature branch/worktree cleanup은 다음 **fresh Local AI Agent**가 독립 확인 후 수행한다.

## 8. Overengineering guard

- empty future directory / `.gitkeep` 금지
- 현재 acceptance에 필요하지 않은 tool/controller/service 선제 도입 금지
- 실제 중복/독립 lifecycle 전 module/helper 추출 금지
- Redis/Valkey, Forgejo HA, Backstage, full Argo UI/HA, separate GitOps repo, multi-region 등을 이름값으로 추가하지 않음
- implementation 결과에 맞춘 acceptance 사후 완화 금지
- 같은 standing rule을 `AGENTS.md`, session prompt, 별도 custom-instruction 파일에 중복 작성하지 않음
- 반복되는 실제 실패 패턴이 확인되기 전에는 custom agent/skill/prompt-file을 추가하지 않음

## 9. Upstream / version

P0의 REVALIDATE/DEFERRED 값을 archive exact 값으로 복원하지 않는다.

특히 implementation 직전에 확인:

- Forgejo exact LTS patch/chart
- Argo CD version/commit
- Terraform/AzureRM version
- GitHub OIDC subject/environment protection
- AKS version/region/managed Istio revision
- managed Istio customization/support boundary
- selected Envoy stat mapping
- KEDA metric/scaler contract

Final evidence에는 actual version/digest를 기록한다.

## 10. Stable / experiment ownership

Experiment는 Argo-owned stable resource를 직접 mutation하지 않는다. AKS managed controller lifecycle을 단순히 GitOps라는 이유로 Argo에 넣지 않는다.

Reliability experiment 전에 관련 normal test가 PASS해야 한다.

## 11. Evidence

- raw run append-only
- negative result를 성공처럼 수정하지 않음
- valid run / hypothesis support 구분
- final evidence exact source commit 기록
- secret/private local path/credential 제외
- 측정하지 않은 결과 claim 금지

`PASS`, `verified`, `reproduced`, `restored`, `zero residual`은 실제 evidence 확인 후에만 사용한다.

## 12. Azure safety

- Azure PAYG
- explicit approval 없이 provision/destroy 금지
- PR CI에서 Azure resource 자동 생성 금지
- paid apply 전 current cost/resource/RBAC/quota preflight
- paid environment same-day destroy 기본
- 24시간 초과 유지에는 새 승인
- finalization은 DNS delegation, identity/RBAC, state backend, residual resource까지 확인

## 13. Language / Git

- human docs: 한국어 기본
- product/API/metric/CLI/code/path: 공식 영어
- branch: 영어
- commit/PR title: `<english type>(<english scope>): <한글 설명>`
- PR body: 한국어
- main: squash merge 기본


## 14. Session meta-prompt contract

ChatGPT가 Fresh Local AI Agent에 전달하는 milestone prompt는 **이번 작업에만 필요한 delta**를 담는다. Repository-wide standing rule은 `AGENTS.md`를 다시 길게 복사하지 않고 읽도록 지시한다.

권장 구조:

1. **Mission** — 이번 unit에서 최종적으로 무엇이 true여야 하는지 한 문단으로 정의
2. **Expected baseline** — repository, expected `main` SHA, 이전 merged PR/unit처럼 실행 전 확인할 상태
3. **Read first** — `AGENTS.md`와 이번 unit에 직접 필요한 문서/path만 지정
4. **Scope / non-goals** — 해야 할 것과 하지 않을 것을 관찰 가능한 단위로 명시
5. **Decisions / revalidation** — 관련 DECIDED 사항과 이번 세션에서 확인할 REVALIDATE/DEFERRED 항목
6. **Acceptance / validation** — 완료 조건과 실제 실행할 test/static validation/evidence
7. **Safety / stop conditions** — dirty worktree, baseline SHA 불일치, upstream/spec 충돌, 예상하지 못한 external side effect처럼 임의 진행하면 안 되는 조건
8. **Git deliverable / final report** — branch/commit/push/PR 경계와 최종 보고할 SHA, test 결과, 남은 issue

원칙:

- 같은 지시는 한 번만 쓴다.
- 이미 repository 문서가 정의한 내용을 prompt에 장문 복제하지 않는다.
- 구현 방법보다 완료 상태와 acceptance를 우선하며, DECIDED architecture만 필요한 수준으로 구체화한다.
- Step마다 실제 action/output이 무엇인지 모호하지 않게 쓴다.
- 예상 가능한 실패/분기점에는 fail-closed 행동을 명시한다.
- Agent는 repository를 먼저 읽고 실제 상태와 prompt가 충돌하면 조용히 재해석하지 말고 중단/보고한다.
- Scope가 끝날 때까지 작업·검증·self-review를 완료하고, blocker가 있을 때만 부분 상태와 근거를 보고한다.
