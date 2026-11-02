# Implementation Plan

## 1. 목적

Roadmap을 **현재 milestone의 reviewable work unit**으로 분해하는 실행 규칙을 정의한다.

P0에서 미래 milestone의 PR/task 개수, exact file/API/version을 미리 고정하지 않는다. Long-range contract는 architecture/milestone dependency로 유지하고, 실제 work-unit graph는 해당 milestone 진입 시 current repository/upstream/evidence를 보고 만든다.

## 2. Milestone dependency

기본 engineering 순서는 다음과 같다.

```text
P0 → P1 → P2 → P3 → P4 → P5 → P6 → P7 → P8 → P9 → P10 → P11
```

Hard gates:

- P3 measurement/recovery contract가 P4 failure experiment보다 먼저다.
- P4 Local mechanism proof가 P5 Azure source에 반영되어야 한다.
- P6 actual Azure action은 P5 preflight, P4 mechanism proof, current cost/quota/RBAC와 explicit user approval이 필요하다.
- P7은 P6 actual platform calibration 뒤에 수행한다.
- P8은 P7 operations signal path와 P4 mechanism proof, current paid-environment preflight, explicit approval이 필요하다.
- P9는 P8 controlled incident evidence와 explicit approval이 필요하다.
- P10은 P8/P9 evidence를 근거로 redesign하며 actual Azure action 전에 explicit approval을 다시 확인한다.
- P11은 P10까지의 engineering claim/evidence를 regression/finalization하며 final Azure action이 있으면 별도 preflight/approval을 거친다.

## 3. Milestone entry gate

ChatGPT는 milestone 시작 전에 다음을 수행한다.

1. actual `main`, previous merged PR/evidence와 outstanding limitation 확인
2. 해당 milestone에 필요한 current official upstream/runtime deep research
3. 관련 DECIDED / REVALIDATE / DEFERRED 항목 재분류
4. milestone capability boundary와 non-goal 확인
5. dependency와 safety/external-side-effect edge 식별
6. **현재 milestone만** 최소 reviewable work-unit graph로 분해
7. 각 work unit의 acceptance/evidence/cleanup boundary 확정

다음 milestone의 세부 task graph는 만들지 않는다.

## 4. Work-unit decomposition 기준

### 분리한다

다음 중 하나 이상이면 별도 work unit/PR을 우선 검토한다.

- 독립적인 prerequisite 또는 후속 dependency가 있다.
- 독립적인 acceptance criterion이 있다.
- rollback/cleanup/safety boundary가 다르다.
- paid/external side effect가 다르다.
- 하나의 PR이면 reviewer가 capability와 evidence를 이해하기 어렵다.
- 후속 unit이 이 결과를 명확한 prerequisite로 사용한다.

### 분리하지 않는다

다음 이유만으로 unit을 만들지 않는다.

- directory/file이 다르다.
- tool/product가 여러 개다.
- 형식적으로 PR을 작게 만들고 싶다.
- 같은 acceptance가 함께 통과해야만 capability가 의미를 가진다.
- 아직 실제 complexity가 관측되지 않았다.

기본 관계:

```text
1 work unit
≈ 하나의 일관된 acceptance boundary
≈ 가능하면 1 PR
```

Milestone이 충분히 작으면 milestone 하나가 work unit 하나일 수 있다. Agent context의 재개·교체는 작업 단위를 바꾸지 않으며 `AGENTS.md`의 session/ownership 경계를 따른다.

### Work-unit refinement

구현 중 새 evidence가 초기 계획의 세부사항을 무효화해도 **engineering intent, acceptance, safety/external-side-effect 및 승인 권한 경계가 유지**되면 Local AI Agent가 세부 실행 계획·구현 방법을 조정하고 같은 branch/PR에서 계속한다. 계약 자체의 보정이나 work-unit 재분해는 ChatGPT가 판단하며, 기존 사용자 승인 밖의 권한은 별도 승인 없이 확대하지 않는다.

다음 중 하나면 기존 work unit을 억지로 확장하지 않고 현재 milestone 안에서 재분해한다.

- engineering intent 또는 capability가 실질적으로 달라진다.
- 독립적으로 완료 가능한 별도 work가 생긴다.
- rollback/cleanup/safety/external-side-effect boundary가 달라진다.
- 기존 acceptance를 유지한 채 설명하기 어려울 정도로 scope가 확장된다.

구현 결과에 맞춰 acceptance를 사후 완화하는 것은 refinement가 아니다.

## 5. Work-unit specification gate

ChatGPT가 각 work unit 시작 전에 다음을 확정한다.

- Mission / prerequisite
- Expected baseline
- Scope / non-goals
- relevant DECIDED architecture
- REVALIDATE result
- 필요한 DEFERRED value 또는 측정 계획
- acceptance criteria
- required evidence
- cost/external side effect
- cleanup/rollback boundary
- stop conditions

구현 결과에 맞춰 acceptance를 사후 완화하지 않는다.

Local AI Agent 작업 지시는 `AGENTS.md` standing rule을 반복하지 않고 이번 work unit의 delta만 담는다.

