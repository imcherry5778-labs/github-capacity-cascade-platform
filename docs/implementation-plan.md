# Implementation Plan

## 1. 목적

Roadmap을 실제 work-unit dependency와 **구현 전 specification gate**로 바꾼다. P0에서 future file/API 전체를 고정하지 않는다.

## 2. Work units

| Unit | Prerequisite | 결과 | Azure side effect |
| --- | --- | --- | --- |
| P1 | P0 | Local Forgejo correctness | 없음 |
| P2 | P1 | Local GitOps reconciliation | 없음 |
| P3A-01 | P2 | state + GitHub OIDC identity + scoped RG/RBAC source | 없음 |
| P3A-02 | P3A-01 | delegated DNS + Key Vault source | 없음 |
| P3A-03 | P3A-01 | VNet/subnet + private PostgreSQL + storage/registry source | 없음 |
| P3A-04 | P3A-03 | AKS + managed Istio/KEDA/Key Vault CSI source | 없음 |
| P3A-05 | P3A-02,04 | Azure platform/routing/bootstrap/identity source | 없음 |
| P3A-06 | P3A-05 | resource/RBAC/cost/apply-destroy preflight | 없음 |
| P4A-01 | P2 | structured developer measurement | 없음 |
| P4A-02 | P4A-01 | local recovery/restore/upgrade/rollback proof | 없음 |
| P5-01 | P4A-01 | minimal `ext-authz-sim` | 없음 |
| P5-02 | P5-01 | healthy shared gate | 없음 |
| P5-03 | P5-02 | saturation/retry mechanism | 없음 |
| P3B-01 | P3A-06, P5-03 | bootstrap/foundation actual proof | explicit approval |
| P3B-02 | P3B-01 | calibration environment | explicit approval |
| P4B | P3B-02, P4A-02 | Azure operations proof | explicit approval |
| P6 | P4B, P5-03 | cascade investigation | explicit approval |
| P7 | P6 | mitigation/recovery | explicit approval |
| P8 | P7 | critical/bulk isolation | explicit approval |
| P9 | P8 | regression/final evidence/finalization | 일부 explicit approval |

Execution order는 `P3A → P4A → P5 → P3B`다.

## 3. Unit 시작 전 gate

ChatGPT가 각 unit 시작 전에 다음을 확정한다.

- Goal / prerequisite
- Scope / non-goals
- relevant DECIDED architecture
- REVALIDATE result
- DEFERRED value
- acceptance criteria
- required evidence
- cost/external side effect
- cleanup/rollback boundary

구현 결과에 맞춰 acceptance를 사후 완화하지 않는다.

Fresh Local AI Agent에 전달하는 session prompt는 `AGENTS.md`의 standing rule을 반복하지 않고, 이번 unit의 mission/baseline/scope/revalidation/acceptance/safety/deliverable만 담는 lean delta prompt로 작성한다.

## 4. P0에서 exact pin하지 않는 값

- Forgejo exact patch/chart/image digest
- Local Kubernetes/k3s patch
- Argo CD version/commit
- Terraform/AzureRM version
- AKS Kubernetes patch / managed Istio revision
- exact Envoy rejection metric spelling
- KEDA threshold
- Azure node/PostgreSQL SKU
- resource request/limit
- log/trace sampling
- SLO threshold
- GitHub OIDC exact subject

해당 unit 시작 시 current official upstream/runtime을 확인하고 필요하면 source/evidence에 pin한다.

## 5. P3A contract

### P3A-01 Bootstrap

DECIDED boundary:

- state backend
- bootstrap-created foundation/environment Resource Group
- GitHub Actions user-assigned identity/federation
- GitHub Environment `azure` 사용 방향
- state container: `Storage Blob Data Contributor`
- foundation RG: `Contributor` + `Role Based Access Control Administrator`
- environment RG: `Contributor` + `Role Based Access Control Administrator`
- privileged RBAC scope는 project-owned RG 밖으로 넓히지 않음
- subscription-wide Owner/Contributor/User Access Administrator 기본값 금지
- automatic Resource Provider registration을 암묵적 side effect로 사용하지 않음
- actual apply 없음

