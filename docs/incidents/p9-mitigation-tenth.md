# P9 제10차 — actual positive 이후 C3 calibration configuration 중단

상태: **CPU/HPA·healthy·KEDA actual positive / calibration1 invalid / measured0 / P9-owned 원복 완료 / P9 acceptance 미충족**.
[실행·raw/checksum·원복](../evidence/p9-mitigation-tenth-20261101/README.md)을 authority로 사용한다.
Actual execution source는 `d23e1629d0206db914088a54c6378d17237b67c8`이며 source 변경은 없다.

제10차에 승인된 dry-run → shared mesh → target live admission → backend endpoint → HAProxy → HPA/PodMonitor/CUSTOM
순서를 지켰고 operator-only Warning gate를 만들지 않았다. Initial Pod3 Ready/restart0, requests400m/512Mi·limits900m/1024Mi다.
Normal1 valid/success/warmup9를 확인한 뒤 public initialize1이240.244508초/exit0으로 완료됐다.
실제 poll4 fresh candidate → poll5 동일 stale pending → poll6 advancing fresh ready,
journey 후 poll7 stale pending → poll8 fresh CPU/HPA+target telemetry final completion을 관측했다.
Healthy journey1의 same-window ingress/check/target30개와 native auth·TLS·correlation·native stats·Prometheus를 확인했다.
Synthetic/no-data zero 변환은 없다.

Healthy completion 뒤 전용 UAMI/FIC/AMW 단일 scope role·SA annotation과 operator apply restart1을 수행했다.
실제 scaler Ready/HPA currentMetrics와 정확한 owner UID를 확인했으며 scale-out 성공으로 승격하지 않았다.
Operator preflight assertion은 전체 P9 C3 configuration proof와 구분한다. 이 preflight는 C3 ScaledObject exact-spec equality를 실행하지 않았다.

C3 calibration1은 ledger 계수 뒤22.081829초/exit1로 중단했다. Configuration/run_start/snapshot/offered-arrival artifact가 없다.
Generic CLI failure만 있어 직접 exception은 unknown이다. Actual admitted spec에는 source render에 없는
`advanced.scalingModifiers: {}`가 있고 이 field를 제외하면 나머지는 일치한다. 생성 응답에도 같은 빈 object가 있다.
Source exact-spec equality가 false라는 계약 충돌은 확인했으나 이것을 직접 exception trace로 주장하지 않는다.
Calibration1 invalid를 사용 횟수에 포함하고 후속 workload를 중단했다. Freeze 없음, C0–C3 각각0, recovery not measured다.

CUSTOM 우선 제거/shared guarded restore, scaler/HPA 제거, KEDA SA/template 복구와 restore rollout1/Ready2,
namespace 삭제·native final verify1·PAT21/22 revoke/login block·port-forward 종료·workspace role/FIC/UAMI/image/temp IAM 정리를 확인했다.
Stable 보존22항목을 확인하고 보호 사본을 삭제했다. 과거9개 archive와 누적 비용을 보존하며 준비/원복 누적10회,
KEDA apply/restore 누적 각2회다. Before/final two-RG ActualCost KRW104,099.2492616492, P9 incremental unknown이다.
기존 USD100 검토 총액 안의 위험 검토만 수행했고 추가 USD100 배정/retention 연장/전체 teardown은 없다.
현재 source로 자동 재실행하지 않으며 구현 변경·merge/P10 없이 같은 Draft PR에 negative를 보존한다.