## 6. Exact pin / runtime-dependent value

다음 값은 장기간 미래 milestone까지 선제 고정하지 않는다.

- Forgejo exact patch/chart/image digest
- Local Kubernetes/k3s patch
- Argo CD version/commit
- Terraform/AzureRM version
- AKS Kubernetes patch / managed Istio revision
- selected ingress/routing API
- exact Envoy rejection/overflow metric spelling
- KEDA metric/scaler/threshold
- Azure node/PostgreSQL SKU
- resource request/limit
- log/trace sampling
- SLO threshold
- GitHub OIDC exact subject

해당 work unit에서 필요해질 때 current official upstream/runtime을 확인하고 reproducibility가 필요한 값만 source/evidence에 pin한다.

## 7. Known milestone capability boundaries

아래는 future PR list가 아니라 milestone이 최종적으로 cover해야 할 capability boundary다.

### P3 — Local Operations Contract

- structured developer operation / attempt result
- local healthy baseline
- metric/log/correlation schema
- coordinated backup + fresh restore
- `forgejo doctor`
- upgrade/state-aware rollback
- session/PAT continuity as applicable

Shell/Git/Forgejo API 구조로 requirement를 만족할 수 있으면 별도 custom probe service를 만들지 않는다.

### P4 — Local Reliability Fixture

- minimal `ext-authz-sim`
- healthy shared gate
- HAProxy + selected Istio/Envoy path
- inbound active-request capacity target
- selected-runtime rejection signal
- no-retry baseline + bounded retry amplification
- confounder guard
- fixture cleanup/removal

Local KEDA controller는 concrete requirement가 생기기 전에는 추가하지 않는다.

### P5 — Azure IaC & Platform Source

최종 책임 boundary:

```text
infra/terraform/
├── bootstrap/
├── foundation/
└── environment/
```

- `bootstrap`: state backend, CI identity/trust, permission-boundary Resource Group/RBAC
- `foundation`: delegated project DNS, Key Vault, 필요한 최소 long-lived shared identity/resource
- `environment`: AKS, private PostgreSQL, storage/registry/network/private DNS, observability, paid runtime

DECIDED defaults:

- GitHub Actions → Azure OIDC/workload federation
- project-owned Resource Group 밖으로 privileged CI RBAC scope 확대 금지
- state container: `Storage Blob Data Contributor`
- foundation/environment RG: `Contributor` + `Role Based Access Control Administrator`
- AKS managed Istio/KEDA/Key Vault CSI + Workload Identity 우선
- actual apply 없음

P5에서 exact OIDC subject, region/quota, AKS/revision capability, ingress/routing API, supported/allowed/blocked customization boundary, pricing과 destroy order를 REVALIDATE한다.

필수 capability가 managed Istio의 blocked boundary와 충돌할 때만 self-managed Istio fallback ADR을 연다.

### Paid Azure boundary — P6–P11

P6–P11의 paid 실행은 **해당 campaign의 첫 external mutation 직전** 다음 중 실행 판단에 영향을 주는 항목만 bounded하게 확인한다. 최근 검증된 항목은 scope·source·자원·권한·가격/사용량 가정·기한에 유효성 변화가 없으면 재사용한다. 새 채팅·보고·문서 수정만으로 전체 preflight를 반복하지 않는다.

- exact source commit
- current environment state/lifetime
- current price/resource/RBAC/quota
- 필요한 external DNS delegation action
- explicit user approval와 그 approval이 cover하는 action/scope

승인은 지정 campaign·source·권한·횟수·비용·기한에 결합된다. **새 campaign 또는 승인 밖 변경에는 명시 승인이 필요**하지만, 같은 유효 승인 안의 계속 실행·허용된 복구는 날짜 변경이나 새 보고만으로 재승인받지 않는다. 이 규칙은 exact-SHA/횟수/비용/기한 gate를 완화하거나 새 campaign을 승인하지 않는다.

실행 중에는 resource/권한/사용량·단가/기한의 유의미한 변화, 실제 한도 초과 징후 또는 계약상 필수 gate가 있을 때 해당 항목만 재확인한다. 새 Pod·identity·process의 필수 live gate와 각 실행의 남은 횟수·deadline/원복 reserve 검사는 유지한다. 비용 모델은 기존 기준으로 필요한 delta만 갱신하며, 같은 보존구간·이미 계상한 allowance/uncertainty를 승인 왕복마다 새 항목으로 중복 추가하지 않는다. 기존 모델의 명시적 보수적 중복과 과거 기록은 숨기거나 소급 삭제하지 않는다.

청구 지연에 따른 실비·잔액 unknown만으로 조회·승인서 작성 루프를 만들지 않는다. 유효한 보수적 projection과 승인 한도가 유지되면 그 범위에서 진행하고, 한도를 평가할 근거가 없거나 초과 위험이 있으면 관련 유료 행동만 보류한다. 새 사용자 결정은 미승인 실행·권한/자원 확대·실제 비용/횟수/기한 변경 등 필요한 delta에 한정해 기존 승인과 함께 한 번에 요청한다.

