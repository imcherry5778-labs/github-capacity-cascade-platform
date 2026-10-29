# P9 제9차 Azure 준비 — initialize 전 운영 검사 오류로 중단

상태: **normal valid / source initialize0 / 운영자가 추가한 Warning 검사에서 중단 / P9-owned 원복 완료 / P9 acceptance 미충족**.
Campaign 날짜는2026-10-30 KST이며 아래 실제 시각은2026-10-29 UTC다.

승인·실제 preparation source는 **`ee75e3a336326ec5567b5f399ec08028169b02f1`**,
main/base는 `3f788a9c1d103f6c07bd403af269133fac287002`다.
[제9차 통합 승인](https://github.com/imcherry5778-labs/github-capacity-cascade-platform/pull/41#issuecomment-6510384906),
[독립 source review](https://github.com/imcherry5778-labs/github-capacity-cascade-platform/pull/41#pullrequestreview-5705882474),
[승인 source Full Local CI](https://github.com/imcherry5778-labs/github-capacity-cascade-platform/actions/runs/40962772330),
[CodeQL](https://github.com/imcherry5778-labs/github-capacity-cascade-platform/actions/runs/40962765010)를 확인했다.
실행 전후 clean source를 대조했으며 구현 변경은 없다. 후속 evidence HEAD와 actual execution source를 구분한다.

## Actual preparation

첫 외부 mutation 전 `RESULT_PHASE=warmup`, 실제 repository `.tmp/bin/kubectl` **v1.36.4**와
SHA256 `8b8f088da2dab964f853b38464033b1be15ede2839eca751482357c45abdd05a`를 확인했다.
Live tools·cluster UID·Argo revision·chart digest·runtime imageIDs로 fresh normal context를 생성했다.
Native non-admin auth, HTTPS certificate/hostname verification, process-local DNS override를 사용했다.
Admin logical version2 한정 reuse 시 기존 Secret UID/data hash와 mounted version을 대조했다. Secret rotation은 없다.

Normal create **1회/exit0/7.256초**, actual structured validator **valid/success/warmup, operation_count9/attempt_count9**다.
Run ID는 `20261029231942-446e2f`다. 정상 요청 이후 기록 wrapper가 잘못된 validator key `operations`를 읽어
KeyError를 냈으나 실제 결과를 변경하지 않고 올바른 schema로 read-only 확인했다. Normal create를 반복하지 않았다.

Exact-source image를 local build/publish하고 ACR의 단일 SHA tag/digest를 대조했다.
Digest는 **`sha256:9be5dcba04e73b492048da58d4bdf141cd5ede160f5a4cffb10f60f46ce1133b`**다.
ACR manifest metadata에 `tags`가 있다고 가정한 operator 조회를 실제 `show-tags --detail` 결과로 교정했다.
Publish 재실행이나 ACR Tasks/새 compute는 없다.

ConfigMap `23:23:45/46` → backend Service `23:23:47` → target Deployment `23:26:27`
→ target Ready `23:26:41` → **HAProxy Deployment `23:26:43`** 순서였다.
실제 Service/ClusterIP/selector와 Ready EndpointSlice를 HAProxy 생성 전에 확인했다.
Target·HAProxy·DB의 initial/post-stop Pod3는 모두 Ready/Running, active restart0/lastState empty였다.
Init container도 restart0/Error·OOM 없음이었다. Pod 교체나 history reset은 없다.
Actual admission의 보수적 합계는 requests **400m/512Mi**, limits **900m/1024Mi**였다.

**준비 순서 이탈:** operator는 server-side dry-run admission와 baseline node headroom 뒤
`23:26:22`에 shared mesh를 적용하고 target을 생성했다. Actual live admission은 그 뒤 HPA/PodMonitor/CUSTOM 전에 확인했다.
이는 shared mesh 전에 실제 Pod admission을 요구한 승인 순서를 모두 지킨 것이 아니다.
당시 이유는 새 target의 bootstrap stats matcher 적용이었다. Dry-run을 actual 승인 gate의 대체 proof로 인정하지 않는다.
설정은 최종 원래 UID/data로 복구했으며 이 순서 이탈도 raw에 보존했다.

## 실제 중단 원인과 판정 한계

**승인된 source의 `initialize`는 호출되지 않았다.** 첫 operator wrapper는 importlib가 만든 untracked bytecode를
clean-source 검사에서 발견해 호출 전에 멈췄다. 자신이 생성한 파일 하나만 SHA 확인 후 제거했고 이후 bytecode 생성을 막았다.
두 번째 wrapper는 승인 source보다 넓은 **namespace 전체 retained Warning 검사**를 추가해 아래 Pod Warning을 거부했다.
이는 불필요한 운영 gate를 추가한 오류이며 CPUStartup/settling 실패가 아니다.

| Owner | Reason/count | First–last UTC | Ready UTC |
| --- | --- | --- | --- |
| target `istio-proxy` startup probe | Unhealthy/2 | 23:26:28–29 | 23:26:41 |
| target `app` readiness probe | Unhealthy/2 | 23:26:31 | 23:26:41 |
| HAProxy readiness TCP probe | Unhealthy/1 | 23:26:44 | 23:26:44 |

HAProxy는 Warning과 Ready가 같은 초이며 subsecond 선후관계는 unknown이다.
Post-stop capture에서 이 Warning history/count/time은 변하지 않았다. Warning을 삭제하거나 숨기지 않았다.
Source `Runtime.guard()`는 일반 Warning에 `last observed >= Runtime.since`를 적용하고,
CPU preparation의 해당 HPA Warning은 별도로 과거 이력까지 포함한다.
Operator의 전체 history 검사는 이 구분을 따르지 않았다. 실제 source guard 자체가 실행되지 않았으므로
추후 gate 통과 여부도 측정하지 않았다. 최초 raw `mandatory_gate` 표기는 그대로 두고
`operator-stop-interpretation.json`에 그 표기가 source 요건이 아니라는 정정을 추가했다.

같은 HPA UID의 metric Warning도 raw에 남겼지만 CPUStartup은 이를 관측하지 않았다.
Post-stop Pod metric을 준비 완료 proof로 승격하지 않는다. **CPU source 관측0, initialize0, healthy journey0,
KEDA mutation/restart0/0, calibration0, C0–C3 각각0**, freeze 없음, mitigation/recovery **not measured**다.
Synthetic 입력, fault, acceptance 완화, 자동 재준비/제10차 workload는 없다.

## 비용·기한·원복

첫 유료 mutation 전 live resource identity·최신 비용/usage와 +72h 비용 위험을 조회했다.
주요 고정 retail 소계는 **USD69.6598537**(월 단위72/730 가정)이며 private endpoint/DNS·계측/트래픽·Grafana users·
Foundation/Bootstrap·tax/FX 등은 제외/변동이다. 실제 청구액 보장이 아니다. 사용자는 이 session에서
**기존 누계와 별도로 추가 세전 USD100 검토 한도**를 기존 +72h 유지 및 제9차1회에 승인했다.
기존 USD5 계획/USD10 검토 기준을 초기화하지 않는다. USD100도 Azure billing hard cap이 아니다.
`cost-risk-review.json`의 승인 전 상태는 historical이며 뒤의 `additional-cost-approval.json`을 함께 읽는다.

Before/final two-RG ActualCost는 **KRW49,306.6929280465**다(Oct28 30,259.1340498108 + Oct29 19,047.5588782357).
Shared/delayed billing으로 **P9 incremental actual unknown**이며 before/final 동일값을 비용0으로 해석하지 않는다.
과거8회·제8차 KRW44,295.3701043718과 모든 raw/checksum을 보존하며 이번 준비/원복까지 누적 **9회**다.

CUSTOM을 먼저 exact UID로 제거한 뒤 shared UID/data test 원복, 소유 namespace 삭제를 확인했다.
Final native read-only verify1/exit0 후 **PAT20 DELETE204/0 bytes → PAT401 → list0 → login 차단/Basic401**을 확인했다.
Fixture account/repo/Issue/PR records는 보존했다. Image live refs0/단일 owned digest 삭제/ACR repo 부재,
임시 AKS role exact ARM DELETE/GET RoleAssignmentNotFound와 기존 assignment2개 보존을 확인했다.
Stable Forgejo/Argo/Secret/PVC/PV/Disk/nodes/ingress 및 Environment ARM IDs, KEDA unchanged/Ready2 등
보존 비교 **19개 모두 true**다. KEDA 변경/신규 identity와 apply/restore restart는 각각0이며 historical 각1회는 유지한다.
보호 local credential/kubeconfig/registry auth/fixture clone/tool 사본을 제거했다.
Global Azure CLI login, shared base/node image cache와 fixture DB records를 물리 삭제했다고 주장하지 않는다.

Environment **2026-11-02 10:30 KST**, Foundation/Bootstrap **2026-11-03 00:33 KST** 계약을 유지한다.
추가 기한 연장/provider TTL 변경/전체 teardown은 없고 P11 재사용을 위해 기존 환경을 보존했다.
이번 중단으로 P9 acceptance는 미충족이다. 새 paid campaign은 자동 반복하지 않는다. Draft 유지, merge/P10 없음이다.

## Artifact와 검증

[execution.json](execution.json), [comparison.json](comparison.json), [validation.json](validation.json),
[raw-index.json](raw-index.json), [raw-evidence.tar.gz](raw-evidence.tar.gz)에 실제/negative/원복을 기록했다.
Archive **163 files**, SHA256 **`3ed885e18457997996a150401bbfc97aa2211cd8c5b255d9e4c357474110d7b9`**다.
각 member path/size/SHA256, 과거8개 archive의 byte 보존, 실제 credential/private path 유출 검사를 확인했다.
구현과 test 변경이 없어 P6/P7/P8 전체 실험이나 unchanged regression을 수동 반복하지 않았다.
Final evidence exact-head GitHub CI는 actual source CI와 분리해 PR에 기록한다.
