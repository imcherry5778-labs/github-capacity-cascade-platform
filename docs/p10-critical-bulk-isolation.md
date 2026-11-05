# P10 — Critical/Bulk operation isolation (첫 implementation)

상태: **source 구현(P10-W1) + Local 2-pool paired harness와 managed collector 계약(P10-W2, source-only) + Azure pre-paid source gate(P10-W3, source-only) / cost-free 검증 범위는 [evidence](evidence/p10-source-20261105/README.md)와 exact-head CI artifact 참조 / Azure 미실행 / P10 acceptance 미완료**.
W1 baseline `58fae6f105bd5bc28e2c85e05a138f6cb3e4ed03`에서 시작했고 W2는 merged PR52 `ab77792`에서 시작했다. [P8 incident](incidents/p8-controlled-cascade.md),
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
- `local-isolation-pair.py` (P10-W2): 같은 invocation-owned P4 cluster에서 shared(2 replica 1 pool)와 isolated(Critical 1 + Bulk 1)를 **실제 Pod/Service/Istio inbound capacity/HAProxy로** 번갈아 올려 같은 후보 부하를 paired로 건다. 기존 `ext-authz-sim`은 scale 0으로 두고, 시작 전 P10 label 객체·Pod뿐 아니라 label 없이 같은 이름(`ext-authz-{shared,critical,bulk}`, `p10-capacity`)을 가진 객체가 있어도 아무것도 바꾸지 않고 거부한다. Arm마다 actual Pod UID → sidecar container ID → effective inbound `maxRequests` → Service/EndpointSlice → pool을 매핑하고, warm-up(Pod마다 stats 생성)을 측정에서 제외한다. Driver 산출(`m.drive`)과 native 0.25s sampler, HAProxy ring, 대조 가능한 log/counter, 9개 confounder guard를 한 monotonic clock에 모아 `validate`/`compare`로 판정한다. 렌더된 정확한 inventory는 **첫 mutation(apply) 이전에** 소유로 등록하고(부분 apply·rollout·HAProxy 교체·mapping 실패도 포함), arm 전환·종료 삭제가 끝나 inventory 부재를 kind/namespace/name으로 읽어 확인한 뒤에만 해제한다(삭제 실패 시 소유 유지·복원 때 재시도). 종료(예외·중단 포함)는 항상 pool 제거, HAProxy/hold/원본 target 복원과 Forgejo stable UID/spec 불변을 읽어 확인(`restoration.json`)하며 복원이 불완전하면 non-zero다. 결과 `positive`/`valid-negative`만 exit 0이고 `observation-insufficient`/invalid는 실패다. 이 결과는 Local single-node loopback이며 Azure·TLS·managed telemetry 증거도, threshold freeze도 아니다. 실제 수치는 exact-head CI artifact(`p10-pair/result.json`)에만 있다.
- `test-local-isolation-pair.py`: cluster 없이 protocol bytes(실제 `git upload-pack`), 가짜 ingress 상대 probe 분류, native stat 파서, sampler gap, Pod/Service/endpoint 매핑, guard, 복원 판정, 결과 재검증을 검사한다. 통과가 runtime proof는 아니다.
- `azure-isolation.py` (P10-W3): Azure gate. 새 controller/service/framework 없이 W1 renderer/driver/validator, W2 client/sampler/guard, P8 identity·`Runtime`·`target_mapping`·`admission`·`gateway_scope`·mesh overlay, P9 `cluster_name` metric mapping을 재사용한다.
  - `preflight MANIFEST PRICE OUTPUT`: 별도 `P10_AZURE_READONLY=<exact SHA>` 확인과 보호 kubeconfig 아래에서 Kubernetes `get`/`auth can-i`/Envoy admin `GET`, `az aks show`, `az acr repository show`, AMW query 2개, 익명 HTTPS healthz만 호출한다(그 밖의 kubectl 동사는 process 시작 전에 거부). 결과는 approval **요청** 준비 여부(`ready-for-approval-request`/`blocked`)이며 승인이 아니다. 관측 누락·read RBAC 부족·campaign RBAC 미결정은 정확한 verb/resource/namespace 목록과 함께 blocker다. Role은 부여·요청·escalation하지 않는다. 예산/headroom은 항상 UNKNOWN으로 남긴다.
  - Manifest는 P8 identity, **source 후보와 같은** plan, fixture, AMW endpoint/cluster label을 묶는다. `campaign`은 `P10_AZURE_APPROVED=<exact SHA>`, 같은 manifest hash, 이 plan의 freeze hash, 고정 limit(healthy 2, calibration pair ≤1, measured pair 1, fault run ≤4, Pod4/1500m/2048Mi), 새 append-only ledger(존재하면 거부: 재개·재사용 없음)와 전체 3840초 reserve를 요구한다. 매 action 전 횟수와 action+1800초 cleanup reserve를 확인하고, 시작한 action은 결과와 무관하게 소비된다.
  - Mapping/admission: actual Pod UID → native sidecar container ID → effective inbound `max_requests`(ORIGINAL_DST 8080)와 `cluster_name` stat tag → Service selector/EndpointSlice → pool, 그리고 P8 conservative sum(init·native sidecar·overhead 포함)과 arm별 Pod 구성. Preflight headroom은 request 추정일 뿐 admission 증거가 아니다.
  - Ingress: Forgejo hostname의 TLS filter chain에서 Istio BASE(`normalize_path`, slash merge 없음, escaped slash 유지), Forgejo route retry0·rewrite 없음, campaign 전 ext_authz 부재/안에서는 exact HAProxy cluster·path prefix 없음·body 제외·fail-closed. Healthy는 Local과 **같은 probe 표**(`local-isolation-check.probe_plan`)를 managed ingress HTTPS로 실행한다.
  - Managed: 기존 AMW에 대해 `cluster`/`namespace`/`job`/`cluster_name` selector의 raw range-vector를 scrape/3 간격으로 POST 조회하고, 실패 poll은 값이 아니라 gap이다. Tail은 scrape+ingestion(75초) 이하다.
  - Campaign: 기존 namespace/policy/provider가 있으면 아무 mutation 없이 거부한다. Namespace·CUSTOM policy·shared ConfigMap 원본을 해당 mutation **이전에** 소유로 등록하고, 종료 시 exact-UID policy 삭제 → UID 확인 후 shared ConfigMap data 복원 → campaign label namespace 삭제를 각각 read-back으로 확인한 뒤에만 해제한다. Ingress provider 부재, stable Pod/spec·Argo, HTTPS healthz와 인증 Issue read까지 확인해야 `restored`다. 실패 run도 raw를 append-only로 남긴다.
