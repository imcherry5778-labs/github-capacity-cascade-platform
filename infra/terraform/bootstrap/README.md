# Azure bootstrap source — P5-W1

이 stack은 state backend, GitHub Actions CI trust, Resource Group permission boundary만 소유한다.
현재는 **implemented / static verified** 대상이며 Azure provisioning/runtime은 **not verified**다.
Architecture의 lifecycle/RBAC contract는 [`docs/architecture.md`](../../../docs/architecture.md#terraform-lifecycle)를 따른다.

## Lifecycle / inputs

`bootstrap local state → foundation remote state → environment remote state` 순서다.
bootstrap은 backend block이 없는 유일한 local-state stack이다. 후속 stack source는 아직 없다.
foundation/environment는 bootstrap의 `backend_config` output을 소비하고 서로 다른 blob `key`를 사용한다.
`use_oidc=true`, `use_azuread_auth=true`, `lookup_blob_endpoint=false`이므로 state container의 data-plane 역할만 사용하며 account-key lookup을 요구하지 않는다.
이는 [HashiCorp azurerm backend contract](https://developer.hashicorp.com/terraform/language/backend/azurerm)에 따른다.

필수 operator inputs:

- `subscription_id`, `tenant_id`, `location`
- `resource_group_names`의 서로 다른 `bootstrap`, `foundation`, `environment`
- `state_storage_account_name`, `state_storage_sku`의 `tier`, `replication_type`
- `ci_identity_name`; private container 이름은 `state_container_name`으로 바꿀 수 있다(기본 `tfstate`).

실제 account/naming 값은 commit하지 않는 local input으로 전달한다. region/SKU/cost 선택은 후속 paid-run preflight에서 한다.
bootstrap 실행 권한은 operator가 별도로 확인해야 한다. 아래 CI identity에는 bootstrap RG 관리 권한이 없어 자신의 trust/backend를 관리할 수 없다.
Local state에는 provider가 보관하는 민감 값이 포함될 수 있으므로 보호하고 Git에 넣지 않는다.
foundation/environment를 제거하더라도 bootstrap state/backend/trust는 후속 stack 정리와 state 보존 확인이 끝날 때까지 유지한다.
실제 생성/변경/삭제, role/principal inventory, destroy 순서와 residual resource 검증은 P6 이후 승인된 실행에서 확인한다.

## Planned inventory / CI scope

Resource 12개: RG 3개, Storage Account 1개, private Blob Container 1개, User Assigned Managed Identity 1개,
Federated Identity Credential 1개, role assignment 5개다. Terraform module/AzureAD provider는 없다.

| CI role | Scope | 수 |
| --- | --- | --- |
| `Storage Blob Data Contributor` | state Blob Container의 ARM ID | 1 |
| `Contributor` | foundation/environment RG 각각의 ARM ID | 2 |
| `Role Based Access Control Administrator` | foundation/environment RG 각각의 ARM ID | 2 |

State는 HTTPS/TLS 1.2, private container, public blob 금지, Shared Key 비활성화, Entra ID 인증을 사용한다.
AzureRM은 `storage_use_azuread=true`, `resource_provider_registrations="none"`으로 고정한다.
5.7.0의 [storage container implementation](https://github.com/hashicorp/terraform-provider-azurerm/blob/v5.7.0/internal/services/storage/storage_container_resource.go)은 `storage_account_id`에서 ARM container ID를 만들고 Resource Manager API를 사용한다.
Container 문서의 Shared Key 관련 설명을 runtime 검증 결과로 해석하지 않는다.

## Inspected GitHub trust

2026-10-01 authenticated read-only API snapshot은 [`oidc-inspection.json`](oidc-inspection.json)에 있다.
Repository/owner ID, 생성일, 실제 OIDC 설정 및 active `main` ruleset의 관련 항목을 보존한다.
OIDC 설정은 `use_default=true`, `use_immutable_subject=true`이며 별도 custom claim keys는 반환되지 않았다.
API가 반환한 `sub_claim_prefix`에 default branch context를 붙여 다음 exact subject를 도출했다.

```text
repo:imcherry5778-labs@273613742/github-capacity-cascade-platform@1384941385:ref:refs/heads/main
```

- Issuer: `https://token.actions.githubusercontent.com`
- Audience: `api://AzureADTokenExchange`
- [GitHub immutable subject/reference](https://docs.github.com/en/actions/reference/security/oidc#immutable-subject-claims)
- [GitHub Azure audience contract](https://docs.github.com/en/actions/how-tos/secure-your-work/security-harden-deployments/oidc-in-azure)

이 subject는 protected `main`의 branch context이며 PR context나 GitHub Environment context에 대한 trust가 아니다.
실제 Actions OIDC token 발급/Azure token exchange는 실행하지 않았다(**not verified**).
Rename/transfer/OIDC template 또는 `main` protection 변경 시 다음 read-only 조회와 공식 subject contract를 다시 대조한다.
현재 snapshot은 영구적인 setting authority가 아니다.

```sh
gh api repos/imcherry5778-labs/github-capacity-cascade-platform/actions/oidc/customization/sub
gh api repos/imcherry5778-labs/github-capacity-cascade-platform
gh api repos/imcherry5778-labs/github-capacity-cascade-platform/rulesets/24163252
```

## Reproducible static validation

2026-10-01 공식 latest stable release를 확인했다:
[Terraform 1.16.4](https://github.com/hashicorp/terraform/releases/tag/v1.16.4),
[AzureRM 5.7.0](https://github.com/hashicorp/terraform-provider-azurerm/releases/tag/v5.7.0).
`versions.env`와 `versions.tf`의 exact pin을 검사하며 `.terraform.lock.hcl`에 provider checksum을 commit한다.
Tool installer는 upstream release archive의 SHA-256을 확인하고 repository-local `.tmp/bin`에 설치한다.

```sh
make terraform-static
make static
```

Terraform 검증은 fresh temp directory에 source/tests/lockfile만 복사하고 empty CLI config와 credential-free environment로 실행한다.
`fmt -check -recursive`, `init -backend=false -input=false -lockfile=readonly`, `validate`, `test -filter=tests/security.tftest.hcl`을 사용한다.
모든 test는 [mock provider](https://developer.hashicorp.com/terraform/language/tests/mocking)와 `command=plan`이며 Azure API를 호출하지 않는다.
Exact subject/issuer/audience, 단일 CI principal, container/RG role scope 5개, Entra ID backend contract,
case-insensitive RG boundary collapse 거부를 검사한다. Source inventory/local-state 및 mock-only guard도 실행한다.
Init의 registry/release download에는 인터넷이 필요하다. PR CI에는 Azure login, OIDC token 권한, 실제 plan/apply/destroy가 없다.
