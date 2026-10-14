# Environment lifecycle identity; cross-RG roles are scoped to the existing foundation resources.
resource "azurerm_user_assigned_identity" "forgejo_secrets" {
  name                = "${var.names.kubernetes_cluster}-forgejo-secrets"
  resource_group_name = var.resource_group_name
  location            = var.location
}

resource "azurerm_federated_identity_credential" "forgejo_secrets" {
  name                      = "forgejo-secrets"
  user_assigned_identity_id = azurerm_user_assigned_identity.forgejo_secrets.id
  issuer                    = azurerm_kubernetes_cluster.this.oidc_issuer_url
  audience                  = ["api://AzureADTokenExchange"]
  subject                   = "system:serviceaccount:forgejo:forgejo-secrets"
}

resource "azurerm_role_assignment" "forgejo_secrets" {
  scope                = var.key_vault_id
  role_definition_name = "Key Vault Secrets User"
  principal_id         = azurerm_user_assigned_identity.forgejo_secrets.principal_id
}

resource "azurerm_user_assigned_identity" "cert_manager" {
  name                = "${var.names.kubernetes_cluster}-cert-manager"
  resource_group_name = var.resource_group_name
  location            = var.location
}

resource "azurerm_federated_identity_credential" "cert_manager" {
  name                      = "cert-manager"
  user_assigned_identity_id = azurerm_user_assigned_identity.cert_manager.id
  issuer                    = azurerm_kubernetes_cluster.this.oidc_issuer_url
  audience                  = ["api://AzureADTokenExchange"]
  subject                   = "system:serviceaccount:cert-manager:cert-manager"
}

resource "azurerm_role_assignment" "cert_manager_dns" {
  scope                = var.dns_zone_id
  role_definition_name = "DNS Zone Contributor"
  principal_id         = azurerm_user_assigned_identity.cert_manager.principal_id
}
