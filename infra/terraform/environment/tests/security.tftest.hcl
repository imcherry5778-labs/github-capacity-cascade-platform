# 전부 mock + plan이다. Azure credential/API, remote backend와 실제 apply가 필요하지 않다.
mock_provider "azurerm" {
  override_during = plan

  mock_resource "azurerm_virtual_network" {
    defaults = {
      id = "/subscriptions/00000000-0000-0000-0000-000000000000/resourceGroups/test-environment/providers/Microsoft.Network/virtualNetworks/test-vnet"
    }
  }

  mock_resource "azurerm_container_registry" {
    defaults = {
      id           = "/subscriptions/00000000-0000-0000-0000-000000000000/resourceGroups/test-environment/providers/Microsoft.ContainerRegistry/registries/testenvironmentacr"
      login_server = "testenvironmentacr.azurecr.io"
    }
  }

  mock_resource "azurerm_postgresql_flexible_server" {
    defaults = {
      id   = "/subscriptions/00000000-0000-0000-0000-000000000000/resourceGroups/test-environment/providers/Microsoft.DBforPostgreSQL/flexibleServers/test-postgresql"
      fqdn = "test-postgresql.postgres.database.azure.com"
    }
  }

  mock_resource "azurerm_log_analytics_workspace" {
    defaults = {
      id = "/subscriptions/00000000-0000-0000-0000-000000000000/resourceGroups/test-environment/providers/Microsoft.OperationalInsights/workspaces/test-law"
    }
  }

  mock_resource "azurerm_monitor_workspace" {
    defaults = {
      id             = "/subscriptions/00000000-0000-0000-0000-000000000000/resourceGroups/test-environment/providers/Microsoft.Monitor/accounts/test-amw"
      query_endpoint = "https://test-amw.test-location.prometheus.monitor.azure.com"
    }
  }

  mock_resource "azurerm_monitor_data_collection_endpoint" {
    defaults = {
      id = "/subscriptions/00000000-0000-0000-0000-000000000000/resourceGroups/test-environment/providers/Microsoft.Insights/dataCollectionEndpoints/test-aks-prometheus"
    }
  }

  mock_resource "azurerm_dashboard_grafana" {
    defaults = {
      id       = "/subscriptions/00000000-0000-0000-0000-000000000000/resourceGroups/test-environment/providers/Microsoft.Dashboard/grafana/test-grafana"
      endpoint = "https://test-grafana.example.grafana.azure.com"
      identity = {
        principal_id = "66666666-6666-6666-6666-666666666666"
        tenant_id    = "00000000-0000-0000-0000-000000000000"
      }
    }
  }

  mock_resource "azurerm_application_insights" {
    defaults = {
      id     = "/subscriptions/00000000-0000-0000-0000-000000000000/resourceGroups/test-environment/providers/Microsoft.Insights/components/test-appi"
      app_id = "77777777-7777-7777-7777-777777777777"
    }
  }
}

override_resource {
  target          = azurerm_kubernetes_cluster.this
  override_during = plan
  values = {
    id                  = "/subscriptions/00000000-0000-0000-0000-000000000000/resourceGroups/test-environment/providers/Microsoft.ContainerService/managedClusters/test-aks"
    node_resource_group = "MC_test-environment_test-aks_test-location"
    oidc_issuer_url     = "https://test-location.oic.prod-aks.azure.com/00000000-0000-0000-0000-000000000000/11111111-1111-1111-1111-111111111111/"
  }
}

override_resource {
  target          = azurerm_user_assigned_identity.aks_control_plane
  override_during = plan
  values = {
    id           = "/subscriptions/00000000-0000-0000-0000-000000000000/resourceGroups/test-environment/providers/Microsoft.ManagedIdentity/userAssignedIdentities/test-aks-control-plane"
    principal_id = "33333333-3333-3333-3333-333333333333"
  }
}

