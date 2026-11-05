# P10 — Critical/Bulk operation isolation (첫 implementation)

상태: **source 구현, cost-free 검증 범위는 [evidence](evidence/p10-source-20261105/README.md) 참조 / Azure 미실행 / P10 acceptance 미완료**.
Baseline `58fae6f105bd5bc28e2c85e05a138f6cb3e4ed03`에서 시작했다. [P8 incident](incidents/p8-controlled-cascade.md),
[P9 Campaign32](evidence/p9-mitigation-thirty-second-20261105/README.md)의 negative/valid accounting과 raw는 변경하지 않는다.
P9의 실행 승인·budget·counter를 재사용하지 않는다.

## 분류와 topology

분류는 **operation isolation**이다. Actor identity/role 보호가 아니며 Bulk actor가 같은 Critical endpoint를 호출하는 경우까지 보호하지 않는다.
`scripts/critical-bulk-isolation.py`의 fixture input은 owner/repo/issue를 고정한다.

| Class | server-observed method + request-target (고정 fixture) |
| --- | --- |
| Critical | `GET /api/v1/repos/{owner}/{repo}/issues/{issue}` (query 없음) |
| Bulk | `GET /{owner}/{repo}.git/info/refs?service=git-upload-pack` |
| Bulk | `POST /{owner}/{repo}.git/git-upload-pack` |
| 그 밖 | HAProxy403 deny; Critical 승격 없음 |

HAProxy는 `url`의 exact match를 사용한다. Prefix·case folding·추가 URI decoding·임의 query를 허용하지 않는다.
Client priority/class header, correlation ID, source IP, PAT, role은 분류 input이 아니다.
Ingress가 먼저 수행한 canonicalization 뒤의 method/path가 분류 경계다. Dot-segment가 canonical Issue URI가 될 때
check와 native Forgejo가 **같은 Issue**를 읽는지 별도로 검증한다. HAProxy 자체 raw noncanonical URI는 거부한다.
HAProxy가 관측한 escaped slash·double slash·wrong method·추가 query·absolute URI가 Critical로 진입하면 classifier escape다.
Selected managed ingress에서 normalization/effective HTTP check를 다시 관측하기 전 Azure 실행은 보류한다.

| 항목 | Shared control | Isolated |
| --- | --- | --- |
| target Deployment | `ext-authz-shared`, replicas2 | `ext-authz-critical`1 + `ext-authz-bulk`1 |
| target Service | shared pool1개 | dedicated pool2개 |
| target 총수 | 2 | 2 |
| capacity | Pod별 inbound Envoy maxRequests2 | 동일 |
| hold | Pod별1000ms | 동일 |
| HAProxy | 단일 provider/frontend, HTTP worker1/thread1/maxconn256/retries0 (master-worker mode) | 동일, backend 선택만 다름 |

동일 app image/resources, 총 replica 수, client concurrency/timing/retry, source/revision, ingress CUSTOM/native auth/TLS,
sentinel과 confounder guard를 유지한다. HAProxy queue 분리 자체를 protection 근거로 쓰지 않는다.
두 arm의 **actual Pod UID → sidecar ID → inbound mapping → Service endpoint → pool 선택**을 보존해야 한다.
Arm 전환은 drain 뒤 이전 target 제거/scale0 → 새 pool2개 actual admission → endpoint/effective config 확인 순서다.
전환 중 표본은 측정에 합치지 않는다. Stable Forgejo/Gateway/VirtualService/Argo는 renderer에 포함하지 않는다.
P8의 같은 provider overlay를 재사용하고 provider를 추가하지 않는다. HPA/KEDA/새 controller/node/PVC는 없다.

## 구현과 검증 경계

- `critical-bulk-isolation.py`: offline render, callback 기반 deterministic open-loop driver, exact-check/UID/coverage validator와 paired comparison. Azure operator/mutation entrypoint 없음.
- `test-critical-bulk-isolation.py`: synthetic positive / valid negative / observation-insufficient / invalid 회귀. Synthetic은 runtime proof가 아니다.
- `check-isolation-haproxy.py`: pinned3.4.6 실제 Docker HTTP dispatch. 두 backend가 같은 app을 쓰는 **protocol test**이므로 physical isolation proof가 아니다.
- `local-isolation-check.py`: invocation-owned P4 local cluster에서 healthy Issue/Git/native-auth, effective ext_authz, credential/body exclusion을 검사하고 실험 HAProxy를 복원한다. 기존 P4 saturation은 복원 뒤 실행한다. Local HTTP는 Azure TLS proof가 아니다.

