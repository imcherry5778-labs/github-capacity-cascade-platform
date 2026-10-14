# P5 aggregate paid-execution preflight

P5-W4는 source/static 검증만 수행한다. 이 문서는 P6 paid gate의 단일 aggregate checklist이며
실제 Azure execution 승인이나 완료 evidence가 아니다. 2026-10-14 기준 region/account/quota/
operator principal/final hostname은 제공되지 않았으며 **not verified**다.
Deploy order는 `bootstrap → foundation → environment → platform → runtime validation`,
cleanup order는 `platform → environment → foundation → bootstrap`다.

## Infrastructure / ownership — DECIDED

Explicit inventory는 owning source에 있다. 복사된 inventory를 별도로 운영하지 않는다.

| Stack / owner | Source inventory | Lifecycle |
| --- | --- | --- |
| bootstrap | [12 resources](../infra/terraform/bootstrap/README.md#planned-inventory--ci-scope): three RG boundaries, state backend, CI identity/OIDC/RBAC | 마지막 제거; local state 보호 |
| foundation | [2 resources](../infra/terraform/foundation/README.md#planned-inventory): public project DNS zone, private/RBAC Key Vault | 장기 shared; parent authority는 external |
| environment | [34 resources](../infra/terraform/environment/README.md#planned-inventory): W3 28 + W4 identity/FIC/RBAC 6 | short-lived PAYG; fourth stack 없음 |
| platform operator | [ownership table](../platform/azure/README.md#source--ownership): Core/cert-manager bootstrap, namespaces/RBAC, TLS, managed monitoring config, project A record | platform cleanup |
| Argo | Forgejo chart + `platform/azure/stable`; `forgejo` namespace만 | self-heal ON / prune OFF |
| cert-manager | ACME account Secret, CertificateRequest/Order/Challenge, `aks-istio-ingress/forgejo-tls` | issuer/certificate controller lifecycle |
| Azure RP | [implicit inventory](../infra/terraform/environment/README.md#planned-managed-side-effects) | AKS node RG/VMSS/OS disk/LB/IP/PV/add-on identity; Monitor `MA_*` RG/default DCE/DCR; possible NetworkWatcherRG |
| external operator | parent NS delegation/registrar authority | 이 source에서 registrar/parent zone을 변경하지 않음 |

Experiment-owned fixture/namespace는 stable Argo ownership 밖이다. Managed ingress Deployment/Service,
Istio/KEDA/CSI lifecycle과 controller installation을 Argo로 이관하지 않는다.
Snapshot/backup/state, retained disk, soft-deleted vault, DNS delegation은 explicit resource deletion과
별도로 inventory한다. Implicit resource의 개수/이름/잔존은 **not verified**다.

## Capability / availability

| Item | Maturity | P6 execution 전에 필요한 evidence |
| --- | --- | --- |
| Region/subscription/tenant | DEFERRED / not verified | 승인된 actual account/region, constraints, naming availability |
| AKS `1.36` / `asm-1-30` | REVALIDATE | 문서 compatibility는 일치하나 region selection이 아님; `az aks get-versions`, `az aks mesh get-revisions`의 region/tier별 current output + selected patch |
| Node SKU/count, control-plane Free/Standard | DEFERRED | VM family vCPU/total regional vCPU, SKU restrictions/zone capacity, node addon/Forgejo/producer headroom |
| PostgreSQL version/SKU/storage | DEFERRED | region SKU/tier/vCPU/storage min/max/IOPS/backup constraints와 current capacity; application baseline은 측정 전 미확정 |
| VNet/subnet/pod/service CIDR | REVALIDATE | non-overlap, private DNS link, delegated PostgreSQL subnet ≥ /28, node/IP/max-pod/PE headroom, required public egress |
| Resource Provider registration | REVALIDATE | environment [RP list](../infra/terraform/environment/README.md#resource-provider-registration)와 subscription 상태 대조; source의 auto-registration은 OFF |
| Provider operation quotas | not verified | AKS clusters/node pools/LB/rules/public IP/disk/PE/DNS/PG/ACR/Monitor/Grafana 및 identity/FIC/role-assignment count |
| Public HTTPS hostname / delegation | DEFERRED | existing project zone, parent authority 승인, observed NS chain/A resolution, ingress actual IP |
| Admission/schema/effective access | not verified | managed namespaces/CRDs, controller readiness, scoped RBAC deny/allow, private endpoints |

Microsoft [release compatibility policy](https://learn.microsoft.com/en-us/azure/aks/istio-support-policy)는
`asm-1-30`의 AKS `1.36` compatibility를 포함한다. Regional availability/actual managed patch는
문서 표만으로 확인할 수 없다. Explicit selected revision과 actual control-plane/proxy imageID를
P6 evidence에 기록한다. No quota request/region API/token exchange는 P5에서 수행하지 않는다.

### Managed-capability matrix — REVALIDATE

`allowed`는 Azure support 범위 밖이며 `supported`와 구분한다.
Active policy/CUSTOM의 classification은 문서화된 API/blocked list를 토대로 한 보수적 inference이며
특정 field의 managed admission/runtime 보장은 **not verified**다. P4 Local PASS를 근거로 올리지 않는다.

| Capability | Classification | Evidence | Runtime validation required |
| --- | --- | --- | --- |
| Stable HTTPS ingress | supported | Microsoft [secure gateway](https://learn.microsoft.com/en-us/azure/aks/istio-secure-gateway); external selector, credential namespace `aks-istio-ingress` | P6: TLS/SDS/route/native auth/developer E2E |
| External authorization | allowed; CUSTOM admission not verified | Microsoft [MeshConfig](https://learn.microsoft.com/en-us/azure/aks/istio-meshconfig) `extensionProviders=Allowed`; [blocked CR list](https://learn.microsoft.com/en-us/azure/aks/istio-about); upstream [CUSTOM API](https://istio.io/latest/docs/reference/config/security/authorization-policy/) | P6/P8: selected revision admission, fail-closed, generated ext_authz/header/body exclusion |
| Active-request capacity policy | allowed (inference); field admission not verified | [managed Sidecar reference](https://learn.microsoft.com/en-us/azure/aks/istio-meshconfig) + [upstream inboundConnectionPool](https://istio.io/latest/docs/reference/config/networking/sidecar/); no Microsoft field-level support claim | P6/P8: Sidecar admission, actual inbound maxRequests/config and overflow behavior |
| Proxy stat exposure | allowed | Microsoft [MeshConfig](https://learn.microsoft.com/en-us/azure/aks/istio-meshconfig) `defaultConfig.proxyStatsMatcher=Allowed` | P6/P8: matcher admission, actual stats/counters and managed scrape visibility |
| Selected routing API | supported | Microsoft [classic ingress](https://learn.microsoft.com/en-us/azure/aks/istio-deploy-ingress) and secure gateway: `networking.istio.io/v1beta1` Gateway/VirtualService | P6: served API/schema, 443 route/native auth |
| Telemetry | default envoy logging / managed Prometheus supported; tracing allowed | Microsoft [Telemetry API](https://learn.microsoft.com/en-us/azure/aks/istio-telemetry), `v1`, asm ≥ 1-22 | P6/P7: actual logs/metrics/traces classified separately |
| Forbidden controller/custom resource overrides | blocked | [managed limitations](https://learn.microsoft.com/en-us/azure/aks/istio-about): ProxyConfig CR, WorkloadEntry/Group, IstioOperator, WasmPlugin | 사용 안 함; required feature blocked면 stop/report |

Gateway API alternative는 [dedicated Microsoft guide](https://learn.microsoft.com/en-us/azure/aks/istio-gateway-api)에서
Managed Gateway API installation + asm ≥ 1-26을 요구한다. Overview에는 여전히 미지원 설명이 있어
문서 불일치를 남긴다. 추가 capability 없이 충족하는 classic 경로를 선택한다(DECIDED).
Second ingress/self-managed Istio, managed gateway Deployment/Service mutation은 없다.
P8에 필요한 support-limited 옵션이 admission에서 거부되면 fallback을 자동 구현하지 않는다.

## Version / source provenance — REVALIDATE

| Component | 2026-10-14 source selection/evidence |
| --- | --- |
| Forgejo | official release `v15.0.9`, rootless OCI index `sha256:caf1bca332f95cdcf124227a4bfa3b49bbbfbbc8a5e4a97406921cb581165413`; existing v15 LTS track 유지 |
| Forgejo chart | official OCI `17.1.7`, digest `sha256:f5044e73361f5991978f1bc281a570bf893fd0f468e7d76274a7853eb27428cf`; actual schema/render로 Azure persistence/SA contract 검사 |
| Argo CD Core | existing `v3.5.3`, commit `c9c369efcc5b2a0bd720803f8d14a1c3eaddf579`; core-install SHA256 `1a87025d8eb2eae621653fd312fb9ca51df1b4b3b6992a030e3a9ef38e45c448` 재조회 |
| cert-manager | official release `v1.21.2`, chart OCI digest `sha256:634dce9c13b56677a2c05e2ab76c312d0be2664022d5dd05815da67e1fd5f610`; [1.21 Kubernetes compatibility](https://cert-manager.io/docs/releases/) includes 1.36 |
| Terraform/AzureRM | existing exact `1.16.4` / `5.7.0`; credential-free init/validate/mock test, committed lockfile 유지 |
| Managed Istio/Envoy | actual managed patch/build/imageID/stat mapping **not verified**; Local `1.30.5`를 Azure pin으로 복사하지 않음 |
| Deployment Git SHA | DEFERRED; actual merged source commit을 P6 input으로 선택, clean exact checkout + ancestry/render 확인 |

Official Forgejo [release](https://code.forgejo.org/forgejo/forgejo/releases/tag/v15.0.9),
[chart source](https://code.forgejo.org/forgejo-helm/forgejo/src/tag/17.1.7/values.yaml),
[Argo source](https://github.com/argoproj/argo-cd/blob/c9c369efcc5b2a0bd720803f8d14a1c3eaddf579/manifests/core-install.yaml),
[cert-manager release](https://github.com/cert-manager/cert-manager/releases/tag/v1.21.2)가 authority다.
Pinned release를 현재 latest라고 일반화하지 않는다. P6 직전 security/support changes를 재검증한다.

## Cost model — REVALIDATE / amounts not verified

각 line은 승인 region/currency의 PAYG SKU/meter/unit/quantity/time/rate/effective date와 pricing URL을
남겨 `rate × billable units`로 계산한다. Hourly line은 approved run hours `H`, long-lived line은
retention hours/days `R`, data line은 expected volume과 post-run actual volume을 구분한다.
Monthly minimum/rounding/free allowance/region 차이를 확인하기 전 단순 hourly proration을 하지 않는다.
[Azure calculator](https://azure.microsoft.com/en-us/pricing/calculator/)와
[Retail Prices API](https://learn.microsoft.com/en-us/rest/api/cost-management/retail-prices/azure-retail-prices)를
pricing source로 사용하고 current subscription offer/tax/exchange rate는 별도 확인한다.

| Cost line | SKU / quantity required | Time / usage | Confidence needed before approval |
| --- | --- | --- | --- |
| AKS system VM + OS disk | chosen Linux VM SKU × node_count; OS disk tier/GB/node | H + provisioning/cleanup margin | region PAYG meter, documented addon/controller requests로 low/high headroom estimate |
| AKS control plane | chosen Free/Standard, 1 cluster | H, actual tier billing unit | SKU rate/free qualification 확인 |
| LB / public IP | Standard LB 1 + outbound/ingress IP actual count, rules | H + data processed GB | implicit inventory와 network SKU/rule meter 확인 |
| Forgejo PV | `managed-csi`, one RWO PVC, input Gi → actual disk tier/rounded capacity | H/R; PVC delete 후 residual도 포함 | CSI provisioned tier/rounding/reclaim/retained snapshot actual inventory |
| PostgreSQL compute | chosen Flexible Server SKU/tier/vCPU, 1 server | H; stop 상태 storage도 별도 | region/SKU rate/availability 확인 |
| PostgreSQL storage/backup | input storage_mb, IOPS/tier, backup footprint/retention | GB-month/IOPS/retention R | included backup allowance와 restore/retained backup charge 확인 |
| ACR | Basic/Standard, 1 registry, artifact GB | H/R + storage/bandwidth | SKU day/minimum billing와 extra storage 확인 |
| Log Analytics/Container Insights | PerGB2018, 1 workspace; streams/interval/retention input | ingestion GB, retention R | low/high volume estimate, allowance/retention meter 확인 |
| Managed Prometheus | 1 Monitor workspace | collected samples/query processing, H | scrape target/sample cardinality/query demand estimate; stat enablement 비용 포함 |
| Managed Grafana | W3 Standard, 1 instance, selected major | H/R, users/plan meter | region availability와 instance minimum billing 확인 |
| Application Insights | workspace-based 1 resource | ingestion GB/retention, H/R | logs/traces overlap 중복 billing 여부; trace path unknown을 0 비용으로 단정하지 않음 |
| Private Endpoint / DNS | KV PE 1; private DNS 2 zones + links | H, processed GB, queries, R | PE/data/DNS zone/query meters 확인 |
| Bandwidth | ingress/egress/inter-region/registry download | GB by path | traffic estimate + zone/region free allowances 확인 |
| State / public DNS / Key Vault | bootstrap state storage chosen tier/replication, zone 1, Standard KV 1 | GB/operations/queries + R | run 후 long-lived retention와 soft-delete 비용 조건 확인 |
| Residual / recovery assets | retained disks/snapshots/backups/log retention/managed RG | R 또는 until removal | final inventory와 actual billed cost 재대조 |

Amount/confidence는 아직 **not verified**다. Final monthly bill/available quota를 제시하지 않는다.
Approved same-day budget은 low/high estimate + cleanup margin + retained-resource exposure를 포함해야 한다.

## Security / operational gate

| Principal | Role / exact scope | Reason / lifecycle owner |
| --- | --- | --- |
| bootstrap CI identity | existing container `Storage Blob Data Contributor`; foundation/environment RG each `Contributor` + `Role Based Access Control Administrator` | W1 trust/state/IaC; bootstrap owner, 범위 변경 없음 |
| `forgejo_secrets` UAMI | `Key Vault Secrets User` / existing foundation vault ID 하나 | mounted secret read, exact `system:serviceaccount:forgejo:forgejo-secrets`; environment owner |
| `cert_manager` UAMI | `DNS Zone Contributor` / foundation public zone ID 하나 | DNS-01 TXT records, exact `system:serviceaccount:cert-manager:cert-manager`; environment owner |
| Argo controller SA | cluster discovery/read + SSAR; explicit `forgejo` Role | stable reconciliation; operator bootstrap owner, no cluster-wide write |
| Trusted P6 operator | temporary `Azure Kubernetes Service RBAC Cluster Admin` / environment AKS ARM ID 하나; install 시간만, 완료 직후 제거; no Terraform permanent grant | Core/cert-manager install and namespace/Role bootstrap; actual principal/effective privilege **not verified**, existing approved access 없으면 P6 stop |
| Trusted initialization operator | temporary `Key Vault Secrets Officer` / existing vault 하나, plus W3 initial PostgreSQL admin login | private secret initialization/DB role only; P6 operator records/removes assignment and rotates admin password before steady state |
| Trusted observation operator | `Monitoring Data Reader` / Monitor workspace, `Log Analytics Reader` / LAW, `Grafana Viewer` / Grafana instance | runtime signal checks; actual principal/access **not verified**, use-time scoped grants only |

CI의 기존 environment RG Contributor는 control-plane credential retrieval action을 포함하므로
중복 Cluster User role를 추가하지 않는다([Contributor actions](https://learn.microsoft.com/en-us/azure/role-based-access-control/built-in-roles/general)).
이 control-plane role는 Kubernetes data-plane bootstrap authorization을 대신하지 않는다.

Temporary grants are P6 approval/review duties, not new persistent Terraform identities.
새 UAMI assignment는 [Azure new-service-principal guidance](https://learn.microsoft.com/en-us/azure/role-based-access-control/role-assignments-template#new-service-principal)와
[AzureRM 5.7.0 role assignment schema](https://github.com/hashicorp/terraform-provider-azurerm/blob/v5.7.0/website/docs/r/role_assignment.html.markdown)에 따라
`principal_type=ServicePrincipal` / `skip_service_principal_aad_check=true`를 사용한다.
이는 replication-time lookup 경계의 source 설정이며 actual effective access는 **not verified**다.
Subscription Owner/Contributor/User Access Administrator, permanent AKS Cluster Admin, workload/CI
Secrets Officer 권한을 추가하지 않는다. Project RG 밖 권한이 필요하면 stop/report한다.
Kubernetes RBAC escalation에 필요한 bootstrap privilege가 없는 operator는 임의 broad role을 만들지 않는다.
Temporary operator assignments도 teardown inventory에 포함하고 completion 전에 제거한다.

2026-10-14 GitHub read-only API에서 immutable Environment subject와 `azure` main-only branch policy,
required reviewer/wait/custom protection 부재가 W1 snapshot과 일치함을 확인했다.
이 설정은 Azure cost approval gate가 아니다. Azure workflow/OIDC token 권한을 추가하지 않는다.
P6는 [W1 trust inspection](../infra/terraform/bootstrap/README.md#inspected-github-trust)을 재조회한다.

P6 gate는 API Entra-only access/authorized IP path, identity issuer/subject/audience/role propagation,
Key Vault private DNS/mount sync/key presence, dedicated role privileges and password matching,
delegation/A record/TLS trust/native auth/anonymous denial/SSH disabled를 actual evidence로 확인한다.
[Secret/DB ordering](../platform/azure/README.md#secret-startup--rotation)의 실패는 rollout stop이다.
Developer E2E는 P3 operation/attempt boundary를 보존하고, coordinated backup는 DB + full application
data + secret/version manifest를 같은 write boundary에서 확보한다. Fresh restore + doctor + same
credential/session/DB/filesystem developer E2E 전에는 recovery success를 주장하지 않는다.

### Observability maturity

Logs/metrics ingestion source는 [platform source](../platform/azure/README.md#observability-source와-evidence-경계)와
W3 DCR/Grafana integration을 연결한다. 실제 Forgejo/Envoy/PG/node logs/metrics query 결과는 **not verified**다.
P6/P8 mechanism preflight에는 actual managed proxy config/stat inventory, active overflow와 rejection mapping,
HAProxy queue/errors, app checks, client impact, restart/pressure/DB exhaustion을 같은 window로 대조할 방법이 필요하다.
Healthy developer test와 credential/body exclusion 전 reliability experiment를 시작하지 않는다.

Configuration-only [Collector ingestion source](../platform/azure/tracing-collector.json)는
OTLP → upstream azuremonitor exporter + runtime env reference다. Source와 actual trace evidence는
각각 **not verified**이며 stable Application은 Collector를 설치하지 않는다.
Collector runtime version/digest/credential ownership의 확정은 **DEFERRED**다. [Managed tracing](https://learn.microsoft.com/en-us/azure/aks/istio-telemetry)은
allowed but unsupported이며 Forgejo가 verified trace source를 제공한다는 증거가 없다.
Native Azure OTLP는 [preview prerequisite](https://learn.microsoft.com/en-us/azure/azure-monitor/containers/kubernetes-open-protocol)와
Istio mTLS 제한이 있어 W3에 없는 add-on/feature registration을 자동 도입하지 않는다.
Upstream Azure Monitor Collector exporter는 beta이며 Microsoft 지원을 보장하지 않는다.
추가 exporter credential/collector lifecycle의 선택을 구현 편의로 확정하지 않는다.
이 config를 runtime에 활성화하려면 verified trace source, credential-free review와 별도 승인 gate를 충족해야 한다.

## Deployment / teardown — DECIDED order, runtime not verified

P6 explicit approval 전에 current cost/quota/RBAC + exact source commit을 검토한다. 그 뒤:

1. Bootstrap local-state source → backend/CI trust/three RG boundaries.
2. Foundation remote state → project zone/private vault. Parent delegation은 external authority의 별도 승인 action.
3. Environment remote state → private network/PG/AKS/observability/identities/FIC/roles.
4. Platform operator: verify private access → DB role/KV initialization → render exact merged source →
   namespaces, scoped Core bootstrap/controller RBAC, cert-manager Helm/issuer/certificate,
   monitoring config, approved project A record → Argo Application.
5. Runtime validation: producer sync/key presence → Forgejo readiness → HTTPS/native auth/developer E2E →
   logs/metrics → coordinated backup/fresh restore. Trace absence는 별도 not verified로 기록한다.

Default same-day teardown과 24h 초과 별도 승인은 AGENTS.md를 따른다. Actual destroy는 P5에서 없다.

1. Platform: stop autosync, quiesce writers/flush, 필요한 coordinated backup·secret-version metadata 보존;
   Application 삭제에 cascade finalizer가 없으므로 owned resource를 명시 제거한다. Gateway/VirtualService/Telemetry,
   Forgejo Deployment와 producer/SPC/SA/CSI Secrets를 exact ownership 확인 뒤 제거한다.
   Cert-manager Certificate/Issuer 및 cert-owned Secret/Order/Challenge/account key와 controller/CRD bootstrap을
   shared consumer 부재 확인 뒤 제거한다. Managed ingress Deployment/Service를 직접 지우지 않는다.
2. PVC/PV: chart `helm.sh/resource-policy=keep`와 prune OFF 때문에 retained claim을 명시 inventory한다.
   PVC→PV reclaim policy→disk/snapshot ID를 기록하고 approved retention 또는 deletion을 확인한다.
   Project A record와 challenge TXT를 정리하고 parent delegation은 external owner에게 확인한다.
3. Environment: TF-owned identities/FIC/role assignments/private connectivity/AKS/PG/ACR/observability를 정리한다.
   AKS node RG/LB/IP/PV disk와 Monitor-managed RG/default DCE/DCR 잔존을 확인한다.
   PG PITR/backup retention 및 exports의 비용/삭제 경계를 확인한다. 삭제 성공만으로 zero residual claim 금지.
4. Foundation: project records/delegation 필요성 확인 후 DNS zone/vault를 정리한다. KV는 provider purge/recover
   OFF, soft-delete 7일이며 이름 재사용/exceptional purge는 W2 boundary를 따른다.
5. Bootstrap: downstream state/locks와 evidence 보존 후 CI trust/identity/RG RBAC/state container/account,
   final three RG boundaries를 제거한다. Temporary operator assignments를 별도 확인한다.
6. Finalization: project/managed RG, public IP/LB/disk/snapshots, PG backups, ACR, Monitor/LAW/Grafana/AppInsights,
   DNS delegation/records, KV deleted-vault, identity/FIC/RBAC/state backend inventory + actual costs를 대조한다.
   승인된 retained resources는 owner/expiry/expected cost를 남기고 zero residual로 표시하지 않는다.