override_resource {
  target          = azurerm_user_assigned_identity.aks_kubelet
  override_during = plan
  values = {
    id           = "/subscriptions/00000000-0000-0000-0000-000000000000/resourceGroups/test-environment/providers/Microsoft.ManagedIdentity/userAssignedIdentities/test-aks-kubelet"
    client_id    = "44444444-4444-4444-4444-444444444444"
    principal_id = "55555555-5555-5555-5555-555555555555"
  }
}

override_resource {
  target          = azurerm_subnet.aks_nodes
  override_during = plan
  values          = { id = "/subscriptions/00000000-0000-0000-0000-000000000000/resourceGroups/test-environment/providers/Microsoft.Network/virtualNetworks/test-vnet/subnets/aks-nodes" }
}

override_resource {
  target          = azurerm_subnet.postgresql
  override_during = plan
  values          = { id = "/subscriptions/00000000-0000-0000-0000-000000000000/resourceGroups/test-environment/providers/Microsoft.Network/virtualNetworks/test-vnet/subnets/postgresql" }
}

override_resource {
  target          = azurerm_subnet.private_endpoints
  override_during = plan
  values          = { id = "/subscriptions/00000000-0000-0000-0000-000000000000/resourceGroups/test-environment/providers/Microsoft.Network/virtualNetworks/test-vnet/subnets/private-endpoints" }
}

override_resource {
  target          = azurerm_private_dns_zone.key_vault
  override_during = plan
  values          = { id = "/subscriptions/00000000-0000-0000-0000-000000000000/resourceGroups/test-environment/providers/Microsoft.Network/privateDnsZones/privatelink.vaultcore.azure.net" }
}

override_resource {
  target          = azurerm_private_dns_zone.postgresql
  override_during = plan
  values          = { id = "/subscriptions/00000000-0000-0000-0000-000000000000/resourceGroups/test-environment/providers/Microsoft.Network/privateDnsZones/test-postgresql.private.postgres.database.azure.com" }
}

override_resource {
  target          = azurerm_monitor_data_collection_rule.container_insights
  override_during = plan
  values          = { id = "/subscriptions/00000000-0000-0000-0000-000000000000/resourceGroups/test-environment/providers/Microsoft.Insights/dataCollectionRules/test-aks-container-insights" }
}

override_resource {
  target          = azurerm_monitor_data_collection_rule.prometheus
  override_during = plan
  values          = { id = "/subscriptions/00000000-0000-0000-0000-000000000000/resourceGroups/test-environment/providers/Microsoft.Insights/dataCollectionRules/test-aks-prometheus" }
}

override_resource {
  target          = azurerm_user_assigned_identity.forgejo_secrets
  override_during = plan
  values = {
    id           = "/subscriptions/00000000-0000-0000-0000-000000000000/resourceGroups/test-environment/providers/Microsoft.ManagedIdentity/userAssignedIdentities/test-aks-forgejo-secrets"
    client_id    = "88888888-8888-8888-8888-888888888888"
    principal_id = "99999999-9999-9999-9999-999999999999"
  }
}

override_resource {
  target          = azurerm_user_assigned_identity.cert_manager
  override_during = plan
  values = {
    id           = "/subscriptions/00000000-0000-0000-0000-000000000000/resourceGroups/test-environment/providers/Microsoft.ManagedIdentity/userAssignedIdentities/test-aks-cert-manager"
    client_id    = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
    principal_id = "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb"
  }
}

