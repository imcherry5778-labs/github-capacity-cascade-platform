# Azure environment source — P5-W3

이 stack은 bootstrap이 만든 environment Resource Group 안의 paid runtime infrastructure만 소유한다.
현재는 **implemented / static verified** 대상이며 Azure backend/provisioning/runtime은 **not verified**다.
Lifecycle/RBAC/managed capability/observability contract는 [`docs/architecture.md`](../../../docs/architecture.md#7-azure-control-plane)를 따른다.

Forgejo, Argo CD, ingress routing object, workload ServiceAccount/SecretProviderClass, OTel Collector,
Key Vault secret, experiment fixture는 이 stack에 없다. 후속 P5-W4가 아래 output을 소비한다.

## Remote state / authentication

`bootstrap local state → foundation remote state → environment remote state` 순서다. Backend는 `azurerm`,
state key는 `environment.tfstate`로 고정하고 foundation과 같은 OIDC/Entra ID 경계를 사용한다.
Source에는 `use_oidc=true`, `use_azuread_auth=true`, `lookup_blob_endpoint=false`, `use_cli=false`, `use_msi=false`만 둔다.
Account/container/tenant/client는 bootstrap `backend_config` output에서 runtime으로 전달하며 commit하지 않는다.

```sh
terraform init \
  -backend-config="storage_account_name=<backend_config.storage_account_name>" \
  -backend-config="container_name=<backend_config.container_name>" \
  -backend-config="tenant_id=<backend_config.tenant_id>" \
  -backend-config="client_id=<backend_config.client_id>"
```

Provider도 GitHub Actions `environment: azure` job의 OIDC token만 사용한다. Client secret/certificate, storage access key,
SAS token, CLI/MSI fallback은 없고 Resource Provider 자동 등록은 `resource_provider_registrations="none"`이다.
이번 work unit에는 Azure workflow, `id-token: write`, 실제 token exchange가 없다.

## Inputs / decision maturity

실제 값은 commit하지 않는 local/CI input으로 전달한다. Variable validation은 형식과 정적 invariant만 검사하며,
값이 Azure에서 사용 가능하거나 충분하다는 증거가 아니다.

| Input | 상태 | 비고 |
| --- | --- | --- |
| `subscription_id`, `tenant_id`, `ci_client_id`, `resource_group_name` | bootstrap output | `resource_group_name`은 `resource_group_names.environment` |
| `key_vault_id` | foundation output | `key_vault.id`. Vault를 참조만 한다 |
| `location` | DEFERRED | 단일 region |
| `kubernetes.version`, `kubernetes.istio_revision` | REVALIDATE | 후보 `1.36` / `asm-1-30`. 선택 region에서 확인 전에는 후보일 뿐이다 |
| `kubernetes.sku_tier` | DEFERRED | `Free` 또는 `Standard` |
| `kubernetes.system_node_pool` | DEFERRED | VM SKU/count. 측정 전 capacity baseline이 아니다 |
| `kubernetes.api_server_authorized_ip_ranges` | DEFERRED | 빈 set이면 IP 제한 없음(Entra ID 인증은 유지) |
| `network` | operator input | VNet/subnet/pod/service CIDR. 중첩/범위/형식 validation |
| `postgresql.version/sku_name/storage_mb` | DEFERRED | compute/storage SKU |
| `postgresql.database_name/administrator_login` | operator input | reserved name 거부 |
| `postgresql.administrator_password_version` | operator input | rotation 때만 증가 |
| `postgresql_administrator_password` | secret runtime input | `ephemeral`/`sensitive`, write-only 전달 |
| `container_registry_sku` | DEFERRED | `Basic` 또는 `Standard`만 허용 |
| `monitoring.*` | DEFERRED | retention/stream/interval/Grafana major version |
| `names` | operator input | PostgreSQL/ACR/Grafana는 전역 고유 이름 |

Paid deployment 전에 선택 region에서 다음 공식 조회 결과가 필요하다.
현재 source는 region별 availability를 확인하지 않았다(**not verified**).

```sh
az aks get-versions --location <location> -o table
az aks mesh get-revisions --location <location> -o table
```

## Explicitly managed inventory

Resource 28개. Module, data source, Kubernetes/Helm provider, AzureAD provider는 없다.
Resource Group, Key Vault 및 그 secret/key/certificate/access policy, DNS public record는 만들지 않는다.

| Area | Terraform address | 역할 |
| --- | --- | --- |
| Network | `azurerm_virtual_network.this` | 단일 VNet |
| Network | `azurerm_subnet.aks_nodes` | AKS node subnet (Azure CNI Overlay node IP) |
| Network | `azurerm_subnet.postgresql` | `Microsoft.DBforPostgreSQL/flexibleServers` delegated subnet |
| Network | `azurerm_subnet.private_endpoints` | private endpoint 전용 subnet |
| Key Vault | `azurerm_private_dns_zone.key_vault` | `privatelink.vaultcore.azure.net` |
| Key Vault | `azurerm_private_dns_zone_virtual_network_link.key_vault` | zone ↔ VNet link |
| Key Vault | `azurerm_private_endpoint.key_vault` | foundation vault `vault` subresource + DNS zone group |
| PostgreSQL | `azurerm_private_dns_zone.postgresql` | `<server>.private.postgres.database.azure.com` |
| PostgreSQL | `azurerm_private_dns_zone_virtual_network_link.postgresql` | zone ↔ VNet link |
| PostgreSQL | `azurerm_postgresql_flexible_server.this` | private access server |
| PostgreSQL | `azurerm_postgresql_flexible_server_database.application` | application database 하나 |
| AKS | `azurerm_user_assigned_identity.aks_control_plane` | cluster control-plane identity |
| AKS | `azurerm_user_assigned_identity.aks_kubelet` | kubelet(image pull) identity |
| AKS | `azurerm_kubernetes_cluster.this` | 단일 region cluster + managed capability |
| Registry | `azurerm_container_registry.this` | project-built image registry |
| RBAC | `azurerm_role_assignment.aks_subnet` | 아래 RBAC 표 |
| RBAC | `azurerm_role_assignment.aks_kubelet_operator` | 아래 RBAC 표 |
| RBAC | `azurerm_role_assignment.aks_acr_pull` | 아래 RBAC 표 |
| RBAC | `azurerm_role_assignment.grafana_monitor_workspace` | 아래 RBAC 표 |
| Logs | `azurerm_log_analytics_workspace.this` | Container Insights / Application Insights 저장소 |
| Logs | `azurerm_monitor_data_collection_rule.container_insights` | `ContainerInsights` extension DCR |
| Logs | `azurerm_monitor_data_collection_rule_association.container_insights` | AKS ↔ DCR |
| Metrics | `azurerm_monitor_workspace.this` | Managed Prometheus destination |
| Metrics | `azurerm_monitor_data_collection_endpoint.prometheus` | Prometheus ingestion DCE |
| Metrics | `azurerm_monitor_data_collection_rule.prometheus` | `Microsoft-PrometheusMetrics` DCR |
| Metrics | `azurerm_monitor_data_collection_rule_association.prometheus` | AKS ↔ DCR |
| Metrics | `azurerm_dashboard_grafana.this` | Azure Managed Grafana Standard, API key 비활성 |
| Tracing | `azurerm_application_insights.this` | workspace-based selected-tracing destination |

DCR/DCRA 구성은 Microsoft 공식 onboarding template
([Managed Prometheus](https://github.com/Azure/prometheus-collector/tree/main/AddonTerraformTemplate),
[Container Insights](https://github.com/microsoft/Docker-Provider/tree/ci_prod/scripts/onboarding/aks/onboarding-msi-terraform))를
최소 형태로 따른다. Prometheus recording/alert rule group, dashboard, SLO rule, alarm은 만들지 않는다.

## Network / connectivity

- VNet 하나에 책임별 subnet 셋. 모든 subnet은 `default_outbound_access_enabled=false`이며 NSG/route table/NAT Gateway/Firewall/Application Gateway가 없다.
- AKS는 Azure CNI Overlay다. Pod/service CIDR은 VNet 밖이며 VNet 및 서로와 겹치지 않음을 variable validation이 거부한다.
- PostgreSQL subnet은 최소 `/28`. Azure는 첫 server 생성 시 WAL archive용 `Microsoft.Storage` service endpoint를 이 subnet에 추가하므로
  source에 선언해 drift 제거를 막는다([Azure PostgreSQL private access](https://learn.microsoft.com/en-us/azure/postgresql/network/concepts-networking-private)).
- PostgreSQL은 delegated subnet + linked private DNS zone만 사용하고 `public_network_access_enabled=false`다. 같은 server에 private endpoint를 만들지 않는다.
- Key Vault data plane은 private endpoint + `privatelink.vaultcore.azure.net` zone group으로만 해석된다. Foundation vault의 public access는 꺼진 그대로 둔다.

### Outbound / public endpoint

Private DB와 Key Vault 경로가 있다고 AKS egress 전체가 private한 것은 아니다.

- AKS node egress는 `outbound_type=loadBalancer`의 Standard Load Balancer outbound rule과 node resource group의 managed public IP로 나간다.
- Node bootstrap과 managed add-on(Istio, KEDA, Key Vault CSI, Azure Disk CSI, Azure Monitor agent) image/control-plane 의존성:
  `mcr.microsoft.com`/`*.data.mcr.microsoft.com`, `management.azure.com`, `login.microsoftonline.com`, AKS API server FQDN,
  OS package/node image endpoint, Azure Monitor ingestion/configuration endpoint
  ([AKS outbound rules](https://learn.microsoft.com/en-us/azure/aks/outbound-rules-control-egress)).
- ACR Basic/Standard는 private link가 없으므로 image pull은 public registry endpoint에 Entra ID 인증으로 접근한다.
- Forgejo image registry와 GitOps source(GitHub) 접근도 public egress다. Exact 대상은 W4가 소비하는 source에 따라 정해진다.
- AKS API server는 **public managed endpoint**다(private cluster 아님). Kubernetes 인증은 Entra ID, 인가는 Azure RBAC이며 local account/admin certificate는 꺼져 있다.
  GitHub-hosted runner 경로를 위해 IP 제한은 optional input이다. 이 endpoint는 application HTTPS ingress와 별개다.
- Application HTTPS ingress는 managed Istio external ingress gateway가 만드는 public Load Balancer IP다. Routing object, DNS record, TLS는 W4 범위다.
- Managed Grafana endpoint와 Azure Monitor/Log Analytics ingestion/query endpoint는 public endpoint이며 Entra ID 인증을 사용한다.

## AKS managed capability

| Capability | Source | 상태 |
| --- | --- | --- |
| Managed identity | user-assigned control-plane + kubelet identity | static verified |
| OIDC issuer / Workload ID | `oidc_issuer_enabled`, `workload_identity_enabled` | static verified. Workload identity/federated credential은 W4 |
| Managed Istio | `service_mesh_profile` `mode=Istio`, `revisions=[input]`, external ingress gateway만 | revision/region **not verified** |
| Managed KEDA | `workload_autoscaler_profile.keda_enabled` | KEDA version은 AKS minor가 결정. ScaledObject/threshold는 experiment 범위 |
| Key Vault CSI | `key_vault_secrets_provider` (rotation off) | SecretProviderClass/identity binding은 W4 |
| Azure Disk CSI | `storage_profile.disk_driver_enabled=true`, file/blob driver off | snapshot controller는 AKS 기본값 |
| Container Insights / Managed Prometheus | `oms_agent`(MSI auth) + `monitor_metrics` + DCRA | ingestion **not verified** |

Upgrade는 operator action으로만 한다(`automatic_upgrade_channel` 미설정, `node_os_upgrade_channel="None"`).
Managed Istio add-on은 cluster auto-upgrade를 따라가지 않으며, 자동 node image 교체가 controlled experiment confounder가 되지 않게 한다.

[Istio add-on 공식 문서](https://learn.microsoft.com/en-us/azure/aks/istio-about) 2026-09-17 revision과
[support policy](https://learn.microsoft.com/en-us/azure/aks/istio-support-policy) 2026-09-11 revision 기준:

- `asm-1-30`은 AKS 1.32–1.37과 compatible로 표기되며 expected EOL은 2027-01이다. Regional rollout은 [AKS release status](https://releases.aks.azure.com/)와 `az aks mesh get-revisions`가 authority다.
- **Blocked**: `ProxyConfig`, `WorkloadEntry`, `WorkloadGroup`, `IstioOperator`, `WasmPlugin` custom resource. Ambient, multi-cluster, Gateway API(ingress/GAMMA)도 미지원이다.
- **Allowed but support-limited**: `EnvoyFilter`. 이 사용에서 생긴 문제는 add-on support 범위 밖이다. MeshConfig는 일부 field만 supported다.
- Ingress gateway는 annotation/`externalTrafficPolicy`만 customization 가능하며 port/protocol 변경은 지원하지 않는다.
- P4 shared-gate path(`ext_authz` extension provider, `Sidecar` connection pool, proxy stat)의 managed support 분류는 아직 runtime 검증 전이다(**not verified**).

KEDA add-on은 Metrics Server/Operator resource/Helm value 변경을 지원하지 않고 cluster 안의 유일한 external metrics server여야 한다
([KEDA add-on](https://learn.microsoft.com/en-us/azure/aks/keda-about)). 같은 workload를 HPA와 ScaledObject가 동시에 제어하지 않는다.

## PostgreSQL credential

- `administrator_login`과 write-only `administrator_password_wo`, `administrator_password_wo_version`을 사용한다.
- Password input은 `ephemeral=true`, `sensitive=true`다. Write-only 값은 plan/state에 저장되지 않는다
  ([Terraform write-only arguments](https://developer.hashicorp.com/terraform/language/manage-sensitive-data/write-only)).
  Mock test는 plan에서 `administrator_password`와 `administrator_password_wo`가 모두 null임을 검사한다.
- Rotation은 새 password와 함께 `administrator_password_version`을 올려서만 적용한다. 같은 version으로 password만 바꾸면 Azure에 반영되지 않는다.
- Output은 FQDN, database 이름, administrator login만 노출한다.
- 이 credential은 **초기화용**이다. Forgejo 전용 DB role/password 생성, Key Vault 저장, CSI/Workload ID 소비는 W4의 승인된 경로가 소유한다.
  이 stack은 SQL을 실행하지 않고 application user를 만들지 않는다.
- Infrastructure source가 있어도 database가 application-ready라는 뜻은 아니다.

## Identity / RBAC

Bootstrap CI identity의 권한(state container `Storage Blob Data Contributor`, foundation/environment RG `Contributor` +
`Role Based Access Control Administrator`)은 변경하지 않는다. Subscription-wide 권한을 새로 요구하지 않는다.
이 stack이 만드는 role assignment는 4개이며 모두 environment RG 안의 resource scope다.

| Principal | Role | Scope | 필요 이유 |
| --- | --- | --- | --- |
| `aks_control_plane` identity | `Network Contributor` | `aks-nodes` subnet | BYO subnet에 node/LB를 붙인다 |
| `aks_control_plane` identity | `Managed Identity Operator` | `aks_kubelet` identity 하나 | Kubelet에 pre-created identity를 할당한다 |
| `aks_kubelet` identity | `AcrPull` | ACR | Node image pull. Cluster 생성 전에 부여한다 |
| Grafana system-assigned identity | `Monitoring Data Reader` | Azure Monitor workspace | Grafana Prometheus data source 조회 |

생성하지 않는 것:

- Workload identity, federated identity credential, Key Vault data-plane role: W4.
- AKS Kubernetes data-plane role(`Azure Kubernetes Service RBAC *`): local account가 꺼져 있으므로 CI/operator의 cluster 접근은 W4가 principal/scope를 정해 environment RG 안에 부여해야 한다.
- Grafana user role(`Grafana Admin/Viewer`): 사람 principal은 commit하지 않으며 사용 전 별도로 부여한다.
- ACR push role: 현재 [ACR role 문서](https://learn.microsoft.com/en-us/azure/container-registry/container-registry-rbac-built-in-roles-overview)는
  `RBAC Registry Permissions` mode의 push에 `AcrPush`를 권장한다. CI의 RG `Contributor`가 data-plane push를 포함하는지는 **not verified**다.
  Image push workflow를 만드는 work unit이 push principal을 정하고 environment RG 안에서 `AcrPush`를 부여한다.

Cross-RG dependency: Key Vault private endpoint 연결 승인은 foundation vault의 `privateEndpointConnectionsApproval` action이 필요하며,
bootstrap이 CI에 준 foundation RG `Contributor`가 이를 포함한다. 실제 effective RBAC는 **not verified**다.

## Planned managed side effects

아래 resource는 Terraform이 explicit하게 소유하지 않지만 Azure가 위 resource 때문에 만든다. Terraform state/destroy가 직접 보장하지 않는다.

| Side effect | 원인 | RBAC / cost / cleanup 의미 |
| --- | --- | --- |
| AKS node resource group (`MC_<rg>_<cluster>_<location>` 기본) | AKS | VMSS/OS disk, Standard LB, outbound public IP, Istio ingress public IP, add-on identity(KV CSI 등), PV managed disk. AKS RP가 소유하며 cluster 삭제 시 함께 제거된다 |
| Azure Monitor workspace managed resource group (`MA_<workspace>_<location>_managed`)과 default DCE/DCR | Monitor workspace 생성 | Project RG 밖이다. CI RG-scoped 권한으로 직접 관리하지 않으며 workspace 삭제 뒤 잔존 여부를 확인한다 |
| `NetworkWatcherRG` / Network Watcher | Region의 첫 VNet 생성 시 Azure 자동 활성화(subscription 설정에 따름) | Project RG 밖. 비용은 기본적으로 없지만 residual candidate다 |
| AKS add-on 내부 identity와 role assignment | Istio/KEDA/KV CSI/Monitoring add-on | Node RG 안에서 AKS가 관리한다. Inventory는 runtime에서 확인한다 |
| PostgreSQL subnet `Microsoft.Storage` service endpoint | 첫 server 생성 | Source에 선언되어 drift로 제거되지 않는다 |

## Billable services

Final price/quota는 이 PR에서 정하지 않는다. W4 aggregate paid-run preflight가 current price/quota와 함께 산정한다.

| Service | Billing dependency |
| --- | --- |
| AKS control plane | `kubernetes.sku_tier` |
| AKS node | `system_node_pool.vm_size` × `node_count` × 시간 + OS disk |
| Standard Load Balancer / public IP | outbound IP, Istio external ingress IP, rule/data processed |
| Managed disk (PV) | W4 PVC size/tier |
| PostgreSQL Flexible Server | `sku_name` compute 시간 + `storage_mb` + backup storage |
| Container Registry | `container_registry_sku` 일 단위 + storage |
| Log Analytics / Container Insights | ingestion GB(`container_insights_streams`, interval) + retention |
| Application Insights | 같은 Log Analytics ingestion/retention |
| Azure Monitor workspace | Prometheus sample ingestion/query |
| Azure Managed Grafana | Standard instance 시간 + active user |
| Private Endpoint / Private DNS | endpoint 시간 + data processed, zone 수 + query |
| Bandwidth | internet egress |

## Resource Provider registration

자동 등록이 꺼져 있고 CI identity는 RG-scoped라 등록할 수 없으므로, paid-run 전에 subscription에서 등록 상태를 확인한다.
`Microsoft.ContainerService`, `Microsoft.Compute`, `Microsoft.Network`, `Microsoft.ManagedIdentity`, `Microsoft.DBforPostgreSQL`,
`Microsoft.ContainerRegistry`, `Microsoft.KeyVault`, `Microsoft.OperationalInsights`, `Microsoft.Insights`, `Microsoft.Monitor`,
`Microsoft.AlertsManagement`, `Microsoft.Dashboard`, `Microsoft.Storage`(PostgreSQL service endpoint).
AlertsManagement provider는 이 stack이 alert rule을 만들지 않아도 Managed Prometheus onboarding prerequisite다
([AKS monitoring prerequisites](https://learn.microsoft.com/en-us/azure/azure-monitor/containers/kubernetes-monitoring-enable?tabs=terraform#prerequisites)).

## Lifecycle / cleanup

Creation order:

```text
bootstrap (local state) → foundation (DNS zone, Key Vault) → environment (이 stack) → W4 platform
```

Environment destroy 전에 제거할 platform resource:

- W4가 만든 Kubernetes `LoadBalancer` Service, PVC/PV(특히 reclaim policy `Retain` disk), Argo CD Application/namespace
- Key Vault에 W4가 만든 secret과 workload role assignment(foundation vault는 남는다)
- Application data/DB backup이 필요하면 destroy 전에 coordinated backup을 끝낸다

Destroy order:

```text
W4 platform → environment → foundation → bootstrap
```

Environment를 먼저 지워야 foundation vault의 private endpoint connection이 정리된다.
Bootstrap state/backend/trust는 후속 stack 정리와 state 보존 확인이 끝날 때까지 유지한다.

Residual candidates (destroy 성공이 부재를 증명하지 않는다):

- `Retain` PV managed disk, AKS node resource group 잔존
- Azure Monitor workspace managed resource group/DCE/DCR, `NetworkWatcherRG`
- PostgreSQL deleted-server backup retention
- Log Analytics workspace soft-delete(이름 재사용 충돌 가능)
- Foundation Key Vault soft-delete(7일, purge는 CI 권한 밖)
- Public DNS delegation/record(W4 이후)

### Backup boundary

P3 coordinated backup은 `pg_dump`/application-data tar 결과를 operator 측 workspace로 stream한다(`scripts/local-recover.sh`).
Azure에서도 같은 contract를 private network 안의 helper pod와 Kubernetes API stream으로 적용할 수 있으므로,
W3는 별도 backup Storage Account/container/private endpoint를 만들지 않는다. PostgreSQL native backup/PITR은 DB recovery layer일 뿐이다.
P7이 durable off-cluster backup destination을 요구하면 별도 reviewable capability로 추가한다. Backup job/실행은 없다.

## Static validation

```sh
make terraform-static
make static
```

`scripts/terraform-verify.sh`가 bootstrap/foundation과 같은 방식으로 fresh temp copy, empty CLI config, credential-free environment에서
`fmt -check -recursive`, `init -backend=false -input=false -lockfile=readonly`, `validate`, `test`를 실행한다.
Test는 [mock provider](https://developer.hashicorp.com/terraform/language/tests/mocking)와 `command=plan`만 사용한다.
Positive contract 2개와 negative 11개(subnet 중첩/VNet 밖 subnet/pod CIDR 중첩/`/29` DB subnet/service CIDR 밖 DNS IP/
malformed CIDR/Key Vault가 아닌 ID/Premium ACR/non-managed Istio revision/reserved DB admin/짧은 password)를 검사한다.
Source guard는 exact inventory, OIDC-only backend/provider, credential 부재, private PostgreSQL, write-only password,
Key Vault 참조 전용, AKS managed capability, ACR admin 비활성, role assignment 4개, non-secret output을 검사하고,
대표 위반을 주입한 mutation이 guard에 거부되는지 확인한다.
Provider pin은 bootstrap/foundation과 같은 Terraform `1.16.4` / AzureRM `5.7.0`이며 `.terraform.lock.hcl`은 foundation과 동일하다.
2026-10-13 upstream latest는 Terraform `1.16.5`, AzureRM `5.9.0`이지만 5.8.0/5.9.0 changelog에 W3 필요 변경이 없어 pin을 유지했다.

Mock validation은 runtime proof가 아니다.

## Not verified

Remote backend 인증/locking, GitHub OIDC token exchange, Azure plan/provisioning, region의 AKS version/Istio revision/SKU availability,
quota/capacity, Resource Provider 등록, managed add-on runtime 동작과 Istio customization 분류, AKS egress,
PostgreSQL private DNS resolution/connectivity, Key Vault private endpoint 승인/resolution, Container Insights/Prometheus ingestion,
Grafana 조회, effective RBAC propagation, managed side effect 실제 inventory, cost, destroy/residual cleanup.
