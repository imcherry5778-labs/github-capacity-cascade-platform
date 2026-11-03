# P9-W1 source preparation evidence

상태: **Azure runtime 미승인·미실행**. Matrix/측정/통합 승인 계약은
[P9 실행 문서](../../p9-mitigation-recovery.md) 한 곳에 둔다.

- [management.json](management.json): 기존 권한의 ARM read-only 조회. AKS/KEDA enabled/OIDC,
  resource/role/PG/Disk/quota inventory. Kubernetes/Secret/workload는 확인하지 않았다.
- [cost.json](cost.json): 현재 두 RG ActualCost query/result. KRW16,015.5402320629는 기존 환경의
  지연된 누적 관측이며 P9 actual 증가분은 unknown이다.
- [prices.json](prices.json): Korea Central retail query 입력/선택 항목. Billing hard cap이 아니다.
- [haproxy-local.json](haproxy-local.json): upstream checksum으로 확인한 native HAProxy3.4.6 source
  build, 네 arm parser와 loopback24-request queue 검증. Azure image/runtime 검증이 아니다.
  intentional429/PR, timeout503/sQ, server/BACKEND row 차이와 stats listen 제외를 확인했다.
- [validation.json](validation.json): directly affected regressions, P8 historical raw replay와 `make static`.
  Source file hashes를 기록한다. Exact submitted/review target SHA는 이 Draft PR의 HEAD/final report다.

P8 evidence는 수정하지 않았다. 기존 archive의 calibration05/no-retry02/retry pair를 cost-free로
재검증했으며 새로운 P8 workload나 P6/P7 drill을 실행하지 않았다. P9의 synthetic recovery tests는
validator 회귀일 뿐 Azure recovered claim이 아니다. Cleanup/mitigation 비교/corrective action 연결은
승인 후 같은 PR에서 실제 runtime raw/reviewed evidence를 추가해야 한다.
