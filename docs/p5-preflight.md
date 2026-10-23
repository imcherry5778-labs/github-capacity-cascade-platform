# P5 aggregate paid-execution preflight

P5-W4는 source/static 검증만 수행한다. 이 문서는 P6 paid gate의 단일 aggregate checklist이며
실제 Azure execution 승인이나 완료 evidence가 아니다. P5 최초 preflight(2026-10-14)에서 region/account/quota/
operator principal/final hostname은 제공되지 않았다. P6-DNS-APEX는 apex delegation 방식을 확정하며
실제 DNS delegation/runtime 검증은 계속 **not verified**다. 실제 domain/account/naming은 local/CI input으로 전달한다.
Deploy order는 `bootstrap → foundation → environment → platform → runtime validation`,
cleanup order는 `platform → environment → foundation → bootstrap`다.

## Infrastructure / ownership — DECIDED

Explicit inventory는 owning source에 있다. 복사된 inventory를 별도로 운영하지 않는다.

| Stack / owner | Source inventory | Lifecycle |
| --- | --- | --- |
| bootstrap | [12 resources](../infra/terraform/bootstrap/README.md#planned-inventory--ci-scope): three RG boundaries, state backend, CI identity/OIDC/RBAC | 마지막 제거; local state 보호 |
| foundation | [2 resources](../infra/terraform/foundation/README.md#planned-inventory): public apex DNS zone, private/RBAC Key Vault | 장기 shared; registrar authority는 external |
| environment | [34 resources](../infra/terraform/environment/README.md#planned-inventory): W3 28 + W4 identity/FIC/RBAC 6 | short-lived PAYG; fourth stack 없음 |
| platform operator | [ownership table](../platform/azure/README.md#source--ownership): Core/cert-manager bootstrap, namespaces/RBAC, TLS, managed monitoring config, project A record | platform cleanup |
| Argo | Forgejo chart + `platform/azure/stable`; `forgejo` namespace만 | self-heal ON / prune OFF |
| cert-manager | ACME account Secret, CertificateRequest/Order/Challenge, `aks-istio-ingress/forgejo-tls` | issuer/certificate controller lifecycle |
| Azure RP | [implicit inventory](../infra/terraform/environment/README.md#planned-managed-side-effects) | AKS node RG/VMSS/OS disk/LB/IP/PV/add-on identity; Monitor `MA_*` RG/default DCE/DCR; possible NetworkWatcherRG |
| external operator | Gabia registrar NS delegation/rollback | 이 source에서 registrar NS를 변경하지 않음 |

Experiment-owned fixture/namespace는 stable Argo ownership 밖이다. Managed ingress Deployment/Service,
Istio/KEDA/CSI lifecycle과 controller installation을 Argo로 이관하지 않는다.
Snapshot/backup/state, retained disk, soft-deleted vault, DNS delegation은 explicit resource deletion과
별도로 inventory한다. Implicit resource의 개수/이름/잔존은 **not verified**다.

## Capability / availability

| Item | Maturity | P6 execution 전에 필요한 evidence |
| --- | --- | --- |
| Region/subscription/tenant | DEFERRED / not verified | 승인된 actual account/region, constraints, naming availability |
| AKS `1.36` / `asm-1-30` | REVALIDATE | 문서 compatibility는 일치하나 region selection이 아님; `az aks get-versions`, `az aks mesh get-revisions`의 region/tier별 current output + selected patch |
| Node SKU/count, control-plane Free/Standard | DEFERRED | system pool node count는 정수 ≥ 2로 validation; node당 최소 4 vCPU/4 GB, B-series 제외는 [공식 조건](https://learn.microsoft.com/en-us/azure/aks/use-system-pools)에 따라 실제 SKU로 확인. VM family/total regional vCPU quota, region availability, addon/Forgejo/producer headroom은 별도 미검증 |
| PostgreSQL version/SKU/storage | DEFERRED | region SKU/tier/vCPU/storage min/max/IOPS/backup constraints와 current capacity; application baseline은 측정 전 미확정 |
| VNet/subnet/pod/service CIDR | REVALIDATE | non-overlap, private DNS link, delegated PostgreSQL subnet ≥ /28, node/IP/max-pod/PE headroom, required public egress |
| Resource Provider registration | REVALIDATE | environment [RP list](../infra/terraform/environment/README.md#resource-provider-registration)와 subscription 상태 대조; source의 auto-registration은 OFF |
| Provider operation quotas | not verified | AKS clusters/node pools/LB/rules/public IP/disk/PE/DNS/PG/ACR/Monitor/Grafana 및 identity/FIC/role-assignment count |
| Public HTTPS hostname / delegation | DECIDED apex 방식 / runtime not verified | foundation apex zone, Gabia registrar NS 4개 전환 승인, observed NS chain/SOA/A resolution, ingress actual IP; 아래 DNS gate 충족 |
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

## P6-W1 security/version reconciliation — 2026-10-21

위 2026-10-14 표는 P5 source selection의 역사적 기록이다. P6-W1의 현재 pin authority는
`versions.env`와 아래 공식 upstream 재조회다. Azure runtime/support/cost 검증으로 승격하지 않는다.

| Component | P6-W1 결정 / 공식 근거 |
| --- | --- |
| Argo CD Core | `v3.5.3 → v3.5.6`. [GHSA-fmxq-cgp8-87wp](https://github.com/argoproj/argo-cd/security/advisories/GHSA-fmxq-cgp8-87wp)의 3.5.x 영향 범위는 `<3.5.4`다. [v3.5.6 release](https://github.com/argoproj/argo-cd/releases/tag/v3.5.6)는 같은 minor의 수정 patch다. |
| Forgejo | `15.0.9-rootless → 15.0.10-rootless`. [공식 release/support](https://forgejo.org/releases/)에서 v15 LTS는 2027-07-15까지 지원한다. [15.0.10 notes](https://codeberg.org/forgejo/forgejo/src/branch/forgejo/release-notes-published/15.0.10.md)의 Actions fork-event 권한, label ownership/metadata, tag API metadata 보안 수정을 반영한다. Actions disabled만으로 label/API 수정 필요성을 제외하지 않는다. |
| Terraform | `1.16.4 → 1.16.6`. [1.16.5](https://github.com/hashicorp/terraform/releases/tag/v1.16.5)는 tainted-state/resource-identity crash를, [1.16.6](https://github.com/hashicorp/terraform/releases/tag/v1.16.6)는 registry HTTP/2 resource exhaustion `CVE-2026-78669`를 수정한다. Upstream은 compromised registry를 core security 보장 밖 threat로 구분한다. 세 stack의 exact required version과 기존 checksum installer를 함께 적용한다. |
| AzureRM | `5.7.0` 유지. [5.8.0–5.10.0 changelog](https://github.com/hashicorp/terraform-provider-azurerm/blob/v5.10.0/CHANGELOG.md)와 [공개 advisory](https://github.com/hashicorp/terraform-provider-azurerm/security/advisories)를 확인했다. 현재 source에 갱신을 요구하는 security fix는 확인되지 않았다. 아래 관련 변경과 적용 여부를 구분한다. |
| Forgejo chart | `17.1.7` 유지. [official chart release](https://code.forgejo.org/forgejo-helm/forgejo-helm/releases/tag/v17.1.7)와 후속 17.2.0/17.3.0/17.3.1 release를 비교하고 OCI artifact를 다시 받았다. 후속 release의 service label/OAuth mapping/v18 internal-token 변경은 현재 Core와 관련이 없고, 17.3.0의 `15.0.10` default 갱신은 직접 image override로 반영한다. Chart의 default appVersion은 `15.0.9`이나 common `image.tag`와 Azure digest override로 `15.0.10`을 선택한다. Schema/render regression으로 실제 image와 Core contract를 검사한다. |
| cert-manager | `v1.21.2` 유지. [release](https://github.com/cert-manager/cert-manager/releases/tag/v1.21.2), [support matrix](https://cert-manager.io/docs/releases/), [공개 advisory](https://github.com/cert-manager/cert-manager/security/advisories)를 확인했다. 1.21은 Kubernetes 1.36을 포함하며 조회된 advisory 영향 범위에 이 patch는 포함되지 않는다. ACME response/ambient credential 보안 수정은 이미 이 patch에 있다. 실제 AKS admission/DNS-01/renewal은 not verified다. |

Argo [tag ref](https://api.github.com/repos/argoproj/argo-cd/git/ref/tags/v3.5.6)는
`c2b1e3017e2cec86b122172e861dcd026453ae44` commit이다. 해당
[Core manifest](https://raw.githubusercontent.com/argoproj/argo-cd/c2b1e3017e2cec86b122172e861dcd026453ae44/manifests/core-install.yaml)의
SHA256은 `d3d9d3555ad77eb4b6d27b1ec0d2af7978a91537e84d54631f983c227f0a3d31`이다.
Core kind inventory와 Redis `public.ecr.aws/docker/library/redis:8.2.3-alpine` dependency는 이전 pin과 같다.
Local bootstrap과 Azure kustomization은 같은 exact commit을 사용한다. AppProject 제한 우회는
controller RBAC와 별개이므로 기존 narrow Azure RBAC도 유지한다. 공개 advisory 목록의
2026-10-07 repo-server Kustomize/Jsonnet/OCI/SSH 수정도 3.5.4에 포함된다.

Forgejo [official registry tag](https://code.forgejo.org/v2/forgejo/forgejo/manifests/15.0.10-rootless)를
anonymous pull authentication으로 재조회하여 response bytes SHA256과 `Docker-Content-Digest`를 대조했다.

- OCI index: `sha256:6ffebd9ab9ee9f6677e3523fa60debd9de630ff2a226fa681d6cc0c7ba541d77`
- Index의 linux/amd64 manifest: `sha256:2cec77b3181e6e52a4e4d110b2509ef48c0b03f279d520c51bf5731233a8cb18`
- Chart `17.1.7` OCI digest 재조회: `sha256:f5044e73361f5991978f1bc281a570bf893fd0f468e7d76274a7853eb27428cf`
- cert-manager `v1.21.2` chart OCI digest 재조회: `sha256:634dce9c13b56677a2c05e2ab76c312d0be2664022d5dd05815da67e1fd5f610`

Azure renderer의 Forgejo와 CSI producer는 stable tag + TO index digest를 공유한다.
Local normal lifecycle은 values commit `9b4fdb44cc07ea11870730e728b038514e415e29`의 stable tag를 사용한다.
Static은 pinned Git object의 common/local values와 checkout을 byte 비교하여 과거 patch 배포를 거부한다. Upgrade drill은
`15.0.9 → 15.0.10` tag/index/amd64 imageID를 검증한다. [v15 upgrade guide](https://forgejo.org/docs/v15.0/admin/upgrade/)의
full backup/queue/old binary와 newer state 금지를 유지한다. 새 patch notes에는 별도 Core migration이나
PAT/session 재발급 요구가 명시되지 않았다. Runtime continuity는 새 exact-head full Local CI로 별도 판정한다.
기존 P3 `15.0.8 → 15.0.9` evidence는 [역사적 preflight](local-operations.md#official-upstream-preflight-2026-09-30)로 보존한다.
새 preflight raw release-note SHA256은 `15.0.9=6aa9580cab5d0fbfde65a16077d873ba660a9ba2cda9d8e30d37e7af8a02c51c`,
`15.0.10=602db98c853da2b491070e9b1cffed97b3e07b530ff32bf04c8ac7e2904daec1`이며 변경 시 중단한다.

AzureRM 관련 후속 수정 중 AKS minor alias perpetual diff는 P6에서 실제 exact patch 선택 전에
재검토한다. 현재 capability 후보 `1.36`을 deployment 선택으로 간주하지 않는다.
Subnet service endpoint list-order diff(현재 단일 endpoint), Grafana SMTP(미사용),
PostgreSQL `PremiumV22_LRS` storage validation(현재 해당 type 미선택),
StorageV2→Storage kind 변경(현재 고정 StorageV2)은 이 work unit의 갱신 근거가 아니다.
Provider를 유지하므로 세 `.terraform.lock.hcl`은 변경하지 않으며 `init -lockfile=readonly`로 확인한다.
이 검토는 취약점 부재의 포괄적 보장이 아니며 paid 실행 직전 current advisory를 다시 확인한다.

P6-W1은 public upstream/GitHub 조회와 credential-free static/mock/render/Local regression만 수행한다.
Azure subscription/credentialed plan/OIDC exchange/paid resource/DNS/secret action은 범위 밖이다.
P6 후속 gate의 actual account/region/quota/cost/RBAC, exact AKS/managed Istio runtime,
secret/private reachability/TLS/observability와 merged deployment SHA는 계속 **not verified**다.

## DNS apex delegation gate

P6-DNS-APEX(2026-10-23)의 DECIDED 방식은 **Gabia registrar NS → foundation Azure DNS apex zone의
authoritative NS 4개**다. Child zone delegation을 전제하지 않는다. Domain registration은 Gabia에 유지한다.
기존 foundation은 input을 zone 이름으로 그대로 사용하고, renderer는 하위 hostname의 상대 A record와
동일 zone의 DNS-01 hosted zone을 만든다. Resource inventory와 RBAC resource scope는 늘리지 않는다.
`cert_manager`의 `DNS Zone Contributor`는 기존처럼 foundation zone ID 하나에 한정되지만,
그 zone이 apex이므로 apex 전체 record에 권한이 미친다. `selector.dnsNames`를 권한 경계로 해석하지 않는다.

Paid 실행 승인 전에 external DNS operator와 Terraform cleanup operator를 지정하고 다음을 확보한다.

1. Gabia NS 변경 권한, 현재 registrar/TLD delegation 및 authoritative NS/SOA/TTL, existing records와
   Email Routing 의존성, DNSSEC/parent DS 상태를 다시 확인한다. 사전 전달된 계정 상태는 runtime evidence를 대신하지 않는다.
2. Rollback/teardown에 사용할 **유효한 대체 authoritative DNS**와 관리 권한, 필요한 records/의도한 teardown 응답,
   NS 목록을 확정한다. 전환 전에 각 대체 NS의 authoritative SOA/NS 응답을 직접 확인한다.
   기존 Cloudflare nameserver가 계속 유효하거나 같은 값으로 복구 가능하다고 가정하지 않는다.
3. Registrar/TLD NS TTL, zone NS TTL, relevant record/negative TTL과 registrar 처리 시간을 확인하여
   복구·전파 확인을 포함한 same-day cleanup 가능 시간을 산정한다. 대체 DNS, 권한 또는 시간이 미확정이면
   **P6 paid execution blocker**로 보고하고 실행 승인을 진행하지 않는다.

[Gabia 공식 FAQ](https://webtraffic.gabia.com/faq/view.php?category1=&category2=&category3=&keyword=&seqno=3279)는
NS 변경 후 안정화에 1~2일이 걸릴 수 있다고 안내한다(2026-10-23 재확인).
따라서 apex 전환과 복구의 당일 완료는 보장할 수 없으며, 현재 same-day cleanup contract와의 충돌은
**미해결 P6 paid execution blocker**다. 관측 TTL/복구 계획으로 당일 완료 가능성을 검토하거나,
아래 별도 임시 보존 승인을 먼저 받아야 한다. 본 PR은 same-day 기본값을 완화하거나 보존을 승인하지 않는다.

승인된 전환에서 Terraform operator는 생성된 zone의 actual NS 4개를 전달하고 external operator가 Gabia에 설정한다.
Azure authoritative NS 직접 질의와 registrar/TLD delegation chain, 독립 recursive resolver들의 SOA/NS/A 결과를
UTC 시각/TTL과 함께 기록한다. Azure output이나 registrar UI 저장만으로 전환 성공을 선언하지 않는다.
[Azure delegation 지침](https://learn.microsoft.com/en-us/azure/dns/dns-delegate-domain-azure-dns)과
[DNS caching 경계](https://learn.microsoft.com/en-us/azure/dns/dns-faq#how-long-does-it-take-for-dns-changes-to-take-effect)를 참고한다.

Teardown/rollback에서도 external operator가 대체 DNS의 준비 상태를 재확인한 뒤 Gabia NS를 복구한다.
Terraform cleanup operator는 TLD delegation이 대체 NS를 가리키는지, 각 대체 NS의 authoritative 응답과
독립 recursive resolver들의 NS/SOA/필요한 record 응답이 의도한 상태인지 확인한다.
관측한 delegation/cache TTL의 대기 구간과 재질의 결과를 남기며, 전파 미완료/불일치/응답 실패 시
**Azure DNS zone을 삭제하지 않고 cleanup incomplete로 보고**한다. A/TXT record cleanup은 delegation 복구의 대체물이 아니다.

Same-day deadline 전에 gate를 완료할 수 없다면 구체적인 blocker와 잔존 resource를 보고한다.
필요한 임시 보존은 owner, exact resource/state/RBAC 의존성, 보존 기간/expiry, 예상 비용 및 제거 계획에 대한
**별도 explicit approval**을 요구한다. 24시간 초과에는 AGENTS.md의 새 승인 조건도 적용한다.
승인이 없다고 zone을 무조건 삭제하거나 cleanup 성공으로 처리하지 않는다. 가능하고 승인된 다른 cleanup은 진행하되
zone과 그 foundation RG/state/cleanup 권한을 먼저 제거하지 않는다. 실제 복구·전파·zone 삭제는 모두 **not verified**다.

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
2. Foundation remote state → apex zone/private vault. Gabia registrar NS delegation은 위 DNS gate에 따른 external operator의 별도 승인 action.
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
   Project A record와 challenge TXT는 writer/controller 정지 후 exact ownership을 확인해 정리한다.
   External operator가 위 DNS gate에 따라 대체 authoritative DNS로 Gabia NS를 복구하고 결과를 확인한다.
3. Environment: TF-owned identities/FIC/role assignments/private connectivity/AKS/PG/ACR/observability를 정리한다.
   AKS node RG/LB/IP/PV disk와 Monitor-managed RG/default DCE/DCR 잔존을 확인한다.
   PG PITR/backup retention 및 exports의 비용/삭제 경계를 확인한다. 삭제 성공만으로 zero residual claim 금지.
4. Foundation: 위 DNS gate의 delegation 복구/전파 확인이 완료된 뒤에만 DNS zone을 정리한다.
   Gabia NS가 Azure를 가리키거나 전파가 미완료이면 foundation destroy를 실행하지 않고 blocker/보존 승인을 보고한다.
   KV는 provider purge/recover
   OFF, soft-delete 7일이며 이름 재사용/exceptional purge는 W2 boundary를 따른다.
5. Bootstrap: DNS zone이 보존 중이면 foundation RG/state/cleanup 권한을 제거하지 않는다.
   Downstream state/locks와 evidence 보존 후 CI trust/identity/RG RBAC/state container/account,
   final three RG boundaries를 제거한다. Temporary operator assignments를 별도 확인한다.
6. Finalization: project/managed RG, public IP/LB/disk/snapshots, PG backups, ACR, Monitor/LAW/Grafana/AppInsights,
   DNS delegation/records, KV deleted-vault, identity/FIC/RBAC/state backend inventory + actual costs를 대조한다.
   승인된 retained resources는 owner/expiry/expected cost를 남기고 zero residual로 표시하지 않는다.