variables {
  subscription_id                = "00000000-0000-0000-0000-000000000000"
  tenant_id                      = "00000000-0000-0000-0000-000000000000"
  ci_client_id                   = "11111111-1111-1111-1111-111111111111"
  resource_group_name            = "test-environment"
  location                       = "test-location"
  foundation_resource_group_name = "test-foundation"
  dns_zone_id                    = "/subscriptions/00000000-0000-0000-0000-000000000000/resourceGroups/test-foundation/providers/Microsoft.Network/dnsZones/platform.example.com"
  names = {
    virtual_network         = "test-vnet"
    kubernetes_cluster      = "test-aks"
    postgresql_server       = "test-postgresql"
    container_registry      = "testenvironmentacr"
    log_analytics_workspace = "test-law"
    monitor_workspace       = "test-amw"
    grafana                 = "test-grafana"
    application_insights    = "test-appi"
  }
  key_vault_id = "/subscriptions/00000000-0000-0000-0000-000000000000/resourceGroups/test-foundation/providers/Microsoft.KeyVault/vaults/test-foundation-kv"
  network = {
    address_space = "10.20.0.0/16"
    subnets = {
      aks_nodes         = "10.20.0.0/22"
      postgresql        = "10.20.4.0/28"
      private_endpoints = "10.20.5.0/27"
    }
    kubernetes = {
      pod_cidr       = "10.244.0.0/16"
      service_cidr   = "10.0.0.0/16"
      dns_service_ip = "10.0.0.10"
    }
  }
  # Provider 형식 검증만 통과하는 placeholder다. Region availability나 capacity baseline으로 해석하지 않는다.
  kubernetes = {
    version        = "1.36"
    istio_revision = "asm-1-30"
    sku_tier       = "Free"
    system_node_pool = {
      vm_size    = "test-vm-size"
      node_count = 2
    }
    api_server_authorized_ip_ranges = []
  }
  postgresql = {
    version                        = "17"
    sku_name                       = "B_Standard_B1ms"
    storage_mb                     = 32768
    database_name                  = "forgejo"
    administrator_login            = "forgejoadmin"
    administrator_password_version = 1
  }
  postgresql_administrator_password = "mock-only-not-a-real-password"
  container_registry_sku            = "Basic"
  monitoring = {
    log_analytics_retention_in_days = 30
    container_insights_streams      = ["Microsoft-ContainerLogV2", "Microsoft-KubeEvents", "Microsoft-KubePodInventory"]
    container_insights_interval     = "1m"
    grafana_major_version           = "12"
  }
}

