# P9 제6차 승인 실행 — initialization Pod restart guard 중단

상태: **valid normal 통과 / initialization 필수 Pod guard 실패 / P9-owned 원복 완료 / P9 acceptance 미충족**.
승인·실제 execution source는 `30271ea59c4824b9bf4455ec038528891692d434`다.
[제6차 통합 승인](https://github.com/imcherry5778-labs/github-capacity-cascade-platform/pull/41#issuecomment-6494902133),
[독립 review](https://github.com/imcherry5778-labs/github-capacity-cascade-platform/pull/41#pullrequestreview-5696587057),
[승인 source Full Local CI](https://github.com/imcherry5778-labs/github-capacity-cascade-platform/actions/runs/40857524860)를 확인했다.
실행 동안 source/clean HEAD를 유지했고 implementation 수정은 없다. 후속 evidence HEAD는 실제 execution source와 구분한다.

## 5차 오류 교정과 실제 normal proof

첫 external mutation 전에 `RESULT_PHASE=warmup`을 기존 validator의 `warmup|measured` 허용값 및
healthy initializer의 `warmup` 요구와 대조했다. 실제 선택한 executable은 repository `.tmp/bin/kubectl`,
version **v1.36.4**, SHA256 **`8b8f088da2dab964f853b38464033b1be15ede2839eca751482357c45abdd05a`**다.
`versions.env` pin과 일치하며 실행 종료 시에도 version/hash가 같았다. Absolute local path는 보호 attestation에만
보존하고 public raw에는 실제 repository-relative path를 기록했다.

Normal context는 현재 도구 정보와 live cluster/Argo/Forgejo image 정보에서 fresh 생성했다.
과거 context를 복사하지 않았다. Context CLI의 첫 local 확인은 checking process의 producer env가 local 기본값이어서
거부됐으나, native HTTP 전에 실제 `azure-aks`/transport 환경으로 대조해 통과했다. Context bytes는 바꾸지 않았다.
새 native normal create **1회/exit0**, operations9/attempts9를 실제 source validator가
**valid/success/warmup**으로 확인했다. Numeric PAT ID17은 발급 뒤 후속 mutation 전에 audit에 기록했다.
이 결과를 healthy/runtime gate의 성공 flag로 미리 사용하지 않았다.

## 실제 준비와 필수 중단

| 항목 | 이번 실행 |
| --- | --- |
| Environment | 기존 AKS1.36.4/asm-1-30·D4s_v4 node2/autoscaling OFF, cluster UID 일치; Argo Synced/Healthy |
| Image | exact source tag1 publish, digest `sha256:e0a95cf4d2431ad719c6638282a2638d713c83840d53b534128cad378d4b2fef`; 종료 시 삭제 |
| Credential | 기존 admin logical version2 UID/data hash·mounted versions 일치 후 한정 재사용; rotation 없음 |
| Owned preparation | Namespace/DB Secret/shared overlay/HAProxy/target/CPU HPA/PodMonitor 준비 뒤 CUSTOM 적용 |
| Admission | Ready Pod3, conservative requests CPU400m/512Mi, limits CPU900m/1024Mi; injected init/native sidecar 포함 |
| Initialize | invocation1/exit1, external command29.468초, healthy initializer25.138초 |
| 직접 failure | `readiness_resource_guard / InitializationGuardError / pod_not_ready_or_restarted` |
| Restart evidence | initial 및 later-read terminal snapshot의 같은 HAProxy UID, restart3, last termination `Error` |
| CPU/healthy | CPU poll0·준비 완료 없음, healthy journey intent0/실행0, target positive telemetry 없음 |
| KEDA | actual2.19.0-25/Ready2; 다른 ScaledObject/ScaledJob0, UAMI/FIC/workspace role·SA/operator 변경/restart0 |
| Campaign | fault0, calibration0, freeze 없음, C0/C1/C2/C3 measured 각각0; mitigation/recovery not measured |

Operator가 initial manifest 객체를 순차 생성하면서 HAProxy Deployment를 backend Service보다 먼저 생성했다.
HAProxy 이전 container log는 `ext-authz-sim.p8-shared-gate.svc.cluster.local` 주소를 해석하지 못하고
worker가 exit1로 종료한 것을 보존한다. 이후 Ready가 됐지만 restart3/Error 이력은 이미 initial snapshot에 있었다.
Source의 기존 무재시작 guard는 이를 거부한다. **Ready=True를 무재시작 proof로 사용할 수 없다.**
Source가 failing guard 전체 payload를 emit하지 않으므로 initial/post-stop snapshot과 해당 호출의 실제 payload를
같은 것으로 취급하지 않는다. 두 snapshot의 이력과 previous log는 guard failure에 부합한다.
정확한 첫 DNS query 시각과 Service/DNS propagation latency는 측정하지 않았다.
Source의 CPU settling300초나 sample-window90초/freshness30초 결함으로 원인을 바꾸지 않는다.

준비 중 DB Secret에 username key가 있다고 가정한 local manifest construction도 거부됐다.
실제 Secret은 password만 포함하므로 current source `values-common.yaml`의 app role `forgejo`를 사용했다.
이 오류 시점에는 DB Secret/Pod를 생성하지 않았으며 기존 app role/verify-full/read-only SQL 범위를 유지했다.
이 local 보완은 source 수정이나 native normal/initialize 재실행이 아니다.

필수 guard failure 뒤 CUSTOM을 우선 제거하고 shared CM을 원복했다.
Initialize/healthy journey/Pod를 재시도하거나 HAProxy Pod를 교체해 restart history를 초기화하지 않았다.
계획된300초 CPU settling/840초 external initialization bound는 유지됐고 이번 중단은 timeout이 아니다.
[Incident/corrective action](../../incidents/p9-mitigation-sixth.md)을 연결한다.

## 원복·보존·비용

CUSTOM UID/spec를 대조해 우선 제거했고 shared CM UID/applied-data를 JSON Patch test한 뒤 원래 data를 복구했다.
소유 namespace/controllers/DB Secret/Pods를 제거하고 namespace/policy 부재를 확인했다.
KEDA Deployment UID/spec·SA UID/annotations·Ready2, stable Forgejo UID/spec·Argo Synced/Healthy,
stable Secret UID/data hash, node/PVC/PV/service UID 집합과 PVC/PV spec을 비교했다.
Actual Azure Disk ID가 기존 PV handle과 같고10GiB임을 확인했다. 새 compute/Disk/PVC/DNS/autoscaling 변경은 없다.

Final native normal read-only verify **1회/exit0** 뒤 PAT17 exact DELETE204/0 bytes, PAT401/token 목록0,
계정 login 차단/Basic401을 확인했다. Fixture 계정/repo/Issue/PR 기록은 유지한다.
Owned digest의 tag가 승인 source 한 개이고 Pod spec/imageID의 live 참조0인 것을 확인한 뒤
manifest/tag/local tag를 제거했다. Shared base/cache는 purge하지 않았다.

AKS role CLI delete는60초 client timeout을 기록했다. Exact GET에서 소유 role이 남은 것을 확인하고
같은 principal/scope의 **exact ARM ID만 DELETE**한 뒤 GET not-found와 원래 assignment ID 집합 일치를 확인했다.
Timeout을 삭제 성공으로 승격하거나 다른 role을 삭제하지 않았다. Kubernetes authorization cache의 즉시 소멸은 미측정이다.
보호 credential/PAT/clone/ACR auth/kubeconfig/ephemeral kubelogin/full traceback·local helper를 제거했다.
Azure CLI login 유지, 기본 kubeconfig 변경/port-forward 없음이다.
이는 P9-owned cleanup이며 전체 Environment/cache/fixture-record zero-residual 선언이 아니다.

Before/final two-RG ActualCost는 **KRW34,327.6634214082**로 같다
(usage20261028 KRW30,259.1340498108 + usage20261029 KRW4,068.5293715974).
**P9 incremental actual은 delayed/shared billing 때문에 unknown**이며 같은 값은 비용0 proof가 아니다.
과거5회와 이번을 합쳐 준비/원복 **누적6회**, historical KEDA apply/restore restart 각1회를 보존한다.
이번 KEDA mutation/restart는0이다. USD5 계획/누적 USD10 검토 기준은 billing hard cap이 아니며 reset하지 않는다.
Resource cap Pod≤4/requests·limits 각각 CPU≤1500m·memory≤2048Mi, run≤600초를 유지했다.
Environment **2026-10-30 10:30 KST**, Foundation/Bootstrap **2026-10-31 00:33 KST**를 연장하지 않았다.
전체 teardown은 없으며 P11까지 기존 환경 재사용 경계를 유지한다.

## Evidence와 남은 gate

[Execution](execution.json), [comparison](comparison.json), [raw117 archive](raw-evidence.tar.gz),
[개별 size/SHA256 index](raw-index.json), [검증](validation.json)을 연결한다.
Archive SHA256은 `0145380edc3741577f6b5560042bec5f93e4c3ad2715f185d0cbe1778340ecf1`이다.
117 member size/hash, 실제 valid normal validator, initial snapshot의 기존 no-restart predicate 위반,
cleanup 비교·known-secret/private-path scan과 과거 archive hash 보존을 확인했다.
Private credential/traceback/absolute local path 파일은 publication에서 제외했다.
Unchanged implementation 검증이나 P6/P7/P8 전체 실험을 수동 반복하지 않았다.

남은 gate는 무재시작 healthy baseline→CPU/HPA→single healthy shared-path/target telemetry→실제 KEDA/scaler auth→
calibration/freeze/C0–C3 continuing-demand recovery다. 이번 run은 이 gate를 통과하지 않았다.
다음 승인 실행에서는 기존 Service/config를 먼저 준비해 HAProxy Deployment 시작 순서를 교정하고
기존 Ready+restart0 predicate를 함께 확인해야 한다. Source 변경/추가 controller/별도 Task는 이번 결과의 요구사항이 아니다.
이번 negative/history를 보존하고 별도 통합 재승인 전 자동 재실행하지 않는다.
