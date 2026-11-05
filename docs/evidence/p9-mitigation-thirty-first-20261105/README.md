# 제31차 P9-W2 — reviewed valid calibration·freeze, measured C0/C1/C2 reviewed valid, C3 INVALID / owned cleanup 완료

**P9 acceptance는 미충족이다. 4-arm 비교는 실행하지 않았다.** Measured C3가 saved validator에서 invalid가 되었기 때문이다.

- 근거: [단일 Campaign31 승인](https://github.com/imcherry5778-labs/github-capacity-cascade-platform/issues/47#issuecomment-6637904463)([전달 기록](https://github.com/imcherry5778-labs/github-capacity-cascade-platform/issues/47#issuecomment-6637942879)), [독립 source gate](https://github.com/imcherry5778-labs/github-capacity-cascade-platform/pull/49#pullrequestreview-5772464508)
- Paid source는 `57c64f1a48224719685ad8ee453358e0d7b2e725`다.
- Operator는 sealed template(`1dfa262e…`)에서 instance로 생성했다. Paid 실행 전에 sealed test(sequence 12, cadence 6, C0 order 3)를 통과했다.
- 실행 중 source와 template은 바꾸지 않았다.

| 실행 | 결과 |
| --- | --- |
| initial / final normal | 각 1, SUCCESS |
| initialize / healthy | 각 1, SUCCESS (ingress 29 = authorization 29 = target 29) |
| KEDA apply / restore | 1/1 |
| C3 calibration | 1 started. **source `reviewed()` valid**, recovery not recovered(negative) |
| freeze | **source `frozen()` PASS** (P9 첫 freeze) |
| measured C0 / C1 / C2 | 각 1, **reviewed valid**. recovery: recovered 90.0s / recovered 90.0s / not recovered(negative) |
| measured C3 | 1 started. Run 완료, **saved validator INVALID** |
| comparison | 실행 안 함(4 arm 모두 reviewed여야 가능) |
| cloud mutation | 30 |

## 실행별 사실

모든 run이 demand 2400 = issued 2400, unissued 0이었다. Driver lag max는 1.19–1.50s였다.

| run | checks = admitted + rejected (+queue timeout) | scaling | recovery |
| --- | --- | --- | --- |
| C3 calibration1 | 3687 = 1134 + 2553 | observed (signal→desired→Ready→traffic) | not recovered |
| C0 | 3777 = 1032 + 2745 | not observed (CPU HPA) | recovered 89.997s |
| C1 | 3745 = 1154 + 2591 | not observed | recovered 89.987s |
| C2 | 4030 = 901 + queue_timeout 3129 | not observed | not recovered |

- **Confounder review:** 11개 signal을 모두 관측했고 `competing_bottleneck=false`로 판정했다.
  - PG CPU ≤18%, 연결 ≤22/844, node CPU ≤0.69 core, pressure 없음, sentinel 432–433개 전부 성공, freshness는 guard 안이었다.
  - C2에서 HAProxy queue는 측정 대상 정책이다. qmax 1, econ 1건을 기록했다.
- **Calibration report:**
  - `cadence_observed=true`다. 근거인 direct controller observation은 snapshot 8–15(+131.8…+288.5s)이고, 새 target UID는 1개다.
  - all-Pod series, ownership은 true였고, scrape 15s, raw age 51.6s였다.
  - 진단값인 status-change gap 3× 합은 286.79s였다(gate 아님).

## Measured C3 invalid

- Run 자체는 완료됐다: process exit 0, `run_end` completed, monitor/run failure 없음.
- Saved validator 결과: `invalid HPA/KEDA warning provenance or recurrence`.
- **경과(첫 signal evaluation 기준):**
  - Warmup은 inventory +59.0s(snapshot 4)부터 첫 fully observed signal +99.7s(snapshot 5)까지다.
  - Exact HPA `FailedGetExternalMetric`/`FailedComputeMetricsReplicas`의 count 2는 native 시각 +88.8s에 기록됐다. 이는 warmup 안이다.
  - 그런데 snapshot 5의 guard event 수집 시각은 **+87.2s**였다. 그래서 증가가 다음 snapshot 6에서야 보였다.
  - `KEDAScalerFailed` count 2(+67.8→+83.8s)는 허용됐다.
- **원인:** `57c64f1a`는 증가 허용을 native 시각이 아니라 snapshot index(`≤ observed snapshot`)로 판정했다.
- **종료 판단:** 교정하려면 paid source를 바꿔야 하고, measured C3(≤1)는 이미 소비됐다. 따라서 이 campaign에서는 다시 실행하거나 비교할 수 없어 종료했다.

## C0 전환 operator recovery (measure intent 소비 전)

1. Operator는 C0 CPU HPA를 replica 2인 상태에서 복원한 뒤 2→1로 reset했다.
2. 새 HPA의 기본 scale-down stabilization 300s가 이 reset을 되돌렸다(`ScaleDownStabilized`, CPU 2%/60%). 그래서 single Ready target 180s 대기가 deadline을 넘겼다.
3. 실행 중에는 source와 template을 바꾸지 않았다. native HPA가 스스로 1개 target으로 줄어드는 것을 read-only로 기다린 뒤, `measured_arm`의 남은 단계를 그대로 실행했다.
4. 이 경과는 operator event로 기록했다.

## 후속 cost-free 교정 (paid 이후, C31 재분류 없음)

- **Source:** 증가 허용을 native 시각으로 판정한다.
  - 조건 1: first와 last가 warmup episode 안에 있어야 한다(last < 첫 full signal).
  - 조건 2: 더 늦게 보인 version이라면, 그 사이 snapshot의 guard 수집 시각이 모두 native last+1s보다 앞서야 한다. 이는 event 시각이 초 단위이기 때문이다. 즉, 그 version 이후에 수집된 guard가 그 version을 빠뜨렸다면 invalid다.
  - C31 C3-measured raw를 local copy에서 hypothetical replay하면 `validate()`가 통과한다(recovery recovered 80.0s). 이 결과는 C31을 valid로 바꾸지 않는다. C29/C30 replay도 계속 통과한다.
- **Operator:** `to_c0_controller`에서 replica reset을 CPU HPA 복원보다 먼저 수행하도록 바꿨다. Sealed hash를 다시 봉인했다.

## 원복·계수

Cleanup 15단계가 모두 complete=true였고 errors=[]였다.

- PAT 3개는 DELETE 204, reuse 401이었다.
- 19:17:57Z에 독립적으로 read-only 재확인했다: 34 IDs, Owner 2, nodes 2, C31 UAMI·image tag·임시 AKS admin role 부재, process 종료, lock 해제.
- 이는 Campaign31 owned cleanup에 한정한 결과이며 global zero residual을 뜻하지 않는다.
- Resource hold는 약 72분이고 실제 비용은 UNKNOWN이다.

누적: campaign 31 / initialize 시작 28 / healthy 18 / calibration 시작 14(reviewed valid 2: C27, C31) / freeze 1 / measured 시작 C0–C3 각 1(reviewed valid C0/C1/C2, C3 invalid) / KEDA actions 14/14. Campaign22–30은 재분류하지 않는다.

## 참고 자료

[execution](execution.json), [raw index](raw-index.json), [sanitized archive](raw-evidence.tar.gz).

- 공개 file 115개는 roundtrip을 확인했고, identifier scan 결과는 0이다.
- 원본 raw는 local append-only로 보존한다.
