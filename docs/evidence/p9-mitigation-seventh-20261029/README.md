# P9 제7차 Azure 실행 — CPU startup Warning 발생 경계 중단

상태: **valid normal·무재시작 Pod 준비 통과 / CPU preparation 실패 / P9-owned 원복 완료 / P9 acceptance 미충족**.

승인·실제 execution source는 **`1ce291523ecddb3918e3879f322e45dfca122ee6`**, main/base는
`3f788a9c1d103f6c07bd403af269133fac287002`다.
[제7차 통합 승인](https://github.com/imcherry5778-labs/github-capacity-cascade-platform/pull/41#issuecomment-6496347488),
[독립 source review](https://github.com/imcherry5778-labs/github-capacity-cascade-platform/pull/41#pullrequestreview-5697341921),
[승인 HEAD CI](https://github.com/imcherry5778-labs/github-capacity-cascade-platform/actions/runs/40865716577)를 확인했다.
실행 중 clean exact source를 유지했다. 이번 commit은 docs/evidence만 추가하며 후속 evidence HEAD를 실행 source로 바꾸지 않는다.

## Actual preparation

첫 external mutation 전에 `RESULT_PHASE=warmup`을 기존 validator 허용값과 대조했다.
실제 선택한 repository `.tmp/bin/kubectl`은 **v1.36.4**, SHA256
`8b8f088da2dab964f853b38464033b1be15ede2839eca751482357c45abdd05a`로 versions.env pin과 일치했고 final check도 같았다.
Absolute local path는 보호 attestation에만 두었다. Live cluster/Argo/runtime imageID와 실제 도구 정보로 fresh context를 만들었다.
Normal create **1회/exit0**, 기존 structured validator **valid/success/warmup, operations9/attempts9**를 확인했다.
Native HTTPS 인증·TLS hostname/certificate 검증과 process-local DNS override를 유지했다. Admin version2는 승인된 범위에서만 재사용했다.

새 image는 `acrccpp6krc57781024.azurecr.io/ext-authz-sim:1ce291523ecddb3918e3879f322e45dfca122ee6`,
registry 대조 digest는 **`sha256:ba914d82d15dd8c11f008e7a1009b375520cfa8bc3e7ce16cb7da795075650bc`**다.
기존 pinned base와 source Dockerfile을 Podman으로 build/publish했다. ACR Tasks/새 compute는 사용하지 않았다.

6차 ordering 오류는 실제로 교정했다. UTC 기준 ConfigMaps `12:26:05/06` → backend Service `12:26:08`
→ target Pod `12:26:12` → target Ready `12:26:27` → **HAProxy Deployment `12:26:33`** 순서다.
Service name/namespace/ClusterIP/selector와 Ready backend EndpointSlice를 HAProxy 생성 전에 확인했다.
Initial HAProxy·target·DB는 모두 Ready/Running, active containers **restart0/last termination null**이었다.
Init status도 restart0/Error·OOM 없음이었다. Pod3의 보수적 admitted 합계는 requests **400m/512Mi**, limits **900m/1024Mi**였다.
그 뒤 CUSTOM을 생성하고 public `initialize`를 1회 호출했다. Pod 교체/history reset이나 guard 완화는 없다.

## Actual CPU negative

| 실제 경계/관측 | UTC / 결과 |
| --- | --- |
| target Pod 생성 / Ready | `12:26:12` / `12:26:27` |
| CPU HPA 생성 | `12:26:13` |
| initialize 시작 | `12:26:59.412445` |
| 첫 CPU poll | pending; sample `12:26:26`, window `12.868623936s`; Ready 전체 window 불충족, HPA ScalingActive false |
| 같은 Warning UID의 이전 관측 | count3, 마지막 발생 `12:27:13` |
| 실패를 일으킨 새 발생 | count5, 마지막 발생 **`12:27:43` = Pod+91초 / HPA+90초** |
| initialize 종료 | `12:27:57.061643`, exit1, 외부 **57.649초** / initializer **52.966초** |
| 실패 stage / public code | `readiness_resource_guard / ValueError / validation_failed` |
| 보호 exception chain에서 확인한 원인 | `CPU warning outside startup lifetime` |

해당 Warning은 exact HPA UID `48aec29f-3df5-49f8-be3a-5e3d6d0f4ef4` 소유의
`FailedGetContainerResourceMetric`, event UID `dc1109fc-9b0d-4b0d-92e5-85825b9e7db9`다.
최초 발생은 `12:26:43`이지만 count·마지막 발생이 실제로 증가했다.
Source는 Pod와 HPA 각각의 생성 후90초 안에 발생한 Warning만 허용한다. 이번 마지막 발생은 Pod 기준91초로 경계를 넘었다.
이는 **현재 시각에서 오래된 retained Warning을 거부한 결과가 아니며**, settling300초나 외부840초 timeout 소진도 아니다.
Warning 삭제·은폐, 발생 허용 확대, initialize/normal 자동 반복 없이 후속 workload를 중단했다.

**CPU poll1/ready poll0, healthy journey intent0/실행0, KEDA mutation0, fault0, calibration0,
freeze 없음, measured C0–C3 각각0**이다. Mitigation·continuing-demand recovery는 모두 **not measured**다.
두 advancing valid CPU sample·quiet interval·healthy target telemetry의 positive proof는 확보하지 못했다.

Post-stop 조회에서 HPA `ScalingActive=True` transition `12:28:43`/currentMetrics2%·1m을 확인했다.
그 뒤 조회한 CPU sample은 timestamp `12:28:32`, window `1m12.279s`, app `355796n`이다.
이는 initialization 종료 후 수집됐으며 sample 수집 시 freshness30초도 넘는다. 준비 성공이나 두 sample proof로 승격하지 않는다.
Initial/post-stop Pod는 같은 UID의 restart0을 유지했다. Failing guard 전체 payload는 source가 emit하지 않아 별도 snapshot으로 가장하지 않는다.

## Cleanup·비용·보존

CUSTOM exact UID/spec 대조 후 우선 제거 → shared ConfigMap UID/applied-data JSON Patch test 원복 →
campaign 소유 namespace/controllers/PodMonitor/HPA/DB Secret/Pods 제거·부재를 확인했다.
Final native read-only verify **1회/exit0** 뒤 PAT18 numeric ID exact DELETE **204/0 bytes**,
PAT **401**, token 목록0, login 차단/Basic401을 확인했다. Fixture account/repo/Issue/PR 기록은 보존한다.
Image spec/imageID live references0·소유 단일 tag 확인 뒤 exact digest/tag와 local tag를 삭제했다. Shared local base/cache는 유지한다.
임시 AKS role의 exact ARM ID/principal/scope를 확인해 DELETE하고 GET not-found·원래 assignment ID 집합 일치를 확인했다.
즉시 Kubernetes authorization cache 소멸은 미측정이다.

KEDA Deployment UID/spec·SA UID/annotations unchanged/Ready2, 이번 apply/restore restart0/0이다.
과거 첫 실행의 apply1/restore1은 유지한다. Stable Forgejo UID/spec, Argo Synced/Healthy·spec,
Secret UID/data hash, node/PVC/PV/service UID 집합·PVC/PV/service spec, 기존 PV handle→Disk ID·10GiB,
Environment ARM resource ID 집합을 대조했다. 보호 credential/PAT/clone/kubeconfig/ACR auth/ephemeral kubelogin/full traceback/helper를 제거했다.
기본 kubeconfig 변경·port-forward 없음, 기존 Azure CLI login 유지다. 전체 environment/물리 cache/fixture record zero-residual claim은 아니다.

Before/final two-RG ActualCost는 **KRW38,284.28956189241**
(20261028 KRW30,259.1340498108 + 20261029 KRW8,025.15551208161)다.
이전6차 aggregate KRW34,327.6634214082를 reset하지 않았다. Shared/delayed billing으로 **P9 incremental actual unknown**이며
before/final 같은 값은 비용0 proof가 아니다. 계획 USD5/누적 검토 USD10은 billing hard cap이 아니다.
준비/원복 **누적7회**, calibration 및 각 measured arm 누적0회다.
Pod≤4, requests/limits 각각 CPU≤1500m·memory≤2048Mi, run≤600초, drain60초/rollback30분과
Environment **2026-10-30 10:30 KST**·Foundation/Bootstrap **2026-10-31 00:33 KST**를 유지했다.
추가 compute/Disk/PVC/DNS·retention 변경/전체 teardown은 없다.

## Evidence와 검증

[execution](execution.json), [comparison](comparison.json), [validation](validation.json), [incident](../../incidents/p9-mitigation-seventh.md),
[raw archive](raw-evidence.tar.gz)·[index](raw-index.json)를 연결한다.
Archive **124 members**, SHA256 **`1eb8d059688fd214ab3dca0452af96d32b07de6cdef82c7b19a28ae6277c5be1`**.
각 path/size/SHA256, 실제 source normal validator, Service 선행/무재시작 predicate, Warning UID/count/발생시각,
원복 비교, known credential/private-path scan, 과거6개 archive hash 보존을 검증했다.
준비 중 local pin/Argo field/hash serialization 조회 실수는 workload 전 교정했고 raw `operator-preparation-notes.json`에 남겼다.
Workload retry/source 수정은 없다. Unchanged implementation/P6–P8 전체 실험은 수동 반복하지 않았다.
최종 evidence HEAD의 Full Local CI/static·CodeQL/Analyze 결과는 GitHub exact-head checks로 별도 확인한다.

다음 실행 전 이번 실제 Warning 발생 이력과90초 발생 허용 계약을 독립 검토해야 한다.
Positive CPU/HPA→single healthy shared-path/target telemetry→KEDA/scaler auth→calibration/freeze→C0–C3 recovery gate는 남아 있다.
이번 실행 안에서 source 수정·자동 paid replay·새 Task/branch/PR을 만들지 않았다. 추가 Azure 실행은 별도 exact-source 통합 승인 대상이다.
Draft 유지, merge/P10 없음이다.
