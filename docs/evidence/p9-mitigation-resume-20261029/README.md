# P9 승인 재개 — healthy 초기화 준비 gate 중단

상태: **준비 gate 실패 / healthy journey·fault·calibration·measured 미실행 / P9-owned 원복·cleanup 완료**.
P9 acceptance는 충족하지 않았다. Mitigation/recovery 결과가 없으며, recovery observation window도 시작하지 않았으므로
이 결과를 `not recovered within observation window`로 바꾸지 않는다.

승인·실제 execution source는 **`9c7b4be942e534dff2e36fe069e144bfa96d045a`**다.
[사용자 승인](https://github.com/imcherry5778-labs/github-capacity-cascade-platform/pull/41#issuecomment-6486166268),
[독립 source gate](https://github.com/imcherry5778-labs/github-capacity-cascade-platform/pull/41#pullrequestreview-5692094220),
exact-head Full Local CI40802389637·CodeQL/Analyze success를 확인했다.
Main은 `3f788a9c1d103f6c07bd403af269133fac287002`이며 실행 중 source를 수정하지 않았다.
후속 evidence/docs HEAD는 실행 승인 source와 별개다.
이전 `c06ce67...`의 [preflight/negative/cleanup](../p9-mitigation-preflight-20261029/README.md)은 변경하지 않았다.

## 실제 수행과 중단

| 단계 | 이번 재개 관측 |
| --- | --- |
| Azure identity/환경 | 승인 사용자·subscription/AKS 일치, cluster UID·Argo Synced/Healthy·stable spec·shared mesh 원복 baseline 일치 |
| Image | 새 exact-source tag1 build/publish, digest `sha256:5b4e76aadcf02de20718170a2c36e82cdbd965ce43466ab449ccfec15d3d6b56`; 이후 삭제 |
| 정상 native HTTPS | 새 fixture create1, structured operations/attempts9 성공; 원복 후 같은 fixture verify1 성공 |
| 초기 admission | Pod3, requests CPU400m/memory512Mi, limits CPU900m/memory1024Mi; injected init/native sidecar 포함 |
| Healthy initialize | entrypoint1회, exit1; `healthy_initialization_failure`만 기록, journey intent/telemetry poll/completion 없음 |
| Healthy journey / fault | 각각0회; 실패를 이유로 workload를 반복하지 않음 |
| KEDA | actual `2.19.0-25`/SA/CRD 확인, 다른 ScaledObject/ScaledJob0; UAMI/FIC/workspace assignment·SA mutation·restart 각각0 |
| Calibration / freeze / C0–C3 | calibration0, freeze 없음, measured 각0; [비교 상태](comparison.json) 모두 not measured |

`healthy-initialize-command.json`, `healthy-initialization/events.jsonl`, `initialization-ledger.jsonl`,
`operator-ledger.jsonl`이 invocation과 중단 순서를 보존한다. 약39.79초의 invocation에서 journey intent 이전에 중단했다.
Source CLI는 causal exception을 노출하지 않고 generic 실패 문구만 남기므로 **정확한 실패 원인은 unknown**이다.
같은 시간대 HPA resource-metric 경고는 관측됐으나 원인으로 확정하지 않는다. Snapshot budget 초과 여부도 확정하지 않았다.

`target-*-gate-stop.json`, `fixture-events-gate-stop.json`, `pod-metrics-gate-stop.json`은 CUSTOM policy 제거 후의
read-only 진단이다. Offline target mapping/bootstrap `cluster_name` 대조는 통과했지만 admin/native inbound series는
pre-traffic 상태에서 없었다. 이 partial check를 초기화·telemetry·scaler 성공으로 승격하지 않는다.
이전 bootstrap cluster의 positive sample을 target inbound proof로 바꾸지도 않는다.
[Incident와 corrective action](../../incidents/p9-mitigation-resume.md)을 연결한다.

## 원복과 보존

1. 실패 확인 후 **CUSTOM policy 우선 제거**. UID/campaign 확인 후 삭제했고 workload를 추가하지 않았다.
2. Shared ConfigMap UID/적용 data를 JSON Patch test로 확인한 뒤 원본 data 복구.
3. KEDA는 이번에 변경하지 않았으며 원래 SA UID/annotation·Deployment UID/spec와 Ready2를 확인했다.
   새 KEDA UAMI/FIC/workspace role은 생성하지 않았다. Historical apply1/restore1은 사용 기록으로 유지한다.
4. 소유 namespace/controller/PodMonitor/Sidecar/DB Secret/Pod 제거. Registry manifest/tag의 다른 tag·live Pod 참조0을 확인한 후
   소유 image와 local tag를 삭제했다. 공용 base cache는 prune하지 않았다.
5. 새 PAT **ID13**을 후속 cleanup 요청 전에 audit에 기록했다. DELETE **HTTP204/0 bytes**, 기존 PAT **401**, token 목록0을
   login 차단 전에 확인했다. `prohibit_login=true`와 Basic401도 확인했다. 기존 request helper를 재사용했고 별도 cleanup harness는 없다.
6. 임시 AKS assignment만 삭제하고 기존 Owner2 보존 확인. 전용 kubeconfig/admin·DB credential/fixture clone/ACR auth를 제거했다.
   Port-forward는 만들지 않았으며 기본 kubeconfig와 기존 Azure CLI login은 보존했다.
7. Stable Argo/spec, Secret UID/data hash, PVC/PV/node UID 및 기존 Disk10GiB를 확인했다.
   Environment resource ID 집합·nodes2/autoscaling OFF를 보존했다. Fixture 계정/repo/Issue/PR 기록은 남긴다.

이 결과는 **P9-owned cleanup**이다. 전체 environment teardown/물리적 cache·fixture record zero-residual을 주장하지 않는다.
Environment **2026-10-30 10:30 KST**, Foundation/Bootstrap **2026-10-31 00:33 KST** 유지.

## 비용·횟수·한계

과거 두 RG ActualCost **KRW18,845.545320581**을 보존한다. 이번 before/final 조회는 모두
2026-10-28 usage의 **KRW24,292.445425032**다. 지연 반영된 shared-resource aggregate이며
이번 P9 증가분·과거 준비/원복 비용을 분리할 수 없다. **동일한 전후 값은 P9 비용0의 증거가 아니다.**
Current retail 입력도 보존했다. 계획 증분 USD5 / 누적 검토 USD10은 hard billing cap이 아니고 0으로 초기화하지 않았다.
새 node/server/Disk/PVC·autoscaling/DNS 변경·보존 연장·추가 유료 run은 없다.

이전 정상 create1/verify1, KEDA apply1/restore1, IAM/image/credential 준비·원복과 이번 정상 create1/verify1·준비·원복을
별도 기록한다. Calibration/measured 누적은 여전히0이며 두 번째 target admission/scaling도 관측하지 않았다.

- Cost Management HTTP429와 Retry-After를 보존하고 제한된 read-only 재조회 후 current cost를 확보했다.
- Key Vault metadata read는 ForbiddenByRbac였다. 권한을 추가하지 않았다. 기존 version2 재사용 근거는 이전 native-auth proof,
  같은 Kubernetes Secret UID와 그 proof 이전의 CSI data-writer timestamp(2026-10-28 06:56:27 UTC), current mounted object version이다.
  Current Key Vault version enumeration을 성공했다고 주장하지 않는다.
- 정상/최종 journey의 API helper intent/status/bytes와 credential ID를 `normal-request-audit.jsonl`로 보존했다.
  Git 내부 HTTP와 일부 기존 auxiliary curl을 포함한 전체 HTTP 수는 unknown이며 operation과1:1로 추정하지 않는다.
- Local event serialization/own bytecode/INI parse 및 cleanup metadata field 오류는 `preparation-negative-01`–`06`에 보존했다.
  Source/acceptance를 변경하거나 이들을 calibration/measurement로 바꾸지 않았다.
- Source CLI가 실패한 stage/type/causal traceback을 보존하지 않아 원인 식별에 제한이 있다. 추가 workload로 진단을 보완하지 않았다.
- Kubernetes authorization cache의 즉시 revocation은 측정하지 않았다. Azure assignment 부재는 확인했다.
- 과거 PAT numeric ID/DELETE status·HTTP501 body 미보존은 과거 limitation으로 남는다. 이번 ID13/204 기록으로 과거를 덮지 않는다.

## Raw와 validation

[실행 요약](execution.json), [comparison](comparison.json), [검증](validation.json),
[raw archive](raw-evidence.tar.gz), [개별 index/checksum](raw-index.json)을 보존한다.
Raw127개는 append-only 수집의 sanitized projection이다. Credential 값·private local path는 포함하지 않는다.
Local image inspect의 host storage/graph path만 export에서 제외했고 projection을 index에 기록했다.
실제 source/image, approval·identity·plan hash·false healthy/runtime flags와 정상 proof의 단계별 binding을 대조할 수 있다.

남은 gate는 pre-journey 실패 원인 식별, 실제 shared-path positive journey, inbound admin/native/ingested series·freshness/cadence,
admission/ownership과 실제 KEDA scaler authentication, calibration/freeze 및 C0–C3 continuing-demand evidence다.
기존 승인 SHA/flags를 후속 evidence HEAD에 치환하지 않는다. 같은 PR의 독립 검토와 필요한 재개 판단 전 추가 workload를 시작하지 않는다.