run "environment_contract" {
  command = plan

  assert {
    condition = (
      azurerm_virtual_network.this.resource_group_name == "test-environment" &&
      azurerm_virtual_network.this.address_space == toset(["10.20.0.0/16"]) &&
      azurerm_subnet.aks_nodes.address_prefixes == tolist(["10.20.0.0/22"]) &&
      azurerm_subnet.postgresql.address_prefixes == tolist(["10.20.4.0/28"]) &&
      azurerm_subnet.private_endpoints.address_prefixes == tolist(["10.20.5.0/27"]) &&
      !azurerm_subnet.aks_nodes.default_outbound_access_enabled &&
      !azurerm_subnet.postgresql.default_outbound_access_enabled &&
      !azurerm_subnet.private_endpoints.default_outbound_access_enabled &&
      length(azurerm_subnet.aks_nodes.delegation) == 0 &&
      length(azurerm_subnet.private_endpoints.delegation) == 0
    )
    error_message = "Network는 existing environment RG의 VNet 하나와 책임별 subnet 세 개, implicit default outbound 미사용이어야 한다."
  }

  assert {
    condition = (
      length(azurerm_subnet.postgresql.delegation) == 1 &&
      azurerm_subnet.postgresql.delegation[0].service_delegation[0].name == "Microsoft.DBforPostgreSQL/flexibleServers" &&
      azurerm_subnet.postgresql.service_endpoint[0].service == "Microsoft.Storage" &&
      azurerm_postgresql_flexible_server.this.delegated_subnet_id == azurerm_subnet.postgresql.id &&
      azurerm_postgresql_flexible_server.this.private_dns_zone_id == azurerm_private_dns_zone.postgresql.id &&
      azurerm_postgresql_flexible_server.this.public_network_access_enabled == false &&
      azurerm_private_dns_zone.postgresql.name == "test-postgresql.private.postgres.database.azure.com" &&
      azurerm_private_dns_zone_virtual_network_link.postgresql.private_dns_zone_id == azurerm_private_dns_zone.postgresql.id &&
      azurerm_private_dns_zone_virtual_network_link.postgresql.virtual_network_id == azurerm_virtual_network.this.id &&
      azurerm_postgresql_flexible_server_database.application.name == "forgejo" &&
      azurerm_postgresql_flexible_server_database.application.server_id == azurerm_postgresql_flexible_server.this.id
    )
    error_message = "PostgreSQL은 delegated subnet + linked private DNS zone만 사용하고 public endpoint가 없어야 한다."
  }

  assert {
    # Write-only 값은 plan/state에 항상 null로 기록된다. Sensitive state attribute도 사용하지 않는다.
    condition = (
      azurerm_postgresql_flexible_server.this.administrator_password == null &&
      azurerm_postgresql_flexible_server.this.administrator_password_wo == null &&
      azurerm_postgresql_flexible_server.this.administrator_password_wo_version == 1 &&
      azurerm_postgresql_flexible_server.this.authentication[0].password_auth_enabled == true &&
      output.postgresql.administrator_login == "forgejoadmin" &&
      !contains(keys(output.postgresql), "administrator_password")
    )
    error_message = "PostgreSQL password는 write-only로만 전달되어 plan/state/output에 남지 않아야 한다."
  }

  assert {
    condition = (
      azurerm_private_endpoint.key_vault.subnet_id == azurerm_subnet.private_endpoints.id &&
      azurerm_private_endpoint.key_vault.private_service_connection[0].private_connection_resource_id == var.key_vault_id &&
      azurerm_private_endpoint.key_vault.private_service_connection[0].subresource_names == tolist(["vault"]) &&
      azurerm_private_endpoint.key_vault.private_service_connection[0].is_manual_connection == false &&
      azurerm_private_endpoint.key_vault.private_dns_zone_group[0].private_dns_zone_ids == tolist([azurerm_private_dns_zone.key_vault.id]) &&
      azurerm_private_dns_zone.key_vault.name == "privatelink.vaultcore.azure.net" &&
      azurerm_private_dns_zone_virtual_network_link.key_vault.virtual_network_id == azurerm_virtual_network.this.id
    )
    error_message = "foundation Key Vault는 private endpoint + privatelink.vaultcore.azure.net zone group으로만 연결해야 한다."
  }

  assert {
    condition = (
      azurerm_kubernetes_cluster.this.oidc_issuer_enabled == true &&
      azurerm_kubernetes_cluster.this.workload_identity_enabled == true &&
      azurerm_kubernetes_cluster.this.local_account_disabled == true &&
      azurerm_kubernetes_cluster.this.azure_active_directory_role_based_access_control[0].azure_rbac_enabled == true &&
      azurerm_kubernetes_cluster.this.identity[0].type == "UserAssigned" &&
      azurerm_kubernetes_cluster.this.identity[0].identity_ids == toset([azurerm_user_assigned_identity.aks_control_plane.id]) &&
      azurerm_kubernetes_cluster.this.kubelet_identity[0].user_assigned_identity_id == azurerm_user_assigned_identity.aks_kubelet.id &&
      azurerm_kubernetes_cluster.this.kubelet_identity[0].object_id == azurerm_user_assigned_identity.aks_kubelet.principal_id &&
      length(azurerm_kubernetes_cluster.this.service_principal) == 0 &&
      azurerm_kubernetes_cluster.this.kubernetes_version == "1.36" &&
      length(azurerm_kubernetes_cluster.this.api_server_access_profile) == 0
    )
    error_message = "AKS는 user-assigned managed identity, OIDC issuer, Workload ID, local account 비활성, Entra ID + Azure RBAC를 사용해야 한다."
  }

  assert {
    condition = (
      azurerm_kubernetes_cluster.this.service_mesh_profile[0].mode == "Istio" &&
      azurerm_kubernetes_cluster.this.service_mesh_profile[0].revisions == tolist(["asm-1-30"]) &&
      azurerm_kubernetes_cluster.this.service_mesh_profile[0].external_ingress_gateway_enabled == true &&
      azurerm_kubernetes_cluster.this.service_mesh_profile[0].internal_ingress_gateway_enabled == false &&
      azurerm_kubernetes_cluster.this.workload_autoscaler_profile[0].keda_enabled == true &&
      length(azurerm_kubernetes_cluster.this.key_vault_secrets_provider) == 1 &&
      azurerm_kubernetes_cluster.this.storage_profile[0].disk_driver_enabled == true &&
      azurerm_kubernetes_cluster.this.storage_profile[0].file_driver_enabled == false &&
      azurerm_kubernetes_cluster.this.storage_profile[0].blob_driver_enabled == false
    )
    error_message = "AKS managed Istio/KEDA/Key Vault CSI와 Azure Disk CSI persistent storage만 켜야 한다."
  }

  assert {
    condition = (
      azurerm_kubernetes_cluster.this.default_node_pool[0].vnet_subnet_id == azurerm_subnet.aks_nodes.id &&
      azurerm_kubernetes_cluster.this.default_node_pool[0].auto_scaling_enabled == false &&
      azurerm_kubernetes_cluster.this.default_node_pool[0].node_count == 2 &&
      azurerm_kubernetes_cluster.this.network_profile[0].network_plugin == "azure" &&
      azurerm_kubernetes_cluster.this.network_profile[0].network_plugin_mode == "overlay" &&
      azurerm_kubernetes_cluster.this.network_profile[0].outbound_type == "loadBalancer" &&
      azurerm_kubernetes_cluster.this.network_profile[0].pod_cidr == "10.244.0.0/16" &&
      azurerm_kubernetes_cluster.this.network_profile[0].service_cidr == "10.0.0.0/16" &&
      azurerm_kubernetes_cluster.this.automatic_upgrade_channel == null &&
      azurerm_kubernetes_cluster.this.node_os_upgrade_channel == "None"
    )
    error_message = "AKS는 고정 system pool, Azure CNI Overlay, explicit LB outbound, operator-only upgrade를 사용해야 한다."
  }

  assert {
    condition = (
      azurerm_container_registry.this.admin_enabled == false &&
      azurerm_container_registry.this.anonymous_pull_enabled == false &&
      azurerm_container_registry.this.role_assignment_mode == "LegacyRegistryPermissions" &&
      azurerm_container_registry.this.sku == "Basic"
    )
    error_message = "ACR은 admin/anonymous pull 없이 Entra ID role 기반 인증만 사용해야 한다."
  }

  assert {
    # W3 infrastructure role 네 개는 유지한다. W4 workload role 두 개는 별도 assertion으로 검증한다.
    condition = (
      azurerm_role_assignment.aks_subnet.role_definition_name == "Network Contributor" &&
      azurerm_role_assignment.aks_subnet.scope == azurerm_subnet.aks_nodes.id &&
      azurerm_role_assignment.aks_subnet.principal_id == azurerm_user_assigned_identity.aks_control_plane.principal_id &&
      azurerm_role_assignment.aks_acr_pull.role_definition_name == "AcrPull" &&
      azurerm_role_assignment.aks_acr_pull.scope == azurerm_container_registry.this.id &&
      azurerm_role_assignment.aks_acr_pull.principal_id == azurerm_user_assigned_identity.aks_kubelet.principal_id &&
      azurerm_role_assignment.aks_acr_pull.principal_id == "55555555-5555-5555-5555-555555555555" &&
      azurerm_role_assignment.aks_kubelet_operator.role_definition_name == "Managed Identity Operator" &&
      azurerm_role_assignment.aks_kubelet_operator.scope == azurerm_user_assigned_identity.aks_kubelet.id &&
      azurerm_role_assignment.aks_kubelet_operator.principal_id == azurerm_user_assigned_identity.aks_control_plane.principal_id &&
      azurerm_role_assignment.grafana_monitor_workspace.role_definition_name == "Monitoring Data Reader" &&
      azurerm_role_assignment.grafana_monitor_workspace.scope == azurerm_monitor_workspace.this.id &&
      azurerm_role_assignment.grafana_monitor_workspace.principal_id == "66666666-6666-6666-6666-666666666666"
    )
    error_message = "Role assignment는 subnet join, kubelet identity 할당, kubelet AcrPull, Grafana의 monitor workspace 조회로만 한정해야 한다."
  }

  assert {
    condition = (
      azurerm_kubernetes_cluster.this.oms_agent[0].log_analytics_workspace_id == azurerm_log_analytics_workspace.this.id &&
      azurerm_kubernetes_cluster.this.oms_agent[0].msi_auth_for_monitoring_enabled == true &&
      length(azurerm_kubernetes_cluster.this.monitor_metrics) == 1 &&
      azurerm_log_analytics_workspace.this.local_authentication_enabled == false &&
      azurerm_monitor_data_collection_rule_association.container_insights.target_resource_id == azurerm_kubernetes_cluster.this.id &&
      azurerm_monitor_data_collection_rule_association.container_insights.data_collection_rule_id == azurerm_monitor_data_collection_rule.container_insights.id &&
      azurerm_monitor_data_collection_rule.container_insights.destinations[0].log_analytics[0].workspace_resource_id == azurerm_log_analytics_workspace.this.id &&
      azurerm_monitor_data_collection_rule.container_insights.data_sources[0].extension[0].extension_name == "ContainerInsights" &&
      azurerm_monitor_data_collection_rule_association.prometheus.target_resource_id == azurerm_kubernetes_cluster.this.id &&
      azurerm_monitor_data_collection_rule_association.prometheus.data_collection_rule_id == azurerm_monitor_data_collection_rule.prometheus.id &&
      azurerm_monitor_data_collection_rule.prometheus.destinations[0].monitor_account[0].monitor_account_id == azurerm_monitor_workspace.this.id &&
      azurerm_monitor_data_collection_rule.prometheus.data_collection_endpoint_id == azurerm_monitor_data_collection_endpoint.prometheus.id &&
      azurerm_dashboard_grafana.this.azure_monitor_workspace_integrations[0].resource_id == azurerm_monitor_workspace.this.id &&
      azurerm_dashboard_grafana.this.api_key_enabled == false &&
      azurerm_application_insights.this.workspace_id == azurerm_log_analytics_workspace.this.id
    )
    error_message = "Container Insights/Managed Prometheus/Grafana/Application Insights destination 연결이 필요하다."
  }

  assert {
    condition = (
      output.kubernetes_cluster.id == azurerm_kubernetes_cluster.this.id &&
      output.kubernetes_cluster.oidc_issuer_url == azurerm_kubernetes_cluster.this.oidc_issuer_url &&
      output.kubernetes_cluster.node_resource_group == "MC_test-environment_test-aks_test-location" &&
      output.kubernetes_cluster.kubelet_principal_id == "55555555-5555-5555-5555-555555555555" &&
      output.container_registry.login_server == "testenvironmentacr.azurecr.io" &&
      output.postgresql.fqdn == "test-postgresql.postgres.database.azure.com" &&
      output.key_vault_private_endpoint.private_dns_zone_id == azurerm_private_dns_zone.key_vault.id &&
      output.monitoring.monitor_workspace_id == azurerm_monitor_workspace.this.id &&
      output.network.subnet_ids.aks_nodes == azurerm_subnet.aks_nodes.id
    )
    error_message = "W4가 소비할 non-secret resource/identity/dependency metadata output이 필요하다."
  }
}

