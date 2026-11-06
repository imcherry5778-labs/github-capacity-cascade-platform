# P11 — Regression & Final Evidence

상태: **P11 Core 완료(승인 범위 한정) — W1 cost-free regression·read-only preflight·destroy guard([PR #60](https://github.com/imcherry5778-labs/github-capacity-cascade-platform/pull/60)) + W2 Azure finalization 실행 완료.** Project 소유 Azure resource는 모두 제거됐지만 Environment Terraform destroy run은 **FAILED**로 보존하며 PASS로 주장하지 않는다. 최종 결과는 [§6](#6-w2-final-result-2026-11-07-kst)이 authority다. P12는 진행하지 않았다.

§1–§5는 W1 작성 시점(2026-11-06, source `3e732bb`)의 기록이다. 특히 §3–§5의 inventory·blocker·승인 요청은 **historical W1 snapshot**이며 current live 상태가 아니다. 그 안의 "이 PR"은 PR #60을 뜻한다.

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

- **P10 Azure raw는 repository 밖에 있다.** Campaign provenance의 private store 두 개(`p10nov06` 80 files, `p10nov06b` 59 files)는 원래 operator Mac의 휘발성 temp directory에만 있었다. P8/P9 raw는 repository `raw-evidence.tar.gz`와 primary checkout의 ignored `.tmp/`에 있다.
  - **Durable private copy (MEASURED, 2026-11-06):** 두 store를 primary Mac checkout의 ignored `.tmp/p11-p10-raw-retained/`에 non-destructive copy했다. Directory는 0700, file은 0600이며 Git tracking은 없다(`git status` clean). Destination이 비어 있는지 확인한 뒤 overwrite 없이 복사했다. 원본은 옮기거나 지우지 않았다.
  - **검증:**
    - PR #59의 sha256 prefix 7개가 일치한다: `ledger.jsonl` `30c4e773…`, `result.json` `6f509057…`, `restoration.json` `0ce30a2c…`, measured-isolated/shared `run.json` `b2789ddd…`/`8af7cd08…`, `preflight-2.json` `23166444…`, `fixture-revocation.json` `1305fe6b…`.
    - `p10nov06` ledger `00a7d3f5…`도 일치하고, `p10nov06b`에 보존된 이전 campaign 80-file manifest 대비 80/80 OK다.
    - Copy 전체 sha256은 원본과 80/80, 59/59 일치한다.
    - Copy 전후 원본 content와 mode/mtime은 불변이다.
  - Copy 옆에 0600 manifest를 두었다(`p10nov06.sha256` `be3c21a7…`, `p10nov06b.sha256` `c2a24439…`). Raw는 공개하지 않는다. 이것은 evidence retention이며 Azure data backup이 아니다.
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
- **IaC 동결:** `00b603f..3e732bb` 사이 `infra/terraform`, `scripts/azure-execution.py`, `.github/workflows/azure-execution.yml` diff가 없다. Terraform source는 마지막 성공 dispatch와 같다. `scripts/azure-execution.py`는 이 PR에서 destroy guard만 추가한다(§3 Terraform state).

## 3. W2 teardown preflight (read-only)

> Historical W1 snapshot(2026-11-06 ~08:20–08:40Z). 아래 resource·RBAC·DNS·state 수치는 teardown 전 상태이며 current live 상태가 아니다. 최종 결과는 §6.

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
  - 마지막 성공 dispatch의 state address는 environment **34**, foundation **2**다(MEASURED: run 40614665503 `environment:apply` 34 planned/34 state, run 40426082431 `foundation:plan` 2). Source에 선언된 resource 수(environment 34, foundation 2)와 같다.
    - 정정: 이 PR 초안은 log를 잘라 읽어 environment를 32로 잘못 적었다.
  - **Destroy guard (SOURCE, 이 PR):** 기존 destroy는 source allowlist와 action vocabulary만 검사했고, 빈 plan·부분 plan·no-op도 apply할 수 있었다. 이제 `scripts/azure-execution.py`가 다음을 강제한다.
    1. Destroy approval에 `destroy_expected_state_counts`(예: `{"environment": 34, "foundation": 2}`)가 있어야 한다. 양의 정수이며 key는 `foundation`/`environment`만 허용하고, 대상 stack이 포함돼야 한다.
    2. Saved plan 직후, apply 전에 fresh `terraform state list`를 실행한다. 그 결과는 중복이 없고, source address 안에 있으며, 승인 count와 정확히 같아야 한다.
    3. Plan은 applyable·complete·non-errored여야 한다. 변경은 모두 `managed`이고 address 집합이 live state와 정확히 같아야 하며(누락·추가·중복 없음), action은 모두 `["delete"]`여야 한다.
    4. 불일치하면 fixed code(`STATE_INVENTORY`/`DESTROY_SET`/`DESTROY_ACTION`/`PLAN_STATUS`/`RESOURCE_CHANGES`)만 출력하고 apply하지 않는다. State address나 provider payload는 출력하지 않는다.
    - Plan/apply/rotation 경로는 바꾸지 않았다. Cost-free mock test로만 검증했으며, 실제 remote state 대상 동작은 W2 dispatch 전까지 **not verified**다.
  - Repository variable `P6_CAMPAIGN_APPROVAL`과 secret `P6_EXECUTION_CONFIG_B64`가 존재한다(값 미조회).
  - Approval gate는 다음을 모두 요구한다: approved `source_sha`=dispatch SHA=current `main`, merged PR, ≤10h·같은 KST 날짜 window, budget ≤ USD 50, config digest, operation별 predecessor evidence.
- **Bootstrap:** Fedora primary checkout의 local state다. W1 Mac에서는 Fedora SSH가 publickey 거부로 막혀, 아래는 orchestrator의 독립 read-only 관측이다.
  - `terraform.tfstate`: 0600, 27,725 bytes, serial 13, resource instance 12, state `terraform_version` 1.16.6. Primary checkout은 clean `main`이다.
  - Fedora system `terraform`은 v1.17.0이고, cached `.tmp/bin/terraform`은 v1.16.6이다. Current `bootstrap/versions.tf`는 정확히 `= 1.16.7`을 요구한다.
  - **W2 bootstrap destroy 전에 1.16.7 binary가 준비돼야 한다(blocker).** W1에서는 state 조작·도구 설치·복사·재생성·reset을 하지 않았다.

### DNS (MEASURED)

- Registrar Gabia, registry expiry 2027-04-21, DNSSEC unsigned
- `.xyz` TLD는 Azure NS 4개(`ns{1..4}-08.azure-dns.*`)로 delegate하며 TTL은 3600이다. 1.1.1.1과 8.8.8.8도 같은 응답이다.
- Azure zone record set은 apex NS/SOA와 `forgejo` A(→ AKS external ingress IP) 3개뿐이다. MX/TXT/CAA는 없다.
- 대체 DNS로 Cloudflare `roxy`/`tom`이 양쪽 다 `aa` authoritative SOA/NS로 응답한다. Apex A/AAAA/MX/TXT/CAA와 `forgejo`·`_dmarc` record는 없다. Mail 의존성은 관측되지 않았다.
- **Cloudflare zone 상태 (orchestrator 독립 read-only API):** `imcherry5778.xyz`는 status **`moved`**(active 아님), type `full`, assigned NS `roxy`/`tom`, DNS record 0이다. 따라서 Gabia delegation을 Cloudflare로 되돌린 뒤 zone이 **`active`로 돌아오는 것**을 확인해야 한다. 그 뒤 authoritative·recursive 확인까지 끝나야 Azure zone/Foundation/Bootstrap을 삭제할 수 있다.
- **UNKNOWN:** Gabia NS 변경 권한·처리 시간. Gabia FAQ는 안정화에 1–2일이 걸릴 수 있다고 안내한다.

### Data preservation

- **Azure 쪽 보존 필요 데이터: 없음(INFERENCE).** Forgejo PVC·PostgreSQL에는 fixture data만 있고, claim은 repository evidence와 PR record로 추적된다. KV secret은 environment 전용이다. AMW/LAW 데이터는 필요한 query 결과가 이미 evidence에 있다.
- 추가 backup·export는 권장하지 않는다. Destroy하면 PVC disk(MC RG), PG PITR, ACR image가 함께 사라진다.
- **보존 필요였던 P10 Azure raw:** Teardown 뒤에는 재생성할 수 없어 durable private copy를 만들고 검증했다(§1). 남은 보존 작업은 없다.

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
4. **DNS gate (W2 승인 직후 먼저 시작):** 사용자가 Gabia NS를 Cloudflare `roxy`/`tom`으로 복구한다. 전환 중에도 Azure NS와 zone은 유지한다(Cloudflare zone이 비어 있으므로 cache가 섞여 있는 동안 `forgejo`만 다르게 해석된다). 그 뒤 다음을 TTL 대기 후 확인한다.
   - Cloudflare zone이 `moved` → `active`
   - TLD delegation
   - 각 Cloudflare NS의 authoritative 응답
   - 독립 recursive resolver 응답

   미완료나 불일치가 있으면 Azure zone·foundation·bootstrap을 삭제하지 않고 cleanup incomplete로 보고한다.
5. **`foundation:destroy`:** DNS gate 확인 뒤 실행한다. KV는 soft-delete 7일이고 purge는 하지 않는다. 이름 예약만 남고 비용은 없다.
6. **Bootstrap destroy:** Fedora에서 같은 operator가 최신 local state로 실행한다. 순서: downstream state가 비었는지 확인 → CI FIC/identity/RBAC, state account, RG 3개 삭제.
7. **Finalization:** subscription 전체 RG/resource, role assignment, deleted KV, DNS delegation, 실제 cost를 대조한다. `NetworkWatcherRG`는 Azure 자동 생성이며 비용이 없는 별도 판단 대상이다.

### Retention

Environment 기한은 **2026-11-08 10:30 KST**, Foundation/Bootstrap 기한은 **2026-11-09 00:33 KST**다. 자동 연장·자동 삭제는 없다.
Gabia 전환이 1–2일 걸리면 Foundation/Bootstrap 기한 안에 DNS gate가 끝나지 않을 수 있다. 그래서 DNS 전환을 W2 승인 직후 environment destroy보다 먼저(또는 병행해) 시작한다. 그래도 기한을 넘기면 zone/foundation/bootstrap 보존 연장이 별도로 필요하다. 이 보존은 비용이 작다. 자동 연장은 없다.

## 4. Gap 분류

> Historical W1 snapshot. 아래 blocker는 W2에서 해소됐다(§6). 1.16.7 binary는 Fedora에서 pinned·checksum 검증 후 사용했고, Cloudflare zone은 `active`로 복귀했다.

**P11 acceptance blocker:**

1. Azure lifecycle 미종료(W2 승인 필요)
2. Fedora에 bootstrap이 요구하는 Terraform 1.16.7 binary가 없음(W2 bootstrap destroy 전 준비)
3. Cloudflare zone `moved` → `active` 복귀가 Azure zone/Foundation/Bootstrap 삭제의 선행 조건

해소됨: P10 Azure raw의 휘발성 보관(durable verified copy, §1), destroy plan 전체 집합 guard 부재(이 PR source, CI 대기).

**Unknown, W2 실행 전에 확인할 것:** Gabia 권한·처리 시간, Smart Detection residual 실제 여부, destroy guard의 실제 remote state 동작.

**Blocker 아님:** `azure-isolation.py` 동일 snapshot race(재실행 계획 없음), Local CI artifact 만료(gate 재생성 가능), Mac host 도구 부재, `eastus` Network Watcher(범위 밖).

## 5. W2 승인 요청 (사용자 결정)

> Historical W1 snapshot. 실제 승인·실행과 그 결과는 PR #60 comment와 §6에 있다.

Go 조건을 만족하는 W2는 다음을 **명시적으로** 승인받아야 한다. W1의 read-only 결과는 승인이 아니다.

1. **Gabia NS → Cloudflare `roxy`/`tom` 복구(사용자 hands-on), 승인 직후 가장 먼저.** Azure NS·zone은 유지한 채 Cloudflare `active` 복귀와 authoritative/recursive 전파를 관측한다.
2. **Source binding:** 이 PR merge 뒤의 `main` SHA. `P6_CAMPAIGN_APPROVAL` repository variable 갱신(GitHub mutation)도 포함한다. Window ≤10h·같은 KST 날짜, budget ≤ USD 50.
   - Destroy마다 **`destroy_expected_state_counts`**를 승인 값으로 명시한다. 현재 관측은 `environment` 34, `foundation` 2이며, dispatch 직전 근거로 다시 확정한다.
3. **Platform 정지와 Azure DNS `forgejo` A record exact 삭제.**
4. **`environment:destroy` dispatch 1회.** Source guard가 다음을 확인할 때만 apply한다: fresh state list = 승인 count(34), saved plan = 그 전체 집합의 `delete`. 실패하면 재시도하지 않고 state/lock/residual을 진단한다.
5. **Environment RG의 Terraform 외 residual exact-ID 삭제.** Smart Detection action group·alert rule이 실제로 남은 경우에 한한다.
6. **`foundation:destroy` dispatch 1회.** 1번 DNS gate(Cloudflare `active` 포함)가 확인된 뒤, 승인 count 2로 실행한다.
7. **Fedora bootstrap destroy(사용자 host).** Terraform **1.16.7** binary를 먼저 준비하고, 최신 local state(serial 13 기준 재확인)로 실행한다. DNS gate가 Foundation/Bootstrap 기한(2026-11-09 00:33 KST) 안에 끝나지 않으면 보존 연장 여부도 함께 결정한다.

권장 순서: 승인 직후 1을 시작한다. 같은 window에서 2–5를 Environment 기한(2026-11-08 10:30 KST) 전에 끝낸다. 6–7은 DNS 확인 뒤에 한다. 보존 하루마다 약 ₩30k가 들므로 environment teardown을 미룰 근거는 없다.

## 6. W2 final result (2026-11-07 KST)

Final operational source는 merged `main` `0c78d0d82dd8c84a17382e4d3806a54a489025ab`(PR #60)다. 상세 실측과 판정 authority는 PR #60 comment다. 여기서는 결과만 요약하고 log를 반복하지 않는다.

- [Final independent gate](https://github.com/imcherry5778-labs/github-capacity-cascade-platform/pull/60#issuecomment-6691695074)
- [Stale state backend exception](https://github.com/imcherry5778-labs/github-capacity-cascade-platform/pull/60#issuecomment-6691507680)
- [Foundation destroy result](https://github.com/imcherry5778-labs/github-capacity-cascade-platform/pull/60#issuecomment-6691483700)
- [Environment destroy failure + residual cleanup](https://github.com/imcherry5778-labs/github-capacity-cascade-platform/pull/60#issuecomment-6690610889)

| 단계 | 결과 (MEASURED) |
| --- | --- |
| DNS | Azure zone `forgejo` A exact 삭제. Gabia delegation을 Cloudflare `roxy`/`tom`으로 복구했고 Cloudflare zone은 **ACTIVE**다. Public resolver에 `forgejo` A가 없다. |
| `environment:destroy` | Run [42253781737](https://github.com/imcherry5778-labs/github-capacity-cascade-platform/actions/runs/42253781737) **FAILED**. 소비됐고 재시도하지 않았다. 33/34 삭제, remote state에 `azurerm_monitor_workspace.this` 1개가 남았다. AMW는 사용자가 별도로 요청한 exact-ID ARM DELETE로 나중에 제거했고, Smart Detection residual 2개도 exact-ID로 삭제했다. **PASS가 아니다.** |
| `foundation:destroy` | Run [42264345423](https://github.com/imcherry5778-labs/github-capacity-cascade-platform/actions/runs/42264345423) **SUCCESS**. Guard가 fresh state 2 = 승인 count를 확인했고 exact 2 delete(`azurerm_dns_zone.project`, `azurerm_key_vault.project`), 최종 state 0. |
| Bootstrap | Fedora original checkout·original local state로 pinned Terraform 1.16.7을 사용했다. Saved plan은 exact 12 delete였고 apply 1회 SUCCESS. 최종 local state 0 instance, serial 26, mode 0600. Project RG 3개 모두 absent. |
| Approval | `P6_CAMPAIGN_APPROVAL`은 disabled, `allowed_operations=[]`. |

Stale Environment state의 처분:

- 실패 run이 remote state에 남긴 `azurerm_monitor_workspace.this`는 ARM·RP·Resource Graph에서 absent로 확인된 resource의 stale pointer였다.
- 이 state는 **documented exception**으로, 승인된 Bootstrap teardown이 owned state storage account를 삭제하면서 함께 폐기됐다. `terraform state rm`이나 추가 Terraform dispatch는 쓰지 않았다.
- 따라서 Environment Terraform state가 Terraform으로 비워졌다거나 Environment destroy가 PASS했다고 주장하지 않는다.

Final inventory와 boundary:

- Subscription에는 범위 밖 `NetworkWatcherRG`(Azure 자동 생성 resource 2)만 남았다. 수정하지 않았다.
- Role assignment는 baseline `Owner` 2뿐이다. Bootstrap CI identity·FIC·RBAC와 state backend는 제거됐다.
- Key Vault는 soft-deleted 상태이며 scheduled purge는 2026-11-13이다. 조기 purge는 하지 않았다.
- P10 private raw(80 + 59 files)는 primary checkout의 ignored `.tmp/`에 보존돼 있다(§1). 공개하지 않는다.
- 최종 Cost Management invoice는 **UNKNOWN**이다. §3의 누적 ActualCost는 당시 Cost Management 조회치이고 하루 유지비는 추정치다. 최종 청구 확정액은 아니다.
- 기존 limitation은 그대로다. P7 tracing은 not verified, P10은 one controlled pair이며 statistical proof가 아니다.
- 보존 기한 연장, 추가 유료 실행, P12 진입은 없었다.
