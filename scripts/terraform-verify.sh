#!/usr/bin/env bash
# P5 bootstrap/foundation/environment: clean source copy, empty CLI config/environment, mock-only plan. Azure API를 호출하지 않는다.
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
# shellcheck source=versions.env
source "$ROOT/versions.env"
TF="$ROOT/.tmp/bin/terraform"
[[ "$("$TF" version -json | jq -r .terraform_version)" == "$TERRAFORM_VERSION" ]]

python3 - "$ROOT" "$TERRAFORM_VERSION" "$AZURERM_VERSION" <<'PY'
from pathlib import Path
import json, re, sys
root, terraform, azurerm = Path(sys.argv[1]), *sys.argv[2:]
base = root / "infra/terraform"
assert {p.name for p in base.iterdir()} == {"bootstrap", "foundation", "environment"}, "P5 Terraform stacks are bootstrap/foundation/environment only"
stack = base / "bootstrap"
source = "\n".join(p.read_text() for p in stack.glob("*.tf"))
assert not list(stack.glob("*.tf.json")), "unexpected alternative Terraform source"
assert not re.search(r'\b(backend|module|data|provisioner)\s+"', source), "local-state/resource-only bootstrap required"
expected = {
    ("azurerm_resource_group", "boundary"), ("azurerm_storage_account", "state"),
    ("azurerm_storage_container", "state"), ("azurerm_user_assigned_identity", "ci"),
    ("azurerm_federated_identity_credential", "azure"),
    *(('azurerm_role_assignment', name) for name in ('state', 'contributor', 'rbac')),
}
resources = re.findall(r'\bresource\s+"([^"]+)"\s+"([^"]+)"', source)
assert len(resources) == len(expected) and set(resources) == expected, "unexpected bootstrap resource inventory"
assert f'required_version = "= {terraform}"' in source, "Terraform pin mismatch"
assert re.search(r'version\s*=\s*"= ' + re.escape(azurerm) + '"', source), "AzureRM pin mismatch"
assert re.search(r'resource_provider_registrations\s*=\s*"none"', source), "automatic RP registration forbidden"
assert re.search(r'storage_use_azuread\s*=\s*true', source), "Entra ID storage authentication required"
evidence = json.loads((stack / "oidc-inspection.json").read_text())
oidc = evidence["oidc_configuration"]
assert oidc["use_default"] is True and oidc["use_immutable_subject"] is True
assert oidc["sub_claim_prefix"] == "repo:imcherry5778-labs@273613742/github-capacity-cascade-platform@1384941385"
environment = evidence["environment"]
assert environment["name"] == "azure"
assert environment["deployment_branch_policy"] == {"protected_branches": False, "custom_branch_policies": True}
assert [rule["type"] for rule in environment["protection_rules"]] == ["branch_policy"], "unexpected Environment protection"
policies = evidence["deployment_branch_policies"]
assert policies["total_count"] == 1
assert [{key: policy[key] for key in ("name", "type")} for policy in policies["branch_policies"]] == [{"name": "main", "type": "branch"}]
assert evidence["deployment_protection_rules"] == {"total_count": 0, "custom_deployment_protection_rules": []}
subject = oidc["sub_claim_prefix"] + ":environment:" + environment["name"]
assert evidence["derived_environment_subject"] == subject
assert re.findall(r'github_environment_subject\s*=\s*"([^"]+)"', source) == [subject], "immutable Environment subject required"
assert ":ref:refs/heads/main" not in source, "branch-only federation subject forbidden"
tests = list((stack / "tests").glob("*"))
assert [p.name for p in tests] == ["security.tftest.hcl"], "unexpected Terraform test"
test = tests[0].read_text()
assert re.findall(r'\bmock_provider\s+"([^"]+)"', test) == ["azurerm"]
assert not re.search(r'\b(provider|module)\s*("|{)|\bproviders\s*=', test), "real test provider/module forbidden"
commands = re.findall(r'\bcommand\s*=\s*(\w+)', test)
assert commands and all(command == "plan" for command in commands), "mock plan only"
print("[terraform-verify] PASS bootstrap inventory/local state/pins/Environment OIDC/mock-only guard")

