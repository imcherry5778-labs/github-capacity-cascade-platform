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

`operation_start`는 bounded command 전에 기록한다. JSONL serialization과 API payload/credential 및 Git auth 준비를 마친 뒤, command 호출 직전·직후에 monotonic time을 포착해 `attempt`를 기록한다. `operation`은 semantic assertion이 끝나야 성공한다. Operation/attempt의 `duration_seconds`는 같은 단일 command 구간이며 Linux `/proc/uptime`의 monotonic clock을 사용한다(약 10 ms 해상도). Shell timer 호출, sidecar 기록, `timeout` wrapper, process 시작/회수의 작은 overhead는 남는다. Fixture/settle/assertion 및 JSONL serialization 시간은 포함하지 않는다. 특히 `298957448f9f994dbedc9d9e3066ce033d0b31d0`에서 생성한 이전 evidence는 `operation_start` serialization 시간이 duration에 포함됐으므로 새 측정값과 같은 boundary로 비교하지 않는다. 이전 raw run은 수정하지 않는다. Git Smart HTTP 내부 요청 수는 관측하지 않으므로 기록하거나 attempt로 추정하지 않는다. Git 원격 command는 `timeout 65s`와 TERM 후 5s kill-after, API command는 curl `--max-time 60 --retry 0`이다. Exit 137은 명령이 설정된 timeout 경계를 지난 뒤 강제 종료된 경우에만 `timeout`으로 분류한다. Git credential helper는 비활성화한다.

## 결과, 지표, correlation

`results/local/<baseline-id>/<run-id>/events.jsonl`은 append-only JSONL이다. 첫 record는 `run_start` (`schema_version=1`, source SHA/dirty, plan, tool/runtime/Argo/chart provenance), 마지막 정상 종료 record는 `run_end` (completion과 validity 별도)다. 중간에는 `operation_start`, `attempt`, `operation`, `auxiliary_event`가 있다. `run_id → operation_id → attempt_id → auxiliary_event.attempt_id`로 client result를 연결하며 fixture/readiness/seed event의 operation/attempt 참조는 null이다. 이 ID는 project log correlation 값이며 OTel `trace_id`가 아니다. Forgejo 내부 trace 또는 HTTP request 단위 연계는 증명하지 않는다. Forgejo native access-log request ID는 추후 확장 후보일 뿐 이 unit에서 서버 설정은 바꾸지 않는다.

Command exit가 0이어도 semantic assertion이 틀리면 operation은 `failed`다. API status 오류는 실제 HTTP status와 `http_status` error class를 기록한다. curl nonzero exit에서도 관측한 HTTP status를 보존한다. HTTP 응답이 없음을 뜻하는 `000`은 null이고, HTTP 200 뒤 transport failure이면 status 200과 실패 exit/error class를 함께 기록한다. Transport timeout은 exit 28 / `timeout`으로 기록한다. SIGINT/SIGTERM은 가능한 경우 `interrupted`로 종료한다. SIGKILL처럼 기록할 기회가 없으면 `run_end`가 없어 validator는 `incomplete`라고 판정한다. Command 시작 전 중단에는 attempt를 만들지 않고 열린 operation을 남긴다. `validity`는 결과 해석 가능성이고 `completion`/operation outcome과 별개다. 완결된 failed/interrupted run도 해석 가능하면 `valid`이며 validator CLI exit 0이다. 열린 operation이나 `run_end` 부재는 `incomplete`이며 CLI exit 2다. Record 모순 및 schema 위반은 CLI exit 1이다.

`scripts/validate-operation-results.py`는 record별 allowlist, bounded error class, ID 참조, attempt count, semantic/outcome 관계, duration과 completion을 검사한다. Successful planned run에는 위 9개 operation type이 각각 정확히 한 번 있어야 한다. Terminal operation record와 실제 관측된 attempt record를 각각 집계한다. 따라서 열린 operation의 attempt가 기록된 prefix에서는 attempt metric만 남고, operation 성공을 추정하지 않는다. 같은 JSONL에서 다음 project-defined family를 재계산한다. Label은 `operation_type`, `outcome`만 사용한다. `run_id`, user, repository, commit SHA, request ID는 label이 아니다.

