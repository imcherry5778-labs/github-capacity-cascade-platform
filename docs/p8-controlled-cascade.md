# P8-W1 Controlled Cascade 실행 절차

현재 상태는 **source 준비 / Azure 실행 미승인**이다. 이 문서는 실행 승인이 아니다.
기준은 `a3bf43f4a2c423cfa7974d481a94f788149174aa`와 이번 session의 P8-W1 contract다.
P7의 [baseline](evidence/p7-operations-20261028/baseline-summary.json),
[고정 SLO](evidence/p7-operations-20261028/initial-slo.json),
[운영/정리 결과](evidence/p7-operations-20261028/execution.json)를 재사용한다.
P6/P7 전체 검증, recovery drill, KEDA, P9 recovery 비교, P10 isolation은 수행하지 않는다.

## 실행 순서와 승인 gate

1. [통합 승인 요청](evidence/p8-controlled-cascade-20261029/approval-request.md)의 exact source/target/범위를 승인받는다.
2. Repository 밖 mode 0700 directory와 그 안 mode 0600 전용 kubeconfig를 만든다. 현재 기본 kubeconfig는 다른 AWS cluster이므로 사용하지 않는다.
   승인된 principal에 해당 AKS resource만의 임시 `Azure Kubernetes Service RBAC Cluster Admin`을 부여하고 assignment ID를 보존한다.
   `az aks get-credentials --file`의 새 파일과 Entra user authentication을 사용한다. 인증 우회나 admin certificate는 사용하지 않는다.
3. Kubernetes API read로 cluster UID, managed revision, Argo sources/spec/revisions·Healthy/Synced,
   Forgejo 이미지/PVC/PV/Disk, 승인된 Forgejo hostname과 ingress selector, 기존 shared ConfigMap UID/resourceVersion/data와 P8 이름의 부재를 확인한다.
   Stable revision은 `2f63d283ebba12aaed8705732f1206d71ddc33db`로 유지한다.
   Operator-owned shared ConfigMap과 ingress namespace의 기존 policy 목록을 보호 directory에 저장한다.
   알려지지 않은 owner/동일 이름의 resource, stable drift, 새 managed revision이면 mutation 전에 중단한다.
4. 현재 Pod requests/limits·node allocatable/pressure·metrics API·HPA capability와 PostgreSQL headroom을 확인한다.
   신규 node/server/Disk/PVC 없이 두 번째 target Pod가 schedule될 여유가 있어야 한다.
   기존 node autoscaling은 OFF이며 이 값을 바꾸지 않는다. `ResourceQuota` 및 **실제 admission** 검사가 모두 필요하다.
5. 정확한 execution commit의 `cmd/ext-authz-sim/`과 `versions.env`의 base image로 local build하고
   기존 ACR의 **ext-authz-sim repository 하나**에 source-SHA tag로 push한다. 기존 tag를 덮지 않는다.
   Digest를 확인하여 identity의 `ext_authz_image`에 넣는다. Build source SHA와 published digest, 실제 Pod imageID는 별도 기록한다.
6. 기존 HTTPS 정상 journey를 **한 번** `create`하고 semantic result를 확인한다.
   P7처럼 warmup+5 baseline을 다시 만들지 않는다. 기존 P7 threshold를 변경하지 않는다.
   기존 native administrator는 승인된 fixture 준비에만 쓰고 측정은 새 non-admin developer/PAT로 한다.
7. 승인한 shared MeshConfig overlay → fixture → 건강/metric/admission 확인 → CUSTOM policy 순으로 적용한다.
   hold=0 / maxRequests=1024에서 별도 healthy-gate journey를 한 번 `create`한다.
   Controlled DENY와 credential/body exclusion, ingress filter/provider/hostname scope, no-retry route와 HAProxy 경로를 확인한다.
   Native auth의 무인증 private read 거부도 확인한다. 실패하면 fault를 시작하지 않는다.
8. 정상 HPA `ContainerResource(app,cpu)` metric·app requests 50m·controller 판단·replica 1→2 여유를 확인한 뒤 calibration한다.
   아래 candidate는 Azure 검증값이 아니다. 실패한 directory는 보존하고 필요한 bounded refinement는 별도 calibration으로 기록한다.
   Run은 13개 wave × 24 Issue operations, concurrency 12, wave 간격 10초 후보로 시작한다.
   이는 약 120초의 **반복 burst** 관측이며 지속적인 전체 window saturation을 주장하지 않는다.
   각 wave의 Git `ls-remote main` 1회도 같은 source/config/demand로 고정한다.
