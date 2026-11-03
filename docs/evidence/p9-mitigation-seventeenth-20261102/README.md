# P9 제17차 — cadence 관측, 최종 CPU freshness·telemetry budget 실패

**단일 campaign 종료 / initialize 재호출0 / KEDA·calibration·measured·recovery 미도달 / P9 acceptance 미충족**.

[명시 실행 승인](https://github.com/imcherry5778-labs/github-capacity-cascade-platform/pull/41#issuecomment-6572646532)과
[독립 source review](https://github.com/imcherry5778-labs/github-capacity-cascade-platform/pull/41#pullrequestreview-5733758699)의
고정 source `daeaff99cfddd33dd2409b2dfa15f25af56a2635`를 실행했다. Current main
`d9977cc9046485bb7b47849297ec9769a3629223`의 #46 운영 보정을 읽되 paid checkout에 merge하지 않았다.
실행 전 PR base snapshot은 `b8dc521af4671306f4b5abfefea244c8143ba5a4`다.
후속 docs/evidence commit은 실행 source가 아니며 repository implementation source는 변경하지 않았다.

첫 mutation은 **2026-11-02 08:54:48 UTC**였다. 단일 exact-AKS 임시 Entra user role과 보호 user kubeconfig,
source/campaign label을 확인한 image digest
`sha256:c3cb76175c4f3247650b68a6b695afa8dbf2c7bb2dc7f31e88e38ce7072c2d61`,
actual cluster/Pod UID·managed ingress IP·hostname·preparation plan hash를 결합했다.
4-Pod preview는 requests650m/832Mi, limits1450m/1664Mi다. DB hostname/CA verify-full·TLS/read-only SQL과
target-stage headroom 확인 뒤 HAProxy를 준비했다. Stable Argo는 Synced/Healthy였다.

## 실제 positive와 실패 경계

Normal1과 healthy journey1은 각각 **valid/success/warmup, 9operations/9attempts**다.
Public initialize1은 **09:15:47–09:19:15 UTC / exit1**, source 내부 elapsed201.479초였다.
CPU poll9개 중 fresh3·ready2이며 첫 fresh51.665초, 두 advancing fresh sample의 준비 완료116.957초였다.
HPA 회복·같은 UID/Warning 이력·window/quiet 조건은 유지했다.

| Source 시작 후 | CPU sample age | CPU 판정 | Target signal |
| --- | ---: | --- | --- |
| 19.619s | 44.162s | pending | journey 전 |
| 51.665s / 83.744s | 14.208s / 46.287s | 첫 fresh / stale | journey 전 |
| 116.957s | 23.500s | ready | healthy journey 진입 |
| 140.515s / 155.462s | 39.471s / 54.406s | pending | 뒤의141.369s / 157.795s 결과는 uninitialized |
| 170.809s | 69.732s | pending | 171.770s 결과는 observed |
| 185.891s | 21.695s | ready | 186.905s 결과는 observed, 최종 CPU freshness 미충족 |
| 200.781s | 36.742s | pending | 다섯 번째 수집은 미완료 |

완료된 telemetry4회의 시작 간격은 **15.000118 / 15.000066 / 15.000068초**다.
수집 시작부터 결과까지12.740 / 14.166 / 13.141 / 13.275초였다.
따라서 DAE의 시작 기준 cadence는 실제 관측됐다. 결과 간격과 시작 간격을 혼동하지 않는다.
제16차와의 차이는 통제된 인과 비교나 전체 runtime remediation 증거가 아니다.
두 observed signal은 같은 target UID의 inbound overflow rate0/active0/samples≥2 및 guarded query0이었다.

네 번째는 CPU guard ready와 signal observed를 기록했지만 `positive_path`에 진입하지 않고 다음 poll로 진행했다.
변경 없는 source 분기로부터 **최종 `clock() <= cpu_fresh_until`이 false였음**을 추론한다.
그 결과 시점의 CPU age는 약**30.448초**로 추정된다. 이는 앞의 serial settling poll4개에서 얻은
UTC/monotonic offset 중앙값을 이용한 추정이며, exact guard 종료·fresh-until·최종 평가 clock을 직접 측정한 값은 아니다.

실패 stage는 `telemetry_signal / ValueError / validation_failed`다. 보호 trace는 값 없이 고정 문구
`snapshot query budget exceeded`로 분류했다. 완료된4회와 다섯 번째 CPU guard/부분 query를 합쳐 collection 시작5회,
Prometheus intent21/response21이다. 마지막 수집은3개 query 응답 뒤 **다음 HTTP 요청 intent 전** budget 검사에서 거부됐다.
Candidate 최대25 query 이내이며 외부 HTTP 실패나 CPU settling300초 timeout의 증거가 아니다.
`healthy_initialization_complete`는 없고 `ready_for_keda_authentication`·`runtime_preflight_passed`는 false다.

관측된 CPU sample timestamp의 증가 간격62/56/63초만으로 metrics-server 설정·export/cache·local 수집의 기여율을
확정할 수 없다. Source correctness bug는 확인하지 못해 구현 수정이나 이를 그대로 반복하는 test를 추가하지 않았다.
Freshness30초·collection30초·telemetry75초·두 advancing sample·Warning/UID invariant를 완화하지 않았다.
다음 기술 판단에는 기존 CPU/telemetry timeline을 사용하고, 새 관측이 필요하면 같은 epoch의 guard 종료·fresh-until·평가 시각을
직접 연결하는 최소 진단 또는 실제 metrics source 설정 확인을 별도 범위로 정한다. 완전한 원인 규명을 새 진입 gate로 만들거나
동일한 무근거 제18차 실행을 제안하지 않는다. Source 변경은 cost-free 영향 검증과 ChatGPT 독립 exact-head review가 필요하다.

## 종료·원복·보안

승인된 initialize≤1을 소비해 campaign을 닫았다. Operator의 campaign별 intent/lock과 source healthy ledger를 유지했고
재호출하지 않았다. 남은 횟수/allowance는 이월하지 않는다. Optional post-CPU-timeout metrics GET은 조건이 해당하지 않아 미실행이다.
KEDA UAMI/FIC/role·SA/template mutation과 apply/restore restart는0/0, fault/calibration0/measured 각0이다.
누적은 **campaign17 / public initialize14 / healthy5 / started-invalid calibration2 / measured 각0 / KEDA restart3/3**이다.

CUSTOM exact UID 제거 → shared CM UID/data guarded 원본 복원 → owned namespace 삭제 뒤 final native verify1/exit0의
**5개 CLI check**를 확인했다. Verify는 structured operation events를 생성하지 않는다.
Fixture PAT32·33 각각 재사용401/list0와 로그인 차단을 확인했고 DB records는 보존했다.
폐기 helper의 DELETE204 assertion은 있으나 실제 DELETE 응답을 별도 event로 남기지 않아 직접 기록된204를 주장하지 않는다.
Live reference0·exact digest/tag set 확인 뒤 소유 ACR image/local tag를 제거하고 부재를 재확인했다.
원래 Owner2개 보존과 임시 AKS role 제거, stable Argo/Pod UID/spec/Ready/zero-restart·Deployment/KEDA,
admin/DB Secret UID/data·CSI version과 **이번에 실제 사전 snapshot을 얻은 Bound PVC/PV UID/spec**, 고정4RG inventory를 확인했다.
**14개 cleanup check가 모두 true**다. 같은 부모가 forwarding handle을 소유했고 start1/poll683/failed poll0,
의도한 TERM/wait(-15), parent exit0과 두 owned PID 부재를 확인했다. Measured 직전 semantic probe는 미도달이다.

Operator의 quota string 비교를 숫자 비교로 고치고 string/int/invalid/equal fixtures를 확인했다.
이미 관측한 management metadata는 재사용했다. ACR tag 부재 ERROR 형식 가정으로 build 전2회 중단한 뒤
정확한 tag/manifest/repository 부재만 허용하고 auth/subscription 오류를 거부하는 fixture를 확인해 build/push는1회만 수행했다.
실제 cleanup 중 오류는 없었다. 실패 event를 삭제하거나 normal/initialize/healthy/final verify를 반복하지 않았다.

실제 operator boundary의 fake 검증2회는 named Secret matrix/empty default·generic alias/raw 차단,
Argo nesting·ACR no-tags/foreign-tag·HTTPS socket/SSL import 경로, 중간 실패 후 실제 cleanup 함수 재개와 verify/PAT 폐기 중복 방지,
initialize intent/lock·stdout/stderr/예외 보호·nested process group stop/wait를 다뤘다.
`fake_exception`2개는 의도한 fake-secret fault injection이다. 모든 kubectl 문법을 포괄하는 parser 검증은 아니다.
실제 named Secret GET은 DB 준비/admin bootstrap/각 보존검증의4회였다.

[기존 admin 회전 결과](https://github.com/imcherry5778-labs/github-capacity-cascade-platform/pull/41#issuecomment-6569049379)를
재사용했고 CSI version `712ccfb64ac7409789fa78ec2ddcf7f2`는 유지됐다. Old credential/transcript를 열거나
추가 회전·KV write·global logout/session DB mutation을 수행하지 않았다. 기존 session/output unknown은 남는다.

## 비용·기한·증거

Latest bounded cost preflight는 **08:53:39 UTC**, posted Two-RG **KRW152,794.6734891407**,
누적 planning **USD275.0294931431 / 승인 세전 review cap290**이다.
기존263.1902866455 + 이번 variable/uncertainty10 + 직전 posted 관측150,587.6256920534 대비 양수 delta/1,200으로 계산했다.
Expected5와 uncertainty/cleanup reserve5는10에 한 번만 포함했다. 기존 보존/overlap·과거 allowance를 다시 더하거나
실패 후 미사용 금액을 차감하지 않았다. 1,200KRW/USD는 planning 가정이며 환율·잔액·billing hard cap이 아니다.
Scope/rate/retention 가정에 유의미한 변화가 없어 #46에 따라 관측·모델을 재사용했으며 종료 후 비용 GET은 반복하지 않았다.
현재 P9 단독 실비·미반영 사용량/잔액은 **unknown/shared/delayed**다.

Environment **2026-11-05 10:30 KST**, Foundation/Bootstrap **11월6일00:33 KST**와
whole8045초·initialize/run/drain/rollback3065초·run/drain/rollback2220초 strict reserve를 유지했다.
새 보존·전체 teardown·merge/P10은 수행하지 않았다. 제17차는 closed이며 다음 paid campaign은 별도
exact-SHA/횟수/비용/기한 승인 범위가 필요하다. 이 결과는 새 실행 승인이 아니다.

[execution.json](execution.json), [comparison.json](comparison.json), [validation.json](validation.json),
[raw-index.json](raw-index.json), [sanitized raw archive](raw-evidence.tar.gz)에 범위와 한계를 연결한다.
Archive43개 member의 path/size/SHA256을 재검증하고 과거16개 archive byte/hash를 보존했다.
현재 실제 password/PAT·관측된 Azure/ACR token과 encoding scan matches0, private path0이다.
Secret object/value·kubeconfig·private trace/stdout/stderr/account output·operator program은 공개하지 않았다.
Scan은 과거 노출을 취소하거나 session containment를 입증하지 않는다. 소유 RAM/보호 evidence 파일556개를 제거했다. 수량은 validation에,
final exact evidence HEAD CI는 기존 PR 결과 comment에 기록한다. Global Azure CLI cache·무관한 image cache는 보존하며 물리적 secure erasure나
전체 Environment zero residual은 주장하지 않는다.
