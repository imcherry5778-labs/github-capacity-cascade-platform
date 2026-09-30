#!/usr/bin/env bash
# P5-W1: clean source copy, empty CLI config/environment, mock-only plan. Azure API를 호출하지 않는다.
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
# shellcheck source=versions.env
source "$ROOT/versions.env"
TF="$ROOT/.tmp/bin/terraform"
STACK="$ROOT/infra/terraform/bootstrap"
[[ "$("$TF" version -json | jq -r .terraform_version)" == "$TERRAFORM_VERSION" ]]

python3 - "$ROOT" "$TERRAFORM_VERSION" "$AZURERM_VERSION" <<'PY'
from pathlib import Path
import json, re, sys
root, terraform, azurerm = Path(sys.argv[1]), *sys.argv[2:]
base = root / "infra/terraform"
assert {p.name for p in base.iterdir()} == {"bootstrap"}, "P5-W1 only implements bootstrap"
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
PY

work="$(mktemp -d "$ROOT/.tmp/terraform-static.XXXXXX")"
trap 'rm -rf "$work"' EXIT
cp "$STACK/"*.tf "$STACK/.terraform.lock.hcl" "$work/"
cp -R "$STACK/tests" "$work/"
touch "$work/terraform.rc"
# Azure credentials, TF_VAR/TF_CLI_ARGS, cached CLI credentials/config, local state/tfvars는 상속하지 않는다.
tf() { env -i PATH="$PATH" TF_IN_AUTOMATION=1 TF_INPUT=0 TF_CLI_CONFIG_FILE="$work/terraform.rc" "$TF" -chdir="$work" "$@"; }
tf fmt -check -recursive
tf init -backend=false -input=false -lockfile=readonly
tf validate
tf test -filter=tests/security.tftest.hcl
echo "[terraform-verify] PASS clean credential-free fmt/init/validate + mock security contract"
