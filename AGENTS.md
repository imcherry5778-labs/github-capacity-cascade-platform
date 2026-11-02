# AGENTS.md

이 저장소는 SRE / Platform Engineering case study다. 작업자는 기능 수보다 **합의된 milestone/work-unit contract의 최소·검증 가능한 변경**을 우선한다.

## 1. Source of truth

**현재 repository state와 normative contract를 섞지 않는다.**

현재 repository state의 authority:

- GitHub `main`, actual PR/HEAD, CI/check, review state, branch state와 relevant repository setting/ruleset

현재 work unit의 normative contract:

1. ChatGPT가 해당 work unit 시작 전에 확정한 scope/non-goals/acceptance
2. current `main`의 repository contract documents

Repository contract documents:

- `docs/charter.md`
- `docs/architecture.md`
- `docs/roadmap.md`
- `docs/implementation-plan.md`
- `docs/conventions.md`
- `docs/terminology.md`
- `AGENTS.md`

Current official upstream은 REVALIDATE의 evidence source다. Upstream과 normative contract가 충돌하면 구현자가 조용히 contract를 바꾸지 않고 중단/보고해 specification을 먼저 보정한다.

Archive/legacy repository는 historical reference일 뿐 current contract가 아니다. 과거 agent 설명이나 local unmerged work를 source of truth로 사용하지 않는다.

## 2. Roles

### ChatGPT

- milestone 진입 전에 actual `main`, previous evidence와 current upstream을 딥리서치한다.
- 현재 milestone만 reviewable work-unit graph로 분해한다.
- 각 work unit의 architecture relevance, scope/non-goals, safety, REVALIDATE result, acceptance/evidence를 정의한다.
- architecture/spec correction은 docs-only PR로 제안/정리할 수 있지만 implementation source 수정은 Local AI Agent에 위임한다.
- 사용 가능한 연결로 작업·교정을 직접 전달한다. 기본적으로 Local Agent가 실행하고 사용자가 완료 또는 실제 blocker의 결과 링크를 가져오면 검토하며, routine prompt 전달이나 상시 감독을 전제하지 않는다.
- exact-head CI/review 뒤 actual PR/diff/HEAD/check/review thread를 독립 검토한다.
- 문제가 없을 때 검토한 exact HEAD를 기준으로 squash merge한다.

### Local AI Agent

Repository implementation executor. **새 work unit의 초기 context는 fresh를 기본**으로 하고 actual Git/GitHub state를 확인한다. 합의된 범위의 추가 조사·세부 계획·구현·검증·CI 대응·승인된 운영/복구·evidence 정리를 소유한다. Agent는 merge하지 않는다.

여기서 **fresh session**은 agent context의 시작이며 Git lifecycle과는 별개다. 같은 work unit의 `CONTINUE_EXISTING_PR`은 기존 session을 재사용/resume한다. 재개 불가 또는 구체적인 context 품질 문제로 교체해도 worktree/branch/PR/evidence를 보존하고 경쟁 writer 부재를 확인한다. Implementation writer/cloud mutation owner는 각각 하나만 둔다.

Milestone 첫 work unit은 ChatGPT가 확정한 milestone decomposition을 읽고 시작한다. 같은 intent/acceptance/safety/권한 경계의 세부 계획과 구현 방법은 Agent가 evidence에 따라 조정한다. 계약 변경이나 work-unit 재분해는 ChatGPT가 판단하며, 사용자 권한이 필요한 결정은 기존 승인 범위를 넘겨 대신 승인하지 않는다. 같은 boundary 안의 오류 복구는 §5를 따른다.

### GitHub

Remote source of truth, PR change-management boundary, exact-head CI/review surface.

## 3. Empty-repository bootstrap exception

완전히 빈 새 repository에서 Git ref를 만들기 위한 **최소 bootstrap commit**만 일반 PR cycle의 1회성 예외다. Bootstrap commit에는 implementation이나 milestone 완료 claim을 넣지 않는다.

P0 specification 자체는 bootstrap 이후 feature branch / PR / exact-head review 경계를 따른다. P0 merge 이후 `main` direct implementation push와 force-push를 금지한다.

## 4. Fresh work-unit start

이 절차는 새 work unit의 branch를 시작할 때 적용한다. 기존 PR의 Agent context 재개·교체는 현재 worktree/branch/PR을 보존하고 필요한 상태만 확인하며, 아래의 main 전환·새 branch·이전 작업 cleanup을 자동 적용하지 않는다. 새 work unit의 Agent는 먼저 확인한다.

