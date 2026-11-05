# 제27차 P9-W2 — reviewed valid C3 calibration / freeze fail-closed(cadence) / owned cleanup 완료

**P9 acceptance 미충족. Measured C0–C3는 시작하지 않았다.**
[단일 Campaign27 승인](https://github.com/imcherry5778-labs/github-capacity-cascade-platform/issues/47#issuecomment-6622151880),
[독립 source gate](https://github.com/imcherry5778-labs/github-capacity-cascade-platform/pull/49#pullrequestreview-5762998611),
paid source `7d0221ad7a2004ecb782b8ac0bd4b7a815c6218f`
([exact-head CI41766449436](https://github.com/imcherry5778-labs/github-capacity-cascade-platform/actions/runs/41766449436)).

- 실행 중 paid source는 바꾸지 않았다.
- Operator instance는 hash가 고정된 template에서 생성했다(driver template `ef9f17bc…c442`, instance hash는 [execution](execution.json)에 기록).
- Owned image digest는 [execution](execution.json)에 기록했다.

| 실행 | 결과 |
| --- | --- |
| initial normal / final normal | 각1, SUCCESS (final은 CUSTOM/mesh/namespace 복원 뒤 실제 validator gate 통과) |
| initialize / healthy | 각1, SUCCESS (ingress29 = authorization29 = target29) |
| KEDA apply / restore | 1/1. Native workload identity, 정확한 ScaledObject 소유 HPA positive |
| C3 calibration | 1 started. Local validation 통과, **source `reviewed()` valid** |
| freeze / measured C0–C3 | **fail closed** / 각0 |
| cloud mutation | 23 (모두 owned cleanup 대상) |

## 첫 mutation 전 gate와 준비

Read-only preflight는 전 항목 PASS였다. KEDA 2.19 형식 GET(4726 byte)도 HTTP200/vector였다. 이것은 URL 길이 transport만 확인한 것이다.

C0 fixture는 Service-first로 적용했다. Helper Pod에서 `getent`로 1회 조회한 주소가 ClusterIP 하나와 정확히 일치했고, endpoint는 현재 Ready target이었다. 그 뒤 HAProxy를 적용했고 restart는 0이었다.

Initialize도 처음으로 통과했다. Collector POST query는 정상이었다.

## C3 preflight operator 교정 (calibration intent 전, 횟수 소비 없음)

Healthy 3 snapshot 이후 fault configuration이 attempt1–3에서 대기 deadline을 넘겼다.

- **원인:** source `collect_snapshot`은 `runtime.collection_deadline.at`을 설정하고 해제하지 않는다. Operator가 같은 Runtime으로 configuration을 직접 호출하자 모든 kubectl이 즉시 `snapshot command budget exceeded`가 됐다(실패 poll 58회 기록).
- **교정:** snapshot 묶음이 끝날 때마다 operator가 만료된 deadline을 해제했다. Attempt4가 PASS했다(healthy 3 + fault 3 joint, 현재 KEDA HPA UID, HAProxy memory/OOM/restart).
- **대기 상한:** 진단 중 operator 대기를 100→180→300s로 늘렸다. 하지만 attempt4의 fault hold 수렴은 약 71–80s였으므로 대기 확대는 필요 없었다.
- 실패한 attempt의 evidence는 보존했다. Source, guard, 판정은 바꾸지 않았다.

## Calibration 1

- **Window:** 04:32:08–04:40:40Z.
- **Demand:** scheduled 2350 = issued 2350, unissued 0, driver lag max 1.541s ≤ 2s.
- **Accounting:** checks 3591 = target admitted 1132 + rejected 2459. Admission shed, queue timeout, path error는 모두 0이다.
- **Scaling:** signal → desired → Ready → 두 UID traffic 순서가 관측됐다. Autoscaling 주장 전에 ownership audit가 필요하며, 이 audit은 review에 포함됐다.
- **Recovery:** release 후 all-Pod 수렴에 90.18s가 걸렸다. 남은 window 안에 3 연속 good window를 얻지 못해 **not recovered within observation window**다. 이것은 negative이며 SLO를 완화하지 않았다.
- **Confounder:** 11개 signal이 모두 observed다(cloud PromQL/KQL, PG ARM 10 metrics). 판단 근거는 다음과 같다.
  - Forgejo app CPU 피크 0.181 core
  - PG CPU 12.97%, 연결 19/844
  - Node CPU 피크 0.69/4 core, pressure 없음
  - HAProxy queue/error/retry 0
  - Sentinel 424/424 성공
  - Freshness guard 범위 안
  - HPA 1개를 ScaledObject 1개가 소유하고 수동 변경은 0

  따라서 `competing_bottleneck=false`로 판단했고, `reviewed()` 결과는 valid다.
- **Calibration report:** reviewed, missing 0, all-Pod series, controller ownership은 모두 True다.

**`cadence_observed=False`.** Native 근거로 계산한 보수적 상한은 다음과 같다.

| 항목 | 값 |
| --- | --- |
| scrape 상한 | 15s |
| ingestion 상한 | 53.558s (최대 raw age; 하한 38.558s) |
| controller 상한 | 28.979s (same-HPA status update 26회, mitigation 꼬리 14.121s) |
| formula `3×(15+53.558+28.979)` | **292.611s > mitigation 290s** |

Source `frozen()`은 `reviewed bounded calibration required`로 fail closed했고 frozen.json은 없다.

- 초과 원인은 이번 run에서 관측된 AMW ingestion latency다. Operator가 교정할 수 있는 원인이 아니므로 두 번째 calibration은 blind retry가 된다. 그래서 시작하지 않았다.
- Plan(controller 15, mitigation 290)과 guard는 바꾸지 않았다.
- Campaign27을 종료했다.

## 원복·계수

같은 parent의 cleanup에서 다음 단계가 모두 complete=true, errors=[]였다: `CUSTOM_remove`, `mesh_restore`, `namespace_remove`, `final_normal`, `KEDA_restore`(원본 SA/template, available 2), normal/healthy/final fixture(PAT DELETE204, reuse401, login401), `stable_integrity`, `image_remove`, AMW/UAMI/FIC/AKS role 제거, `ARM_final`, `forward_close`.

04:55:39Z 독립 read-only 재확인 결과는 다음과 같다: 34 IDs, Owner 2, nodes 2. C27 UAMI·image tag·임시 role은 없었고, driver/forward는 종료됐으며 lock은 해제됐다. 이는 Campaign27 owned cleanup만의 결과이며 global zero residual이 아니다.

누적은 campaign 27 / initialize 시작 24 / healthy 14 / calibration 시작 10(그중 reviewed valid 1) / measured 각0 / KEDA actions 10/10이다. Campaign22–26은 재분류하지 않는다. Resource hold는 약 54분, 실제 비용은 UNKNOWN이다.

**다음 결정(새 승인 필요):** 원래 cadence 계약을 유지하면 mitigation이 관측된 보수적 상한보다 커야 한다. 이번 관측은 292.6s이고 source 상한은 300s다. Plan 변경 여부, 측정 정의, 추가 campaign은 모두 별도 review와 사용자 결정 사항이다.

[execution](execution.json), [raw index](raw-index.json), [sanitized archive](raw-evidence.tar.gz)를 함께 본다.

- 공개 60개 file roundtrip을 확인했다. 원본 UUID 1188개와 IP, project resource name, VMSS node name, private host, JWT, subscription, private path에 대한 scan 결과는 0이다.
- Node는 `node-N`, MC resource group은 `MC_redacted`로 가명 처리했다.
- 원본 raw는 local append-only로 보존했다. Private harness와 진단 파일은 SHA256만 기록했다.
