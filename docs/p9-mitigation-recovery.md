# P9-W1 Mitigation & Recovery

현재 상태: **제9차 normal valid / initialize 전 operator 검사 오류로 중단 / P9-owned 원복 완료 / P9 acceptance 미충족**.
승인·실제 preparation source는 `ee75e3a336326ec5567b5f399ec08028169b02f1`다.
[제9차 통합 승인](https://github.com/imcherry5778-labs/github-capacity-cascade-platform/pull/41#issuecomment-6510384906),
[actual/negative/원복 evidence](evidence/p9-mitigation-ninth-20261030/README.md), [incident](incidents/p9-mitigation-ninth.md)를 연결한다.
승인 source보다 넓은 전체 retained Warning 검사를 operator가 추가해 startup/readiness 이력에서 멈췄다.
Source initialize/CPUStartup은 호출되지 않았으며 CPU 계약 실패로 분류하지 않는다. Shared mesh를 실제 admission 전에
dry-run 근거로 적용한 순서 이탈도 별도 기록했다. Initial/post-stop Pod3 Ready/restart0과 actual 자원 상한은 확인했다.
Normal1 valid/success/warmup 9operations/9attempts, initialize·CPU 관측·healthy·KEDA·calibration·각 measured arm0,
freeze 없음, mitigation/recovery not measured다. CUSTOM/shared/namespace·PAT20/image/role·보호 사본을 정리하고 stable을 보존했다.
준비/원복 누적9회·과거8회 archive와 비용은 유지한다. 최신 two-RG ActualCost KRW49,306.6929280465,
P9 incremental actual unknown이다. 사용자는 기존 누계와 별도인 추가 세전 USD100 검토 한도를 기존 +72h 유지·제9차1회에
승인했다. USD5 계획/USD10 검토 기준은 초기화하지 않으며 USD100도 billing hard cap이 아니다.
기존 승인 retention 계약을 유지한다. 추가 Azure 실행/기한 연장/전체 teardown·merge/P10은 없다.

## 제8차 historical 실행

현재 상태: **제8차 normal valid·무재시작 Pod 준비 통과 / CPU 준비300초 경계 중단 / P9-owned 원복 완료 / P9 acceptance 미충족**.
승인·실제 execution source는 `98e95e5850f2442e08a6306bf955aa12c0427b17`다.
[제8차 통합 승인](https://github.com/imcherry5778-labs/github-capacity-cascade-platform/pull/41#issuecomment-6505956066),
[actual/negative/원복 evidence](evidence/p9-mitigation-eighth-20261030/README.md), [incident](incidents/p9-mitigation-eighth.md)를 연결한다.
Warning은 생성 후121초 count8까지 보존·허용됐고 첫 fresh CPU/HPA 관측 뒤 이력이 변하지 않았다.
Fresh CPU/HPA 관측은 실제 poll3·5에 있었으나 중간/후속 stale poll과 source의 candidate 해제 경로로 ready는0이었다(후보 해제는 source 판독 추론).
Initialize1회는300.004초에 반복 내부 ingress Envoy config 수집 command_timeout으로 중단했다. CPU poll9 모두 pending이며
healthy journey·KEDA 변경·fault·calibration·각 measured arm0, freeze 없음이다. Synthetic/자동 retry/source 수정은 없다.
CUSTOM/shared/namespace·PAT19/image/AKS role·보호 사본 cleanup과 stable/KEDA/storage 보존을 확인했다.
준비/원복 누적8회·two-RG ActualCost KRW44,295.3701043718·P9 incremental unknown·과거 raw/checksum을 보존한다.
Source CI 성공과 actual positive preparation/mitigation/recovery 미완료를 구분한다. 제9차 자동 실행·merge/P10은 없다.
제8차 실행 당시 보존 기한은 당시 evidence를 따르며, 현재 보존 계약은 아래 승인된 +72h 기한을 따른다.

## CPU preparation source 계약

현재 source 계약: **제8차 freshness/candidate source-only 교정 / 실제 Azure positive gate 미통과 / P9 acceptance 미충족**.
[제8차 독립 리뷰](https://github.com/imcherry5778-labs/github-capacity-cascade-platform/pull/41#pullrequestreview-5704588146)에 따라
검증한 동일 CPU sample의 stale duplicate는 positive로 세지 않고 후보를 보존한다. 준비 완료 뒤 telemetry에서도
구조가 유효한 stale export는 기존 bounded polling 안에서 pending이며, 최종 완료에는 현재 fresh CPU/HPA와 target telemetry 모두 필요하다.
[독립 리뷰](https://github.com/imcherry5778-labs/github-capacity-cascade-platform/pull/41#pullrequestreview-5698170608)에 따라
첫 fresh positive CPU/HPA recovery 전에는 정확한 CPU HPA metric Warning의 count/time 증가를 기존 monotonic settling300초 안에서 허용한다.
별도 Warning 발생90초 상한은 제거하며300초 발생 상한으로 치환하지 않는다. 첫 recovery 관측 이후 새 Warning·count/time 증가와 history 유실은 계속 실패한다.
Sample window90초/freshness30초, snapshot30초/command15초, quiet15초·두 advancing valid sample, outer840초/kill5초는 유지한다.
과거 actual negative·비용·raw/checksum·원복 기록은 바꾸지 않는다. 이 교정 자체는 Azure 실행 승인이 아니며 새 exact-head 독립 review와 사용자 통합 승인이 필요하다.

## 제7차 historical 실행

현재 상태: **제7차 valid normal·무재시작 Pod 준비 통과 / CPU Warning 발생 경계 중단 / P9-owned 원복 완료 / P9 acceptance 미충족**.
승인·실제 execution source는 `1ce291523ecddb3918e3879f322e45dfca122ee6`다.
[제7차 통합 승인](https://github.com/imcherry5778-labs/github-capacity-cascade-platform/pull/41#issuecomment-6496347488),
[실행·negative·원복 evidence](evidence/p9-mitigation-seventh-20261029/README.md),
[incident](incidents/p9-mitigation-seventh.md)를 연결한다.
Backend Service/config·실제 ClusterIP/selector·Ready endpoint를 HAProxy 생성 전에 확인했고 initial Pod3는 Ready/restart0이었다.
Warmup·fresh kubectl v1.36.4 path/hash·context와 normal9 operations/attempts valid를 유지했다.
Initialize1회/57.649초는 같은 CPU HPA Warning의 count3→5·마지막 발생 Pod+91초/HPA+90초로
`CPU warning outside startup lifetime`에서 중단했다. Retained history age 또는 settling300초 timeout 실패가 아니다.
CPU poll1/pending, healthy journey·fault·KEDA 변경·calibration·각 measured arm0, freeze 없음이다.
Post-stop HPA/metric을 positive proof로 바꾸지 않았다. CUSTOM/shared/namespace·PAT18/image/AKS role·보호 사본을 정리하고 stable/KEDA/storage를 보존했다.
준비/원복 누적7회·two-RG ActualCost KRW38,284.28956189241·P9 incremental unknown·과거 raw/checksum을 유지한다.
당시 source 수정/paid replay 없이 중단했다. 위 후속 source-only 교정은 historical 실패를 성공으로 바꾸지 않는다. 추가 Azure 실행은 별도 통합 승인 대상이다.

## 제6차 historical 실행

현재 상태: **제6차 valid normal 통과 / initialization Pod restart guard 중단 / P9-owned 원복 완료 / P9 acceptance 미충족**.
승인·실제 execution source는 `30271ea59c4824b9bf4455ec038528891692d434`다.
[제6차 통합 승인](https://github.com/imcherry5778-labs/github-capacity-cascade-platform/pull/41#issuecomment-6494902133),
[실행·negative·원복 evidence](evidence/p9-mitigation-sixth-20261029/README.md),
[incident](incidents/p9-mitigation-sixth.md)를 연결한다.
Warmup·실제 kubectl v1.36.4 path/hash 사전 대조와 fresh normal context를 사용했고 normal9 operations/attempts가 valid였다.
Initialize1회는 `pod_not_ready_or_restarted`로 중단했다. HAProxy는 initial snapshot부터 restart3/Error였고
previous container log에 backend DNS 해석 실패가 기록됐다. Ready=True를 무재시작 proof로 사용하지 않는다.
CPU poll·healthy journey·fault·calibration·각 measured arm0, freeze 없음이다. Pod/history reset이나 initialize 반복은 없다.
CUSTOM/shared/namespace·PAT17/image/AKS role·보호 사본 cleanup과 stable/KEDA/storage 보존을 확인했다.
과거5회를 포함한 준비/원복 누적6회·비용·raw/checksum을 유지한다. Source 수정/새 Task 없이 실행 순서를 교정해야 하며
별도 통합 재승인 전 자동 반복하지 않는다. 후속 evidence HEAD는 실제 execution source와 구분한다.

## 제5차 historical 실행

현재 상태: **제5차 승인 실행 normal result metadata invalid / P9-owned cleanup 완료 / P9 acceptance 미충족**.
승인·실제 execution source는 `50aac4a9fab0881dfba41340f4a6ef0f5c4e0142`다.
[제5차 통합 승인](https://github.com/imcherry5778-labs/github-capacity-cascade-platform/pull/41#issuecomment-6493316821),
[실행·negative·원복 evidence](evidence/p9-mitigation-fifth-20261029/README.md),
[incident](incidents/p9-mitigation-fifth.md)를 연결한다.
Operator가 normal create에 `RESULT_PHASE=baseline`을 지정해 structured validator가 `invalid phase`로 거부했다.
Developer operations/attempts9개 성공·exit0과 valid provenance를 구분한다. Raw 수정/normal create 반복/flag 승격은 없다.
Initialize·CPU preparation·healthy journey·fault·calibration·각 measured arm0이며 namespace/CUSTOM/KEDA 변경 전 중단했다.
최종 native verify1과 PAT16/image/AKS 임시 role·보호 credential cleanup, stable/shared/KEDA/storage 보존을 확인했다.
준비/원복 누적5회·비용·과거 raw/checksum을 보존한다. 후속 evidence HEAD는 실행 승인 source가 아니다.
정상 경로 phase는 validator의 기존 `warmup` 계약을 사용해야 하며 재승인 전 자동 반복하지 않는다.

## 제4차 historical 실행

상태: **제4차 승인 실행 CPU preparation 실패 / P9-owned 원복 완료 / P9 acceptance 미충족**.
승인·실제 execution source는 `b484160cc0bf13af93d234a5ba30c4013f1d8e00`다.
[통합 승인](https://github.com/imcherry5778-labs/github-capacity-cascade-platform/pull/41#issuecomment-6490726245),
[독립 source review](https://github.com/imcherry5778-labs/github-capacity-cascade-platform/pull/41#pullrequestreview-5694111880),
[제4차 실제 실행·negative·원복 evidence](evidence/p9-mitigation-fourth-20261029/README.md)를 연결한다.
Initialize1회는 `readiness_resource_guard / ValueError / validation_failed`, private source error
`CPU warning outside startup lifetime`로 중단했다. CPU poll2개는 pending, healthy journey·fault·calibration·각 measured arm0,
freeze·mitigation/recovery 결과 없음이다. Later-read HPA 회복 status를 완료된 준비 proof로 승격하지 않는다.
Cleanup 뒤 실제 CPU window `1m5.166s` 표현만 cost-free source correction했다. 새로운 Azure 실행은 없으며
후속 HEAD는 실행 승인 source가 아니다. 아래 시간 계약은 추가 source-only correction이며 Azure 재실행은 없다.
과거 네 차례 준비/원복·비용·raw/checksum과 measured 상한·acceptance를 보존한다.
이전 제3차 `ffea5cb`의 [실행/원복](evidence/p9-mitigation-third-20261029/README.md)은 별도 historical evidence다.

이전 제2차 이력:
상태: **새 승인 source의 healthy initialization 준비 gate 중단 / P9-owned controls 원복 완료 / P9 acceptance 미충족**.
새 승인·실제 execution source는 `9c7b4be942e534dff2e36fe069e144bfa96d045a`다.
[사용자 통합 재개 승인](https://github.com/imcherry5778-labs/github-capacity-cascade-platform/pull/41#issuecomment-6486166268),
[독립 source gate](https://github.com/imcherry5778-labs/github-capacity-cascade-platform/pull/41#pullrequestreview-5692094220),
[실제 재개·negative·원복 evidence](evidence/p9-mitigation-resume-20261029/README.md)를 연결한다.
새 정상 create1/final verify1은 성공했고 initialize1회는 journey intent 전에 실패했다. Healthy journey·fault·calibration·measured는0,
freeze·mitigation/recovery 결과는 없다. Causal exception은 CLI가 노출하지 않아 unknown이며 경고/시간 초과로 단정하지 않는다.
이전 `c06ce67b2d438c7affde6b6934368b43afa4c1f4`의
[승인](https://github.com/imcherry5778-labs/github-capacity-cascade-platform/pull/41#issuecomment-6483350700)과
[preflight/negative/cleanup](evidence/p9-mitigation-preflight-20261029/README.md)은 historical로 보존한다.
아래 C0–C3 contract/상한을 유지하며 추가 workload를 자동 반복하지 않는다. 후속 evidence HEAD는 실행 승인 SHA가 아니다.
P8 [reviewed evidence](evidence/p8-controlled-cascade-20261029/README.md)와
[incident](incidents/p8-controlled-cascade.md)를 재사용하며 historical raw/validator는 보존한다.
P6/P7 drill, P8 전체 실험, factorial/조합 최적화, P10은 범위 밖이다.

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

공통 후보는 mitigation180s + recovery180s, drain/마지막 수집60s를 계획한다.
실제 scrape/ingestion/controller cadence를 calibration에서 확인하여 공통 mitigation을
`max(120s, 3×(scrape+ingestion+controller))` 이상, 10초 배수로 **measured 전에** 고정한다.
코드는 mitigation≤300s, recovery120–240s, 두 구간 합계≤540s, arm 계획≤600s를 제한한다.
Kubernetes 명령은 최대15s, 한 snapshot의 Kubernetes 수집 budget30s, Prometheus query는
각5s다. Deadline/관측 부족은 raw로 보존하고 새 run으로 자동 보충하지 않는다.

| 상한 | 후보360s / run | 최대로 승인 요청하는540s / run |
| --- | ---: | ---: |
| Wave | 72 | 108 |
| Issue logical operations | 1,728 | 2,592 |
| Issue attempts (max2) | 3,456 | 5,184 |
| Supplemental Git operations/attempts | 72 | 108 |
| 합계 logical operations / attempts | 1,800 / 3,528 | 2,700 / 5,292 |

Calibration **총2회 이하**(C3 및 C2를 우선 후보로 삼고 C1 seed/범위는 cost-free로 고정), measured는 C0→C1→C2→C3 **각1회**, 합계 최대6회다. Calibration 자체는
한 arm만 실행하며 조합 arm을 만들지 않는다. Candidate 변경도 두 번의 calibration budget
안에서만 한다. 최종 measured plan과 다른 이전 calibration hash는 ledger에 남긴다.
상한 합계는 logical16,200 / client attempts31,752, 관측+drain60분이다.
Git 내부 HTTP/check 수는 attempt 수와 다르므로 이 숫자가 check 상한이라는 주장은 없다.
각 run의 direct sentinel은 단일 worker, 요청 간1초 이상, 명령 timeout10초로 최대 약600회
(6회 약3,600회)이며 public demand와 별도다. 초기/최종 정상 journey는 각1회,
healthy-gate journey1회, native-deny/controlled-deny/path 확인은 각각1회로 요청한다.
모든 probe·actual HTTP/check 수·telemetry query 수를 실행 ledger에 기록한다.
추가 반복은 자동 실행하지 않고 새로운 승인 대상이다.

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
재개 시 actual version이 다르면 중단하고 matching contract를 확인한다. 이전 source correction 당시 runtime 조회/upgrade는 없었고, 이번 승인 재개에서 같은 image를 read-only 재확인했다. 실제 scaler 인증은 미검증이다.
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
보존 archive의 positive sample은 bootstrap cluster뿐이며 **target inbound positive sample은 없다**.
이를 inbound 초기화 또는 query 성공으로 재해석하지 않는다.
`sum(rate(...[1m]))`의 unit은 rejected checks/s이며 raw cumulative counter를 threshold에
연결하지 않는다. 후보 threshold0.5, calibration 허용0.25–1.0이다. 이는 rejection을 낮추려는
반응 후보이며 capacity2가 SLO를 복원한다는 가정이 아니다. Gauge의 짧은 peak는 scrape가
놓칠 수 있어 counter rate를 택했으며 high-frequency admin 관측/log와 따로 대조한다.

Query는 per-Pod rate·원본 timestamp freshness·up=1 및 **kube_pod_info의 target 수와 coverage**를
guard한다. Inventory series의 label/freshness와 target Pod들의 실제 UID/name도 대조해야 한다.
Empty/partial/stale/error를0으로 바꾸지 않고 `ignoreNullValues=false`, TLS verify를 사용한다.
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

준비용 gate는 fault/측정용 full telemetry gate와 분리한다. `initialize`도 새 exact-source Azure 승인과
normal/native-auth/TLS evidence, 같은 actual identity/plan hash/limits/retention을 요구한다.
`healthy_gate_passed`/`runtime_preflight_passed`를 초기화 시작을 위해 true로 만들지 않는다.

CPU HPA 준비는 별도 **read-only settling** 경계를 사용한다. `healthy_initialize` 시작부터 configuration을 포함한
monotonic hard cap **300초**, positive proof 확보 즉시 완료하며 성공 보장이나 고정 대기 시간이 아니다.
poll 간격 최대15초이며 매 collection의 기존30초/명령별15초 budget은 유지한다. 추가 traffic/journey 반복은 없다.
Configuration/image/hostname/owner 및 Pod/DB/node/admission/headroom은 매 poll에서 즉시 검사한다.
첫 fresh positive CPU/HPA recovery 전까지 허용하는 Warning은 정확히 같은 namespace·UID의
`HorizontalPodAutoscaler/hpa-app-cpu`에 속한 `FailedGetContainerResourceMetric`/`FailedComputeMetricsReplicas`뿐이다.
이 Warning의 반복/count·last timestamp 증가는 별도 객체 age/발생 시간 제한 없이 기존 monotonic settling300초 안에서 허용한다.
Pod/HPA 생성≤first≤last≤snapshot 시각을 요구한다. First timestamp/reason 불변, count/time 단조 증가·동시 변경과 history 보존을 검증한다.
다른 Warning/owner/미귀속 event, timestamp 선후관계 위반·history drift/유실은 즉시 실패한다.
첫 fresh positive CPU/HPA recovery 관측에서 recovery latch를 고정하며 이후 새로운 Warning 또는 기존 Warning의 count/time 증가는
quiet15초/두 번째 sample을 기다리는 중이나 중간 metric 누락 뒤에도 즉시 실패한다.
Runtime.since를 재설정하거나 warning 이력을 삭제하지 않는다.

`Runtime.guard(cpu_preparation=True)`는 이미 수집한 owned Pod 중 CPU target의 namespace/name/UID,
creationTimestamp/deletionTimestamp와 Ready status/lastTransitionTime만 별도 `cpu_preparation_pods`로 제공한다.
CPUStartup은 이 opt-in lifecycle을 사용한다. `admission.pods`의 name/uid/containers 자원 요약을 원본 Pod로 취급하지 않으며
P8 admission accounting·기본 guard 계약은 유지한다. Lifecycle 필드 누락/UID·Ready transition drift는 fail-closed다.

준비 성공에는 고정 target UID의 실제 Ready/무재시작·변하지 않은 Ready transition, `app` CPU 양수 sample,
sample window 전체가 Ready 이후이며 sample age≤30초인 관측을 요구한다. 실제 `38.03s`/`1m5.166s` 표현을 초로 해석하되 window≤90초를 유지한다. CPU HPA spec/UID/unowned CPU controller가
일치하고 AbleToScale=True/ScalingActive=True 및 `ContainerResource/cpu/app`의 양수 currentMetrics averageValue/averageUtilization도 있어야 한다.
ObservedGeneration이 있으면 actual generation과 대조한다. 필드가 없는 actual HPA에 generation을 합성하지 않는다.
Startup 실패의 실제 placeholder `currentMetrics=[{type:""}]`는 알려진 ScalingActive=False 상태에서만 pending이며 정상 metric이 아니다.
누락/stale/pre-Ready sample 또는 HPA 회복 미확인은 준비를 통과하지 못하고 bounded timeout에서 실패한다.
Zero/unknown을 positive metric으로 승격하지 않는다. Pod/HPA UID·Ready transition/owner drift는 기다리지 않고 실패한다.
첫 후보 이후 **직전 검증 sample과 timestamp/window/app CPU가 같은 stale duplicate**이며 positive HPA와 ScalingActive transition,
Warning history·Pod/UID·DB/node/resource invariant가 유지되면 후보를 보존한다. 이 poll은 pending/false이며 sample 수를 늘리지 않는다.
다른 metric 누락/새 stale timestamp/HPA 미회복은 기존대로 후보를 취소한다. 새 fresh advancing sample은 매번 기존 window/freshness/quiet/HPA 조건을 만족해야 한다.
마지막 검증 sample보다 timestamp가 역행하거나 같은 timestamp의 window/app CPU가 바뀌면 실패한다.

Warning의 safe reason/time/owner·event UID/count를 append-only `cpu_preparation_warning`으로 보존한다.
`cpu_preparation_poll`에는 실제 CPU timestamp/window/value, HPA spec/UID/current metric·ScalingActive/transition 및 pending/ready를 기록한다.
원문 warning message/body/argv는 넣지 않으며 unknown reason/owner는 안전한 분류로만 남긴 뒤 실패한다.
Startup warning이 있으면 HPA ScalingActive 회복 transition이 마지막 warning 이후여야 하고, 최소15초 quiet와
15초 이상 떨어진 두 번의 advancing valid CPU sample·변하지 않은 warning UID/count/time을 확인한 뒤에만 준비를 통과한다.
이미 양수 metric/HPA가 정상이고 warning이 없는 baseline은 별도 대기 없이 통과할 수 있다.
회복 뒤 healthy journey/telemetry polling에서 새 warning·count/time 증가·history 유실·HPA/invalid·missing metric 상태 악화는 실패한다.
완료된 CPU 준비 proof와 현재 poll의 fresh 판정은 구분한다. Telemetry에서는 Ready 전체 window와 양수 CPU 구조가 유효하고
HPA positive/ScalingActive transition이 유지되는 stale export(새 timestamp 포함)만 기존 `ingestion+3×scrape` deadline 안에서 pending으로 관측한다.
Stale poll은 `CPUStartup.completed`를 보존해도 return/status는 false/pending이다. `healthy_initialize`는 target signal이 observed여도
그 poll의 CPU/HPA가 fresh positive가 아니면 완료하지 않는다. Fresh CPU/HPA만 있고 target telemetry가 없을 때도 완료하지 않는다.
최종 shared-path ALLOW/correlation·native auth·target inbound log/counter·per-Pod freshness/rate 검증은 그대로이며 journey를 반복하지 않는다.
Measured/C3의 기존 strict warning/controller/telemetry guard와 P8 기본 호출은 이 예외를 사용하지 않는다.

300초 선택 근거는 4차 생성07:39:10·Ready07:39:26·later-read HPA transition07:40:40과
post-stop sample07:41:31/window65.166초다. 이 window를 참고한 synthetic 다음 sample 간격65초와
poll≤15초·수집≤30초를 포함하는 bounded 후보이며 실측 성공 시간은 아니다. 실제 sample cadence는 미확정이다. [Kubernetes HPA 문서](https://kubernetes.io/docs/concepts/workloads/autoscaling/horizontal-pod-autoscale/#pod-readiness-and-autoscaling-metrics)의
Ready 전체 sample window/default CPU initialization period5분도 재확인했다. 해당 AKS flag 값은 미확인이다.
제7차 Pod+91초의 실제 Warning count3→5는 첫 positive 전 pending으로 replay한다.
실제 실패 시 full guard는 archive에 없어 마지막으로 관측한 pending HPA/sample을 유지한 reconstruction임을 명시한다.
P8 `guard()`→P9 `CPUStartup`에 실제 UID/owner/reason/count/time·Pod lifecycle을 통과시키고,
post-stop HPA/currentMetrics·stale CPU만으로 준비 완료를 주장하지 않는다. 후속 fresh advancing CPU sample2개는 명시적 synthetic이다.
미회복 replay는 monotonic300초에 timeout하며 Warning 이력/첫 candidate 이후 재발·기타 safety negative와 제4차 관련 회귀를 유지한다.
CPU sample window≤90초, freshness≤30초는 settling300초와 별개이며 별도 Warning 발생 deadline은 없다.
제8차9-poll도 같은 P8 guard adapter를 거쳐 replay한다. Full guard/UTC poll 시각은 미기록이므로 command-end UTC/failure monotonic anchor로
wall clock을 재구성하고, 실제 sample/HPA/Warning projection·poll 간격·archived lifecycle을 유지한다. DB 응답은 기존 adapter의 synthetic이다.
원래60개 회귀와 함께 Poll3 후보→Poll4 동일 stale pending/후보 유지→Poll5 fresh advancing에서 offline 준비 완료,
Poll6–9 stale는 모두 pending/false임을 확인한다. **이는 수정 class의 cost-free replay이며 제8차 actual ready0을 변경하지 않는다.**
전체 healthy_initialize 회귀는 실제 준비5 polls와 stale poll6 뒤 명시적 synthetic journey/server/Prometheus·fresh CPU 후속 sample을 사용한다.
Target signal observed+stale CPU만으로 완료하지 않으며 fresh CPU와 positive target path가 함께 있을 때만 완료한다.
Stale-only는 settling300초 또는 기존 telemetry deadline에서 실패하고 HPA/Warning/owner·UID·sample history·DB/node/resource negative도 유지한다.
Cost-free 검증: P9 regression66개(제4·7·8차 archive와 synthetic 구분, quiet 완료 전 recovery latch 및 보존 기한 reserve 포함), P8 regression38개와 `make static`을 통과했다.
동일 제7차 입력을 이전 source class에 넣으면 Pod+91초에서 거부하고 수정 class에서는 pending인 것을 대조했다.
여덟 차례 raw archive의 기존 byte/SHA256를 보존했으며 final exact-head CI·독립 review는 GitHub에서 별도 확인한다.

`initialize` CLI는 GNU `timeout --signal=TERM --kill-after=5s`의 process group 안에서 내부 `_initialize`를
1회 호출한다. Operator는 public `initialize`를 사용하며 더 짧은 외부 wrapper를 씌우지 않는다.
외부 TERM 시점은 `330 + 300 + 30 + 100 + ingestion + 3×scrape + 5`초다.
330초는 기존 Runtime setup의60초 command4개(git2/Azure2)와15초 kubectl6개 합계이며 command 상한 증액이 아니다.
이후 settling300초(configuration 포함), 별도 baseline stats/logs collection30초, journey90초+kill/wait 여유10초,
telemetry `ingestion+3×scrape`, dispatch 여유5초를 합한다. 현재 후보는 **840초**, 허용 cadence 최대는1005초,
각각 TERM 뒤 kill-after5초이며 measured run600초와 구분한다. 정상 시 바로 종료한다.
Settling의 각 configuration+guard collection은 `min(now+30, settling deadline)`을 공유하며 command≤15초를 유지한다.
Baseline stats/logs는 완료된 settling collection과 분리한30초를 사용한다. Preparation 진입 시 외부 timeout+5초 kill 여유와
기존 run/drain+30분 rollback reserve가 retention 전에 들어가는지도 검사한다.

실패 event는 고정된 `stage`, 전체/단계 `elapsed_seconds`/`stage_elapsed_seconds`, 허용된
`exception_class`와 제한된 `error_code`를 output 및 append-only initialization ledger에 기록하고 예외를 다시 전파한다.
Journey intent 이전에는 `configuration` → `readiness_resource_guard` → `baseline_stats` → `baseline_logs`를 구분한다.
이후 journey/accounting/validation·telemetry configuration/resource/signal·positive path도 별도 stage로 기록한다.
Warning guard는 typed `warning_event`, 기존 snapshot command budget 소진은 `snapshot_command_budget_exceeded`,
subprocess timeout은 `command_timeout`으로 구분하며 오류 문자열로 원인을 추정하지 않는다.
공개 event에는 message/argv/stderr/body/path나 임의 exception class 이름을 넣지 않는다. 알려지지 않은 class는
`BaseException`/`unknown_failure`로 기록한다. 상세 exception chain은 기존 mode0700 private directory의
`initialization-failure.txt`를 mode0600/exclusive-create로 보존한다. 이 파일은 raw archive/publication 대상이 아니며
승인된 보호 local cleanup 경계에서 제거한다. 기존 파일/쓰기 오류는 덮어쓰지 않고 안전한 별도 code를 남기며 원래 실패를 유지한다.
실패 record는 `runtime_preflight_passed=false`이며 정상/healthy/runtime 승인 flag를 변경하지 않는다.
이 source-only 진단 보완은 과거 unknown 원인을 소급 입증하거나 새 Azure 실행을 승인하지 않는다.

1. 전용 kubeconfig/ownership/stable delta, exact CUSTOM hostname/provider/selector와 fail-closed/native auth/TLS,
   pinned image/controller, hold0/capacity1024/readiness, 실제 sidecar/init/overhead 포함 resource/headroom을 확인한다.
2. 이미 계획한 bounded healthy journey **1회**를 재사용한다. Intent를 append-only initialization ledger에 먼저 기록하고
   90초에 process group에 TERM을 보내고 kill-after5초로 자식 명령도 제한한다. Journey raw는 기존 schema의 `phase=warmup`, 외부 initialization record는 `measured_denominator=false`로
   측정 schedule/분모에 섞지 않되 API request intent/status/bytes와 실제 같은-window ingress/check log delta를 보존한다.
   Git operation을 HTTP1회로 추정하지 않는다. Journey 실패·timeout도 사용된 행동이며 telemetry 때문에 재시도하지 않는다.
3. Journey 이후 최대 `ingestion+3×scrape` 동안 scrape 간격의 **read-only** polling으로 동일 UID/config,
   admin/native stat, ingested target series, freshness와 rate2 samples, guarded query를 확인한다.
   성공 전에 같은 journey window의 신규 ALLOW check·target inbound200·ingress native response log가 양수이며
   수가 일치해야 한다. 기존 validator로 warmup journey의 exact source/transport·9개 성공 attempt를 검증하고,
   각 attempt마다 해당 operation/attempt ID의 check가 있어야 한다. 기존 fixture/settle/anonymous/Git 보조 요청도
   opt-in auxiliary correlation으로 같은 run에 귀속한다. Git1회=HTTP1회/check1회를 가정하지 않는다.
   Check ID/ALLOW·credential/body exclusion·HAProxy hop·시간 범위, proxy cluster/status와 실제 target counter를
   대조하며 zero/missing/mismatch/rotation/denied/unattributed는 실패한다. 기존 private anonymous401/404는
   shared gate ALLOW 이후의 native auth 결과이며 ext_authz deny/error와 구분한다. Proxy format에는 correlation ID가
   없어 proxy 대응은 같은 window의 count/cluster/status 수준이며 이를 per-request trace라고 부르지 않는다.
   초기 stat가 없던 UID는 마지막 누적 counter와 전체 UID target log를 대조하고 누락 snapshot을0으로 합성하지 않는다.
   이미 존재하던 observed series는 이 positive-path proof를 대신하지 않는다.
   두 gate를 통과하면 `ready_for_keda_authentication=true`이며 **`runtime_preflight_passed=false`는 유지**한다.
   필수 query/stat 부재가 지속되면 timeout으로 중단한다. Invariant/unknown/query 오류는 즉시 전파한다.
4. 위 target mapping/telemetry gate 뒤에만 KEDA UAMI/FIC/workspace role 및 필요한 SA annotation/rollout을 준비한다.
   다른 ScaledObject 영향·원본 상태와 승인된 restart 횟수를 먼저 확인하고 실제 scaler 인증을 검증한다.
   Operator identity의 query 성공은 KEDA scaler 인증 성공이 아니다. 이후 full runtime gate → fault/calibration/freeze/measured 순서다.

P9 admin 요청은 `stats?format=json`, native 요청은 `stats/prometheus`이며 `usedonly`/filter를 추가하지 않는다.
[Envoy admin](https://www.envoyproxy.io/docs/envoy/v1.38.0/operations/admin)의 JSON과 사용 여부/filter에 따른 누락을
실제 numeric0과 구분한다. 관측 payload에 없는 counter는 deferred/unused일 수 있어도0으로 만들지 않고,
인위적 counter 증가나 임의 traffic으로 보완하지 않는다. Archive의 filtered negative만으로 deferred option이
실제 설정됐다고 주장하지 않는다. 기존 Pod 및 P8의 기본 strict stat 검사는 유지한다.

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

## 이전 통합 승인 범위 — c06 preflight 이력

이전 승인·실행 source는 **`c06ce67b2d438c7affde6b6934368b43afa4c1f4`**다. 승인 기록 URL과
actual identity, plan hash, limits를 보호된 입력에 연결했고 `P9_AZURE_APPROVED`도 같은 SHA를 사용했다.
Gate 중단·원복 상태와 실제 flag는 evidence의 `approval-binding.json`에 보존했다.
아래는 그 승인 범위이며 후속 문서/evidence HEAD나 다른 SHA를 실행 승인으로 치환하지 않는다. Normal/healthy/live preflight의 실제
evidence 없이 approval JSON의 flag를 true로 채우지 않는다.

[승인 요청 시 management read](evidence/p9-source-20261029/management.json): subscription
`e5a6bc91-44fb-46aa-90ee-badd6d197609`, Entra User object ID
`6f750efc-cb1a-4a49-b6e7-23fc6061e25a`, Korea Central, `rg-ccp-environment-krc-p6`.
AKS `aks-ccp-krc-p6`는 Running/Succeeded,1.36.4, asm-1-30, D4s_v4 node2/autoscaling OFF다.
PG `pg-ccp-p6-krc-57781024`/ACR `acrccpp6krc57781024`/AMW `amw-ccp-krc-p6`/LAW
`law-ccp-krc-p6`와 기존 Disk/PVC를 재사용한다. 이 사전 조회에서는 Cluster UID/Argo/CRD/operator/SA/admission을
관측하지 않았다. 이후 실제 확인·미확인·중단 상태는 연결된 실행 evidence를 따른다.
이들은 관련 **mutation 전 read-only gate**이며 mismatch 시 중단한다.

이 source에 승인된 exact 외부 행동과 원복은 다음과 같다.

- 위 User에 AKS resource 하나의 임시 `Azure Kubernetes Service RBAC Cluster Admin` assignment.
  전용 mode0600 kubeconfig의 Entra user auth를 사용하고 종료 시 소유 assignment ID만 삭제한다.
  기존 Owner2개는 보존한다. Secret 읽기 전에 실제 identity/owner/Argo/정상성을 확인한다.
- 기존 ACR의 `ext-authz-sim:<approved-source-sha>` 한 tag에 local source build/publish,
  digest 확인·source/image 동결. 새 registry/ACR Tasks/새 publish IAM은 없다.
  P9-owned tag/digest가 공유되지 않았음을 확인한 뒤 exact 객체만 cleanup한다.
- `forgejo/forgejo-admin` version2의 이번 P9 한정 재사용·rotation 생략과 `forgejo/forgejo-db`
  필요한 credential 읽기. 기존 stable Secret 변경 없이 non-admin disposable fixture2개/PAT2개,
  private journey repo/Issue/PR를 준비한다. Administrator는 load에 사용하지 않는다.
  `p8-shared-gate/p8-db-read` 하나에 기존 app DB role만 임시 복사, TLS verify-full/read-only SQL.
  종료 시 Secret 삭제, exact PAT ID revoke/401 확인, 계정 login 차단, fixture 기록 보존 여부 기록.
- Removed P8의 이름을 재사용한 **P9 campaign 소유** namespace `p8-shared-gate`, fixture,
  Sidecar fault/hold, CPU HPA/ScaledObject/TriggerAuthentication/PodMonitor와 hostname exact CUSTOM policy.
  Mesh overlay는 `scripts/azure-cascade.py mesh`로 revision shared ConfigMap의 provider/stat matcher만
  추가한다. 실제 UID/data 보존·restore conflict guard를 적용한다. Default CM/managed spec/Argo source는 수정하지 않는다.
- P9 전용 UAMI **`p9-keda-prometheus`**를 같은 RG에 생성하는 안을 요청한다. Resource ID는
  `/subscriptions/e5a6bc91-44fb-46aa-90ee-badd6d197609/resourceGroups/rg-ccp-environment-krc-p6/providers/Microsoft.ManagedIdentity/userAssignedIdentities/p9-keda-prometheus`.
  새 compute/server가 아니며 client/principal ID는 생성 뒤 보존한다. FIC 이름 `p9-keda-operator`,
  issuer는 management.json의 actual OIDC URL, subject **`system:serviceaccount:kube-system:keda-operator`**,
  audience **`api://AzureADTokenExchange`**다. Actual SA가 다르면 조용히 바꾸지 않고 중단한다.
  최소 role **Monitoring Data Reader**를 기존 `Microsoft.Monitor/accounts/amw-ccp-krc-p6` resource
  **하나**에만 부여한다. 기존 고권한 control-plane/Forgejo identity를 대신 재사용하지 않는다.
- 위 [Microsoft managed 절차](https://learn.microsoft.com/en-us/azure/aks/keda-workload-identity)에 따라
  실제 필요할 때만 `kube-system/keda-operator` SA client-id annotation과 **operator rollout restart1회**를
  요청한다. 원래 annotation/UID/template fingerprint를 보존하고 workload-identity token/env 주입을 검증한다.
  기존이 이미 올바른 경우 중복 변경하지 않는다. 원복은 원래 annotation 복귀와 restart1회, actual
  controller ready 확인이다. 이 변경은 **experiment quota 밖의 shared managed controller 영향**이며
  다른 ScaledObject/운영 workload 영향이 있으면 mutation 전에 보고한다. Helm/resources/임의 spec 변경은 없다.
  끝나면 소유 workspace role assignment → FIC → UAMI를 exact ID로 제거한다.

Experiment는 **Pod4 / requests와 limits 각각 CPU1500m / memory2048Mi** 상한이다.
기존 P8 actual validation init/native sidecar를 보수적으로 합친 최대 예상은 CPU1450m /
memory1664Mi다. 실제 주입/overhead와 node headroom을 다시 검증한다. 새 node/server/Disk/PVC,
node autoscaling 변경은 없다. 부족하면 상한/acceptance를 임의 확대·완화하지 않는다.

[승인 요청 시 비용](evidence/p9-source-20261029/cost.json)은 두 RG의2026-10-28 합계
**KRW16,015.5402320629**다. 조회는 성공했지만 청구 지연/완전성 제한이 있고 P9 증가분은 unknown이다.
[승인 요청 시 retail 입력](evidence/p9-source-20261029/prices.json)을 기준으로 추가 image0.2GB
월 환산USD0.02 + logs1GB×USD3.11 + metrics100만×USD0.11/천만=USD0.011 + egress1GB×USD0.12,
query/변동 여유USD1.739를 합친 **증가분 검토 예상USD5**, 추가 검토 예산USD10을 요청한다.
이는 계측량 가정이며 billing hard cap이 아니다. 기존 node/server 유지비와 shared controller
rollout 비용/영향을 포함한 정확한 P9 실비는 분리 unknown이다. 재시작 때문에 새 node는 만들지 않는다.
Actual volume/cost·새 비용 근거가 budget을 넘으면 추가 run을 시작하지 않는다.

[사용자 +72h 보존 승인](https://github.com/imcherry5778-labs/github-capacity-cascade-platform/pull/41#issuecomment-6509128514)에 따라
현재 Environment 기한은 **2026-11-02 10:30 KST** (`2026-11-02T01:30:00Z`),
Foundation/Bootstrap은 **2026-11-03 00:33 KST** (`2026-11-02T15:33:00Z`)다.
P8 Runtime과 P9 DEADLINE은 같은 Environment 기한을 사용한다. 이전 기한 이후의 승인된 실행 진입을 허용하되
새 기한 직전/정각/직후와 initialization840초+kill5초/run/drain60초/rollback30분 reserve 경계를 직접 회귀로 검증한다.
이 source-only 변경은 Azure provider TTL 변경이나 제9차 실행 승인이 아니다. 과거8회 evidence의 당시 날짜·raw/checksum·비용은 그대로다.
3일 보존에 따른 추가 운영 비용은 기존 USD5/누적USD10 검토 기준에 포함된 것으로 가정하지 않으며 P9 incremental actual은 unknown이다.
Run+60s drain+**30분 원복 여유**가 남지 않으면 실행 gate가 새 run을 거부한다.
자동 연장/삭제나 P11 이전 전체 teardown은 없다. Cleanup은 CUSTOM policy 우선 제거 → shared
CM data fingerprint 원복 → experiment controllers/fixtures/monitor/Secret/namespace → 소유 image,
IAM/FIC/UAMI, PAT/fixture login/보호 local 사본/port-forward 순으로 exact identity를 확인한다.
KEDA annotation/rollout 원복은 FIC 삭제 전에 수행한다. 정상 HTTPS/native auth, Argo revision/spec,
원래 PVC/PV/Disk/Secret 보존을 확인한다. P9-owned cleanup과 전체 environment finalization은 다르다.

## 제2차 통합 재개 승인 delta와 실제 사용 이력

새 exact source `9c7b4be942e534dff2e36fe069e144bfa96d045a`의 CI/source gate 뒤 위 통합 재개 승인을 받았다.
아래 재준비 범위가 승인됐으며 실제 사용/미사용은 새 실행 evidence를 따른다. Normal proof만 실제 통과했고
healthy/runtime-preflight flag는 false다. Initialize 준비 gate 실패 후 원복했으며 기존 승인 SHA를 다른 HEAD로 치환하지 않는다.
이전·이번 준비/원복과 비용 unknown을 함께 보존하고 다음 유료 workload를 자동 시작하지 않는다.

- 새 source/image digest의 재build/publish·cleanup, fixture/PAT 재준비와 version2 admin credential의 명시적 재사용,
  전용 AKS 임시 권한/보호 kubeconfig, experiment Secret/fixture/shared overlay 재준비·원복.
- 위 healthy 초기화 순서와 실제 request accounting, 그 뒤 새 UAMI/FIC/workspace RBAC 및 **실제 필요할 때만**
  KEDA annotation/restart·원복. 이전 operator apply restart1/restore restart1은 이미 사용한 행동이며
  새 승인에는 필요 시 apply/restore 각1회의 delta와 다른 workload 영향 확인이 포함됐으며 이번 실제 사용은0/0이다. 자동 반복 한도 확대는 없다.
- 이전 normal create1(구조화된 developer attempts9)/final verify1, image publish/delete1, IAM/fixture 준비·원복은 사용된 행동이다.
  이전 Healthy/CUSTOM/fault/calibration/measured는 각각0이었다. 이번 CUSTOM은 적용/제거했고 healthy journey·fault/calibration/measured는0, freeze·non-recovery 결과는 없다. 기존 ledger/raw/negative/checksum을 보존하고
  새 preparation ledger와 연결한다. Calibration 총≤2와 measured 각 arm1회, resource/cost/retention 상한은 유지한다.
- 이전 비용 관측 before/final **KRW18,845.545320581**, P9 증가분 unknown을 이어간다. USD5 예상/USD10 검토 예산을
  0으로 초기화하지 않는다. 재개 전 기존 준비·원복을 포함한 누적 비용/사용량 근거를 다시 확인한다.
- 과거 PAT numeric ID/DELETE status와 HTTP501 body 미보존은 historical limitation이다. 과거 credential 작업을 재실행하지 않는다.
  다음 PAT 발급 시 numeric ID를 후속 mutation 전에 보호된 credential/audit에 기록한다. 기존 request helper는 method/path/expected status를
  호출 전에 append하고 status와 response bytes를 body와 별도로 보존하여 빈204를 처리한다. 다음 exact-ID revoke에서도
  동일한 기록 순서와 분리된 HTTP status/body 처리를 사용하며 401·login 차단 결과를 보존한다. 별도 cleanup harness는 없다.
  Prometheus query는 intent/hash와 응답, HTTP failure status/body를 보호된 evidence에 보존한다(서버가 echo한 bearer는 redact).

Environment/Foundation 기한 연장, 새 compute/Disk/PVC, node autoscaling/DNS 변경, P6/P7 drill/P8 전체 실험, P10은 요청하지 않는다.
필수 gate 실패나 승인 초과이면 새 workload를 멈추고 기존 승인 문서의 안전 원복 순서를 따른다.

## 실행 entrypoint와 남은 gate

Source gate는 직접 회귀, P8 historical replay, `make static`, exact-head PR CI와 독립 review다.
제7차 actual CPU preparation 실패 뒤 Warning 시간 계약을 source-only 교정했다. 실제 positive/telemetry gate는 미통과다.
아래는 entrypoint 사용 형식이며 성공한 campaign 기록이 아니다. 재개 전 새 source gate와 필요한 승인을 확인한다.

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

실제 source SHA/cluster UID/image digest와 approval URL, current cost/quota/lifetime,
SA/FIC/operator 영향·auth·CRD/PodMonitor schema·actual series labels/inventory/freshness,
per-Pod traffic/normal healthy tests, admitted resource, timeout/queue 동작과 recovery 관측 cadence가
**필수 실행 gate**로 남아 있다. Source 검증을 Azure runtime PASS 또는 recovered로 표시하지 않는다.