run "restricted_api_server_ranges" {
  command = plan
  variables {
    kubernetes = {
      version        = "1.36"
      istio_revision = "asm-1-30"
      sku_tier       = "Free"
      system_node_pool = {
        vm_size    = "test-vm-size"
        node_count = 2
      }
      api_server_authorized_ip_ranges = ["203.0.113.0/24"]
    }
  }

  assert {
    condition     = azurerm_kubernetes_cluster.this.api_server_access_profile[0].authorized_ip_ranges == toset(["203.0.113.0/24"])
    error_message = "Operator가 준 API server authorized range만 적용해야 한다."
  }
}

run "reject_single_node_system_pool" {
  command = plan
  variables {
    kubernetes = {
      version        = "1.36"
      istio_revision = "asm-1-30"
      sku_tier       = "Free"
      system_node_pool = {
        vm_size    = "test-vm-size"
        node_count = 1
      }
      api_server_authorized_ip_ranges = []
    }
  }
  expect_failures = [var.kubernetes]
}

run "reject_overlapping_subnets" {
  command = plan
  variables {
    network = {
      address_space = "10.20.0.0/16"
      subnets = {
        aks_nodes         = "10.20.0.0/22"
        postgresql        = "10.20.3.0/28"
        private_endpoints = "10.20.5.0/27"
      }
      kubernetes = {
        pod_cidr       = "10.244.0.0/16"
        service_cidr   = "10.0.0.0/16"
        dns_service_ip = "10.0.0.10"
      }
    }
  }
  expect_failures = [var.network]
}

