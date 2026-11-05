# 제28차 P9-W2 — CLOSED/invalid (calibration monitor validation_failed) / owned cleanup 완료

**P9 acceptance 미충족. Freeze와 measured C0–C3는 시작하지 않았다.**
[단일 Campaign28 승인](https://github.com/imcherry5778-labs/github-capacity-cascade-platform/issues/47#issuecomment-6625733645)과
[독립 source gate](https://github.com/imcherry5778-labs/github-capacity-cascade-platform/pull/49#pullrequestreview-5765077924)의 paid source는
`6ae7342807df86d2ffc623b298d9ef0a977cce11`이다.
Operator는 sealed template(`bc9def5b…b292`)에서 instance를 생성했고 instance hash는 [execution](execution.json)에 있다.
실행 중 source와 template은 바꾸지 않았다.

| 실행 | 결과 |
| --- | --- |
| initial / final normal | 각1, SUCCESS (final은 복원 뒤 validator gate 통과) |
| initialize / healthy | 각1, SUCCESS (ingress29 = authorization29 = target29) |
| KEDA apply / restore | 1/1. Native workload identity, 정확한 ScaledObject 소유 HPA positive |
| C3 preflight | 첫 시도 PASS (healthy 3 + fault 3 joint, HAProxy memory/OOM/restart). C27 deadline 교정이 효과를 냈다 |
| C3 calibration | 1 started, **INVALID** |
| freeze / measured C0–C3 | 없음 / 각0 |
| cloud mutation | 17 |

## Calibration 1 실패

Monitor가 schedule origin+269.5s(mitigation 중)에 `validation_failed`로 중단했다. Source는 +270.0s에 fault를 조기 release했다.
종료 시점 demand는 scheduled 2400, issued 1350, unissued 1050, driver lag max 0.301s다. Invalid이므로 비교 대상이 아니다.

- 실패한 collection은 +252.8s에 시작됐고 collector signal evaluation 직후에 중단됐다. Source는 partial snapshot을 발행하지 않는다.
  그 evaluation의 guarded 값은 5.96이고 raw/up age는 52.45s(≤60)였다. Per-Pod telemetry age도 ≤60s이고, local/server clock 차이는 0.06–0.19s였다.
- 저장된 snapshot 15개는 `common_guards`, `controller_metric_warnings`, `haproxy_capture_guard`를 모두 통과한다.
- **실패한 guard는 source가 기록하지 않는다**(allowlist error code만 남음). Signal 다음 단계는 `lifecycle.resources()`다.
- **원인 근거(read-only):** 120s 동안 metrics-server Pod-metric timestamp를 50회 조회했다. 그중 18회에서 timestamp가 이전보다 과거로 되돌아갔다(예: 08:24:30Z 다음 08:24:20Z).
  이는 `resources()`의 `stamp >= previous`(`resource sample history drift`) 조건과 부합한다. 다만 강한 근거일 뿐, 실패한 collection의 원인을 증명한 것은 아니다.
- 이 조건을 교정하려면 source guard를 바꿔야 하므로 이번 승인 범위 밖이다. 두 번째 calibration은 blind retry가 되므로 시작하지 않고 NO-GO로 종료했다.
- Operator note: template 정리 과정에서 `c3()` 완료 출력(safeout)이 빠졌다. 출력만의 문제이며 c3는 완료됐고 결과 파일도 저장됐다.

## 원복·계수

Cleanup 15단계가 모두 complete=true, `cleanup-final` errors=[]였다:

- `CUSTOM_remove`, `mesh_restore`, `namespace_remove`, `final_normal`, `KEDA_restore`
- normal/healthy/final fixture: PAT DELETE 204, reuse 401
- `stable_integrity`, image 제거, AMW/UAMI/FIC/AKS role 제거, `ARM_final`, `forward_close`

08:28:48Z 독립 read-only 재확인에서 34 IDs, Owner 2, nodes 2를 확인했다. C28 UAMI, image tag, 임시 role은 없었다. Driver/forward는 종료됐고 lock은 해제됐다.
이 결과는 Campaign28 owned cleanup에 한정되며 global zero residual을 뜻하지 않는다.

누적: campaign28 / initialize 시작25 / healthy15 / calibration 시작11(reviewed valid1, C27) / measured 각0 / KEDA actions11/11.
Campaign22–27은 재분류하지 않는다. Resource hold는 약28분이고 실제 비용은 UNKNOWN이다.

**다음 결정(새 review와 승인 필요):** AKS metrics-server의 non-monotonic Pod-metric timestamp와 source resource history guard 사이의 계약 충돌을 정리해야 한다.

[execution](execution.json), [raw index](raw-index.json), [sanitized archive](raw-evidence.tar.gz)를 함께 본다.
공개된 46개 file은 roundtrip을 확인했다. 원본 UUID/IP, resource/VMSS node name, private host, JWT, subscription, private path에 대한 scan 결과는 모두 0이다.
원본 raw는 local append-only로 보존했다.
