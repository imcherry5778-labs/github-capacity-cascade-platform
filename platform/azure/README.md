# Azure stable source — P5-W4

Source/render는 credential-free다. 실제 deploy, identity token exchange, secret sync,
SQL, DNS, certificate issuance와 traces는 **not verified**이며 P6 승인 실행에서 확인한다.
Paid execution의 단일 gate는 [P5 aggregate preflight](../../docs/p5-preflight.md)다.

## Deployment-time input / exact source

`scripts/render-azure-platform.py INPUT.json .generated/azure`는 JSON output만 쓴다.
INPUT은 repository 밖의 non-secret operator metadata이며 다음 **모든** string field가 필요하다.

| Field | Authority |
| --- | --- |
| `source_revision` | P6에서 actual GitHub merged commit으로 선택한 lowercase full 40-character SHA |
| `hostname`, `dns_zone` | foundation public apex zone 아래 final HTTPS hostname / apex zone 이름 |
| `subscription_id`, `tenant_id`, `foundation_resource_group` | approved bootstrap metadata |
| `key_vault_name` | foundation Key Vault output |
| `forgejo_secrets_client_id`, `cert_manager_client_id` | environment `platform_identities` output |
| `postgresql_fqdn`, `database_name` | environment PostgreSQL output; role는 `forgejo` |
| `pvc_size` | cost approval된 positive integer Gi; Azure Disk `managed-csi` |
| `istio_revision` | region에서 확인한 environment AKS revision |
| `ingress_ip` | managed external ingress Service의 actual public IPv4; 추측값 금지 |
| `acme_email`, `acme_environment` | operator contact; explicit `staging` 또는 `production` |

Branch/abbreviated SHA, out-of-zone hostname, private ingress IP, password/token 필드는 거부한다.
CLI는 clean checkout `HEAD == source_revision`, local `origin/main` ancestry를 요구한다.
P6는 먼저 fresh fetch와 actual GitHub merge state를 독립 확인한다. Local ancestry 검사는
remote source authority를 대체하지 않는다. P5에는 배포 revision이 없고, PR HEAD를 pin하지 않는다.
Static fixture의 full SHA는 parser/render 검증용이며 배포 가능한 merged-source 증거가 아니다.

