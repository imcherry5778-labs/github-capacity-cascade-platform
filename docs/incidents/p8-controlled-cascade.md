# P8 controlled cascade — 초기 incident record

상태: **Azure 측정·원복 완료, 독립 exact-head review 대기**. 분류: `LAB_IMPLEMENTATION`.
Historical GitHub incident topology의 복제 주장이 아니다. P9 mitigation/recovery와 P10 isolation은 수행하지 않았다.

## 영향과 판정

Mandatory shared check의 **실제 ext-authz-sim inbound Envoy active-request 포화**가
verified HTTPS/native developer PAT를 사용하는 private Issue read와 HTTPS Git read를 실패시켰다.
같은 source/configuration/replica/demand에서 client max_attempts만 1→2로 바꾸자 Issue attempts는
**1.918배**, 전체 check dispatch는 **1.874배**가 됐다. 추가 부하에 비해 Issue 성공은 47→49에 그쳤다.
정상 app CPU HPA가 proxy-side pressure를 반영하지 못한 관측을 지지한다.
이는 25개 반복 burst의 한 paired observation이며 지속 포화·통계적 일반화·회복 효과를 주장하지 않는다.

| 항목 | No retry (`no-retry-02`) | Bounded retry (`retry`) |
| --- | ---: | ---: |
| UTC window (2026-10-28) | 19:36:58.900–19:39:18.014 | 19:39:58.067–19:42:17.267 |
| Logical Issue operations | 600 | 600 |
| Issue attempts | 600 | 1,151 |
| Logical Issue success / failure | 47 / 553 | 49 / 551 |
| HTTP200 / HTTP403 attempts | 47 / 553 | 49 / 1,102 |
| Issue command latency > P7 0.2s | 59 / 600 | 49 / 1,151 |
| Supplemental HTTPS Git reads / failed | 25 / 22 | 25 / 24 |
| Dispatched checks | 628 | 1,177 |
| Admitted checks | 53 | 51 |
| Active-request rejections | 575 | 1,126 |
| Sampled active peak / pending overflow | 2 / 0 | 2 / 0 |
| Direct authenticated sentinel success | 415 / 415 | 421 / 421 |
| HPA app CPU / replicas | 2% / 1 | 2% / 1 |
| Actual metric timestamp update span | 124s | 116s |

P7 [고정 SLO](../evidence/p7-operations-20261028/initial-slo.json)를 변경하지 않았다.
Issue latency는 같은 단일 curl-command timing이다. 빠른 HTTP403도 실패이며 latency 수치만으로 정상으로 판단하지 않는다.
Git은 `ls-remote refs/heads/main`의 expected SHA 검사로, P7 clone/fetch latency SLI와 합치지 않는다.
Git 한 attempt가 여러 HTTP check를 만들 수 있다. 전체 checks에서 Issue attempts를 뺀 Git check 추정치는 28/26이다.
Logical operation, attempt, dispatch, admission과 rejection을 서로 같은 단위로 취급하지 않는다.

## 동결과 실제 failure mechanism

Execution source: **`bc0a4def4e6b43cf1a748b045869218214730df9`**.
승인 HEAD `033a53fba2a5e4f6196fa5c60654c6648f12f5b5`의 CI 성공을 확인한 뒤,
같은 승인 범위 안의 최소 Azure adapter 수정을 직접 회귀검증하고 실행했다.
App image는 승인 HEAD에서 build한 동일 bytes/digest이며 이후 app source 변경은 없다.
Stable Argo revision은 `2f63d283ebba12aaed8705732f1206d71ddc33db`로 유지했다.

Calibration05와 전체 confounder review 뒤 `frozen-02.json`으로 동결했다.
Fingerprint: `0d023ac11b3f4b530a853995fe9af827fe475ee0a083db58aaffc8521c696019`.
maxRequests2 / hold1000ms / 25 waves×24 Issue operations / concurrency12 / wave 간격5s / Git25회,
actual target replica1 및 Pod UID, source, image, config, transport가 두 run에서 같다.
실험 변경 변수는 실패한 idempotent Issue read에 대한 client max_attempts 1→2뿐이다.
Writes와 fixture 준비에는 retry를 적용하지 않았다.

