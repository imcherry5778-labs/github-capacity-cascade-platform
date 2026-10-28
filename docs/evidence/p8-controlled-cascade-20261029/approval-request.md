# P8-W1 통합 실행 승인 요청

상태: **미승인**. Source 변경을 가진 Draft PR의 최종 보고에 적힌 **exact HEAD**가 승인 대상 source다.
그 SHA의 `scripts/azure-cascade.py`, P4 fixture/ext-authz-sim, P7 journey/operations와
[P8 실행 절차](../../p8-controlled-cascade.md)를 사용한다. 실행·원복 evidence는 같은 branch/PR에 추가한다.
Code 수정으로 SHA가 바뀌면 영향을 받는 검증과 exact source 기록을 갱신한다. 안전/외부 side effect 범위를 확대하지 않는다.

## Target / principal / drift

Subscription `e5a6bc91-44fb-46aa-90ee-badd6d197609`, Korea Central, Resource Group `rg-ccp-environment-krc-p6`의 다음 기존 resource를 재사용한다.

| Resource | 실제 이름 | Owner / 변경 범위 |
| --- | --- | --- |
| AKS | `aks-ccp-krc-p6` | Terraform Environment / 임시 fixture·experiment HPA·policy 및 operator-owned shared MeshConfig만 |
| PostgreSQL | `pg-ccp-p6-krc-57781024` | Terraform Environment / 기존 app DB role의 read-only query만 |
| ACR Basic | `acrccpp6krc57781024` | Terraform Environment / `ext-authz-sim` repository의 새 source-SHA tag와 digest만 |
| Monitor / Log Analytics | `amw-ccp-krc-p6` / `law-ccp-krc-p6` | 기존 query 경로만, 새 pipeline/IAM 없음 |
| Stable Forgejo | `forgejo` namespace / Deployment | Argo / revision·spec·PVC·Secret source 유지, disposable developer fixture 준비·측정만 |
| Shared mesh | `aks-istio-system/istio-shared-configmap-asm-1-30` | P6 operator-owned / 원본 UID/data 보존, P8 overlay 후 원복 |

실행 principal은 Entra User object ID **`6f750efc-cb1a-4a49-b6e7-23fc6061e25a`**다.
[관리 API delta](management-delta.json)는 2026-10-29 00:44 KST에 관측했다.
AKS `Running/Succeeded`, `1.36.4`, managed revision `asm-1-30`, `Standard_D4s_v4` 2개 고정 node,
PostgreSQL `Ready` / version17 / `Standard_D2ds_v5` / 기존 32GiB / HA 없음, ACR Basic을 확인했다.
Core/DSv4 quota는 사용8 / 한도10이며 **새 quota나 node를 사용하지 않는다**.
P7 임시 AKS Cluster Admin assignment는 현재 목록에 없고 기존 Owner assignment 두 개는 유지된다.
P7 임시 Disk 세 개는 없고 기존 Forgejo Disk 하나가 남아 있다.
초기 Disk size projection의 null은 field casing 차이였고 [후속 관리 API read](management-followup.json)의 실제 값은 10GiB다.
ACR storage 사용은 0 / 포함 10GiB로 반환됐다.

Management 관측 범위에서 기존 환경 재사용 후보가 유지된다. 현재 사용자 kubeconfig는 다른 AWS cluster이며 사용하지 않았다.
Actual Argo/workload/mesh owner/data/admission/metrics의 P7 대비 drift는 새 P8 AKS 권한 없이 확인했다고 주장하지 않는다.
승인 직후 **read-only Kubernetes delta gate**에서 이를 확인하며 mismatch/부족 headroom이면 workload mutation 전에 중단한다.
Stable deployed revision은 P7의 `2f63d283ebba12aaed8705732f1206d71ddc33db`를 보존한다.

## 최대 admitted resource / 신규 resource 여부