DNS input 예시는 `dns_zone=example.com`, `hostname=forgejo.example.com`이며 실제 domain은 local/CI input으로만 전달한다.
기존 validation은 hostname이 `.` + zone으로 끝나는 하위 이름인지 확인하므로 apex zone도 지원한다.
`dns-record.json`은 zone `example.com` 안의 상대 A record `forgejo`를 지정하고 ingress IPv4/TTL 300을 담는다.
DNS-01은 같은 apex 이름을 `azureDNS.hostedZoneName`으로 사용한다
([cert-manager AzureDNS contract](https://cert-manager.io/docs/configuration/acme/dns01/azuredns/)).
Zone apex 자체를 Forgejo hostname으로 사용하는 것은 현재 contract 밖이다.
Registrar delegation/rollback은 external operator 소유이며 renderer는 이를 실행하지 않는다.
Platform A/TXT cleanup과 Azure zone 삭제는 [DNS apex delegation gate](../../docs/p5-preflight.md#dns-apex-delegation-gate)를 따른다.

## Source / ownership

| Source / rendered output | Owner |
| --- | --- |
| `argocd/kustomization.yaml` | operator bootstrap; exact upstream Core + narrow controller cluster read RBAC |
| `argocd/forgejo-rbac.json`, `namespaces.json` | operator bootstrap; `forgejo` namespace write Role, three project namespaces |
| `argocd-application.json` | operator bootstrap; in-cluster SA authentication, AppProject/Application |
| `cert-manager-values.json` | operator Helm bootstrap `oci://quay.io/jetstack/charts/cert-manager` `v1.21.3` (CRDs 포함; version/digest authority는 `versions.env`) |
| `tls.json` | operator-owned ClusterIssuer + Certificate in existing `aks-istio-ingress`; Secret/account key는 cert-manager |
| `stable/` + common/Azure Forgejo values | Argo-owned `forgejo` namespaced resources |
| `mesh-config.json` | operator-owned revision-specific managed shared ConfigMap; safe access-log format |
| `monitoring.json` | operator-owned managed Prometheus scrape ConfigMap; `kube-system` |
| `dns-record.json` | operator-owned planned project A record request; explicit approved DNS action 필요 |
| `postgresql-role.sql` | temporary operator DB initialization; Azure/SQL 실행 기능 없음 |

Argo는 Forgejo, application SA, CSI SPC/producer, classic Gateway/VirtualService, namespaced
Telemetry만 관리한다. AppProject는 GitHub repository와 Forgejo chart 두 source, in-cluster
`forgejo` destination, 9개 namespaced kind만 허용하고 cluster resource를 허용하지 않는다.
Core bootstrap의 default wildcard ClusterRole을 cluster discovery/read + SelfSubjectAccessReview로
교체한다. Explicit in-cluster Secret의 `namespaces=forgejo`, `clusterResources=false`와
`resource.respectRBAC=strict`는 namespace Role을 보조한다. Token을 Secret에 저장하지 않는다.
Upstream Core의 Redis는 control plane dependency다. Forgejo application cache dependency가 아니다.
Managed Istio/KEDA/CSI와 ingress Deployment/Service, cert-manager installation, experiment는
Argo 대상이 아니다. Automated sync/self-heal ON, prune OFF; teardown은 operator가 수행한다.

## Secret startup / rotation

Key Vault의 `forgejo-admin-username`, `forgejo-admin-password`, `forgejo-db-password` 값은
P6에서 초기화한다. CSI가 생성할 Kubernetes Secret contract는 기존 `forgejo-admin`
(`username`, `password`)와 `forgejo-db` (`password`)를 유지한다.

1. Environment FIC/RBAC와 private DNS/data-plane reachability를 확인한다.
2. Dedicated DB role를 초기화하고 동일 application password를 Key Vault에 저장한다.
3. Argo wave `-20`: `forgejo`, `forgejo-secrets` ServiceAccount와 SPC를 생성한다.
4. Wave `-10`: 별도 `forgejo-secrets` Deployment가 CSI volume을 mount한다.
   Producer에는 `secretKeyRef`, envFrom, synced Secret volume이 없어 startup cycle이 없다.
5. Producer mount가 동기화를 유발한다. Wave `0` Forgejo init은 non-optional
   `forgejo-db`/`forgejo-admin` reference가 채워지기 전에는 실행되지 않는다.
   P6는 Secret의 key 존재만 확인하며 값을 출력하지 않고 readiness를 bounded wait한다.

SPC 자체가 Secret을 생성한다고 가정하지 않는다. Producer는 sync된 Secret의 지속 ownership을
위해 platform lifetime 동안 유지한다. 마지막 mount Pod가 사라지면 sync Secret이 삭제될 수 있다
([CSI sync lifecycle](https://secrets-store-csi-driver.sigs.k8s.io/topics/sync-as-kubernetes-secret)).
Forgejo chart `17.1.7`의 init에서 DB/admin Secret을 먼저 요구하므로 독립 producer가 필요하다.
Helm extra CSI mount만 추가하는 것으로 startup/order 증명을 대신하지 않는다.
Producer는 pin된 기존 Forgejo rootless image의 shell/sleep만 쓰며 writer/general sync controller가 아니다.
Forgejo SA는 Azure identity/token 권한이 없다. Producer SA만 Key Vault read identity를 사용한다.

W3 rotation은 OFF다. Rotation은 P6/P7의 coordinated maintenance로 명시 실행하며
database password → KV version → producer 재생성/동기화 → Forgejo controlled restart →
같은 credential developer E2E 순으로 검증한다. 중간 실패 시 새 version을 성공처럼 기록하지 않는다.
Runtime artifact에는 Secret **값** 대신 name/key/version metadata만 보존한다.

## Database initialization

W3 administrator password는 ephemeral/write-only이고 SQL role는 생성하지 않는다.
추가 secret broker나 administrator credential 저장소 없이 같은 승인된 operator session이
private network에서 initial password로 접속한다. Login identity/operator ownership와
대상 `current_database()`/server FQDN을 먼저 확인하고 shared DB에서는 중단한다.

`postgresql-role.sql`은 존재하지 않는 제한 role만 생성하고 기존 privileged role면 중단한다.
Dedicated DB의 CONNECT, `public` schema USAGE/CREATE만 부여한다. Forgejo가 직접 생성한
table/sequence의 owner이므로 migration 권한을 가지며 server admin/다른 DB 권한을 주지 않는다.
기존 object가 다른 role 소유이면 임의 broad GRANT/ownership 변경 없이 중단한다.

초기 password 설정은 [psql `\password`](https://www.postgresql.org/docs/current/app-psql.html)의
interactive hidden prompt를 사용한다. SQL literal, CLI argument, shell history/debugging,
query echo/log, Terraform input/state와 CI artifact로 password를 전달하지 않는다.
Key Vault 입력은 operator가 검증한 private client에서 RAM-backed 0600 transient file를
`az keyvault secret set --file … --output none`에 전달하고 즉시 제거한다. 실제 secret write 권한은
아래 preflight의 temporary operator duty이며 CI/workload에 `Secrets Officer`를 상시 부여하지 않는다.
임시 RAM/file cleanup 또는 private reachability를 보장할 수 없으면 실행하지 않는다.
Admin password는 이번 초기화 session 뒤 W3 write-only version을 증가시켜 rotate하고
session memory를 폐기한다. Application password의 장기 authority는 기존 Key Vault다.

Role 생성/privilege 설정은 반복 가능하다. Password 설정/rotation은 별도 explicit action이고
DB/KV 사이의 atomic operation을 주장하지 않는다. 초기화 완료 전에 Forgejo startup을 허용하지 않는다.
DB role/login·schema ownership·KV version 일치와 forbidden cross-DB access는 P6 검증 대상이다.

## TLS / certificate permission

Microsoft [secure gateway](https://learn.microsoft.com/en-us/azure/aks/istio-secure-gateway)의
credential namespace는 `aks-istio-ingress`다. Certificate도 이 existing namespace에 두어
cert-manager가 `forgejo-tls`를 만들게 한다. Gateway object는 `forgejo`에서 managed external
selector를 가리키며 `credentialName=forgejo-tls`를 사용한다. Managed gateway resource는 수정하지 않는다.
cert-manager가 Secret을 같은 Certificate namespace에 생성하는
[Certificate contract](https://cert-manager.io/docs/usage/certificate/)를 사용한다.

ClusterIssuer ambient authentication만 ON, namespaced Issuer ambient authentication OFF.
DNS solver는 Workload Identity와 zone 하나의 DNS Zone Contributor를 사용한다.
`selector.dnsNames`는 routing selector이며 certificate authorization boundary로 해석하지 않는다.
Chart의 aggregateClusterRoles를 OFF로 하며 project CI/Argo/app SA에 Certificate,
CertificateRequest, Issuer, Order, Challenge write/approval 권한을 주지 않는다.
Trusted operator만 issuer/certificate 생성 권한을 가진다. Arbitrary namespace의 cert-manager
API create 권한을 추가하면 다시 검토해야 한다. P6는 unauthorized principal의 이 API들에 대한
`can-i` deny 및 managed namespace admission/certificate readiness/renewal을 확인한다.
Private key/ACME account key는 controller-generated Kubernetes Secret이며 Git에 없다.
Staging certificate를 production-trusted HTTPS 성공으로 보고하지 않는다.

## Observability source와 evidence 경계

Forgejo console log → W3 Container Insights DCR/Log Analytics, explicit Forgejo `/metrics`
및 Envoy `/stats/prometheus` scrape → W3 Monitor Workspace → 기존 Grafana integration을 사용한다.
Public VirtualService는 `/metrics`를 404로 차단한다. Dashboard/alert/controller는 추가하지 않는다.
Bootstrap `mesh-config.json`은 status/detail/duration/cluster만 기록하며 credential/body/path/query를 제외한다.
P3 logical operation/attempt/correlation/structured outcome/monotonic latency boundary는
[local operation contract](../../docs/local-operations.md)를 유지한다. Infrastructure HTTP metrics만으로
developer operation 성공률/latency를 만들지 않는다. Correlation ID를 metric label로 만들지 않는다.

Configuration-only `tracing-collector.json`은 OTLP receiver → upstream `azuremonitor` exporter의
최소 traces pipeline source다. Connection string은 runtime env reference만 있고 값/credential은 없다.
이 config는 Argo Application/Bootstrap에 포함하지 않는다. Collector image/version/support, verified
source와 connection-string ownership을 P6에서 검토하기 전 deploy/trace generation을 허용하지 않는다.
이 ingestion source도 **not verified**다. Tracing source는 별도 판단이 필요하다. Microsoft managed `tracing.*`는 allowed이며 support 범위 밖이다.
Forgejo internal trace instrumentation/propagation과 ingestion은 **not verified**다. P7 exit에는 tracing이 필수가 아니며 기존 metrics/logs의 actual query와 명시적 correlation이 필요하다. 실행 source·private recovery 절차·승인 경계는 [P7 operations](../../docs/local-operations.md#p7-azure-operations)에 있다.
Application Insights resource 존재만으로 trace evidence를 주장하지 않는다. 지원되는 minimal
Collector ingestion path의 선택/검증 상태는 aggregate preflight에 기록한다.
P4/P8에서는 actual managed proxy build/config/active-overflow stat mapping과 collector visibility,
Forgejo/DB/node health, ext_authz fail-closed/credential exclusion을 확인한 뒤 experiment를 시작한다.
