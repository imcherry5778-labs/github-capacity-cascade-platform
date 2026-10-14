terraform {
  required_version = "= 1.16.4"

  # bootstrap의 state container에 별도 key로 저장한다. account/container/tenant/client는
  # bootstrap backend_config output을 -backend-config runtime input으로 전달한다.
  backend "azurerm" {
    key                  = "environment.tfstate"
    use_oidc             = true
    use_azuread_auth     = true
    lookup_blob_endpoint = false
    use_cli              = false
    use_msi              = false
  }

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
  client_id                       = var.ci_client_id
  environment                     = "public"
  use_oidc                        = true
  use_cli                         = false
  use_msi                         = false
  resource_provider_registrations = "none"
}
