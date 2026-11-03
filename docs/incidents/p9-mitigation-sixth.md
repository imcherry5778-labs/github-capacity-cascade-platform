# P9 제6차 실행 — HAProxy startup restart guard 중단

상태: **valid normal 통과 / initialization Pod guard 실패 / P9-owned 원복 완료 / P9 acceptance 미충족**.
[실행·raw/checksum·원복](../evidence/p9-mitigation-sixth-20261029/README.md)을 authority로 사용한다.
승인·실제 execution source는 `30271ea59c4824b9bf4455ec038528891692d434`이며 실행 중 source 수정은 없다.

5차의 phase/tool provenance 오류는 교정했다. 첫 external mutation 전 warmup을 허용값과 대조했고,
repository kubectl v1.36.4의 실제 selected path/hash를 확인했다. Fresh context의 실제 normal create1회,
operations9/attempts9를 기존 validator가 valid/success/warmup으로 확인했다.

Initialize1회는29.468초에 `readiness_resource_guard / InitializationGuardError / pod_not_ready_or_restarted`로 중단했다.
Initial snapshot에서 이미 HAProxy Pod는 Ready=True지만 restart3/last termination Error였다.
Previous container log는 backend DNS 주소 해석 실패와 worker exit1을 보존한다.
Operator가 HAProxy Deployment를 backend Service보다 먼저 순차 생성한 순서와 부합한다.
정확한 첫 DNS query/propagation latency와 failing guard 전체 payload는 미기록이며 이를 소급 합성하지 않는다.
Source의 무재시작 guard 거부는 타당하다. Ready만 확인한 operator 준비는 충분하지 않았다.

CPU poll0·준비 완료 없음, healthy journey/fault/calibration/C0–C3 measured0, freeze 없음이다.
CPU300초/initialize840초 계약의 timeout 또는 metric feasibility 결과로 해석하지 않는다.
HAProxy Pod 교체/history reset, initialize 재실행, acceptance 완화는 하지 않았다.

CUSTOM 우선 제거→shared UID/data guard 원복→소유 namespace/Secret/controllers 제거 후 final native verify1을 확인했다.
PAT17 DELETE204/0 bytes·401/list0·login 차단, image/tag/local tag 제거와 live references0을 기록했다.
AKS CLI delete timeout 후 남은 exact owned role을 ARM DELETE하고 GET not-found·원래 role ID 집합을 확인했다.
Stable/KEDA/Secret/storage/node/ingress·Environment ID 집합과 Disk10GiB를 보존하고 보호 local credential 사본을 제거했다.
준비/원복 누적6회, 과거 KEDA restart 각1회와 비용 이력을 유지한다. P9 incremental actual은 unknown이다.

Corrective action은 기존 Service/config를 HAProxy Deployment보다 먼저 준비하고 기존 Ready+restart0 조건을
함께 확인하는 operator 실행 순서 교정이다. 이번 결과에 source-only 수정이나 별도 Task를 추가하지 않는다.
현재 invalid preparation/negative를 보존하고 다음 별도 승인 전 workload를 자동 재실행하지 않는다.
Resource/cost/retention/rollback 상한은 그대로이며 Draft 유지, merge/P10 없음이다.