stack = base / "foundation"
source = "\n".join(p.read_text() for p in stack.glob("*.tf"))
assert not list(stack.glob("*.tf.json")), "unexpected alternative Terraform source"
assert (stack / ".terraform.lock.hcl").is_file(), "committed provider lockfile required"
assert not re.search(r'\b(module|data|provisioner)\s+"', source), "resource-only foundation required"
backends = re.findall(r'\bbackend\s+"([^"]+)"\s*\{([^}]*)\}', source)
assert [name for name, _ in backends] == ["azurerm"], "single azurerm remote backend required"
backend = dict(re.findall(r'^\s*(\w+)\s*=\s*(\S+)\s*$', backends[0][1], re.M))
assert backend == {
    "key": '"foundation.tfstate"', "use_oidc": "true", "use_azuread_auth": "true",
    "lookup_blob_endpoint": "false", "use_cli": "false", "use_msi": "false",
}, "foundation backend must be OIDC + Entra ID with runtime account/container/tenant/client inputs"
assert not re.search(r'\b(client_secret\w*|client_certificate\w*|access_key|sas_token|oidc_token\w*|msi_endpoint)\s*=', source), \
    "long-lived or committed Azure credential forbidden"
# backend + provider 각각 OIDC만 허용한다. Provider client_id는 bootstrap CI identity input이다.
for setting, count in ((r'use_oidc\s*=\s*true', 2), (r'use_cli\s*=\s*false', 2), (r'use_msi\s*=\s*false', 2),
                       (r'client_id\s*=\s*var\.ci_client_id', 1)):
    assert len(re.findall(setting, source)) == count, f"OIDC-only provider/backend: {setting}"
assert f'required_version = "= {terraform}"' in source, "Terraform pin mismatch"
assert re.search(r'version\s*=\s*"= ' + re.escape(azurerm) + '"', source), "AzureRM pin mismatch"
assert re.search(r'resource_provider_registrations\s*=\s*"none"', source), "automatic RP registration forbidden"
# CI에는 subscription-scope deleted-vault purge/recover 권한이 없다. 두 feature 모두 명시적으로 끈다.
def key_vault_features(text):
    block = re.search(r'\bkey_vault\s*\{([^}]*)\}', text)
    return block and dict(re.findall(r'^\s*(\w+)\s*=\s*(\S+)\s*$', block.group(1), re.M))
expected_features = {"purge_soft_delete_on_destroy": "false", "recover_soft_deleted_key_vaults": "false"}
assert key_vault_features(source) == expected_features, \
    "Key Vault provider features must disable purge-on-destroy and automatic soft-deleted vault recovery"
# Negative regression: recovery feature를 제거하거나 켜면 위 contract가 거부해야 한다.
recover = r'^[ \t]*recover_soft_deleted_key_vaults\s*=\s*false[ \t]*\n'
for mutated in (re.sub(recover, "", source, flags=re.M),
                re.sub(recover, "      recover_soft_deleted_key_vaults = true\n", source, flags=re.M)):
    assert mutated != source and key_vault_features(mutated) != expected_features, \
        "automatic Key Vault recovery removal/enablement must fail the static contract"
resources = re.findall(r'\bresource\s+"([^"]+)"\s+"([^"]+)"', source)
assert sorted(resources) == [("azurerm_dns_zone", "project"), ("azurerm_key_vault", "project")], \
    "foundation inventory is one public DNS zone and one Key Vault only"
assert not re.search(r'\b(access_policy|network_acls)\b', source), "legacy access policy/network ACL forbidden"
vault = re.search(r'resource\s+"azurerm_key_vault"\s+"project"\s*\{(.*?)\n\}', source, re.S).group(1)
for setting in (r'sku_name\s*=\s*"standard"', r'rbac_authorization_enabled\s*=\s*true',
                r'public_network_access_enabled\s*=\s*false', r'soft_delete_retention_days\s*=\s*7\b',
                r'purge_protection_enabled\s*=\s*false', r'resource_group_name\s*=\s*var\.resource_group_name'):
    assert re.search(setting, vault), f"Key Vault contract: {setting}"
outputs = dict(re.findall(r'\boutput\s+"([^"]+)"\s*\{(.*?)\n\}', source, re.S))
assert set(outputs) == {"dns_zone", "key_vault"}, "unexpected foundation outputs"
assert "azurerm_dns_zone.project.name_servers" in outputs["dns_zone"], "delegation name servers output required"
assert sorted(re.findall(r'azurerm_key_vault\.project\.(\w+)', outputs["key_vault"])) == ["id", "name", "vault_uri"], \
    "Key Vault output is non-secret ID/name/URI metadata only"
