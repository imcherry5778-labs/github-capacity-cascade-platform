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

### GitHub CI Redis image supply

PR #31의 `38f6850`에서 run `40453911056` attempt 1·2는 Argo CD Redis
`public.ecr.aws/docker/library/redis:8.2.3-alpine`의 `ImagePullBackOff` / `registry-rate-limited`와
rollout timeout으로 실패했다. 두 attempt의 owned cleanup은 PASS였고 후속 recovery/upgrade/ownership은 skipped였다.
이 실패 evidence는 이후 성공 run으로 대체하지 않는다. 별도 read-only registry 조회에서도 ECR Public HTTP 429를 관측했다.

`local-up.sh`는 checksum을 검증한 upstream Core를 설치한 뒤 `GITHUB_ACTIONS=true`에서만 Redis image를
`versions.env`의 Docker Official Image digest로 지정한다. 동일 경로가 fresh lifecycle/recovery/upgrade/ownership의
각 새 cluster에 적용된다. GitHub 밖의 기본 실행, Core checksum, Redis `8.2.3-alpine` 버전,
upstream `imagePullPolicy: Always`, 기존 rollout/cleanup gate는 유지한다. Host Docker cache와 k3d node의
containerd store는 별개이며 `Always`는 사전 적재 후에도 registry resolution을 요구하므로 단순 preload를 사용하지 않는다.
새 credential/registry service, 무제한 backoff, runtime skip은 추가하지 않는다. Docker Hub가 실패해도 gate를 우회하지 않는다.

2026-10-27 `docker buildx imagetools inspect --raw`로 두 registry의 tag index bytes가 같고 SHA256이
`08ad0b1d280850169a790dba1393ff7a90aef951fc19632cf4d3ce4f78e679ba`임을 확인했다.
양쪽 index의 linux/amd64 manifest는 `sha256:e499175dfb27569cd40010c2eee346113db95fdd0efc88ab9fd70a9e807f4542`다.
따라서 registry만 바꾸고 같은 content를 digest로 고정한다. OCI index가 platform manifest와 config/layer digest를
연결한다. 비교 명령은 token/config/layer 원문을 출력하지 않으며 실제 runtime/CI 결과는 exact source HEAD별 PR evidence로 남긴다.

### Run evidence

`results/local/`은 Git에서 제외하되 `.tmp/journey` 및 credential-bearing runtime state와 분리해 `local-down.sh` 이후에도 남긴다. 실패한 run도 덮어쓰지 않는다. CI는 JSONL/summary 파일만 명시적으로 upload하고 `.tmp`, raw response, kubeconfig, credential, diagnostics를 upload하지 않는다. `request` 오류도 raw API body를 출력하지 않는다. 테스트는 API status/timeout, Git failure, incomplete record와 secret exclusion을 검증한다.

Ownership marker를 받은 `local-up.sh`가 직접 만든 cluster에서 bootstrap이 실패하면, owned cleanup 전에 create/delete lock 안에서 현재 server ID가 그 cluster와 같은지 다시 확인한 뒤 `local-verify.sh bootstrap-diagnostics`를 bounded 실행해 CI step log에 남긴다. 이 mode 자체도 marker의 server ID와 현재 server ID가 같지 않으면 조회하지 않으며, marker가 없는 guard setup(`make up`) 실패에는 workflow 진단 step을 두지 않는다. 출력은 node condition/allocatable/taint, workload replica/condition reason, healthy Pod 수(Ready condition, main/init container status, restart 포함), unhealthy Pod의 condition reason과 init/main container의 image·ready·started·restart·state/last termination reason·exit code, Warning 및 `argocd` event의 reason/count다. Pod/event는 Kubernetes API에서 전체 object JSON(Pod spec 포함)을 받지만 위 status/metadata field만 출력한다. Secret/ConfigMap은 조회하지 않는다. Container log와 condition/container/termination/event message 원문은 출력하지 않는다. Reason/type은 identifier 형식일 때만 출력하고, message에서는 고정 allowlist의 hint token(예: `insufficient-memory`, `image-not-found`, `object-not-found`, `readiness-probe`)만 남긴다. Ownership이 없거나 확인되지 않으면 조회하지 않으며, 진단 실패는 원래 exit code와 cleanup을 바꾸지 않는다. `tests/e2e/test-local-bootstrap-diagnostics.py`가 stub과 fake credential sentinel로 이 순서와 경계를 검증한다.

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

