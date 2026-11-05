# 제32차 P9-W2 — reviewed valid calibration·freeze, measured C0–C3 reviewed valid, source compare valid / owned cleanup 완료

**P9에서 처음으로 같은 fault/demand 조건의 C0–C3 measured 4 arm이 모두 reviewed valid였고, source `compare()`도 valid였다.**

- 근거: [Campaign32 승인](https://github.com/imcherry5778-labs/github-capacity-cascade-platform/issues/47#issuecomment-6644006116), [+72h 보존과 reserve 정정 승인](https://github.com/imcherry5778-labs/github-capacity-cascade-platform/issues/47#issuecomment-6645059367), [독립 source gate](https://github.com/imcherry5778-labs/github-capacity-cascade-platform/pull/49#pullrequestreview-5777556739), [exact-head CI 41934775041](https://github.com/imcherry5778-labs/github-capacity-cascade-platform/actions/runs/41934775041)(4/4, full lifecycle 실행)
- Paid source는 `26d9805ed07885fdedbc72ed7febe88d671872a7`이고, operator는 sealed template(`ed798b87…`)에서 instance로 생성했다.
- 실행 중 source와 template은 바꾸지 않았다.
- 이 campaign의 첫 시도는 매 mutation마다 8045s reserve를 요구하는 규칙 때문에 Azure 호출 전에 NO-GO였다. 그때 소비된 횟수는 없다.
- 이 결과는 하나의 동시 비교이며, 통계적 일반화가 아니다.
- Comparison은 원복을 증명하지 않는다. 원복은 아래 cleanup 근거로 따로 확인했다.

| 실행 | 결과 |
| --- | --- |
| initial / final normal | 각 1, SUCCESS |
| initialize / healthy | 각 1, SUCCESS (ingress 29 = authorization 29 = target 29) |
| KEDA apply / restore | 1/1 |
| C3 calibration | 1 started, **reviewed valid** |
| freeze | **source `frozen()` PASS** |
| measured C0 / C1 / C2 / C3 | 각 1, **모두 reviewed valid** |
| comparison | **source `compare()` valid** |
| cloud mutation | 30 |

## Arm별 사실

모든 run이 demand 2400 = issued 2400, unissued 0이었다. Driver lag max는 1.20–1.53s였다.

| run | checks = admitted + rejected (+queue timeout) | scaling | recovery |
| --- | --- | --- | --- |
| C3 calibration1 | 3691 = 1130 + 2561 | observed | not recovered |
| C0 (CPU HPA) | 3777 = 1032 + 2745 | not observed | recovered 80.0s |
| C1 (backoff) | 3751 = 1154 + 2597 | not observed | recovered 70.0s |
| C2 (HAProxy admission) | 3819 = 1112 + queue_timeout 2707 | not observed | recovered 80.0s |
| C3 (KEDA proxy scaling) | 3685 = 1138 + 2547 | observed (HPA 1개, ScaledObject 1개 소유) | not recovered within observation window |

- **Confounder review:** 매 run 11개 signal을 모두 관측했고 `competing_bottleneck=false`로 판정했다.
  - PG CPU ≤15.3%, 연결 ≤25/844, node CPU ≤0.70 core, pressure 없음.
  - HAProxy error/retry는 0이고, sentinel 426–429개가 전부 성공했다.
  - Freshness는 guard 안이었다(raw age ≤53.8s, inventory ≤66.3s/90).
  - C2의 HAProxy queue는 측정 대상 정책이다.
- **Warmup Warning:** native warmup 안에서 KEDA/HPA no-data Warning이 났다. Calibration에서는 각 3, C3 measured에서는 KEDA 3, HPA 2였다. Source가 episode와 native 시각 조건으로 허용했고, 이후 같은 HPA의 joint positive가 확인됐다.
- **Calibration report:**
  - `cadence_observed=true`다. 근거인 direct controller observation은 snapshot 9–15(+155.7…+299.7s)이고, 새 target UID는 1개다.
  - all-Pod series, ownership은 true였고, scrape 15s, raw age 51.5s였다.
  - 진단값인 status-change gap 3× 합은 363.7s였다. 이는 freeze gate가 아니다.
- **해석의 범위:** C0/C1/C2는 관측 window 안에서 recovered였다. C3는 KEDA scale-up이 관측됐지만 window 안에서 recovered가 아니었다(negative). 이 비교에서 어떤 mitigation의 개선이나 우열을 주장하려면 ChatGPT의 acceptance 판정이 필요하다.

## 원복·계수

Cleanup 15단계가 모두 complete=true였고 errors=[]였다.

- Final normal은 validator gate를 통과했다.
- PAT 3개는 DELETE 204, reuse 401이었다.
- 01:22:41Z에 독립적으로 read-only 재확인했다: 34 IDs, Owner 2, nodes 2, C32 UAMI·image tag·임시 AKS admin role 부재, process 종료, lock 해제.
- 이는 Campaign32 owned cleanup에 한정한 결과이며 global zero residual을 뜻하지 않는다.
- Resource hold는 약 65분이다.
- 실행 전 native 확인에서 RG lock 0, TTL성 tag 0, Azure budget 객체 0이었고 spendingLimit은 보고되지 않았다. 따라서 provider가 강제하는 budget이나 TTL은 없고, 실제 비용은 UNKNOWN이다.

누적: campaign 32 / initialize 시작 29 / healthy 19 / calibration 시작 15(reviewed valid 3) / freeze 2 / measured 시작 각 2(reviewed valid C0·C1·C2 각 2, C3 1) / compare valid 1 / KEDA actions 15/15. Campaign22–31은 재분류하지 않는다.

## 참고 자료

[execution](execution.json), [raw index](raw-index.json), [sanitized archive](raw-evidence.tar.gz).

- 공개 file 127개는 roundtrip을 확인했고, identifier scan 결과는 0이다.
- 원본 raw는 local append-only로 보존한다.
