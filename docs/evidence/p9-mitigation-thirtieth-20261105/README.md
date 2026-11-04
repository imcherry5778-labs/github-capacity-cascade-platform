# 제30차 P9-W2 — CLOSED/invalid (HPA warning recurrence) / owned cleanup 완료

**P9 acceptance는 미충족이다. Freeze와 measured C0–C3는 시작하지 않았다.**

- 근거: [단일 Campaign30 승인](https://github.com/imcherry5778-labs/github-capacity-cascade-platform/issues/47#issuecomment-6633485342), [독립 source gate](https://github.com/imcherry5778-labs/github-capacity-cascade-platform/pull/49#pullrequestreview-5770057985)
- Paid source는 `2224f1098b1465b3c8a90e8fb758608e365529a1`이다. Operator는 sealed template(`bc9def5b…b292`)에서 instance로 생성했다.
- Sealed operator test 3종(sequence/cadence/C0 order)은 paid 전에 통과했다.
- 실행 중 source와 template은 바꾸지 않았다.

| 실행 | 결과 |
| --- | --- |
| initial / final normal | 각 1, SUCCESS (final은 복원 뒤 validator gate 통과) |
| initialize / healthy | 각 1, SUCCESS (ingress 28 = authorization 28, target 30, auxiliary 13) |
| KEDA apply / restore | 1/1. Native workload identity, 정확한 ScaledObject 소유 HPA positive |
| C3 preflight | PASS |
| C3 calibration | 1 started. Run 완료, **saved validator INVALID** |
| freeze / measured C0–C3 | 없음 / 각 0 |
| cloud mutation | 17 |

## Calibration 1

Run은 끝까지 완료됐다: `run_end` completed, monitor/run failure 없음, snapshot 27개, 최대 gap 21.45s.

- **Demand:** scheduled 2400 = issued 2400, unissued 0, driver lag max 1.258s.
- **Saved validator:** `invalid HPA/KEDA warning provenance or recurrence`.
- **Warning 내역:** 시각은 첫 signal evaluation 기준이다.
  - Exact HPA의 `FailedGetExternalMetric`과 `FailedComputeMetricsReplicas`가 각각 count 1→**2**였다(+88.5→+104.5s, HPA sync 16s 간격).
  - ScaledObject `KEDAScalerFailed`도 count 1→2였다(+91.5→+106.5s).
  - 세 Warning 모두 같은 native warmup episode 안에 있다. Episode는 새 target inventory snapshot 4(+57.4s)에서 시작해 첫 fully observed signal snapshot 7(+131.0s)에서 끝난다.
  - Count 1은 snapshot 6에, count 2는 snapshot 7에 나타났고, 그 뒤로는 변하지 않았다.
- **거부 이유:** `2224f109`는 KEDA 반복만 bounded warmup으로 허용하고 HPA는 count1로 유지했다. 그래서 같은 no-data 오류가 HPA sync마다 전파된 반복을 거부했다.
- **두 번째 calibration을 하지 않은 이유:** 교정하려면 paid source를 바꿔야 한다. 그런데 source approval gate는 run-ledger의 모든 row를 identity `source_sha`에 결합한다. 따라서 교정된 calibration을 이 C30 ledger에서 실행하려면 검토되지 않은 operator/ledger rebinding이 필요하고, 이는 승인 범위 밖이다. 그래서 두 번째 calibration 없이 NO-GO로 종료했다.
- **참고(invalid run이므로 freeze 입력이 아님):** cadence 보수 상한은 3×(15+51.967+38.395)=**316.087s**로 mitigation 300s를 넘는다.
  - Controller 상한 38.395s는 HPA status 변경 간격 24개 중 하나다. 나머지 간격은 18.9–29.0s였다.

## 후속 cost-free 교정 (paid 이후, 이 run 재분류 없음)

Source의 Warning 반복 허용 범위를 넓혔다. 이제 exact HPA UID의 `FailedGetExternalMetric`/`FailedComputeMetricsReplicas`도 KEDA와 같은 native warmup episode, 같은 strict 증가 조건 안에서만 반복을 허용한다. 그 밖의 guard는 그대로다.

C30 raw를 local copy에서 hypothetical replay한 결과, `validate()`가 통과했다.

- Recovery는 `recovered`(약 80s)다.
- 이 결과는 C30을 valid로 바꾸지 않는다.
- `reviewed()`/`frozen()`은 same-window cloud confounder review를 수집하지 않아 확인하지 못했다.
- 위 cadence 316.087s로 보면 이 data는 freeze도 통과하지 못한다.

## 원복·계수

Cleanup 15단계가 모두 complete=true였고 errors=[]였다.

- `CUSTOM_remove`, `mesh_restore`, `namespace_remove`, `final_normal`, `KEDA_restore`
- PAT: normal/healthy/final 모두 DELETE 204, reuse 401, login 401
- stable, image, role, UAMI/FIC, `ARM_final`, `forward_close`

15:09:53Z에 독립적으로 read-only 재확인했다.

- 34 IDs, Owner 2, nodes 2
- C30 UAMI·image tag·임시 AKS admin role 부재
- Driver/forward 종료, lock 해제

이는 Campaign30 owned cleanup에 한정한 결과이며 global zero residual을 뜻하지 않는다.

누적: campaign 30 / initialize 시작 27 / healthy 17 / calibration 시작 13(reviewed valid 1, C27) / measured 각 0 / KEDA actions 13/13. Campaign22–29는 재분류하지 않는다. Resource hold는 약 28분이고 실제 비용은 UNKNOWN이다.

**다음 결정(새 review와 승인 필요):**

1. 위 HPA warning 교정에 대한 source review.
2. Cadence gate 문제. 관측된 controller status 변경 간격 최대값(이번에는 38.4s 한 번)이 mitigation 300s 안의 3× 상한을 넘었다. 측정 정의를 유지할지, plan을 조정할지 판단해야 한다.

## 참고 자료

[execution](execution.json), [raw index](raw-index.json), [sanitized archive](raw-evidence.tar.gz).

- 공개 file 45개는 roundtrip을 확인했고, identifier scan 결과는 0이다.
- 원본 raw는 local append-only로 보존한다.
