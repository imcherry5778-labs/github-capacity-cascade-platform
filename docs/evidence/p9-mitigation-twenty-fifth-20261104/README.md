# 제25차 P9-W2 — CLOSED/invalid (HTTP 414) / owned cleanup 완료

**P9 acceptance 미충족. C3 calibration·freeze·measured C0–C3는 시작하지 않았다.**
[단일 Campaign25 승인](https://github.com/imcherry5778-labs/github-capacity-cascade-platform/issues/47#issuecomment-6617584526)과
[비용 gate 정합화](https://github.com/imcherry5778-labs/github-capacity-cascade-platform/issues/47#issuecomment-6618120240)의 paid source는
`a8c865164036cb453fa27f0d89545d58eddbb7a1`이다. 실행 중 paid source는 바꾸지 않았고 이 SHA로 retry하지 않았다.
Owned image manifest digest는 `sha256:59aab4e66f580b3a995d57fe4e0c3e4cc954a17c4b9690b2d43a5900bf6f8741`, plan SHA256은 `18e920b9…806b6a`다.

| 실행 | 실제 소비·결과 |
| --- | --- |
| normal journey | 1, SUCCESS (warmup valid, operation9) |
| public initialize / healthy journey | 1 / 1; healthy journey SUCCESS(ingress30·authorization30), initialize는 telemetry 단계 FAILED |
| C3 calibration / freeze / measured C0–C3 | 0 / 없음 / 각0 |
| KEDA SA apply/restore action | 0/0 |
| cloud mutation | 11 (모두 owned cleanup 대상) |

## 실패 원인 — collector query GET URL 길이

- 2026-11-03T23:48:44Z(08:48 KST), initialize 시작 202.281초 뒤 `telemetry_signal` 단계에서 다섯 번째 request인
  `collector_query`(SHA256 prefix `a1c8abd7e001`) GET이 **HTTP 414 URI Too Long**을 받았다. 같은 initialize의 신호 query 4종 GET 12회는 모두 200이었다.
  Collector query는 모든 target Pod가 observed된 poll에서만 호출되며, 이번에는 세 번째 poll이 첫 호출이었다.
- GET URL 길이(endpoint+path+encoded query): Campaign24 source `d1ed52b8`의 collector **4395 byte**(Campaign24 응답 27/27 HTTP200),
  `13c0b0d`의 identity/coverage guard 항 추가 이후 **9168 byte**(Campaign25 HTTP414). AMW URL 한도는 공식 문서에 없다. 4395는 허용, 9168은 거부로 관측됐을 뿐이다.
- 기존 test는 `http_json`을 patch해 URL query string만 확인했고 local runtime은 AMW를 조회하지 않아 CI가 실제 직렬화 길이를 검사하지 못했다.
- Ledger의 `healthy_initialization_failure`는 `error_code=unknown_failure`로 기록됐고 직전 `prometheus_query_error`가 414를 보존한다. Raw는 수정하지 않았다.

Prometheus [HTTP API](https://prometheus.io/docs/prometheus/latest/querying/api/)와
[Azure Monitor managed Prometheus query API](https://learn.microsoft.com/en-us/azure/azure-monitor/metrics/prometheus-api-promql)는
`/api/v1/query`의 `POST` + `Content-Type: application/x-www-form-urlencoded` body를 문서화하며 Bearer `Authorization` header는 GET과 같다.
교정은 PR #49의 후속 source commit에서 cost-free로만 수행했고 Azure에서 실행하지 않았다.

**REVALIDATE:** [KEDA 2.19 Prometheus scaler](https://github.com/kedacore/keda/blob/v2.19.0/pkg/scalers/prometheus_scaler.go)는 GET만 사용한다.
`a8c86516` scale query의 KEDA GET URL은 `time` parameter 포함 약 **4726 byte**로, 관측된 허용 4395와 거부 9168 사이라 수용 여부가 미검증이다.
Campaign25는 KEDA apply 전에 닫혀 이를 관측하지 않았다. Collector transport 교정으로 해결되지 않는 별도 의존성이다.

## 원복·계수

ChatGPT가 기존 Campaign25 parent의 등록된 `SIGTERM → finally: cleanup()` 경로만 호출했다(첫 step 2026-11-04T00:01:32Z, parent exit 00:03:01Z).
원본 `operator-events.jsonl`에서 `CUSTOM_remove`, `mesh_restore`, `namespace_remove`, `normal_fixture`, `healthy_fixture`, `stable_integrity`,
`image_remove`, `AMW_role_remove`, `UAMI_FIC_remove`, `AKS_role_remove`, `ARM_final`, `forward_close` 각 `cleanup_step complete=true`와
`operator_parent_exit cleanup_complete=true`를 확인했다. `cleanup-final.json`은 complete=true, errors=[]이며 PAT DELETE204·reuse401(normal/healthy),
ARM 34 IDs 불변·Owner2·fixed2 nodes·owned role 부재, owned image digest 부재를 기록한다.
`details.forward_close=false`는 context manager `__exit__` 반환값(예외 미억제)이며, close 근거는 `cleanup_step forward_close complete=true`와
`forward_wait stop returncode=-15 intentional_stop_requested=true`다.
2026-11-04T00:33Z 로컬 재확인: `campaign.lock` 획득 가능(해제), 원래 driver/forward PID 부재, 소유 driver/port-forward process 0.
이는 **Campaign25 owned cleanup 경로와 기록의 성공**이며 전체 환경 zero residual 선언이 아니다. 이 cost-free session에서 Azure/AKS 재조회는 하지 않았다.

Paid source 변경 없는 operator 교정: image publish의 private Docker config native endpoint, manifest read의 CLI plugin directory,
첫 mutation 전 access boundary assertion 1회(당시 cloud mutation0). Private operator harness는 실행 중 file을 수정해 함수를 다시 load했으며
cleanup()은 23:49:32Z `operator_cleanup_readiness`에서 마지막 file 내용으로 다시 load됐다. Harness·diagnostic의 SHA256만 [execution](execution.json)에 기록했다.

누적(Campaign24 누적 + Campaign25): **campaign25 / initialize 시작22 / healthy13 / started-invalid calibration9 / measured 각0 / KEDA apply·restore actions9/9**.
Campaign22–24 CLOSED/invalid는 재분류하지 않는다. Billing GET0, planning projection315.3567 USD, actual 비용 UNKNOWN.
Environment 11/5 10:30 KST, Foundation/Bootstrap 11/6 00:33 KST를 유지하며 자동 연장·전체 teardown은 없다.
새 paid 실행(Campaign26)은 교정 source의 ChatGPT 독립 exact-head review와 새 명시적 사용자 승인 전에는 할 수 없다.

[execution](execution.json), [raw index](raw-index.json), [sanitized archive](raw-evidence.tar.gz)를 함께 본다.
공개25개 file의 size/SHA256·roundtrip과 원본 UUID/IP·resource name·private host·JWT·subscription·private-path scan 0을 확인했다.
원본 raw는 local append-only로 보존하고 공개본은 identifier pseudonym만 적용했으며 original hash를 재서명하지 않았다.
Journey credential/work directory, kubeconfig, Docker config는 공개·hash 대상에서 제외했다.
