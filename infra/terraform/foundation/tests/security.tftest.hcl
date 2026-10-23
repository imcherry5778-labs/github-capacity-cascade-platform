# 전부 mock + plan이다. Azure credential/API, remote backend와 실제 apply가 필요하지 않다.
mock_provider "azurerm" {
  override_during = plan

  mock_resource "azurerm_dns_zone" {
    defaults = {
      id           = "/subscriptions/00000000-0000-0000-0000-000000000000/resourceGroups/test-foundation/providers/Microsoft.Network/dnsZones/example.test"
      name_servers = ["ns1-01.azure-dns.com.", "ns2-01.azure-dns.net.", "ns3-01.azure-dns.org.", "ns4-01.azure-dns.info."]
    }
  }

  mock_resource "azurerm_key_vault" {
    defaults = {
      id        = "/subscriptions/00000000-0000-0000-0000-000000000000/resourceGroups/test-foundation/providers/Microsoft.KeyVault/vaults/test-foundation-kv"
      vault_uri = "https://test-foundation-kv.vault.azure.net/"
    }
  }
}

variables {
  subscription_id     = "00000000-0000-0000-0000-000000000000"
  tenant_id           = "00000000-0000-0000-0000-000000000000"
  ci_client_id        = "11111111-1111-1111-1111-111111111111"
  resource_group_name = "test-foundation"
  location            = "test-location"
  dns_zone_name       = "example.test"
  key_vault_name      = "test-foundation-kv"
}

run "shared_resource_contract" {
  command = plan

  assert {
    condition = (
      azurerm_dns_zone.project.name == "example.test" &&
      azurerm_dns_zone.project.resource_group_name == "test-foundation" &&
      output.dns_zone.id == azurerm_dns_zone.project.id &&
      output.dns_zone.name == "example.test" &&
      output.dns_zone.name_servers == azurerm_dns_zone.project.name_servers &&
      length(output.dns_zone.name_servers) == 4
    )
    error_message = "기존 foundation RG에 apex zone 이름을 그대로 전달하고 registrar delegation용 Azure name server 4개를 출력해야 한다."
  }

  assert {
    condition = (
      azurerm_key_vault.project.resource_group_name == "test-foundation" &&
      azurerm_key_vault.project.location == "test-location" &&
      azurerm_key_vault.project.tenant_id == var.tenant_id &&
      azurerm_key_vault.project.sku_name == "standard" &&
      azurerm_key_vault.project.rbac_authorization_enabled == true &&
      azurerm_key_vault.project.public_network_access_enabled == false &&
      azurerm_key_vault.project.soft_delete_retention_days == 7 &&
      azurerm_key_vault.project.purge_protection_enabled == false
    )
    error_message = "Key Vault는 standard/RBAC/public access 비활성/7일 soft-delete/purge protection 미사용이어야 한다."
  }

  assert {
    condition = (
      output.key_vault.id == azurerm_key_vault.project.id &&
      output.key_vault.name == "test-foundation-kv" &&
      output.key_vault.uri == "https://test-foundation-kv.vault.azure.net/"
    )
    error_message = "Key Vault output은 non-secret ID/name/URI metadata만 노출해야 한다."
  }
}
