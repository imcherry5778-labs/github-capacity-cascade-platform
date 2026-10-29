# P9 제3차 실행: readiness/resource warning guard 중단

상태: **P9-owned 원복/cleanup 완료, P9 acceptance 미충족**.
[실행·negative·checksum](../evidence/p9-mitigation-third-20261029/README.md)과
[과거 unknown incident](p9-mitigation-resume.md)를 구분한다.
실행 source는 `ffea5cb865728af54554c91460e3b96364d955fb`이며 후속 docs HEAD는 실행 승인 source가 아니다.

정상 native journey create1/attempt9 성공, Ready Pod3의 실제 resource cap 확인 뒤 initialize1회가 실패했다.
새 diagnostic은 `readiness_resource_guard / InitializationGuardError / warning_event`,
전체 healthy_initialize18.56초/실패 stage5.01초를 보존했다. Private traceback의 source frame도 이 failure와 일치했다.
이번 직접 실패 지점은 확인됐지만 HPA metric 부재의 더 깊은 원인은 미확정이다.
동일 window의 05:56:23 UTC HPA FailedGetContainerResourceMetric/FailedComputeMetricsReplicas 경고를 보존했다.
반환된 guard event 목록 자체는 저장되지 않았으므로 정확한 집합을 확정하지 않는다.
과거 두 번째 initialize의 원인은 여전히 unknown이며 이번 관측을 소급 적용하지 않는다.

Healthy journey intent가 없고 fault/calibration/각 measured arm0, freeze 없음이다.
Warning/timeout 조건을 완화하거나 workload를 반복하지 않았다. Recovery observation window 자체가 없으므로
non-recovery 측정 결과로 해석하지 않는다.

CUSTOM 우선 제거, 원본 shared ConfigMap 복구, KEDA 원래 UID/spec/SA·Ready2 확인 후 소유 namespace/Secret/controllers,
image·PAT ID14·임시 AKS role과 보호 local 사본을 정리했다. Stable 자원과 retention은 보존했다.
첫 CUSTOM delete의 출력 옵션 오류는 즉시 수정했으며 error와 실제 제거 기록을 모두 보존했다.
원복 뒤 정상 fixture verify1과 PAT DELETE204/401·login 차단을 확인했다.

후속 corrective action은 **미검증 제안**이다. 보존된 HPA events·resource metric snapshot 및 정상 준비 시간대를 먼저 대조하고,
실제 metrics availability/초기화 gate 순서와 warning 발생 이유를 독립 검토한다. 필요하면 다음 source gate에서
안전한 guard event reason/timestamp publication 경계를 정하되 원문 payload나 credential을 공개하지 않는다.
Warning 제외·snapshot budget 확대·미확인 flag 승격·acceptance 사후 완화는 해결책으로 사용하지 않는다.
새 source/실행 범위 판단과 별도 승인 전 추가 Azure workload는 없다. Backoff/admission/scaling 효과는 아직 검증되지 않았다.
