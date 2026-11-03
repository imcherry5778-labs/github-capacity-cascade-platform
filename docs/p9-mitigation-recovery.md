# P9-W1 Mitigation & Recovery

목표는 동일 fault/demand의 C0–C3 비교, continuing-demand recovery, 실제 request accounting과 P9-owned 원복 evidence다.
P9 acceptance는 아직 미충족이다. [제23차 실제 결과](evidence/p9-mitigation-twenty-third-20261103/README.md)는 CLOSED/invalid이며 남은 실행 권한은 close와 함께 소멸했다.
누적 campaign23 / public initialize20 / healthy11 / started-invalid calibration8 / measured 각0 / KEDA apply·restore8/8을 보존한다.
Exact source `076bc8a3dbd09e8192057e19df8b6cc5cb55274d`의 실제 initialize/KEDA/partial joint observation 뒤 controller·HAProxy log 결손으로 calibration이 invalid였다.
Source CI·synthetic·부분 positive를 valid calibration, measured 성과 또는 recovered로 승격하지 않는다.

현재 실행 범위·보존은 [Paid Azure boundary](implementation-plan.md#paid-azure-boundary--p6p11)와 별도 실제 사용자 결정을 따른다.
Environment 기한은 2026-11-05 10:30 KST, Foundation/Bootstrap은 11월6일00:33 KST다. 자동 연장·전체 teardown·merge/P10은 없다.
P6/P7 drill, P8 전체 실험, factorial/조합 최적화, 다른 architecture 구현은 범위 밖이다.

## 비교와 동결

| Arm | C0 대비 유일한 mitigation delta | Controller |
| --- | --- | --- |
| C0 control | 실패한 fixture Issue read에 bounded retry, max_attempts=2 | 기존 app CPU HPA, requests50m, target60%, min1/max2 |
| C1 backoff | 두 번째 attempt 전 deterministic uniform jitter 250–750ms, seed5778 후보 | C0와 같음 |
| C2 admission | HAProxy server maxconn2 / maxqueue12, backend queue12 이상이면429, queue timeout250ms 후보 | C0와 같음 |
| C3 scaling | per-Pod proxy overflow **rate** 기반 managed KEDA | CPU HPA 제거, KEDA HPA min1/max2 |

공통 fault는 maxRequests2 / hold1000ms다. Wave마다 Issue24, concurrency12, Git
`ls-remote refs/heads/main` 1회, 간격5초를 유지한다. Writes/fixture setup에는 retry가 없다.
Authorized fixture의 동일 Issue에 대한 direct native-auth sentinel과 exact CUSTOM path가
확인된 경우에만 403/429/503을 **provisional experiment overload**로 재시도한다.
최종 ingress log가 native denial(`via_upstream` 403 등)을 포함하면 비교를 거부한다.
이는 일반 HTTP403 retry 권고가 아니며 unauthorized read를 실험 부하에 섞지 않는다.

[후보 입력](../experiments/fixtures/shared-gate/mitigation-candidate.json)의 KEDA `2.19.0-25`는 이전 실행에서 보존한 actual image tag다. 새 live 확인을 수행한 값이 아니다.
Zero client ID는 미설정이며 재개 시 actual version·새 identity client ID·series·cadence를 다시 확인해 보호된 plan에 연결한다.
ARM에서 managed KEDA enabled를 확인한 것만으로 version/CRD/인증을 확인했다고 보지 않는다.
최종 source는 승인 대상 exact HEAD, published digest, verified HTTPS hostname/native PAT,
process-local DNS override, source/render hashes, P7 SLO hash, fault/demand/schedule와 arm delta를 묶는다.
`freeze`는 같은 최종 plan의 reviewed calibration report 1–2개를 요구한다. Report에는
source/plan/fixture hash와 verified HTTPS transport(DNS override 포함), `reviewed`, `missing_required_signals=[]`, 실제 cadence, all-Pod series,
`per-pod-active-overflow-counter-rate-per-second` 의미, 아래 고정 `metric_contract`, controller ownership 검토를 기록한다.
Boolean report는 actual calibration raw/동일 window 검토를 대신하지 않는다.

C0/C1은 같은 runtime identity/UID/config를 사용한다. C2에는 config reload를 위한 HAProxy
Pod 교체와 config hash delta만, C3에는 CPU→KEDA 정책·target replica/UID와 C2→공통 HAProxy
복귀 rollout만 허용한다. Target imageID/build/stat mapping, stable/ingress UID/spec/provider/
hostname, Argo revision과 나머지 drift 검사는 유지한다. Arm마다 initial target은1이다.
새 arm을 위해 target을 수동으로1에 초기화한 기록은 autoscaling 성과로 세지 않는다.

## 시간·부하 상한

공통 후보는 mitigation240s + recovery180s, drain/마지막 수집60s를 계획한다.
실제 scrape/ingestion/controller cadence를 calibration에서 확인하여 공통 mitigation을
`max(120s, 3×(scrape+ingestion+controller))` 이상, 10초 배수로 **measured 전에** 고정한다.
코드는 mitigation≤300s, recovery120–240s, 두 구간 합계≤540s, arm 계획≤600s를 제한한다.
Kubernetes 명령은 최대15s, 한 snapshot의 Kubernetes 수집 budget30s, Prometheus query는
각5s다. Deadline/관측 부족은 raw로 보존하며 복구/다음 run 판단은 AGENTS.md의 복구 경계을 따른다.

| 상한 | 후보420s / run | 최대로 승인 요청하는540s / run |
| --- | ---: | ---: |
| Wave | 84 | 108 |
| Issue logical operations | 2,016 | 2,592 |
| Issue attempts (max2) | 4,032 | 5,184 |
| Supplemental Git operations/attempts | 84 | 108 |
| 합계 logical operations / attempts | 2,100 / 4,116 | 2,700 / 5,292 |

Calibration **총2회 이하**(C3 및 C2를 우선 후보로 삼고 C1 seed/범위는 cost-free로 고정), measured는 C0→C1→C2→C3 **각1회**, 합계 최대6회다. Calibration 자체는
한 arm만 실행하며 조합 arm을 만들지 않는다. Candidate 변경도 두 번의 calibration budget
안에서만 한다. 최종 measured plan과 다른 이전 calibration hash는 ledger에 남긴다.
상한 합계는 logical16,200 / client attempts31,752, 관측+drain60분이다.
Git 내부 HTTP/check 수는 attempt 수와 다르므로 이 숫자가 check 상한이라는 주장은 없다.
각 run의 direct sentinel은 단일 worker, 요청 간1초 이상, 명령 timeout10초로 최대 약600회
(6회 약3,600회)이며 public demand와 별도다. 초기/최종 정상 journey는 각1회,
healthy-gate journey1회, native-deny/controlled-deny/path 확인은 각각1회로 요청한다.
모든 probe·actual HTTP/check 수·telemetry query 수를 실행 ledger에 기록한다.
승인 상한을 넘는 추가 반복은 새로운 승인 대상이다.

Scheduler는 wave 완료를 기다리지 않고 같은 monotonic offsets에 arrival을 제출한다.
Issue12/Git1 worker와 최대49 pending으로 client backlog를 제한한다. 초과 또는 monitor 실패 시
추가 발행을 중단하고 남은 예정 arrival을 `not-issued/cancelled`로 보존하며 fault release를 시작한다.
이는 valid mitigation이 아니다. Comparison은 unissued0 / max driver lag≤2s를 요구한다.
회복 window의 driver lag는 더 엄격하게≤0.2s다. 부하가 밀린 것을 완화 성과로 세지 않는다.

## KEDA signal과 ownership

기존 managed KEDA/Managed Prometheus를 재사용한다. [Microsoft managed KEDA 문서](https://learn.microsoft.com/en-us/azure/aks/keda-workload-identity)의
version별 실제 image/CRD/operator/SA 상태를 먼저 보존한다. 읽을 수 없으면 필수 실행 gate다.
기록된 actual `2.19.0-25`에 맞춰 [2.19 scaler](https://keda.sh/docs/2.19/scalers/prometheus/)와
[identity override](https://keda.sh/docs/2.19/authentication-providers/azure-ad-workload-identity/)를 참조한다.
재개 시 actual version이 다르면 중단하고 matching contract를 확인한다. 과거 확인 결과는 현재 scaler 인증 proof가 아니다.
Managed controller의 Helm/resource/spec 임의 변경이나 self-managed 대체는 하지 않는다.

실험 소유 `azmonitoring.coreos.com/v1 PodMonitor/p9-envoy`는 기존 scraper를 사용한다.
선택 series는 `envoy_cluster_upstream_rq_active_overflow`, labels
`cluster/namespace/pod/job="p9-envoy"/cluster_name="inbound|8080||"`로 제한한다.
Adapter의 단일 `metric_contract`를 raw/rate/active/timestamp/sample-count/guarded query,
KEDA render, collector, saved validator와 freeze가 공유한다. Label fallback/OR selector는 없다.
Actual ORIGINAL_DST inbound cluster `inbound|8080||`, listener destination port8080과 route,
`alt_stat_name="inbound|8080||;"` 및 suffix5 admin stat 이름을 연결한다. Bootstrap은
`use_all_default_tags=false`, `cluster_name` tag regex `^cluster(\.(.+);)`를 확인한다.
Native exposition의 overflow counter/active gauge type과 label, 같은 Pod의 ingested sample을 대조한다.
Mapping/tag/label ambiguity나 drift는 신규 Pod warmup 중에도 실패한다.
`sum(rate(...[1m]))`의 unit은 rejected checks/s이며 raw cumulative counter를 threshold에
연결하지 않는다. 후보 threshold0.5, calibration 허용0.25–1.0이다. 이는 rejection을 낮추려는
반응 후보이며 capacity2가 SLO를 복원한다는 가정이 아니다. Gauge의 짧은 peak는 scrape가
놓칠 수 있어 counter rate를 택했으며 high-frequency admin 관측/log와 따로 대조한다.

Query는 per-Pod rate·원본 timestamp freshness·up=1 및 **kube_pod_info의 target 수와 coverage**를
guard한다. Inventory series의 label/freshness와 target Pod들의 실제 UID/name도 대조해야 한다.
Empty/partial/stale/error를0으로 바꾸지 않고 `ignoreNullValues=false`, TLS verify를 사용한다.
Collector의 기존 다섯 번째 instant query는 `p9_query_term` label로 canonical guarded 결과,
rate/fresh-rate/inventory/up count·up minimum·raw/up/inventory maximum age와 `vector(time())`를 분리한다.
Guarded row만 기존 판정에 넘기며 없는 operand는 `[]`, non-finite 값은 원문으로 보존한다.
진단이 있어도 guarded `[]`는 measured 경로에서 invalid, initialize에서는 기존 uninitialized 경계다.
Canonical `scale_query` hash와 collector envelope hash를 구분하고, raw 응답·추출 결과·server evaluation epoch 및
request/response UTC·monotonic elapsed를 saved validator가 대조한다. UTC clock 동기화는 가정하지 않는다.
[Instant API](https://prometheus.io/docs/prometheus/latest/querying/api/#instant-queries)와
[`time()`](https://prometheus.io/docs/prometheus/latest/querying/functions/#time)의 단일 evaluation time은
backend transaction/ingestion atomicity 보장이 아니다. 제18차 historical 조회와 당시 negative는 그대로 보존하며
이번 cost-free 계측 교정으로 runtime 원인·P9 acceptance 완료를 주장하지 않는다. Request 횟수·query5초·collection30초는 유지한다.

Threshold는 KEDA `AverageValue`이며 총 rate/threshold의 desired replica 판단을 actual generated
HPA metric·desired·Ready·각 target의 traffic timeline과 함께 기록한다. 수동 scale은 성공 proof가 아니다.

전체 live target UID/inventory에는 Pending도 포함하고, runtime config/counter/log는 Ready target에서 수집한다.
Collector와 saved-run validator는 같은 lifecycle 경계를 적용한다. 신규 C3 UID의 Pending→Ready는
첫 관측부터 최대90초, Ready 이후 series 초기화는 `ingestion+3×scrape` 이내만 허용한다.
Ready 직후 admin stat가 아직 materialize되지 않은 상태도 같은 Ready budget 안에서만 허용한다.
구조/config invariant는 stat 유무와 독립적으로 검사한다. `Pending → Ready/no-admin-stat → 첫 계획된 traffic →
admin/native stat → rate 최소2 samples`를 `admin_stats`의 실제 값/누락과 `warming-new-pod` not-ready/no-data로 보존한다.
누락 UID는 `stats`에 추가하지 않는다. 이미 admin stat를 관측한 UID의 재누락도 실패한다.
신규 Pod를 위한 추가 load는 없으며 최초 stat snapshot이 nonzero여도 해당 UID의 누적 counter와 lifetime 전체 log를
나중에 확보하여 계획된 traffic을 모두 accounting한다. 누락 snapshot을0으로 합성하지 않으며 final counter/log가 없으면 invalid다.
Idle/recovery/scaling 성공 proof로 세지 않는다. 기존 또는 이미 관측된 Pod의 누락/stale/error,
unknown series/UID, startup timeout은 중단 사유이며 inventory query guard는 유지한다. 첫/마지막만 빼는
방식 없이 각 Pod lifetime의 counter/log를 수집하고 reset/restart·수집 누락을 구분한다.
관측 중 사라진 Pod의 final counter/log를 확보하지 못하면 valid로 승격하지 않는다.

전환/복귀는 renderer의 전체 List를 한 번 apply하는 방식으로 하지 않는다.
`transition`은 파일로 순서와 확인 gate만 생성한다.

1. C3 진입: CPU HPA exact 객체 삭제·부재 → target owner0 확인 → TriggerAuthentication/ScaledObject 적용 →
   generated HPA의 exact ScaledObject UID ownerReference와 owner1 확인.
2. 복귀: ScaledObject foreground 삭제·부재 → generated HPA 부재 → owner0 확인 → 기존 CPU HPA 적용 → owner1 확인.
3. 전환 중 controller 중복/unknown owner 또는 삭제 지연이면 CUSTOM policy를 우선 제거하고 중단한다.
   Stable Deployment는 scale/mutate하지 않는다. Experiment controller manifest만 원복한다.

## 최초 healthy 초기화 순서

1. 실제 source/image digest·cluster/Pod UID·Argo revision·plan/approval hash를 결합하고 normal/native-auth/TLS를 먼저 확인한다.
   Dedicated Entra user kubeconfig, exact CUSTOM hostname/provider/selector, fail-closed path, pinned image/controller,
   hold0/capacity1024, app CPU HPA, Ready/무재시작·DB verify-full/read-only SQL·node headroom/admission을 검증한다.
   `healthy_gate_passed`/`runtime_preflight_passed`를 초기화를 위해 미리 true로 만들지 않는다.
2. CPU 준비는 configuration을 포함한 monotonic300초 안에서 read-only settling한다. Configuration/guard 각각30초,
   명령15초와 poll 사이 sleep≤15초를 지킨다. 실제 poll 완료 간격이15초 이하라는 보장은 없다.
   같은 Pod/HPA UID/spec·unowned CPU owner·Ready transition과 양수 `app` CPU, Ready 이후 전체 sample window≤90초,
   sample age≤`min(60초, 2×실제 검증된 CPU sample window)`와 AbleToScale/ScalingActive 및 양수 `ContainerResource/cpu/app` currentMetrics를 요구한다.
   Pod/HPA 생성≤Warning first≤last≤안전 관측 시각이며 first/reason 불변, count/time 단조 증가·동시 변경과 history를 보존한다.
   첫 positive 전 허용 Warning은 exact CPU HPA namespace/UID의 `FailedGetContainerResourceMetric`/
   `FailedComputeMetricsReplicas`뿐이다. 다른 Warning/owner/미귀속·lifecycle/UID/Ready drift는 즉시 실패한다.
   첫 positive에서 recovery latch를 고정하고 이후 새 Warning/count/time 증가·history 유실을 거부한다. `since`를 재설정하지 않는다.
   Retained Warning은 마지막 Warning 이후 ScalingActive 회복, quiet15초와15초 이상 떨어진 두 advancing valid sample이 필요하다.
   Warning 없는 이미 정상인 baseline은 별도 대기 없이 통과할 수 있다. Timestamp 역행·같은 timestamp의 window/CPU 변경은 실패한다.
   구조적으로 유효한 stale export와 positive HPA만 후보를 보존하며 advancing/fresh proof로 세지 않는다.
   다른 누락/invalid/HPA 미회복은 후보를 취소하거나 실패한다. 완료 후에도 current stale poll은 pending이며 target observed만으로 완료하지 않는다.
3. 기존 healthy journey1회만 사용한다. Append-only init ledger intent를 먼저 기록하고 timeout90초/TERM·kill-after5초를 적용한다.
   기존 validator로 exact source·clean context·HTTPS transport와 warmup9 operations/9 attempts를 검증한다.
   기존 fixture/settle/anonymous/Git 보조 요청도 auxiliary correlation으로 귀속한다. 측정 분모에 섞거나 telemetry 때문에 재호출하지 않는다.
4. Journey 이후 `ingestion+3×scrape` 안에서 같은 UID/config/admin/native·target series·guarded query를 read-only 수집한다.
   Candidate는75초/시작 간격≥15초, 최대5poll·Prometheus 최대25query다. Configuration과 CPU 외 guard 관측을 기존 worker로 겹치고,
   signal과 guard 완료 뒤 기존 CPU metrics GET1회를 수행한다. 같은 collection30초/global deadline·명령15초를 재시작하지 않는다.
   같은 target bootstrap 응답1회로 matcher/metric binding을 검증하며 null 응답을 재조회하지 않는다.
   이전 poll의 UID/HPA/Warning/resource/DB 관측을 대신 쓰지 않는다. CPU age는 늦은 취득 시각에 계산하되,
   HPA/Warning quiet·선후관계는 따로 보존한 안전 관측 시각으로 판정한다. 늦은 CPU 시각으로 quiet를 부풀리지 않는다.
   Final native-path/log accounting 뒤에도 같은 CPU age≤`min(60초, 2×실제 검증된 CPU sample window)`와 target freshness를 모두 확인한다. P8 기본/측정·C3 경로는 이 opt-in을 사용하지 않는다.
5. 같은 journey window의 신규 ALLOW check·target inbound200·ingress native response가 양수이고 수가 일치해야 한다.
   모든9 attempt의 operation/attempt ID와 auxiliary ID, check ID/시간 범위, credential/body exclusion·HAProxy hop을 대조한다.
   Target cluster/status, ingress Forgejo route/status, actual target counter와 logs를 검증한다. Anonymous401/404는 gate ALLOW 이후 native auth 결과다.
   Proxy format에는 correlation ID가 없으므로 proxy 대응은 같은-window count/cluster/status 수준이다. Git1회=HTTP/check1회를 가정하지 않는다.
   초기 stat 없는 UID는 lifetime counter/전체 UID log, 나머지는 before/after delta로 대조한다. Zero/missing/mismatch/rotation/deny/unattributed는 실패다.
   성공은 `ready_for_keda_authentication=true`, **`runtime_preflight_passed=false`**다. 필수 query/stat 부재는 deadline까지 pending,
   invariant/unknown/query 오류는 즉시 실패하며 성공 flag나 소비 횟수를 되돌리지 않는다.
6. 그 뒤 승인된 KEDA IAM/SA 변경과 actual scaler auth/cadence/full gate를 통과해야 calibration에 진입한다.
   Operator 자신의 query 성공은 scaler 인증 proof가 아니다. CLI `initialize`/`transition`/`measure ... calibration`은 이 순서를 대체하지 않는다.

Admin은 `stats?format=json`, native는 `stats/prometheus`를 사용하고 `usedonly`/filter를 추가하지 않는다.
Deferred/absent counter를0으로 만들거나 임의 traffic으로 보완하지 않는다. 신규 UID의 부재만 bounded warmup으로 관측하며
기존/이미 observed UID의 series 소실·unknown label/UID·startup timeout은 실패다. Full guard·numeric0과 부재를 구분한다.
실패는 safe class/code·stage·elapsed로 기록하며 secret/argv/message/body를 공개하지 않는다. 상세 trace는 기존0700 private 경계의
0600 exclusive file로만 보존하고 owned cleanup에서 제거한다. Raw 실패·기존 file/write 오류·consumption은 덮어쓰지 않는다.

## Measured snapshot 시간·관측 계약

모든 mandatory 조회와 마지막 HAProxy stats 뒤에 실제 end/epoch를 기록하고 end-at≤30초일 때만 snapshot/convergence를 발행한다.
명령15초/query5초·saved observation gap≤35초·run≤600초를 유지한다. 실패 시 기존 worker 종료를 기다리고 partial snapshot을 발행하지 않는다.
Configuration/guard는 동일 absolute deadline을 쓰며 서로의 admin observations/lifecycle을 변경하지 않는다.
두 결과의 config/UID를 대조한 뒤 admin stats→logs→Prometheus signal→HAProxy stats 의존 순서를 지킨다.
매 UID lifetime의 image/build/mapping/hold/counter/log·HPA owner·Warning·원본 ScaledObject metadata/spec provenance를 보존한다.
CPU 초기화의 stale/Warning 예외를 measured/C3의 strict guard에 적용하지 않는다.

### C3 두 Ready target 수집

C3 Ready2개에만 기존 target worker2개를 쓰고 같은 collection deadline을 thread-local에 전달한다.
Target별 matcher/native/hold/counter/mapping을 검증한 local result만 UID별로 합친다. 같은 target의 같은 bootstrap 응답을
matcher와 metric binding에 재사용하며 다른 UID·이전 cycle cache를 대신 쓰지 않는다. 실패 시 기존 admin observations를 부분 덮어쓰지 않는다.
모든 Ready target app/proxy logs, ingress/HAProxy logs, Prometheus query와 HAProxy server/BACKEND를 수집한다.
Full live inventory에는 Pending도 포함하며 Ready/initialized series 전까지 성공 replica로 세지 않는다.
사라진 Pod의 final counter/log가 없거나 reset/restart/불완전 수집이면 invalid다. 수동 scale은 autoscaling 성공이 아니다.

## Recovery와 accounting

각 arm의 mitigation은 fault를 유지한다. Release worker는 예정 mitigation 종료에 hold0,
maxRequests1024로 바꾸며 **동시에 같은 logical arrivals가 계속된다**. ConfigMap projection과
각 Envoy capacity/hold의 실제 수렴 전 구간은 따로 남긴다. Release 중 허용 값은
각 target의 hold1000→0 / capacity2→1024뿐이며 서로 다른 시점의 수렴을 `fault_state`와
`release-not-converged` gap으로 보존하고 recovery proof에서 제외한다. 이때도 hostname/provider/
selector, image, controller ownership 및 나머지 invariant 검사는 계속한다. Drift나 unknown validation
failure는 monitor failure로 전파되어 추가 demand 중단과 기존 fault release 경로로 이어진다.
Gate/native auth 우회나 demand 감소는 없다.
Fault 유지 중 원래 SLO를 회복했다고 가정하지 않는다.

Recovery window는 schedule origin 기준 고정된 연속10초다. 마지막 arrival은 duration−5초이며
관측 deadline까지 계속 수집한다. 첫 fully-converged window부터 다음 조건을3개 연속 요구한다.

- 매 window에 예정된 새 Issue48/Git2가 실제 발생하며 driver lag≤0.2s, 미발행/취소 없음.
- 새 Issue 모두 **첫 attempt** semantic success, P7 단일 curl-command latency≤0.2s.
- Git read semantic success. `ls-remote`에 P7 clone/fetch latency threshold를 적용하지 않음.
- Window 안에 completion, 필수 freshness/Pod readiness/관측 coverage가 존재함.

Release command, 실제 all-Pod 수렴, first-good window, confirmation/deadline을 각각 기록한다.
조건 미충족은 `not recovered within observation window`다. 빠른 deny/낮은 rejection/CPU는
recovery가 아니다. P7 command latency와 schedule→completion의 queue/backoff 포함 operation
latency를 별도 배열로 보고하며 전체 campaign의 실패/누락 분모를 유지한다.

Operation/attempt/check/dispatch/admission/target rejection은 다른 단위다. C2 intentional429는
HAProxy `PR`, queue timeout503은 `sQ` termination으로 분리하며 target503 overflow와 섞지 않는다.
HAProxy queue/connect/response/total timing과 server/BACKEND 두 stat row를 보존한다.
Queue timeout은 backend response이지만 target server dispatch가 아니다. Stats listen 조회 log는 제외한다. Window check 보존식은
`새 check + 시작 queue/inflight = target admission + target rejection + admission shedding +
queue timeout + path error + 종료 queue/inflight`다. Residual을 분모에서 빼지 않는다.
Final proof는 drain 뒤 queue/inflight0와 target counter/access/app log·ingress/check 수의
mapping을 요구한다. 내부 Git check 수를1로 추정하지 않는다. Reset/rotation/불완전 수집은 invalid다.
C2 queue는 측정 대상, 다른 arm에서는 경쟁 병목 guard다.

`validate`는 local mechanism/recovery 계산만 하며 `pending-cloud-confounder-review`를 반환한다.
기존 P8의9개 동일-window confounder signal에 `proxy_series_freshness`,
`scaling_ownership_audit`를 더하여 actual file/window/hash/interpretation을 검토해야 `review`가 valid다.
`manual_replica_changes=0`과 arm별 HAProxy queue role도 필수다. Runtime 후 `compare`의 네 결과를
같은 incident의 backoff/admission/proxy-scaling corrective action에 연결한다.
결과가 없는 현재 corrective action은 검증 완료가 아니다.

## Campaign22 차단 원인과 cost-free 교정

[독립 검토](https://github.com/imcherry5778-labs/github-capacity-cascade-platform/pull/41#pullrequestreview-5749731895)와
[불변 raw/index](evidence/p9-mitigation-twenty-second-20261103/README.md)는 실행 source `ab59fda4d9e0f0ed837b77794b6d03a0db07d832`의
CLOSED/invalid evidence다. 신규 source로 과거 manifest/hash를 재결합하지 않는다. 다음 관측 보완의 Azure 효과는 미검증이다.

- **DECIDED — controller failure 유지.** demand+74.881s/+84.105s snapshot의 earlier HPA는
  `ScalingActive=False/FailedGetExternalMetric`, `currentMetrics`에 `type:""`인 빈 entry1개가 있어 usable current metric이 없다. Later collector의 AMW `observed`와
  resource `initializing-new-pod`를 합쳐 controller 성공으로 해석하지 않는다. 기존 bounded new-Pod AMW warming
  예외를 resource 초기화 전체로 넓히지 않는다. 기존 HPA GET 하나에 request/response monotonic clock,
  UID/resourceVersion/generation과 status hash를 기록해 snapshot guard의 바로 그 실패 상태에 연결한다.
  **REVALIDATE:** actual positive HPA metric/status와 all-Pod AMW·advancing CPU의 joint observation;
  초기화 중 잠정 HPA 실패를 허용할 필요가 있다면 controller의 실제 실패 시작/종료와 새 UID lifecycle 경계를
  먼저 입증해야 한다. Raw의 다음 demand+93.294s snapshot은 `ScalingActive=True`와 실제 External metric을 담지만 앞선 실패의 성공 증거로 소급하지 않는다. 현재 정보로 ingestion/controller 지연 상한을 새로 만들거나 과거 snapshot을 합칠 수 없다.
- **DECIDED — accounting residual 유지.** delta3156 HAProxy 중44건은 `400/CR, Tw=-1`이며 약435.336초에
  TCP readiness 기본10초 cadence와 부합한다. [TCP probe](https://kubernetes.io/docs/concepts/workloads/pods/probes/)는
  HTTP request 없이 연결을 검사하므로 가능한 기원이나 행별 attribution은 unknown이다. 나머지3112건과
  ingress3141건의 **29건 차이**도 남는다(성공11건·overload/error18건 차이). Per-row timestamp/ID가 없어
  최종 HAProxy server/backend 응답 counter·target log·ingress는 각각3141로 일치해 HAProxy 로그 완전성/수집 경계로 조사 범위를 좁혔으나, 손실 위치나 행별 기원은 확정하지 않는다. 다음 render는 HAProxy readiness를 기존 unlogged
  loopback stats8404의 `wget` exec로 옮겨 check8080에 probe 연결을 섞지 않는다. HAProxy3.4
  [공식 log fields](https://docs.haproxy.org/3.4/configuration.html#8.2.4)의 accept epoch/ms, process/request/log counter,
  HTTP request 수신 시간을 추가하고 target/ingress와 HAProxy log read 구간을 각각 기록한다.
  Peer/URL/header/body는 수집하지 않는다. **REVALIDATE:** 새 로그의 counter 연속성·boundary·실제 ingress mapping.
  `400` 일괄 제외, `Tw=-1`→0, residual 분모 제거 또는 equality 합성은 하지 않는다.
- **DECIDED — recovery fail-close 유지.** optimistic observation coverage로 분리 재계산해도 good window0이다.
  Recovery Issue attempt884개 중674개가0.2초 초과, command p50 약0.343초/p95 약1.308초,
  driver lag p95 약1.331초/max1.501207초다. 모든10초 window에 command SLO 실패가 있어 driver gate만
  바꾸어도 recovered가 아니다. Issue12 worker에 wave당24 arrivals이므로 두 번째 묶음의 worker 대기가
  command 시간에 의존한다. 기존 raw에는 submit clock이 없어 scheduler/host stall과 worker backlog의 비중은
  분리할 수 없다. 300초 이후24개 wave의 첫12개 lag p50은0.0215초, 다음12개는0.4092초이며 두 번째 묶음의 최초 issued는 첫 묶음 최초 completion 뒤 median0.000402초/max0.000602초다. Worker 대기가 driver lag에 포함된다는 근거다. 다음 source는 `submitted`를 기록해 schedule→submit과 submit→issued를 나누고 recovery
  window의 기존 실패 조건별 counts를 보고한다. command·operation latency와 기존0.2초/전체2초 기준은 그대로다.
  **REVALIDATE:** 같은 수요에서 controller/target 안정화 후 command SLO와 host/worker 지연의 실제 분리.
  기존 `validate`/`review`는 `not recovered` 자체를 run-invalid 조건으로 삼지 않는다. Valid run의 미회복도 negative result로 보고하며, 이번 validity는 별도 controller/accounting 실패로 막혔다.

**DEFERRED:** 새 source의 actual calibration·freeze·measured C0–C3·동일-window cloud confounder review와 recovery/rollback
검증은 새 실행 권한 없이는 진행하지 않는다. 실제 비교/회복/accounting/owned rollback이라는 P9 목표는 줄이지 않는다.
Azure/AKS/AMW/credential/Secret GET 또는 mutation 없이 수행한 source/archived-negative/synthetic 검증은 paid acceptance가 아니다.

CI는 complete exact-head PR file set와 immutable base SHA를 검증한 뒤 exclusive P9 delta만 shortcut으로 허용한다.
직전 immutable `run.head_sha`/`job.head_sha`의 동일 PR `local-platform` SUCCESS와 실제 local/recovery/upgrade/ownership/cleanup steps SUCCESS를
[Actions job metadata](https://docs.github.com/en/rest/actions/workflow-jobs)로 확인한다. Public metadata read만 사용하며
GitHub token 권한은 늘리지 않는다. 과거 run의 `pull_requests[].head/base`는 현재 PR을 가리키는 mutable link이므로 과거 실행 SHA/base 증거로 쓰지 않는다. Current base는 PR API의 전후 일치와 literal SHA의 local full diff로 고정한다. 이전 base는 그 run의 성공한 summary 단계 이름에 event base SHA를 담아 불변으로 보존·대조한다. 이 증거가 없거나 다르거나 모호하면 full runtime이다. API 오류·rename·shared/unknown path·base drift는 full runtime이다.
생략된 runtime은 다음 shortcut 근거가 되지 않는다. `make static`/CodeQL과 required check 이름은 유지하며,
생략 HEAD의 runtime은 명시적으로 **SKIPPED / not verified**다. Workflow/classifier 자체 변경은 full runtime이다.

위 CI 변경을 포함한 `e4a7575937fda7fb7b647b2f5d463996a6634945`의
[full local-platform 실행](https://github.com/imcherry5778-labs/github-capacity-cascade-platform/actions/runs/41613354166)은
실제 runtime 단계 전체 SUCCESS, job elapsed27분53초였다. Current HEAD의 runtime 생략은 이 이전 실행 결과와 구분한다.
Mutable PR 링크 교정과 불변 base metadata를 포함한 `2898c0dd739a69ff7d24ae16d3588b5fe3c44fa5`의
[최종 full 실행](https://github.com/imcherry5778-labs/github-capacity-cascade-platform/actions/runs/41618889681)도
runtime 단계 전체 SUCCESS, job elapsed28분53초였다. 성공 summary 단계가 기록한 event base는
`d9977cc9046485bb7b47849297ec9769a3629223`이며, 현재 PR API와 local literal base diff의 동일 SHA와 대조한다.

## 권한·자원·원복 경계

실제 승인 source/image/identity·scope·횟수와 current resource/권한/기한을 바인딩한다. 새 source의 paid 경로는 독립 review와 별도 사용자 결정 전 보류한다.
기존 AKS/node/PG/ACR/AMW를 재사용하며 새 compute/node/server/Disk/PVC, autoscaling/DNS/Argo stable mutation은 없다.
별도 승인된 임시 AKS RBAC Cluster Admin은 exact AKS1의 Entra user assignment ID와0600 user kubeconfig에 한정하고 원래 Owner를 보존한다.
소유 ACR source-SHA tag/digest는 source/build와 결합하고 live reference0·공유 tag/digest 부재를 확인한 exact 객체만 정리한다.
Mesh overlay는 revision shared ConfigMap의 provider/stat matcher만 UID/data guard로 변경하며 default CM/managed spec/Argo source는 바꾸지 않는다.
Experiment는 Pod≤4, requests와 limits 각각 CPU≤1500m/memory≤2048Mi이며 init/native sidecar/overhead와 headroom을 포함한다.
공유 managed controller 변경은 별도 승인·다른 ScaledObject 영향 확인이 필요하다. 필요할 때만 원본 SA annotation/template/UID를 보존하고 restart/restore한다.
P9 전용 KEDA UAMI/FIC는 actual OIDC issuer, exact `system:serviceaccount:kube-system:keda-operator`, `api://AzureADTokenExchange`와
existing AMW 한 resource의 Monitoring Data Reader에 한정한다. Actual SA/version/권한이 다르면 임의 확장하지 않는다.

Credential 경로는 action별 named allowlist·private env/stdin/0600 file로 한정한다. Generic Secret/raw Secret·불필요한 key를 읽지 않는다.
Allowlist는 admin bootstrap/preserve의 `forgejo/forgejo-admin` username/password, DB prepare/preserve의 `forgejo/forgejo-db` password와 소유 `p8-shared-gate/p8-db-read`의 필요한 PG fields뿐이다.
기존 Forgejo admin은 필요한 fixture bootstrap/폐기에만 사용하며 load는 non-admin disposable fixture/PAT≤2다.
DB는 기존 app role만 owned client Secret에 임시 복사하고 hostname/CA verify-full·TLS·read-only SQL을 검증한다.
Secret/credential·Authorization·private path·예외/cleanup 출력은 공개하지 않는다. PAT numeric ID를 mutation 전 보호 audit에 기록하고,
exact-ID revoke/재사용401·token list0·fixture login 차단을 확인하며 DB record 보존 여부를 기록한다.

같은 parent가 기존 `owned_forward` handle·watcher를 preparation부터 child 실행/cleanup까지 소유한다. Local13000 bind와 stable Pod UID를 확인하고
의도한 close/wait와 실제 child exit를 확인한다. 조용한 재시작·주기적 새 tunnel·liveness만으로 native semantic200을 대체하지 않는다.
각 run 전 authorized non-admin fixture의 direct native sentinel/path convergence를 확인한다.
실패한 run은 invalid/소비로 보존한다. Source-changing same-ledger recovery·measured retry·카운터 초기화는 지원하지 않는다.
같은 승인 안의 허용된 bounded recovery만 남은 승인 범위/횟수/기한·원복 reserve 안에서 수행한다. Closed campaign의 잔여 권한은 이월하지 않는다.

Whole reserve는1800+실제 initialize timeout I+kill5+6×600+1800초이며 candidate I840이면8045초다.
각 run/drain/rollback2220초와 initialize 포함3065초의 strict retention cutoff를 유지한다. 부족하면 새 위험 행동을 시작하지 않는다.
Owned cleanup은 CUSTOM exact UID 제거→shared CM UID/data guarded 복원→experiment controls/Secret/namespace→정상 native/TLS 검증,
fixture 폐기·소유 image exact tag/digest/로컬 tag·forward/권한 제거 순서다. KEDA 원본 SA/rollout을 복원한 뒤 소유 role/FIC/UAMI를 제거한다.
Argo revision/spec/Pod·기존 PVC/PV/Disk/Secret/CSI·원래 Owner와 fixed inventory 보존을 실제 evidence로 확인한다.
소유 객체/보호 사본만 제거하며 전체 environment finalization·물리적 secure erasure·외부 session 완전 containment를 주장하지 않는다.

## 실행 entrypoint와 남은 gate

현재 새 paid 실행 권한은 없다. 아래는 승인·binding·실제 gate를 통과한 operator의 기존 CLI 형태이며 자동 실행 순서가 아니다.
실행과 분석의 append-only ledger/lock을 유지하고 `measure`는 workload 전에 invalid 포함 intent를 소비한다.
`freeze`와 `review`의 실제 raw/window 검토, native auth/TLS·DB·UID/owner·resource/time·validity 조건은 생략하지 않는다.

```bash
python3 scripts/azure-mitigation.py render "$IDENTITY" "$PLAN" C0 "$NEW_RENDER_DIR"
python3 scripts/azure-mitigation.py transition "$IDENTITY" "$PLAN" C3 "$NEW_TRANSITION" "$APPROVAL"
# 새 통합 승인 뒤 구조/normal/native auth/TLS/resource gate → 기존 healthy journey + read-only 초기화:
python3 scripts/azure-mitigation.py initialize "$IDENTITY" "$PLAN" "$APPROVAL" "$CONTEXT" "$PRIVATE_DIR" "$NEW_INIT" "$INIT_LEDGER"
# 위 target telemetry gate 뒤 필요한 KEDA IAM/SA → 실제 scaler auth/cadence/full gate → fault 수렴 뒤:
python3 scripts/azure-mitigation.py measure "$IDENTITY" "$PLAN" C3 calibration "$NEW_RUN" "$APPROVAL" - "$LEDGER"
python3 scripts/azure-mitigation.py queries "$NEW_RUN" "$QUERY_IDENTITY" "$NEW_QUERY_PLAN"
python3 scripts/azure-operations.py collect "$NEW_QUERY_PLAN" "$NEW_COLLECTION"
python3 scripts/azure-mitigation.py postgres-metrics "$NEW_RUN" "$NEW_PG_METRICS"
# raw/negative/동일-window review, bounded 후보 확정 후:
python3 scripts/azure-mitigation.py freeze "$IDENTITY" "$PLAN" "$REVIEWED_CALIBRATION" "$NEW_FROZEN"
python3 scripts/azure-mitigation.py measure "$IDENTITY" "$PLAN" C0 measured "$NEW_C0" "$APPROVAL" "$NEW_FROZEN" "$LEDGER"
# C1/C2/C3도 동일 ledger/freeze와 각1회. 각 arm 전 같은 fault/initial replica 복귀를 확인한다.
python3 scripts/azure-mitigation.py validate "$NEW_C0" "$NEW_LOCAL_SUMMARY"
python3 scripts/azure-mitigation.py review "$NEW_C0" "$NEW_REVIEWED_SUMMARY"
python3 scripts/azure-mitigation.py compare "$NEW_C0" "$NEW_C1" "$NEW_C2" "$NEW_C3" "$NEW_FROZEN" "$NEW_COMPARISON"
```

실제 source SHA/cluster UID/image digest와 approval URL, current resource/quota/lifetime,
SA/FIC/operator 영향·auth·CRD/PodMonitor schema·actual series labels/inventory/freshness,
per-Pod traffic/normal healthy tests, admitted resource, timeout/queue 동작과 recovery 관측 cadence가
**필수 실행 gate**로 남아 있다. Source 검증을 Azure runtime PASS 또는 recovered로 표시하지 않는다.

## Evidence와 이전 기록

[제17차 결과/raw/원복](evidence/p9-mitigation-seventeenth-20261102/README.md),
[이전 실행 evidence](evidence/), [incident](incidents/)와 기존 PR commit/comment는 그대로 보존한다.
[현재 source-only 판단](https://github.com/imcherry5778-labs/github-capacity-cascade-platform/pull/41#issuecomment-6578609673)은 실행 승인이 아니다.

<a id="이전-통합-승인-범위--c06-preflight-이력"></a>
[과거 권한/원복 범위 원문](https://github.com/imcherry5778-labs/github-capacity-cascade-platform/blob/44879f36c9e517acf2dfdd502a75f71946d48b76/docs/p9-mitigation-recovery.md#이전-통합-승인-범위--c06-preflight-이력)은 당시 이력이며 현재 권한으로 재사용하지 않는다.
