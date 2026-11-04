# 제29차 P9-W2 — CLOSED/invalid (KEDA warning recurrence) / owned cleanup 완료

**P9 acceptance는 미충족이다. Freeze와 measured C0–C3는 시작하지 않았다.**

- 근거: [단일 Campaign29 승인](https://github.com/imcherry5778-labs/github-capacity-cascade-platform/issues/47#issuecomment-6631593658), [독립 source gate](https://github.com/imcherry5778-labs/github-capacity-cascade-platform/pull/49#pullrequestreview-5766479509)
- Paid source는 `364cfb55f18c45c30610c9fe6e888c4832b0ffa9`이고, operator는 sealed template(`bc9def5b…b292`)에서 instance로 생성했다.
- 실행 중 source와 template은 바꾸지 않았다.

| 실행 | 결과 |
| --- | --- |
| initial / final normal | 각 1, SUCCESS (final은 복원 뒤 validator gate 통과) |
| initialize / healthy | 각 1, SUCCESS (ingress 30 = authorization 30 = target 30) |
| KEDA apply / restore | 1/1. Native workload identity, 정확한 ScaledObject 소유 HPA positive |
| C3 preflight | PASS |
| C3 calibration | 1 started. Run 완료, **saved validator INVALID** |
| freeze / measured C0–C3 | 없음 / 각 0 |
| cloud mutation | 17 |

## Calibration 1

Run은 끝까지 완료됐다: `run_end`, monitor failure 없음, snapshot 28개, release는 계획대로 origin+300s.

- **Demand:** scheduled 2400 = issued 2400, unissued 0, driver lag max 1.585s(≤2s).
- **Saved validator:** `invalid HPA/KEDA warning provenance or recurrence`.
- **Warning 내역:**
  - ScaledObject `KEDAScalerFailed`가 **count 2**였다(13:28:20Z → 13:28:35Z).
  - 같은 HPA에서 `FailedGetExternalMetric` 1회, `FailedComputeMetricsReplicas` 1회가 났다(13:28:25Z).
  - 발생 시점은 새 C3 Pod warmup 구간(origin+112s 무렵)이다.
- **해석:** guarded query는 모든 Pod series가 초기화될 때까지 의도적으로 빈 결과를 반환한다. 이때 `ignoreNullValues=false`이고 KEDA는 15s마다 polling한다. 따라서 warmup이 길어지면 scaler 실패가 반복될 수 있다. Source 계약은 count==1 비반복만 허용하므로, strict guard가 정확히 fail closed한 것이다.
- **참고(invalid run이므로 freeze 입력이 아님):** cadence 보수 상한은 3×(15+52.02+28.135)=285.464s로 mitigation 300s 이내였다.
- **종료 판단:** 이 조건을 교정하려면 source의 Warning 반복 정책을 바꿔야 하며, 이는 이번 승인 범위 밖이다. 두 번째 calibration은 blind retry가 되므로 하지 않고 NO-GO로 종료했다.

## 원복·계수

Cleanup 15단계가 모두 complete=true였고 errors=[]였다.

- `CUSTOM_remove`, `mesh_restore`, `namespace_remove`, `final_normal`, `KEDA_restore`
- PAT: normal/healthy/final 모두 DELETE 204, reuse 401
- stable, image, role, `ARM_final`, `forward_close`

13:38:05Z에 독립적으로 read-only 재확인했다.

- 34 IDs, Owner 2, nodes 2
- C29 UAMI·tag·임시 role 부재
- Driver/forward 종료, lock 해제

이는 Campaign29 owned cleanup에 한정한 결과이며 global zero residual을 뜻하지 않는다.

누적: campaign 29 / initialize 시작 26 / healthy 16 / calibration 시작 12(reviewed valid 1, C27) / measured 각 0 / KEDA actions 12/12. Campaign22–28은 재분류하지 않는다. Resource hold는 약 22분이고 실제 비용은 UNKNOWN이다.

**다음 결정(새 review와 승인 필요):** 새 Pod warmup 중 의도된 no-data와 KEDA scaler Warning 반복(count) 정책 사이의 계약 충돌을 정해야 한다.

## 참고 자료

[execution](execution.json), [raw index](raw-index.json), [sanitized archive](raw-evidence.tar.gz).

- 공개 file 45개는 roundtrip을 확인했고, identifier scan 결과는 0이다.
- 원본 raw는 local append-only로 보존한다.
