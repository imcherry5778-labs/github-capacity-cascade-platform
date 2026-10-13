variable "subscription_id" {
  description = "승인된 foundation 대상 subscription ID. 실제 값은 local/CI input으로만 전달한다."
  type        = string
  nullable    = false
}

variable "tenant_id" {
  description = "bootstrap backend_config.tenant_id와 같은 Microsoft Entra tenant ID."
  type        = string
  nullable    = false
}

variable "ci_client_id" {
  description = "bootstrap ci_identity.client_id. GitHub Actions OIDC federation 대상 identity다."
  type        = string
  nullable    = false
}

variable "resource_group_name" {
  description = "bootstrap이 소유하는 기존 foundation Resource Group 이름. 이 stack은 RG를 만들지 않는다."
  type        = string
  nullable    = false
}

variable "location" {
  description = "Key Vault Azure location. 후속 paid-run preflight에서 선택한다."
  type        = string
  nullable    = false
}

variable "dns_zone_name" {
  description = "Parent DNS authority가 나중에 delegate할 project public subdomain zone 이름."
  type        = string
  nullable    = false
}

variable "key_vault_name" {
  description = "전역적으로 고유한 Key Vault 이름."
  type        = string
  nullable    = false
}
