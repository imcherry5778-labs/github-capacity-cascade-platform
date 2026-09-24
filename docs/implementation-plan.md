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
≈ 1 fresh Local AI Agent session
≈ 가능하면 1 PR
```

Milestone이 충분히 작으면 milestone 하나가 work unit 하나일 수 있다.

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

Fresh Local AI Agent session prompt는 `AGENTS.md` standing rule을 반복하지 않고 이번 work unit의 delta만 담는다.

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

### P6 / P7 — Paid Azure

P6/P7 실행 전:

- exact source commit
- current price/resource/RBAC/quota
- external DNS delegation action
- explicit user approval

이 필요하다.

P6와 P7을 같은 approval/session에서 연속 수행할 수 있으면 environment를 재생성하기 위해 중간 destroy하지 않는다.

같은 승인 범위에서 P7을 바로 진행하지 않으면 same-day destroy가 기본이고, 24시간 초과 유지에는 새 explicit approval이 필요하다.

### P8–P11 — Investigation / mitigation / redesign / finalization

P8–P10은 실제 Azure controlled experiment 단계다. 각 milestone 시작 시 current environment가 유지 중인지, P5 source에서 재생성이 필요한지, current cost/quota/RBAC와 approval 범위를 다시 확인한다. 이전 approval을 다음 날/다음 paid campaign에 자동 승계하지 않는다.

P11의 cost-free regression은 Azure 없이 실행 가능해야 한다. Final Azure evidence/finalization이 필요할 때만 별도 current preflight와 explicit approval을 사용한다.

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
