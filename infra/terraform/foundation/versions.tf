terraform {
  required_version = "= 1.16.7"

  # bootstrap의 state container에 별도 key로 저장한다. account/container/tenant/client는
  # bootstrap backend_config output을 -backend-config runtime input으로 전달한다.
  backend "azurerm" {
    key                  = "foundation.tfstate"
    use_oidc             = true
    use_azuread_auth     = true
    lookup_blob_endpoint = false
    use_cli              = false
    use_msi              = false
  }

  required_providers {
    azurerm = {
      source  = "hashicorp/azurerm"
      version = "= 5.11.0"
    }
  }
}

provider "azurerm" {
  features {
    key_vault {
      # Vault purge/recover는 subscription-scope 권한이 필요하다. CI는 foundation RG 권한만 가지므로
      # destroy는 soft-delete까지만 수행하고 Azure가 retention 만료 후 purge한다.
      # 이전에 삭제된 vault를 자동 recover하지 않는다. 재배포는 충돌하지 않는 이름을 사용한다.
      purge_soft_delete_on_destroy    = false
      recover_soft_deleted_key_vaults = false
    }
  }

  subscription_id                 = var.subscription_id
  tenant_id                       = var.tenant_id
  client_id                       = var.ci_client_id
  environment                     = "public"
  use_oidc                        = true
  use_cli                         = false
  use_msi                         = false
  resource_provider_registrations = "none"
}