- repository/remote URL
- `git status`
- current branch
- `git fetch --all --prune`
- local/remote `main` SHA
- local/remote branches
- `git worktree list`
- 이전 work unit PR state/final head
- current milestone/work-unit contract

예상하지 못한 dirty worktree를 임의 reset/stash하지 않는다.

### Previous work-unit cleanup

이전 work unit이 실제 merge된 경우에만 그 작업의 local worktree/local branch를 정리한다.

Remote head branch lifecycle은 actual GitHub repository policy를 따른다.

- GitHub native setting이 merged head branch automatic deletion을 소유하면 Local AI Agent는 이를 정상 경로로 중복 삭제하지 않고 `git fetch --all --prune` 뒤 remote-tracking ref가 정리됐는지 확인한다.
- native cleanup이 적용되지 않았거나 expected cleanup 뒤에도 remote branch가 남은 경우에만 fallback cleanup을 검토한다.
- fallback remote branch 삭제 전에는 PR `merged`, final PR head SHA, current remote branch HEAD, 보존할 unique work 부재를 확인하고 exact branch name 하나만 삭제한다.
- Wildcard/prefix/bulk branch deletion을 금지한다.

이전 merged work cleanup 뒤 새 work-unit branch를 만들기 전에:

1. `git switch main`
2. local `main`이 예상하지 못한 dirty/diverged 상태가 아닌지 확인
3. `git merge --ff-only origin/main`
4. local `main` SHA와 `origin/main` SHA가 같은지 확인

동일하지 않거나 fast-forward가 불가능하면 임의 reset/rebase하지 않고 중단/보고한다.

## 5. Implementation cycle

새 work unit은 §4 뒤 clean/synchronized `main`에서 새 feature branch를 만든다. 기존 작업의 수정은 같은 branch/PR에서 수행한다.

1. current upstream/runtime preflight
2. 합의 scope 구현
3. 직접 영향받는 local/static test
4. self-review
5. commit
6. push
7. PR 생성

PR 생성만으로 작업 완료를 주장하지 않는다. 관련 필수 CI 결과 확인·in-scope 실패 교정과 적용되는 실행·원복 evidence 정리까지 수행한 뒤 PR/exact HEAD/acceptance 근거를 연결해 보고한다. 승인 범위에서 해결할 수 없는 blocker는 부분 결과·시도한 조치·남은 한도·안전 상태와 필요한 판단을 보고한다.

다음 work unit capability를 선제 구현하지 않는다. 한 PR은 가능한 한 하나의 capability다.

검증·조사·승인 정리는 현재 acceptance를 막는 문제와 실제 권한 결정에 한정한다. 환경을 보존한 채 검토만 반복하는 지연도 비용이다. 변경 없는 source/CI·관측·승인 근거는 재사용하고, 영향 검증과 source 검토는 CI 대기 중 병행한다. 이미 충분한 evidence가 있으면 ChatGPT가 바로 판단·직접 전달하며, 승인안 작성→결과 전달→동일 내용 재검토를 별도 작업으로 반복하지 않는다. 새 사용자 결정만 기존 승인 링크와 변경점으로 한 번에 묶고 같은 유효 승인 안의 행동은 재승인받지 않는다.

### 복구와 실행 중단 경계

Scope/acceptance/safety boundary가 바뀌지 않는 구현·운영 오류는 Agent가 원인 파악 → 수정 → 영향 검증 → 계속 진행한다. 계약/권한 충돌 또는 가용 증거로 더 진행할 수 없는 기술적 blocker는 구체 근거와 최소 다음 행동을 ChatGPT에 전달해 escalation한다.

위험 행동·부하 중단 및 필요한 fault release/isolation과 campaign 전체 종료/원복을 구분한다. 안전·ownership·비용·기한이 유지되고 해당 실행 승인이 bounded recovery를 허용하면 같은 campaign에서 고치고 진행한다. 시작한 실패 run은 invalid/횟수 소비로 보존하며 재개해 valid로 만들지 않는다. 다음 calibration은 원인 조치 후 남은 승인 횟수·비용·시간 안에서만 가능하다. 근거 없는 반복·카운터 초기화·acceptance 완화는 금지한다.

