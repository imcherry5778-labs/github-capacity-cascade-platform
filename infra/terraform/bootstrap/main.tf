locals {
  # 2026-10-01 authenticated GitHub GET: use_default=true, use_immutable_subject=true.
  # provenance와 재확인 절차는 README.md 참조. Trust identity는 operator input으로 확장하지 않는다.
  github_main_subject = "repo:imcherry5778-labs@273613742/github-capacity-cascade-platform@1384941385:ref:refs/heads/main"

  ci_resource_groups = {
    foundation  = azurerm_resource_group.boundary["foundation"].id
    environment = azurerm_resource_group.boundary["environment"].id
  }
}

resource "azurerm_resource_group" "boundary" {
  for_each = var.resource_group_names

  name     = each.value
  location = var.location
}

resource "azurerm_storage_account" "state" {
  name                     = var.state_storage_account_name
  resource_group_name      = azurerm_resource_group.boundary["bootstrap"].name
  location                 = azurerm_resource_group.boundary["bootstrap"].location
  account_kind             = "StorageV2"
  account_tier             = var.state_storage_sku.tier
  account_replication_type = var.state_storage_sku.replication_type

  https_traffic_only_enabled      = true
  min_tls_version                 = "TLS1_2"
  shared_access_key_enabled       = false
  default_to_oauth_authentication = true
  allow_nested_items_to_be_public = false
}

resource "azurerm_storage_container" "state" {
  name                  = var.state_container_name
  storage_account_id    = azurerm_storage_account.state.id
  container_access_type = "private"
}

resource "azurerm_user_assigned_identity" "ci" {
  name                = var.ci_identity_name
  resource_group_name = azurerm_resource_group.boundary["bootstrap"].name
  location            = azurerm_resource_group.boundary["bootstrap"].location
}

resource "azurerm_federated_identity_credential" "main" {
  name                      = "github-main"
  user_assigned_identity_id = azurerm_user_assigned_identity.ci.id
  issuer                    = "https://token.actions.githubusercontent.com"
  audience                  = ["api://AzureADTokenExchange"]
  subject                   = local.github_main_subject
}

resource "azurerm_role_assignment" "state" {
  scope                = azurerm_storage_container.state.id
  role_definition_name = "Storage Blob Data Contributor"
  principal_id         = azurerm_user_assigned_identity.ci.principal_id
  principal_type       = "ServicePrincipal"
}

resource "azurerm_role_assignment" "contributor" {
  for_each = local.ci_resource_groups

  scope                = each.value
  role_definition_name = "Contributor"
  principal_id         = azurerm_user_assigned_identity.ci.principal_id
  principal_type       = "ServicePrincipal"
}

resource "azurerm_role_assignment" "rbac" {
  for_each = local.ci_resource_groups

  scope                = each.value
  role_definition_name = "Role Based Access Control Administrator"
  principal_id         = azurerm_user_assigned_identity.ci.principal_id
  principal_type       = "ServicePrincipal"
}
