output "backend_config" {
  description = "향후 foundation/environment azurerm backend 입력. 각 stack은 별도의 key를 추가한다."
  value = {
    storage_account_name = azurerm_storage_account.state.name
    container_name       = azurerm_storage_container.state.name
    tenant_id            = var.tenant_id
    client_id            = azurerm_user_assigned_identity.ci.client_id
    use_oidc             = true
    use_azuread_auth     = true
    lookup_blob_endpoint = false
  }
}

output "ci_identity" {
  description = "CI 인증/RBAC inventory를 위한 identity ID와 검증한 federation subject."
  value = {
    id           = azurerm_user_assigned_identity.ci.id
    client_id    = azurerm_user_assigned_identity.ci.client_id
    principal_id = azurerm_user_assigned_identity.ci.principal_id
    subject      = azurerm_federated_identity_credential.main.subject
  }
}

output "resource_group_ids" {
  description = "후속 stack이 소비할 bootstrap-owned permission boundary."
  value       = { for key, group in azurerm_resource_group.boundary : key => group.id }
}