9. Calibration의 mechanism/impact와 전체 confounder review 뒤 freeze한다.
   Paired measured run은 `max_attempts=1 → 2`만 바꾼다. Replica/UID/config/source/demand/transport drift,
   wave pacing overrun, transport 오류, 필수 metric 부재, cap/scheduling 문제는 유효한 signal mismatch가 아니다.
10. 각 run의 같은 window에 기존 Managed Prometheus/Log Analytics와 ARM PostgreSQL metrics를 조회한다.
    Ingestion 지연/empty/error는 새 collection directory에 보존한다. No-data를 0/정상으로 대체하지 않는다.
    Runtime 결과와 confounder review가 끝난 뒤 paired result를 만든다.
11. CUSTOM policy를 **먼저** 제거하여 정상 request path로 복귀한다. 이후 원래 shared ConfigMap `data`를 UID/변경 전후 fingerprint로 확인해 복구한다.
    다른 operator의 중간 변경이 있으면 덮지 않고 보고한다. P8-only fields만 원복하며 default ConfigMap/managed controller를 수정하지 않는다.
    Fixture/HPA/Secret/namespace와 소유한 image tag/manifest, 임시 IAM assignment를 exact identity로 정리한다.
    정상 HTTPS journey `verify`, direct/native auth, Argo state/revision, 원래 resource identity와 P8 resource 부재를 확인한다.
    정상 서비스 복귀를 demand를 유지한 P9 recovery proof라고 부르지 않는다.
12. 두 fixture PAT를 exact token ID로 revoke하고 원래 token의 재사용 거부와 fixture login 차단을 확인한다.
    소유한 port-forward, 보호된 credential/kubeconfig 사본을 정리하고 raw/checksum/negative evidence·incident를 같은 PR에 추가한다.
    Environment/Foundation/Bootstrap은 기존 기한 그대로 보존한다.

## Adapter 입력과 사용

`scripts/azure-cascade.py`의 `render`/`mesh`는 파일 생성만 한다. Apply/delete/IAM/image push는 자동 실행하지 않는다.
`measure`는 **승인 후** 사용하며 `P8_AZURE_APPROVED`에 승인받은 exact execution SHA를 지정한다.
이 환경변수는 승인 기록의 대체물이 아니다. Clean source, 전용 kubeconfig, cluster UID와 ARM revision을 검사한다.
Environment 기한 뒤 새 workload 시작은 거부한다. 원복은 operator가 승인 범위 안에서 별도로 수행한다.

Identity JSON은 다음 non-secret field만 받는다. Runtime 전 actual 값으로 채우며 예시 값을 사용하지 않는다.

```json
{
  "campaign": "p8campaign",
  "source_sha": "<exact execution SHA>",
  "cluster_resource_id": "<actual AKS resource ID>",
  "cluster_uid": "<kube-system Namespace UID>",
  "revision": "asm-1-30",
  "stable_revision": "2f63d283ebba12aaed8705732f1206d71ddc33db",
  "ext_authz_image": "<actual ACR repository@sha256:digest>",
  "ingress_selector": {"istio": "<actual external gateway label>"},
  "forgejo_hostname": "forgejo.imcherry5778.xyz",
  "pg_resource_id": "<actual existing PostgreSQL resource ID>"
}
```

```bash
# 이 예시는 승인 뒤 보호된 operator context에서 실행한다. Private 경로/credential은 evidence에 복사하지 않는다.
python3 scripts/azure-cascade.py render "$P8_IDENTITY" "$P8_RENDERED"
python3 scripts/azure-cascade.py mesh "$P8_IDENTITY" "$P8_ORIGINAL_SHARED_CM" "$P8_MESH_PATCH"
```

