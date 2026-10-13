# Logs: Container Insights → Log Analytics. Local shared key 인증은 쓰지 않는다.
resource "azurerm_log_analytics_workspace" "this" {
  name                         = var.names.log_analytics_workspace
  resource_group_name          = var.resource_group_name
  location                     = var.location
  sku                          = "PerGB2018"
  retention_in_days            = var.monitoring.log_analytics_retention_in_days
  local_authentication_enabled = false
}

resource "azurerm_monitor_data_collection_rule" "container_insights" {
  name                = "${var.names.kubernetes_cluster}-container-insights"
  resource_group_name = var.resource_group_name
  location            = var.location

  destinations {
    log_analytics {
      name                  = "ciworkspace"
      workspace_resource_id = azurerm_log_analytics_workspace.this.id
    }
  }

  data_flow {
    streams      = var.monitoring.container_insights_streams
    destinations = ["ciworkspace"]
  }

  data_sources {
    extension {
      name           = "ContainerInsightsExtension"
      extension_name = "ContainerInsights"
      streams        = var.monitoring.container_insights_streams
      extension_json = jsonencode({
        dataCollectionSettings = {
          interval               = var.monitoring.container_insights_interval
          namespaceFilteringMode = "Off"
          enableContainerLogV2   = true
        }
      })
    }
  }
}

resource "azurerm_monitor_data_collection_rule_association" "container_insights" {
  name                    = "ContainerInsightsExtension"
  target_resource_id      = azurerm_kubernetes_cluster.this.id
  data_collection_rule_id = azurerm_monitor_data_collection_rule.container_insights.id
}

# Metrics: Managed Prometheus → Azure Monitor Workspace → Managed Grafana.
# Workspace 생성 시 Azure가 별도 managed resource group과 default DCE/DCR을 암묵적으로 만든다(README 참조).
resource "azurerm_monitor_workspace" "this" {
  name                = var.names.monitor_workspace
  resource_group_name = var.resource_group_name
  location            = var.location
}

resource "azurerm_monitor_data_collection_endpoint" "prometheus" {
  name                = "${var.names.kubernetes_cluster}-prometheus"
  resource_group_name = var.resource_group_name
  location            = var.location
  kind                = "Linux"
}

resource "azurerm_monitor_data_collection_rule" "prometheus" {
  name                        = "${var.names.kubernetes_cluster}-prometheus"
  resource_group_name         = var.resource_group_name
  location                    = var.location
  kind                        = "Linux"
  data_collection_endpoint_id = azurerm_monitor_data_collection_endpoint.prometheus.id

  destinations {
    monitor_account {
      name               = "MonitoringAccount1"
      monitor_account_id = azurerm_monitor_workspace.this.id
    }
  }

  data_flow {
    streams      = ["Microsoft-PrometheusMetrics"]
    destinations = ["MonitoringAccount1"]
  }

  data_sources {
    prometheus_forwarder {
      name    = "PrometheusDataSource"
      streams = ["Microsoft-PrometheusMetrics"]
    }
  }
}

resource "azurerm_monitor_data_collection_rule_association" "prometheus" {
  name                    = "${var.names.kubernetes_cluster}-prometheus"
  target_resource_id      = azurerm_kubernetes_cluster.this.id
  data_collection_rule_id = azurerm_monitor_data_collection_rule.prometheus.id
}

resource "azurerm_dashboard_grafana" "this" {
  name                  = var.names.grafana
  resource_group_name   = var.resource_group_name
  location              = var.location
  sku                   = "Standard"
  grafana_major_version = var.monitoring.grafana_major_version
  api_key_enabled       = false

  identity {
    type = "SystemAssigned"
  }

  azure_monitor_workspace_integrations {
    resource_id = azurerm_monitor_workspace.this.id
  }
}

resource "azurerm_role_assignment" "grafana_monitor_workspace" {
  scope                = azurerm_monitor_workspace.this.id
  role_definition_name = "Monitoring Data Reader"
  principal_id         = azurerm_dashboard_grafana.this.identity[0].principal_id
  principal_type       = "ServicePrincipal"
}

# Selected tracing destination. OTel Collector와 ingestion credential/identity는 후속 work unit이 소유한다.
resource "azurerm_application_insights" "this" {
  name                = var.names.application_insights
  resource_group_name = var.resource_group_name
  location            = var.location
  application_type    = "other"
  workspace_id        = azurerm_log_analytics_workspace.this.id
}
