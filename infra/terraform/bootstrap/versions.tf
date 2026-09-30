terraform {
  required_version = "= 1.16.4"

  # bootstrap만 implicit local state를 사용한다. 자신의 state backend를 참조하지 않는다.
  required_providers {
    azurerm = {
      source  = "hashicorp/azurerm"
      version = "= 5.7.0"
    }
  }
}

provider "azurerm" {
  features {}

  subscription_id                 = var.subscription_id
  tenant_id                       = var.tenant_id
  environment                     = "public"
  storage_use_azuread             = true
  resource_provider_registrations = "none"
}