run "reject_subnet_outside_vnet" {
  command = plan
  variables {
    network = {
      address_space = "10.20.0.0/16"
      subnets = {
        aks_nodes         = "10.20.0.0/22"
        postgresql        = "10.21.4.0/28"
        private_endpoints = "10.20.5.0/27"
      }
      kubernetes = {
        pod_cidr       = "10.244.0.0/16"
        service_cidr   = "10.0.0.0/16"
        dns_service_ip = "10.0.0.10"
      }
    }
  }
  expect_failures = [var.network]
}

run "reject_pod_cidr_overlapping_vnet" {
  command = plan
  variables {
    network = {
      address_space = "10.20.0.0/16"
      subnets = {
        aks_nodes         = "10.20.0.0/22"
        postgresql        = "10.20.4.0/28"
        private_endpoints = "10.20.5.0/27"
      }
      kubernetes = {
        pod_cidr       = "10.20.128.0/17"
        service_cidr   = "10.0.0.0/16"
        dns_service_ip = "10.0.0.10"
      }
    }
  }
  expect_failures = [var.network]
}

run "reject_undersized_postgresql_subnet" {
  command = plan
  variables {
    network = {
      address_space = "10.20.0.0/16"
      subnets = {
        aks_nodes         = "10.20.0.0/22"
        postgresql        = "10.20.4.0/29"
        private_endpoints = "10.20.5.0/27"
      }
      kubernetes = {
        pod_cidr       = "10.244.0.0/16"
        service_cidr   = "10.0.0.0/16"
        dns_service_ip = "10.0.0.10"
      }
    }
  }
  expect_failures = [var.network]
}

