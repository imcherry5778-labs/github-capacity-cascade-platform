# P10 첫 implementation — cost-free source evidence

Baseline `58fae6f105bd5bc28e2c85e05a138f6cb3e4ed03`, [Draft PR52](https://github.com/imcherry5778-labs/github-capacity-cascade-platform/pull/52).
이 evidence의 실행 source는 `0bf487e`로 시작하는 commit이며, exact SHA는 [protocol JSON](haproxy-protocol.json)의 `source_sha`다.
후속 evidence/documentation commit의 exact-head CI는 PR checks와 immutable Actions artifact를 따른다.

## 직접 실행한 검증

| 검증 | 결과 | 경계 |
| --- | --- | --- |
| P10 targeted tests | 14 PASS | real10s driver 포함; paired conclusion 사례는 synthetic |
| pinned HAProxy3.4.6 Docker protocol | PASS | allowlisted3, negative13, unsafe credential/body3개 |
| P8 adapter tests | 38 PASS | offline; paid runtime 아님 |
| P9 mitigation tests | 156 OK, skipped3 | skip을 실행 성공으로 합치지 않음 |
| P4 shared-gate / saturation tests | 15 / 10 PASS | offline |
| CI classifier tests | 40 PASS | offline |
| operation-result checks | PASS | producer/clock/TLS configuration contract |
| shell syntax / diff whitespace | PASS | 직접 영향 path |

`haproxy-protocol.json`은 실제 class dispatch와 app의 credential/body absence/denial record를 담는다.
두 backend가 같은 app을 사용하는 protocol test다. Physical isolation이나 Forgejo native auth/TLS proof가 아니다.
P10 CLI는 renderer/validator/comparison만 제공한다. Driver는 callback engine이며 승인 없는 Azure operator entrypoint는 없다.

## CI가 추가 검증하는 범위

Full `local-platform`은 pinned tools/static/render/Terraform, actual P10 HAProxy protocol,
owned fresh P1–P4 local lifecycle(healthy Forgejo Issue/Git/native-auth/effective ext_authz P10 smoke와 설정 복원 포함),
P4 saturation/removal, recovery/upgrade와 ownership/cleanup을 실행한다.
Actual step 결과와 exact HEAD가 성공한 경우에만 해당 runtime을 검증 완료로 판단한다.
P10 `p10-healthy.json`, `p10-protocol.json`은 sanitized shared-gate Actions artifact에 포함한다.
Mac에서 Linux 전용 full `make static/local`을 실행했다고 주장하지 않는다.

## 미실행 / 남은 gate

- actual2-pool paired calibration, numeric freeze와 physical pool mapping/runtime protection: **not verified**.
- Azure tenant/AKS/AMW/credential/Secret/inventory 조회와 mutation/paid test: **실행하지 않음**.
- actual managed ingress normalization/method/path, native/init admission/headroom/공유 환경 current price: **UNKNOWN / not verified**.
- independent source gate와 별도 P10 paid approval: **없음**.

[분류·topology·acceptance·bounded feasibility 후보](../../p10-critical-bulk-isolation.md)를 따른다.
P8/P9 historical negative/valid/raw는 수정하지 않았고 source/CI 검증을 paid acceptance나 P10 완료로 승격하지 않는다.

[Public retail pricing projection](retail-price-summary.json)은 tenant 인증 없는 read-only public API 결과다. Incremental USD2는 planning estimate이며 budget cap/실제 비용/실행 승인이 아니다.
