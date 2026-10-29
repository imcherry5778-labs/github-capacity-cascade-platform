# P9 제4차 실행 — CPU startup lifetime 검증 중단

상태: P9-owned 원복/cleanup 완료, **P9 acceptance 미충족**.
[실행·raw/checksum](../evidence/p9-mitigation-fourth-20261029/README.md)을 authority로 사용한다.
실제 execution/approval source는 `b484160cc0bf13af93d234a5ba30c4013f1d8e00`이며 후속 source/docs HEAD와 구분한다.

Native normal create1/attempt9, Ready Pod3의 cap 확인 뒤 initialize1회가 실패했다.
직접 error는 `readiness_resource_guard / ValueError / validation_failed`, protected source traceback의
`CPU warning outside startup lifetime`이다. Healthy_initialize87.14초/guard stage72.45초, command92.26초를 보존했다.
Pod/HPA 생성07:39:10 UTC·Ready07:39:26 UTC와 실패 시각07:41:00 UTC를 대조했다.
이는 source의 생성 age90초 경계이며 전체 settling90초 clock과 구분한다. Timeout 증액/Warning 제외/재시도는 없다.

두 emitted CPU poll은 모두 pre-Ready window·미advance sample·HPA False/currentMetrics 미확보로 pending이었다.
중단 후 읽은 HPA status는 ScalingActive=True, transition07:40:40 UTC, app/cpu currentMetrics2%/1m을 보고한다.
이 later-read status를 실패한 guard의 전체 payload나 완료된 positive gate로 승격하지 않는다.
CPU preparation completion·healthy journey intent·fault·calibration·각 measured arm은0이며 recovery window도 없다.
Underlying metrics 지연 원인과 과거 두 번째 실행 원인은 unknown으로 유지한다.

CUSTOM을 우선 제거하고 원본 shared CM을 복구했다. KEDA 변경 없이 원래 UID/spec/SA·Ready2 확인 후
소유 namespace/Secret/controllers·image·임시 AKS role·PAT ID15 및 보호 local 사본을 정리했다.
원복 뒤 native normal verify1, PAT DELETE204/401·login 차단과 stable Argo/Secret/storage/node 보존을 확인했다.
Before/final aggregate KRW26,885.8891798273 동일 값은 비용0을 뜻하지 않으며 P9 incremental actual은 unknown이다.

## Cleanup 이후 cost-free source correction

Terminal PodMetrics의 실제 window `1m5.166s`는 승인 source의 초 전용 parser에서 거부된다.
보존된 window를 synthetic healthy CPU/HPA wrapper에 넣어 수정 전 `invalid CPU sample window`를 직접 재현했다.
같은 branch/PR에서 minute+seconds 표현을65.166초로 해석하는 최소 수정만 했다. Equivalent seconds, pre-Ready pending,
>90초·zero·unknown 거부 회귀를 유지하며 lifetime90초/snapshot30초/command15초·warning history·quiet/advancing sample 경계는 바꾸지 않았다.
실행 source bytes는 실행 동안 B484와 같았고 이 parser 수정 뒤 Azure workload/image/IAM을 다시 실행하지 않았다.
직접 P9 52개/P8 38개와 `make static`을 통과했다. Synthetic duration 회귀의 positive는 runtime success가 아니다.

다음 corrective action은 생성 lifetime·initialize settling clock·실제 metric cadence가 완료 proof를 만들 수 있는지
보존된 timing과 post-stop status로 검토하는 것이다. Source/contract 보정은 독립 gate와 새 승인 대상으로 남기며
한도를 사후 늘리거나 post-stop sample을 성공으로 사용하지 않는다. P9 mitigation/scaling/recovery 효과는 미측정이다.

## 후속 source-only 시간 계약 보정

같은 PR에서 Warning의 first/last 발생 시각을 Pod/HPA 생성 후90초 안으로 검증하고,
현재 poll의 객체 age90초와 분리했다. UID/owner/reason·first timestamp·count/time history를 보존하며
늦은 활성 Warning, history drift/유실, 첫 positive 이후 재발은 중단한다.
CPU settling은 별도 monotonic300초 hard cap이며 positive 확보 즉시 완료한다.
Window90초/freshness30초·snapshot30초/command15초·quiet15초·두 advancing valid samples는 유지한다.
`initialize`의 외부 process group timeout도 전체 단계 예산으로 정합화했다.
현재 cadence840초(+kill5초)는 setup330/settling300/baseline30/journey100/telemetry75/dispatch5의 합이며
measured run600초와 별개다. Preparation retention 검사에 이 예산과 기존 rollback reserve를 포함한다.

4차 archive의 실제 Pod/HPA/Warning/CPU 구조를 기존 P8 guard→P9 경계로 replay한 cost-free 회귀에서
생성 age90/110초의 pending, post-stop 자료를 조합한 첫 positive만으로는 미완료,
약65초 cadence 뒤 **synthetic** advancing sample에서만 완료됨을 검사한다.
Collection 비용을 포함한 initialize 통합 회귀도300초 timeout과 조기 완료를 구분한다.
이는 Azure recovery proof가 아니며 healthy journey·calibration·C0–C3 measured는 여전히0이다.
과거 실행 source/승인·raw/checksum·네 차례 준비/원복 비용·횟수는 변경하지 않았다.
새 exact-head CI/독립 review와 별도 통합 승인 뒤에만 실제 CPU/HPA/healthy telemetry·KEDA auth 및
calibration/freeze/C0–C3 continuing-demand/recovery·안전 원복을 연속 진행할 수 있다.

직접 P9 56개/P8 38개 및 `make static` PASS. 기존 positive shared-path·C3·release/recovery·P8 strict 회귀를 포함한다.
GNU timeout의 cost-free process-group smoke에서 exit124와 descendant TERM 수신을 확인했다.
이 source 검증은 위 실제 Azure 실행 source `b484160...`의 runtime evidence와 별개다.