run "reject_dns_service_ip_outside_service_cidr" {
  command = plan
  variables {
    network = {
      address_space = "10.20.0.0/16"
      subnets = {
        aks_nodes         = "10.20.0.0/22"
        postgresql        = "10.20.4.0/28"
        private_endpoints = "10.20.5.0/27"
      }
      kubernetes = {
        pod_cidr       = "10.244.0.0/16"
        service_cidr   = "10.0.0.0/16"
        dns_service_ip = "10.1.0.10"
      }
    }
  }
  expect_failures = [var.network]
}

run "reject_malformed_cidr" {
  command = plan
  variables {
    network = {
      address_space = "10.20.0.1/16"
      subnets = {
        aks_nodes         = "10.20.0.0/22"
        postgresql        = "10.20.4.0/28"
        private_endpoints = "10.20.5.0/27"
      }
      kubernetes = {
        pod_cidr       = "10.244.0.0/16"
        service_cidr   = "10.0.0.0/16"
        dns_service_ip = "10.0.0.10"
      }
    }
  }
  expect_failures = [var.network]
}

run "reject_non_key_vault_reference" {
  command = plan
  variables {
    key_vault_id = "/subscriptions/00000000-0000-0000-0000-000000000000/resourceGroups/test-foundation/providers/Microsoft.Storage/storageAccounts/notavault"
  }
  expect_failures = [var.key_vault_id]
}

