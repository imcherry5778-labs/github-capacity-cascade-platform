# BYO subnet을 쓰려면 cluster 생성 전에 control-plane identity가 subnet 권한을 가져야 한다.
# System-assigned identity는 cluster 생성 뒤에야 생기므로 user-assigned identity를 사용한다.
resource "azurerm_user_assigned_identity" "aks_control_plane" {
  name                = "${var.names.kubernetes_cluster}-control-plane"
  resource_group_name = var.resource_group_name
  location            = var.location
}

resource "azurerm_role_assignment" "aks_subnet" {
  scope                = azurerm_subnet.aks_nodes.id
  role_definition_name = "Network Contributor"
  principal_id         = azurerm_user_assigned_identity.aks_control_plane.principal_id
  principal_type       = "ServicePrincipal"
}

# Kubelet identity를 node resource group의 AKS 생성 identity 대신 environment RG에 미리 만든다.
# AcrPull을 cluster 생성 전에 부여할 수 있고 identity lifecycle이 이 stack에 남는다.
# AKS control plane은 이 identity 하나에 대해서만 Managed Identity Operator 권한이 필요하다.
resource "azurerm_user_assigned_identity" "aks_kubelet" {
  name                = "${var.names.kubernetes_cluster}-kubelet"
  resource_group_name = var.resource_group_name
  location            = var.location
}

resource "azurerm_role_assignment" "aks_kubelet_operator" {
  scope                = azurerm_user_assigned_identity.aks_kubelet.id
  role_definition_name = "Managed Identity Operator"
  principal_id         = azurerm_user_assigned_identity.aks_control_plane.principal_id
  principal_type       = "ServicePrincipal"
}

resource "azurerm_kubernetes_cluster" "this" {
  name                = var.names.kubernetes_cluster
  resource_group_name = var.resource_group_name
  location            = var.location
  dns_prefix          = var.names.kubernetes_cluster
  kubernetes_version  = var.kubernetes.version
  sku_tier            = var.kubernetes.sku_tier

  # Upgrade는 승인된 operator action으로만 수행한다. Managed Istio도 cluster auto-upgrade를 따라가지 않으며,
  # 자동 node image 교체가 controlled experiment의 confounder가 되지 않게 한다.
  automatic_upgrade_channel = null
  node_os_upgrade_channel   = "None"

  identity {
    type         = "UserAssigned"
    identity_ids = [azurerm_user_assigned_identity.aks_control_plane.id]
  }

  kubelet_identity {
    client_id                 = azurerm_user_assigned_identity.aks_kubelet.client_id
    object_id                 = azurerm_user_assigned_identity.aks_kubelet.principal_id
    user_assigned_identity_id = azurerm_user_assigned_identity.aks_kubelet.id
  }

  # Public managed API endpoint다(private cluster 아님). Local account/admin certificate를 끄고
  # Kubernetes 인증은 Entra ID, 인가는 Azure RBAC로만 한다. kubeconfig는 output하지 않는다.
  local_account_disabled            = true
  role_based_access_control_enabled = true

  azure_active_directory_role_based_access_control {
    azure_rbac_enabled = true
    tenant_id          = var.tenant_id
  }

  dynamic "api_server_access_profile" {
    for_each = length(var.kubernetes.api_server_authorized_ip_ranges) > 0 ? [1] : []
    content {
      authorized_ip_ranges = var.kubernetes.api_server_authorized_ip_ranges
    }
  }

  oidc_issuer_enabled       = true
  workload_identity_enabled = true

  default_node_pool {
    name                 = "system"
    vm_size              = var.kubernetes.system_node_pool.vm_size
    node_count           = var.kubernetes.system_node_pool.node_count
    auto_scaling_enabled = false
    vnet_subnet_id       = azurerm_subnet.aks_nodes.id
  }

  node_provisioning_profile {
    mode = "Manual"
  }

  # Azure CNI Overlay: node만 VNet subnet IP를 쓰고 pod는 VNet 밖 overlay CIDR을 쓴다.
  network_profile {
    network_plugin      = "azure"
    network_plugin_mode = "overlay"
    load_balancer_sku   = "standard"
    outbound_type       = "loadBalancer"
    pod_cidr            = var.network.kubernetes.pod_cidr
    service_cidr        = var.network.kubernetes.service_cidr
    dns_service_ip      = var.network.kubernetes.dns_service_ip
  }

  # AKS managed capability. Lifecycle은 AKS가 소유하며 Argo CD나 Helm으로 대체하지 않는다.
  service_mesh_profile {
    mode                             = "Istio"
    revisions                        = [var.kubernetes.istio_revision]
    external_ingress_gateway_enabled = true
    internal_ingress_gateway_enabled = false
  }

  workload_autoscaler_profile {
    keda_enabled = true
  }

  key_vault_secrets_provider {
    secret_rotation_enabled = false
  }

  # Forgejo single-replica persistent data는 Azure Disk CSI PV를 사용한다. 다른 storage driver는 켜지 않는다.
  storage_profile {
    disk_driver_enabled = true
    file_driver_enabled = false
    blob_driver_enabled = false
  }

  # Container Insights(managed identity auth)와 Managed Prometheus metrics profile.
  # 실제 destination은 monitoring.tf의 data collection rule association이 연결한다.
  oms_agent {
    log_analytics_workspace_id      = azurerm_log_analytics_workspace.this.id
    msi_auth_for_monitoring_enabled = true
  }

  monitor_metrics {}

  depends_on = [
    azurerm_role_assignment.aks_subnet,
    azurerm_role_assignment.aks_kubelet_operator,
    azurerm_role_assignment.aks_acr_pull,
  ]
}

# Registry는 Entra ID 인증만 사용한다. Admin user와 anonymous pull을 끄고, AKS kubelet identity에 AcrPull만 준다.
resource "azurerm_container_registry" "this" {
  name                   = var.names.container_registry
  resource_group_name    = var.resource_group_name
  location               = var.location
  sku                    = var.container_registry_sku
  admin_enabled          = false
  anonymous_pull_enabled = false
  role_assignment_mode   = "LegacyRegistryPermissions"
}

resource "azurerm_role_assignment" "aks_acr_pull" {
  scope                = azurerm_container_registry.this.id
  role_definition_name = "AcrPull"
  principal_id         = azurerm_user_assigned_identity.aks_kubelet.principal_id
  principal_type       = "ServicePrincipal"
}