Campaign은 사용자 중단·범위 완료·안전/ownership 복구 불가·승인상 종료·횟수/비용/retention reserve 소진일 때 owned cleanup으로 종료하며, 실패 한 번 자체를 종료 사유로 삼지 않는다.

유료·credential 관련 실행 전에는 변경되었거나 아직 검증하지 않은 실제 operator 호출·process 소유·민감 출력·owned cleanup 및 횟수/복구 gate만 필요한 만큼 확인한다. 반복 실패의 교정 근거와 다음 관측은 기존 결과에 짧게 연결하고, 완전한 원인 규명이나 새로운 승인 문서 작성을 진입 조건으로 추가하지 않는다. 비용·권한 확인의 시점과 재사용은 `docs/implementation-plan.md`의 Paid Azure boundary를 따른다.

Source 수정과 cost-free 검증은 진행할 수 있다. 승인이 exact SHA로만 한정되어 있으면 변경 SHA의 paid 경로는 필요한 review/승인 전까지 보류한다. 향후 승인이 동일 scope의 bounded source correction을 명시적으로 포함해도 실제 실행 gate가 해당 복구·누적 계수를 지원하는지 확인하고, 영향 검증·독립 review·새 SHA/image/plan binding을 마친 범위에서만 진행한다. 보존 기한 자동 연장이나 전체 Environment teardown을 복구 수단으로 삼지 않는다.

## 6. Exact-head review / fix

PR exact-head CI/review 후 ChatGPT가 actual PR, base/head SHA, diff, CI/check, review status/thread를 다시 본다.

문제가 있으면 **같은 local branch / remote branch / PR**에서 수정한다. HEAD가 바뀔 때마다 영향받는 test/CI를 다시 검증한다.

## 7. Merge / next baseline

Local AI Agent는 merge하지 않는다.

ChatGPT가 검토한 exact PR HEAD를 기준으로 squash merge하고, merge 후 PR merged state와 새 `main` SHA를 확인한다.

Relevant native post-merge repository policy가 있으면 실제 적용 결과도 확인한다. GitHub native policy가 merged remote head branch lifecycle을 소유하는 경우 이를 정상 cleanup 경로로 사용하고, 기대한 cleanup이 일어나지 않으면 policy drift/fallback cleanup으로 취급한다.

그 새 `main` SHA가 다음 work unit의 단일 remote baseline이다.

방금 merge된 work의 local worktree/local branch cleanup과 local `main` fast-forward synchronization은 다음 새 work unit을 맡은 Local AI Agent가 상태를 독립 확인 후 수행한다.

Milestone의 마지막 work unit이 merge되면 ChatGPT가 milestone exit evidence를 확인하고 다음 milestone deep research/decomposition을 수행한다.

## 8. Overengineering guard

- empty future directory / `.gitkeep` 금지
- 현재 acceptance에 필요하지 않은 tool/controller/service 선제 도입 금지
- 실제 중복/독립 lifecycle 전 module/helper 추출 금지
- Forgejo application-tier Redis/Valkey, Forgejo HA, Backstage, full Argo UI/HA, separate GitOps repo, multi-region 등을 이름값으로 추가하지 않음
- Argo CD Core 등 chosen control plane의 upstream dependency를 Forgejo dependency 금지와 혼동하지 않음
- implementation 결과에 맞춘 acceptance 사후 완화 금지
- 같은 standing rule을 `AGENTS.md`, session prompt, 별도 custom-instruction 파일에 중복 작성하지 않음
- 반복되는 실제 실패 패턴이 확인되기 전에는 custom agent/skill/prompt-file을 추가하지 않음
- portfolio/presentation/personal-learning artifact를 engineering repo에 섞지 않음

## 9. Upstream / version

과거 exact 값을 근거 없이 복원하지 않는다.

특히 필요한 work unit 직전에 확인:

- Forgejo exact LTS patch/chart
- Argo CD version/commit과 upstream dependency
- Terraform/AzureRM version
- GitHub OIDC subject/environment protection
- AKS version/region/managed Istio revision
- managed Istio customization/support boundary
- selected ingress/routing API
- selected Envoy stat mapping
- KEDA metric/scaler contract

Final/reviewed evidence에는 필요한 actual version/digest를 기록한다.

## 10. Stable / experiment ownership

Experiment는 Argo-owned stable resource를 직접 mutation하지 않는다. AKS managed controller lifecycle을 단순히 GitOps라는 이유로 Argo에 넣지 않는다.

