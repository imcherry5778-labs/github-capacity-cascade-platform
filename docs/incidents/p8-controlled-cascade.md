# P8 controlled cascade — 초기 incident record

상태: **계획 / source 준비, Azure 실행 미승인**. 실제 incident를 재현했다고 주장하지 않는다.
분류: `LAB_IMPLEMENTATION`. Historical GitHub incident topology의 복제 주장이 아니다.

## 조사 질문

Verified HTTPS와 Forgejo native auth를 유지한 private Issue read 및 HTTPS Git read가
mandatory shared check의 inbound Envoy active-request capacity 포화에 의해 실패하는가?
같은 상위 demand에서 client max_attempts만 1→2로 바꾸면 attempts/check workload가 증가하는가?
정상 app-container CPU HPA가 replica/metric/scheduling 여유를 가진 상태에서도 proxy-side pressure와 다른 signal을 보이는가?

## 기존 evidence와 동결 기준

P7 [45-operation baseline 및 초기 SLO](../evidence/p7-operations-20261028/initial-slo.json)를 유지한다.
Source/실행 순서는 [P8 runbook](../p8-controlled-cascade.md),
실행 전 관리 API 관측은 [management delta](../evidence/p8-controlled-cascade-20261029/management-delta.json)다.
P4 후보를 Azure 검증값으로 취급하지 않는다. Calibration과 confounder guard 후에만 source/runtime/config/demand를 동결한다.

## 현재 판정

- Developer impact: **not measured**
- Failure mechanism/rejection mapping: **not verified on Azure target**
- CPU-HPA signal mismatch: **not measured**
- Retry amplification: **not measured**
- Confounder guard: **runtime not verified**
- Restoration / 정상 journey 복귀: **not executed**
- Hypothesis: **inconclusive**

## 실행 뒤 같은 PR에서 보완할 record

Exact execution SHA, stable deployed revision, actual proxy build/image digest/Pod UID/config/stat mapping을 연결한다.
각 calibration/paired run의 UTC window, logical operations/attempts/dispatched/admitted/active/rejection,
Issue success/command latency SLO, Git read 영향과 direct sentinel을 기록한다.
HAProxy/Forgejo/sidecar/PostgreSQL/node 관측과 경쟁 가설을 함께 제시한다.
Negative/invalid run과 valid hypothesis support를 구분하고 원복·credential/IAM/resource cleanup 확인을 덧붙인다.
P9 mitigation/recovery나 P10 isolation 결과는 포함하지 않는다.
