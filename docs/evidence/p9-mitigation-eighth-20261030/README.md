# P9 제8차 Azure 실행 — CPU 준비300초 경계 중단

상태: **valid normal·무재시작 Pod 준비 통과 / CPU ready0 / P9-owned 원복 완료 / P9 acceptance 미충족**.
Campaign 날짜는2026-10-30 KST이며 아래 runtime 시각은2026-10-29 UTC다.

승인·실제 execution source는 **`98e95e5850f2442e08a6306bf955aa12c0427b17`**,
main/base는 `3f788a9c1d103f6c07bd403af269133fac287002`다.
[제8차 통합 승인](https://github.com/imcherry5778-labs/github-capacity-cascade-platform/pull/41#issuecomment-6505956066),
[독립 source review](https://github.com/imcherry5778-labs/github-capacity-cascade-platform/pull/41#pullrequestreview-5699052353),
[승인 source CI](https://github.com/imcherry5778-labs/github-capacity-cascade-platform/actions/runs/40883184917)를 확인했다.
없어진 local feature checkout을 Orca CLI로 승인 remote HEAD에서 격리 복원했다. 같은 branch/PR이며 다른 working tree를 변경하지 않았다.
실행 전후 clean exact source를 확인했고 source 수정은 없다. 후속 evidence HEAD를 actual execution source로 바꾸지 않는다.

## Actual preparation

첫 external mutation 전에 `RESULT_PHASE=warmup`을 validator 허용값과 대조했다.
실제 선택한 repository `.tmp/bin/kubectl`은 **v1.36.4**, SHA256
`8b8f088da2dab964f853b38464033b1be15ede2839eca751482357c45abdd05a`로 versions.env pin과 일치했고 final check도 동일했다.
Absolute path는 보호 attestation에만 두었다. Actual tools·live cluster/Argo/runtime imageID의 fresh context를 생성했다.
Normal create **1회/exit0**, actual source validator **valid/success/warmup, 9operations/9attempts**다.
Native non-admin auth/private repo/HTTPS certificate·hostname verification과 process-local DNS override를 유지했다.
Admin logical version2는 승인 범위에서만 재사용했고 current Secret UID/data hash·mounted version이 이전 evidence와 같았다.

기존 ACR의 새 승인 SHA 단일 tag `ext-authz-sim:98e95e5850f2442e08a6306bf955aa12c0427b17`을 source Dockerfile/pinned base로 build/publish했다.
Registry 대조 digest는 **`sha256:2cfa62dd9491ee4b06e554297364517be3a8e322671ca3638f0220c3829efe37`**다.
ACR Tasks/새 compute는 사용하지 않았다.

ConfigMaps `19:32:15/16` → backend Service `19:32:18` → target Pod/CPU HPA `19:32:22`
→ target Ready `19:32:37` → **HAProxy Deployment `19:32:56`** 순서를 지켰다.
Service name/namespace/ClusterIP/selector·Ready EndpointSlice를 HAProxy 생성 전에 확인했다.
Initial HAProxy·target·DB는 모두 Ready/Running·active containers restart0/last termination null이었다.
Init status도 restart0/Error·OOM 없음이었다. Admitted Pod3의 보수적 합계는 requests **400m/512Mi**, limits **900m/1024Mi**다.
그 뒤 CUSTOM을 생성하고 public `initialize`를1회 호출했다. Pod 교체/history reset은 없다.

## CPU 관측과 실제 중단

Initialize 시작 `19:33:14.758074`, 종료 `19:38:20.264819`, exit1이다.
외부 process elapsed **305.507초**, initializer elapsed **300.004초**다.
Public failure는 **`readiness_resource_guard / TimeoutExpired / command_timeout`**이다.
보호 exception chain은 settling 반복 안의 `configuration`→ingress Envoy dynamic route config 수집에서
남은 **0.272423409초** command budget이 적용된 `subprocess.TimeoutExpired`임을 확인했다.
Public stage label은 반복 내부 configuration까지 포함하며 마지막 실행 stack과 구분한다.
외부840초 TERM/kill-after5초가 먼저 종료한 결과가 아니다. Snapshot30초/command15초를 확대하지 않았다.

CPU HPA exact UID `574ff3ca-6624-4c7e-98e1-c4e66eb43a66`의 허용된 metric Warning2개는
collector 첫 관측 count5(`19:33:38`)→7(`19:34:08`)→8(`19:34:23`)로 증가했다. 마지막 발생은 **Pod/HPA 생성 후121초**였다.
새 source는 이를 보존·관측하며 pending을 유지했다. Warning90초 cutoff 오류는 재발하지 않았다.
첫 fresh CPU/HPA 관측 이후 Warning UID/count/time은 변하지 않았다. 삭제·숨김·재발 허용은 없다.

| CPU poll | Sample timestamp UTC | Window(s) | Ready 전체 window+fresh | HPA metric recovered | Source status |
| --- | --- | ---: | --- | --- | --- |
| 1 | 19:32:37 | 13.935554496 | false | false | pending |
| 2 | 19:33:22 | 55.728040256 | false | false | pending |
| 3 | 19:34:23 | 61.047 | **true** | **true** | pending |
| 4 | 19:34:23 | 61.047 | false | true | pending |
| 5 | 19:35:25 | 58.711 | **true** | **true** | pending |
| 6 | 19:35:25 | 58.711 | false | true | pending |
| 7 | 19:36:17 | 51.982 | false | true | pending |
| 8 | 19:36:17 | 51.982 | false | true | pending |
| 9 | 19:37:22 | 64.538 | false | true | pending |

**Fresh CPU/HPA positive 관측은 poll3·5 두 번 실제로 있었다.** 이 둘의 CPU timestamp는 advancing이며
initializer elapsed83.855초/147.392초에 관측됐다. HPA currentMetrics는 app/cpu의2%·1m이었다.
그러나 중간 poll4는 stale 판정이었다. 이후 poll6–9도 Ready 전체 window는 만족하지만 fresh 판정은 false였다.
현재 source는 non-positive poll에서 candidate를 해제하므로 이 sequence가 ready로 이어지지 않는 것과 부합한다.
이는 **source 판독에 따른 추론**이며 internal candidate state/full guard payload는 emit되지 않았다.
서로 다른 두 fresh 관측이 전혀 없었다고 서술하거나, 반대로 이를 actual preparation 완료로 재분류하지 않는다.

완료 poll 간격은 약31.56–33.00초였다. 관측한 서로 다른 sample timestamp 간격은45/61/62/52/65초다.
이는 collector가 본 export 간격이며 실제 metric 생성 주기·지연 원인·AKS controller flags를 입증하지 않는다.
Window 길이를 cadence로 해석하지 않는다. 마지막 완료 poll은 initializer elapsed276.567초였고,
다음 반복 수집이300초 경계에 도달했다. Bound/freshness/sample 조건이나 source를 바꾸고 재시도하지 않았다.

**CPU poll9/pending9/ready0, healthy journey intent0/실행0, KEDA mutation0, fault0, calibration0,
freeze 없음, measured C0–C3 각각0**이다. Mitigation/continuing-demand recovery는 모두 **not measured**다.
Synthetic recovery·추가 probe·자동 workload replay는 없다. Post-stop HPA/sample을 준비 성공으로 승격하지 않는다.

## Cleanup·비용·보존

CUSTOM exact UID/spec 대조 후 우선 제거 → shared ConfigMap UID/applied-data JSON Patch test 원복 →
소유 namespace/controllers/PodMonitor/HPA/DB Secret/Pods 제거·부재를 확인했다.
Final native read-only verify **1회/exit0** 뒤 PAT19 numeric ID exact DELETE **204/0 bytes**,
PAT **401**, token 목록0, login 차단/Basic401을 확인했다. Fixture records는 유지한다.
Image spec/imageID references0·소유 단일 tag 확인 뒤 exact remote digest/tag와 local tag를 제거했다.
임시 AKS role exact ID/principal/scope GET→DELETE→GET not-found·원래 assignment ID 집합 일치를 확인했다.
즉시 Kubernetes authorization cache 소멸은 미측정이다.

KEDA Deployment UID/spec·SA UID/annotations unchanged/Ready2, 이번 operator apply/restore restart0/0이다.
과거 첫 실행의 apply1/restore1은 유지한다. Stable Forgejo UID/spec, Argo Synced/Healthy·spec,
Secret UID/data hash, node/PVC/PV/service UID 및 PVC/PV/service spec, 기존 PV handle→actual Disk ID·10GiB,
Environment ARM resource ID 집합을 대조했다. 보호 credential/PAT/clone/kubeconfig/ACR auth/ephemeral kubelogin/full traceback/helper를 제거했다.
전용 kubeconfig만 사용했고 port-forward는 만들지 않았다. Azure CLI login·shared local base/cache는 유지한다.
P9-owned cleanup이며 전체 Environment/물리 cache/fixture records zero-residual claim은 아니다.

Before/final two-RG ActualCost는 **KRW44,295.3701043718**
(20261028 KRW30,259.1340498108 + 20261029 KRW14,036.236054561)다.
이전7차 aggregate KRW38,284.28956189241와 준비/원복 **누적8회**를 보존한다.
Shared/delayed billing으로 **P9 incremental actual unknown**이며 before/final 같은 값은 비용0 proof가 아니다.
계획 USD5/누적 검토USD10은 hard billing cap이 아니고 reset하지 않았다.
Pod≤4, requests/limits 각각 CPU≤1500m·memory≤2048Mi, run≤600초, drain60초/rollback30분과
Environment **2026-10-30 10:30 KST**·Foundation/Bootstrap **2026-10-31 00:33 KST**를 유지했다.
추가 compute/Disk/PVC/DNS·retention 변경/전체 teardown은 없다.

## Evidence와 검증

[execution](execution.json), [comparison](comparison.json), [validation](validation.json), [incident](../../incidents/p9-mitigation-eighth.md),
[raw archive](raw-evidence.tar.gz)·[index](raw-index.json)를 연결한다.
Archive **127 members**, SHA256 **`4864a6a5438e6ef48be7cb9b08d862993aadffe9f19974d4ea74573f857e3e0c`**.
Path/size/SHA256, 실제 normal source validator, source/pin/creation order·무재시작 predicate,
CPU poll/Warning history, 원복20비교, known credential/private-path scan, 과거7개 archive byte 보존을 검증했다.
Unchanged implementation/P6–P8 전체 실험은 수동 반복하지 않았다. Final evidence HEAD의 CI는 GitHub exact-head checks로 별도 확인한다.
추가 source 수정이나 제9차 자동 실행은 하지 않는다. 다음 판단은 이 timeline의 독립 검토와 새 exact-source 통합 승인 대상이다.
실제 CPU preparation 완료→healthy shared-path/target telemetry→KEDA/scaler auth→calibration/freeze→C0–C3 recovery gate는 남아 있다.
Draft 유지, merge/P10 없음이며 기존 환경은 P11 재사용을 위해 보존했다.
