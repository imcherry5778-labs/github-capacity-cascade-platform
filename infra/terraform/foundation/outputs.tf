output "dns_zone" {
  description = "Project public zone. name_servers는 parent authority delegation 입력이며 delegation 완료 증거가 아니다."
  value = {
    id           = azurerm_dns_zone.project.id
    name         = azurerm_dns_zone.project.name
    name_servers = azurerm_dns_zone.project.name_servers
  }
}

output "key_vault" {
  description = "후속 private connectivity/workload access가 참조할 non-secret Key Vault metadata."
  value = {
    id   = azurerm_key_vault.project.id
    name = azurerm_key_vault.project.name
    uri  = azurerm_key_vault.project.vault_uri
  }
}
