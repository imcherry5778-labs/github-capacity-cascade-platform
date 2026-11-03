# P9 제9차 — initialize 전 operator Warning 검사 범위 오류

상태: **normal valid / source initialize0 / 운영 중단 / P9-owned 원복 완료 / P9 acceptance 미충족**.
[실행·raw/checksum·원복 evidence](../evidence/p9-mitigation-ninth-20261030/README.md)를 authority로 사용한다.
실제 preparation source는 `ee75e3a336326ec5567b5f399ec08028169b02f1`이며 구현 수정은 없다.

Operator가 public initialize 전에 namespace의 전체 retained Warning을 거부하는 검사를 추가했다.
Target의 startup/readiness Unhealthy count2/2는 Ready보다12초/10초 이전에 끝났고,
HAProxy readiness Unhealthy count1은 Ready와 같은 초였다(subsecond 순서 unknown).
Initial/post-stop Pod3 모두 Ready/restart0/lastState empty이며 Warning history/count/time은 보존됐다.
Source는 ordinary Warning에 `Runtime.since`를 적용하고 CPU HPA history를 별도로 보존한다.
추가 검사는 이 시간 범위를 따르지 않았다. **Source CPUStartup/initialize가 실패한 것으로 분류하지 않는다.**
최초 raw의 `mandatory_gate` 표기는 보존하고 별도 operator interpretation에 정정했다.

별도 준비 순서 이탈도 있었다. Shared mesh를 actual target admission 전에 dry-run/headroom 근거로 적용했다.
Actual admission은 HPA/PodMonitor/CUSTOM 전에 확인했지만 승인된 shared mesh 순서 전체를 지킨 proof가 아니다.
Shared 설정은 원래 UID/data로 복구했다. 승인 contract를 사후 변경하지 않는다.

Normal create1은 actual valid/success/warmup 9operations/9attempts다. Metadata 기록 wrapper KeyError와
자신이 생성한 untracked bytecode 정리는 source 호출 전/후의 운영 오류이며 정상 요청을 반복하지 않았다.
Source initialize0·CPU 관측0·healthy0·KEDA0·calibration0·각 measured arm0, freeze 없음, recovery not measured다.
Post-stop CPU/HPA 조회를 positive proof로 쓰거나 synthetic 입력을 사용하지 않았다.

CUSTOM 우선 제거, shared guarded restore, namespace/Secret 삭제, final native verify1,
PAT20 revoke/login block, owned image/임시 role 삭제, 보호 사본 제거와 stable 보존19항목을 확인했다.
준비/원복 누적9회·historical KEDA restart 각1회·과거8개 archive를 보존한다.
Before/final two-RG ActualCost KRW49,306.6929280465, P9 incremental actual unknown이다.
추가 USD100 세전 검토 한도 승인은 기존 +72h 유지·제9차1회에 한정되며 billing hard cap이 아니다.
기존 승인 기한과 Azure Environment를 유지하고 자동 재준비/제10차 실행·merge/P10은 수행하지 않는다.
