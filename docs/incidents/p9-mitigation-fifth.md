# P9 제5차 실행 — operator normal phase 설정 오류

상태: **normal gate invalid / P9-owned cleanup 완료 / P9 acceptance 미충족**.
[실행·raw/checksum·비용·원복](../evidence/p9-mitigation-fifth-20261029/README.md)을 authority로 사용한다.
승인·실제 execution source는 `50aac4a9fab0881dfba41340f4a6ef0f5c4e0142`이며 실행 중 source 변경은 없다.

Operator가 native normal create invocation에 `RESULT_PHASE=baseline`을 잘못 지정했다.
Create exit0 및 developer operation/attempt9개 성공과 별개로, structured validator는 허용 phase가
`warmup`/`measured`이므로 `ValueError: invalid phase`를 반환했다. 직접 원인은 **operator 설정 오류**다.
Raw의 script-reported `validity=valid`를 validator PASS로 사용하지 않았고 phase도 수정하지 않았다.
Normal create를 반복하거나 승인 flag를 승격하지 않았다.

Initialize/CPU settling/healthy journey/fault/calibration/C0–C3 measured는 모두0이다.
Namespace/CUSTOM/shared overlay/experiment Secret과 KEDA 변경 전 중단했으므로
이번 결과로 CPU300초 계약의 feasibility, HPA 회복, KEDA 인증 또는 mitigation/recovery를 판단할 수 없다.

같은 fixture final native verify1/exit0 뒤 PAT16 DELETE204/0 bytes·PAT401/list0·login 차단/Basic401을 확인했다.
소유 image/digest/tag/local tag와 임시 AKS role을 제거하고 원래 resource/role ID 집합을 확인했다.
Shared/KEDA/stable/Secret/storage/node baseline과 기존 Environment를 보존했으며 보호 credential 사본도 제거했다.
준비/원복 누적5회와 과거 KEDA restart 각1회, latest aggregate KRW34,327.6634214082를 보존한다.
P9 incremental actual은 unknown이며 same before/final cost를 비용0으로 바꾸지 않는다.

Corrective action은 다음 별도 승인 실행의 operator 정상 경로 phase를 `warmup`으로 지정하고
같은 validator의 허용 값과 invocation metadata를 HTTP side effect 전에 대조하는 것이다.
이번 실행에서 승인 implementation을 바꿀 source 근거는 없으며 별도 controller/service/Task를 만들지 않는다.
이번 raw/negative를 유지하고 재승인 전 native create/healthy/calibration/measured를 자동 재실행하지 않는다.
Environment 보존 기한과 resource/cost/rollback 상한은 그대로다. Draft 유지, merge/P10 없음.
