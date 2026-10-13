# Azure foundation source — P5-W2

이 stack은 bootstrap이 만든 foundation Resource Group 안의 장기 shared resource만 소유한다.
현재는 **implemented / static verified** 대상이며 Azure backend/provisioning/runtime은 **not verified**다.
Lifecycle/RBAC/DNS/secret contract는 [`docs/architecture.md`](../../../docs/architecture.md#terraform-lifecycle)를 따른다.

## Planned inventory

Resource 2개만 정의한다. Module, data source, AzureAD provider는 없다.

| Resource | 역할 |
| --- | --- |
| `azurerm_dns_zone.project` | parent authority가 나중에 delegate할 project public zone |
| `azurerm_key_vault.project` | 후속 persistent application secret 저장소 |

Resource Group, DNS record, parent NS delegation, Key Vault secret/key/certificate, access policy,
role assignment, managed identity, private endpoint/private DNS, VNet/subnet은 만들지 않는다.
Resource Group은 bootstrap이 소유하며 이 stack은 이름만 input으로 받는다.

## Remote state / authentication

`bootstrap local state → foundation remote state` 순서다. Backend는 `azurerm`, state key는 `foundation.tfstate`로 고정한다.
Source에는 `use_oidc=true`, `use_azuread_auth=true`, `lookup_blob_endpoint=false`, `use_cli=false`, `use_msi=false`만 둔다.
`lookup_blob_endpoint=false`이면 data-plane URI를 account/container 이름으로 만들므로 subscription/resource group lookup이 필요 없다
([HashiCorp azurerm backend](https://developer.hashicorp.com/terraform/language/backend/azurerm)).
Account/container/tenant/client는 bootstrap `backend_config` output에서 runtime으로 전달하며 commit하지 않는다.

```sh
terraform init \
  -backend-config="storage_account_name=<backend_config.storage_account_name>" \
  -backend-config="container_name=<backend_config.container_name>" \
  -backend-config="tenant_id=<backend_config.tenant_id>" \
  -backend-config="client_id=<backend_config.client_id>"
```

Backend와 provider는 모두 GitHub Actions OIDC만 허용한다. CLI/MSI fallback을 끄므로 operator의 개인 Azure session이
CI identity의 RG-scoped 권한 부족을 가리지 않는다. Client secret/certificate, storage access key, SAS token 입력은 없다.
Provider 입력 `subscription_id`, `tenant_id`, `ci_client_id`는 non-secret 값이며 `ci_client_id`는 bootstrap `ci_identity.client_id`다.
GitHub OIDC token은 `environment: azure` job에서 자동으로 찾는다. 이번 work unit에는 Azure workflow가 없다.
Resource Provider 자동 등록은 `resource_provider_registrations="none"`으로 끈다.

Operator inputs: `subscription_id`, `tenant_id`, `ci_client_id`, `resource_group_name`(bootstrap `resource_group_names.foundation`),
`location`, `dns_zone_name`, `key_vault_name`. 실제 domain/account/naming 값은 commit하지 않는다.

## Azure DNS

Parent domain은 기존 registrar/DNS authority에 남는다. 이 stack은 project subdomain public zone만 만든다.
`dns_zone.name_servers` output은 Azure가 zone에 할당한 name server이며 parent authority에 NS delegation을 만들 **입력**이다.
Output이 존재해도 delegation이나 resolution이 완료됐다는 뜻이 아니다. Delegation은 이후 paid gate의 external DNS action이다.

## Key Vault

| 속성 | 값 | 이유 |
| --- | --- | --- |
| `sku_name` | `standard` | HSM-backed key 요구가 없다 |
| `rbac_authorization_enabled` | `true` | Azure RBAC data-plane model. AzureRM 5.7.0에서 required이며 legacy access policy를 쓰지 않는다 |
| `public_network_access_enabled` | `false` | Provider default는 `true`라 명시한다 |
| `soft_delete_retention_days` | `7` | Azure 허용 범위 7–90일의 최소값. 생성 후 변경 불가 |
| `purge_protection_enabled` | `false` | 한번 켜면 끌 수 없고 retention 동안 purge/name reuse를 막는다 |

Public network access가 꺼져 있고 private endpoint가 아직 없으므로 secret data-plane 접근은 **의도적으로 불가능**하다.
Private connectivity는 후속 work unit 범위이며 그 전까지 data-plane reachability는 **not verified**다.
CI identity에는 Key Vault data-plane role을 주지 않는다. 후속 workload access role은 bootstrap이 준
foundation RG `Role Based Access Control Administrator` 범위 안에서 필요할 때 추가한다.

### Destroy lifecycle

[Azure soft-delete 문서](https://learn.microsoft.com/en-us/azure/key-vault/general/soft-delete-overview)에 따르면 vault purge는
subscription owner 또는 `Key Vault Purge Operator` 권한이 필요하다. AzureRM 5.7.0 provider는 기본적으로
destroy 뒤 purge를 호출하고 같은 이름의 soft-deleted vault를 자동 recover하지만, CI identity는 foundation/environment RG 권한만 가진다.
따라서 provider feature를 다음처럼 고정한다.

```hcl
features {
  key_vault {
    purge_soft_delete_on_destroy    = false
    recover_soft_deleted_key_vaults = false
  }
}
```

- Destroy는 provider-driven purge 없이 soft-delete까지만 수행하고, Azure가 7일 retention 뒤 purge한다.
- 이전에 삭제된 vault의 자동 recover는 사용하지 않는다.
- Retention 동안 같은 vault 이름 재사용은 정상 CI lifecycle에서 지원하지 않는다. 새로 승인된 배포는 충돌하지 않는 `key_vault_name`을 사용한다.
- 예외적인 recover/purge는 별도 operator 권한과 승인이 필요하며 이 stack의 CI 경로가 아니다.
- Terraform `destroy` 성공은 soft-deleted vault 같은 Azure residual object가 모두 사라졌다는 증거가 아니다.

이 설정은 lifecycle hardening이며 Azure runtime permission 문제의 검증된 해결이 아니다.
AzureRM 5.7.0은 자동 recover를 꺼도 생성 전에 subscription-scope deleted-vault API를 조회한다
([source](https://github.com/hashicorp/terraform-provider-azurerm/blob/v5.7.0/internal/services/keyvault/key_vault_resource.go)).
이 feature는 그 조회를 없애거나 subscription-scope 권한을 주지 않으며, 그 조회의 403/409 등 실제 생성/삭제/RBAC/residual 동작은 **not verified**다.
실제 destroy/residual 확인은 P6 이후 승인된 실행에서 한다.

## Static validation

```sh
make terraform-static
make static
```

`scripts/terraform-verify.sh`가 bootstrap과 같은 방식으로 fresh temp copy, empty CLI config, credential-free environment에서
`fmt -check -recursive`, `init -backend=false -input=false -lockfile=readonly`, `validate`, `test`를 실행한다.
Test는 [mock provider](https://developer.hashicorp.com/terraform/language/tests/mocking)와 `command=plan`만 사용하며 remote backend에 접속하지 않는다.
Source guard는 exact inventory, `foundation.tfstate` OIDC/Entra ID backend, OIDC-only provider, committed credential 부재,
Key Vault security/lifecycle 속성, access policy/network ACL 부재, DNS name server와 Key Vault ID/name/URI output을 검사한다.
Provider pin은 bootstrap과 같은 Terraform `1.16.4` / AzureRM `5.7.0`이며 `.terraform.lock.hcl`을 commit한다.

## Not verified

Remote backend 인증/locking, GitHub OIDC token exchange, Azure plan/provisioning, Resource Group 존재/접근,
DNS zone 생성, public delegation/resolution, Key Vault runtime/data-plane access, private endpoint connectivity,
effective RBAC propagation, Azure cost.
