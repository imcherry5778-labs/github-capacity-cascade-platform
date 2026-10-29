# P9 제3차 승인 실행 — readiness/resource warning gate 중단

상태: **필수 초기화 gate 실패, P9-owned 원복/cleanup 완료, P9 acceptance 미충족**.
Healthy journey·fault·calibration·각 measured arm0, freeze 없음이다. Mitigation/recovery는 not measured이며
recovery window가 없으므로 `not recovered within observation window` 결과로 바꾸지 않는다.

승인·실제 execution source는 **`ffea5cb865728af54554c91460e3b96364d955fb`**다.
[사용자 승인](https://github.com/imcherry5778-labs/github-capacity-cascade-platform/pull/41#issuecomment-6488955743),
[최종 source gate](https://github.com/imcherry5778-labs/github-capacity-cascade-platform/pull/41#issuecomment-6487437745),
exact-head Full Local CI40811719098·CodeQL/Analyze success를 확인하고 실행했다.
Main은 `3f788a9c1d103f6c07bd403af269133fac287002`이며 실행 중 implementation은 변경하지 않았다.
후속 docs/evidence HEAD는 실행 승인 source가 아니다. 이전 두 실행의 raw/checksum/approval을 보존했다.

## 실제 수행과 실패 판정

| 단계 | 이번 실행 |
| --- | --- |
| Identity/환경 | 승인 사용자·subscription/AKS/cluster UID 일치, Argo Synced/Healthy, stable/shared/KEDA baseline 일치 |
| Image | source tag1 build/publish; digest `sha256:0215e9da851ec0a1380ab8d0e2d6a83f4b731b01decd2944e000d6441d3cc65a`; 종료 시 삭제 |
| Native normal | 새 non-admin fixture create1, structured operation/attempt9 성공; 원복 후 동일 fixture verify1 성공 |
| Initial admission | Ready Pod3; requests CPU400m/512Mi, limits CPU900m/1024Mi; sidecar/init 포함 conservative sum |
| Initialize | invocation1/exit1, command 약23.98초; healthy_initialize 약18.56초, 실패 stage 약5.01초 |
| Failure | `readiness_resource_guard` / `InitializationGuardError` / `warning_event` |
| Healthy journey/fault | 모두0. Journey intent/accounting/telemetry poll/completion 없음; workload 재시도 없음 |
| KEDA | actual2.19.0-25/원래 SA·spec, 다른 ScaledObject/ScaledJob0 확인. 새 IAM/SA/template mutation 및 apply/restore restart0 |
| Calibration/freeze/C0–C3 | calibration0, frozen plan 없음, measured 각0; [비교](comparison.json) 모두 not measured |

`healthy-initialization/events.jsonl`과 `initialization-ledger.jsonl`은 동일한 failure record1개다.
Stage/type/code와 false runtime-preflight/KEDA-ready flag가 보존돼 **이번 직접 실패 지점은 확인됐다**.
Protected mode0600 traceback의 source frame은 `initialization_safety → check`이며 `warning_event` 예외를 유지했다.
공개 projection은 stage/type/code·elapsed와 source filename/line/function만 포함한다. Message/argv/body/private path는 없다.
전체 traceback은 공개 archive에서 제외하고 보호 local cleanup 때 제거했다.

동일 invocation window의 HPA `FailedGetContainerResourceMetric`/`FailedComputeMetricsReplicas`가
2026-10-29 05:56:23 UTC에 관측됐고 message는 CPU metrics API에 metric이 없다고 기록한다.
이는 warning guard 중단과 일치하지만 **반환된 guard event 목록 자체는 저장되지 않았다**.
정확한 event 집합·metric 부재의 더 깊은 원인은 미확정이다. Timeout/budget 초과를 이번 causal exception으로 분류하지 않는다.
과거 `9c7b4be` 실행의 원인은 여전히 unknown이며 이번 결과로 소급 추론하지 않는다.
[Incident/corrective action](../../incidents/p9-mitigation-third.md)을 연결한다.

실제 확인 전 flag를 올리지 않았다. Configuration 단계는 완료했지만 positive journey/target telemetry gate는 미통과이며,
pre-traffic absent stat를 numeric0·inbound success로 만들지 않았다. Candidate cadence/client ID는 freeze가 아니다.
API helper audit에는 intent20/response20과 PAT ID14가 보존된다. Git 내부 HTTP·일부 auxiliary curl을 포함한 전체 HTTP 수는
unknown이며 operation9를 HTTP/check9로 취급하지 않는다.

## 원복·소유 cleanup

1. Initialize 실패 뒤 CUSTOM 제거를 우선했다. 첫 delete의 미지원 `-o json` 옵션 오류를 보존하고 즉시 기본 출력으로 수정하여
   동일 소유 UID를 제거했다. 이후 shared ConfigMap UID/applied-data를 JSON Patch test로 확인해 원본 data를 복구했다.
2. KEDA는 변경하지 않았고 원래 Deployment UID/spec·SA UID/annotation·Ready2를 확인했다. 이번 새 UAMI/FIC/workspace role은0이며
   `p9-keda-prometheus` 부재를 확인했다. 과거 첫 실행 apply1/restore1은 별도 사용 기록으로 유지한다.
3. P9 소유 namespace/controllers/Sidecar/PodMonitor/DB Secret/Pods를 삭제하고 namespace 부재를 확인했다.
4. Live Pod image 참조0, 해당 digest의 tag가 승인 source 한 개임을 확인한 뒤 소유 ACR manifest/tag와 local tag를 삭제했다.
   Shared base cache를 prune하지 않았다.
5. PAT ID14를 발급·후속 cleanup 전에 기록했다. DELETE204/0 bytes, 기존 PAT401, token 목록0을 login 차단 전에 확인했고,
   `prohibit_login=true` 및 Basic401도 확인했다. 기존 request helper를 재사용했다. Fixture 계정/repo/Issue/PR 기록은 보존한다.
6. AKS resource 하나의 소유 임시 role만 삭제하고 원래 Owner assignment IDs를 보존했다. Default kubeconfig는 변경하지 않았다.
   전용 kubeconfig/admin·DB/PAT/fixture clone/ACR auth/traceback과 checksum-verified 임시 kubelogin을 제거했다.
   Port-forward는 만들지 않았고 기존 Azure CLI login은 유지했다.
7. Stable Deployment UID/spec·Secret UID/data hash, Argo Synced/Healthy, PVC/PV/node UID 집합과 기존 Disk10GiB를 대조했다.
   Environment resource ID 집합과 nodes2/autoscaling OFF를 보존했다.

이는 **P9-owned cleanup**이며 전체 Azure environment teardown 또는 cache/fixture record zero-residual이 아니다.
Kubernetes authorization cache의 즉시 권한 소멸은 측정하지 않았고 Azure assignment 부재는 확인했다.
Admin logical version2 재사용은 기존 Secret UID/data hash, CSI writer timestamp와 현재 mounted object version을 이전 proof에 연결했다.
Key Vault 추가 권한/credential rotation은 없다.

## 비용·기한과 보존된 negative

과거 ActualCost KRW18,845.545320581 및 KRW24,292.445425032를 이어받는다.
이번 마지막 성공 조회는 **KRW26,885.8891798273 / usage date20261028**이다. 최초429 뒤 제한된 재조회에서 성공했다.
종료 조회와 마지막 제한된 재조회는 모두429여서 **final actual은 확보하지 못했다**.
P9 incremental actual은 delayed/shared billing으로 unknown이며 합계 차이를 P9 실비로 귀속하거나 비용0으로 만들지 않는다.
과거 실행 구간(2026-10-28 21:00 UTC 이후) 관련 namespace log의 관측 `_BilledSize` 합계323,094 bytes는 bounded 재준비 판단에 사용했지만
전체 P9 비용·완전한 최종 ingestion 양을 증명하지 않는다. 기존 USD5 예상/누적 USD10 검토 기준은 hard billing cap이 아니고 reset하지 않았다.
추가 calibration/measured run은 시작하지 않았다.

Environment **2026-10-30 10:30 KST**, Foundation/Bootstrap **2026-10-31 00:33 KST** 유지.
새 run+60초 drain+30분 rollback 여유가 있었지만 필수 gate 실패로 실행하지 않았다.
새 node/server/Disk/PVC·node autoscaling/DNS·retention·stable Secret 변경은 없다.

Local kubelogin 부재, 정상 결과의 console-only key 오류, multi-object JSON capture 오류 및 delete 출력 옵션 오류를
`operator-preparation-limitations.json`/원래 error captures로 보존했다. 정상 journey/초기 workload를 반복하지 않았으며
이들을 calibration/measurement로 계수하지 않는다. 과거 PAT ID/DELETE status·501 body 미보존도 과거 limitation으로 남는다.

## Raw·validation과 남은 gate

[실행 요약](execution.json), [comparison](comparison.json), [raw archive](raw-evidence.tar.gz),
[index/checksum](raw-index.json), [검증](validation.json)을 연결한다.
Raw153개는 안전한 publication projection이며 full traceback/credential/kubeconfig/Secret data는 포함하지 않는다.
Source/image/hash·승인·false flags, 실제 admission, credential/IAM/image/shared cleanup을 대조할 수 있다.

직접 P9 46개/P8 38개와 `make static`을 통과했다. 이 source 검증과 정상 native verify는 P9 effectiveness/recovery proof가 아니다.
다음 검토는 실제 HPA metric availability와 warning 발생 이유·준비 gate 순서를 보존 evidence로 평가해야 한다.
Warning 무시/timeout 확대/재실행으로 결과를 바꾸지 않는다. 실제 shared-path positive·target telemetry·KEDA auth,
calibration/freeze 및 C0–C3 continuing-demand evidence는 남아 있다. 같은 PR의 독립 검토와 필요한 새 실행 승인 전 추가 workload는 없다.
