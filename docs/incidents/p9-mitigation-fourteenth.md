# P9 제14차 calibration direct sentinel/monitor 중단

승인 source `69bace6cdb3dabe047a71454528c27111f706c05`의 단일 campaign에서 normal1,
public initialize1·healthy journey1, 실제 fresh CPU/HPA+target telemetry, KEDA scaler 인증·단일 owner와
full C3 configuration/snapshot preflight를 통과했다. 준비는 DB `verify-full`과 target-stage live headroom 선행을 지켰다.

그 뒤 C3 calibration1은 첫 snapshot 뒤 direct sentinel15회 모두 transport error였고
`monitor_failure`/`run_failure`로 중단됐다. 직접 traceback의 최종 exception은
`ValueError: direct native-auth sentinel preflight`다. Preflight에서200이었던 전용 forwarding process의
PID가 중단 후 없었다. Operator forwarding lifecycle 문제이며 소멸 원인은 미기록이다.
별도 monitor exception은 unknown이고 Azure/source 원인으로 단정하지 않는다.

Public demand 발행0, calibration invalid다. Saved validator도 거부했다.
Freeze·C0–C3 measured·continuing-demand recovery는 미도달이며 valid-negative 성과나 recovery 측정 결과가 없다.
추가 calibration/run·source 변경 없이 downstream을 중단했다.

CUSTOM/shared mesh·KEDA SA/deployment·IAM/FIC/UAMI·namespace·PAT27/28·image·임시 AKS role·보호 사본을 정리했다.
Native namespace CA/CRL CM ownership guard의 차단/확인/계속 과정도 보존했다.
Stable/owned33개 check와 final native verify1/exit0을 확인했고 stable Azure Environment는 P11 재사용을 위해 보존했다.

전후 posted ActualCost는 KRW130,403.0455542038이며 P9 실비는 shared/delayed/unknown이다.
기존 USD180 review envelope와 retention을 유지했고 자동 제15차·merge/P10은 없다.
실제 시각·source/image/plan hash·raw·비용·원복은
[제14차 evidence](../evidence/p9-mitigation-fourteenth-20261102/README.md)에 있다.
P9 acceptance는 미충족이다.
