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

## 후속 source-only 진단 보완

과거 raw/checksum·approval/execution SHA는 그대로 보존했다. 이번 수정은 stage/type/timing을 남기는 경계를 복구하며
**위 실행의 root cause는 여전히 unknown**이다. Archive의 HPA warning lastTimestamp는 02:43:27/02:44:27 UTC이며
P8 guard는 runtime `since` 이후 Warning을 검사한다. 실패한 호출의 `since`/stage별 timing/causal exception이 없으므로
해당 event가 guard에서 반환됐는지, 30초 snapshot budget이 먼저 소진됐는지 판정할 수 없다.
전체 invocation 약39.79초도 Runtime 생성 이후 collection 시간과 같다고 가정하지 않는다.
Warning 필터와 30초 collection/명령별 최대15초 timeout은 변경하지 않았다.

`healthy_initialize` 실패는 configuration·readiness/resource·baseline stats/logs 및 이후 단계별 stage와
전체/단계 elapsed, 제한된 exception class/error code를 append-only로 기록한다.
오류 message/argv/stderr/body/보호 local path는 공개하지 않는다. 상세 traceback은 protected mode0600 파일로 분리하고,
쓰기 실패도 원래 예외를 삼키거나 기존 진단 파일을 덮어쓰지 않는다.
Mocked configuration 실패, archived reason/timestamp를 사용한 synthetic warning guard, 실제 Runtime.k의 mocked command
timeout/failure 및 budget 소진, baseline stats/log 실패가 서로 구분되는 것을 cost-free 회귀로 검사한다.
모든 pre-journey 실패는 journey 미실행, completion 부재와 runtime-preflight false를 유지하며 positive-path/C3/release 회귀도 보존한다.
이는 source 진단 동작의 검증이며 Azure causal proof나 backoff/admission/scaling corrective action 검증이 아니다.
직접 P9 46개/P8 38개 및 `make static`을 통과했다. 동일 mocked configuration 실패를 이전 `bf62aae`와 대조하면
이전 failure record에는 stage/type/code가 없고 수정본에는 `configuration`/`ValueError`/`validation_failed`가 남는다.
Calibration·각 measured arm0 기록과 기존 archive SHA256은 보존했으며 새 Azure 접근·workload·mutation은 없다.

새 exact-head source gate 이후 별도 유료 재개 승인에는 fresh IAM/image/credential/shared configuration 재준비,
healthy initialization과 남은 KEDA·calibration/freeze/C0–C3 및 원복 범위를 함께 연결해야 한다.
기존 source 승인/삭제된 identity/flags를 재사용하지 않으며 누적 비용·횟수·retention과 acceptance를 확대하지 않는다.
