# P9 제7차 실행 — CPU Warning 발생90초 경계 중단

상태: **valid normal·무재시작 Pod 준비 통과 / CPU preparation 실패 / P9-owned 원복 완료 / P9 acceptance 미충족**.
[실행·raw/checksum·원복](../evidence/p9-mitigation-seventh-20261029/README.md)을 authority로 사용한다.
승인·실제 execution source는 `1ce291523ecddb3918e3879f322e45dfca122ee6`이며 runtime source 수정은 없다.

6차 ordering 오류를 교정해 ConfigMaps와 backend Service/ClusterIP/selector·Ready endpoint를 선행 확인한 뒤 HAProxy를 생성했다.
Initial HAProxy·target·DB의 Ready/Running·restart0·last termination null과 admitted cap을 확인했다.
Warmup·실제 kubectl v1.36.4 path/hash 사전 대조, fresh context와 normal create1회의 valid/success 9 operations/attempts도 유지했다.

Initialize1회는 외부57.649초/initializer52.966초에
`readiness_resource_guard / ValueError / validation_failed`로 중단했다.
보호 exception chain의 원인은 `CPU warning outside startup lifetime`이다.
CPU HPA exact owner Warning의 count3→5, 마지막 발생 `12:27:43 UTC`는 Pod 생성 `12:26:12` 후91초,
HPA 생성 `12:26:13` 후90초였다. Source의 양쪽 생성 기준 발생 허용90초 중 Pod 경계를 넘었다.
Retained history의 현재 age나 settling300초/outer840초 timeout 때문에 중단한 것으로 재해석하지 않는다.

CPU poll1은 pending이었고 두 advancing valid sample/quiet proof는 없다.
Healthy journey intent/실행·KEDA 변경·fault·calibration·C0–C3 measured는0, freeze 없음이다.
Post-stop HPA transition `12:28:43`과 이후 CPU sample은 실패한 initialization을 성공으로 바꾸지 않는다.
Warning 삭제·은폐·history reset·guard 완화·initialize 자동 재실행은 없다.

CUSTOM 우선 제거→shared UID/data test 원복→소유 namespace/controller/Secret 제거,
final native verify1→PAT18 DELETE204/0 bytes·401/list0·login 차단,
image live refs0/exact delete, role exact ARM DELETE/GET not-found·원래 assignment 보존을 확인했다.
Stable Forgejo/Argo/Secret/storage/node/ingress·Environment ID와 KEDA unchanged/Ready2를 대조하고 보호 local 사본을 제거했다.
준비/원복 누적7회, 과거 KEDA restart 각1회와 비용 이력을 보존한다.
Before/final two-RG ActualCost KRW38,284.28956189241, P9 incremental actual unknown이다.

이번 실제 Warning 발생 timeline과 기존90초 계약의 독립 검토가 다음 실행 판단의 입력이다.
추가 source-only 작업이나 paid replay를 자동 시작하지 않는다. 새 exact-source 통합 승인 전 workload 중단을 유지한다.
Resource/cost/retention/rollback 경계는 그대로이며 Draft 유지, merge/P10 없음이다.