P6-W1 CI 조사에서는 `9b64beb`의 attempt 1(Redis registry rate limit)과 attempt 2(P4 `ErrImageNeverPull`)를 별도 실패로 유지한다. Attempt 2는 build/import 로그가 임시 directory와 함께 삭제되어 원인이 아직 확정되지 않았다. Pinned [k3d v5.9.0 tools-node 구현](https://github.com/k3d-io/k3d/blob/v5.9.0/pkg/client/tools.go#L100-L168)은 per-node import 오류를 반환하지 않으므로 exit 0만으로 availability를 증명할 수 없다([upstream issue](https://github.com/k3d-io/k3d/issues/1484), [미병합 수정 PR](https://github.com/k3d-io/k3d/pull/1694)). 이 결함의 존재와 해당 CI 실패의 원인은 구분한다.

Fixture는 import 직후 invocation-owned 단일 node의 CRI에서 normalized exact reference와 built image의 config digest를 확인하고, rollout 후 Pod의 node/reference/`Never` policy를 다시 확인한다. Docker inspect의 image ID(OCI index/manifest일 수 있음)는 별도로 남기고, local image export의 config bytes SHA256을 CRI ID와 비교한다([OCI manifest/config 구분](https://github.com/opencontainers/image-spec/blob/v1.1.1/manifest.md)). Import mode 변경, 재시도, registry push/pull은 추가하지 않는다. 실패 시 cleanup 전에 fixed credential-free build/import command의 exit code와 path-redacted 로그, CRI ID/tag 및 containerd reference, fixture Pod image/node/wait reason, event reason/count와 고정 message hint를 보존한다. Node/containerd 원문 log는 보존하지 않고 고정 hint만 추출한다. CI artifact allowlist는 이 `image-*` 파일만 추가하며 Secret/ConfigMap/env/image config/kubeconfig는 포함하지 않는다. 진단은 bounded read-only이며 원래 실패 및 owned cleanup 결과를 바꾸지 않는다. 새 exact-head CI의 실행 결과는 PR evidence에 별도로 기록한다.

Gated journey는 P3의 9개 operation, single command attempt, retry 없음, fixture/assertion 밖 latency boundary를 그대로 사용한다. Measured API/Git command를 준비할 때 `x-operation-id`, `x-attempt-id`를 넣는다. Assertion/seed 요청에는 measured attempt ID를 넣지 않는다. 하나의 Git attempt에서 복수 HTTP check가 생길 수 있으므로 validator는 attempt별 **한 개 이상** ALLOW check를 요구하고 실제 개수를 기록한다.

Gated Git transport에는 `http.followRedirects=false`를 적용해 canonical direct endpoint로 redirect되면 성공으로 처리하지 않는다. curl API command도 redirect를 따라가지 않는다. 기존 direct Git transport 설정은 유지한다.

Provider header allowlist에는 correlation과 `x-gate-test-deny`만 넣고 body buffering을 사용하지 않는다. Selected Envoy HTTP check는 `Authorization`을 기본 포함하므로 allowlist만으로 credential value를 제외할 수 없었다. Supported `includeAdditionalHeadersInCheck`로 check copy의 `authorization`을 비밀이 아닌 고정 값 `p4-check-without-credentials`로 덮어쓴다. Original Forgejo request의 credential은 유지한다. App은 header **이름**, credential-values-absent/body-absent boolean, safe bounded correlation ID, fixed HAProxy-hop 판정과 decision만 기록한다. Authorization의 모든 duplicate 값이 고정 값 하나와 일치하지 않거나 Cookie/Proxy-Authorization/body가 check에 도달하거나 HAProxy hop이 없으면 fail closed한다. Path/query와 header value 및 body는 기록하지 않는다. Proxy access log도 status/detail/upstream-cluster/upstream-host만 남긴다. Non-mutating `GET /api/v1/version`에 sentinel Authorization/Cookie/body와 controlled deny header를 보내 403/DENY, 빈 body와 ingress `ext_authz_denied`/upstream 미호출을 검사한다. 이 probe의 실제 check exclusion 검사가 성공하기 전에는 developer credential을 gated endpoint에 보내지 않는다.

`results/local/shared-gate-<id>/`는 source SHA/dirty, direct baseline, image identity, rendered experiment source, owned resource UID, selected proxy config/version/stat inventory, check JSONL, narrow HAProxy/proxy path evidence, DENY와 removal/result를 보존한다. Journey `events.jsonl`은 기존 operation artifact allowlist가 보존한다. Full config dump, certificates, raw HTTP response, kubeconfig/credentials/temp directory는 artifact에 넣지 않는다. Check log와 phase log는 append-only이고 실패 phase도 보존한다. Dirty run은 exploratory로만 분류하며 final validator는 clean source를 요구한다.

Removal은 현재 server ID와 installed object UID/owner를 다시 확인한 뒤 exact experiment manifests만 삭제한다. 같은 cluster에서 experiment namespaces/CRDs/cluster-scoped inventory 부재, reliability endpoint 부재, stable Forgejo spec/UID 유지, Argo exact revision의 `Synced/Healthy`, direct developer journey를 검사한 후 invocation-owned cluster cleanup으로 진행한다. 전체 cluster 삭제만으로 fixture 제거를 주장하지 않는다.

W1의 stat inventory는 actual version에서 관측한 이름/값만 기록한다. `upstream_rq_active_overflow`의 존재 여부는 기록하되 saturation/rejection signal 검증으로 승격하지 않는다. W1은 Linux/amd64 Local HTTP proof이며 saturation/load calibration/retry amplification/P5 Azure source는 포함하지 않는다.

## P4-W2 active-request saturation / bounded retry

`make local`은 W1 healthy journey와 credential/body exclusion을 먼저 확인한 뒤 같은 fixture에서 `scripts/shared-gate-saturation.py`를 실행한다. W1의 기본 `maxRequests=1024`, hold `0`은 유지한다. Target Pod의 `proxy.istio.io/config` `ProxyStatsMatcher`에는 `upstream_rq_active`, `upstream_rq_active_overflow`, `upstream_rq_total`, `upstream_rq_pending_active`, `upstream_rq_pending_overflow` suffix만 추가한다. Mesh 전체 stat enablement나 `EnvoyFilter`는 사용하지 않는다. Actual bootstrap matcher와 target cluster의 실제 stat 이름을 별도로 보존한다.

### Official upstream revalidation (2026-10-01)

[Sidecar inbound connection pool](https://istio.io/latest/docs/reference/config/networking/sidecar/)과 selected [1.30.5 mapping source](https://github.com/istio/istio/blob/1.30.5/pilot/pkg/networking/core/cluster_traffic_policy.go)는 `http2MaxRequests`를 Envoy `maxRequests`로 변환한다. [Envoy 1.38 변경 기록](https://www.envoyproxy.io/docs/envoy/latest/version_history/v1.38/v1.38.0)은 exhausted `max_requests`의 authoritative rejection signal을 `upstream_rq_active_overflow`로 구분한다. Selected [connection-pool source](https://github.com/envoyproxy/envoy/blob/a3357a295443d008c6aec4c3d508745d9b002f40/source/common/conn_pool/conn_pool_base.cc)와 [runtime guard source](https://github.com/envoyproxy/envoy/blob/a3357a295443d008c6aec4c3d508745d9b002f40/source/common/runtime/runtime_features.cc)도 확인했다. `envoy.reloadable_features.skip_pending_overflow_count_on_active_rq`를 수정하지 않고 admin의 해당 entry와 실제 active/pending overflow delta를 기록한다. Entry가 없는 경우 default source와 측정한 effective behavior를 구분한다.

[Istio stat 설정](https://istio.io/latest/docs/ops/configuration/telemetry/envoy-stats/)은 workload annotation으로 `ProxyStatsMatcher`를 적용할 수 있음을 명시한다. [ext_authz API](https://www.envoyproxy.io/docs/envoy/latest/api-v3/extensions/filters/http/ext_authz/v3/ext_authz.proto)는 `failure_mode_allow=false`의 check error/5xx가 downstream rejection으로 전달됨을 설명한다. Client status를 mechanism counter로 대신 사용하지 않는다. 실제 status/detail은 각 run에서 기록하고 판정한다.

### Calibration / frozen measurement

Experiment ConfigMap의 hold 파일은 허용된 check에만 non-CPU-spin delay를 적용한다. Request header/query로 duration을 선택하지 않으며, app이 `0..2000 ms` 범위 밖 값을 거부한다. Source `experiments/fixtures/shared-gate/saturation.json`의 단일 bounded 후보는 `max_requests=2`, `hold_ms=1000`, logical operations `24`, concurrency `12`다. Calibration이 actual capacity, non-zero active overflow, client impact, direct sentinel, confounder guard를 모두 만족하면 **값을 바꾸지 않고** `frozen.json`을 exclusive-create한다. 실패하면 추가 tuning/acceptance 완화 없이 중단한다. Calibration은 final proof가 아니다.

Measured load는 W1 healthy developer fixture의 기존 private Issue를 읽는 authenticated `GET` 하나다. No-retry와 retry는 같은 frozen demand/runtime/hold/capacity/concurrency를 사용하고 client `max_attempts`만 `1 → 2`로 바꾼다. 실패한 operation에 즉시 최대 한 번 retry하며 HAProxy/Forgejo route retry는 계속 `0`이다. P3의 9-operation schema는 변경하지 않는다. Experiment JSONL은 operation/attempt ID, HTTP status, semantic read outcome, monotonic timing을 기록한다. Body/credential/path는 보존하지 않는다.

`authorization_checks`는 HAProxy backend가 target에 전달하고 응답받은 HTTP check 수이며 **inbound에서 거절된 check도 포함**한다. `admitted_app_checks`는 실제 app의 ALLOW 기록 수다. Target inbound access-log 수, target active overflow, app/target upstream total, ingress `ext_authz_error`와 client failure 수를 같은 격리된 run window에서 대조한다. App correlation은 operation/attempt ID로 확인한다. 이 좁은 HTTP read의 dispatch count가 client attempt와 맞는지 검사할 뿐, 일반 Git operation의 HTTP 수를 1:1로 가정하지 않는다.

Direct-path의 같은 authenticated Issue read와 `/api/healthz`를 부하 중 반복해 모든 응답과 gated failure의 시간 overlap을 확인한다. 전/중/후 Pod Ready/UID/restart, node Ready/pressure, PostgreSQL read-only query와 connections/max/reserved/state inventory를 검사한다. HAProxy queue/error/retry/response counters를 기록하고 competing limit/error가 있으면 invalid로 중단한다. CPU/memory metrics API가 있으면 관측값을 기록하며 기존 Local cluster가 metrics-server를 끈 상태이면 unavailable로 남긴다. 임의 latency/SLO threshold를 추가하지 않는다.

`results/local/shared-gate-<id>/saturation/`은 calibration plan, frozen config/provenance, 각 run의 append-only events와 immutable configuration/before/after/path/summary, final result를 보존한다. Validator는 dirty source, 불완전 run, capacity/demand drift, missing/competing overflow, failed/non-overlapping sentinel, restart/pressure/DB exhaustion/HAProxy queue, count mismatch를 거부한다. Final result는 W1 건강 검증과 같은 cluster의 fixture removal/post-removal direct journey도 재검사한다. CI는 기존 45분 job과 P1/P2/P3 recovery/upgrade 경로를 유지하며 filename allowlist만 upload한다.

Retry amplification은 같은 logical demand의 attempt/check/shared-path request 증가로 판정한다. Overflow 증가나 reliability 개선/악화는 amplification의 필수 조건이 아니다. 이 증거는 Local Linux/amd64 loopback mechanism proof이며 Azure managed support, Azure SLO, HPA/KEDA/mitigation 또는 P5 구현을 주장하지 않는다.

## P3-W3 patch upgrade / state-aware rollback

`make upgrade`는 `scripts/local-recover.sh upgrade`를 사용한다. 기존 W2의 developer fixture, coordinated checkpoint, Secret/DB/full `/data` restore와 doctor validator를 재사용한다. 현재 drill은 2026-10-28 security pin revalidation에 따라 linux/amd64에서 `15.0.9-rootless`(A) → stable `15.0.11-rootless`(B) 한 pair만 검증한다. Official OCI index와 amd64 manifest digest는 `versions.env`의 W3 inventory로 구분한다. Kubernetes의 actual imageID와 init/application image도 비교하며, tag만으로 runtime identity를 주장하지 않는다.

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

### P6-W1 pair revalidation (2026-10-21)

위 2026-09-30 preflight와 기존 P3 evidence는 `15.0.8 → 15.0.9`의 역사적 기록이다.
당시 pair의 security/release/digest 근거는 [P6-W1 reconciliation](p5-preflight.md#p6-w1-securityversion-reconciliation--2026-10-21)에 있다.
당시 `15.0.9` A는 disposable loopback maintenance, stable/Azure source는 `15.0.10` B였다.
2026-10-28 security pin은 A를 유지하고 B만 `15.0.11`로 갱신한다. Release/digest/hash 근거는
[P6 security pin revalidation](p5-preflight.md#p6-forgejo-security-pin--2026-10-28)에 있다.
현재 pair도 release-note hash 변경, doctor/config/inventory 변화, DB authority/credential continuity 실패를
그대로 거부한다. 새 pair의 runtime 결과는 새 exact-head CI에서 확인하며 과거 evidence를 재사용하지 않는다.

### Regression / evidence

W3는 같은 source의 P1/P2 runtime regression, P3-W1 baseline, W2 recovery를 먼저 성공시켜야 한다. CI는 앞선 lifecycle/recovery step의 explicit result path를 전달해 중복 실행을 피하고, local standalone invocation은 해당 regression을 직접 실행한다. 기존 CI 45분 bound는 실제 full job 실행으로 확인한다.

`results/local/upgrade-<id>/`에는 checkpoint component hash/size, upstream hash/reference, stage별 runtime/DB authority/storage/credential hash, doctor 분류, B marker/absence/new write, regression과 append-only phase만 남긴다. Raw dump, tar, Secrets, password, PAT, cookie, config/env와 응답은 mode 0700 temporary directory에 두고 성공/실패 모두 제거한다. CI artifact는 sanitized filename allowlist만 사용한다. Validator는 lifecycle 순서, freshness, credential continuity, doctor와 marker proof 누락/모순을 거부한다. Dirty development run은 exploratory이며 final `validate-upgrade.py result`는 clean exact-head source를 요구한다.

## P7 Azure operations

P7-W1 Task 2는 사용자의 명시적 통합 승인 후 기존 환경에서 실행했다.
[실행·정리 evidence](evidence/p7-operations-20261028/execution.json)에 실제 결과와 실패·제한을 구분했다.
HTTPS baseline 45/45, metrics/logs와 별도 mechanism visibility, fresh restore/upgrade/state-aware rollback을 검증했다.
공개 maintenance 합계는 약 275초이며 stable revision·Argo policy·shared MeshConfig/bootstrap은 복귀했다.
이 기록이나 script invocation 예시는 다음 유료 실행·IAM·maintenance·rotation 생략의 승인이 아니다.
P7 전체는 같은 branch/draft PR에서 이어간다.
별도 campaign timeout이나 삭제 예약은 없다. 보존 기한·다음 실행 승인은
[Paid Azure boundary](implementation-plan.md#paid-azure-boundary--p6p11)를 따른다.

P6 `results/raw/p6-platform-20261028T0222Z/platform-bootstrap-final-20261028T070825Z.json`
**원본**을 기존 operator checkout에서 읽었다. Source/deployed revision은
`2f63d283ebba12aaed8705732f1206d71ddc33db`, stable은 `15.0.11+gitea-1.22.0`이며
P6의 client는 독립 확인한 public A에 process-scoped curl/Git resolve를 사용했다.
P6 전달 보고만으로 P7 baseline을 대체하지 않으며 기존 raw 파일은 수정하지 않는다.

### HTTPS baseline / correlation / SLO

기존 producer `tests/e2e/forgejo-developer-journey.sh`의 operation 9개, attempt 1개,
command timing·semantic assertion·timeout은 동일하다. `JOURNEY_ENVIRONMENT=azure-aks`는
public HTTPS hostname origin만 허용한다. Curl config/proxy 및 Git global/system config에서
격리하고 certificate/hostname 검증을 유지한다. `JOURNEY_DNS_OVERRIDE`는 선택한 public IPv4이며
모든 curl/Git command에 동일하게 적용한다. 이 경우 일반 client DNS 성공을 주장하지 않는다.
`JOURNEY_ENDPOINT_URL`로 Azure 공개 origin을 다른 endpoint로 바꿀 수 없다.
Local HTTP loopback과 Azure HTTPS는 closed boundary이며 임의 문자열은 거부한다.

Producer는 `transport`(endpoint/scheme/TLS/DNS override)와 실제 environment를 기록하고,
validator는 이를 검사하며 summary에도 보존한다. Legacy Local raw의 transport 부재는
그대로 지원한다. Transport/environment/deployed revision/runtime image가 다른 run은 하나의
baseline으로 합칠 수 없다. Source execution SHA와 stable deployed revision은 별개다.

승인 후 operator는 기존 Local context와 같은 sanitized field만 가진 `context.json`을 준비한다.
`source_sha`는 clean execution HEAD, `argo_values_revision`은 **유지할 실제 stable revision**이다.
`environment.kind=azure-aks`와 actual `cluster_resource_id`, `cluster_uid`(kube-system Namespace UID),
Kubernetes/managed Istio revision을 기록한다. `runtime_images`는 actual Forgejo imageID와 managed
PostgreSQL server version, `tool_versions`는 실제 client version이다. Chart version/digest도 actual
Argo status와 비교한다. URL/credential은 context에 넣지 않는다. 환경 변수로 trusted
`FORGEJO_URL`, admin credential, 필요 시 `JOURNEY_DNS_OVERRIDE`를 전달하며 shell tracing은 끈다.

```bash
# P7_PRIVATE는 repository 밖 mode 0700 보호 directory. 경로와 credential/cookie/checkpoint 내용은 evidence에 복사하지 않는다.
python3 scripts/azure-operations.py baseline "$P7_CONTEXT" "$P7_BASELINE_RESULTS" "$P7_PRIVATE"
```

Runner는 매 journey 전후 stable `Synced/Healthy`, automated/selfHeal ON/prune OFF,
deployed revisions와 ready Forgejo imageID를 검사한다. Warmup 1 + measured 5 journey,
measured 45 operations/45 attempts, concurrency=1/max_attempts=1을 바꾸지 않는다.
실패한 output directory는 보존하고 새 invocation에 재사용하지 않는다. Private directory의 6개
fixture credential은 최종 PAT 회수까지 보호하며 삭제/회수 여부를 실제 확인한다.

`query identity` JSON은 실제 `cluster_resource_id`, selected proxy `namespace/pod/container=istio-proxy`,
admin `admin_cluster_name`과 Prometheus cluster label 값인 `envoy_cluster_name`, existing
`prometheus_endpoint`와 `log_workspace_id`, actual `prometheus_cluster` label 값이다. 예시 이름으로 runtime identity를 채우지 않는다.
실제 exported label key가 `cluster_name`이면 `envoy_cluster_label=cluster_name`을 명시한다.
기존 `envoy_cluster_name` key도 지원하며 이 두 key 이외의 임의 label은 거부한다.

```bash
python3 scripts/azure-operations.py proxy-snapshot "$P7_QUERY_IDENTITY" "$P7_PROXY_BEFORE"
python3 scripts/azure-operations.py queries "$P7_BASELINE_RESULTS/baseline-summary.json" "$P7_QUERY_IDENTITY" "$P7_QUERY_PLAN"
python3 scripts/azure-operations.py collect "$P7_QUERY_PLAN" "$P7_QUERY_RESULTS"
python3 scripts/azure-operations.py proxy-snapshot "$P7_QUERY_IDENTITY" "$P7_PROXY_AFTER"
```

`proxy-snapshot`은 actual Pod UID/node/image spec/imageID/restart, proxy build version,
selected active cluster의 name/alt_stat_name과 native stat prefix·관측 counter를 남긴다.
Raw config dump/certificate/Secret은 보존하지 않는다. Managed runtime의 실제 cluster/stat
mapping과 Prometheus label을 대조하며 Local Envoy build/recipe를 Azure identity로 쓰지 않는다.
Default stat visibility에 없는 counter는 missing으로 남긴다. P7 실제 실행에서는 부재를 확인한 뒤
기존 operator-owned shared MeshConfig의 `defaultConfig.proxyStatsMatcher`에 다섯 suffix만 임시 추가했다.
이는 [AKS Allowed but outside support](https://learn.microsoft.com/en-us/azure/aks/istio-meshconfig) 경계다.
Stable 재기동 후 실제 native sidecar bootstrap·admin stat·Prometheus label을 확인했으며,
원래 shared ConfigMap과 bootstrap은 종료 시 복귀한다. P8에서 다시 사용하려면 그 실행의 승인 범위에 포함한다.
Managed controller Deployment나 Argo-owned Pod template을 수정하지 않는다.

Query는 기존 `forgejo`/`azure-stable-envoy` scrape의 `up`과 selected cluster의 active/active-overflow,
pending-active/pending-overflow/total을 같은 measured window로 조회한다. Series가 없으면 `no-data`,
관측 sample이 0이면 실제 0이며 `or vector(0)`으로 메우지 않는다. `up=0`은 scrape failure다.
Prometheus 관측 series의 actual `cluster/job/instance/namespace/pod`와 선택한 cluster label을 보존하고,
모든 query는 확인한 actual `cluster` label로 scope를 제한하며 반환 series의 cluster도 검사한다. Label mapping을 확인하기 전 exit evidence로 승격하지 않는다.
Overflow 0은 visibility evidence이며 saturation/rejection proof가 아니다. P8 fault/retry/scaling은 실행하지 않는다.

Log Analytics는 같은 AKS resource ID·window·Forgejo/selected proxy workload의 ContainerLogV2를
count/first/last timestamp로 조회한다. Raw log message/body/header/URL은 artifact에 넣지 않는다.
빈 rows와 query error도 각각 `no-data`와 `query-failed`로 보존한다. Ingestion 지연 후 재조회는
같은 window를 새 output directory에 보존하며 이전 실패를 덮지 않는다.

Client JSONL의 `run_id → operation_id → attempt_id`와 UTC command timestamp/monotonic duration을
operation별로 확인하고, summary의 measured window와 query plan/result·Pod identity를 연결한다.
API/Git measured command에 client correlation header를 보내지만 현재 safe server log에는 그 ID가 없다.
따라서 **server 연계는 동일 시간 구간 + workload**, request-level join/distributed tracing은
**not verified**다. Git attempt 하나의 내부 HTTP 수를 추정하지 않는다. Tracing은 P7 exit 필수가 아니다.

초기 SLO는 Task 2 baseline 뒤 operation별 count/min/max/mean, 실제 성공/실패 분모와
Service Active Window(첫 measured 시작→마지막 종료, 실패 구간을 빼지 않음)를 근거로 결정한다.
선택한 성공률/command latency threshold와 관측값·여유분 근거·적용 window·execution source를
sanitized reviewed evidence에 기록하고 P8 fault **전에 고정**한다. 작은 표본의 production percentile,
월간/24×7 목표나 Local sample로 Azure threshold를 만들지 않는다.
2026-10-28 HTTPS baseline 뒤 [초기 SLO](evidence/p7-operations-20261028/initial-slo.json)를 P8 fault 전에 고정했다.
Controlled Service Active Window 성공률 목표는 1.0이며, operation별 command latency 상한은
관측 maximum의 두 배를 0.1초 단위로 올림한 초기 운영 여유다. Production percentile 추정값이 아니다.

2026-10-28 upstream 확인: [Managed Prometheus REST/PromQL](https://learn.microsoft.com/en-us/azure/azure-monitor/metrics/prometheus-api-promql),
[Log Analytics query/time range](https://learn.microsoft.com/en-us/azure/azure-monitor/logs/api/request-format),
[Forgejo v15 upgrade guide](https://forgejo.org/docs/v15.0/admin/upgrade/).
기존 Entra operator credential로 query하며 새 app registration/IAM grant를 자동 생성하지 않는다.

### Coordinated Azure checkpoint / private fresh target

기존 Local `local-recover.sh`는 cluster create/delete와 in-cluster PostgreSQL이 hardcoded여서 Azure에서
그대로 호출하지 않는다. 아래 operator 절차와 `azure-recovery.py` adapter만 사용한다. P3 doctor parser,
selected check/known diagnostic, developer `verify`/`write`, DB authority validator는 재사용한다.

Operator의 non-secret input JSON은 정확히 `campaign`, `stage`(`restore|a|rollback`), execution
`source_sha`, `stable_deployed_revision`, `stable`, `target`을 가진다. `stable`에는 actual
`namespace=forgejo/deployment=forgejo/pvc=forgejo-data`, `db_host/db_name/db_role`,
`pvc_uid/pv_uid/pv_name/disk_id`를 기록한다. `target`은 `namespace=p7-ops-<campaign>`,
`pvc=p7-data`, 같은 기존 server의 `db_host`, **private** `db_ipv4`,
`db_name=p7_<campaign>_<stage>`, `db_role=p7_<campaign>_role`이다.
현재 live source와 input이 다르면 시작하지 않는다. Branch PR HEAD로 stable renderer/main-only gate를 우회하지 않는다.

```bash
python3 scripts/azure-recovery.py render "$P7_RECOVERY_INPUT" "$P7_RENDERED"
```

Render는 배포하지 않는다. `boundary.json`(private Namespace/ResourceQuota),
`pvc.json`, `helper.json`, `db-client.json`, `app.json`은 별도 파일이다. Stage `a`에만 exact B의
`app-b.json`도 있다. Source checkpoint용 `checkpoint-helper.json`/`checkpoint-db.json`은
`forgejo` namespace의 임시 Pod이며 stable controller에 넣지 않는다. Helper는 original PVC를
**read-only** mount하고 fsGroup 변경도 하지 않는다. Source DB client는 기존 app role/Secret을 참조한다.
Target app은 Secret volume의 password로 rebind한 `/data` config만 사용하고 DB environment override가 없다.
Old A에는 Service/Ingress/Gateway/VirtualService를 만들지 않는다. Rebind는 `server.HTTP_ADDR=127.0.0.1`도 고정하고 exec readiness도 Pod loopback을 사용한다. 현재 AKS source는 NetworkPolicy enforcement를 설정하지 않으므로 NetworkPolicy object로 격리를 주장하지 않는다. 실제 listen socket/Pod IP 접근 거부를 시작 직후 확인하고 operator port-forward로만 접근한다.
Pod는 injection OFF, SA token automount OFF다. New controller/Argo Application을 만들지 않는다.

Temporary Pod는 전체 동시 2개, admitted requests 합계 CPU 750m/memory 1536Mi 이하다.
App 500m/1024Mi + DB client 250m/512Mi, helper 100m/128Mi이며 source/target helper를 겹치지 않는다.
Namespace quota와 별도로 각 admission 뒤 **모든 namespace의** campaign Pod를 조회해 검사한다.
Injection/init/ephemeral container가 생기면 중단하며 overhead도 예산에 더한다.

```bash
kubectl --request-timeout=15s get pods -A -l "p7.campaign=$P7_CAMPAIGN" -o json >"$P7_PRIVATE/admitted.json"
python3 scripts/azure-recovery.py admission "$P7_RECOVERY_INPUT" "$P7_PRIVATE/admitted.json"
```

승인 후 checkpoint 순서:

1. Source Git/API state와 non-admin PAT·native session을 준비·확인한다. 추가 fixture는 baseline 밖이다.
   `RECOVERY_FIXTURE=1`로 기존 journey `create`를 사용하고 fixture의 credential/state file hash를 보호한다.
   Source app/Pod UID, imageID/version, Argo policy/spec/revisions, PVC/PV/Disk, DB engine version/owner,
   필요한 `forgejo-admin/forgejo-db/forgejo-inline-config` Secret key/version metadata를 고정한다.
2. 외부 writer를 quiesce하고 operator 외 쓰기 부재를 확인한다. Argo operation이 없음을 확인한 뒤
   `forgejo-azure`의 automated.enabled만 false로 pause한다. Exact source와 나머지 policy를 유지한다.
   기존 `forgejo manager flush-queues --config /data/gitea/conf/app.ini --timeout 2m`를
   `timeout -k 5s 150s kubectl … exec`로 실행한다. Deployment replicas=0 → original Pod delete를
   bounded wait하고 label selector로 writer Pod 부재를 재확인한다. 아직 DB/data backup을 시작하지 않는다.
3. Rendered source DB/helper Pod만 명시 apply한다. Admission을 검사한 뒤 원본 DB를
   `pg_dump -Fc --no-owner`로, full `/data`를 `tar -C /data -cf - .`로 보호된 operator checkpoint에
   stream한다. DB client의 `PGSSLMODE=verify-full/PGSSLROOTCERT=system`은 유지한다.
   필요한 세 Secret은 private mode 0600 `secrets.json` list에 저장한다. Manifest는 아래 계약을 따른다.
4. `azure-recovery.py bundle`이 성공하면 source helper/DB client 두 Pod만 삭제·부재 확인한다.
   Stable replicas를 기존 값으로 복귀하고 원래 automated policy(ON/selfHeal ON/prune OFF)를 되돌린다.
   Original spec/revision, readiness/health, 같은 source fixture readback을 확인한다.
   이 **stable 재개 뒤** 나머지 drill을 private fresh target에서 수행한다. 실패 시 원본을 삭제하거나
   checkpoint로 덮지 않으며 stable 복귀 상태와 실패를 기록한다.

Private checkpoint의 `manifest.json`은 `input`, `backup_complete`, `writer_absent`, `queue_flushed`,
actual `version`, pinned `image_spec`, actual `image_id`, `components`를 가진다. Components는 `database.dump`,
`application-data.tar`, `secrets.json` 각각의 streaming SHA256/positive byte size다. Checkpoint 자체는
0700, 파일은 0600이고 총 16GiB 이내다. 실제 source Pod imageID와 component/Secret version metadata는
별도 sanitized evidence로 연결한다. Binary 파일/Secret 값/PAT/cookie/app.ini는 upload하지 않는다.
`bundle`은 component hash/size, archive path/link 안전성, Azure Secret inventory와 exact version을 검사한다.

```bash
python3 scripts/azure-recovery.py bundle "$P7_CHECKPOINT"
```

Fresh restore는 stable 15.0.11 checkpoint를 사용한다. DB administrator 사용 승인을 받은 뒤 기존
private operator DB 경로에서 **새 temp role 하나**와 role-owned fresh DB를 생성한다. 예전 DB가 있으면
DROP/overwrite하지 않고 중단한다. Password는 random alphanumeric 32–128자 protected file와
interactive `psql \password`로 설정하며 SQL literal/argv/history에 넣지 않는다. Target namespace에
`p7-credential` Secret 하나(`password` key)만 `--from-file`로 만든다. 다른 source Secret을 target에
세 개 더 만들지 않는다. Signing/session/internal key는 `/data`의 restored config로 유지한다.

Fresh DB/target PVC 준비 뒤 original DB/PVC가 아님을 검사한다. Target DB client로 read-only query:

```sql
SELECT json_build_object(
 'current_database',current_database(),'current_user',current_user,
 'owner',(SELECT pg_get_userbyid(datdba) FROM pg_database WHERE datname=current_database()),
 'server_address',host(inet_server_addr()),'ssl',(SELECT ssl FROM pg_stat_ssl WHERE pid=pg_backend_pid()),
 'public_tables',(SELECT count(*) FROM information_schema.tables WHERE table_schema='public'),
 'other_sessions',(SELECT count(*) FROM pg_stat_activity WHERE datname=current_database() AND pid<>pg_backend_pid()));
```

다른 sessions가 보이지 않는 권한이면 exclusivity를 추정하지 않고 승인된 administrator가 확인한다.
DB owner만으로 `public` schema CREATE 권한을 추정하지 않는다. Fresh target DB에서
`has_schema_privilege(current_user,'public','CREATE')`를 확인하고, 없으면 승인된 administrator가
**그 fresh DB에만** 임시 role의 `USAGE, CREATE ON SCHEMA public`을 부여한다. 원본 schema/role은 변경하지 않는다.
Source DB에 접속한 상태에서 target SQL을 실행하지 않는다. Namespace/PVC/PV의 live JSON,
위 DB JSON을 각각 `namespace/pvc/pv/database`에 넣고 `pods=[]`를 live 조회로 확인한 snapshot을 만든다.
DB query 후 client Pod도 제거한다. Tar에서 app.ini만 private copy로 추출해 rebind한 뒤 guard한다.

```bash
python3 scripts/azure-recovery.py rebind "$P7_RECOVERY_INPUT" "$P7_PRIVATE/restored-app.ini" "$P7_PRIVATE/db-password"
python3 scripts/azure-recovery.py guard "$P7_RECOVERY_INPUT" "$P7_PRIVATE/target-snapshot.json" "$P7_PRIVATE/restored-app.ini" >"$P7_FRESH_GUARD"
```

Guard는 target ownership label, distinct PVC UID/PV UID/name/Disk ID, claimRef, 10Gi managed-csi,
role-owned empty DB/session 부재, target-only DB config를 요구한다. 소유권이 모호하거나 source DB를
가리키면 **시작하지 않는다**. Snapshot과 source input의 capture time/cluster UID도 evidence에 연결한다.

Guard 뒤 helper/DB client를 다시 만들고 fresh DB에 `pg_restore --exit-on-error --no-owner --no-acl`,
empty PVC에 `tar -C /data -xf -`로 **완전한 checkpoint**를 복원한다. Rebind한 app.ini를 helper를 통해
`/data/gitea/conf/app.ini`에 mode 0600으로 교체한다. Signing/session config는 유지하며 temporary DB
HOST/NAME/USER/PASSWD/SSL_MODE와 private HTTP_ADDR만 달라야 한다. Source `secrets.json`은 보호·비교용이며 target에 apply하지 않는다.
Helper에서 app.ini를 다시 private file로 읽고 `azure-recovery.py config`로 target binding을 검증한다.
DB data/table owner·original row/DB authority를 확인하고 helper를 삭제한 뒤에만 `app.json`을 apply한다.
Effective Pod에는 추가 envFrom/DB URL/GITEA__/FORGEJO__ override가 없어야 한다. Admission과 actual
version/imageID, `/api/healthz`를 확인한다. Mount/bootstrap이 임의 config를 재생성하면 중단한다.

Private access는 `kubectl -n "$P7_NAMESPACE" port-forward --address 127.0.0.1 pod/p7-forgejo 13001:3000`이다.
기존 journey `verify`/`write`에 `FORGEJO_URL`은 original advertised HTTPS origin,
`JOURNEY_ENDPOINT_URL=http://127.0.0.1:13001`, `JOURNEY_ENVIRONMENT=local-k3d`를 전달한다.
이는 **측정하지 않는 private tunnel**이며 Local baseline이라고 기록하지 않는다. RESULT_*와 public
DNS override는 전달하지 않는다. 기존 clone remote는 command-scoped insteadOf로 private endpoint에
보내므로 restore 검증이 공개 stable을 읽는 실수를 막는다. Private fixture directory는 원본과 별도 복사하고
PAT/session 값 hash는 같아야 한다.

`azure-recovery-check.sh doctor`는 `P7_NAMESPACE/P7_POD/P7_PRIVATE/P7_DOCTOR_OUTPUT`을 받아
기존 `validate-recovery.py doctor-upgrade`를 실행한다. 최초 `P7_DOCTOR_SOURCE=-`, 다음 stage는
source sanitized doctor JSON을 준다. Selected integrity check, exact paths diagnostic, effective
LFS/SSH/log config가 기존 P3와 다르면 성공으로 완화하지 않는다. `--fix`는 사용하지 않는다.
`session-login`은 healthy stable source에서 한 번만 HTTPS native login한다(`DEV_USER/DEV_PASSWORD`,
source private port-forward의 `P7_PRIVATE_URL` 필요). `session-verify`는 **동일 cookie 값**을 private
tunnel로 replay하여 protected settings 200/developer identity와 원본 cookie file hash를 검사한다.
Fresh A fixture는 `P7_NAMESPACE=p7-ops-…`일 때 같은 login mode가 private tunnel에서 한 번만 로그인하고 그 cookie를 B/rollback에서도 재사용한다. 이는 persisted native session state의 적용 가능한 continuity이며 HTTP browser Secure-cookie 동작을 주장하지 않는다.

State 판정은 기존 journey의 main/feature SHA, private repository, PR/Issue API와 같은 PAT readback,
DB row 및 `/data/git/gitea-repositories/<developer>/journey.git`의 Git ref/object를 함께 비교한다.
복구 후 새 `write`의 commit/Issue가 API/DB/filesystem에 존재해야 한다. Credential 대체/재로그인으로
continuity를 통과시키지 않는다. Recovery 결과는 operator의 순서별 append-only phase와 실제 command
exit, checkpoint hash/fresh guard/doctor/state proof를 연결하고 Local cluster lifecycle validator에
가짜 server/Pod/PVC ID를 넣어 Azure PASS를 만들지 않는다.

### Private upgrade / state-aware rollback / 종료

Stable fresh restore를 정리한 뒤 같은 temporary role/credential Secret을 사용해 **다른 fresh DB/PVC**에
15.0.9(A)를 시작한다. A의 config만 stable checkpoint에서 private copy해 target DB로 rebind하며
**stable DB/data를 A로 가져오지 않는다**. Empty PVC에 config와 필요한 root directory만 준비하고
empty DB guard를 검사한 뒤 A가 fresh schema를 초기화하게 한다. Native rootless image의 effective
config/path를 확인한다. Fresh A의 admin은 [v15 CLI](https://forgejo.org/docs/v15.0/admin/command-line/)의
`forgejo admin user create --admin --username p7admin --email p7admin@example.com --random-password
--random-password-length 32 --must-change-password=false --config /data/gitea/conf/app.ini`로
생성하고 출력은 protected 0600 file로만 받는다. 생성 password를 private operator environment로 읽어
기존 non-admin developer fixture를 준비하며 password/CLI 출력은 evidence에 복사하지 않는다.
Stage `a`의 empty DB/PVC guard를 유지하고, A fixture/PAT/session·doctor·세 DB
authority(`version`, `forgejo_version`, `forgejo_migration`)를 기록한다. 기존
`validate-upgrade.py database_authority` 계약으로 actual catalog/row/ID inventory를 검사한다.
A queue flush → graceful stop → writer 없음 → full A checkpoint(DB/data와 필요한 config/Secret version)를 만든다. A checkpoint는 input stage `a`와 target의 단일 temporary Secret inventory로 같은 `bundle` validator를 사용한다. Stable의 세 Secret inventory를 복제하지 않는다. Component hash/size·16GiB·보호 mode와 signing/session config를 같은 방법으로 확인한다. Helper·DB client는 같은
render 경로를 쓰되 A data에 stable read-only checkpoint helper를 잘못 붙이지 않는다.

각 version transition은 old app Pod의 graceful deletion/UID 부재를 확인한 뒤 새 Pod를 생성한다. 동일 private A DB/PVC에서 helper 없이 `app-b.json`으로 exact 15.0.11(B)를 시작한다. Actual B
image spec/imageID/version, same PAT/session, original state·doctor·DB authority를 검증한다.
`journey write b-only`로 B-only Git commit/Issue를 만들고 API/DB/filesystem persistence를 확인한다.
단순 application patch 변경을 DB migration이라고 부르지 않는다. B-only marker와 A fixture를 보존하고
B queue flush/graceful stop을 확인한다. B target의 temporary Pod/DB/PVC/Disk만 UID로 정리한다.

Rollback은 stage `rollback`의 **또 다른 fresh** DB/PVC에 **A checkpoint 전체 + A version**을 복원한다.
B state에 A binary를 실행하거나 migration metadata를 수정하지 않는다. A/rollback DB authority가 같고,
original state·같은 PAT/session·doctor가 유지되어야 한다. 새 rollback write **전에** B-only Issue API 404와
DB row 부재, original main SHA 복구, full Git object inventory에 B-only commit 부재를 확인한다.
그 후 `journey write`로 다른 commit/Issue를 생성하고 API/DB/filesystem persistence와 doctor를 재검증한다.
Private clone/work의 B-only `post-write.env`는 별도 보존하고 rollback fixture는 A checkpoint 시점 복사본을 쓴다.
번호 재사용은 title/commit identity로 구분한다. 구버전은 공개 stable 경로에 배포하지 않는다.

Temporary 10Gi PVC/Disk와 fresh DB는 동시 각각 1개, restore/A/rollback의 누적 각각 최대 3개다.
앞선 stage의 exact Pod/PVC/PV/Disk와 DB 부재를 확인하기 전 다음 fresh target을 만들지 않는다.
UID/Disk ID/DB owner가 inventory와 다르면 삭제하지 않는다. Stable DB/PVC, source revision,
Infrastructure/Terraform ownership은 유지한다. 성공/실패 모두 stable readiness·original Argo policy 복귀,
임시 Pod/PVC/Disk/DB/role/Secret·IAM exact assignment 부재, PAT 회수·cookie/checkpoint 보호 파일 제거를
각각 actual 조회로 확인한다. Rotation 생략은 새 explicit exception 승인 전 실행하지 않는다.
Final evidence는 execution HEAD와 stable deployed revision/runtime identity를 따로 기록하고 query no-data,
실패 phase, session/tracing 제한, ActualCost unknown을 숨기지 않는다. Runtime 확인 전 PASS/zero residual을 쓰지 않는다.
