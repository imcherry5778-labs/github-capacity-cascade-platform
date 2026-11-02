# P9 제19차 — Mac initialize 성공 / C3 calibration invalid / owned cleanup 완료

실행 source는 `7ee476d01eea6d5df68e7d237bf9ae07c1b1eb72`다.
[제19차 승인](https://github.com/imcherry5778-labs/github-capacity-cascade-platform/pull/41#issuecomment-6583473509)의 미소비 실행 source만
[사용자 결정](https://github.com/imcherry5778-labs/github-capacity-cascade-platform/pull/41#issuecomment-6584397812)으로 변경했고,
[독립 exact-source review](https://github.com/imcherry5778-labs/github-capacity-cascade-platform/pull/41#pullrequestreview-5740953524) 뒤 같은 Mac checkout/branch/Draft #41에서 실행했다.
실행 중 source 변경은 없다. 이전 Mac first-mutation NO-GO의 소비량0과 제18차 CLOSED/negative를 유지한다.
이번 campaign19는 CLOSED이며 **P9 acceptance 미충족, freeze·C0–C3 measured·유효 comparison/recovery는 없다.**

## 실제 실행

- 실제 Darwin/arm64 CLI·actor/subscription/RBAC·AKS/AMW·source/image/plan·Secret action allowlist·출력 보호와 deadline/owned cleanup reserve를 첫 mutation 전에 확인했다. 기존 고정2노드·AKS1.36.4/asm-1-30·PG17·4RG를 재사용했다. 기존 비용 모델의 bounded usage 증가분을 반영한 누적 projection은 USD285.3566776355, 기존 세전 review cap USD290 이내였다. 신규 allowance·상한 인상·가용 현금 주장은 없다. P9 actual 비용은 shared/delayed/unknown이다.
- Normal·healthy journey는 각각 warmup9 operations/9 attempts `valid/success`, public initialize1·retry0·exit0이다. CPU poll8, telemetry poll4, Prometheus request19/최대25다. Initialize는 `ready_for_keda_authentication=true`, `runtime_preflight_passed=false`까지만 부여했다.
- 전용 UAMI/FIC·exact AMW Monitoring Data Reader, 기존 managed KEDA2.19.0-25 SA/apply restart1회를 사용했다. 실제 새 operator Pod2개의 identity injection, generated-HPA selector/ScaledObject UID와 **실제 external metrics API 응답**, 이후 현재 config/series/DB/resource full gate를 확인했다. Operator 자신의 AMW query만으로 scaler 인증을 주장하지 않았다.
- C3 calibration1이 origin+271.573초에 monitor failure로 invalid 종료됐다. 예정1,800 logical operations 중1,375가 발행됐고425는 unissued, client attempts2,134다. Snapshot16개/최대18.584초, direct sentinel247개는 모두 semantic success다. 이 값은 유효 비교나 완화 성과가 아니다.
- Source는 이후 arrivals를 중단했다. 예정 release 뒤 마지막 snapshot(origin+293.419초)은 두 target의 hold0/capacity1024 수렴을 기록했다. Full360초 demand/recovery를 완료하지 않았으므로 recovery 성공으로 세지 않는다. 실제 최대 admitted Pod4, requests/limits CPU650m/1450m·memory832Mi/1664Mi로 기존 상한을 유지했다.

## 이번 실패와 새 envelope의 실제 범위

실패 cycle의 네 요청은 각각 HTTP200/success/vector였다. **rate는 `[]`, active와 timestamp는 각2개, 1분 sample-count는 한 target의1개 표본만** 반환했다.
두 UID 모두 이미 series가 관측된 기존 target이다. 앞선 snapshot15개의 lifecycle을 replay한 뒤 이 네 응답에서 source와 같은 방식으로 누락 rows를 구성하면 `TargetLifecycle.signal`이 정확히 `unapproved missing telemetry`로 거부한다.
이 cycle에는 다섯 번째 query가 발행되지 않았다. 따라서 이번 실패를 guarded-empty/sub-guard 실패로 바꾸어 설명하지 않는다.

완료 snapshot의 다섯 번째 envelope 응답13개는 actual AMW에서 guarded row·최소 operand·evaluation epoch를 구분해 반환했다. 모든 guarded row가 존재했고 source의 strict extraction/provenance·UTC/monotonic clock·collection/query budget 검증을 통과했다(최대 query1.029초).
이는 실제 AMW envelope 동작 evidence다. 서로 다른 요청의 ingestion 상태가 같다는 보장이나 단일 instant query의 backend transaction/ingestion atomicity를 주장하지 않는다.
제18차 guarded-empty 당시의 미기록 predicate는 여전히 unknown이며, 이번 결과로 소급 확정하지 않는다. 후속 historical query는 하지 않았다.

Saved `validate`는 `failed/incomplete run`으로 거부한다. 별도 `common_guards` replay도 `stale resource metric`을 확인했다.
예를 들어 신규 target의 origin+70.704초 snapshot에서 resource metric age35.126초가 source의 실제 window×2=24.640초 상한을 넘었다. 해당 raw 두 표본을 보존했다.
AMW rate/sample availability가 일시적으로 사라진 scrape/ingestion/backend 원인과 이 resource-metric staleness의 근본 원인은 입증되지 않았다. 값을0으로 만들거나 freshness·Warning·timeout·KEDA predicate를 완화하지 않았다.
같은 source에서 원인에 근거한 operator 교정이 성립하지 않아 calibration2와 measured를 호출하지 않았다. 남은 횟수는 이월하지 않는다.

## Owned cleanup와 검증

CUSTOM exact UID 제거, shared CM UID/data guarded 복원, experiment namespace/Secret/controls 부재, 원래 KEDA SA/template·replicas2/Ready 복귀와 restore restart1회, 전용 AMW role/FIC/UAMI 제거를 확인했다.
Source-bound ACR manifest는 live Pod reference0·exact tag/digest 확인 후 삭제하고 최종 부재도 읽어 확인했다. 임시 AKS role 부재·원래 Owner2개·4RG/ARM resource34개 ID 집합 보존을 확인했다.
Final native verify1회가 성공했다(기존 CLI check5개이며 구조화 operation5개라는 뜻은 아님). Fixture PAT36/37은 각각 DELETE204·재사용401·token list0·login401, DB records 보존을 확인했다.
Stable Argo spec/revisions·Pod/Deployment UID/spec·admin/DB Secret UID/value·CSI version·PVC/PV UID/spec/Bound를 비교했다.
같은 parent가 forwarding을 끝까지 소유했고 의도한 TERM 뒤 wait(-15)로 회수했다. 전체 environment zero residual이나 전역 session containment를 주장하지 않는다.

Operator 오류는 같은 source 안에서 고쳤다. Docker private config의 기존 Mac engine context 연결, Azure CLI tag key parser, ACR tag/manifest response shape, KEDA rollout의 total/new Ready2 확인, nullable external-metric label 대조, preflight의 실제 fault baseline/window 및 nonmutating event writer, exclusive evidence file 충돌이다.
KEDA 전환 중 Warning과 실패한 operator/preflight 기록을 삭제하지 않았다. 현재 full gate는 실제 관측 window로 확인했으며, 측정의 strict Warning/lifecycle 기준은 유지했다. 성공한 normal/initialize/healthy/PAT DELETE/final verify/KEDA restart를 반복하지 않았다.

누적 **campaign19 / public initialize16 / healthy7 / started-invalid calibration4 / measured 각0 / KEDA apply·restore5/5**다.
기존 Environment `2026-11-05T01:30:00Z`, Foundation/Bootstrap `2026-11-05T15:33:00Z`와 USD290 cap을 유지했다. retention 연장·전체 teardown·merge/P10은 없다.

[execution](execution.json), [comparison/gap](comparison.json), [validation](validation.json), [raw index](raw-index.json), [sanitized selected raw archive](raw-evidence.tar.gz)를 함께 본다.
Archive33개 path/size/SHA256은 index와 대조한다. Credential·argv·stderr·private trace/kubeconfig는 제외하고 subscription UUID·소유 local path는 일관되게 대체했다. 원본 selected checksum과 공개본 checksum을 구분한다.
기존 모든 negative/archive/ledger는 변경하지 않았다. 실행 source의 [local-platform](https://github.com/imcherry5778-labs/github-capacity-cascade-platform/actions/runs/41490573718)·[CodeQL](https://github.com/imcherry5778-labs/github-capacity-cascade-platform/actions/runs/41490566988) SUCCESS를 재사용한다. 공개본33개 checksum·sanitized normal/healthy9개 및 negative replay를 재검증했다. Publication scan 뒤 campaign parent exit0과 소유 보호 사본·임시 도구·local image tag 제거를 확인했고 global Azure cache는 보존했다. Evidence-only HEAD/CI는 #41 결과 comment에 연결한다.
