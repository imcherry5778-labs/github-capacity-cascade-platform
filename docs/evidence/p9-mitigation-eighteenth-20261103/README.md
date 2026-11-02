# P9 제18차 — initialize 성공 / C3 calibration invalid / owned cleanup 완료

실행 source는 `4777ae414c94c22a6226b27fe57a9bffcad8e5e3`, current main 계약은 `d9977cc9046485bb7b47849297ec9769a3629223`다.
[사용자 실행 승인](https://github.com/imcherry5778-labs/github-capacity-cascade-platform/pull/41#issuecomment-6580372657)과
[독립 exact-head review](https://github.com/imcherry5778-labs/github-capacity-cascade-platform/pull/41#pullrequestreview-5738448304)에 결합했다.
같은 wolffish/branch/Draft #41을 유지했고 실행 중 source를 변경하지 않았다.
2026-11-03 KST(11월2일 UTC) 단일 campaign은 CLOSED다. **P9 acceptance는 미충족이며 freeze·C0–C3 measured·유효 recovery/comparison은 없다.**

## 실제 결과

- Normal/healthy journey는 각각 warmup9 operations/9 attempts `valid/success`다. Public initialize1·retry0이 성공했다. Initialize의 권한은 `ready_for_keda_authentication=true`, `runtime_preflight_passed=false`까지였다.
- CPU settling7 + telemetry3 = CPU poll10, telemetry query15/최대25다. 마지막 poll CPU age는23.561초였고 native-path/log accounting 뒤의 최종 freshness 검사도 source가 통과했다. Healthy window의 실제 check/target request는29/29다. Timeout/freshness/Warning/UID/query 기준을 완화하지 않았다. 한 번의 성공으로 prior failure의 runtime 원인이나 source 교정의 인과 효과가 확정되지는 않는다.
- 그 뒤 전용 UAMI/FIC·exact AMW Monitoring Data Reader, 기존 KEDA SA와 apply restart1회를 사용했다. 실제 KEDA external metrics API의 generated-HPA selector/ScaledObject UID·metric 응답, 두 managed operator Pod의 identity injection, config/series/DB/resource gate를 확인한 뒤 runtime preflight flag를 부여했다. Operator 자신의 Prometheus query만으로 인증을 주장하지 않았다.
- C3 calibration1이 schedule origin+202.439초에 monitor failure로 중단됐다. 예정1,800 logical operations 중1,025가 발행·완료됐고775는 `not-issued`다. 실제 client attempts는1,793이다. Snapshot12개(최대19.290초), direct sentinel189개는 모두 semantic success였다. 이 수치는 valid measured 분모나 완화 성과가 아니다.
- Source는 이후 arrivals를 중단했다. 예정 fault release 뒤 마지막 snapshot은 origin+221.859초에 두 target의 `hold0/capacity1024` 수렴을 기록했다. Full360초 demand/recovery window를 완료하지 않았으므로 회복 성공으로 세지 않는다. Desired/Ready2·두 UID의 traffic은 raw 관측이며 invalid run의 유효 autoscaling 성과를 주장하지 않는다.

## 실패에서 입증한 것과 남은 gap

실패 직전 네 query는 두 기존 target의 rate/active/timestamp/sample-count를 반환했다. 다섯 번째 **guarded query는 HTTP200 / success / vector / `[]`**였다.
저장된 raw의 cost-free replay에서 성공 snapshot11개와 기존 두 series를 검증한 다음, 같은 source의 `TargetLifecycle.signal`이 정확히 `empty/invalid guarded scale query`로 거부함을 재현했다.
이는 CPU settling 실패나 HTTP/query 오류와 구분된다. 빈 vector를0으로 바꾸지 않았다.

당시 up/inventory/freshness 중 어느 sub-guard가 탈락했는지는 기록되지 않았다. 원래 query의 정확한 server evaluation epoch도 empty result에는 없다.
실패 직전 series의 server epoch로 추정한1초 bracket(원래 query epoch는 미기록)을0.1초 step으로 historical query3개(각≤5초)만 읽었다. 나중 조회의 inventory/up timestamp와 up1은 정상이나, ingestion 뒤의 historical 결과는 **원래 ingestion 상태의 재현이 아니다**.
따라서 특정 sub-guard·scraper/export/cache/ingestion 원인을 단정하지 않는다.

동일 SHA·동일 freshness 안의 원인 교정 근거가 없어 두 번째 calibration을 소진하지 않았다. Healthy/initialize/measured 재호출이나 counter 초기화는 없다.
현재의 최소 기술 gap은 **빈 guarded query 당시의 up·inventory·각 freshness predicate와 query request/response/evaluation clock을 같은 ingestion 상태에서 구분할 관측**이다.
ChatGPT가 기존 budget 안의 최소 관측 변경과 계약 영향을 판단해야 한다. 추가 retry controller나 freshness/timeout 완화는 구현하지 않았다. 새로운 paid campaign/승인안을 자동 생성하지 않는다.

## Owned cleanup와 보존

Owned cleanup은11월2일15:38:06 UTC에 완료됐다. CUSTOM exact UID 제거·shared CM UID/data guarded restore·소유 namespace/Secret/controls 제거, KEDA 원래 SA/template·replicas2/Ready 복귀 후 전용 role/FIC/UAMI 제거, 소유 ACR tag/digest와 local tag 제거를 확인했다.
Final native verify는1회 성공(기존 CLI check5개; 구조화된 operation5개라는 주장은 아님)했다.
Fixture PAT34/35는 각각 DELETE204·재사용401·token list0·login401로 확인했고 DB records는 보존했다.
같은 parent가 forward를 계속 소유했고 의도한 TERM 뒤 wait(-15)로 회수했다. 임시 exact AKS role 제거와 원래 Owner2개 보존을 확인했다.

Stable Argo revision/spec·Pod UID/Deployment·admin/DB Secret·CSI version·PVC/PV UID/spec/Bound·4RG inventory를 비교해 보존했다.
이전 [admin 회전 결과](https://github.com/imcherry5778-labs/github-capacity-cascade-platform/pull/41#issuecomment-6569049379)를 재사용했고, named Secret 목적별 GET4회 외 KV/old credential/transcript read나 추가 회전은 하지 않았다.
공개본 credential/path scan 뒤 같은 parent의 exit0을 확인하고 이번 소유 보호 사본과 다운로드한 임시 도구만 제거했다. Global Azure cache와 무관한 image cache는 보존했다. Global session containment·physical secure erasure·전체 environment zero residual을 주장하지 않는다.

Operator 오류는 source 변경 없이 같은 승인 안에서 교정했다. Journey 전 context 인수/계정 ID와 username 구분, 실제 KEDA replicas2, nullable external-metric labels, fixture block PATCH의 불필요한 `login_name` 제거다.
변경된 parser/payload는 captured-response/fake 검사로 확인했다(총 cost-free operator 검사47개). Initial normal/initialize/measured, 성공한 PAT DELETE/final verify/KEDA restart를 반복하지 않았다.
Forgejo [v15.0.11 EditUser](https://code.forgejo.org/forgejo/forgejo/src/tag/v15.0.11/routers/api/v1/admin/user.go)는 login_name/source_id를 함께 요구한다. Login 차단은 해당 두 필드 없이 `prohibit_login`만 사용했다.
[KEDA 2.19 provider](https://github.com/kedacore/keda/blob/v2.19.0/pkg/provider/provider.go)는 요청 selector로 ScaledObject를 찾는다. Nullable response label을0/성공으로 합성하지 않고 요청·HPA selector/owner 및 실제 metric을 대조했다.

누적은 **campaign18 / public initialize15 / healthy6 / started-invalid calibration3 / measured 각0 / KEDA restart4/4**다. 이번 미사용 calibration1과 measured 권한은 이월하지 않는다.
기존 USD290 승인 한도는 그대로이며 새 allowance/비용 모델/비용 조회는 없다. P9 actual 비용은 shared/delayed/unknown이다.
Environment `2026-11-05T01:30:00Z`, Foundation/Bootstrap `2026-11-05T15:33:00Z` 기한은 변경하지 않았다. 전체 teardown·추가 retention·merge/P10은 없다.

[execution](execution.json), [comparison/gap](comparison.json), [validation](validation.json), [raw index](raw-index.json), [sanitized append-only raw archive](raw-evidence.tar.gz)를 함께 본다.
이전 모든 negative/raw/ledger는 변경하지 않았다. 실행 source의 [local-platform](https://github.com/imcherry5778-labs/github-capacity-cascade-platform/actions/runs/41460375413)·[CodeQL](https://github.com/imcherry5778-labs/github-capacity-cascade-platform/actions/runs/41460367465) checks4개 SUCCESS를 재사용한다. 최종 evidence HEAD/CI는 PR 결과 comment에 연결한다.