run "reject_premium_registry" {
  command = plan
  variables {
    container_registry_sku = "Premium"
  }
  expect_failures = [var.container_registry_sku]
}

run "reject_unmanaged_istio_revision" {
  command = plan
  variables {
    kubernetes = {
      version        = "1.36"
      istio_revision = "1.30.5"
      sku_tier       = "Free"
      system_node_pool = {
        vm_size    = "test-vm-size"
        node_count = 2
      }
      api_server_authorized_ip_ranges = []
    }
  }
  expect_failures = [var.kubernetes]
}

run "reject_reserved_postgresql_administrator" {
  command = plan
  variables {
    postgresql = {
      version                        = "17"
      sku_name                       = "B_Standard_B1ms"
      storage_mb                     = 32768
      database_name                  = "forgejo"
      administrator_login            = "azure_superuser"
      administrator_password_version = 1
    }
  }
  expect_failures = [var.postgresql]
}

run "reject_short_postgresql_password" {
  command = plan
  variables {
    postgresql_administrator_password = "short"
  }
  expect_failures = [var.postgresql_administrator_password]
}

run "platform_workload_rbac" {
  command = plan
  assert {
    condition = (
      azurerm_federated_identity_credential.forgejo_secrets.subject == "system:serviceaccount:forgejo:forgejo-secrets" &&
      azurerm_federated_identity_credential.cert_manager.subject == "system:serviceaccount:cert-manager:cert-manager" &&
      azurerm_federated_identity_credential.forgejo_secrets.user_assigned_identity_id == azurerm_user_assigned_identity.forgejo_secrets.id &&
      azurerm_federated_identity_credential.cert_manager.user_assigned_identity_id == azurerm_user_assigned_identity.cert_manager.id &&
      azurerm_federated_identity_credential.forgejo_secrets.issuer == azurerm_kubernetes_cluster.this.oidc_issuer_url &&
      azurerm_federated_identity_credential.cert_manager.issuer == azurerm_kubernetes_cluster.this.oidc_issuer_url &&
      toset(azurerm_federated_identity_credential.forgejo_secrets.audience) == toset(["api://AzureADTokenExchange"]) &&
      toset(azurerm_federated_identity_credential.cert_manager.audience) == toset(["api://AzureADTokenExchange"]) &&
      azurerm_role_assignment.forgejo_secrets.scope == var.key_vault_id &&
      azurerm_role_assignment.forgejo_secrets.role_definition_name == "Key Vault Secrets User" &&
      azurerm_role_assignment.forgejo_secrets.principal_id == azurerm_user_assigned_identity.forgejo_secrets.principal_id &&
      azurerm_role_assignment.forgejo_secrets.principal_type == "ServicePrincipal" &&
      azurerm_role_assignment.forgejo_secrets.skip_service_principal_aad_check == true &&
      azurerm_role_assignment.cert_manager_dns.scope == var.dns_zone_id &&
      azurerm_role_assignment.cert_manager_dns.role_definition_name == "DNS Zone Contributor" &&
      azurerm_role_assignment.cert_manager_dns.principal_id == azurerm_user_assigned_identity.cert_manager.principal_id
      && azurerm_role_assignment.cert_manager_dns.principal_type == "ServicePrincipal"
      && azurerm_role_assignment.cert_manager_dns.skip_service_principal_aad_check == true
    )
    error_message = "Exact ServiceAccount federation and resource-scoped platform roles required."
  }
}

run "reject_dns_outside_foundation" {
  command = plan
  variables { dns_zone_id = "/subscriptions/00000000-0000-0000-0000-000000000000/resourceGroups/other/providers/Microsoft.Network/dnsZones/example.com" }
  expect_failures = [var.dns_zone_id]
}

run "reject_vault_outside_foundation" {
  command = plan
  variables { key_vault_id = "/subscriptions/00000000-0000-0000-0000-000000000000/resourceGroups/other/providers/Microsoft.KeyVault/vaults/other" }
  expect_failures = [var.key_vault_id]
}
