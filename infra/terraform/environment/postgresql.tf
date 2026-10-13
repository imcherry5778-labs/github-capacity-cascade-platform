# Private access(VNet integration): delegated subnet + private DNS zone만 사용한다.
# 이 방식에서는 PostgreSQL private endpoint를 함께 만들지 않는다.
resource "azurerm_private_dns_zone" "postgresql" {
  # `<name>.postgres.database.azure.com`은 server 이름과 같으면 안 되므로 한 단계 더 둔다.
  name                = "${var.names.postgresql_server}.private.postgres.database.azure.com"
  resource_group_name = var.resource_group_name
}

resource "azurerm_private_dns_zone_virtual_network_link" "postgresql" {
  name                 = "postgresql"
  private_dns_zone_id  = azurerm_private_dns_zone.postgresql.id
  virtual_network_id   = azurerm_virtual_network.this.id
  registration_enabled = false
}

resource "azurerm_postgresql_flexible_server" "this" {
  name                = var.names.postgresql_server
  resource_group_name = var.resource_group_name
  location            = var.location
  version             = var.postgresql.version
  sku_name            = var.postgresql.sku_name
  storage_mb          = var.postgresql.storage_mb

  delegated_subnet_id           = azurerm_subnet.postgresql.id
  private_dns_zone_id           = azurerm_private_dns_zone.postgresql.id
  public_network_access_enabled = false
  geo_redundant_backup_enabled  = false

  # 초기화 credential만 둔다. write-only attribute라 password가 plan/state에 저장되지 않으며,
  # rotation은 administrator_password_version을 올려서만 적용한다.
  administrator_login               = var.postgresql.administrator_login
  administrator_password_wo         = var.postgresql_administrator_password
  administrator_password_wo_version = var.postgresql.administrator_password_version

  authentication {
    password_auth_enabled         = true
    active_directory_auth_enabled = false
  }

  lifecycle {
    # Azure가 zone을 배정한다. 배정 결과를 되돌리는 update를 만들지 않는다.
    ignore_changes = [zone]
  }

  depends_on = [azurerm_private_dns_zone_virtual_network_link.postgresql]
}

resource "azurerm_postgresql_flexible_server_database" "application" {
  name      = var.postgresql.database_name
  server_id = azurerm_postgresql_flexible_server.this.id
  charset   = "UTF8"
  collation = "en_US.utf8"
}
