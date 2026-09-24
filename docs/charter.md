# Project Charter

## 1. 목적

GitHub의 2026년 8월 공개 capacity incident에서 확인할 수 있는 overload-driven cascading failure의 failure class를 실제 Forgejo developer platform에 축소 적용해 **user impact → investigation → mitigation → recovery → redesign → regression prevention**을 검증하는 SRE / Platform Engineering case study다.

기존 [`github-capacity-cascade-lab`](https://github.com/imcherry5778-labs/github-capacity-cascade-lab)은 mechanism research foundation이고, 이 저장소는 실제 developer journey와 platform lifecycle을 가진 engineering case study다. Incident source register와 Lab evidence를 새 repository에 복제하지 않고 provenance가 필요한 경우 원본 Lab을 참조한다.

## 2. 핵심 질문

1. Git/PR/Issue developer operation이 정상 상태에서 반복 가능하게 동작하는가?
2. shared mandatory path의 request-processing capacity가 포화되면 developer impact가 어떻게 나타나는가?
3. retry가 같은 상위 demand를 더 많은 attempt/request로 증폭시키는가?
4. application-container CPU 중심 autoscaling이 proxy-side saturation을 놓칠 수 있는가?
5. metrics/logs/traces와 developer-operation result를 연결해 mechanism을 설명할 수 있는가?
6. 같은 workload/fault boundary에서 mitigation trade-off를 비교할 수 있는가?
7. demand를 끄지 않고 recovery할 수 있는가?
8. critical developer traffic과 bulk/automation traffic을 분리하면 blast radius를 줄일 수 있는가?
9. 같은 failure class의 재도입을 regression verification에서 잡을 수 있는가?

## 3. 원칙

### Platform first

Forgejo developer platform이 주인공이다. Reliability fixture는 platform reliability를 조사하기 위한 수단이다.

### Developer operation first

Pod Ready, CPU, HTTP 200만으로 정상 여부를 판단하지 않는다. Clone/fetch, push, Pull Request, Issue 같은 developer operation을 최상위 user signal로 사용한다.

### Stable state와 experiment state 분리

Stable platform과 temporary experiment는 ownership/lifecycle을 분리한다. Experiment는 stable desired state를 직접 mutation하지 않는다.

### Evidence over hypothesis

가설과 반대 결과라도 valid run이면 보존한다. `experiment PASS`, `SLO met`, `hypothesis supported`는 별도 판정이다.

### 필요한 만큼만 복잡하게

현재 problem/acceptance에 필요하지 않은 tool/controller/service, abstraction, module, empty directory를 선제 도입하지 않는다.

### Local-first, Azure-short-lived

Local/static으로 확정 가능한 contract는 Azure 비용 전에 확정한다. Azure paid runtime은 calibration/evidence를 위해 짧게 사용한다.

## 4. Core scope

### Platform

- Forgejo v15 LTS track
- single replica
- external PostgreSQL
- persistent application/repository data
- Azure public HTTPS entry path
- Argo CD Core reconciliation
- Key Vault + Workload Identity + Secrets Store CSI
- Azure managed observability
- GitHub Actions CI/IaC orchestration

### Operations

- developer-operation measurement / SLI / SLO
- observability query/alert/dashboard
- coordinated backup/restore proof
- upgrade/state-aware rollback proof
- cost/cleanup/finalization runbook

### Reliability

- synthetic shared gate
- request-concurrency saturation
- application-CPU scaling signal mismatch comparison
- retry amplification
- overload protection
- saturation-aware scaling comparison
- recovery under continuing demand
- critical/bulk isolation

## 5. Core 밖

기본적으로 다음은 Core 완료 조건이 아니다.

- GitHub internal topology/auth structure의 정확한 복제
- Forgejo HA / multi-region
- Forgejo application-tier Redis/Valkey
- Backstage
- Forgejo Actions runner platform
- Argo CD full UI/HA
- separate GitOps repository
- complex priority/fair queueing
- per-user quota
- always-on public demo
- portfolio website / presentation packaging / personal learning notes
- 추가 messaging platform

실제 필요성이 확인되면 별도 architecture decision으로 재검토한다.

## 6. Environment model

### Local

- disposable Kubernetes environment
- Local-only dependency substitute 허용
- developer correctness와 reliability mechanism을 Azure 전에 검증
- 개발용 HTTP/port-forward 예외 허용
- Azure observability stack 전체를 복제하지 않음

### Azure

- single region
- ephemeral PAYG runtime
- private PostgreSQL
- public exposure는 HTTPS ingress 중심
- same-day destroy 기본
- 24시간 초과 유지에는 새 명시적 승인
- final evidence에 exact source/runtime provenance 기록

## 7. 완료 기준

최소한 다음이 실제 evidence로 확인되어야 한다.

- Local/Azure 핵심 developer journey
- normal test / experiment ownership 분리
- baseline 근거를 가진 developer SLI/SLO
- cascade user impact + mechanism + confounder guard
- 동일 조건 mitigation 비교
- continuing demand 중 recovery
- critical/bulk isolation 전후 비교
- coordinated restore + doctor + developer E2E
- upgrade/state-aware rollback
- Azure finalization과 residual inventory
- 최종 claim이 reviewed evidence로 추적 가능

## 8. 표현 경계

- FACT / INFERENCE / LAB_IMPLEMENTATION / UNKNOWN을 구분한다.
- 공개 source의 서로 다른 incident window를 임의로 하나의 숫자로 합치지 않는다.
- Lab evidence는 Platform runtime proof를 대신하지 않는다.
- 이 프로젝트를 production-ready service라고 과장하지 않는다.
