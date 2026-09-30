variable "subscription_id" {
  description = "승인된 bootstrap 대상 subscription ID. 실제 값은 local input으로만 전달한다."
  type        = string
  nullable    = false
}

variable "tenant_id" {
  description = "승인된 Microsoft Entra tenant ID. 실제 값은 local input으로만 전달한다."
  type        = string
  nullable    = false
}

variable "location" {
  description = "후속 paid-run preflight에서 선택할 Azure location. P5-W1은 region을 선택하지 않는다."
  type        = string
  nullable    = false
}

variable "resource_group_names" {
  description = "이 프로젝트가 새로 소유할 bootstrap/foundation/environment Resource Group 이름."
  type = object({
    bootstrap   = string
    foundation  = string
    environment = string
  })
  nullable = false

  validation {
    condition     = length(distinct([for name in values(var.resource_group_names) : lower(name)])) == 3
    error_message = "bootstrap/foundation/environment는 서로 다른 Resource Group이어야 한다."
  }
}

variable "state_storage_account_name" {
  description = "전역적으로 고유한 state Storage Account 이름."
  type        = string
  nullable    = false

  validation {
    condition     = can(regex("^[a-z0-9]{3,24}$", var.state_storage_account_name))
    error_message = "Storage Account 이름은 소문자/숫자 3~24자여야 한다."
  }
}

variable "state_storage_sku" {
  description = "후속 cost/region preflight에서 선택할 state storage tier/replication. P5-W1은 SKU를 선택하지 않는다."
  type = object({
    tier             = string
    replication_type = string
  })
  nullable = false
}

variable "state_container_name" {
  description = "foundation/environment가 서로 다른 state blob key를 사용할 private container."
  type        = string
  default     = "tfstate"
  nullable    = false
}

variable "ci_identity_name" {
  description = "GitHub Actions용 단일 User Assigned Managed Identity 이름."
  type        = string
  nullable    = false
}
