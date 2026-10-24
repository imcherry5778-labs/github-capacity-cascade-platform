variable "subscription_id" {
  description = "승인된 environment 대상 subscription ID. 실제 값은 local/CI input으로만 전달한다."
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
  description = "bootstrap이 소유하는 기존 environment Resource Group 이름. 이 stack은 RG를 만들지 않는다."
  type        = string
  nullable    = false
}

variable "location" {
  description = "단일 region. 후속 paid-run preflight에서 AKS version/Istio revision/SKU availability와 함께 선택한다."
  type        = string
  nullable    = false
}

variable "names" {
  description = "Environment resource 이름. 전역 고유 이름(PostgreSQL/ACR/Grafana)은 operator가 충돌 없이 고른다."
  type = object({
    virtual_network         = string
    kubernetes_cluster      = string
    postgresql_server       = string
    container_registry      = string
    log_analytics_workspace = string
    monitor_workspace       = string
    grafana                 = string
    application_insights    = string
  })
  nullable = false

  validation {
    # 파생 이름(DCE `<cluster>-prometheus` 최대 44자)이 Azure 길이 제한 안에 들어오도록 33자로 제한한다.
    condition     = can(regex("^[a-z0-9][a-z0-9-]{0,31}[a-z0-9]$", var.names.kubernetes_cluster))
    error_message = "kubernetes_cluster 이름은 소문자/숫자/하이픈 2~33자여야 한다."
  }

  validation {
    condition     = can(regex("^[a-z0-9][a-z0-9-]{1,61}[a-z0-9]$", var.names.postgresql_server))
    error_message = "postgresql_server 이름은 소문자/숫자/하이픈 3~63자여야 한다."
  }

  validation {
    condition     = can(regex("^[a-zA-Z0-9]{5,50}$", var.names.container_registry))
    error_message = "container_registry 이름은 영문/숫자 5~50자여야 한다."
  }

  validation {
    condition     = can(regex("^[a-zA-Z][a-zA-Z0-9-]{0,21}[a-zA-Z0-9]$", var.names.grafana))
    error_message = "grafana 이름은 영문으로 시작하는 영문/숫자/하이픈 2~23자여야 한다."
  }
}

variable "key_vault_id" {
  description = "foundation key_vault.id output. 이 stack은 vault를 참조만 하고 생성/변경하지 않는다."
  type        = string
  nullable    = false

  validation {
    condition     = can(regex("(?i)^/subscriptions/[^/]+/resourceGroups/[^/]+/providers/Microsoft\\.KeyVault/vaults/[^/]+$", var.key_vault_id))
    error_message = "key_vault_id는 기존 Key Vault의 ARM resource ID여야 한다."
  }

  validation {
    condition     = startswith(lower(var.key_vault_id), lower("/subscriptions/${var.subscription_id}/resourceGroups/${var.foundation_resource_group_name}/providers/Microsoft.KeyVault/vaults/"))
    error_message = "Key Vault role은 같은 subscription의 승인된 foundation RG 안으로 제한한다."
  }
}

variable "foundation_resource_group_name" {
  description = "bootstrap resource_group_names.foundation. Cross-RG workload RBAC boundary 검증용이다."
  type        = string
  nullable    = false
}

variable "dns_zone_id" {
  description = "foundation dns_zone.id. cert-manager의 zone-scoped role에만 사용한다."
  type        = string
  nullable    = false

  validation {
    condition     = can(regex("(?i)^/subscriptions/[^/]+/resourceGroups/[^/]+/providers/Microsoft\\.Network/dnsZones/[^/]+$", var.dns_zone_id)) && startswith(lower(var.dns_zone_id), lower("/subscriptions/${var.subscription_id}/resourceGroups/${var.foundation_resource_group_name}/providers/Microsoft.Network/dnsZones/"))
    error_message = "dns_zone_id는 같은 subscription의 승인된 foundation RG public DNS zone이어야 한다."
  }
}

