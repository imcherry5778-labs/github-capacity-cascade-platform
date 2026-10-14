resource "azurerm_virtual_network" "this" {
  name                = var.names.virtual_network
  resource_group_name = var.resource_group_name
  location            = var.location
  address_space       = [var.network.address_space]
}

# 모든 subnet은 implicit default outbound access를 쓰지 않는다. AKS egress는 cluster의
# Standard Load Balancer outbound rule이 명시적으로 제공한다.
resource "azurerm_subnet" "aks_nodes" {
  name                            = "aks-nodes"
  resource_group_name             = var.resource_group_name
  virtual_network_name            = azurerm_virtual_network.this.name
  address_prefixes                = [var.network.subnets.aks_nodes]
  default_outbound_access_enabled = false
}

resource "azurerm_subnet" "postgresql" {
  name                            = "postgresql"
  resource_group_name             = var.resource_group_name
  virtual_network_name            = azurerm_virtual_network.this.name
  address_prefixes                = [var.network.subnets.postgresql]
  default_outbound_access_enabled = false

  # Azure는 첫 server 생성 시 WAL archive용 Microsoft.Storage service endpoint를 이 subnet에 추가한다.
  # Source에 선언해 Terraform이 이를 drift로 보고 제거하지 않게 한다.
  service_endpoint {
    service = "Microsoft.Storage"
  }

  delegation {
    name = "postgresql-flexible-server"

    service_delegation {
      name    = "Microsoft.DBforPostgreSQL/flexibleServers"
      actions = ["Microsoft.Network/virtualNetworks/subnets/join/action"]
    }
  }
}

resource "azurerm_subnet" "private_endpoints" {
  name                            = "private-endpoints"
  resource_group_name             = var.resource_group_name
  virtual_network_name            = azurerm_virtual_network.this.name
  address_prefixes                = [var.network.subnets.private_endpoints]
  default_outbound_access_enabled = false
}

# foundation Key Vault는 public network access가 꺼져 있다. 이 private endpoint와 privatelink zone이
# VNet 안의 유일한 data-plane 경로다. Vault 자체와 secret/role은 이 stack이 소유하지 않는다.
resource "azurerm_private_dns_zone" "key_vault" {
  name                = "privatelink.vaultcore.azure.net"
  resource_group_name = var.resource_group_name
}

resource "azurerm_private_dns_zone_virtual_network_link" "key_vault" {
  name                 = "key-vault"
  private_dns_zone_id  = azurerm_private_dns_zone.key_vault.id
  virtual_network_id   = azurerm_virtual_network.this.id
  registration_enabled = false
}

resource "azurerm_private_endpoint" "key_vault" {
  name                = "${var.names.virtual_network}-key-vault"
  resource_group_name = var.resource_group_name
  location            = var.location
  subnet_id           = azurerm_subnet.private_endpoints.id

  private_service_connection {
    name                           = "key-vault"
    private_connection_resource_id = var.key_vault_id
    subresource_names              = ["vault"]
    is_manual_connection           = false
  }

  private_dns_zone_group {
    name                 = "key-vault"
    private_dns_zone_ids = [azurerm_private_dns_zone.key_vault.id]
  }
}
