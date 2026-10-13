output "network" {
  description = "후속 platform source가 참조할 VNet/subnet ID."
  value = {
    virtual_network_id = azurerm_virtual_network.this.id
    subnet_ids = {
      aks_nodes         = azurerm_subnet.aks_nodes.id
      postgresql        = azurerm_subnet.postgresql.id
      private_endpoints = azurerm_subnet.private_endpoints.id
    }
  }
}

output "kubernetes_cluster" {
  description = "Non-secret AKS metadata. kubeconfig/admin credential은 output하지 않는다. 접근은 Entra ID + Azure RBAC다."
  value = {
    id                         = azurerm_kubernetes_cluster.this.id
    name                       = azurerm_kubernetes_cluster.this.name
    node_resource_group        = azurerm_kubernetes_cluster.this.node_resource_group
    oidc_issuer_url            = azurerm_kubernetes_cluster.this.oidc_issuer_url
    istio_revision             = var.kubernetes.istio_revision
    control_plane_principal_id = azurerm_user_assigned_identity.aks_control_plane.principal_id
    kubelet_principal_id       = azurerm_user_assigned_identity.aks_kubelet.principal_id
  }
}

output "postgresql" {
  description = "Private PostgreSQL endpoint metadata. Password는 output/state에 없다."
  value = {
    id                  = azurerm_postgresql_flexible_server.this.id
    fqdn                = azurerm_postgresql_flexible_server.this.fqdn
    database_name       = azurerm_postgresql_flexible_server_database.application.name
    administrator_login = azurerm_postgresql_flexible_server.this.administrator_login
  }
}

output "key_vault_private_endpoint" {
  description = "foundation Key Vault private connectivity metadata. Private resolution은 runtime에서 확인한다."
  value = {
    id                  = azurerm_private_endpoint.key_vault.id
    private_dns_zone_id = azurerm_private_dns_zone.key_vault.id
    private_ip_address  = azurerm_private_endpoint.key_vault.private_service_connection[0].private_ip_address
  }
}

output "container_registry" {
  description = "Entra ID 인증 registry metadata. Admin credential은 비활성이며 output하지 않는다."
  value = {
    id           = azurerm_container_registry.this.id
    login_server = azurerm_container_registry.this.login_server
  }
}

output "monitoring" {
  description = "Managed observability destination metadata. Connection string/instrumentation key는 output하지 않는다."
  value = {
    log_analytics_workspace_id  = azurerm_log_analytics_workspace.this.id
    monitor_workspace_id        = azurerm_monitor_workspace.this.id
    monitor_workspace_query_url = azurerm_monitor_workspace.this.query_endpoint
    grafana_id                  = azurerm_dashboard_grafana.this.id
    grafana_endpoint            = azurerm_dashboard_grafana.this.endpoint
    application_insights_id     = azurerm_application_insights.this.id
    application_insights_app_id = azurerm_application_insights.this.app_id
    container_insights_dcr_id   = azurerm_monitor_data_collection_rule.container_insights.id
    prometheus_dcr_id           = azurerm_monitor_data_collection_rule.prometheus.id
  }
}
