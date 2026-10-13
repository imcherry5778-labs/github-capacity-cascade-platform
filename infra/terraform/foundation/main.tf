resource "azurerm_dns_zone" "project" {
  name                = var.dns_zone_name
  resource_group_name = var.resource_group_name
}

resource "azurerm_key_vault" "project" {
  name                = var.key_vault_name
  resource_group_name = var.resource_group_name
  location            = var.location
  tenant_id           = var.tenant_id
  sku_name            = "standard"

  # Data plane은 Azure RBAC만 사용하고 public endpoint를 열지 않는다.
  # Private endpoint가 생기기 전까지 data-plane 접근은 의도적으로 불가능하다.
  rbac_authorization_enabled    = true
  public_network_access_enabled = false

  # Azure 최소 retention. Purge protection은 되돌릴 수 없어 cleanup/name reuse lifecycle을 바꾸므로 켜지 않는다.
  soft_delete_retention_days = 7
  purge_protection_enabled   = false
}
