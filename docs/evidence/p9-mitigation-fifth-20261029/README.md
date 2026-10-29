# P9 제5차 승인 실행 — normal result phase invalid

상태: **operator invocation 설정 오류로 normal gate invalid / P9-owned cleanup 완료 / P9 acceptance 미충족**.
승인·실제 execution source는 `50aac4a9fab0881dfba41340f4a6ef0f5c4e0142`다.
[제5차 통합 승인](https://github.com/imcherry5778-labs/github-capacity-cascade-platform/pull/41#issuecomment-6493316821),
[독립 source review](https://github.com/imcherry5778-labs/github-capacity-cascade-platform/pull/41#pullrequestreview-5695631178),
[source Full Local CI attempt2](https://github.com/imcherry5778-labs/github-capacity-cascade-platform/actions/runs/40845659267/attempts/2)를 확인했다.
실행 동안 implementation/source bytes와 clean HEAD를 유지했으며, 후속 evidence/docs HEAD는 실행 source와 구분한다.

## 실제 실행과 중단

| 항목 | 이번 실행 |
| --- | --- |
| 기존 환경 | 지정 subscription/user/cluster UID, AKS1.36.4·asm-1-30·기존 D4s_v4 node2/autoscaling OFF 확인 |
| Stable/KEDA | Argo Synced/Healthy, Forgejo chart17.1.7/image15.0.11, KEDA2.19.0-25/Ready2, 다른 ScaledObject/ScaledJob0 |
| Image | exact source tag1 build/publish, digest `sha256:2ecf02b0e2a19036de097bb645669dda57ad2fda0020d3f2d07a73d73289e4af`; 종료 시 삭제 |
| Credential | 기존 admin logical version2의 UID/data hash·mounted version 일치 후 승인된 P9 한정 재사용; rotation 없음 |
| Native normal create | invocation1/exit0, developer operations9/attempts9; raw phase=`baseline`으로 structured validator는 invalid |
| 직접 failure | `normal_result_validation / ValueError / invalid phase`; temporary operator가 `RESULT_PHASE=baseline`을 잘못 지정 |
| CPU/healthy | initialize0, CPU preparation0, healthy journey0; 300초/840초 경계를 실제 실행한 결과 없음 |
| Experiment/KEDA | namespace/CUSTOM/shared overlay/DB Secret 생성0, UAMI/FIC/workspace role·SA/operator 변경0, restart0/0 |
| Calibration/freeze/measured | calibration0, freeze 없음, C0/C1/C2/C3 각각0; mitigation/recovery not measured |
| Final normal | 같은 fixture의 native read-only verify1/exit0; create 재실행 없음 |

`tests/e2e/forgejo-developer-journey.sh create`는9개 operation/attempt 성공과 exit0을 기록했다.
그러나 operator가 지정한 phase `baseline`은 `validate-operation-results.py`가 허용하는 `warmup`/`measured`가 아니다.
Raw의 `run_end.validity=valid`는 script의 자기 보고이며, 독립 validator의 `ValueError: invalid phase`를 대신하지 않는다.
이는 **operator 설정 오류**이며 승인 source의 CPU/HPA 결함, Azure metric 지연 또는 native auth 실패로 돌리지 않는다.
Normal gate flag를 승격하지 않았고 initialize/healthy/calibration/measured를 시작하지 않았다.
추가 self-review에서 과거 template를 재사용한 normal context의 kubectl client 기록v1.36.4와
실행 후 로컬 조회v1.37.1의 불일치도 확인했다. `normal-context-review.json`에 post-run 관측으로 남겼고
raw context를 덮어쓰지 않았다. 실행 시 binary hash는 미기록이며 이 관측을 start-of-run attestation으로 승격하지 않는다.
Raw phase를 고치거나 derivative를 성공 proof로 만들지 않았으며 normal create도 재실행하지 않았다.
[실제 invocation 설정](execution.json), [incident/corrective action](../../incidents/p9-mitigation-fifth.md)을 연결한다.

로컬 Docker daemon이 없어 Podman5.8.9로 같은 pinned Dockerfile/base/source를 build/push했다.
Base는 `docker.io/library/python:3.14.7-alpine3.24@sha256:9e9fde4d32eedce0b661d9ab91e826b62dddf28e928c230ec55f1866cac66b01`이다.
전용 user kubeconfig와 checksum을 검증한 ephemeral kubelogin0.2.22를 사용했으며 기본 kubeconfig를 변경하지 않았다.
이 도구 선택은 실험 controller/resource/acceptance 변경이 아니다.

## 안전 원복과 보존

CUSTOM/experiment namespace는 준비 전 중단해 생성하지 않았고 종료 시 부재를 확인했다.
Shared ConfigMap UID/data, KEDA Deployment UID/spec·SA UID/annotations·Ready2,
stable Forgejo Deployment UID/spec와 Argo Synced/Healthy·spec, Secret UID/data hash,
node/PVC/PV/service UID 집합과 Environment ARM resource ID 집합을 대조했다.
PV/PVC spec도 일치하며 existing PV handle과 actual Azure Disk ID·10GiB를 확인했다.
새 node/Disk/PVC·autoscaling/DNS·stable Secret 변경은 없다.

Final native verify1 뒤 PAT **ID16**을 exact ID로 DELETE204/0 bytes, 기존 PAT401·token 목록0을 확인한 후
fixture login을 차단하고 Basic401을 확인했다. Credential 발급 numeric ID와 cleanup HTTP status/bytes는
기존 request helper의 append-only audit에 보존한다. Fixture 계정/repo/Issue/PR 기록은 남긴다.
Live image 참조0·해당 digest의 tag가 승인 source 한 개임을 확인한 뒤 ACR manifest/tag와 local tag를 제거했다.
Shared base/cache는 purge하지 않았다. 소유 AKS-only role을 삭제하고 원래 assignment ID 집합을 확인했다.
즉시 Kubernetes authorization cache 소멸은 측정하지 않았다.
보호 admin/DB/PAT/password/clone/ACR auth/kubeconfig·ephemeral kubelogin·full diagnostic 사본을 제거했고
Azure CLI login은 유지했다. Port-forward는 만들지 않았다.

이는 P9-owned cleanup이며 전체 Environment teardown 또는 fixture/cache zero-residual 선언이 아니다.

## 비용·누적 횟수·기한

Before/final ActualCost는 각각 usage20261028 **KRW30,259.1340498108**와 usage20261029 **KRW4,068.5293715974**,
two-RG 합계 **KRW34,327.6634214082**다. 마지막4차 aggregate KRW26,885.8891798273을 reset하지 않는다.
Final cost 첫 조회는 실패했고 HTTP status는 보존하지 못해 unknown이다. 제한된 재조회1회에서 성공했다.
전후 같은 값은 비용0 proof가 아니며 **P9 incremental actual은 delayed/shared billing 때문에 unknown**이다.
USD5 계획/누적 USD10 검토 기준은 billing hard cap이 아니다. 새 compute 없이 제한된 준비만 진행했고
normal gate invalid 이후 추가 유료 run을 시작하지 않았다.

과거 네 차례 준비/cleanup과 historical KEDA apply restart1/restore restart1을 보존한다.
이번 준비/cleanup을 합쳐 **누적5회**이며, 이번 KEDA mutation/restart는0이다.
Experiment Pod는0, 승인 상한은 Pod≤4·requests/limits 각각 CPU≤1500m·memory≤2048Mi 그대로다.
Environment **2026-10-30 10:30 KST**, Foundation/Bootstrap **2026-10-31 00:33 KST**를 유지한다.
Preparation/run/drain/rollback reserve 경계를 늘리지 않았고 retention 연장/전체 teardown은 없다.

## Evidence와 남은 gate

[Execution](execution.json), [comparison](comparison.json), [raw83 archive](raw-evidence.tar.gz),
[개별 size/SHA256 index](raw-index.json), [검증](validation.json)을 보존한다.
Archive SHA256은 `618ba1357800d547fbebe72fec215908f50a49b030ac438b298373016a4686b7`다.
모든 member의 size/SHA256, 실제 raw의 invalid phase 재현, cleanup 비교와 알려진 credential/private path 검사를 수행했다.
원래 account contact metadata와 모든 보호 credential/traceback/helper 파일은 publication에서 제외했다.
Git 내부 HTTP 등 전체 request 수를 operation/attempt9와1:1로 추정하지 않는다.

승인 source의 CPU300초/initialize840초 계약은 여전히 live positive 미검증이다.
정상 provenance gate→CPU/HPA→single healthy shared-path/target telemetry→KEDA scaler auth/cadence→
calibration/freeze/C0–C3 continuing-demand/recovery gate가 남는다.
재개 시 operator phase는 `warmup`이어야 한다. 이번 invalid 결과를 보존하고 별도 통합 재승인 전 자동 반복하지 않는다.