| Workload | 동시 Pod 수 | 예상 requests (CPU / memory) | 예상 limits (CPU / memory) |
| --- | ---: | ---: | ---: |
| HAProxy, injection OFF | 1 | 50m / 64Mi | 250m / 256Mi |
| ext-authz-sim app | 최대2 | 각50m / 64Mi | 각100m / 128Mi |
| 각 target의 injected/native sidecar | 최대2 | 각100m / 128Mi | 각250m / 256Mi |
| PostgreSQL read-only client helper, injection OFF | 1 | 100m / 128Mi | 100m / 128Mi |
| 예상 합계 | **4** | **450m / 576Mi** | **1050m / 1152Mi** |

승인 요청의 aggregate **상한은 Pod4 / CPU1500m / memory2048Mi**다. Requests와 limits 각각에 적용한다.
추가 injected/init container·native sidecar·Pod overhead도 포함한다.
Namespace ResourceQuota와 실제 admitted Pod 검사 두 경로로 확인하며 sequential init까지 보수적으로 합산한다.
예상보다 주입되는 resource가 많아 상한을 넘거나 두 번째 target을 schedule할 여유가 없으면 실험을 중단한다.
Helper는 하나이며 새 service/controller가 아니다. Client/port-forward는 operator host에서 실행한다.

**신규 node/server/Disk/PVC 없음.** 기존 node autoscaling OFF 유지, DB/SKU/storage/network/DNS 변경 없음.
Target replica는 HPA 1–2 범위지만 calibration/frozen paired run은 actual replica1 및 상한2 여유를 요구한다.
자동 scale이 발생하면 동일 조건 비교나 CPU mismatch proof로 승격하지 않는다.

## Mesh / policy / HPA와 보존·원복

- Revision-specific shared ConfigMap에 `p8-shared-gate` extension provider와 다섯 stat suffix만 merge한다.
  `extensionProviders`/`proxyStatsMatcher`는 Allowed, Microsoft support 밖이다.
  기존 원본 UID/resourceVersion/data·provider 목록을 보호된 사본으로 보존한다.
- `p8-shared-gate` namespace의 fixture/Sidecar/HPA는 experiment-owned다.
  CUSTOM `AuthorizationPolicy` 하나는 실제 external ingress label을 대상으로 `aks-istio-ingress`에 만든다.
  Native auth/TLS verification, fail-closed, body/credential exclusion과 retry0 route/HAProxy를 actual config로 확인한다.
- HPA는 `autoscaling/v2`, app-container CPU `ContainerResource`, requests50m, utilization60%, min1/max2다.
  KEDA/다른 scaling controller를 만들거나 같은 Deployment에 겹치지 않는다.
- Gate 제거를 먼저 수행한 뒤 shared `data`를 원복하고 fixture/HPA/Secret/namespace를 정리한다.
  Stable Deployment/Argo revision·spec/managed controller/default ConfigMap은 수정하지 않는다.
  본 source는 새 target bootstrap에서 matcher를 사용하므로 stable matcher 재기동은 계획하지 않는다.
  기존 ingress의 dynamic provider 수렴이 안 되면 managed controller를 임의 변경하지 않고 보고한다.

## IAM / ACR / credential의 exact scope

이번 P8만을 위한 다음 권한·행동을 요청한다. **P7 승인/예외를 승계하지 않는다.**

1. 위 User에 다음 **AKS resource 하나** 범위의 임시 `Azure Kubernetes Service RBAC Cluster Admin` assignment를 생성하고 종료 시 그 assignment ID만 삭제한다.
   `/subscriptions/e5a6bc91-44fb-46aa-90ee-badd6d197609/resourceGroups/rg-ccp-environment-krc-p6/providers/Microsoft.ContainerService/managedClusters/aks-ccp-krc-p6`
   이유는 namespace 생성/admission 확인, operator-owned shared mesh와 ingress policy, Pod exec/port-forward 및 실제 owner/resource inventory다.
2. 기존 principal의 현재 권한으로 ACR login/publish를 허용한다. 대상은
   `acrccpp6krc57781024.azurecr.io/ext-authz-sim:<approved-source-sha>` 및 이 build가 만든 digest뿐이다.
   Local build를 사용하며 ACR Tasks/new registry는 만들지 않는다. 기존 tag를 덮지 않는다.
   새 ACR IAM은 계획하지 않는다. 실제 publish 권한이 없으면 별도 scope 확대 없이 보고한다.
   정리 시 이 P8-only tag/manifest를 삭제하되 실제 reference가 남거나 공유 digest이면 자동 삭제하지 않는다.