P11까지 기존 environment 재사용을 우선한다. Milestone 종료를 same-day destroy에 연결하지 않는다. 기존 resource의 보존 승인과 다음 작업의 실행 승인은 별개이며, 현재 명시적 승인 범위와 보존 기한을 유지한다. 자동 연장·자동 삭제는 없다. 기한 조정 또는 범위 밖 실행·삭제가 필요하면 새 explicit approval을 받는다. 같은 branch/PR/evidence를 이어 쓰며 기한 조정만으로 다시 만들지 않는다.

P7-W1 시작 시 Environment 기한은 **2026-10-30 10:30 KST**, Foundation/Bootstrap은 **2026-10-31 00:33 KST**다. 이번 source 구현은 보존 기한을 변경하지 않는다. 실행 시 current state/승인과 기한을 다시 확인한다. 과거 6시간 비용 추정은 시간 무제한 비용 보장이 아니며 ActualCost는 조회 전 unknown이다.

**추가 72시간 보존 — 2026-11-02 요청**

사용자의 “3일 기간 연장 PR” 요청은 [기존 +72h 보존 승인](https://github.com/imcherry5778-labs/github-capacity-cascade-platform/pull/41#issuecomment-6509128514)의 기한에 **각각 72시간을 추가**하는 것으로 기록한다. 요청 시각부터 3일을 세거나 과거 실행의 승인·기록을 소급 변경하지 않는다.

| 대상 | 직전 승인 기한 (KST) | 추가 보존 기한 (KST) | 추가 보존 기한 (UTC) |
| --- | --- | --- | --- |
| Environment | 2026-11-02 10:30 | **2026-11-05 10:30** | `2026-11-05T01:30:00Z` |
| Foundation/Bootstrap | 2026-11-03 00:33 | **2026-11-06 00:33** | `2026-11-05T15:33:00Z` |

범위는 기존 inventory·operator·DNS/state ownership의 보존이다. 새 resource·권한·부하·제15차 또는 후속 campaign, 자동 연장·전체 teardown을 승인하지 않는다. 기존 DNS 복구·state 의존성과 owned cleanup 경계는 유지한다. 이 기록은 Azure provider TTL이나 삭제 예약을 변경한 결과가 아니다.

비용은 [승인 전 준비의 저장된 비용 모델](https://github.com/imcherry5778-labs/github-capacity-cascade-platform/blob/f4ffab693830ab1e29af27e86029a39fda35a6d7/docs/evidence/p9-resume-preparation-20261102/cost.json)을 재사용한 **추정**이다. Two-RG 최대 full-day KRW30,388.0207611084 × 3 = **KRW91,164.06**, 기존 planning 1,200KRW/USD로 약 **세전 USD75.97**의 추가 보존분이다. 실제 환율·청구액이 아니며 Foundation/Bootstrap 추가분·미반영 사용량·세금은 별도다. 다음 campaign variable USD5를 제외한 기존 누적 모델 USD149.4323에 이 부분만 더해도 약 **USD225.40**이므로 종전 USD180 review envelope 안이라고 가정하지 않는다. 현재 잔액·새 실행 비용상한은 미확인/미승인이고, 다음 유료 실행 승인은 연장 비용을 포함해 별도로 판단한다.

문서의 보존기한과 실제 실행 gate를 구분한다. [P9 PR #41](https://github.com/imcherry5778-labs/github-capacity-cascade-platform/pull/41)의 다음 실행 전에는 `scripts/azure-cascade.py`와 `scripts/azure-mitigation.py`의 hard deadline을 위 Environment 기한과 맞추고 직전/정각/직후 및 initialization/run/drain/rollback reserve 경계를 검증해야 한다. 기간 변경만으로 exact-source 승인·횟수·비용·독립 review gate를 우회하지 않는다. 이 문서 PR 자체는 실행 source를 변경하거나 P9 acceptance를 완료하지 않는다.

P8–P10은 실제 Azure controlled experiment 단계다. 각 milestone 시작 시 existing environment를 이어 쓸지 P5 source에서 재생성할지 위 공통 gate에서 결정한다.

P11의 cost-free regression은 Azure 없이 실행 가능해야 한다. Final Azure evidence 또는 teardown/finalization action이 필요할 때만 위 공통 paid gate를 적용한다.

Exact scenario matrix, threshold, repetition count와 redesign topology는 이전 milestone evidence를 본 뒤 해당 milestone 진입 시 확정한다.

P0의 예시 숫자나 legacy Lab threshold를 자동 복원하지 않는다.

## 8. Evidence / PR contract

한 PR은 가능한 한 하나의 engineering capability를 다룬다.

Final/reviewed evidence에는 필요한 범위에서 다음을 남긴다.

- exact source commit
- actual runtime/version/digest provenance
- scenario/environment config
- developer measurement
- mechanism measurement
- confounder guard
- cleanup/finalization result
- limitation

금지:

- empty future module/directory
- unrelated refactor
- 다음 work unit technology의 선제 도입
- 결과에 맞춘 acceptance 사후 완화
- portfolio/presentation/personal-learning artifact를 engineering evidence로 혼합
