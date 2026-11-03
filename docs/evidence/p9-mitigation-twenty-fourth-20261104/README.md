# 제24차 P9-W2 — CLOSED/invalid / owned cleanup 완료

**P9 acceptance 미충족. Calibration2·freeze·measured C0–C3는 시작하지 않았다.**
[단일 Campaign24 승인](https://github.com/imcherry5778-labs/github-capacity-cascade-platform/issues/47#issuecomment-6612271939)의 paid source는
`d1ed52b8ba14d77345df5b3f19ae8a599421e516`이다. [독립 source gate](https://github.com/imcherry5778-labs/github-capacity-cascade-platform/pull/49#pullrequestreview-5757493662)와
[exact-source CI41683426951](https://github.com/imcherry5778-labs/github-capacity-cascade-platform/actions/runs/41683426951)의4 SUCCESS·실제 FULL local runtime을 확인했다.
Paid 실행 중 source는 바꾸지 않았다. 아래의 Pending imageID 교정은 **cloud cleanup/parent exit 뒤 cost-free future candidate**이며 Azure에서 실행하지 않았다.

| 실행 | 실제 소비·결과 |
| --- | --- |
| normal / public initialize / healthy journey | 각1, retry0, 실제 PASS |
| 첫 C3 calibration | 1, process exit1, INVALID |
| calibration2 / freeze / measured C0–C3 | 미시도 / 없음 / 각0 |
| KEDA SA apply/restore action | 1/1; 실제 Pod restart0/0 |

원본 KEDA template에 WI label이 이미 있어 동일 template patch가 rollout을 만들지 않았다. 기존 projected token과
[2.19의 explicit identity override](https://keda.sh/docs/2.19/authentication-providers/azure-ad-workload-identity/)를 사용했고,
실제 TriggerAuthentication identityId·FIC/AMW role binding, Ready2·usable External metric·HPA exact owner와 healthy3/fault3 joint snapshots를 확인했다.
초기 `restart_count` 필드는 operator intent/conditional counter였으며 `KEDA-action-count-correction-final.json`에 실제 restart0/0을 보정했다. 소비 action은 reset하지 않았다.
Owned image digest는 `sha256:8fab3d49d373fec107bd3110d289c169116b8cac5a290b9006e2454787820c81`이며 로컬 build descriptor와 같았다.
Docker29의 inspect ID/manifest digest를 config digest로 오인했던 operator check는 publish된 **같은 manifest**의 실제 descriptor 비교로 교정했다.

## 실제 validity blocker

- **Independent native HPA Warning:** demand+220.098초에 `FailedGetExternalMetric`/`FailedComputeMetricsReplicas`가 발생했다.
  새 UID의 joint initialization 이후이므로 startup 예외가 아니다. 보존된 completed snapshot20개의 guard HPA는 positive였지만,
  그 사실로 snapshot 사이의 실제 Warning을 지우지 않는다. 해당 Warning의 scaler evaluation epoch/원인은 UNKNOWN이다.
- **AMW canonical guard:** demand+368.703초 monitor가 `validation_failed`로 중단했다. 보존된5개 query response로 실패 signal을 재구성한
  digest가 원래 `signal_evaluation.signal_sha256`와 일치했다. 같은 collector evaluation에서 rate/fresh-rate/inventory/up counts는 모두2,
  up_min1, raw_max_age20.512초, up_max_age35.512초였으나 **kube_pod_info inventory_max_age61.512초 > 원래60초**였다.
  Canonical guarded result는 `[]`였고 exact lifecycle replay도 `empty/invalid guarded scale query`로 거부한다. 이미 초기화된 UID의
  non-startup no-data를0 또는 성공으로 만들지 않았다. 이 later AMW 관측을 earlier HPA Warning의 인과 proof로 합치지 않는다.
- **별도 saved-validator 결함:** 신규 Pending Pod의 app/istio-proxy `imageID=""`가 Ready의 실제 ID로 채워졌는데 원래 predicate는 이를
  `new Pod runtime image drift`로 거부했다. Cost-free 교정은 **이 실제 Pending unknown만** 보존하고 first nonempty ID부터 변경·재누락을 계속 거부한다.
  원래90초 lifecycle, Ready config/image, 기존 UID, HPA/AMW/resource·SLO guard는 유지했다. Candidate로 Warning 이전13개 completed snapshots의
  component replay가 통과해도 전체 retained guard는 non-startup Warning으로 실패하고 original raw의 full validator는 `failed/incomplete run`이다.
  Campaign24는 여전히 INVALID다.

## 유효 run으로 승격하지 않는 부분 관측

Observed Ready→full HPA-positive/AMW/resource joint는 **95.724초**였다. 그 joint 뒤 별도 reference와 후속 snapshot 사이에
두 UID counter가 모두 증가한 시점은 demand+192.899초로 mitigation240초 전이었다.

In-process ring lifetime2913 rows, baseline30, delta **2883 = native check frontend stot delta = ingress/target/server/backend path accounting**이다.
Path error0, ring dropped0,400/CR0이며 status filter·-1→0·row 합성을 하지 않았다. Global `DroppedLogs` 진단은63이었다.
Ring 완전성과 stdio loss 위험을 지지하지만 과거 Campaign23의 각103개 row loss hop을 소급 확정하지 않는다.
실제 snapshot max19.712초<30초, ring capture max0.759초<15초였다. HAProxy actual preflight cgroup82.75MiB/256MiB,
retained PodMetrics memory max83.01MiB, 관측한 OOM/restart0이다. Post-load cgroup peak는 삭제 전 별도 수집하지 않았다.
로컬32667-row proof와 이번 부분 Azure 관측을 full six-run Azure proof로 합치지 않는다.

Scheduled2100, issued1850, **unissued250**, attempts2855다. Monitor 중단으로 남은 arrival을 명시적으로 취소했으며 이를 분모에서 지우지 않았다.
관측한 recovery Issue command644개 중466개가0.2초를 초과했다. Scheduler dispatch max0.0552초,
worker queue max1.4694초, total driver max1.4976초다. **Full180초 recovery는 완료되지 않았고 valid negative recovery 결과도 아니다.**
Full cloud confounder review는 INVALID close 뒤 수행하지 않았으며 competing_bottleneck=false 또는 recovered를 주장하지 않는다.

## 원복·계수·다음 gate

CUSTOM exact UID 제거, shared mesh CM UID/data 원복, namespace 부재, 원본 KEDA SA UID/annotations/template·Ready2,
같은-parent stable Argo/Deployment/Pod·PVC/PV 및 named admin/DB Secret UID·값 비교를 확인했다.
Original Owner2/34 ARM IDs/fixed2 nodes, owned image exact digest/tag·local tags와 임시 AKS/AMW role·FIC/UAMI 부재,
original stable images/restarts·Ready/no-pressure nodes, native admin auth/TLS를 확인했다. Forward는 소유 TERM/wait, parent exit0이었다.

Initial cleanup handler는 fixture EditUser 입력 pair 누락으로 error1을 남겼고 targeted PATCH도422였다. 그 negative를 보존한 뒤
native `source_id=0`와 login_name을 함께 제공해 정상화했다. 이미 삭제한 normal PAT는 다시 DELETE하지 않았다.
두 PAT의 reuse401/list0·fixture login401과 DB record 보존을 확인했다. Normal PAT의 초기 DELETE는 handler가204/404를 허용했으며
정확한 status가 저장되지 않았다. Raw의 `204 in initial handler` 문자열은 별도 HTTP proof가 아닌 operator 표현이었다.
그 한계를 [execution](execution.json)에 보정했으며 healthy PAT DELETE204는 실제 저장됐다. Final cleanup은 complete/errors=[]다.

누적 **campaign24 / initialize21 / healthy12 / started-invalid calibration9 / measured 각0 / KEDA apply·restore actions9/9**이다.
Unused calibration/measured 권한은 close와 함께 소멸했다. Billing GET0, variable planning estimate5 USD/projection310.3567 USD,
actual/shared 비용 UNKNOWN이며 새 숫자 cap·resource/permission 확장·retention 연장·전체 teardown·merge/P10은 없다.
Environment11/5 10:30 KST, Foundation/Bootstrap11/6 00:33 KST를 유지했다.

**REVALIDATE:** raw proxy counter freshness와 kube_pod_info metadata의 실제 timestamp cadence/ingestion 경계를 별도로 판정해야 한다.
이번 관측만으로 configured scrape interval이나 native +220초 scaler 원인을 확정하지 않는다. 60초 guard 완화·새 임의 cap·예외는 구현하지 않았다.
Future source의 독립 exact-head review와 이 contract 경계 판단 전에는 새 paid 실행을 해서는 안 된다. **Campaign25 승인은 없다.**

[comparison](comparison.json), [validation](validation.json), [raw index](raw-index.json), [sanitized archive](raw-evidence.tar.gz)를 함께 본다.
공개67개 file의 size/SHA256·roundtrip과 known credential/JWT/subscription/private-path scan을 확인했다. 원본 credential-free raw는 local append-only로 보존한다.
공개본은 identifier pseudonym만 적용하고 original hash를 재서명하지 않았다. Full original identity/render/plan binding과 원래 signal digest를 공개본만으로
재구성할 수 없다. Private 원본에서 확인한 exact failed-signal hash와 공개 numeric guard/strict-negative replay의 검증 범위를 구분한다.
Cost-free P9 142 tests(139 PASS/3 SKIP), P8 38 PASS, focused8 PASS이며 HAP config/capture 변경이 없어 기존 pinned Docker proof를 재사용했다.
최종 evidence/candidate HEAD와 exact-head CI는 PR #49 결과 comment에 연결한다.
