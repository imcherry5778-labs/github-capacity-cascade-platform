# P9 제22차 — 실제 initialize 성공 / C3 calibration invalid / CLOSED

실행 source는 `ab59fda4d9e0f0ed837b77794b6d03a0db07d832`다. [제22차 단일 승인](https://github.com/imcherry5778-labs/github-capacity-cascade-platform/pull/41#issuecomment-6598614345)과 [exact-source 독립 review](https://github.com/imcherry5778-labs/github-capacity-cascade-platform/pull/41#pullrequestreview-5748871506)에 따라 같은 Mac/branch/PR #41에서 실행했다. Source 변경은 없다. **Campaign22 CLOSED/invalid, P9 acceptance 미충족**이다.

Normal·healthy journey는 각각9 operations/9 attempts valid/success, public initialize1/retry0이 실제 통과했다. CPU poll10·telemetry poll4·Prometheus17/25다. 마지막 CPU age24.159742초/window58.315초와 같은 poll의 observed AMW 이후 약0.901초에 native-path/accounting/final freshness 검증까지 완료했다. Last sample 자체는 old30초에도 들어오므로 이 실행만으로 window-aware 교정의 인과 효과를 분리해 증명하지 않는다. 다른 poll의 ready/observed를 이어 붙이지 않았다.

Actual KEDA2.19.0-25·전용 workload identity 주입/Ready2·ScaledObject Ready/HPA ScalingActive와 external current metric, exact query/TLS/single-owner, 실제 fault 수렴 뒤 full joint snapshots3개를 통과했다. KEDA apply restart1회를 소비했다.

## 실제 calibration과 blocker

C3 calibration1회가240초 mitigation+180초 continuing-demand recovery와 마지막 snapshot까지 process exit0/run_end로 완료됐다. Runtime 약443.889초, snapshot45개(max17.726초≤30), collector query220개(max1.399초≤5), direct sentinel377개 전부 semantic success다. Scheduled/issued2100, unissued0, client attempts3102, failed logical1047, max driver lag1.501207초다. 이 수치는 calibration 관측이며 measured 성과가 아니다.

- 새 UID의 observed Ready→joint resource/AMW snapshot 종료는112.581초였다. 같은 UID의 fresh·advancing resource와 AMW가 함께 관측됐고, 그 뒤 별도 reference와 후속 snapshot 사이에 **두 UID counter 모두 증가**했다. Traffic proof는 mitigation240초 종료 전에 존재한다. Source의150초 resource/75초 AMW/60초 freshness는 완화하지 않았다.
- **첫 saved validator 실패는 `controller metric/status failure`**다. Demand+74.881초와+84.105초에 시작한 snapshot2개에서 앞서 수집된 HPA는 `ScalingActive=False/FailedGetExternalMetric`, 뒤의 AMW는 `observed`, resource는 `initializing-new-pod`였다. Current source가 HPA 예외를 AMW `warming-new-pod`에만 묶으므로 이 경계를 거부한다. HPA/collector의 별도 evaluation·ingestion 상태가 같았다고 주장하지 않는다. Live process 완료를 saved valid로 바꾸지 않았다.
- 별도 source `path_accounting` replay도 **`competing HAProxy queue`**에서 실패한다. HAProxy3112개 row의 Tw=0,44개는 **status400/CR·Tw=-1**, sampled server/backend qmax는0이다. Source에 HAProxy8080 TCP readiness probe가 있고443.889초에44개라는 관측은 probe 기원과 일치하지만, log에 peer/시간/correlation이 없어 각 row의 기원은 미확정이다. 모든400/CR을 필터하거나 -1을0으로 합성하지 않는다. 44개를 제외해도 나머지 HAProxy log3112개와 ingress delta3141개가 달라, 그29개 차이의 원인도 unknown이다. Probe 필터 하나로 accounting이 고쳐진다고 주장하지 않는다.
- 원래 source의 recovery 계산을 따로 replay하면 **qualifying window0 / not recovered**다. Recovery driver lag max1.501207초>0.2초, Issue attempt674개가0.2초를 넘었다. Node/DB/Forgejo/host 중 정확한 병목 인과와 전체 cloud confounder review는 미완료다. Threshold/SLO/driver bound를 바꾸거나 성공으로 만들지 않는다.

같은-source operator 교정으로 위 saved/controller·accounting·SLO 경계를 해결할 근거가 없어 두 번째 calibration을 추측 반복하지 않았다. 남은1회는 campaign close와 함께 소멸했다. **Freeze 없음, C0/C1/C2/C3 measured 각0**, comparison/hypothesis 없음이다. Source-changing paid recovery는 별도 exact-source review/사용자 결정 전 수행하지 않는다.

## 원복·검증 경계

CUSTOM exact UID 제거, shared mesh CM UID/data 복원, namespace/controllers/Secret 제거, KEDA 원본 SA UID/annotation/template 복원 및 Ready2(restore restart1), 전용 AMW role/UAMI/FIC와 임시 AKS role 정리, owned image index+children3개 각 MANIFEST_UNKNOWN·local tag 제거, forwarding TERM/wait(-15)와 parent exit0을 확인했다. 원래 Owner2개와4RG/34 resource ID·고정2-node를 보존했다. Stable Argo/spec/Pod/Deployment/CSI/PVC/PV는 same-parent full 비교와 공개 전후 digest가 같다. Named admin/DB Secret UID/value 비교도 같으며 값은 공개하지 않는다. Initial/final native integrity4개씩 pass, paths는 기존 source-baseline 진단을 보존했다. Fixture/PAT2개는 exact revoke204/reuse401/list0/login401; 계정·저장소 DB records는 보존하고 별도 post-cleanup SQL replay는 하지 않았다. Cleanup errors=[]이다.

초기 operator 단계의 uppercase checkpoint·Azure CLI dotted-tag 파싱·OIDC `issuerUrl` 필드·stand-alone healthy snapshot baseline 오류를 같은 source와 미소비 stage에서 교정했다. Initialize·healthy·KEDA restart·calibration은 재호출하지 않았다. 잘못된 preliminary snapshot은 raw에 보존했다.

누적 **campaign22 / initialize19 / healthy10 / started-invalid calibration7 / measured 각0 / KEDA7/7**. Campaign21과 이전 negative/source/archive는 수정하지 않았다. Cost GET0, 기존 retention/lag/cleanup projection295.3567+이번 bounded variable5=planning300.3567 USD를 기록했으며 actual/shared 비용과 잔액은 unknown이다. USD290을 자동 NO-GO로 쓰거나 새 숫자 cap/자원/기간을 만들지 않았다. Environment `2026-11-05T01:30:00Z`와 Foundation/Bootstrap `2026-11-05T15:33:00Z`를 유지했다. 추가 campaign23·merge/P10·전체 teardown은 없다.

초기 과거 identity 파일 열람에서 subscription 식별자가 tool 출력에 포함된 실수가 있었다. 이후 출력과 이 공개 evidence는 식별자를 마스킹했으며 이미 발생한 transcript 출력 삭제를 주장하지 않는다. 그 열람에서 authentication token/Secret 값은 출력하지 않았다. 별도 credential rotation·전역 audit를 만들지 않았다.

[execution](execution.json), [comparison](comparison.json), [validation](validation.json), [raw index](raw-index.json), [sanitized raw archive](raw-evidence.tar.gz)를 함께 본다. 원본 raw는 append-only다. 공개본은 original render/configuration hash를 다시 서명하지 않으며, 원본 full validator의 negative와 공개본의 기존 common_guards/path_accounting/demand·signal-clock/envelope predicate replay가 동일함을 검증했다. Sanitized archive의 path/size/SHA256과 credential/JWT/private-path scan을 확인했다. Source tests/CI는 exact ab59 review를 재사용하고 evidence HEAD/CI는 #41 결과 comment에 연결한다.