tests = list((stack / "tests").glob("*"))
assert [p.name for p in tests] == ["security.tftest.hcl"], "unexpected Terraform test"
test = tests[0].read_text()
assert re.findall(r'\bmock_provider\s+"([^"]+)"', test) == ["azurerm"]
assert not re.search(r'\b(provider|module)\s*("|{)|\bproviders\s*=', test), "real test provider/module forbidden"
commands = re.findall(r'\bcommand\s*=\s*(\w+)', test)
assert commands and all(command == "plan" for command in commands), "mock plan only"
print("[terraform-verify] PASS foundation inventory/remote backend/OIDC-only/Key Vault/recovery-negative/mock-only guard")
stack = base / "environment"
assert not list(stack.glob("*.tf.json")), "unexpected alternative Terraform source"
assert (stack / ".terraform.lock.hcl").read_text() == (base / "foundation/.terraform.lock.hcl").read_text(), \
    "environment lockfile must match the shared provider pin"
readme = (stack / "README.md").read_text()

def block(text, kind, name):
    match = re.search(r'\b' + kind + r'\s+"' + re.escape(name) + r'"\s*(?:"([^"]+)"\s*)?\{(.*?)\n\}', text, re.S)
    return match.group(2) if match else ""

def environment_violations(source):
    """Environment source contract. 실제 source는 위반이 없어야 하고 아래 mutation은 각각 거부되어야 한다."""
    v = []
    if re.search(r'\b(module|data|provisioner)\s+"', source):
        v.append("resource-only environment required")
    if re.findall(r'\bprovider\s+"([^"]+)"', source) != ["azurerm"] or len(re.findall(r'source\s*=\s*"', source)) != 1:
        v.append("azurerm is the only provider; Kubernetes/Helm/AzureAD providers belong to later work")
    backends = re.findall(r'\bbackend\s+"([^"]+)"\s*\{([^}]*)\}', source)
    if [name for name, _ in backends] != ["azurerm"] or dict(re.findall(r'^\s*(\w+)\s*=\s*(\S+)\s*$', backends[0][1], re.M)) != {
            "key": '"environment.tfstate"', "use_oidc": "true", "use_azuread_auth": "true",
            "lookup_blob_endpoint": "false", "use_cli": "false", "use_msi": "false"}:
        v.append("environment backend must be OIDC + Entra ID with key environment.tfstate and runtime account inputs")
    if re.search(r'\b(client_secret\w*|client_certificate\w*|access_key|sas_token|oidc_token\w*|msi_endpoint)\s*=', source):
        v.append("long-lived or committed Azure credential forbidden")
    for setting, count in ((r'use_oidc\s*=\s*true', 2), (r'use_cli\s*=\s*false', 2), (r'use_msi\s*=\s*false', 2),
                           (r'client_id\s*=\s*var\.ci_client_id', 1), (r'resource_provider_registrations\s*=\s*"none"', 1)):
        if len(re.findall(setting, source)) != count:
            v.append(f"OIDC-only provider/backend: {setting}")
    if f'required_version = "= {terraform}"' not in source or \
            not re.search(r'version\s*=\s*"= ' + re.escape(azurerm) + '"', source):
        v.append("Terraform/AzureRM pin mismatch")
    resources = sorted(re.findall(r'\bresource\s+"([^"]+)"\s+"([^"]+)"', source))
    if resources != expected_resources:
        v.append("unexpected environment inventory (RG/Key Vault/secret/workload/app resources are out of scope)")
    pg = block(source, "resource", "azurerm_postgresql_flexible_server")
    for setting in (r'public_network_access_enabled\s*=\s*false', r'delegated_subnet_id\s*=\s*azurerm_subnet\.postgresql\.id',
                    r'private_dns_zone_id\s*=\s*azurerm_private_dns_zone\.postgresql\.id',
                    r'administrator_password_wo\s*=\s*var\.postgresql_administrator_password\b',
                    r'administrator_password_wo_version\s*=\s*var\.postgresql\.administrator_password_version'):
        if not re.search(setting, pg):
            v.append(f"private PostgreSQL / write-only credential: {setting}")
    if re.search(r'\badministrator_password\s*=', source):
        v.append("plaintext PostgreSQL administrator_password would persist in state")
    password = block(source, "variable", "postgresql_administrator_password")
    if not (re.search(r'ephemeral\s*=\s*true', password) and re.search(r'sensitive\s*=\s*true', password)) or \
            re.search(r'\bdefault\s*=', password):
        v.append("PostgreSQL password input must be ephemeral/sensitive without default")
    if 'name    = "Microsoft.DBforPostgreSQL/flexibleServers"' not in source:
        v.append("PostgreSQL subnet delegation required")
    endpoints = re.findall(r'\bsubresource_names\s*=\s*(\[[^\]]*\])', source)
    if endpoints != ['["vault"]'] or not re.search(r'private_connection_resource_id\s*=\s*var\.key_vault_id', source) or \
            'name                = "privatelink.vaultcore.azure.net"' not in source:
        v.append("single Key Vault private endpoint to the foundation vault with privatelink zone required")
    aks = block(source, "resource", "azurerm_kubernetes_cluster")
    for setting in (r'oidc_issuer_enabled\s*=\s*true', r'workload_identity_enabled\s*=\s*true',
                    r'local_account_disabled\s*=\s*true', r'azure_rbac_enabled\s*=\s*true',
                    r'mode\s*=\s*"Istio"', r'revisions\s*=\s*\[var\.kubernetes\.istio_revision\]',
                    r'keda_enabled\s*=\s*true', r'\bkey_vault_secrets_provider\s*\{', r'disk_driver_enabled\s*=\s*true',
                    r'msi_auth_for_monitoring_enabled\s*=\s*true', r'\bmonitor_metrics\s*\{', r'type\s*=\s*"UserAssigned"'):
        if not re.search(setting, aks):
            v.append(f"AKS managed capability/identity contract: {setting}")
    if re.search(r'\bservice_principal\s*\{', aks):
        v.append("AKS service principal credential forbidden")
    acr = block(source, "resource", "azurerm_container_registry")
    if not re.search(r'admin_enabled\s*=\s*false', acr) or not re.search(r'anonymous_pull_enabled\s*=\s*false', acr):
        v.append("ACR must use identity, not admin/anonymous access")
    roles = sorted(re.findall(r'role_definition_name\s*=\s*"([^"]+)"', source))
    if roles != ["AcrPull", "Managed Identity Operator", "Monitoring Data Reader", "Network Contributor"]:
        v.append("role assignments limited to subnet join, kubelet identity, AcrPull and Grafana workspace read")
    if re.search(r'\bscope\s*=\s*"', source):
        v.append("role assignment scope must reference an environment resource, not a literal scope")
    outputs = dict(re.findall(r'\boutput\s+"([^"]+)"\s*\{(.*?)\n\}', source, re.S))
    if set(outputs) != {"network", "kubernetes_cluster", "postgresql", "key_vault_private_endpoint", "container_registry", "monitoring"}:
        v.append("unexpected environment outputs")
    if any(re.search(r'\.(kube_\w*config\w*|connection_string|instrumentation_key|\w*password\w*|\w*shared_key|admin_username|secret_identity)\b', body)
           or re.search(r'\bsensitive\s*=', body) for body in outputs.values()):
        v.append("outputs expose only non-secret metadata")
    return v

