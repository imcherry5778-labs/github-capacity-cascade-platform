# P9 승인 재개: healthy initialization 준비 gate 중단

상태: 안전 원복/소유 cleanup 완료, **P9 acceptance 미충족**.
[실행·negative·checksum](../evidence/p9-mitigation-resume-20261029/README.md)을 authority로 사용한다.
실행 source는 `9c7b4be942e534dff2e36fe069e144bfa96d045a`이며 후속 docs/evidence HEAD와 구분한다.

## 관측된 영향과 대응

정상 native HTTPS journey create1/9 attempts 성공 후 P9 namespace3 Pods·shared mesh/CUSTOM policy를 준비했다.
새 source의 `initialize`1회가 약39.79초 뒤 exit1로 종료했다. Journey intent 이전이므로 healthy journey0,
fault0, calibration0, measured 각0, freeze·mitigation/recovery 결과 없음이다.
Mandatory gate 실패를 성공으로 처리하거나 workload를 반복하지 않았다.

CUSTOM policy를 우선 제거하고 원본 shared ConfigMap을 복구했다. KEDA는 변경하지 않았고 원래 SA/spec/Ready2를 확인했다.
소유 namespace/Secret/image/임시 AKS role과 보호된 local 사본을 정리했으며 새 PAT ID13의 DELETE204·PAT401·login 차단을 확인했다.
기존 stable Argo/spec/Secret/storage/nodes와 승인 retention은 보존했다.

## 원인과 증거의 한계

**Causal exception은 unknown**이다. Source CLI는 generic 오류와 `healthy_initialization_failure`만 기록했고 stage/type/traceback은 노출하지 않았다.
실행 window 안의 HPA `FailedGetContainerResourceMetric`/`FailedComputeMetricsReplicas`는 실제 관측이다.
Warning safety gate 또는30초 snapshot budget이 관련됐을 가능성은 있으나 어느 것도 causal proof가 아니다.
중단 후 target mapping/bootstrap의 offline 대조는 통과했고 inbound stat/series는 pre-traffic 상태에서 없었다.
이를 새로운 label mismatch, admin-stat defect 또는 recovery 실패로 단정하지 않는다.

## Corrective action — 아직 검증하지 않음

- 같은 PR에서 non-secret failure stage/type 및 보호된 causal exception/duration 보존 경계를 검토한다.
- 보존된 warning·metric·command timing과 strict initialization 순서를 먼저 대조한다. 실제 원인을 확인하기 전 timeout/acceptance를 확대하지 않는다.
- 실제 healthy positive path/target telemetry가 확보된 뒤에만 KEDA identity/operator와 scaler auth로 진행한다.
- Source가 바뀌면 새 exact-head source gate와 필요한 통합 실행 판단을 따른다. 과거 승인 SHA/flags·삭제된 identity를 치환하지 않는다.

이 action은 제안/미검증이다. Backoff/admission/proxy-scaling 효과는 measured하지 않았으며,
부하 감소나 관측 없는 window를 recovered 또는 non-recovered 결과로 만들지 않는다.