3. `forgejo/forgejo-admin`과 `forgejo/forgejo-db`의 필요한 값만 보호된 operator memory/file에서 읽는다.
   **기존 administrator version2 credential의 P8 한정 재사용·rotation 생략을 이번에 새로 승인 요청**한다.
   목적은 정상/healthy-gate journey용 disposable non-admin 계정 **2개**, 각 private journey repo/Issue/PR과 PAT **총2개** 준비다.
   Administrator를 load에 사용하지 않는다. 기존 stable Secret 값을 변경하지 않는다.
4. DB helper용 `p8-shared-gate/p8-db-read` Secret **1개**에 기존 Forgejo app DB role credential을 임시 복사한다.
   TLS hostname 검증과 default_transaction_read_only를 유지하며 SQL은 read-only다. 새 DB/DB role/PG admin credential 사용은 없다.
   Secret 삭제, PAT exact ID revoke/원래 token의 401 거부, fixture 계정 로그인 차단과 보호 사본 삭제를 확인한다.
   Fixture 기록은 소유 범위의 DB/filesystem delete를 피하기 위해 로그인 차단 상태로 남길 수 있으며 이를 명시한다.

Key Vault IAM/Secret version write, DNS delegation/record 변경, Terraform apply/destroy는 요청하지 않는다.
Monitoring IAM도 새로 만들지 않는다. Existing Owner assignment는 삭제하지 않는다.

## 비용 / 보존 기한

[Retail price 및 planning envelope](retail-price-summary.json)는 기존 node/server/registry 유지비와 P8 증가분을 구분한다.
ACR 추가 저장 0.2GB를 한 달 전부 과금해도 USD0.02,
logs0.2GB × USD3.11/GB = USD0.622,
metric samples10만 × USD0.11/천만 = USD0.0011,
egress1GB × USD0.12/GB = USD0.12,
query/변동 여유 USD1.2369를 합쳐 **P8 증가분 검토 예상 USD2**다.
실측 usage나 보장값이 아닌 planning envelope다. 실제 image/data/telemetry volume과 비용을 기록하고
**USD10 추가 검토 예산**을 넘길 근거가 생기면 계속하지 않는다. Billing hard cap은 아니다.

[ActualCost query](actual-cost-query.json)는 Environment와 node Resource Group의 2026-10-28 비용으로
**KRW9140.01008933979**를 반환했다. 조회 성공과 청구 데이터 완전성은 다르다.
이는 기존 환경 누적이며 P8 추가 실비는 아직 미실행/미확정이고 환율 환산을 주장하지 않는다.
Foundation/Bootstrap 비용은 이 query 범위 밖이며 기존 보존비와 분리한다.

기한 변경은 요청하지 않는다.

- Environment: **2026-10-30 10:30 KST**
- Foundation/Bootstrap: **2026-10-31 00:33 KST**

자동 연장·자동 삭제 없음. 기한 변경이 필요해지면 기존 승인으로 진행하지 않는다.
P11 전 전체 teardown을 제안하거나 수행하지 않는다.

## 소유 cleanup과 완료 확인

P8 CUSTOM policy → shared ConfigMap P8 overlay 원복 → HPA/fixture/DB Secret/namespace → 소유 ACR tag/manifest →
소유 임시 IAM assignment → PAT/fixture login/보호 사본/port-forward 순으로 actual identity를 확인한다.
Policy 제거가 shared mesh 원복보다 먼저다. 원복 중 정상 경로를 우선하며 다른 owner의 변경을 덮지 않는다.

최종 evidence는 정상 HTTPS journey/native auth와 직접 authenticated sentinel, Argo revision/policy/healthy,
원래 stable PVC/PV/Disk/Secret 보존, P8 resource/assignment와 보호 local 사본의 정리 결과를 포함한다.
Raw/negative evidence와 실제 source/runtime/config를 initial incident에 연결한다.
완료 전에는 `restored`, `zero residual`, cascade/HPA/retry hypothesis PASS를 주장하지 않는다.