expected_resources = sorted([
    ("azurerm_virtual_network", "this"), ("azurerm_subnet", "aks_nodes"), ("azurerm_subnet", "postgresql"),
    ("azurerm_subnet", "private_endpoints"), ("azurerm_private_dns_zone", "key_vault"), ("azurerm_private_dns_zone", "postgresql"),
    ("azurerm_private_dns_zone_virtual_network_link", "key_vault"), ("azurerm_private_dns_zone_virtual_network_link", "postgresql"),
    ("azurerm_private_endpoint", "key_vault"), ("azurerm_postgresql_flexible_server", "this"),
    ("azurerm_postgresql_flexible_server_database", "application"), ("azurerm_user_assigned_identity", "aks_control_plane"),
    ("azurerm_user_assigned_identity", "aks_kubelet"), ("azurerm_kubernetes_cluster", "this"), ("azurerm_container_registry", "this"),
    *(("azurerm_role_assignment", name) for name in ("aks_subnet", "aks_kubelet_operator", "aks_acr_pull", "grafana_monitor_workspace")),
    ("azurerm_log_analytics_workspace", "this"), ("azurerm_monitor_data_collection_rule", "container_insights"),
    ("azurerm_monitor_data_collection_rule_association", "container_insights"), ("azurerm_monitor_workspace", "this"),
    ("azurerm_monitor_data_collection_endpoint", "prometheus"), ("azurerm_monitor_data_collection_rule", "prometheus"),
    ("azurerm_monitor_data_collection_rule_association", "prometheus"), ("azurerm_dashboard_grafana", "this"),
    ("azurerm_application_insights", "this"),
])
source = "\n".join(p.read_text() for p in sorted(stack.glob("*.tf")))
violations = environment_violations(source)
assert not violations, violations
# README inventory가 실제 source address와 어긋나지 않게 한다.
for kind, name in expected_resources:
    assert f"`{kind}.{name}`" in readme, f"README inventory missing {kind}.{name}"
