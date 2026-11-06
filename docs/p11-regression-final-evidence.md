# P11 — Regression & Final Evidence

상태: **P11-W1 cost-free regression + teardown read-only preflight 완료 / W2(Azure finalization) 미승인·미실행 / P11 acceptance 미완료**.

W1은 Azure·DNS·GitHub setting mutation, Terraform plan/apply/destroy, 유료 실행, credential·RBAC 확대, 데이터 삭제·백업을 하지 않았다.
기준 source는 clean synced `main` `3e732bb8330d450f1a479dd14bfd688da1e6a3b4`이며 tree `46d618b8…`는 [PR #59](https://github.com/imcherry5778-labs/github-capacity-cascade-platform/pull/59) exact HEAD `8715c0eb`의 tree와 같다.
Live 관측 시각은 2026-11-06 08:20–08:40Z(17:20–17:40 KST)다. Subscription/tenant ID, IP, credential, private path는 기록하지 않는다.

근거 출처는 **CONTRACT / SOURCE / CI / MEASURED / INFERENCE / UNKNOWN**으로 구분한다. 검증 수준은 [conventions](conventions.md#10-evidence-wording)의 evidence dimension과 별개다.

## 1. Engineering claim → provenance

각 claim은 merged PR과 exact source, 그리고 CI 또는 live evidence로 추적된다. 이전 counter·negative·consumed 기록은 그대로 둔다.

| Milestone | Claim | Source (merged) | Evidence authority |
| --- | --- | --- | --- |
| P0 | spec/ownership/safety contract | #1 `82a3080`, #3–#5 | CONTRACT 문서 |
| P1–P2 | Local Forgejo E2E, Argo CD Core self-heal | #2 `07f54c7`, #7 `da2ff81` | CI `make local` (아래 §2) |
| P3 | structured operation/attempt, coordinated backup·fresh restore, upgrade/state-aware rollback | #9, #10, #13 `cead2a9` | CI artifact `local-operation-results` / `local-recovery-results` / `local-upgrade-results` |
| P4 | healthy shared gate, active-request saturation, bounded retry, same-cluster removal | #14, #15 `ad49023` | CI artifact `local-shared-gate-results` |
| P5 | Terraform bootstrap/foundation/environment, platform source | #16–#18, #21 | CI static/Terraform validate. Runtime은 P6가 authority |
| P6 | Azure platform calibration | #25–#38 | MEASURED: `azure-execution` dispatch, 마지막 성공 run [40614665503](https://github.com/imcherry5778-labs/github-capacity-cascade-platform/actions/runs/40614665503)(`environment:apply`, `00b603f`) |
| P7 | Azure observability, SLI baseline, restore, initial SLO | #39 `a3bf43f` | [evidence/p7-operations-20261028](evidence/p7-operations-20261028/) |
| P8 | controlled cascade incident | #40 `3f788a9` | [evidence/p8-controlled-cascade-20261029](evidence/p8-controlled-cascade-20261029/README.md), [incident](incidents/p8-controlled-cascade.md) |
| P9 | C0–C3 mitigation 비교, recovery | #41, #48, #49 `c6697a1` | [Campaign32](evidence/p9-mitigation-thirty-second-20261105/README.md) (제22–31차 invalid/negative 보존) |
| P10 | Critical/Bulk isolation (one Azure pair) | #52–#55, #57–#59 `3e732bb` | Sanitized [campaign record](https://github.com/imcherry5778-labs/github-capacity-cascade-platform/pull/59#issuecomment-6679609883), [independent acceptance](https://github.com/imcherry5778-labs/github-capacity-cascade-platform/pull/59#issuecomment-6679708980). `p10nov06` consumed/observation-insufficient 보존 |

Scope limitation은 각 milestone 문서 그대로다. P10은 one pair이며 statistical proof나 actor/role protection이 아니다. P7 tracing은 not verified이며, PostgreSQL `PGSSLMODE=require` limitation도 유지된다.

Evidence 보존 관련 관측:

- **P10 Azure raw는 repository 밖에만 있다.** `p10nov06`, `p10nov06b`는 operator Mac의 `/private/tmp` 아래 0700 private store다(MEASURED). macOS `/tmp`는 재부팅 시 지워질 수 있다. PR #59에는 sha256 prefix만 남아 있어, raw가 사라지면 acceptance 재검증이 불가능해진다. P8/P9 raw는 repository `raw-evidence.tar.gz`와 primary checkout의 ignored `.tmp/`에 있다.
- **P1–P4 Local runtime artifact는 GitHub retention을 따른다.** Current tree의 run [42165987399](https://github.com/imcherry5778-labs/github-capacity-cascade-platform/actions/runs/42165987399) artifact는 2026-11-20T05:24–05:45Z에 만료된다. Digest는 다음과 같다.
  - operation `70573529…`
  - shared-gate `c1d3348e…`
  - recovery `8ff696c8…`
  - upgrade `daa5cac4…`

  같은 gate는 모든 PR CI에서 cost-free로 재생성되므로 regression 재현성은 유지된다.

## 2. Cost-free regression

같은 failure class의 재도입을 잡는 gate는 `local-platform` CI다. 구성은 `make static`, `make local`, recovery, upgrade, ownership/cleanup guard다. 이번 W1에서는 PASS한 controlled experiment를 다시 실행하지 않았다.

- **CI (reuse):** run [42165987399](https://github.com/imcherry5778-labs/github-capacity-cascade-platform/actions/runs/42165987399)의 모든 step이 success다. 이 run은 PR #59 exact HEAD에서 실행됐고 tree가 current `main`과 같다. 포함된 step:
  - static/render/Terraform validation
  - P10 HAProxy classifier
  - fresh lifecycle + owned cleanup
  - healthy gate·removal
  - frozen saturation/bounded retry
  - P10 two-pool paired result·restoration
  - backup/restore
  - upgrade/rollback
  - ownership·cleanup-error guard

  `main` push의 CodeQL [42173661739](https://github.com/imcherry5778-labs/github-capacity-cascade-platform/actions/runs/42173661739)도 success다.
- **Focused local (Mac, Python 3.15):** offline suite 15개를 실행했다.
  - 13개 PASS: operation-results, azure-operations(GNU `stat` shim), azure-cascade, critical-bulk-isolation, local-isolation-pair, azure-isolation, azure-mitigation(skip 3), recovery, upgrade, shared-gate, saturation, ci-change-impact, azure-execution
  - 2개는 Mac host 도구 부재로 실행되지 않았다: `local-bootstrap-diagnostics`(`flock`), `bootstrap-state-protection`(`gpg`). Source regression이 아니며 위 CI에서 PASS했다.
- **Regression gate flake (CI, 교정):** 이 PR 첫 HEAD `0f1378a`(docs-only)의 Local run [42189313574](https://github.com/imcherry5778-labs/github-capacity-cascade-platform/actions/runs/42189313574)이 P10 Local pair의 shared arm에서 `HAProxy frontend vs ring`으로 실패했다(owned restore `restored=true`).
  - 원인: `local-isolation-pair.py` snapshot이 ring과 frontend stats를 별도 `kubectl exec`로 읽는다. Kubelet probe `400/CR` 1건이 before ring read와 stats read 사이에 기록돼 window ring이 counter delta보다 1 row 많았다(`req_tot` 771 vs ring 772, `hrsp_4xx` 12 vs 13). `main`에 잠재한 측정 race이며 docs diff와 무관하다.
  - 교정: counter 앞뒤 ring이 같을 때만 snapshot을 채택한다(최대 3회, 아니면 fail closed). Validator 조건은 바꾸지 않았다.
  - 같은 패턴은 `azure-isolation.py` snapshot에도 있다. W2에는 Azure campaign이 없으므로 수정하지 않고 limitation으로 남긴다.
- **IaC 동결:** `00b603f..3e732bb` 사이 `infra/terraform`, `scripts/azure-execution.py`, `.github/workflows/azure-execution.yml` diff가 없다. Destroy가 쓸 Terraform source·gate는 마지막 성공 dispatch와 같다.

## 3. W2 teardown preflight (read-only)

### Inventory (MEASURED, 2026-11-06 ~08:25Z)

| Scope | 수 | 내용 |
| --- | --- | --- |
| `rg-ccp-environment-krc-p6` | 23 | Terraform 소유 top-level 20 + PE NIC 1 + App Insights 자동 생성 `Application Insights Smart Detection` action group·`Failure Anomalies` alert rule 2 |
| `rg-ccp-foundation-krc-p6` | 2 | `imcherry5778.xyz` public zone, Key Vault |
| `rg-ccp-bootstrap-krc-p6` | 2 | CI UAMI, state Storage Account(`tfstate` container) |
| `MC_…` (AKS node RG) | 7 | VMSS(2× D4s_v4), LB, outbound/ingress public IP, KV CSI identity, NSG, PVC disk 1(`forgejo/forgejo-data`, Attached) |
| `MA_amw-ccp-krc-p6_…` | 2 | AMW managed DCE/DCR |
| `NetworkWatcherRG` | 2 | `koreacentral`, `eastus` watcher. `eastus`는 project 생성 근거가 없어 범위 밖 |

추가로 확인한 상태:

- AKS: `Succeeded/Running`, 1.36.4, `asm-1-30`, KEDA on, 2 fixed node, local account disabled, Azure RBAC
- PostgreSQL 17: Ready, PITR 7일, geo/HA off
- Key Vault: soft-delete 7일, purge protection off, deleted vault 없음
- Resource lock 없음, snapshot 없음, custom role definition 없음, budget 없음
- Activity log: P10 cleanup 이후(07:30Z~) write operation 없음

### RBAC (MEASURED)

- User `Owner` 2 at subscription(baseline)
- Bootstrap CI identity 5: state container `Storage Blob Data Contributor`, foundation/environment RG 각각 `Contributor` + `Role Based Access Control Administrator`
- Environment Terraform 6: AcrPull, subnet Network Contributor, kubelet MI Operator, KV Secrets User, zone DNS Zone Contributor, AMW Monitoring Data Reader
- AKS-managed `Contributor` 1 on MC RG

P10 임시 role/assignment 잔존은 없다.

### Terraform state / ownership

- **Foundation/Environment:** remote state(`tfstate` container)다. Shared Key off, public blob off, blob soft-delete·versioning off(MEASURED). Operator user는 blob data-plane 권한이 없어 직접 조회하지 못한다. 이는 PR #30 이후 알려진 경계이며 권한을 확대하지 않았다. 접근 경로는 CI OIDC(`azure` Environment, `main`만)뿐이다.
  - 마지막 성공 dispatch의 environment state는 32 address다.
  - Repository variable `P6_CAMPAIGN_APPROVAL`과 secret `P6_EXECUTION_CONFIG_B64`가 존재한다(값 미조회).
  - Approval gate는 다음을 모두 요구한다: approved `source_sha`=dispatch SHA=current `main`, merged PR, ≤10h·같은 KST 날짜 window, budget ≤ USD 50, config digest, operation별 predecessor evidence.
- **Bootstrap:** Fedora primary checkout의 local state다(사용자 보고: 0600, serial 13, instance 12). W1 Mac에서 Fedora SSH는 publickey 거부로 **독립 확인하지 못했다(UNKNOWN)**. 복사·재생성·reset은 하지 않았다. Fedora의 Terraform 1.16.7 존재도 UNKNOWN이다.

### DNS (MEASURED)

- Registrar Gabia, registry expiry 2027-04-21, DNSSEC unsigned
- `.xyz` TLD는 Azure NS 4개(`ns{1..4}-08.azure-dns.*`)로 delegate하며 TTL은 3600이다. 1.1.1.1과 8.8.8.8도 같은 응답이다.
- Azure zone record set은 apex NS/SOA와 `forgejo` A(→ AKS external ingress IP) 3개뿐이다. MX/TXT/CAA는 없다.
- 대체 DNS로 Cloudflare `roxy`/`tom`이 양쪽 다 `aa` authoritative SOA/NS로 응답한다. Apex A/AAAA/MX/TXT/CAA와 `forgejo`·`_dmarc` record는 없다. Mail 의존성은 관측되지 않았다.
- **UNKNOWN:** Cloudflare 계정상 zone 상태(active/pending/moved)와 관리 권한, Gabia NS 변경 권한·처리 시간. Gabia FAQ는 안정화에 1–2일이 걸릴 수 있다고 안내한다.

### Data preservation

- **Azure 쪽 보존 필요 데이터: 없음(INFERENCE).** Forgejo PVC·PostgreSQL에는 fixture data만 있고, claim은 repository evidence와 PR record로 추적된다. KV secret은 environment 전용이다. AMW/LAW 데이터는 필요한 query 결과가 이미 evidence에 있다.
- 추가 backup·export는 권장하지 않는다. Destroy하면 PVC disk(MC RG), PG PITR, ACR image가 함께 사라진다.
- **보존 필요: P10 Azure raw.** Repository 밖의 Mac `/private/tmp` private store다. Teardown 뒤에는 재생성할 수 없다. W2 전에 durable private 위치(예: primary checkout ignored `.tmp/`)로 옮길지 결정이 필요하다. 이것은 local 작업이며 W1에서는 수행하지 않았다.

### Cost (MEASURED, 실제 청구서 아님)

- Cost Management ActualCost 2026-10-01~11-06 합계 약 ₩301,450이다.
  - MC RG ₩175,444, environment ₩125,711, foundation ₩295, bootstrap ₩0.1
- 11-01~11-05 standing cost는 **약 ₩29,900/day**다. 보존 하루마다 이만큼이 추가된다.
- Budget·alert는 없다. 이 값은 billing 확정액이 아니다.

### Destroy 순서와 예상 residual

순서는 contract([p5-preflight](p5-preflight.md#deployment--teardown--decided-order-runtime-not-verified), [p6 §cleanup](p6-execution-preparation.md))를 따른다. 아래 1–5단계는 모두 W2 승인 대상이다.

1. **Platform/DNS record:** Argo autosync 정지. Writer가 정지된 뒤 Azure zone의 `forgejo` A record를 exact하게 삭제한다. AKS 삭제로 ingress IP가 해제된 뒤 남는 dangling A record를 막기 위해서다. 별도 PVC backup은 하지 않는다.
2. **`environment:destroy`:** `azure-execution` dispatch로 fresh `plan -destroy` → apply한다. AKS 삭제와 함께 MC RG(PVC disk 포함)가, AMW 삭제와 함께 `MA_` RG가 사라질 것으로 예상한다(INFERENCE, 사후 실측).
3. **Environment RG residual:** Smart Detection action group과 alert rule은 Terraform state 밖이라 남을 것으로 예상한다(INFERENCE). Bootstrap provider는 기본 `features {}`(`prevent_deletion_if_contains_resources=true`)라 이 residual이 있으면 bootstrap RG 삭제가 실패한다(fail-safe). Exact-ID 삭제 승인이 필요하다.
4. **DNS gate:** 사용자가 Gabia NS를 Cloudflare `roxy`/`tom`으로 복구한다. 그 뒤 TLD delegation, 각 Cloudflare NS의 authoritative 응답, recursive resolver 응답을 TTL 대기 후 확인한다. 미완료나 불일치가 있으면 foundation을 삭제하지 않고 cleanup incomplete로 보고한다.
5. **`foundation:destroy`:** DNS gate 확인 뒤 실행한다. KV는 soft-delete 7일이고 purge는 하지 않는다. 이름 예약만 남고 비용은 없다.
6. **Bootstrap destroy:** Fedora에서 같은 operator가 최신 local state로 실행한다. 순서: downstream state가 비었는지 확인 → CI FIC/identity/RBAC, state account, RG 3개 삭제.
7. **Finalization:** subscription 전체 RG/resource, role assignment, deleted KV, DNS delegation, 실제 cost를 대조한다. `NetworkWatcherRG`는 Azure 자동 생성이며 비용이 없는 별도 판단 대상이다.

### Retention

Environment 기한은 **2026-11-08 10:30 KST**, Foundation/Bootstrap 기한은 **2026-11-09 00:33 KST**다. 자동 연장·자동 삭제는 없다.
Gabia 전환이 1–2일 걸리면 Foundation/Bootstrap 기한 안에 DNS gate가 끝나지 않을 수 있다. 그 경우 zone/foundation/bootstrap 보존 연장이 별도로 필요하다. 이 보존은 비용이 작다.

## 4. Gap 분류

**P11 acceptance blocker:**

1. Azure lifecycle 미종료(W2 승인 필요)
2. P10 Azure raw의 휘발성 보관 위치

**Unknown, W2 실행 전에 확인할 것:** Fedora state·도구, Cloudflare zone 상태, Gabia 권한·처리 시간, Smart Detection residual 실제 여부.

**Blocker 아님:** `azure-isolation.py` 동일 snapshot race(재실행 계획 없음), Local CI artifact 만료(gate 재생성 가능), Mac host 도구 부재, `eastus` Network Watcher(범위 밖).

## 5. W2 승인 요청 (사용자 결정)

Go 조건을 만족하는 W2는 다음을 **명시적으로** 승인받아야 한다. W1의 read-only 결과는 승인이 아니다.

1. **Source binding:** 이 PR merge 뒤의 `main` SHA. `P6_CAMPAIGN_APPROVAL` repository variable 갱신(GitHub mutation)도 포함한다. Window ≤10h·같은 KST 날짜, budget ≤ USD 50.
2. **Platform 정지와 Azure DNS `forgejo` A record exact 삭제.**
3. **`environment:destroy` dispatch 1회.** Fresh plan의 destroy 대상이 environment state address(32)와 일치할 때만 apply한다. 실패하면 재시도하지 않고 state/lock/residual을 진단한다.
4. **Environment RG의 Terraform 외 residual exact-ID 삭제.** Smart Detection action group·alert rule이 실제로 남은 경우에 한한다.
5. **Gabia NS → Cloudflare `roxy`/`tom` 복구(사용자 hands-on)와 전파 확인.** 그 뒤 `foundation:destroy` 1회를 실행한다.
6. **Fedora bootstrap destroy(사용자 host).** 필요하면 Foundation/Bootstrap 보존 연장 여부도 함께 결정한다.
7. **사전 local 결정:** P10 Azure raw private evidence의 durable 위치 이동 여부.

권장: 1–4를 Environment 기한 전 같은 window에서 진행한다. 5–6은 DNS 전파 확인에 맞춰 별도 window로 둔다. 보존 하루마다 약 ₩30k가 들므로 environment teardown을 미룰 근거는 없다.