HTTP ext_authz의 method/path 전달과 Authorization 자동 포함은 [selected Envoy API](https://www.envoyproxy.io/docs/envoy/v1.38.6/api-v3/extensions/filters/http/ext_authz/v3/ext_authz.proto)를 확인했다.
[Istio CUSTOM](https://istio.io/latest/docs/tasks/security/authorization/authz-custom/)과 [HAProxy3.4](https://docs.haproxy.org/3.4/configuration.html) 기준으로 단일 provider와 exact ACL을 유지한다.
Local pinned proxy binary는 `3bf722f59561ef9747835e543c0b648eb4ab1237 / 1.38.5-dev`다.
[Managed MeshConfig](https://learn.microsoft.com/azure/aks/istio-meshconfig)의 extensionProviders/proxyStatsMatcher/pathNormalization은 Allowed이며 full support와 구분한다. [Istio normalization](https://istio.io/latest/docs/reference/config/security/normalization/)의 BASE canonicalization을 runtime에서 확인하며 mesh normalization 설정은 바꾸지 않는다.
이것을 P8 managed `1.38.6/Modified`와 같은 binary로 주장하지 않는다. Managed revision/version/imageID는 paid preflight에서 별도 bind한다.

## 측정·판정

후보 `experiments/fixtures/critical-bulk/candidate.json`:120s, Critical2초당1개(60 logical), Bulk0.25초당1개(480 logical),
Critical workers2/Bulk16, max_attempts1. Git 한 command의 여러 HTTP check를1로 추정하지 않는다.
Driver는 각 arrival의 schedule/submit/issue/completion과 attempt index/clock을 분리하고, 미발행/early stop/backlog를 invalid로 남긴다.
숫자는 **후보**이며 local healthy/paired calibration과 관측 coverage를 확인·동결하기 전 paid approval을 요청하지 않는다.
기존 P7 Issue0.2s benchmark는 변경하지 않으며 새 workload의 protection deadline2s와 혼합하지 않는다.

필수 evidence:

- direct client monotonic operation completion/success/latency(주 SLI), separate attempts/retries;
- pool별 Envoy active/active_overflow/total/pending, effective listener/cluster capacity와 actual UID/sidecar/image/resource;
- class/backend/server를 server-side에서 기록한 HAProxy ring, process lifetime/drop/native frontend/backend counters와 ingress/target/app log;
- drained `checks = admission + rejection + queue + other`, per-class/per-pool native counter와 log equality; queue/other residual0;
- full same-window HAProxy/app/sidecar/PG/node/scheduling/direct sentinel/native auth/TLS/ingress confounder evidence와 file hash.

Native sample 후보0.25s, gap≤2×interval, request/sample/response clock과 전체 window coverage를 검사한다.
Experiment-owned `p10-envoy` PodMonitor는 기존 managed scraper로 target2개의5개 native stat를 scrape한다. Managed scrape15s + ingestion≤60s는 별도 freshness/coverage다. Minute metrics로 second-scale latency를 추정하지 않는다.
Active saturation은 sample row 수가 아니라 demand window 경과 시간 비율이다. 인접 native sample 구간을 시간 가중하고 상태 전환은 구간 중간으로 두므로, 짧은 구간에 몰린 중복/burst snapshot은 가중치를 만들지 못한다.
Azure의 managed row는 harness가 투영한 actual Pod UID/pool별 5개 stat을 모두 담아야 하며, native baseline의 UID/pool과 같고 counter가 감소하지 않으며 drained native counter를 넘지 않고 drained 경계 뒤에는 같아야 한다.
Timestamp만 있는 row, 빈/일부 누락 series, UID/pool drift, 비정수·음수 값은 invalid다. 구조가 유효한 series의 freshness/coverage gap만 `observation-insufficient`다.
누락/빈 series는0이 아니다. Counter reset/UID change/log loss/route·demand·source drift/native-auth 또는 TLS 실패/경쟁 병목/accounting gap/early stop은 invalid다.
설정은 valid해도 observation resolution/coverage가 결론을 뒷받침하지 못하면 `observation-insufficient`다.

Useful positive는 shared의 actual bulk-induced critical degradation(후보 good≤90%, Critical target rejection>0),
isolated의 같은 계속되는 Bulk saturation(후보 active saturation≥50%, 실제 Bulk rejection>0)과 Critical protection(후보 good≥95%)이 함께 필요하다.
완전한 valid pair가 이를 지지하지 않으면 `valid-negative`다. 측정 결과를 보고 threshold를 완화하지 않는다.

## Pre-paid feasibility와 남은 gate

현재 **P10 Azure 승인 없음**. 이번 작업은 Azure tenant inventory/credential/resource 호출을 하지 않는다. Public unauthenticated Retail Prices API만 조회했다.
기존 environment 보존기한은2026-11-08 10:30 KST, Foundation/Bootstrap은2026-11-09 00:33 KST다.
Provider TTL/budget cap으로 간주하지 않으며 자동 연장·삭제하지 않는다. [Paid Azure boundary](implementation-plan.md#paid-azure-boundary--p6p11)가 authority다.

Source topology의 steady 최대는 HAProxy1+target2+기존 DB client1=4 Pods다.
P8 renderer request/limit와 같은 app/proxy 값을 사용하며 target2개+HAProxy+DB의 regular container 합계는
CPU limits1000m, memory limits1152Mi다. Init/native sidecar/Pod overhead·rolling transition은 **actual admission 미검증**이다.
Source ResourceQuota1500m/2048Mi/Pod4는 Azure quota/headroom 증거가 아니다. 기존 node2·34 resource ID를 재사용할 계획이다.
Arm 전환 때 old/new target 동시 추가·node 증설로 이 한도를 우회하지 않는다.

승인 전 필요한 최소 순서:

1. exact source CI + independent source gate; local healthy classifier/native-auth와 positive/negative/insufficient 판정·관측 coverage 사례.
2. cost-free actual paired calibration으로 numeric thresholds를 동결하고 plan/fixture/arrival/render/runtime invariants hash를 bind.
3. 필요한 경우만 별도 허용된 read-only inventory: current nodes/allocatable/requests, actual native/init admission,
   managed revision/support, ingress normalize/path/method/credential/body effective config, RBAC/quota, 공유 환경 current price와 retention reserve 확인.
4. 전체 bounded plan을 하나로 제시: initial/final normal, healthy2 arms, calibration pair **최대1회**, measured pair **각1회**(최대4 fault runs),
   각120s + drain15s + telemetry tail≤75s. Fault run reserve840s, preparation/transition1200s, owned cleanup1800s, 총3840s(64분) 후보.
   완료 단계는 다시 예약하지 않으며 실패 run은 append-only/횟수 소비다. 원인 없는 반복은 없다.
5. 비용은 current price×기존 환경 hold64분+image/telemetry 증가량+cleanup reserve로 산정한다.
   기존 공유비와 P10 증가분/late ingestion을 구분한다. Actual price·cost·남은 budget은 **UNKNOWN**이며 임의 cap을 만들지 않는다.
6. 명시적 P10 action/count/cost/time 승인과 source/image/plan/identity binding 뒤에만 mutation을 허용한다.

현재 blockers: actual2-pool normal/paired local calibration·sampling feasibility, managed effective path/normalization mapping,
actual admission/headroom/공유 환경 current price, independent source gate와 명시적 P10 승인.
Managed 쪽 **미구현**: AMW/Prometheus query와 Pod label→UID 투영 collector, Prometheus timestamp와 harness monotonic clock의 정렬, 중간 시점의 native-managed 값 대조.
Offline validator는 투영된 row의 구조·identity·값 범위·drained 경계 일치만 검사한다. 이 검사가 실제 managed 수집이 동작한다는 증거는 아니다.
Renderer/driver/synthetic test 통과를 Azure feasibility 완료 또는 isolation protection으로 표시하지 않는다.

Owned rollback 계획: demand 중단/수집 drain → exact UID CUSTOM policy 제거 → shared ConfigMap UID/data guarded 복원 →
소유 target/HAProxy/DB client/Secret/namespace 제거 → stable UID/spec/Argo revision과 정상 HTTPS/native journey 확인 →
소유 PAT exact-ID revoke/reuse401·fixture login 차단·image reference guard·forward/임시 RBAC 정리.
전체 environment teardown/DNS/state/보존기한 변경은 범위 밖이다. Cleanup 완료는 별도 실제 evidence 없이는 주장하지 않는다.