Managed Istio `asm-1-30`, Envoy `1.38.6/Modified`에서 실제 mapping은
`inbound|8080||` ORIGINAL_DST cluster와 `inbound|8080||;` stat prefix였다.
Listener destination port8080의 route binding까지 확인했으며 P7 Forgejo3000/Local mapping을 가정하지 않았다.
`upstream_rq_active_overflow` 증가가 target의 HTTP503 overflow access record,
HAProxy check dispatch, ingress `ext_authz_error`, developer HTTP403과 같은 run에서 일치했다.
각 run은 **dispatch = admission + active rejection**이고 pending overflow는 0이다.

CUSTOM policy의 selector/provider와 `forgejo.imcherry5778.xyz`, `forgejo.imcherry5778.xyz:443`
exact hostname scope를 live policy 및 각 effective gateway RBAC `:authority` matcher에서 확인했다.
Stable Gateway/VirtualService/Argo source는 변경하지 않았다. Native auth, TLS verification과 fail-closed를 유지했다.
Ingress Forgejo route 및 HAProxy retries는 0이다. Target managed inbound route의 기본
`reset-before-request` / num_retries2는 관측·보존했으며 독립적으로 세지 않았다.
모든 proxy retry를 제거했다거나 client retry만이 유일한 내부 retry라고 주장하지 않는다.

## Confounder guard와 HPA

No-retry/retry 각각의 같은 window에서 다음을 함께 확인했다.

| Signal | No retry | Bounded retry | 해석 |
| --- | ---: | ---: | --- |
| Forgejo app CPU peak | 77.15m | 77.45m | CPU throttle delta0, readiness/restarts/UID 유지 |
| Forgejo sidecar CPU peak | 12.34m | 11.70m | 기존 limit2CPU 대비 여유, memory 약42Mi |
| Target app / proxy CPU peak | 0.568m / 41.33m | 0.531m / 42.06m | app CPU와 proxy capacity pressure 구분 |
| PostgreSQL CPU max | 3.95% | 7.99% | minute Average/Maximum bins, 같은 query window |
| SQL connections max / usable | 19 / 844 | 18 / 844 | ARM active_connections도 관측 |
| SQL command latency max | 0.964s | 0.942s | kubectl/exec 포함, 내부 query percentile 아님 |
| Storage used / free | 13.224% / 약29GB | 동일 | aggregate IOPS max4 / 6, 상세 IO 지연 결과 별도 보존 |
| Node CPU peak (두 node 중 최대) | 382m | 391m | 각 allocatable3860m, pressure/scheduling warning 없음 |
| 추가 target의 최소 CPU 여유 | 1.346 cores | 1.346 cores | memory/allocatable/Pod scheduling inventory도 보존 |
| HAProxy queue/error/retry | queue0, 관련 counter delta0 | 동일 | 경쟁 HAProxy queue/transport 병목 관측 없음 |

HPA는 app requests50m, ContainerResource(app,cpu), target60%, min1/max2다.
AbleToScale/ScalingActive 정상, 상한 cap/metric error/scheduling 문제 없이 replica1이었다.
실제 metrics API 갱신 timestamp가 각각124/116초 span을 포함한다.
최대 metric age78.9/76.2초는 보고된 CPU window 두 개 이내이며 정상으로 임의 0 처리하지 않았다.
AKS controller flag 자체는 읽지 않았고 기본15초 sync를 실제 설정값이라고 주장하지 않는다.

Forgejo/sidecar의 기존 Managed Prometheus scrape·CPU·memory와 Log Analytics log도 같은 window에 관측됐다.
상기 범위에서 경쟁 bottleneck은 관측되지 않았다. 모든 잠재 병목이 배제됐다는 뜻은 아니다.
Direct sentinel은 Pod loopback port-forward의 native-auth HTTP이며 public measured traffic은 HTTPS다.
Direct command max0.423s/0.172s는 별도 transport 표본이다. P7 HTTPS latency SLO 통과라고 합치지 않는다.
Stable managed proxy에서 cgroup file은 제공되지 않았다. CPU/memory/capacity/readiness/sentinel을 확인했으며
sidecar throttling0으로 추정하지 않는다. Full tracing/request-level rejected check ID linkage는 미검증이다.

