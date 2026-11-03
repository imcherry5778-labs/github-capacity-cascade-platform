# P9 승인 실행 — runtime gate 중단과 원복

상태: **필수 telemetry gate 미통과 / calibration·measured 미실행 / P9-owned controls 원복 완료**.
P9 mitigation 효과·autoscaling 성공·continuing-demand recovery 결과는 없다. 이 기록은 P9 milestone 완료 또는 전체 환경 zero-residual 선언이 아니다.

승인·실제 execution source는 모두 `c06ce67b2d438c7affde6b6934368b43afa4c1f4`다.
[승인](https://github.com/imcherry5778-labs/github-capacity-cascade-platform/pull/41#issuecomment-6483350700),
[독립 source gate](https://github.com/imcherry5778-labs/github-capacity-cascade-platform/pull/41#pullrequestreview-5690941787),
exact-head Full Local CI `40775847630`와 CodeQL success를 확인하고 시작했다.
실행 source를 바꾸거나 기존 승인 SHA를 치환하지 않았다. 이 후속 변경은 문서·evidence뿐이다.
기존 main은 `3f788a9c1d103f6c07bd403af269133fac287002`, stable Argo revision은 `2f63d283ebba12aaed8705732f1206d71ddc33db`다.

## 실행·검증 상태

[실행 요약](execution.json), [C0–C3 결과 상태](comparison.json), [incident/corrective action](../../incidents/p9-mitigation-preflight.md)을 연결한다.

| 항목 | 실제 결과 |
| --- | --- |
| 정상 HTTPS journey | create 1회, structured operation/attempt 9개 성공; 원복 후 기존 fixture verify 1회 성공 |
| Healthy-gate journey | 0회; CUSTOM policy 적용 전에 중단 |
| Calibration / freeze | 총 0회 / 동결 없음 |
| C0 / C1 / C2 / C3 measured | 각 0회; 비교·mitigation·recovery 모두 not measured |
| Fault / release / recovery window | 시작하지 않음; recovery time 없음 |
| Fixture / PAT | 각 1개 생성; private journey repo/Issue/PR 기록 보존, PAT revoke와 login 차단 확인 |
| Managed KEDA | actual image `mcr.microsoft.com/oss/v2/kedacore/keda:2.19.0-25`; 다른 ScaledObject/ScaledJob 0개 확인 |
| KEDA identity | 전용 UAMI/FIC/workspace Reader 준비와 token 주입 확인; workspace scaler 인증은 **not verified** |
| Operator rollout | 적용 1회, 원복 1회; 원래 SA annotation·Deployment template·identity env 복귀와 Ready 2개 확인 |

초기 fixture Pod 3개의 실제 admission 합계는 requests CPU400m/memory512Mi, limits CPU900m/memory1024Mi다.
실제 주입된 target Pod spec을 복제한 **보수적 예산 계산**은 두 target 기준 limits CPU1450m/memory1664Mi였다.
두 번째 target의 실제 admission/scheduling 또는 scaling 성공을 관측한 것은 아니다. 승인 상한 Pod4/CPU1500m/memory2048Mi는 변경하지 않았다.

후보는 mitigation180s/recovery180s, backoff250–750ms/seed5778, queue12/250ms, threshold0.5,
scrape15s/ingestion30s/controller15s/freshness60s를 유지했다. 이 cadence는 actual freshness/관측 근거로 동결되지 않았다.
Actual KEDA version과 새 client ID만 보호된 입력에 연결했으며, 해당 UAMI/client ID는 원복 시 제거했다.
`approval-binding.json`의 정상 flag만 true이고 healthy/runtime-preflight flag는 false다.
기존 3×10초 recovery criterion을 완화하지 않았으며, 관측 window 자체가 없으므로 `not recovered within observation window` 결과를 꾸며 넣지 않았다.

## 중단 근거 — FACT와 limitation

- **FACT:** 실제 Envoy bootstrap `stats_tags`의 tag 이름과 노출된 cluster counter/gauge sample label은 `cluster_name`이다.
  승인 source의 `scale_query()`와 `Runtime.signal()`은 `envoy_cluster_name="inbound|8080||"`를 고정 사용한다.
- **FACT:** PodMonitor `up=1`, Kubernetes target UID와 일치하는 `kube_pod_info`는 관측됐다.
  승인 source의 raw/rate/active/timestamp/sample-count/guarded query는 HTTP200과 empty vector를 반환했다. Empty를 0으로 바꾸지 않았다.
- **FACT:** 이 healthy traffic 이전 startup 관측에서 target inbound cluster의 필수 admin stat도 아직 materialize되지 않았다.
  Inbound cluster config와 capacity1024는 존재했고 bootstrap의 다섯 stat suffix도 적용돼 있었다.
- **LIMITATION:** 아직 inbound traffic이 없었으므로 empty의 단일 원인이나 실제 target rate cadence를 측정했다고 주장하지 않는다.
  Native tag contract와 hardcoded selector의 불일치, 필수 mapping/query 미통과가 실행 중단 근거다.

관련 raw는 archive의 `actual-envoy-cluster-label.json`, `ingested-envoy-cluster-label.json`,
`target-prometheus-exact-source-gate.json`, `target-admin-initial-required-stat-negative.json`, `runtime-gate-stop.json`이다.
Public workload를 추가해 series를 만들거나 source/guard를 바꾸지 않고 원복했다.

Actual 2.19 contract는 [Prometheus scaler](https://keda.sh/docs/2.19/scalers/prometheus/),
[Azure Workload Identity](https://keda.sh/docs/2.19/authentication-providers/azure-ad-workload-identity/),
[AKS managed 절차](https://learn.microsoft.com/en-us/azure/aks/keda-workload-identity)와 대조했다.
이는 실제 scaler 인증·C3 동작의 성공 evidence가 아니다.

## 원복·보존

1. CUSTOM policy가 처음부터 absent였음을 우선 확인했다. Public native auth path는 gate로 전환하지 않았다.
2. Shared ConfigMap은 UID와 적용 직후 data를 JSON Patch test로 확인한 뒤 원본 data로 복구했다.
3. KEDA SA의 P9 client annotation을 제거하고, 이번 restart annotation을 원래 값으로 되돌리는 **한 번의 원복 rollout**으로 원래 template을 복원했다.
   Ready 2개와 원래 identity env를 확인한 뒤 workspace assignment → FIC → UAMI를 exact ID/name으로 제거했다.
4. P9-owned HPA/PodMonitor/Sidecar/DB Secret과 namespace를 제거했다. Image의 다른 tag·live Pod 참조가 없음을 확인한 뒤 정확한 manifest/tag와 local owned image를 제거했다.
5. 최종 정상 HTTPS verify 후 PAT 잔여0과 원래 PAT401을 login 차단 **전에** 확인했다. Fixture `prohibit_login=true`와 Basic login 거부도 확인했다.
6. 임시 AKS role assignment 하나를 제거하고 기존 assignment ID 보존을 확인했다. 전용 kubeconfig·ACR auth·fixture credential·helper 사본을 제거했다. Port-forward는 생성하지 않았다.

Argo `Synced/Healthy`, stable Deployment spec와 Secret UID/data, PVC/PV·ingress·node UID가 보존됐다.
Node2/autoscaling OFF, PostgreSQL Ready, 기존 Disk10GiB와 PG storage32GiB를 확인했다.
Environment resource ID 집합은 시작 전과 같았다. 기존 environment teardown이나 DNS·보존 기한 변경은 없다.
Environment **2026-10-30 10:30 KST**, Foundation/Bootstrap **2026-10-31 00:33 KST**를 유지한다.
Fixture 계정/repo/Issue/PR 기록은 남기므로 전체 환경 zero-residual 또는 물리적 image/cache/media 삭제를 주장하지 않는다.

## 비용·audit limitation

시작/종료 ActualCost 응답은 모두 2026-10-28의 기존 두 RG 합계 **KRW18,845.545320581**였다.
승인 요청 시의 KRW16,015.5402320629는 별도 historical 조회다. Billing 지연과 shared-resource 특성 때문에
이번 P9 증가분은 **unknown**이며 전후 합계가 같다는 이유로 0이라고 하지 않는다.
계획 증가분 USD5/추가 검토 예산 USD10과 기존 retention을 바꾸지 않았고 추가 run은 시작하지 않았다.

- 정상 journey의 structured attempts와 Git 내부 HTTP request 수는 다르다. 정상 journey 전체 HTTP 수는 별도 enumerate하지 못했다.
- Telemetry query 18회를 ledger에 계수했다. 탐색용 metric-name regex query의 HTTP501은 late record이며 response body가 남지 않았다.
  Required exact query의 HTTP200/empty 응답은 보존했다. Workload 재실행으로 보완하지 않았다.
- Credential cleanup API 13회를 계수했다. DELETE 뒤 empty-body parser 오류로 **numeric token ID와 원래 DELETE HTTP status를 raw에 남기지 못했다**.
  그 요청은 reconstructed entry로 구분했고 token 잔여0·기존 PAT401을 독립 확인했다. Login 차단 API의 422 응답도 성공으로 바꾸지 않았다.
- 준비·직렬화·검증 enum/field 오류는 `preflight-negative-01`–`08.json`에 보존했다. 실제 campaign run으로 계수하거나 successful calibration으로 승격하지 않았다.
- 임시 AKS role의 native assignment 부재는 확인했다. Kubernetes authorization cache의 즉시 revocation은 따로 측정하지 않았다.

## Raw·검증·재개 경계

[raw archive](raw-evidence.tar.gz)와 [index/checksum](raw-index.json)은 append-only local 수집을 publish한 것이다.
Credential/private input은 포함하지 않았고, principalName email 필드 두 곳만 export에서 제거해 index에 명시했다.
[검증 기록](validation.json)은 archive 재계산, 승인 source file hash, 실제 원복 snapshot 비교와 직접 회귀/static 결과를 기록한다.
Source 승인/실행 SHA와 후속 문서/evidence HEAD를 구분한다. Final exact HEAD/check 상태는 PR/GitHub와 최종 보고가 authority다.

재개 전에는 actual cluster label과 query contract를 같은 source/input으로 결합하고, 승인된 healthy 경로와
inbound stat 초기화 검증 순서를 정리해야 한다. 새 exact source를 독립 source gate에 올린 뒤 필요한 실행 승인을 받아야 한다.
기존 승인 binding의 SHA·flags를 바꿔서 통과시키지 않는다. 기존 C0–C3 intent/acceptance/safety와 같은 PR 경계를 유지한다.