Renderer는 별도 `fixtures.json` / `policy.json`을 만든다. Namespace는 `p8-shared-gate`, revision label을 사용한다.
P4의 HAProxy 설정을 재사용하지만 Local `Never`, `istio-injection=enabled`, `p4-ingress`와 Local gateway/VirtualService는 옮기지 않는다.
P8 resource는 Argo 대상이 아니며 stable main-only renderer 계약을 변경하지 않는다.
`forgejo_hostname`은 승인된 non-secret 소문자 DNS hostname이며 identity와 frozen configuration에 결합한다.
측정 `FORGEJO_URL`의 normalized hostname이 다르면 runtime 접근 전에 거부한다.
CUSTOM policy는 `to.operation.hosts`를 해당 hostname과 정확한 `hostname:443` 두 값으로 제한한다.
다른 hostname까지 매칭하는 wildcard/prefix, 빈 rule은 허용하지 않는다.
승인 뒤 매 run 전후 live policy의 selector/provider/hosts를 확인하고, 실제 gateway HTTP filter chain의
RBAC shadow policy가 같은 두 `:authority` exact matcher로 ext_authz를 활성화하는지 검사한다.
Policy UID/spec hash와 effective hostname scope도 frozen configuration에 기록한다.
이는 [선택한 Istio 1.30의 CUSTOM builder](https://github.com/istio/istio/blob/1.30.5/pilot/pkg/security/authz/builder/builder.go)와
[host matcher](https://github.com/istio/istio/blob/1.30.5/pilot/pkg/security/authz/matcher/header.go) 형식을 검증하는 경로다.
Actual managed gateway가 다른 형식이면 scope를 확인했다고 추정하지 않고 중단한다.
이 확인을 위해 stable Gateway/VirtualService/Argo source를 변경하거나 다른 host로 workload probe를 보내지 않는다.

`p8-db-read` Secret은 승인한 기존 **Forgejo application DB role**의 PSQL 환경변수만 담는다.
`PGHOST/PGPORT/PGDATABASE/PGUSER/PGPASSWORD`, `PGSSLMODE=verify-full`, 해당 image의 신뢰 CA bundle을 가리키는
`PGSSLROOTCERT`, `PGOPTIONS=-c default_transaction_read_only=on`을 사용한다. 실제 server hostname으로 인증서를 검증한다.
새 DB/role/DB admin credential은 만들거나 읽지 않는다. Helper는 Secret 참조만 가진 기존 PostgreSQL image의 단일 client Pod다.
SQL은 explicit READ ONLY transaction/statement timeout 안에서 connections/size와 정상 query를 확인한다.
SQL command latency에는 kubectl/exec 전송이 포함되므로 PostgreSQL 내부 query percentile로 해석하지 않는다.

Mesh overlay는 `aks-istio-system/istio-shared-configmap-asm-1-30`의 기존 JSON `mesh`에 provider와 다섯 stat suffix를 merge한다.
기존 provider/defaultConfig/다른 data key는 보존한다. 원본이 다른 encoding이거나 owner가 다르면 실패한다.
[Microsoft 공식 customization 문서](https://learn.microsoft.com/en-us/azure/aks/istio-meshconfig)의 revision-specific shared ConfigMap 경로를 따른다.
`extensionProviders`와 `defaultConfig.proxyStatsMatcher`는 **Allowed, Microsoft support 밖**이다.
Default ConfigMap 직접 수정, managed Deployment 변경, `EnvoyFilter` 우회는 없다.
Matcher가 적용된 뒤 새로 주입한 target Pod의 실제 bootstrap/build/stat inventory를 보존한다.
기존 stable Pod를 matcher 때문에 재기동할 필요는 없다. 기존 ingress의 dynamic provider/filter 수렴은 actual config로 확인한다.

Calibration 전에 ConfigMap hold와 Sidecar capacity를 candidate 값으로 patch하고 수렴을 확인한다.
HTTP2 active request capacity는 실제 app endpoint를 가진 inbound cluster와 해당 stat inventory로 확인한다.
`inbound|3000||` 또는 Local status mapping을 authority로 쓰지 않는다. Target 503/overflow → ingress ext_authz_error → developer status를 같은 run에서 대조한다.

```bash
# 별도 전용 port-forward가 안정된 Forgejo Pod의 3000을 127.0.0.1:13000에 연결한다.
# DEV_USER/DEV_TOKEN/ISSUE_NUMBER/ISSUE_TITLE/EXPECTED_MAIN_SHA는 healthy-gate fixture의 보호된 결과에서 읽는다.
python3 scripts/azure-cascade.py measure "$P8_IDENTITY" "$P8_SCENARIO" calibration "$P8_CALIBRATION"
python3 scripts/azure-cascade.py validate "$P8_CALIBRATION" "$P8_CALIBRATION/mechanism-summary.json"
python3 scripts/azure-cascade.py queries "$P8_CALIBRATION" "$P8_QUERY_IDENTITY" "$P8_CALIBRATION/cloud-plan.json"
python3 scripts/azure-operations.py collect "$P8_CALIBRATION/cloud-plan.json" "$P8_CALIBRATION/cloud-01"
python3 scripts/azure-cascade.py postgres-metrics "$P8_CALIBRATION" "$P8_CALIBRATION/postgres-01.json"
# 같은 window의 실제 관측 검토 후 confounder-review.json 작성
python3 scripts/azure-cascade.py freeze "$P8_CALIBRATION" "$P8_FROZEN"
python3 scripts/azure-cascade.py measure "$P8_IDENTITY" "$P8_SCENARIO" no-retry "$P8_NO_RETRY" "$P8_FROZEN"
python3 scripts/azure-cascade.py measure "$P8_IDENTITY" "$P8_SCENARIO" retry "$P8_RETRY" "$P8_FROZEN"
# 두 measured run에도 각각 동일 collection/review를 수행한 뒤:
python3 scripts/azure-cascade.py pair "$P8_NO_RETRY" "$P8_RETRY" "$P8_FROZEN" "$P8_PAIR_RESULT"
```

Query identity는 `cluster_resource_id`, 실제 `prometheus_cluster` label, 기존 `prometheus_endpoint`, `log_workspace_id` 네 field다.
`queries`는 run 자체의 window를 사용한다. P7 baseline의 window를 P8 run으로 바꿔 재사용하지 않는다.
`postgres-metrics`는 actual metric definitions에서 확인한 CPU/connections/storage/IO pressure를 기존 ARM 경로로 읽는다.
필수 query가 실패하면 별도 실패 기록과 새 output을 남긴다.

## 판정과 evidence

Public Issue read는 P7처럼 단일 curl-command monotonic timing과 native PAT/TLS verification을 사용한다.
Client retry는 실패한 idempotent read에만 한 번 즉시 허용한다. Writes/journey fixture 준비는 재시도하지 않는다.
Git read는 HTTPS `ls-remote refs/heads/main`의 actual expected SHA를 검사하며 retry하지 않는다.
이 결과를 P7 clone/fetch latency SLI의 동일 표본으로 합치지 않는다.
Logical operations/attempts/dispatch/admitted checks/active/rejection은 각각 별도 집계한다.
Git attempt의 내부 HTTP/check 수를 1로 가정하지 않는다. App에 admitted된 check만 correlation ID로 join할 수 있다.
전체 request-level tracing은 미검증이다.

HPA 관측은 actual metric timestamp 세 개 이상, 최소 60초 갱신 span과 전체 90초 이상 window를 요구한다.
[Kubernetes 문서](https://kubernetes.io/docs/concepts/workloads/autoscaling/horizontal-pod-autoscale/)의 기본 HPA sync period는 15초다.
AKS의 실제 control-plane flag를 확인했다고 주장하지 않으며, 반복 HPA status/currentMetrics와 실제 metrics API 갱신을 함께 기록한다.
하한 1 때문에 `TooFewReplicas`가 되는 정상 상태와 상한 2의 cap을 구분한다.
CPU signal이 올라가 scale되거나 metric/controller가 정상이 아니면 signal mismatch proof가 아니다.

`validate` 결과는 cloud guard 검토 전 `pending-cloud-confounder-review`다.
`confounder-review.json`은 `source_sha`, `fingerprint`, run의 정확한 `window_utc`, `competing_bottleneck=false`,
`missing_required_signals=[]` 및 아래 아홉 signal의 `signals` map을 가진다.
각 signal에는 `status=observed`, 실제 `samples`, `start_utc/end_utc`, 상대 `file`, 실제 file `sha256`,
수치·baseline/headroom·단위·aggregation·해석을 담은 `interpretation`을 기록한다.
Boolean만으로 통과하지 않는다. 실제 파일/window/checksum과 함께 operator가 관측 내용을 독립 검토한다.

- `forgejo_app_cpu_latency`, `forgejo_sidecar_cpu_pressure`
- `postgres_cpu`, `postgres_connections`, `postgres_latency`, `postgres_storage_io`
- `node_cpu_memory_scheduling`, `haproxy_queue_error_retry`, `direct_authenticated_sentinel`

Pod/container metrics에는 Forgejo/sidecar/helper/target별 CPU/memory, Pod health/restarts를 포함한다.
Direct authenticated sentinel은 fault와 겹쳐야 한다. Forgejo CPU/HTTP timing, sidecar saturation/CPU,
PostgreSQL CPU/connection/SQL command latency/storage/IO, node metrics/pressure/scheduling/headroom을 함께 해석한다.
필요한 추가 좁은 stat/metric 조회는 승인 범위에서 수행하고 실제 이름/수집 window를 보존한다.
필수 signal 부재나 경쟁 병목은 `unknown/invalid`로 남긴다. 동일 window의 metrics 지연 수집은 append-only 새 파일을 쓴다.
Raw는 append-only, negative/partial run은 보존한다. Source/config/Pod UID/imageID/build/stat mapping,
P7 SLO hash, measured/review/cleanup evidence를 연결하고 credential/private 경로/full proxy dump는 제외한다.
`pair` 성공도 cleanup이나 P8 전체 완료를 의미하지 않는다. 최종 claim은 실제 원복/정상 journey evidence까지 검토한 뒤 쓴다.
