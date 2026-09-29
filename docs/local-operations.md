# P3-W1 Local developer operation contract

## 실행 경계

`make local`은 소유권이 확인된 새 disposable k3d cluster에서 exact Argo Application `Synced/Healthy`와 Forgejo `/api/healthz`를 확인한 뒤 warm-up journey 1개, measured journey 5개를 순차 실행한다. `concurrency=1`, `max_attempts=1`, client retry 없음이다. 이어서 기존 P1/P2 workload replacement, state continuity, Service drift/self-heal 검증을 실행한다. `make baseline`은 이미 올린 cluster에서 baseline만 실행한다. 이 값은 실패를 본 뒤 바꾸지 않는다.

각 journey는 새 일반 developer 계정과 private repository를 사용한다. Admin의 계정 생성, developer token 발급 및 identity 확인은 `fixture`다. Local commit 준비는 `fixture`, fetch를 위한 두 번째 push는 `seed`, initial push 이후 Forgejo의 비동기 `empty=false` 확인은 `settle`, 추가 remote ref/API/내용 확인은 `assertion`이다. 이들은 developer operation count, latency, retry count에 포함되지 않는다. Readiness polling도 operation이 아니다.

| operation_type | attempt command 시작 → 종료 | semantic assertion |
| --- | --- | --- |
| `private_repository_create` | developer API `POST /user/repos` | private/owner/clone URL, anonymous read 거부 |
| `git_push_initial` | `git push origin main` | remote main SHA, 별도 async settle, branch SHA |
| `git_clone` | authenticated `git clone` | HEAD와 파일 내용 |
| `git_fetch` | 기존 clone에서 `git fetch origin` | 새 main SHA 관측, local fast-forward |
| `git_push_feature` | `git push origin feature/journey` | remote feature SHA |
| `pull_request_create` | developer API `POST /pulls` | 번호/title/open 상태 |
| `pull_request_read` | developer API `GET /pulls/{number}` | 번호/title/base/head/SHA/open 상태 |
| `issue_create` | developer API `POST /issues` | 번호/title/open 상태 |
| `issue_read` | developer API `GET /issues/{number}` | 번호/title/open 상태, PR 아님 |

`operation_start`는 bounded command 직전에, `attempt`는 command 직후에 기록한다. `operation`은 semantic assertion이 끝나야 성공한다. Operation/attempt의 `duration_seconds`는 같은 단일 command 구간이며 Linux `/proc/uptime`의 monotonic clock을 사용한다(약 10 ms 해상도). Fixture/settle/assertion 시간은 포함하지 않는다. Git Smart HTTP 내부 요청 수는 관측하지 않으므로 기록하거나 attempt로 추정하지 않는다. Git 원격 command는 `timeout 65s`, API command는 curl `--max-time 60 --retry 0`이다. Git credential helper는 비활성화한다.

## 결과, 지표, correlation

`results/local/<baseline-id>/<run-id>/events.jsonl`은 append-only JSONL이다. 첫 record는 `run_start` (`schema_version=1`, source SHA/dirty, plan, tool/runtime/Argo/chart provenance), 마지막 정상 종료 record는 `run_end` (completion과 validity 별도)다. 중간에는 `operation_start`, `attempt`, `operation`, `auxiliary_event`가 있다. `run_id → operation_id → attempt_id → auxiliary_event.attempt_id`로 client result를 연결하며 fixture/readiness/seed event의 operation/attempt 참조는 null이다. 이 ID는 project log correlation 값이며 OTel `trace_id`가 아니다. Forgejo 내부 trace 또는 HTTP request 단위 연계는 증명하지 않는다. Forgejo native access-log request ID는 추후 확장 후보일 뿐 이 unit에서 서버 설정은 바꾸지 않는다.

Command exit가 0이어도 semantic assertion이 틀리면 operation은 `failed`다. API status 오류는 실제 HTTP status와 `http_status` error class를 기록하며, transport timeout은 exit 28 / `timeout`으로 기록한다. SIGINT/SIGTERM은 가능한 경우 `interrupted`로 종료한다. SIGKILL처럼 기록할 기회가 없으면 `run_end`가 없어 validator는 `incomplete`라고 판정한다. 시작되지 않은 operation은 성공 record로 채우지 않는다. `validity`는 결과 해석 가능성이고 `completion`/operation outcome과 별개다.

`scripts/validate-operation-results.py`는 record별 allowlist, bounded error class, ID 참조, attempt count, semantic/outcome 관계, duration과 completion을 검사한다. 같은 JSONL에서 다음 project-defined family를 재계산한다. Label은 `operation_type`, `outcome`만 사용한다. `run_id`, user, repository, commit SHA, request ID는 label이 아니다.

| family | 분자/관측값 | 집계 범위 |
| --- | --- | --- |
| `developer_operations_total` | 완료된 operation 1건 | measured run의 operation_type/outcome별 count |
| `developer_operation_attempts_total` | 실행된 client command attempt 1건 | measured run의 operation_type/attempt outcome별 count |
| `developer_operation_duration_seconds` | operation의 command seconds 1개 | measured run의 operation_type/outcome별 sum/count |
| `developer_operation_attempt_duration_seconds` | attempt의 command seconds 1개 | measured run의 operation_type/attempt outcome별 sum/count |

`baseline-summary.json`은 measured 5개에서 family별 count/sum/count와 operation별 min/max/mean을 담고, warm-up을 제외한다. 분모는 실제 완료된 operation/attempt observation 수다. 이 작은 loopback + `kubectl port-forward` client sample은 production percentile, Azure SLO 또는 final threshold 근거가 아니다. Active Window는 첫 measured run 시작부터 마지막 measured run 종료까지이며 그 안의 실패 구간을 제외하지 않는다.

## Evidence lifecycle

`results/local/`은 Git에서 제외하되 `.tmp/journey` 및 credential-bearing runtime state와 분리해 `local-down.sh` 이후에도 남긴다. 실패한 run도 덮어쓰지 않는다. CI는 JSONL/summary 파일만 명시적으로 upload하고 `.tmp`, raw response, kubeconfig, credential, diagnostics를 upload하지 않는다. `request` 오류도 raw API body를 출력하지 않는다. 테스트는 API status/timeout, Git failure, incomplete record와 secret exclusion을 검증한다.

P3-W2는 Argo-safe coordinated backup → fresh restore 및 doctor/E2E/continuity, P3-W3는 검토된 v15 upgrade → previous compatible state 기반 rollback이다. 이번 source에는 두 capability의 mutation이 없다.
