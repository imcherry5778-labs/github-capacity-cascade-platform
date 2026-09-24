# GitHub Capacity Cascade Platform

> A production-minded SRE / Platform Engineering case study that turns a public GitHub capacity incident into a reproducible developer-platform reliability investigation.

GitHub의 2026년 8월 공개 capacity incident에서 확인할 수 있는 **overload-driven cascading failure**의 failure class를 실제 Forgejo developer platform에 축소 적용해 다음 흐름을 검증한다.

```text
public RCA
→ working developer platform
→ healthy baseline
→ developer impact
→ investigation / RCA
→ mitigation
→ recovery while demand continues
→ critical / bulk isolation
→ regression prevention
→ reviewed evidence
```

현재 단계는 **P1 — Local Forgejo correctness**다. P0에서 고정한 architecture·ownership·dependency·safety·acceptance contract를 기준으로, GitOps·service mesh·reliability fixture·Azure 없이 local Forgejo developer journey와 Pod/state lifetime 분리를 검증한다.

## Research boundary

기존 [`github-capacity-cascade-lab`](https://github.com/imcherry5778-labs/github-capacity-cascade-lab)은 capacity/retry mechanism을 작은 단위로 분리해 연구한 foundation이다. Incident source register와 mechanism-level evidence는 Lab의 provenance를 그대로 참조하고 이 repository에서 복제하지 않는다. 이 저장소는 Lab의 구현을 복제하지 않고, 그 knowledge를 실제 developer journey를 가진 platform engineering 문제로 확장한다.

GitHub의 비공개 내부 architecture나 설정은 추정하지 않는다.

- **FACT**: primary source가 직접 뒷받침
- **INFERENCE**: 공개 자료 또는 project evidence에 대한 해석
- **LAB_IMPLEMENTATION**: failure effect를 연구하기 위한 프로젝트 구현
- **UNKNOWN**: 공개되지 않아 확인할 수 없음

## Top-level user signal

Core developer journey:

- Git clone/fetch
- Git push
- Pull Request create/read
- Issue create/read

측정 단위는 구분한다.

```text
developer operation
→ operation attempt
→ HTTP request
→ authorization check
→ Envoy upstream request
→ application request
```

## Architecture direction

Project-level decisions:

- Forgejo v15 LTS track, single replica, external PostgreSQL, persistent application data
- Azure AKS runtime
- Argo CD Core for stable-state reconciliation
- AKS managed Istio/KEDA/Key Vault CSI 우선
- Azure Key Vault + Workload Identity
- Terraform `bootstrap / foundation / environment` lifecycle
- GitHub Actions → Azure OIDC federation
- temporary synthetic shared gate for the reliability experiment
- Azure managed observability

Exact patch/revision/SKU/threshold/metric spelling은 해당 milestone에서 현재 upstream/runtime을 다시 확인한 뒤 고정한다.

## Roadmap

```text
P0   Specification & Research Contract
P1   Local Forgejo Correctness
P2   Local GitOps Reconciliation
P3   Local Operations Contract               COST 0
P4   Local Reliability Fixture               COST 0
P5   Azure IaC & Platform Source              COST 0
P6   Azure Platform Calibration               explicit approval / PAYG
P7   Azure Operations Verification            explicit approval / PAYG
P8   Controlled Cascade Investigation         explicit approval / PAYG
P9   Mitigation & Recovery                    explicit approval / PAYG
P10  Critical / Bulk Isolation                explicit approval / PAYG
P11  Regression & Final Evidence              final Azure action requires approval
```

중요한 실행 순서:

```text
local correctness / GitOps / operations / reliability
→ Azure source + paid-run preflight
→ explicit user approval
→ short-lived Azure calibration / operations verification
→ controlled investigation / mitigation / redesign
→ regression / final evidence
```

## Repository responsibility map

아래는 최종 ownership map이다. P0에서 빈 directory를 생성하지 않는다.

```text
cmd/          project-owned executable
internal/     executable internal implementation
infra/        Azure/cloud infrastructure lifecycle
platform/     stable developer platform source
operations/   SLO, alerts, dashboards, runbooks, cost
tests/        normal-system verification
experiments/  temporary reliability fixtures/scenarios/load
results/      reviewed evidence
docs/         project contract, ADR, incident docs
```

`tests/`는 정상 시스템을 검증하고, `experiments/`는 의도한 failure condition을 검증한다.

Portfolio website source, presentation/résumé-facing copy와 personal learning note는 이 engineering repository에 저장하지 않는다. Architecture/ADR/runbook/incident/postmortem/reviewed evidence는 engineering artifact로 유지하며 외부 presentation layer가 필요하면 이를 참조한다.

## Production-minded boundary

이 프로젝트는 production-ready 24/7 service라고 주장하지 않는다. Core는 single region, ephemeral Azure runtime, Forgejo single replica, no Forgejo HA/multi-region, Argo CD Core, small operator model을 의도적으로 허용한다.

Azure는 PAYG다. 실제 Azure `apply` / `destroy` 또는 비용이 발생할 수 있는 action은 사용자의 명시적 승인 없이 실행하지 않는다.

## Local platform (P1)

Docker, `curl`, `jq`, `git`, `shellcheck`가 필요하다. k3d/kubectl/helm은 `versions.env`의 pinned version을 repository-local `.tmp/bin`에 설치해 사용하며, global 환경과 default kubeconfig는 변경하지 않는다.

```bash
make static   # shell lint, versions.env pin 일치, Helm render/config contract
make local    # fresh k3d cluster → PostgreSQL + Forgejo → developer E2E → workload replacement continuity → cleanup
```

단계별 실행은 `make up`, `make verify`, `make down`이다. Local access는 `127.0.0.1:13000` loopback `kubectl port-forward` HTTP이며, Local development exception일 뿐 Azure ingress/TLS contract가 아니다.

## Documents

- `docs/charter.md` — 목적, 연구 질문, 범위, 완료 기준
- `docs/architecture.md` — architecture, ownership, decision maturity
- `docs/roadmap.md` — milestone 흐름과 exit condition
- `docs/implementation-plan.md` — milestone 진입 시 work-unit 분해 정책과 구현 전 gate
- `docs/conventions.md` — 문서/Git/naming/evidence 규칙
- `docs/terminology.md` — claim/measurement 용어
- `AGENTS.md` — ChatGPT / Local AI Agent / GitHub workflow

사람 대상 문서는 한국어를 기본으로 하고 product/API/metric/CLI/code/path는 공식 영어 표기를 유지한다.
