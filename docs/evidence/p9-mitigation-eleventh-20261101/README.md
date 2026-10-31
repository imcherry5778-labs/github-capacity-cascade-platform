# P9 제11차 — CPU settling timeout과 안전 원복

상태: **normal valid/success / public initialize1회·CPU settling300초 중단 / healthy·KEDA·calibration·C0–C3 measured0 / P9-owned cleanup 완료 / P9 acceptance 미충족**.
Campaign 날짜는2026-11-01 KST이며 아래 runtime 시각은2026-10-31 UTC다.

승인·실제 execution source는 **`94deb6d7b51ab61091f90ee9ad281c4a9afb56cb`**,
main/base는 `3f788a9c1d103f6c07bd403af269133fac287002`다.
[제11차 실행·합산 세전 USD115 검토 승인](https://github.com/imcherry5778-labs/github-capacity-cascade-platform/pull/41#issuecomment-6548514900)과
[독립 source review PASS](https://github.com/imcherry5778-labs/github-capacity-cascade-platform/pull/41#pullrequestreview-5724645562)를 연결한다.
Local/remote/PR exact SHA와 clean source, 중복 제11차 process/ledger 부재를 확인했다.
기존 source·CI·제10차 positive evidence를 다시 검증하거나 P6–P8 전체 preflight를 반복하지 않았다.
후속 evidence HEAD는 actual execution source와 구분한다.

## 실제 준비와 CPU 관측

실제 kubectl **v1.36.4**, `.tmp/bin/kubectl`의 SHA256
`8b8f088da2dab964f853b38464033b1be15ede2839eca751482357c45abdd05a`와 fresh context를 사용했다.
`PYTHONDONTWRITEBYTECODE=1`, `RESULT_PHASE=warmup`, verified HTTPS/native non-admin auth 및 process-local DNS override를 유지했다.
기존 logical version2의 Secret UID/data hash와 mounted version을 제10차 binding과 대조해 한정 재사용했다.
Normal create는 **1회 valid/success/warmup, operation_count9/attempt_count9**다. 기록·validator invocation 교정 때문에 정상 create를 반복하지 않았다.

승인 exact-source image를 local Podman으로 build/publish하고 registry single tag/digest를 대조했다:
**`sha256:e932b4725b472de71d0433284a73fad5358d82a9b67b558e99f19010a3f7ba3e`**.
Existing headroom → injected/init 포함 server dry-run → guarded shared mesh overlay → target/DB 생성과 live admission/Ready/restart0
→ backend Service/Ready EndpointSlice → HAProxy 생성/Ready/restart0 → HPA/PodMonitor/CUSTOM → public initialize 순서를 따랐다.
Initial Pod3의 보수적 합계는 requests **400m/512Mi**, limits **900m/1024Mi**였다.
Ready뿐 아니라 active/init restartCount0, lastState empty와 init 정상 termination을 확인했고 Pod history를 reset하지 않았다.
별도 operator-only Warning gate는 없다.

Public initialize **1회/exit1**, external invocation elapsed **308.521094초**다.
Source 내부 `healthy_initialize`는 **300.000103초**에 `readiness_resource_guard`에서 실패했다.
Private diagnostic의 마지막 exception은 **`ValueError: CPU preparation settling timeout`**으로 확인했다.
Full private trace는 공개하지 않고 고정 class/message만 `initialization-diagnostic.json`에 보존했다.
Outer840초/kill5초가 먼저 종료시킨 것이 아니며 settling300초, window90초/freshness30초,
snapshot30초/command15초, quiet15초 및 두 advancing valid sample 조건을 변경하지 않았다.

| CPU poll | Sample UTC | Window(s) | Fresh + Ready 이후 전체 window | HPA positive | Source status |
| --- | --- | ---: | --- | --- | --- |
| 1 | 20:15:31 | 49.110911296 | false | false | pending |
| 2 | 20:16:26 | 54.294 | true | true | pending |
| 3 | 20:16:26 | 54.294 | false | true | pending |
| 4 | 20:17:26 | 59.860 | false | true | pending |
| 5 | 20:18:24 | 58.102 | true | true | pending |
| 6 | 20:18:24 | 58.102 | false | true | pending |
| 7 | 20:19:18 | 53.827 | false | true | pending |
| 8 | 20:20:26 | 68.051 | true | true | pending |

Poll2·5·8에 실제 fresh CPU/HPA positive를 관측했지만 source 준비 완료는0회다.
Poll3·6은 이전에 검증한 동일 sample의 stale duplicate라 positive로 세지 않고 candidate를 보존한다.
Poll4·7은 **새 timestamp인데 이미 stale**였으며, 첫 poll을 제외한 모든 sample window는 Ready 이후에 들어온다.
Exact source의 `positive=false && stale_duplicate=false` 분기에 따라 poll4·7이 candidate를 지우는 것으로 해석한다.
이는 archived actual poll과 실행 source에서 도출한 inference이며 emitter에 candidate state를 새로 추가한 결과가 아니다.
Poll 간격은 약38.2–39.5초였고 마지막 fresh poll8은 새 candidate만 남긴 채 hard cap에 도달했다.

정확한 CPU HPA owner의 startup Warning 두 history는 count3→4를 관측했다.
첫 positive poll2 이후에는 UID/reason/first/last timestamp/count history가 그대로 유지됐다.
이번 직접 중단 사유는 Warning 재발이나 C3 ScaledObject spec mismatch가 아니라 CPU settling timeout이다.
Healthy journey·target telemetry 완료·KEDA 인증/변경·실제 C3 empty normalization·calibration/freeze·measured·recovery는 **모두 미도달**이다.
제10차의 historical CPU/healthy/KEDA positive를 제11차 live 성공으로 승격하지 않는다. Synthetic 입력·자동 retry·source 수정은 없다.

## 비용과 cleanup

첫 유료 mutation 전에 current resource IDs/SKUs 및 ActualCost/usage를 **한 번의 bounded read-only 비용 검토**로 확인했다.
Cost Management429는 Retry-After에 따른 제한된 재시도 후 회복했다. 별도 Consumption read는 fallback으로 보존했다.
Before/final two-RG ActualCost는 약 **KRW107,878.1372733931**이며 Oct28–31 posted/Oct31 partial이고 Nov1 posted usage는 없다.
제10차 KRW104,099.2492616492, 제9차 KRW49,306.6929280465와 이전 비용을 보존한다.
P9 attributable incremental actual은 **unknown**이며 동일 before/final을 추가 비용0으로 해석하지 않는다.

기존 USD100 + 추가 USD15 = **합산 세전 USD115 검토 범위**다. 신규 USD100을 더하거나 USD5/USD10 이력을 초기화하지 않았다.
전체 posted 증가를 포함하고 Oct31 00:00 UTC부터 Environment 기한까지 **49.5h를50h로 올려** 최근 full-day rate로 계산했다.
이미 posted된 Oct31 partial도 중복 포함하는 보수적 가정이며 planning stress1200KRW/USD는 실제/시장 환율 주장이 아니다.
미반영 Grafana/Foundation/Bootstrap 등 USD5, 이전 campaign 미반영분과 제11차 variable USD6을 더한 예측은 **USD112.5645943**였다.
Nominal margin은 확정 잔액이 아니고 USD115는 Azure billing hard cap이 아니다. 상세 가정은 `cost-risk-review.json`에 보존했다.

필수 gate 실패 뒤 **CUSTOM 우선 제거 → shared mesh UID/data guarded 복구 → owned namespace 삭제**를 완료했다.
KEDA SA/operator/UAMI/FIC/AMW role은 이번에 변경하지 않아 apply/restore restart **각0회**, historical 누적은 **각2회**다.
최종 native verify1/exit0 후 **PAT23 DELETE204/empty → PAT401 → token list0 → fixture login 차단/Basic401**을 확인했다.
Live image refs0/single owned tag/digest를 대조해 ACR digest·local tag/private registry auth를 제거했다.
임시 AKS role은 exact ID 삭제/GET404와 original assignments 보존을 확인했다.
Stable Forgejo/Argo/Secret/PVC/PV/Disk/nodes/ingress·Environment 및 KEDA 보존 비교 **24항목 모두 true**다.
Owned port-forward는 생성하지 않았고 final loopback13000 부재를 확인했다.
보호 local kubeconfig·credential·fixture clone·private diagnostic·registry auth·tool 사본 **126 files**를 제거했다.
Global Azure CLI login/cache, unrelated base cache와 fixture application DB records는 보존했다. 물리적 secure erasure/IAM cache 즉시 만료를 주장하지 않는다.

Azure 준비/원복 누적 **11회**다. Environment **2026-11-02 10:30 KST**, Foundation/Bootstrap **2026-11-03 00:33 KST**를 유지했다.
추가 retention 연장/provider TTL 변경/신규 compute·Disk·PVC·DNS/전체 Environment teardown은 없다.

## Artifact와 남은 gate

[execution.json](execution.json), [comparison.json](comparison.json), [validation.json](validation.json),
[raw-index.json](raw-index.json), [raw-evidence.tar.gz](raw-evidence.tar.gz)를 연결한다.
Archive **142 files**, SHA256 **`0ff59629a0ebe513179878bcac4c00bc2018f6ef232a9b4c35188a3a04799cf7`**다.
Member path/size/SHA256, 과거10개 archive byte 보존과 known credential/encoding/private-path 검사를 확인했다.
Consumption full payload의 unrelated billing/customer/account fields는 공개하지 않고 allowlisted actual excerpt와 original checksum을 보존한다.
Primary forecast의 Cost Management response는 그대로 공개한다.

Operator invocation 교정은 `operator-invocation-corrections.json`에 기록했다.
Local Docker daemon 부재, read-only kubectl/context/validator 인자, Pod guard 필드와 append-only 기록, in-process env 문제는
public initialize 호출 전에 교정했다. Normal create·HAProxy 생성·public initialize·workload를 반복하지 않았다.
Implementation과 source acceptance는 변경하지 않았다. Unchanged source local/static regression을 반복하지 않고 final evidence exact-head GitHub CI를 PR에 기록한다.

남은 실제 gate는 CPU preparation 완료와 healthy positive 이후 C3 normalized source configuration, calibration/freeze,
C0–C3 비교 및 continuing-demand recovery다. P9 acceptance는 미충족이며 제12차 자동 실행·merge/P10은 하지 않는다.
추가 유료 실행은 새 exact-source·비용 승인 대상이다. 기존 Draft PR #41과 stable Environment를 보존한다.
