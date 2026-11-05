# 제23차 P9-W2 — INVALID calibration / P9-owned cleanup 확인

**P9 acceptance 미충족. Campaign23은 CLOSED/invalid이며 freeze·measured C0–C3는 없다.**
[단일 campaign 승인](https://github.com/imcherry5778-labs/github-capacity-cascade-platform/issues/47#issuecomment-6604629172)의 exact source
`076bc8a3dbd09e8192057e19df8b6cc5cb55274d`를 사용했다. PR #48 HEAD `504ae8138b2b32e96fec4df7f0b66e5d9169bf63`과
source tree `fccecf0591e67e524d47ebff465de3014135cb48`가 같아 [검토된 full CI](https://github.com/imcherry5778-labs/github-capacity-cascade-platform/actions/runs/41635668371)를 재사용했다.
실행 중 repository implementation source는 변경하지 않았다. 이 evidence PR의 HEAD와 paid source SHA를 구분한다.

## 실행과 실제 관측

| 구분 | Campaign23 실제 소비 |
| --- | --- |
| normal / public initialize / healthy journey | 각1, retry0, 실제 PASS |
| C3 calibration | 1회, process exit0/run_end complete이나 saved INVALID |
| 두 번째 calibration / freeze / measured C0–C3 | 미시도 / 없음 / 각0 |
| KEDA apply / restore restart | 1 / 1 |

현재 native Entra actor/subscription, 원래 Owner2, 승인된4RG/34 ARM IDs, fixed2 nodes, quota와8045초 whole reserve를 확인했다.
Subscription에 별도 범위의 RG2개가 보였으나 승인된4RG만 자원 비교·mutation/cleanup 대상으로 삼았다.
Linux amd64 image를 exact source revision label로1회 publish했고 registry digest가 로컬 build descriptor와 같았다.
Owned digest는 `sha256:156c3b9ee8ca31aea0929ca01584db65b92002fc2214c6c73145e2d3fe599a11`이다.
AKS1.36.4 / managed Istio `asm-1-30` / KEDA2.19.0-25 / pinned HAProxy3.4.6을 관측했으며 actual image IDs는 archive의 `native-toolchain.json`에 있다.

C0 initialize는 기존 `min(60s,2×validated window)` CPU gate, warning/ownership, 동일 healthy journey의 실제 accounting·AMW/resource 검증을 통과했다.
전용 IAM/WI 연결 뒤 KEDA 실제 주입·Ready2, usable External metric·ScalingActive=True·exact owner와 healthy3/fault3 full joint snapshots를 확인한 뒤 C3 calibration을 시작했다.
C3 기존 UID의 resource freshness는 source의 `2×window`이며 AMW60초 및 C0 초기화 cap과 다르다. Operator가 추가했던60초 cap만 source와 맞췄고, repository gate를 변경하지 않았다.

CLI 전체479.147초≤600초, snapshot24개(max19.264초≤30), collector query118개, direct sentinel378개 전부 semantic success였다.
Scheduled/issued2100, unissued0, attempts3100, failed logical1045다. 새 UID의 **observed Ready→joint94.184초**였고,
그 뒤 별도 reference와 후속 snapshot 사이에 두 UID counter가 모두 증가한 관측은 demand+189.216초로 mitigation240초 전이었다.
이 부분 관측은 invalid calibration을 measured 성과로 승격하지 않는다.

## 두 validity blocker와 별도 recovery 결과

1. **Controller — `controller metric/status failure`.** Snapshot demand+73.831–91.997초에서 guard HPA GET은+78.763–79.176초,
   뒤의 AMW query는+90.801–90.938초였다. HPA는 False/FailedGetExternalMetric, AMW는 observed, resource는 initializing-new-pod다.
   Thread-local marker의 hash가 바로 그 guard status와 모든24 snapshot에서 일치했다. 약11.762초의 별도 관측 간격을 확인했으며,
   later AMW 또는 이후 HPA True를 earlier controller 성공으로 합치지 않았다. HPA message는 generic metric-values error라 actual scaler evaluation epoch/원인은 UNKNOWN이다.
   New UID startup과의 시간적 관련성은 있으나 lifecycle transient의 causal proof나 기존 예외 확대 근거로 확정하지 않는다.
2. **Accounting — `check/ingress/HAProxy path error`.** 새 unlogged readiness 아래400/CR/Tw=-1은0건, 관측한 queue_ms는 모두0이다.
   반면 HAProxy log delta3036 대 ingress·target/server/BACKEND3139로 **103건이 부족**하다. Lifetime log3065개는
   pid8/log_counter0–3167 중103개 gap, duplicate0이었다. Counter의 중간 결손은 마지막 read 시차만으로 설명되지 않는다.
   HAProxy emission→container log→collection 중 정확한 loss hop은 UNKNOWN이다. 모든 row를 보존했고 status filter, -1→0, residual 제거/합성을 하지 않았다.
   이전 Campaign22의44건·29건 기록도 수정하지 않았다.
3. **Recovery — 별도 negative.** Optimistic observation coverage를 넣어 command/driver predicate만 분리해도 qualifying window0 / not recovered다.
   Recovery Issue command884개 중639개가0.2초 초과(p50 0.310초, p95 1.209초)였다. Scheduled→submitted max0.0595초,
   submitted→issued max1.6039초, total driver max1.6248초로 이번 driver lag의 큰 부분이 worker queue에서 관측됐다.
   정확한 server/DB/host 인과와 full cloud confounder review는 미완료다. SLO를 완화하지 않았다.
   다른 validity gate가 통과한 run의 미회복은 valid negative일 수 있지만, 이번 run은 위 controller/accounting 때문에 invalid다.

다음에는 **HPA startup의 독립 clock/원인 판정 계약**과 **complete HAProxy log capture 경로**를 먼저 교정·검토해야 한다.
그 판단은 새 source/독립 gate가 필요하며 이번 exact-source 승인 안에서 구현하거나 재실행하지 않았다.
추측 calibration2, campaign24, P10은 수행하지 않았다. 사용하지 않은 calibration1회와 measured 권한은 close와 함께 소멸했다.

## 원복과 evidence 경계

CUSTOM exact UID 제거/NotFound, shared mesh CM UID/data 원본 복원, namespace 제거, KEDA 원본 SA UID/annotations/template·Ready2를 확인했다.
PAT2개 exact revoke204/reuse401/list0/login401, DB records 보존, stable Argo/Deployment/Pod/CSI producer/SPC/PVC/PV full specs·UID/images/restarts 및
named admin/DB Secret UID·값의 같은-parent 비교가 일치했다. Initial/final native integrity는 각각4개 통과했다.
Forward는 소유 handle에서 의도한 TERM/wait(-15), parent exit0이었다.

최초 cleanup handler는 성공한 delete의 빈 JSON 응답과 lowercase `manifest unknown`을 잘못 처리하여3개 error를 남겼다.
그 negative `cleanup-summary.json`을 보존하고, 이미 성공한 단계·restart·journey를 반복하지 않은 targeted cleanup으로
AMW/AKS 임시 role 부재, exact UAMI/FIC 부재, owned image manifest 부재·local tag 제거, 원래 Owner2/34 IDs/fixed2 nodes를 실제 확인했다.
최종 `cleanup-recovery.json`은 complete/errors=[]다. 유료 source를 바꾸거나 normal/public initialize/calibration을 재실행하지 않았다.
CLI argument/quantity normalization·partial setup·DNS override·empty204 처리 같은 operator 교정도 raw에 남겼다.

누적 **campaign23 / initialize20 / healthy11 / started-invalid calibration8 / measured 각0 / KEDA8/8**이다.
Billing GET0, bounded variable estimate5 USD와 planning projection305.3567 USD를 기록했으며 actual/shared 비용·잔액은 UNKNOWN이다.
새 숫자 cap·resource/permission scope·기간을 만들지 않았다. Environment2026-11-05 10:30 KST / Foundation·Bootstrap11월6일00:33 KST를 유지했다.
자동 연장·전체 teardown·merge는 하지 않았다.

[execution](execution.json), [comparison](comparison.json), [validation](validation.json), [raw index](raw-index.json), [sanitized archive](raw-evidence.tar.gz)를 함께 본다.
원본 raw는 credential-free/append-only로 로컬 보존한다. 공개57개 file의 path/size/SHA256 roundtrip과 known credential/JWT/subscription/private-path scan을 확인했다.
Original/public의 unchanged source predicate replay는 controller/accounting negative, demand와 optimistic recovery 결과가 같다.
Identifier redaction 때문에 원래 identity/render/plan binding 전체를 공개본만으로 재구성할 수 없으며 original hash를 재서명하지 않았다.
Full cloud confounder review와 run-valid/recovered/P9 완료 claim은 없다. Final evidence HEAD/CI는 PR 결과 comment에 연결한다.