| family | 분자/관측값 | 집계 범위 |
| --- | --- | --- |
| `developer_operations_total` | 완료된 operation 1건 | measured run의 operation_type/outcome별 count |
| `developer_operation_attempts_total` | 실행된 client command attempt 1건 | measured run의 operation_type/attempt outcome별 count |
| `developer_operation_duration_seconds` | operation의 command seconds 1개 | measured run의 operation_type/outcome별 sum/count |
| `developer_operation_attempt_duration_seconds` | attempt의 command seconds 1개 | measured run의 operation_type/attempt outcome별 sum/count |

`baseline-summary.json`은 measured 5개에서 family별 count/sum/count와 operation별 min/max/mean을 담고, warm-up을 제외한다. 분모는 실제 완료된 operation/attempt observation 수다. 이 작은 loopback + `kubectl port-forward` client sample은 production percentile, Azure SLO 또는 final threshold 근거가 아니다. Active Window는 첫 measured run 시작부터 마지막 measured run 종료까지이며 그 안의 실패 구간을 제외하지 않는다.

## Evidence lifecycle

`results/local/`은 Git에서 제외하되 `.tmp/journey` 및 credential-bearing runtime state와 분리해 `local-down.sh` 이후에도 남긴다. 실패한 run도 덮어쓰지 않는다. CI는 JSONL/summary 파일만 명시적으로 upload하고 `.tmp`, raw response, kubeconfig, credential, diagnostics를 upload하지 않는다. `request` 오류도 raw API body를 출력하지 않는다. 테스트는 API status/timeout, Git failure, incomplete record와 secret exclusion을 검증한다.

P3-W2의 Argo-safe coordinated backup → fresh restore와 P3-W3의 v15 patch upgrade → previous compatible state 기반 rollback은 같은 lifecycle에 구현되어 있다. 각 실행의 완료 여부는 sanitized result와 exact-head CI로 별도 확인한다.

P3-W2의 `forgejo doctor` 판정은 현재 runtime에 적용되는 개별 무수정 integrity check와 source에서 확인한 경로 진단의 비교로 한다. `doctor check --all`의 무오류 종료를 보편적인 건강 조건으로 사용하지 않는다. LFS가 꺼진 Core에서 `gc-lfs`는 해당 없음이고, console logging으로 인해 `/data/log`가 없는 `paths` 결과는 source baseline의 명시적 예외다. 복구 target에는 이 예외 외 새 경로 오류가 없어야 한다.

## P4-W1 healthy shared gate

`make local`은 기존 direct baseline과 P1/P2 regression이 성공한 **같은 invocation-owned cluster**에서 temporary shared gate를 설치하고 제거까지 검사한다. `scripts/local-shared-gate.sh`는 독립 cluster 재사용 entrypoint가 아니다. 기존 create/delete ownership guard와 최종 cluster cleanup은 `local-run.sh` / `local-down.sh`가 계속 소유한다. W2 recovery와 W3 upgrade regression은 기존 CI 단계로 유지한다.

Request path는 loopback `18080` port-forward → dedicated `p4-ingress` Envoy → HTTP `ext_authz` → HAProxy → `ext-authz-sim` Service → 해당 Pod의 inbound Envoy → Python stdlib app → ALLOW → original Forgejo request다. 기존 direct endpoint `13000`과 stable Forgejo `ROOT_URL`/Git values/Argo source는 유지한다. `JOURNEY_ENDPOINT_URL`은 실제 transport endpoint만 선택하고, Forgejo가 광고하는 clone URL assertion은 계속 direct canonical URL에 적용한다. Forgejo native auth/anonymous-denial assertion도 유지한다.

