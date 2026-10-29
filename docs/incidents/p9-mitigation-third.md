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

## 후속 source-only CPU preparation 보정

제3차 archive의 Ready05:55:54 UTC, CPU timestamp05:56:18 UTC/window38.03202016초,
HPA warning05:55:53/05:56:23 UTC를 직접 회귀에 재사용했다. CPU window 시작은 약05:55:40 UTC로 Ready 이전이다.
[Kubernetes v1.36 HPA 설명](https://v1-36.docs.kubernetes.io/docs/concepts/workloads/autoscaling/horizontal-pod-autoscale/#pod-readiness-and-autoscaling-metrics)은
startup CPU sample의 Ready 구간 유효성을 구분한다. 이번 timeline은 그 문제와 일치하는 inference이며
실제 HPA 회복이나 metrics-server root cause 증거가 아니다. 기존 raw/checksum·실행 source·승인은 변경하지 않았다.

같은 CPU HPA startup warning이 이력에 남아도 실제 positive 회복을 확인하면 준비를 진행할 수 있도록
[최초 healthy 초기화 contract](../p9-mitigation-recovery.md#최초-healthy-초기화-순서)를 최소 보정했다.
새 resource/Pod/HPA를 만들거나 traffic을 추가하지 않는다. Read-only settling≤90초, 기존 snapshot30초/command15초를 유지하고
정확한 owner/UID·CPU sample Ready window/freshness·ScalingActive/currentMetrics·quiet/advancing observations로 회복을 확인한다.
Startup warning은 reason/time/owner/UID/count와 함께 남기고, 회복 뒤 재발·다른 warning·Pod/DB/node/resource 문제는 계속 실패한다.

Archived payload는 pending으로 남으며 synthetic valid CPU/HPA 후속 payload만 positive다. 실제 collection adapter의 owner/time/count
수집과 P8 default shape, healthy_initialize의 준비→journey→후속 strict 검사를 직접 회귀로 연결했다.
Ready-window 회귀의 guard 시각은 해당 window 문제를 분리하는 synthetic 시각이며, 실제 더 늦은 stop export에서의 freshness를 주장하지 않는다.
직접 P9 50개/P8 38개 및 `make static`을 통과했고 같은 retained-warning/positive-HPA mocked 입력을 이전 source와 대조했다.
이전 source는 `warning_event`로 journey0, 수정본은 bounded quiet/advancing sample 확인 뒤 synthetic journey1을 완료했다.
P9 positive shared path/correlation·C3 warmup·release invariant를 보존한다. 실제 HPA/target telemetry/KEDA gate는 아직 미통과다.
새 source gate 이후 별도 Azure 통합 재승인에는 read-only settling 순서와 fresh IAM/image/credential/shared configuration 재준비,
필요한 KEDA 변경/원복·calibration/measured 범위 및 기존3회 준비/cleanup·비용 unknown을 함께 연결해야 한다.
기존 승인 SHA/flags/삭제된 identity를 재사용하거나 비용·횟수·resource/retention·recovery acceptance를 확대하지 않는다.
