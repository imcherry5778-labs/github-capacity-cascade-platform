# P9 제12차 — 첫 guard collection timeout과 안전 원복

상태: **normal valid/success / initialize1회·첫 collection30초 budget에서 command timeout / CPU poll·healthy·KEDA·calibration·C0–C3 measured0 / P9-owned cleanup 완료 / P9 acceptance 미충족**.
아래 runtime 시각은2026-11-01 UTC이며 campaign 날짜는 같은 날 KST다.

승인·실제 execution source는 **`dfdfaabe03d56a5ec9f1dd6f8cffc6627c621d6f`**,
main/base는 `3f788a9c1d103f6c07bd403af269133fac287002`다.
[제12차 통합 실행·합산 세전 USD140 승인](https://github.com/imcherry5778-labs/github-capacity-cascade-platform/pull/41#issuecomment-6552085327),
[독립 source review PASS](https://github.com/imcherry5778-labs/github-capacity-cascade-platform/pull/41#pullrequestreview-5725569706),
[기존 exact-source Full Local CI](https://github.com/imcherry5778-labs/github-capacity-cascade-platform/actions/runs/41253637820),
[CodeQL/Analyze](https://github.com/imcherry5778-labs/github-capacity-cascade-platform/actions/runs/41253632758)를 재사용했다.
Local/remote/PR SHA·clean source·중복 제12차 process/ledger 부재를 확인했고 code/review/CI와 P6–P8 전체 preflight를 반복하지 않았다.
후속 evidence HEAD는 actual execution source와 구분한다.

## 실제 준비와 source-native 중단

실제 kubectl **v1.36.4**, `.tmp/bin/kubectl` SHA256
`8b8f088da2dab964f853b38464033b1be15ede2839eca751482357c45abdd05a`와 fresh context를 사용했다.
`PYTHONDONTWRITEBYTECODE=1`, `RESULT_PHASE=warmup`, verified HTTPS/native non-admin auth 및 process-local DNS override를 유지했다.
기존 logical version2 Secret UID/data hash와 mounted version을 제11차 binding과 대조해 한정 재사용했고 rotation은 없다.
Exact-source image를 local Podman으로 build/publish하고 registry single tag/digest를 확인했다:
**`sha256:f408a755b05161c7de4ebd2569d849bc01cb3e2373751961c77b86e6d2718555`**.

Existing headroom → injected/init 포함 server-side dry-run admission → guarded shared mesh overlay → target/DB 생성
→ live admission/Ready/restart0와 headroom → backend Service/Ready EndpointSlice → HAProxy 생성/Ready/restart0
→ HPA/PodMonitor/CUSTOM → normal → public initialize 순서를 따랐다.
Initial3Pods의 보수적 합계는 requests **400m/512Mi**, limits **900m/1024Mi**였다.
Active/init restartCount0, lastState empty 및 init 정상 termination을 확인했고 Pod를 교체해 history를 숨기지 않았다.
별도 operator-only Warning gate·추가 probe·임의 retest·준비 invocation 오류는 없다.

Normal create **1회 valid/success/warmup, operation_count9/attempt_count9**, elapsed6.888715초다.
Public initialize **1회/exit1**, `02:06:32.666906` intent → `02:07:10.854522` 종료,
external elapsed **38.187575초**다. Source 내부 `healthy_initialize`는 elapsed **30.006590초**,
`readiness_resource_guard` stage elapsed **8.034265초**에 **`TimeoutExpired / command_timeout`**을 보존했다.

Private diagnostic에서 직접 실패한 source command는 다음과 같으며 Python subprocess timeout은 **0.452934343초**였다.

```text
kubectl --request-timeout=10s get events -A -o json
```

`healthy_initialize`가 첫 configuration 전에 설정한 공유 collection deadline30초는 첫 guard에도 이어진다.
Pre-guard elapsed 약21.972325초에는 configuration과 초기 setup/CPUStartup construction 등이 포함된다.
Guard는 마지막 events collection command에 도달했지만 남은 budget 약0.453초 안에 완료하지 못했다.
`Runtime.k`의 `min(15, remaining)` process timeout이며 개별 명령15초/CLI request10초를 늘리거나 줄인 operator wrapper가 아니다.
`initialization-diagnostic.json`의 classification 문구에서 first guard는 **첫 guard collection**을 뜻한다.
이는 첫 개별 명령이 실패했다는 뜻이 아니며 `failure-interpretation.json`에 구분했다.
각 선행 명령의 개별 latency와 underlying API/service 원인은 **unknown**이다. Full private trace는 공개하지 않고 고정 command/class/budget만 추출했다.

Source `Runtime.guard()`가 반환하지 못했으므로 **CPUStartup poll/Warning 판정은0회**다.
Warning 내용 때문에 실패했다거나 valid-stale candidate 수정이 실패했다고 분류하지 않는다. Post-stop export를 당시 positive로 승격하지 않는다.
Settling300초나 outer840초/kill5초 timeout은 발생하지 않았다. Snapshot30초/command15초, freshness30초/window90초/quiet15초와 acceptance를 변경하지 않았다.
Healthy journey/target telemetry 완료, KEDA 변경·인증, actual C3 canonical configuration, calibration/freeze,
C0–C3 measured 및 continuing-demand recovery는 **모두 미도달**이다. Source 수정·synthetic recovery·자동 retry는 없다.

## 단일 비용 검토와 cleanup

첫 유료 mutation 전 최신 ActualCost/usage와 동일 Environment23/Node RG7 ARM IDs·fixed2×D4s_v4·기존 PostgreSQL/ACR을 한 번의 bounded read-only 검토로 확인했다.
Before two-RG posted ActualCost는 **KRW112,982.43859335**, cleanup 후 final snapshot은 **KRW115,421.7153009966**다.
모두 Oct28–31 posted/Oct31 partial이며 Nov1 posted data는 없다. 제11차 KRW107,878.1372733931과 과거 비용을 보존한다.
Before/final 차이를 P9 비용으로 귀속하지 않는다. **P9 attributable incremental actual은 unknown/shared/delayed**다.

기존 USD115 + 추가 USD25 = **합산 세전 USD140 검토 범위**이며 신규 USD100이나 USD140 재배정이 아니다.
전체 posted 증가를 포함하고 Oct31 00:00 UTC부터 Environment 기한까지49.5h를 **50h로 올려** 최근 full-day rate로 계산했다.
이미 posted된 Oct31 partial도 중복 포함하는 가정이다. Planning stress1200KRW/USD는 실제/시장 환율 주장이 아니다.
미반영 Grafana/Foundation/Bootstrap 등 USD5, 이전 campaign 미반영분과 제12차 variable USD11을 더한 예측은 **USD121.8181787**이었다.
Nominal margin은 확정 unspent balance가 아니며 USD140은 Azure billing hard cap이 아니다. 기존 USD5/USD10 이력을 reset하지 않았다.
첫 검토 당시 Environment 잔여84,376.966초는 preparation30분 + initialize845초 + max6×600초 run + rollback30분의8,045초 reserve보다 컸다.
중간 비용 검토/승인을 반복하지 않았고 cleanup 후 조회는 final posted evidence다.

필수 gate 실패 뒤 **CUSTOM 우선 제거 → shared mesh original UID/data guarded 복구 → owned namespace 삭제**를 완료했다.
KEDA SA/operator/UAMI/FIC/AMW role은 변경0, apply/restore restart **각0회**, historical 누적 **각2회**다.
Final native verify **1회/exit0** 후 **PAT24 DELETE204/empty → PAT401 → token list0 → fixture login 차단/Basic401**을 확인했다.
Live image refs0/single owned tag/digest 확인 뒤 ACR digest·local tag/private auth를 제거했다.
임시 AKS role은 exact ID 삭제/GET404·RoleAssignmentNotFound와 original assignments 보존을 확인했다.
Stable Forgejo/Argo/Secret/PVC/PV/Disk/nodes/ingress·Environment 및 KEDA 보존 비교 **24항목 모두 true**다.
Owned port-forward는 생성하지 않았고 final loopback13000 부재를 확인했다. 보호 local kubeconfig·credential·clone·private trace·registry auth·tool 사본 **126 files**를 제거했다.
Global Azure CLI login/cache, unrelated base cache와 fixture DB records는 보존했다. 물리적 secure erasure/IAM cache 즉시 만료를 주장하지 않는다.

준비/원복 누적 **12회**다. Environment **2026-11-02 10:30 KST**, Foundation/Bootstrap **2026-11-03 00:33 KST**를 유지했다.
추가 retention/provider TTL 변경·신규 compute/Disk/PVC/DNS·전체 Environment teardown은 없다.

## Artifact와 남은 gate

[execution.json](execution.json), [comparison.json](comparison.json), [validation.json](validation.json),
[raw-index.json](raw-index.json), [raw-evidence.tar.gz](raw-evidence.tar.gz)를 연결한다.
Archive **139 files**, SHA256 **`849cb2f5228d92302827f6884f273c469934641e1d059f084671efc31ea198c0`**다.
Member path/size/SHA256와 과거11개 archive의 byte 보존, known credential/encoding/private-path scan matches0을 확인했다.
Implementation 변경이 없어 unchanged source regression/static/local CI를 수동 반복하지 않았다. Final evidence exact-head 자동 GitHub CI는 PR에 별도 기록한다.

남은 gate는 실제 첫 CPU guard collection 완료부터 CPU/healthy positive, KEDA/C3 configuration, calibration/freeze,
C0–C3 측정과 continuing-demand recovery다. **P9 acceptance 미충족**이며 제13차 자동 실행·새 source 수정·merge/P10은 하지 않는다.
기존 Draft PR #41과 P11 재사용용 stable Environment를 보존한다.
