# P9 제10차 — 실제 CPU/healthy/KEDA positive, calibration 초기화 중단

상태: **CPU/HPA·healthy telemetry·KEDA 인증/ownership 실제 positive / calibration1 invalid / C0–C3 measured0 / P9-owned 원복 완료 / P9 acceptance 미충족**.
Campaign 날짜는2026-11-01 KST이며 아래 runtime 시각은2026-10-31 UTC다.

승인·실제 execution source는 **`d23e1629d0206db914088a54c6378d17237b67c8`**,
main/base는 `3f788a9c1d103f6c07bd403af269133fac287002`다.
[제10차 승인·수정된 준비 순서](https://github.com/imcherry5778-labs/github-capacity-cascade-platform/pull/41#issuecomment-6513440879),
[독립 review](https://github.com/imcherry5778-labs/github-capacity-cascade-platform/pull/41#pullrequestreview-5706689034),
[source Full Local CI](https://github.com/imcherry5778-labs/github-capacity-cascade-platform/actions/runs/40975269223),
[CodeQL/Analyze](https://github.com/imcherry5778-labs/github-capacity-cascade-platform/actions/runs/40975261693)를 확인했다.
실행 전후 clean SHA와 실제 kubectl v1.36.4 path/SHA256을 대조했고 fresh context를 생성했다.
`PYTHONDONTWRITEBYTECODE=1`을 유지했으며 구현 변경·별도 Warning blocking gate·Pod history reset은 없다.
후속 evidence HEAD는 actual execution source와 구분한다.

## 실제 준비와 CPU/healthy positive

Normal create **1회 valid/success/warmup, operation_count9/attempt_count9**다.
Actual tools·cluster UID·Argo revision·chart digest·runtime imageID로 context를 생성했고 native non-admin auth와
HTTPS certificate/hostname verification, process-local DNS override를 유지했다. 기존 admin logical version2의
Secret UID/data hash와 mounted version을 대조해 한정 재사용했다. Secret rotation은 없다.

Exact-source single-tag image를 build/publish하고 registry digest를 확인했다:
**`sha256:7a54088ec034b7f7ee4a17758d870cb39100b4e8d1f3b3e0576f36839812d7e6`**.
Existing node headroom → server-side injected dry-run admission → guarded shared mesh overlay → target 생성
→ actual live admission/Ready/restart0 → backend Service/Ready EndpointSlice → HAProxy 생성/Ready/restart0
→ HPA/PodMonitor/CUSTOM → public `initialize` 순서를 따랐다. Dry-run을 live proof로 취급하지 않았다.
Initial Pod3의 보수적 합계는 requests **400m/512Mi**, limits **900m/1024Mi**였다.
Target·HAProxy·DB active restart0/lastState empty, init restart0/Error·OOM 없음과 고정 UID를 확인했다.

Public `initialize` **1회/exit0**, `17:45:49.972987` intent → `17:49:50.217556` 종료,
elapsed **240.244508초**다. Source의 settling300초, window90초/freshness30초,
quiet15초/두 advancing valid sample, snapshot30초/command15초, outer840초/kill5초를 변경하지 않았다.
Source-native Warning history/owner/UID/reason 검증을 사용했고 namespace-wide 검사는 추가하지 않았다.

| Source CPU poll | Sample UTC | Fresh + Ready 전체 window | HPA recovered | Status |
| --- | --- | --- | --- | --- |
| 1 | 17:45:33 | false | false | pending |
| 2 | 17:46:26 | true | false | pending |
| 3 | 17:46:26 | false | true | pending |
| 4 | 17:47:22 | true | true | pending/candidate |
| 5 | 17:47:22 | false | true | pending/stale duplicate |
| 6 | 17:48:23 | true | true | **ready** |
| 7, journey 이후 | 17:48:23 | false | true | pending |
| 8 | 17:49:31 | true | true | **ready/final telemetry** |

Poll4→동일 stale poll5→fresh advancing poll6에서 준비를 완료했다. Stale poll5를 positive로 세지 않았다.
Journey 이후 poll7도 stale 자체로 최종 성공시키지 않았고 poll8의 fresh CPU/HPA와 target telemetry가 함께 positive일 때 완료했다.
Healthy journey는 **1회**, actual same-window ingress HTTP30 / ALLOW checks30 / target requests30이었다.
Developer operations와 HTTP request 수를1:1로 해석하지 않는다. Correlation/native auth, target inbound mapping·native stats,
counter/log accounting 및 Prometheus per-Pod coverage/freshness를 source completion에서 검증했다.
Prometheus query9개는 HTTP200이며 no-data를 zero로 바꾸지 않았다. Synthetic 입력은 없다.
`healthy_initialization_complete`는 KEDA 인증 준비만 허용하며 full runtime preflight flag를 부여하지 않는다.

## KEDA actual proof와 calibration 중단

다른 ScaledObject/ScaledJob0을 확인한 뒤 승인된 `p9-keda-prometheus` UAMI, 실제 OIDC issuer의
`system:serviceaccount:kube-system:keda-operator` FIC와 기존 AMW 단일 scope Monitoring Data Reader를 준비했다.
[Managed KEDA 절차](https://learn.microsoft.com/en-us/azure/aks/keda-workload-identity)에 따라 SA annotation 후
operator apply restart **1회**를 사용했고 실제 client/tenant/token-path/audience 주입을 확인했다. Token 값은 읽지 않았다.
CPU HPA exact UID 삭제/zero-owner 확인 후 TriggerAuthentication/ScaledObject를 생성했다.
`17:53:03.490099`에 ScaledObject Ready, 정확한 generated HPA owner UID,
ScalingActive=True/currentMetrics averageValue0, current/desired replicas1을 확인했다.
이는 실제 scaler 응답이며 operator identity의 query 성공을 scaler 인증 proof로 대신하지 않았다.
Scale-out/mitigation 성공은 아직 측정하지 않았다.

Operator preflight는 P8 configuration과 P9 safety/controller/admin/native/telemetry validators, direct native sentinel의 actual reads를
기록했다. `approval-measurement.json`의 preflight flag는 그 operator assertion이며 **P9 C3 전체 configuration 완료 proof가 아니다**.
Operator preflight에서 C3 ScaledObject exact-spec equality는 실행하지 않았다(`preflight-interpretation.json`).
Fault maxRequests2/hold1000의 실제 수렴을 확인한 뒤 C3 calibration1을 public source command로 호출했다.

**Calibration1은 `17:56:19.937631` ledger 계수 후 `17:56:41.922154` exit1, elapsed22.081829초로 중단했다.**
`configuration.json`, `run_start`, snapshot, offered-arrival event가 없고 `invocation-failure.json`만 남았다.
실패도 calibration 사용1회에 포함한다. CLI는 generic failure만 출력해 직접 exception class/message·stack은 **unknown**이다.

종료 시 보존한 실제 ScaledObject와 source render의 확인된 차이는 **`spec.advanced.scalingModifiers: {}`**뿐이다.
이 빈 object는 생성 응답에도 이미 있었고 이 field만 제외하면 spec은 일치한다.
현재 `Runtime.configuration`의 exact-spec equality predicate는 이 admitted object에 대해 false다.
이는 확인된 source/runtime 계약 충돌이며, 기록되지 않은 직접 exception을 소급 입증한 것으로 표현하지 않는다.
Operator preflight의 일부 positive와 실패한 public C3 configuration을 구분한다.
추가 calibration/자동 재시도/acceptance 완화/배포 source 변경은 없다.
Freeze 없음, **C0/C1/C2/C3 measured 각각0**, mitigation/recovery·continuing-demand recovery **not measured**다.

## 비용·원복·보존

첫 유료 mutation 전 bounded read-only cost/usage와 동일 Environment23/Node RG7 ARM IDs·actual SKUs를 확인했다.
Before/final two-RG ActualCost는 **KRW104,099.2492616492**다(Oct28–31 posted/Oct31 partial).
이전 제9차 **KRW49,306.6929280465**와 과거 비용을 보존하며 P9 attributable incremental actual은 **unknown**이다.
동일 before/final 값을 비용0으로 해석하지 않는다. Mixed-service usage quantities를 합쳐 하나의 단위로 보지 않는다.

**기존 세전 USD100 검토 총액 안의 잔여 범위**만 사용했고 신규 USD100 배정은 없다.
기존 +72h 주요 고정 retail 소계 USD69.6598537을 재사용했다. 전체 posted 증가 KRW54,792.5563을 보수적으로 포함하고,
미반영+남은 보존40시간을 최근 full-day rate로 예측했다. Planning stress1200KRW/USD(실제/시장 환율 주장이 아님),
미반영 Grafana/Foundation/Bootstrap 등 USD5와 campaign variable contingency USD5를 더한 검토 예측은 **USD97.8645095**였다.
Nominal margin은 확정 unspent balance가 아니다. `cost-risk-review.json`에 가정과 제외/변동 위험을 기록했다.
USD100은 Azure billing hard cap이 아니고 기존 USD5 계획/USD10 검토 기준도 초기화하지 않았다.

실패 직후 **CUSTOM 우선 제거 → shared original UID/data 복구 → owned scaler/HPA 제거 → KEDA SA/template 복구**를 수행했다.
Apply의 restart annotation을 원래 template annotation으로 돌리는 **restore rollout1회** 후 Ready2·owned client env 부재를 확인했다.
Namespace/Secret/fixtures/monitor 삭제, native final read-only verify1/exit0,
**PAT21·22 각각 DELETE204/0 bytes → PAT401 → list0 → login 차단/Basic401**을 확인했다.
Fixture account/repo/Issue/PR records는 보존했다. Owned port-forward 종료/loopback 부재, workspace role/FIC/UAMI exact delete·GET not-found,
기존 identity IDs 보존, image live refs0/exact digest delete·ACR repo 부재, 임시 AKS role exact delete/GET not-found·original assignments 보존을 확인했다.
Stable Forgejo/Argo/Secret/PVC/PV/Disk/nodes/ingress·Environment와 KEDA 복구 등 보존 비교 **22개 모두 true**다.
보호 local credential/clone/kubeconfig/tool/registry auth 사본을 제거했다. Global CLI login, node/base image cache와 fixture DB records는 보존했다.
IAM auth-cache 즉시 만료나 물리적 secure erasure를 주장하지 않는다.

Azure 준비/원복 누적 **10회**, historical KEDA 각1회 + 이번 각1회 = apply/restore 누적 **각2회**다.
Environment **2026-11-02 10:30 KST**, Foundation/Bootstrap **2026-11-03 00:33 KST** 계약을 유지한다.
추가 연장/provider TTL 변경/전체 teardown/신규 compute·Disk·PVC·DNS는 없다. P11 재사용을 위해 기존 환경을 보존했다.

운영 기록 오류도 보존했다: 첫 local build의 BASE_IMAGE 인자 누락은 build step/publish 전 교정했고,
standalone context validator의 transport env 누락도 normal create 전에 교정했다. Azure CLI identity parser 오류는 exact-ID GET not-found 뒤
동일 승인 ARM PUT으로 처리했다. FIC DELETE 뒤 generic NotFound code의 기록 assertion은 read-only 확인으로 교정했으며 delete를 반복하지 않았다.
성공한 normal/healthy journey나 calibration workload를 반복하지 않았다.

## Artifact와 검증

[execution.json](execution.json), [comparison.json](comparison.json), [validation.json](validation.json),
[raw-index.json](raw-index.json), [raw-evidence.tar.gz](raw-evidence.tar.gz)를 연결한다.
Archive **220 files**, SHA256 **`5ff8400aa7b292d2490a82d94775890f5916e8078ae8429246c816bffd8b4811`**다.
각 member path/size/SHA256, 과거9개 archive byte 보존과 known credential/private path 검사를 확인했다.
구현 변경이 없어 unchanged regression/P6–P8 전체 실험을 수동 반복하지 않았다. Final evidence exact-head CI는 PR에 별도 기록한다.
P9 acceptance는 미충족이며 자동 제11차 실행·새 source 수정·merge/P10은 수행하지 않는다. 같은 Draft PR을 유지한다.