## Negative evidence와 최소 수정

Raw는 append-only로 유지했다. 자세한 파일은 [execution evidence index](../evidence/p8-controlled-cascade-20261029/README.md)에 있다.

- HAProxy terminal LF 누락 startup 실패, actual Istio validation init resource, Azure CLI AKS 조회 인자,
  ORIGINAL_DST listener mapping, bootstrap mask endpoint를 실제 관측에 맞춰 최소 보정했다.
- Calibration01: fixed60s metric age 조건과 historical/combined ingress log delta 문제로 invalid.
- Calibration02/03: 각각 325:323 / 627:626 ingress-to-dispatch 불일치로 invalid.
  10s idle/reused connection 영향은 원인 후보이며 확정하지 않았다.
- Candidate를 25×5s 반복 burst로 바꾸고 HAProxy `option httpclose`를 적용한 calibration04는 valid였다.
- 첫 no-retry는 HTTP628=53+575가 맞았지만 별도 unmatched TLS7개를 HTTP denominator에 합친 validator가 거부했다.
  Policy를 안전 제거했다. 정확한 status0/`filter_chain_not_found`/upstream없음 기록만 HTTP와 구분하는
  회귀를 추가했다. Raw TLS 기록을 버리지 않고 unknown status0·측정 transport 오류는 계속 거부한다.
- Policy UID와 source가 바뀌었으므로 이전 freeze로 비교하지 않았다. Calibration05에서 재검토·재동결했고
  마지막 no-retry-02/retry만 최종 pair로 채택했다. 선택된 pair에는 해당 non-HTTP TLS record가 0개였다.
- 초기 상세 PostgreSQL IO no-data는 그대로 보존했다. Ingestion 지연은 같은 window 추가 조회로 처리하며
  이 이유로 workload를 반복하지 않았다.

## 원복·소유 cleanup·비용

CUSTOM policy 우선 제거 → 기존 shared ConfigMap UID/data 복구 → P8 namespace/HPA/fixtures/DB Secret 제거 순으로 원복했다.
Gateway effective config의 P8 filter/policy 부재와 원래 Deployment/Service/PVC/Gateway/VirtualService UID/spec,
두 stable Secret 값 및 Argo Synced/Healthy/revision 유지를 확인했다.
기존 두 fixture의 정상 HTTPS native-auth/private Git clone/fetch/PR/Issue read가 각각5 checks 통과했다.
이 확인은 P9 recovery drill이 아니다.

Fixture PAT2개는 exact token ID revoke 후 원래 Authorization token의 HTTP401과 token 목록0개를 확인했다.
두 fixture 계정은 login 차단했고 repo/Issue/PR 기록은 승인대로 보존한다.
소유 ACR manifest/tag, 로컬 output image, 임시 AKS Cluster Admin assignment와 port-forward를 제거했다.
기존 Owner assignment 두 개, administrator version2와 stable Secret은 보존했다.
실제3 Pod의 보수적 합계는 CPU limit900m/memory1024Mi, native/init 포함4 Pod 예상 최대는1450m/1664Mi로 승인 상한 이내였다.
새 node/server/Disk/PVC는 없으며 기존 node2·10GiB Disk/PVC1·32GiB PG를 유지했다.
보호된 credential/kubeconfig 사본 정리와 archive 검증 결과는 evidence의 finalization record에 연결한다.

Final ActualCost query는 성공했고 기존 두 RG의 2026-10-28 합계 **KRW16,015.5402320629**를 반환했다.
이는 기존 환경 공유비이며 P8 증가분을 분리할 수 없다. P8 actual 증가분은 **unknown**이고 USD10 이하 실측 claim은 하지 않는다.
계획 USD2 / 추가 검토 USD10은 유지하며 billing hard cap이 아니다.
Environment 2026-10-30 10:30 KST, Foundation/Bootstrap 2026-10-31 00:33 KST 보존 기한을 유지한다.
자동 연장·전체 teardown·DNS 변경은 수행하지 않았다.