variable "network" {
  description = <<-EOT
    단일 VNet과 책임별 subnet, AKS overlay pod/service CIDR. 모든 값은 IPv4 canonical CIDR이다.
    subnet은 VNet 안에서 서로 겹치지 않고, pod/service CIDR은 VNet 및 서로와 겹치지 않아야 한다.
  EOT
  type = object({
    address_space = string
    subnets = object({
      aks_nodes         = string
      postgresql        = string
      private_endpoints = string
    })
    kubernetes = object({
      pod_cidr       = string
      service_cidr   = string
      dns_service_ip = string
    })
  })
  nullable = false

  validation {
    condition = alltrue([
      for cidr in concat([var.network.address_space], values(var.network.subnets),
      [var.network.kubernetes.pod_cidr, var.network.kubernetes.service_cidr]) :
      try(cidrhost(cidr, 0) == split("/", cidr)[0] && can(cidrnetmask(cidr)), false)
    ])
    error_message = "network CIDR은 host bit가 없는 IPv4 CIDR이어야 한다."
  }

  validation {
    condition = alltrue([
      for subnet in values(var.network.subnets) : try(
        tonumber(split("/", subnet)[1]) >= tonumber(split("/", var.network.address_space)[1]) &&
        cidrhost("${split("/", subnet)[0]}/${split("/", var.network.address_space)[1]}", 0) == split("/", var.network.address_space)[0],
      false)
    ])
    error_message = "모든 subnet은 network.address_space 안에 있어야 한다."
  }

  validation {
    # 두 CIDR은 어느 한쪽 prefix 길이로 다른 쪽 network address를 mask했을 때 같으면 겹친다.
    condition = alltrue(flatten([
      for i, a in values(var.network.subnets) : [
        for j, b in values(var.network.subnets) : j <= i || try(
          cidrhost("${split("/", b)[0]}/${split("/", a)[1]}", 0) != split("/", a)[0] &&
          cidrhost("${split("/", a)[0]}/${split("/", b)[1]}", 0) != split("/", b)[0],
        false)
      ]
    ]))
    error_message = "AKS node, PostgreSQL delegated, private endpoint subnet은 서로 겹치지 않아야 한다."
  }

  validation {
    condition = alltrue(flatten([
      for i, a in [var.network.address_space, var.network.kubernetes.pod_cidr, var.network.kubernetes.service_cidr] : [
        for j, b in [var.network.address_space, var.network.kubernetes.pod_cidr, var.network.kubernetes.service_cidr] : j <= i || try(
          cidrhost("${split("/", b)[0]}/${split("/", a)[1]}", 0) != split("/", a)[0] &&
          cidrhost("${split("/", a)[0]}/${split("/", b)[1]}", 0) != split("/", b)[0],
        false)
      ]
    ]))
    error_message = "VNet, AKS pod CIDR, service CIDR은 서로 겹치지 않아야 한다."
  }

  validation {
    # PostgreSQL Flexible Server delegated subnet의 최소 크기는 /28이다.
    condition     = try(tonumber(split("/", var.network.subnets.postgresql)[1]) <= 28, false)
    error_message = "PostgreSQL delegated subnet은 /28 이상 크기여야 한다."
  }

  validation {
    condition = try(
      cidrhost("${var.network.kubernetes.dns_service_ip}/${split("/", var.network.kubernetes.service_cidr)[1]}", 0) == split("/", var.network.kubernetes.service_cidr)[0] &&
      var.network.kubernetes.dns_service_ip != split("/", var.network.kubernetes.service_cidr)[0] &&
      can(regex("^[0-9]+\\.[0-9]+\\.[0-9]+\\.[0-9]+$", var.network.kubernetes.dns_service_ip)),
    false)
    error_message = "dns_service_ip는 service_cidr 안의 첫 번째가 아닌 IPv4 address여야 한다."
  }
}

variable "kubernetes" {
  description = <<-EOT
    AKS control plane/system pool 입력. version/Istio revision은 paid-run 전 `az aks get-versions`,
    `az aks mesh get-revisions`로 선택 region에서 확인한다. VM SKU/count는 측정 전 capacity baseline이 아니다.
    api_server_authorized_ip_ranges가 빈 set이면 public API endpoint는 IP 제한 없이 Entra ID 인증만 요구한다.
  EOT
  type = object({
    version        = string
    istio_revision = string
    sku_tier       = string
    system_node_pool = object({
      vm_size    = string
      node_count = number
    })
    api_server_authorized_ip_ranges = set(string)
  })
  nullable = false

  validation {
    condition     = can(regex("^1\\.[0-9]+(\\.[0-9]+)?$", var.kubernetes.version))
    error_message = "kubernetes.version은 1.<minor> 또는 1.<minor>.<patch> 형식이어야 한다."
  }

  validation {
    condition     = can(regex("^asm-1-[0-9]+$", var.kubernetes.istio_revision))
    error_message = "kubernetes.istio_revision은 AKS managed Istio revision(asm-1-<minor>) 형식이어야 한다."
  }

  validation {
    condition     = contains(["Free", "Standard"], var.kubernetes.sku_tier)
    error_message = "kubernetes.sku_tier는 Free 또는 Standard여야 한다."
  }

  validation {
    condition     = var.kubernetes.system_node_pool.node_count >= 2 && floor(var.kubernetes.system_node_pool.node_count) == var.kubernetes.system_node_pool.node_count
    error_message = "system_node_pool.node_count는 2 이상의 정수여야 한다."
  }

  validation {
    condition = alltrue([
      for cidr in var.kubernetes.api_server_authorized_ip_ranges :
      try(cidrhost(cidr, 0) == split("/", cidr)[0] && can(cidrnetmask(cidr)), false)
    ])
    error_message = "api_server_authorized_ip_ranges는 host bit가 없는 IPv4 CIDR이어야 한다."
  }
}