Reliability experiment 전에 관련 normal test가 PASS해야 한다.

## 11. Evidence

- raw run append-only
- negative result를 성공처럼 수정하지 않음
- valid run / hypothesis support 구분
- reviewed/final evidence에 exact source commit 기록
- secret/private local path/credential 제외 (공개 artifact뿐 아니라 tool/REPL 반환값·stdout/stderr·예외·cleanup 출력 포함; publication scan/보호 사본 제거는 노출된 credential의 별도 처리·회전을 대체하지 않음)
- 측정하지 않은 결과 claim 금지
- engineering evidence와 portfolio/presentation copy를 분리

`PASS`, `verified`, `reproduced`, `restored`, `zero residual`은 실제 evidence 확인 후에만 사용한다.

반복 실패·중대한 안전 사고·불필요한 재작업의 개선안은 기존 결과에 짧게 남기되, 다음 acceptance에 필요하지 않은 문서·회고·정비는 작업을 막지 않는다. 실제 credential 노출·권한 이탈은 처리하지만, 완료된 조치를 재조사하거나 근거 없는 session/output 잔여 위험만으로 전역 cleanup·새 위험수용 승인·추가 캠페인을 만들지 않는다. 남은 unknown은 그대로 기록하고 필수 gate 미충족·구체적인 진행 중 위협·승인 밖 영향이 있을 때만 해당 위험 행동을 멈춘다. 안전한 독립 작업은 계속한다.

## 12. Azure safety

- Azure PAYG
- explicit approval 없이 provision/destroy 금지
- PR CI에서 Azure resource 자동 생성 금지
- paid apply 전 필요한 bounded cost/resource/RBAC/quota 확인; 재사용·재확인 기준은 Paid Azure boundary 한 곳을 따른다
- P11까지 기존 환경 재사용을 우선하며 lifecycle authority는 `docs/implementation-plan.md`의 Paid Azure boundary
- 명시적 승인 범위·보존 기한 유지, 자동 연장·자동 삭제 없음
- finalization은 DNS delegation, identity/RBAC, state backend, residual resource까지 확인

## 13. Language / Git

- human docs: 한국어 기본
- product/API/metric/CLI/code/path: 공식 영어
- branch: 영어
- commit/PR title: `<english type>(<english scope>): <한글 설명>`
- PR body: 한국어
- main: squash merge 기본

## 14. Session meta-prompt contract

ChatGPT가 Local AI Agent session에 전달하는 work-unit prompt는 **이번 작업에만 필요한 delta**를 담는다. Repository-wide standing rule은 `AGENTS.md`를 다시 길게 복사하지 않고 읽도록 지시한다.

권장 구조:

1. **Mission** — 이번 work unit에서 최종적으로 무엇이 true여야 하는지 정의
2. **Expected baseline** — repository, expected `main`/PR HEAD, 이전 merged work unit과 relevant native repository policy처럼 실행 전 확인할 상태
3. **Read first** — `AGENTS.md`와 이번 work unit에 직접 필요한 문서/path
4. **Scope / non-goals** — 해야 할 것과 하지 않을 것을 관찰 가능한 단위로 명시
5. **Decisions / revalidation** — 관련 DECIDED 사항과 이번 session에서 확인할 REVALIDATE/DEFERRED 항목
6. **Acceptance / validation** — 완료 조건과 실제 실행할 test/static/runtime validation/evidence
7. **Safety / stop conditions** — dirty worktree, baseline 불일치, upstream/spec 충돌, destructive/external side effect 등
8. **Git deliverable / final report** — branch/commit/push/PR 경계와 최종 보고할 SHA, test 결과, 남은 issue

원칙:

- 같은 지시는 한 번만 쓴다.
- 이미 repository 문서가 정의한 내용을 prompt에 장문 복제하지 않는다.
- 구현 방법보다 완료 상태와 acceptance를 우선하며, DECIDED architecture만 필요한 수준으로 구체화한다.
- 예상 가능한 실패/분기점에는 fail-closed 행동을 명시한다.
- Agent는 repository를 먼저 읽고 실제 상태와 prompt가 충돌하면 조용히 재해석하지 말고 중단/보고한다.
- Scope가 끝날 때까지 작업·검증·self-review를 완료하고, blocker가 있을 때만 부분 상태와 근거를 보고한다.