- `test-azure-isolation.py`: 위 계약을 mocked live 응답과 실패 주입(partial apply, rollout/mesh/provider 실패, 교체된 policy/ConfigMap, 삭제 실패, 기존 객체, 불일치 window)으로 검사하고 `measure()`/`healthy()` 경로를 stub로 끝까지 실행한다. 통과가 Azure runtime·admission·ingress·telemetry 증거는 아니다.

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

현재 blockers: Local paired 결과를 확인한 numeric freeze(후보 threshold는 바꾸지 않았고 pair 한 번이 freeze는 아니다), 실제 managed 수집 경로 검증(AMW query/auth/PodMonitor label/지연),
managed effective path/normalization mapping, actual admission/headroom/공유 환경 current price, independent source gate와 명시적 P10 승인.
P10-W3 source는 이 gate들을 실행 가능한 fail-closed 형태로 만들었을 뿐 통과시키지 않았다. Read-only `preflight`도 Kubernetes read 권한이 확인되기 전에는 `blocked`이고,
campaign RBAC(namespace/policy/ConfigMap patch/exec/port-forward/log)는 사용자 승인 사항이다. `campaign`이 소유하지 않는 operator 단계 —
initial/final normal journey, fixture user/PAT 준비와 exact-ID revoke·reuse401, ext-authz image publish/정리, 보호 DB read env, 임시 role의 부여/회수 — 는 승인 범위에 따로 묶는다.
Managed 쪽 contract(P10-W2, **mocked Prometheus 응답으로만 검증**; P10-W3에서 label을 P9 Azure evidence의 `cluster_name`과 AMW `cluster`로 정정 — P9 managed bootstrap은 `cluster_name` tag만 내보내므로 W2 selector의 `envoy_cluster_name`은 실제 series와 맞지 않았다): `managed_selector`/`poll_managed`는 range-vector instant query로 evaluation step이 아닌 **raw scrape sample과 그 timestamp**를 받고,
`project_managed`는 series의 Pod **이름**을 harness의 Kubernetes inventory로 actual Pod UID/pool에 투영한다(series label은 identity 근거가 아니다).
빈/일부 누락/미매핑/재작성/비정수 series는 invalid, 한 Pod만 빠진 scrape round는 coverage gap(`observation-insufficient`)이다. Sample의 가시 시점은 그것을 처음 반환한 poll이라 ingestion 지연이 측정된다.
`clock_pair`/`clock_bound`/`to_monotonic`은 harness wall↔monotonic 대응과 step을 검사하고, `managed_guard`는 각 managed counter를 **자기 시각 전후 native sample(±clock 허용)로 bracket**한다.
Collector와 harness host 사이의 skew는 시계로 측정되지 않으며 이 bracket으로만 제한된다. `coverage`는 managed에 대해 window 시작 전 가시성을 요구하지 않고(불가능) `sample_at` bracket과 `at − sample_at ≤ scrape+ingestion`을 요구한다.
Offline validator·collector 통과는 실제 AMW query 인증/endpoint, 실제 PodMonitor series label, 실제 ingestion 지연이 동작한다는 증거가 아니다.
Renderer/driver/synthetic test 통과를 Azure feasibility 완료 또는 isolation protection으로 표시하지 않는다.

Owned rollback 계획: demand 중단/수집 drain → exact UID CUSTOM policy 제거 → shared ConfigMap UID/data guarded 복원 →
소유 target/HAProxy/DB client/Secret/namespace 제거 → stable UID/spec/Argo revision과 정상 HTTPS/native journey 확인 →
소유 PAT exact-ID revoke/reuse401·fixture login 차단·image reference guard·forward/임시 RBAC 정리.
전체 environment teardown/DNS/state/보존기한 변경은 범위 밖이다. Cleanup 완료는 별도 실제 evidence 없이는 주장하지 않는다.