variable "postgresql" {
  description = "PostgreSQL Flexible Server 입력. SKU/storage는 측정 전 capacity baseline이 아니다."
  type = object({
    version                        = string
    sku_name                       = string
    storage_mb                     = number
    database_name                  = string
    administrator_login            = string
    administrator_password_version = number
  })
  nullable = false

  validation {
    condition = (
      can(regex("^[a-z][a-z0-9_]{0,62}$", var.postgresql.administrator_login)) &&
      !startswith(var.postgresql.administrator_login, "pg_") &&
      !contains(["admin", "administrator", "azure_pg_admin", "azure_superuser", "guest", "public", "root", "sa"], var.postgresql.administrator_login)
    )
    error_message = "administrator_login은 소문자 identifier이고 PostgreSQL/Azure reserved name이 아니어야 한다."
  }

  validation {
    condition     = can(regex("^[a-z][a-z0-9_]{0,62}$", var.postgresql.database_name))
    error_message = "database_name은 소문자 PostgreSQL identifier여야 한다."
  }

  validation {
    condition     = var.postgresql.administrator_password_version >= 1 && floor(var.postgresql.administrator_password_version) == var.postgresql.administrator_password_version
    error_message = "administrator_password_version은 1 이상의 정수이며 password rotation 때만 증가시킨다."
  }
}

variable "postgresql_administrator_password" {
  description = <<-EOT
    PostgreSQL 초기화 administrator password. ephemeral input이며 write-only attribute로만 전달되어
    plan/state에 저장되지 않는다. 실제 값은 commit하지 않고 실행 시점 secret input으로만 전달한다.
  EOT
  type        = string
  sensitive   = true
  ephemeral   = true
  nullable    = false

  validation {
    condition     = length(var.postgresql_administrator_password) >= 16 && length(var.postgresql_administrator_password) <= 128
    error_message = "postgresql_administrator_password는 16~128자여야 한다."
  }
}

variable "container_registry_sku" {
  description = "Premium/private link 없이 project image를 보관할 ACR SKU. 비용 선택은 paid-run preflight에서 한다."
  type        = string
  nullable    = false

  validation {
    condition     = contains(["Basic", "Standard"], var.container_registry_sku)
    error_message = "container_registry_sku는 Basic 또는 Standard여야 한다."
  }
}

variable "monitoring" {
  description = "Managed observability destination 입력. retention/stream/interval은 측정 전 final 값이 아니다."
  type = object({
    log_analytics_retention_in_days = number
    container_insights_streams      = list(string)
    container_insights_interval     = string
    grafana_major_version           = string
  })
  nullable = false

  validation {
    condition     = var.monitoring.log_analytics_retention_in_days >= 30 && var.monitoring.log_analytics_retention_in_days <= 730
    error_message = "log_analytics_retention_in_days는 30~730이어야 한다."
  }

  validation {
    # Microsoft Container Insights onboarding template가 정의한 stream 집합 안에서만 고른다.
    condition = length(var.monitoring.container_insights_streams) > 0 && alltrue([
      for stream in var.monitoring.container_insights_streams : contains([
        "Microsoft-ContainerLog", "Microsoft-ContainerLogV2", "Microsoft-KubeEvents", "Microsoft-KubePodInventory",
        "Microsoft-KubeNodeInventory", "Microsoft-KubePVInventory", "Microsoft-KubeServices", "Microsoft-KubeMonAgentEvents",
        "Microsoft-InsightsMetrics", "Microsoft-ContainerInventory", "Microsoft-ContainerNodeInventory", "Microsoft-Perf",
      ], stream)
    ])
    error_message = "container_insights_streams는 비어 있지 않은 Container Insights stream 목록이어야 한다."
  }

  validation {
    condition     = can(regex("^([1-9]|[12][0-9]|30)m$", var.monitoring.container_insights_interval))
    error_message = "container_insights_interval은 1m~30m이어야 한다."
  }

  validation {
    condition     = contains(["12", "13"], var.monitoring.grafana_major_version)
    error_message = "grafana_major_version은 AzureRM 5.11.0이 허용하는 12 또는 13이어야 한다."
  }
}
