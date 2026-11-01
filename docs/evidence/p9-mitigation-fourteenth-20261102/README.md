# P9 제14차 — healthy·KEDA positive, calibration invalid 및 owned 원복

상태: **단일 campaign 종료 / normal·healthy·KEDA 인증·단일 owner·full C3 preflight positive / calibration1 invalid / freeze·C0–C3 measured·recovery 미도달 / P9-owned cleanup 검증 / P9 acceptance 미충족**.
실행 시각은 2026-11-01 UTC, 한국 시각은 2026-11-02 KST다.

실제 실행 source는 **`69bace6cdb3dabe047a71454528c27111f706c05`**,
main/base는 `3f788a9c1d103f6c07bd403af269133fac287002`다.
[제14차 단일 실행 승인](https://github.com/imcherry5778-labs/github-capacity-cascade-platform/pull/41#issuecomment-6559890287)과
[exact-source 독립 review](https://github.com/imcherry5778-labs/github-capacity-cascade-platform/pull/41#pullrequestreview-5728767267)를 확인했다.
기존 source CI/review와 P6–P8 전체 preflight는 반복하지 않았다.
이 후속 docs/evidence HEAD는 실행 source가 아니다. Source·deadline·acceptance 변경은 없다.

## 실제 진입과 준비

Fetch 뒤 local/remote main과 PR HEAD, 기존 branch/worktree의 clean 상태와 Draft/Open/unmerged를 확인했다.
Local process·ledger/raw·Orca 세션/터미널·미push evidence 및 live namespace/CUSTOM/ACR repository로
중복을 점검했다. 이전 source session은 done, 다른 campaign agent/terminal은 없었다.
Campaign `p9a20261102`, 첫 mutation intent **15:26:26.402337**, finalization **15:44:00.245431**이다.
준비/원복 누적14회이며 새 branch/PR·별도 campaign은 없다.

Actual account/AKS/resource/quota와 최소 live identity·Argo·stable 상태를 확인했다.
승인된 AKS 하나의 임시 role만 생성하고 Entra user auth·mode0600 kubeconfig를 사용했다.
처음60회의 Forbidden 관측 뒤 같은 role의 전파를 선언한600초 경계 안에서 계속 관측했고 접근이 열렸다.
이 대기는 source initialization/collection deadline 연장이 아니다.
Kubectl v1.36.4의 actual path/hash를 확인했다. 기존 normal context template을 재사용하되
source를 새 SHA로 묶고 actual image/Argo/chart/cluster/version/tool에 대한9개 비교를 모두 확인했다.
Stable Secret UID/data와 mounted version은 이전 final 상태와 같았다.

Image source revision label과 published digest, actual Pod image binding을 보존했다.

- Image: **`sha256:40f06fee3d0355645918562ad33a82d772806a3ffe96e9a69751b4d47a0348c5`**
- Preparation plan SHA256: **`ec82078689d9d5df7e15a3315ceefbd6c82bb375a8c8efd1f9bab785a008958e`**
- Actual KEDA identity를 연결한 plan SHA256: **`ca5c920b5287907084bbf19020d140fabd02ca2341cf065fb0f3e46e889b41c4`**
- Reviewed freeze/hash: **없음 / 미도달**

준비 순서는 initial live headroom → namespace/config/service/Sidecar 및 injected4-Pod server-side dry-run
→ guarded shared mesh bootstrap → target/DB Ready·UID/restart0 → **target-stage live headroom**
→ DB TLS/native SQL 및 backend Ready EndpointSlice → HAProxy Ready → HPA/PodMonitor/CUSTOM
→ 최종 admitted resource/headroom → normal이었다.
Dry-run UID placeholder를 live Pod UID로 해석하지 않는다.
Sidecar/init/overhead를 보수적으로 합친4-Pod 최대 예상은 requests650m/832Mi, limits1450m/1664Mi다.

임시 DB client는 **`PGSSLMODE=verify-full`**, actual hostname
`pg-ccp-p6-krc-57781024.postgres.database.azure.com`, CA bundle을 사용했다.
Libpq 검증 성공 및 SQL의 TLSv1.3 / TLS_AES_256_GCM_SHA384를 기록했다.
Target headroom 기록 **15:31:31.658649**와 HAProxy create intent의 선후를 raw에서 확인할 수 있다.
제13차 TLS downgrade·target headroom 순서 오류를 반복하지 않았다.

Broad role enumeration의75초 timeout은 exact scope/no Graph name lookup으로 교정했다.
Operator import가 만든 bytecode는 dirty guard에서 차단된 뒤 생성한 파일 하나만 제거했다.
Mounted-version 보고 projection의 `objectName` KeyError는 actual `id` field로 교정하고 최초 snapshot을 보존했다.
이들은 normal/initialize 재시도나 source 변경이 아니다.

## Positive와 invalid의 경계

Normal **1회 / 7.302539s / valid·success·warmup / 9operations·9attempts**다.
Public initialize는 **1회 / 170.861521s / exit0**으로 **15:34:50.099583**에 종료했다.
CPU poll6개 중 ready2개가 있고, 두 advancing fresh sample·Warning/quiet·owner/UID/resource 검사를 유지했다.
Healthy journey1도 valid/success/warmup9이며 최종 fresh CPU/HPA와 target telemetry가 함께 충족됐다.
Source의 `healthy_initialization_complete`1개, 실제 같은-window ingress HTTP/check/target request는 **각30**이다.
Stale CPU와 target observed만으로 성공을 채우거나 boolean flag로 gate를 우회하지 않았다.

이 positive 뒤에만 전용 UAMI/FIC와 AMW 하나의 Monitoring Data Reader를 생성했다.
KEDA actual image는2.19.0-25이며 다른 ScaledObject/ScaledJob0을 확인했다.
필요한 SA annotation/apply restart1회 뒤 actual2 Pods의 client/tenant/token-path/audience 주입을 검증했다.
CPU HPA exact UID 제거·owner0 확인 후 experiment TriggerAuthentication/ScaledObject를 만들었다.
**15:36:25.851513**, actual scaler Ready·HPA ScalingActive/currentMetrics와 exact ScaledObject UID에 연결된
단일 HPA owner를 확인했다. Operator의 Prometheus query를 scaler 인증 proof로 대체하지 않았다.
Healthy 상태의 **full P9 C3 exact configuration·bounded snapshot15.860679s**와 native deny401,
controlled deny403, non-admin direct sentinel200도 통과했다. 이는 measured scale-out/recovery proof가 아니다.

공통 fault hold1000/capacity2의 actual 수렴 뒤 C3 calibration **1/2회**를 호출했다.
Append-only campaign ledger에 계수한 뒤 run_start와 첫 snapshot **16.953282s / target1 / signal observed**를 기록했다.
하지만 calibration direct sentinel **15회 전부 status null / transport / semantic success0**이었고,
`monitor_failure`1 및 `run_failure`1 뒤 **15:38:47.097405 / 46.941121s / exit1**로 끝났다.
보호된 직접 traceback의 최종 exception은 **`ValueError: direct native-auth sentinel preflight`**다.

Preflight에서200이었던 전용 loopback port-forward의 소유 PID는 중단 후 없었다.
Operator forwarding lifecycle이 calibration 동안 유지되지 않은 invalid 조건을 기록한다.
Process log에는 forwarding/connection만 남았으며 **소멸 원인은 미기록/unknown**이다.
별도 monitor exception도 source가 fixed failure만 발행하여 **unknown**이다.
Azure 네트워크나 source bug로 단정하지 않는다. 준비 positive가 calibration의 실패를 소급 충족시키지 않는다.

Public demand driver 진입/발행은0이다. Existing saved validator는 `failed/incomplete run`으로 거부했다.
이는 **invalid pre-demand calibration**이며 valid-negative mitigation 또는 recovery 실패 측정이 아니다.
두 번째 calibration으로 보충하지 않았다. Freeze, C0/C1/C2/C3 measured 각0, continuing-demand recovery
3×10s SLO/accounting window와 compare/cloud confounder review는 모두 미도달이다.
Source/telemetry deadline을 고치거나 제15차를 실행하지 않았다.

## 비용·기한과 exact owned cleanup

첫 paid mutation 전 한 번의 review에서 두 RG posted ActualCost/usage는 **KRW130,403.04555420384792946**였다.
기존 승인 모델인 ninth baseline 이후 posted delta 전체 + 최대 full-day rate×50h(이미 posted된 기간도 중복 포함)
그리고 Foundation/Bootstrap/Grafana USD5와 이전 미반영 campaign/이번 variable USD15를 합친 보수적 projection은
**세전 USD140.3372743432**, 기존 누적 review envelope **USD180** 안이었다.
Planning stress1200KRW/USD는 시장/청구 환율이 아니다. Fixed2×D4s_v4·기존 DB/ACR 및 current resource/quota,
Retail compute 응답을 확인했다. 추가 retail 응답의 실제 수집 시각도 raw에 보존했다.
초기 잔여시간은 전체 campaign reserve8045초보다 컸다. 추가 allowance0·보존 연장0이다.

최종 ActualCost/usage 조회1회도 성공했고 posted 합계는 같은 금액이었다.
청구 지연 때문에 **P9 단독 증가 실비는 shared/delayed/unknown**이며 posted delta0을 실제 비용0으로 주장하지 않는다.
USD180은 provider billing hard cap이 아니다.
Environment **2026-11-02 10:30 KST**, Foundation/Bootstrap **2026-11-03 00:33 KST**를 유지한다.

실패 후 CUSTOM exact UID 삭제 → shared CM original UID/data guarded restore → KEDA 원래 SA annotation과
deployment template 복구/restore rollout1회·Ready2 → owned Reader role/FIC/UAMI exact ID 제거
→ owned namespace exact UID 삭제를 수행했다.
Namespace inventory guard는 campaign label이 없는 native Istio CA/CRL CM에서 멈췄다.
두 CM의 실제 UID·native label·owned namespace 생성 이후 시각을 확인하고 같은 namespace lifecycle로 정리했다.
Shared cluster CA를 변경하거나 finalizer를 강제 제거하지 않았다. 최초 차단 inventory도 보존했다.

Final native verify **1회/exit0** 뒤 PAT27·28 각각 DELETE204/empty → PAT401 → token list0 →
fixture login 차단/Basic401을 확인했다. Fixture DB records는 보존했다.
Live image references0·single owned tag/digest 확인 뒤 ACR image와 local tag를 제거했다.
임시 AKS role의 exact ID 삭제·RoleAssignmentNotFound와 기존 Owner2개 보존을 확인했다.
KEDA apply/restore 각1회, historical 누적 각3회다.

Stable/owned preservation **33개 check가 모두 true**다. Forgejo/Argo·Secret/mounted versions·PVC/PV/Disk·nodes·
ingress·mesh·KEDA·Azure inventory를 보존했다. P11 재사용을 위해 stable Azure Environment를 남겼으며 전체 teardown은 없다.
보호된 credentials/kubeconfig/clone/trace/registry auth/operator 사본 **224 files**와 임시 Orca metadata 사본3개를 제거했다.
소유 forwarding process는 없고 global Azure CLI login/cache·무관한 base cache는 보존했다.
물리적 secure erasure나 전체 Environment zero residual은 주장하지 않는다.

## Artifact와 검증

[execution.json](execution.json), [comparison.json](comparison.json), [validation.json](validation.json),
[raw-index.json](raw-index.json), [raw-evidence.tar.gz](raw-evidence.tar.gz),
[incident](../../incidents/p9-mitigation-fourteenth.md)를 연결한다.
Archive **240 files**, SHA256 **`4a641565d606f8ebd811515ea1e1ebf50c09a04fe06f698767eae217357ef367`**다.
압축본을 다시 읽어 모든 member path/size/hash를 검증했고, 이전13개 archive byte/hash는 그대로다.
Known credential/encoding·private local path scan matches0이다. Raw failure를 성공으로 수정하지 않았다.
Local/static과 후속 exact-head CI는 validation 및 같은 Draft PR #41에 연결하며 runtime acceptance와 구분한다.

**P9 acceptance 미충족**이다. Calibration/freeze·네 measured arm·실제 scale-out 및 continuing-demand recovery가 남았다.
제15차·새 source 개선·추가 예산/보존 연장·merge/P10은 수행하지 않았다.
