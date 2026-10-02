# 전부 mock + plan이다. Azure credential/API와 실제 apply가 필요하지 않다.
mock_provider "azurerm" {
  override_during = plan

  mock_resource "azurerm_user_assigned_identity" {
    defaults = {
      id           = "/subscriptions/00000000-0000-0000-0000-000000000000/resourceGroups/test-bootstrap/providers/Microsoft.ManagedIdentity/userAssignedIdentities/test-ci"
      client_id    = "11111111-1111-1111-1111-111111111111"
      principal_id = "22222222-2222-2222-2222-222222222222"
    }
  }

  mock_resource "azurerm_storage_account" {
    defaults = {
      id = "/subscriptions/00000000-0000-0000-0000-000000000000/resourceGroups/test-bootstrap/providers/Microsoft.Storage/storageAccounts/teststaticstate"
    }
  }

  mock_resource "azurerm_storage_container" {
    defaults = {
      id = "/subscriptions/00000000-0000-0000-0000-000000000000/resourceGroups/test-bootstrap/providers/Microsoft.Storage/storageAccounts/teststaticstate/blobServices/default/containers/tfstate"
    }
  }
}

run "reject_collapsed_permission_boundary" {
  command = plan
  variables {
    resource_group_names = {
      bootstrap   = "test-bootstrap"
      foundation  = "test-foundation"
      environment = "TEST-FOUNDATION"
    }
  }
  expect_failures = [var.resource_group_names]
}

override_resource {
  target          = azurerm_resource_group.boundary["bootstrap"]
  override_during = plan
  values          = { id = "/subscriptions/00000000-0000-0000-0000-000000000000/resourceGroups/test-bootstrap" }
}

override_resource {
  target          = azurerm_resource_group.boundary["foundation"]
  override_during = plan
  values          = { id = "/subscriptions/00000000-0000-0000-0000-000000000000/resourceGroups/test-foundation" }
}

override_resource {
  target          = azurerm_resource_group.boundary["environment"]
  override_during = plan
  values          = { id = "/subscriptions/00000000-0000-0000-0000-000000000000/resourceGroups/test-environment" }
}

variables {
  subscription_id = "00000000-0000-0000-0000-000000000000"
  tenant_id       = "00000000-0000-0000-0000-000000000000"
  location        = "test-location"
  resource_group_names = {
    bootstrap   = "test-bootstrap"
    foundation  = "test-foundation"
    environment = "test-environment"
  }
  state_storage_account_name = "teststaticstate"
  state_storage_sku          = { tier = "Standard", replication_type = "LRS" }
  ci_identity_name           = "test-ci"
}

run "trust_and_permission_boundary" {
  command = plan

  assert {
    condition = (
      azurerm_federated_identity_credential.azure.subject == "repo:imcherry5778-labs@273613742/github-capacity-cascade-platform@1384941385:environment:azure" &&
      azurerm_federated_identity_credential.azure.name == "github-azure" &&
      azurerm_federated_identity_credential.azure.issuer == "https://token.actions.githubusercontent.com" &&
      toset(azurerm_federated_identity_credential.azure.audience) == toset(["api://AzureADTokenExchange"]) &&
      azurerm_federated_identity_credential.azure.user_assigned_identity_id == azurerm_user_assigned_identity.ci.id
    )
    error_message = "Federation은 검증한 immutable azure Environment subject/issuer/audience와 단일 CI identity를 사용해야 한다."
  }

  assert {
    condition = (
      azurerm_role_assignment.state.role_definition_name == "Storage Blob Data Contributor" &&
      azurerm_role_assignment.state.scope == "/subscriptions/00000000-0000-0000-0000-000000000000/resourceGroups/test-bootstrap/providers/Microsoft.Storage/storageAccounts/teststaticstate/blobServices/default/containers/tfstate" &&
      azurerm_role_assignment.state.principal_id == azurerm_user_assigned_identity.ci.principal_id &&
      length(azurerm_role_assignment.contributor) == 2 && length(azurerm_role_assignment.rbac) == 2 &&
      alltrue([for key, assignment in azurerm_role_assignment.contributor :
        assignment.role_definition_name == "Contributor" &&
        assignment.scope == "/subscriptions/00000000-0000-0000-0000-000000000000/resourceGroups/test-${key}" &&
        contains(["foundation", "environment"], key) &&
        assignment.principal_id == azurerm_user_assigned_identity.ci.principal_id
      ]) &&
      alltrue([for key, assignment in azurerm_role_assignment.rbac :
        assignment.role_definition_name == "Role Based Access Control Administrator" &&
        assignment.scope == "/subscriptions/00000000-0000-0000-0000-000000000000/resourceGroups/test-${key}" &&
        contains(["foundation", "environment"], key) &&
        assignment.principal_id == azurerm_user_assigned_identity.ci.principal_id
      ])
    )
    error_message = "CI 역할 5개는 state container 및 project-owned foundation/environment RG에만 있어야 한다."
  }

  assert {
    condition = (
      azurerm_storage_account.state.shared_access_key_enabled == false &&
      azurerm_storage_account.state.default_to_oauth_authentication == true &&
      azurerm_storage_account.state.allow_nested_items_to_be_public == false &&
      azurerm_storage_account.state.https_traffic_only_enabled == true &&
      azurerm_storage_container.state.container_access_type == "private" &&
      output.backend_config.use_oidc && output.backend_config.use_azuread_auth &&
      output.backend_config.lookup_blob_endpoint == false
    )
    error_message = "State는 private/HTTPS/Entra ID를 사용하고 후속 backend는 key lookup 없이 OIDC로 인증해야 한다."
  }
}
