# P9 제8차 실행 — CPU 준비 미완료와300초 collection timeout

상태: **normal valid·무재시작 Pod 준비 통과 / CPU ready0 / P9-owned 원복 완료 / P9 acceptance 미충족**.
[실행·raw/checksum·원복](../evidence/p9-mitigation-eighth-20261030/README.md)을 authority로 사용한다.
승인·실제 execution source는 `98e95e5850f2442e08a6306bf955aa12c0427b17`이며 source 수정은 없다.
격리 checkout을 같은 branch/PR로 복원했고 warmup·actual kubectl v1.36.4 path/hash·fresh context,
Service/ConfigMap·Ready endpoint 선행 및 initial Pod3 Ready/restart0을 확인했다.

Startup metric Warning은 Pod/HPA+121초 count8까지 이력을 유지하며 허용됐고 첫 fresh 관측 이후 변화가 없었다.
제7차 Warning90초 cutoff는 재발하지 않았다. Fresh CPU/HPA positive는 실제 poll3·5에 있었지만,
그 사이 poll4와 이후 poll6–9가 stale 판정이어서 source ready는0이었다.
Non-positive poll에서 candidate를 해제하는 source와 부합한다는 추론이며 candidate/full guard 자체는 미기록이다.
실제 metric 생성 주기·지연 원인·AKS flags는 unknown이다. 두 fresh 관측의 존재와 source의 준비 완료 실패를 구분한다.

Initialize1회는 외부305.507초/initializer300.004초에
`readiness_resource_guard / TimeoutExpired / command_timeout`으로 중단했다.
실제 stack은 반복 내부 configuration의 ingress Envoy route config 수집이며 남은 command budget은0.272423409초였다.
Public stage label은 반복 내부 configuration도 포함한다. 외부840초 timeout이나 Warning 재발로 원인을 바꾸지 않는다.
CPU poll9 모두 pending, healthy journey/KEDA/fault/calibration/C0–C3 measured0, freeze 없음, recovery not measured다.
Source/시간 제한/acceptance 변경, synthetic 입력, Pod history reset이나 자동 재실행은 없다.

CUSTOM 우선 제거→shared UID/data test 원복→소유 namespace/controller/Secret 제거,
final native verify1→PAT19 DELETE204/0 bytes·401/list0·login 차단,
image refs0/exact delete, role exact ARM DELETE/GET not-found·원래 assignment 보존을 확인했다.
Stable Forgejo/Argo/Secret/storage/node/ingress·Environment ID와 KEDA unchanged/Ready2를 대조하고 보호 local 사본을 제거했다.
준비/원복 누적8회·historical KEDA restart 각1회·과거7개 archive와 비용 이력을 유지한다.
Before/final two-RG ActualCost KRW44,295.3701043718, P9 incremental actual unknown이다.
현재 source에 추가 paid replay를 하지 않는다. 다음 판단은 이번 timeline의 독립 review와 새 exact-source 승인 대상이다.
Resource/cost/retention/rollback 경계는 그대로이며 Draft 유지, merge/P10 없음이다.