# Automatic RP registration이 꺼져 있으므로 paid-run preflight 목록이 필수 provider를 빠뜨리지 않게 한다.
for provider in ("ContainerService", "Compute", "Network", "ManagedIdentity", "DBforPostgreSQL", "ContainerRegistry", "KeyVault",
                 "OperationalInsights", "Insights", "Monitor", "AlertsManagement", "Dashboard", "Storage"):
    assert f"`Microsoft.{provider}`" in readme, f"README Resource Provider inventory missing Microsoft.{provider}"
# Negative regression: 대표적인 위험 변경을 주입하면 guard가 각각 거부해야 한다.
mutations = {
    "public PostgreSQL": (r'(resource "azurerm_postgresql_flexible_server"[\s\S]*?public_network_access_enabled\s*=\s*)false', r'\1true'),
    "plaintext PostgreSQL password": (r'administrator_password_wo\s*=\s*var\.postgresql_administrator_password\b',
                                      'administrator_password = var.postgresql_administrator_password'),
    "non-ephemeral password input": (r'(variable "postgresql_administrator_password"[\s\S]*?)ephemeral\s*=\s*true', r'\1ephemeral = false'),
    "PostgreSQL private endpoint": (r'\Z', '\nresource "azurerm_private_endpoint" "postgresql" {\n  subresource_names = ["postgresqlServer"]\n}\n'),
    "recreated Key Vault": (r'\Z', '\nresource "azurerm_key_vault" "project" {\n}\n'),
    "ACR admin user": (r'admin_enabled\s*=\s*false', 'admin_enabled = true'),
    "AKS local account": (r'local_account_disabled(\s*)=\s*true', r'local_account_disabled\1= false'),
    "managed Istio disabled": (r'mode(\s*)=\s*"Istio"', r'mode\1= "Disabled"'),
    "subscription Owner": (r'\Z', '\nresource "azurerm_role_assignment" "ci_owner" {\n  scope                = "/subscriptions/x"\n  role_definition_name = "Owner"\n}\n'),
    "CLI auth fallback": (r'(provider "azurerm"[\s\S]*?use_cli\s*=\s*)false', r'\1true'),
    "kubeconfig output": (r'(output "kubernetes_cluster"\s*\{[\s\S]*?value = \{)', r'\1\n    raw = azurerm_kubernetes_cluster.this.kube_config_raw'),
    "Kubernetes provider": (r'\Z', '\nprovider "kubernetes" {\n}\n'),
}
for label, (pattern, replacement) in mutations.items():
    mutated = re.sub(pattern, replacement, source, count=1)
    assert mutated != source and environment_violations(mutated), f"guard must reject mutation: {label}"
tests = list((stack / "tests").glob("*"))
assert [p.name for p in tests] == ["security.tftest.hcl"], "unexpected Terraform test"
test = tests[0].read_text()
assert re.findall(r'\bmock_provider\s+"([^"]+)"', test) == ["azurerm"]
assert not re.search(r'\b(provider|module)\s*("|{)|\bproviders\s*=', test), "real test provider/module forbidden"
commands = re.findall(r'\bcommand\s*=\s*(\w+)', test)
assert commands and all(command == "plan" for command in commands), "mock plan only"
assert len(re.findall(r'\bexpect_failures\s*=', test)) >= 10, "negative variable validation tests required"
print(f"[terraform-verify] PASS environment inventory/remote backend/OIDC-only/private PostgreSQL/write-only credential/"
      f"Key Vault reference/AKS managed capability/RBAC/output guard + {len(mutations)} rejected mutations + mock-only guard")
PY

work="$(mktemp -d "$ROOT/.tmp/terraform-static.XXXXXX")"
trap 'rm -rf "$work"' EXIT
touch "$work/terraform.rc"
# Azure credentials, TF_VAR/TF_CLI_ARGS, cached CLI credentials/config, local/remote state/tfvars는 상속하지 않는다.
tf() { env -i PATH="$PATH" TF_IN_AUTOMATION=1 TF_INPUT=0 TF_CLI_CONFIG_FILE="$work/terraform.rc" "$TF" -chdir="$dir" "$@"; }
for stack in bootstrap foundation environment; do
  src="$ROOT/infra/terraform/$stack"
  dir="$work/$stack"
  mkdir "$dir"
  cp "$src/"*.tf "$src/.terraform.lock.hcl" "$dir/"
  cp -R "$src/tests" "$dir/"
  tf fmt -check -recursive
  tf init -backend=false -input=false -lockfile=readonly
  tf validate
  tf test -filter=tests/security.tftest.hcl
  echo "[terraform-verify] PASS $stack clean credential-free fmt/init/validate + mock security contract"
done