Local routing은 classic `networking.istio.io/v1` `Gateway` / `VirtualService`다. W1에는 Kubernetes Gateway API CRD나 automated gateway lifecycle이 필요하지 않다. 이는 Local scope 결정이며 AKS 지원 판정이 아니다. Microsoft의 [Gateway API 문서](https://learn.microsoft.com/en-us/azure/aks/istio-gateway-api), [일반 overview](https://learn.microsoft.com/en-us/azure/aks/istio-about), [classic ingress 문서](https://learn.microsoft.com/en-us/azure/aks/istio-deploy-ingress) 사이의 Gateway API 지원 설명은 milestone-entry에서 불일치했으므로 Azure API 선택은 P5 `REVALIDATE`로 남긴다.

### Official upstream preflight (2026-09-30)

[Istio 1.30.5 release](https://istio.io/latest/news/releases/1.30.x/announcing-1.30.5/)와 [1.30 Kubernetes compatibility](https://istio.io/latest/news/releases/1.30.x/announcing-1.30/)를 확인했다. Existing Kubernetes 1.36은 이 branch의 documented 범위다. [HAProxy official release inventory](https://www.haproxy.org/)에서 3.4.6을 확인했다. `versions.env`는 Istio distribution checksum, pilot/proxy/HAProxy OCI index digest와 Python base digest를 pin한다. Built app image와 Kubernetes actual imageID는 매 invocation별 별도 evidence다.

Selected [Istio 1.30.5 source의 header/body 설정](https://github.com/istio/istio/blob/1.30.5/pilot/pkg/security/authz/builder/extauthz.go)과 [connection-pool mapping](https://github.com/istio/istio/blob/1.30.5/pilot/pkg/networking/core/cluster_traffic_policy.go)을 확인했다. `Sidecar.inboundConnectionPool.http.http2MaxRequests: 1024`의 healthy 값은 generated `inbound|8080||` prefix의 실제 cluster `circuitBreakers.thresholds.maxRequests`에서 확인한다. HAProxy에는 별도 admission/rate/queue 정책이나 sidecar를 추가하지 않는다. Upstream control-plane/gateway autoscaling도 꺼 두며 W1에는 HPA/EnvoyFilter/observability controller를 추가하지 않는다.

[Istio release dependency](https://github.com/istio/istio/blob/1.30.5/istio.deps)의 proxy build commit `3bf722f59561ef9747835e543c0b648eb4ab1237`과 해당 [build recipe](https://github.com/istio/proxy/blob/3bf722f59561ef9747835e543c0b648eb4ab1237/WORKSPACE)의 Envoy source commit `a3357a295443d008c6aec4c3d508745d9b002f40`을 구분한다. [Selected Envoy HTTP client source](https://github.com/envoyproxy/envoy/blob/a3357a295443d008c6aec4c3d508745d9b002f40/source/extensions/filters/common/ext_authz/ext_authz_http_impl.cc)는 fixed check header를 `OVERWRITE_IF_EXISTS_OR_ADD`로 적용한 후 check message를 전송한다. Runtime build/version string, native sidecar inventory, cluster name/`altStatName`와 stat inventory는 실제 proxy에서 별도로 기록한다. Recipe commit을 binary version string이라고 부르지 않는다.

### Evidence / removal contract

Gated journey는 P3의 9개 operation, single command attempt, retry 없음, fixture/assertion 밖 latency boundary를 그대로 사용한다. Measured API/Git command를 준비할 때 `x-operation-id`, `x-attempt-id`를 넣는다. Assertion/seed 요청에는 measured attempt ID를 넣지 않는다. 하나의 Git attempt에서 복수 HTTP check가 생길 수 있으므로 validator는 attempt별 **한 개 이상** ALLOW check를 요구하고 실제 개수를 기록한다.

Gated Git transport에는 `http.followRedirects=false`를 적용해 canonical direct endpoint로 redirect되면 성공으로 처리하지 않는다. curl API command도 redirect를 따라가지 않는다. 기존 direct Git transport 설정은 유지한다.

Provider header allowlist에는 correlation과 `x-gate-test-deny`만 넣고 body buffering을 사용하지 않는다. Selected Envoy HTTP check는 `Authorization`을 기본 포함하므로 allowlist만으로 credential value를 제외할 수 없었다. Supported `includeAdditionalHeadersInCheck`로 check copy의 `authorization`을 비밀이 아닌 고정 값 `p4-check-without-credentials`로 덮어쓴다. Original Forgejo request의 credential은 유지한다. App은 header **이름**, credential-values-absent/body-absent boolean, safe bounded correlation ID, fixed HAProxy-hop 판정과 decision만 기록한다. Authorization의 모든 duplicate 값이 고정 값 하나와 일치하지 않거나 Cookie/Proxy-Authorization/body가 check에 도달하거나 HAProxy hop이 없으면 fail closed한다. Path/query와 header value 및 body는 기록하지 않는다. Proxy access log도 status/detail/upstream-cluster/upstream-host만 남긴다. Non-mutating `GET /api/v1/version`에 sentinel Authorization/Cookie/body와 controlled deny header를 보내 403/DENY, 빈 body와 ingress `ext_authz_denied`/upstream 미호출을 검사한다. 이 probe의 실제 check exclusion 검사가 성공하기 전에는 developer credential을 gated endpoint에 보내지 않는다.

`results/local/shared-gate-<id>/`는 source SHA/dirty, direct baseline, image identity, rendered experiment source, owned resource UID, selected proxy config/version/stat inventory, check JSONL, narrow HAProxy/proxy path evidence, DENY와 removal/result를 보존한다. Journey `events.jsonl`은 기존 operation artifact allowlist가 보존한다. Full config dump, certificates, raw HTTP response, kubeconfig/credentials/temp directory는 artifact에 넣지 않는다. Check log와 phase log는 append-only이고 실패 phase도 보존한다. Dirty run은 exploratory로만 분류하며 final validator는 clean source를 요구한다.

Removal은 현재 server ID와 installed object UID/owner를 다시 확인한 뒤 exact experiment manifests만 삭제한다. 같은 cluster에서 experiment namespaces/CRDs/cluster-scoped inventory 부재, reliability endpoint 부재, stable Forgejo spec/UID 유지, Argo exact revision의 `Synced/Healthy`, direct developer journey를 검사한 후 invocation-owned cluster cleanup으로 진행한다. 전체 cluster 삭제만으로 fixture 제거를 주장하지 않는다.

W1의 stat inventory는 actual version에서 관측한 이름/값만 기록한다. `upstream_rq_active_overflow`의 존재 여부는 기록하되 saturation/rejection signal 검증으로 승격하지 않는다. W1은 Linux/amd64 Local HTTP proof이며 saturation/load calibration/retry amplification/P5 Azure source는 포함하지 않는다.

## P3-W3 patch upgrade / state-aware rollback

`make upgrade`는 `scripts/local-recover.sh upgrade`를 사용한다. 기존 W2의 developer fixture, coordinated checkpoint, Secret/DB/full `/data` restore와 doctor validator를 재사용한다. 이번 drill은 linux/amd64에서 `15.0.8-rootless`(A) → stable `15.0.9-rootless`(B) 한 pair만 검증한다. Official OCI index와 amd64 manifest digest는 `versions.env`의 W3 inventory로 구분한다. Kubernetes의 actual imageID와 init/application image도 비교하며, tag만으로 runtime identity를 주장하지 않는다.

Fresh A와 rollback target은 PostgreSQL/Argo만 먼저 준비한다. Application은 autosync를 끈 상태에서 기존 chart/source revision에 `image.tag`와 `image.digest`만 maintenance override하고 bounded manual sync한다. Fresh A의 empty database와 Forgejo PVC 부재를 시작 전에 검사한다. Stable Git values는 계속 B다.

Lifecycle:

```text
fresh A + pre-upgrade developer/PAT/session
→ queue flush (2m, outer bound 150s + kill-after 5s)
→ graceful stop + writer absent
→ coordinated A checkpoint + component hash/size validation
→ manual A → B + health/doctor/original state/same credential
→ B-only Git commit + Issue + API/DB/filesystem persistence
→ B graceful stop + owned cluster cleanup
→ new server/PVC/PV target + complete A checkpoint restore before startup
→ paused exact A + original state/credential
→ B-only Issue API/DB absence + original main + Git object inventory absence
→ new rollback Git/Issue write + API/DB/filesystem persistence + doctor
→ maintenance A retained until disposable target cleanup
```

하나의 pre-upgrade credential file과 cookie file hash를 각 stage에서 비교한다. Session login은 source에서 한 번만 수행하며 이후 protected page 요청은 원래 cookie를 읽기만 한다. B-only Issue absence는 새 rollback Issue보다 먼저 확인한다. 번호가 재사용되어도 `b-only`/`restored` title과 commit identity로 state를 구분한다. B에서 변경된 DB/data에 old binary를 실행하거나 migration metadata를 수정하는 경로는 없다.

DB authority는 2026-09-30 official v15 source와 실제 fresh A PostgreSQL catalog에서 먼저 확인했다. `version`과 `forgejo_version`의 단일 `id=1` version 값뿐 아니라 `forgejo_migration`의 applied ID 목록을 함께 read-only로 관측한다. 세 authority가 같으면 `no schema-version change observed`, 다르면 `migration observed`로 기록한다. Application version 변경만으로 DB migration을 주장하지 않는다. Restored A의 authority는 checkpoint A와 같아야 한다.

Doctor inventory와 selected `check-db-version`, `check-db-consistency`, `check-user-type`, `synchronize-repo-heads`는 A/B/rollback/post-write에서 유지한다. 모든 selected check는 diagnostic 없이 성공해야 한다. `paths`는 console logging의 exact `missing_/data/log` baseline diagnostic으로만 분류하며 PASS로 바꾸지 않는다. `gc-lfs` N/A는 effective LFS disabled일 때만 허용한다. `--fix`는 실행하지 않는다.

### Official upstream preflight (2026-09-30)

[15.0.8 release notes](https://codeberg.org/forgejo/forgejo/src/branch/forgejo/release-notes-published/15.0.8.md), [15.0.9 release notes](https://codeberg.org/forgejo/forgejo/src/branch/forgejo/release-notes-published/15.0.9.md), [v15 upgrade guide](https://forgejo.org/docs/v15.0/admin/upgrade/)를 확인했다. 당시 official v15 LTS는 15.0.9였다. 두 release note에는 이 pair의 manual migration, Core config 변경, rootless 특이사항 또는 PAT/native session 재발급 요구가 명시되지 않았다. 이것은 runtime continuity를 대신하는 보장이 아니다.

15.0.8은 repository template 초기화와 API authorization reducer 등의 보안 수정을, 15.0.9는 ApplyDiffPatch/OpenID CSRF 보안 수정과 push mirror 수정 등을 포함한다. Core에서 OpenID와 mirror는 이번 fixture가 사용하지 않는 기능이다. A는 disposable loopback drill에서만 사용하는 이전 patch다. Guide의 queue backward compatibility 주의, pre-upgrade full backup, old binary/newer database 금지 요구를 적용한다. 매 실행은 실제로 읽은 official raw release-note hash를 재확인하고 변경/접근 실패 시 중단한다. [v15 migration README](https://codeberg.org/forgejo/forgejo/src/tag/v15.0.8/models/forgejo_migrations/README.md)는 세 DB authority의 근거다.

### Regression / evidence

W3는 같은 source의 P1/P2 runtime regression, P3-W1 baseline, W2 recovery를 먼저 성공시켜야 한다. CI는 앞선 lifecycle/recovery step의 explicit result path를 전달해 중복 실행을 피하고, local standalone invocation은 해당 regression을 직접 실행한다. 기존 CI 45분 bound는 실제 full job 실행으로 확인한다.

`results/local/upgrade-<id>/`에는 checkpoint component hash/size, upstream hash/reference, stage별 runtime/DB authority/storage/credential hash, doctor 분류, B marker/absence/new write, regression과 append-only phase만 남긴다. Raw dump, tar, Secrets, password, PAT, cookie, config/env와 응답은 mode 0700 temporary directory에 두고 성공/실패 모두 제거한다. CI artifact는 sanitized filename allowlist만 사용한다. Validator는 lifecycle 순서, freshness, credential continuity, doctor와 marker proof 누락/모순을 거부한다. Dirty development run은 exploratory이며 final `validate-upgrade.py result`는 clean exact-head source를 요구한다.