Exact immutable OIDC subject와 environment deployment protection은 새 repository의 실제 설정으로 REVALIDATE한다.

### P3A-02 Foundation

- project subdomain Azure DNS
- Key Vault
- 실제 필요가 확인된 최소 long-lived shared identity/RBAC

Parent domain 전체를 Azure DNS로 이전하지 않는다.

### P3A-03 Environment network/data

- VNet/subnets
- private PostgreSQL
- storage/registry/private DNS/network

Node/PostgreSQL SKU는 DEFERRED다.

### P3A-04 Managed capabilities

Default: AKS + managed Istio + managed KEDA + managed Key Vault CSI + Workload Identity.

Chosen AKS version/region에서 revision/capability/support boundary를 REVALIDATE한다. Required capability가 막힐 때만 self-managed Istio fallback ADR을 연다.

### P3A-05 Azure platform source

Azure Forgejo source, stable ingress/routing, workload identity/secret integration, explicit cluster bootstrap, Argo stable-state source를 연결한다. Managed controller/experiment lifecycle을 Argo에 넘기지 않는다.

### P3A-06 Preflight

Paid apply 전에 planned resource, RBAC, region/quota, current price, DNS delegation action, destroy/finalization order를 inventory한다.

## 6. P4A contract

### P4A-01 Measurement

Git CLI + Forgejo API/curl path를 재사용한 structured harness를 우선한다.

Minimum result:

- run/scenario id
- operation type/id
- timestamps
- success/failure
- end-to-end duration
- attempt number
- retry/error class

별도 Go developer probe는 shell/Git/API 구조로 실제 requirement를 만족하지 못할 때만 검토한다. Bulk/retry load는 k6 우선.

### P4A-02 Recovery

Local에서 session/PAT continuity as applicable, coordinated backup, fresh restore, `forgejo doctor`, developer E2E, upgrade/state-aware rollback을 검증한다. PITR만으로 Forgejo recovery라고 주장하지 않는다.

## 7. P5 contract

### P5-01 ext-authz-sim

Core custom server-side service는 `ext-authz-sim` 하나로 제한한다. 최소 capability는 Envoy HTTP external authorization response, health/readiness, Prometheus metrics, OTel tracing boundary, deterministic latency/error control, bounded in-flight option과 runtime fault control이다. DB는 추가하지 않고 request-check data path와 admin/metrics surface를 분리한다.

### P5-02 Healthy shared gate

Healthy gate를 추가해도 normal developer E2E가 유지되어야 하며 Forgejo native auth를 우회하지 않는다.

### P5-03 Saturation/retry

Intentional target은 `ext-authz-sim` Pod inbound Envoy의 active-request capacity다.

Selected Istio/Envoy에서 limit behavior, exact rejection stat, stat exposure path, no-retry baseline, bounded retry amplification을 실제 확인한다. Exact counter 이름은 version-independent contract로 간주하지 않는다.

Local KEDA controller는 concrete need가 확인되기 전에는 추가하지 않는다.

## 8. Paid Azure policy

Gate 1/2 실행 전 current pricing/resource/RBAC/quota, exact source commit과 explicit approval이 필요하다.

Calibration은 final evidence가 아니다. Paid environment는 same-day destroy 기본이며 24시간 초과 유지에는 새 승인이 필요하다.

## 9. Evidence / PR unit

Final evidence에는 exact source/runtime provenance, scenario/environment config, developer measurement, mechanism measurement, confounder guard와 cleanup 결과를 남긴다.

한 PR은 가능한 한 하나의 capability다. Empty future module/directory, unrelated refactor, 다음 unit technology의 선제 도입을 금지한다.
