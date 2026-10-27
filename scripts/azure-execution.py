#!/usr/bin/env python3
"""P6 dispatch gate and one approved remote-state operation. No bootstrap execution."""
import base64
import datetime as dt
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
REPOSITORY = "imcherry5778-labs/github-capacity-cascade-platform"
SHA = re.compile(r"[0-9a-f]{40}")
ROTATION_POLICY = "postgresql-password-rotation-1-to-2"
POSTGRESQL = "azurerm_postgresql_flexible_server.this"
# Diagnostic vocabulary only; these actions do not grant permission to apply.
DRIFT_DIAGNOSTIC_LIMIT = 34
DRIFT_DIAGNOSTIC_ACTIONS = {
    ("no-op",): "no-op", ("create",): "create", ("read",): "read", ("update",): "update",
    ("delete",): "delete", ("delete", "create"): "delete,create", ("create", "delete"): "create,delete",
}
PLAN_FAILURE_CODES = frozenset({
    "PLAN_JSON_INVALID", "VALIDATION_EXCEPTION", "RESOURCE_CHANGES", "POLICY_REQUIRED",
    "POLICY_OPERATION", "FORMAT_VERSION", "PLAN_STATUS", "RESOURCE_DRIFT", "DEFERRED_CHANGES",
    "EXTRA_ACTIONS", "RESOURCE_STRUCTURE", "RESOURCE_ADDRESS", "RESOURCE_METADATA",
    "CHANGE_STRUCTURE", "UNKNOWN_VALUES", "REPLACEMENT_IMPORT", "RESOURCE_IDENTITY", "RESOURCE_ID",
    "POSTGRESQL_ACTION", "PASSWORD_VERSION", "PASSWORD_PERSISTED", "RESOURCE_ACTION", "ATTRIBUTE_DIFF",
    "RESOURCE_INVENTORY", "OUTPUT_STRUCTURE", "OUTPUT_CHANGE", "PLAN_CHECKS",
})


class PlanGuardError(ValueError):
    def __init__(self, code, address=None):
        self.code = code
        self.address = address
        super().__init__("plan guard refused")


def plan_require(condition, code, address=None):
    if not condition:
        raise PlanGuardError(code, address)


def require(condition, message):
    if not condition:
        raise ValueError(message)


def digest(config):
    return hashlib.sha256(json.dumps(config, sort_keys=True, separators=(",", ":"),
                                     ensure_ascii=True).encode()).hexdigest()


def timestamp(value):
    parsed = dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
    require(parsed.utcoffset() == dt.timedelta(0), "approval timestamps must use UTC")
    return parsed


def validate(approval, config, env, now):
    require(isinstance(approval, dict) and isinstance(config, dict), "approval/config objects required")
    require(env.get("GITHUB_ACTIONS") == "true" and
            env.get("GITHUB_EVENT_NAME") == "workflow_dispatch" and
            env.get("GITHUB_REF") == "refs/heads/main" and
            env.get("GITHUB_REPOSITORY") == REPOSITORY and
            env.get("GITHUB_RUN_ATTEMPT") == "1", "main dispatch only; rerun requires a new dispatch")
    source = env.get("P6_SOURCE_SHA", "")
    require(SHA.fullmatch(source) and source == env.get("GITHUB_SHA") == approval["source_sha"],
            "approved source must equal dispatch SHA")
    require(approval["status"] == "approved" and approval["campaign_id"] == env["P6_CAMPAIGN_ID"],
            "explicit campaign approval missing or mismatched")
    require(approval["operator"] == env["GITHUB_ACTOR"] == env["GITHUB_TRIGGERING_ACTOR"],
            "dispatch actor is not the approved operator")
    for field in ("approval_evidence", "preflight_evidence"):
        require(isinstance(approval[field], str) and approval[field].startswith("https://"),
                "explicit approval and resolved preflight evidence links required")
    start, expiry = timestamp(approval["starts_at"]), timestamp(approval["expires_at"])
    require(start <= now < expiry and dt.timedelta(0) < expiry - start <= dt.timedelta(hours=10),
            "approval is expired, premature, or exceeds ten hours")
    korea = dt.timezone(dt.timedelta(hours=9))
    require(start.astimezone(korea).date() == expiry.astimezone(korea).date(),
            "campaign window must end on the same Korea calendar day")
    budget = approval["budget_usd"]
    require(type(budget) in (int, float) and 0 < budget <= 50, "pre-tax budget must be at most USD 50")
    require(approval["config_sha256"] == digest(config), "approved input digest mismatch")
    stack, operation = env["P6_STACK"], env["P6_OPERATION"]
    require(stack in ("foundation", "environment") and operation in ("plan", "apply", "destroy"),
            "only existing remote-state stacks and explicit operations are allowed")
    phase = f"{stack}:{operation}"
    operations = approval["allowed_operations"]
    require(isinstance(operations, list) and phase in operations and
            all(item in {f"{s}:{o}" for s in ("foundation", "environment")
                         for o in ("plan", "apply", "destroy")} for item in operations),
            "operation is not approved")
    if "plan_policy" in approval:
        require(approval["plan_policy"] == ROTATION_POLICY and stack == "environment" and
                operation in ("plan", "apply") and
                all(item in ("environment:plan", "environment:apply") for item in operations),
                "plan policy requires environment plan/apply approval only")
    require(isinstance(approval["prerequisite_evidence"], dict), "prerequisite evidence object required")
    evidence = approval["prerequisite_evidence"].get(phase, "")
    require(isinstance(evidence, str) and evidence.startswith("https://"),
            "operation-specific predecessor/cleanup evidence required")
    require(type(approval["source_pr"]) is int and approval["source_pr"] > 0, "merged source PR required")
    require(set(config) in ({"backend", "foundation"}, {"backend", "foundation", "environment"}),
            "config requires backend/foundation and only optional environment inputs")
    require(stack in config, "selected stack inputs required")
    backend = config["backend"]
    require(set(backend) == {"storage_account_name", "container_name", "tenant_id", "client_id"},
            "only non-secret bootstrap backend coordinates are accepted")
    require(re.fullmatch(r"[a-z0-9]{3,24}", backend["storage_account_name"]) and
            re.fullmatch(r"[a-z0-9][a-z0-9-]{1,61}[a-z0-9]", backend["container_name"]),
            "invalid backend coordinates")
    for field in ("tenant_id", "client_id"):
        require(re.fullmatch(r"[0-9a-fA-F-]{36}", backend[field]), "invalid identity coordinate")
    for selected in ("foundation", "environment"):
        if selected not in config:
            continue
        variables = config[selected]
        allowed = set(re.findall(r'^variable "([^"]+)"',
                                 (ROOT / f"infra/terraform/{selected}/variables.tf").read_text(), re.M))
        require(set(variables) == allowed - {"postgresql_administrator_password"},
                "config must contain exactly the non-secret Terraform inputs")
        require(variables["tenant_id"] == backend["tenant_id"] and
                variables["ci_client_id"] == backend["client_id"] and
                variables["location"] == "koreacentral", "identity/region mismatch")
    if "environment" in config:
        require(config["foundation"]["subscription_id"] == config["environment"]["subscription_id"] and
                config["foundation"]["resource_group_name"].lower() != config["environment"]["resource_group_name"].lower() and
                config["foundation"]["resource_group_name"] == config["environment"]["foundation_resource_group_name"],
                "subscription/RG boundaries mismatch")
    if "plan_policy" in approval:
        postgresql = config["environment"].get("postgresql")
        require(isinstance(postgresql, dict) and
                type(postgresql.get("administrator_password_version")) is int and
                postgresql["administrator_password_version"] == 2,
                "rotation policy requires approved password version 2 input")
    return stack, operation


def github(path):
    request = urllib.request.Request("https://api.github.com/repos/" + REPOSITORY + path,
                                     headers={"Authorization": "Bearer " + os.environ["GH_TOKEN"],
                                              "Accept": "application/vnd.github+json",
                                              "X-GitHub-Api-Version": "2022-11-28"})
    with urllib.request.urlopen(request, timeout=30) as response:
        return json.load(response)


def check_source(approval, merged_pr=False):
    source = approval["source_sha"]
    head = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()
    require(head == source == github("/git/ref/heads/main")["object"]["sha"],
            "checkout/approved SHA/current main mismatch")
    require(not subprocess.check_output(["git", "status", "--porcelain"], cwd=ROOT), "dirty checkout")
    if merged_pr:
        pr = github(f'/pulls/{approval["source_pr"]}')
        require(pr["merged"] is True and pr["state"] == "closed" and pr["base"]["ref"] == "main" and
                pr["base"]["repo"]["full_name"] == REPOSITORY and pr["merge_commit_sha"] == source,
                "source must be the exact merged PR commit on main")


def known(value):
    """Terraform unknown masks contain only false leaves when fully known."""
    if isinstance(value, dict):
        return all(known(item) for item in value.values())
    if isinstance(value, list):
        return all(known(item) for item in value)
    return value is False


def drift_diagnostics(plan, addresses):
    """Project bounded summaries; only the fixed AKS candidate paths may be named."""
    lines = []
    for key in ("resource_drift", "resource_changes"):
        entries = plan.get(key)
        prefix = "drift diagnostic: " + key
        if not isinstance(entries, list):
            lines.append(prefix + " entries=unknown shown=0 withheld=unknown status=INVALID")
            continue
        count = len(entries)
        if count > DRIFT_DIAGNOSTIC_LIMIT:
            lines.append(f"{prefix} entries={count} shown=0 withheld={count} status=LIMIT")
            continue
        records, seen, aks = [], set(), []
        duplicate = False
        for entry in entries:
            if not isinstance(entry, dict):
                continue
            address = entry.get("address")
            if not isinstance(address, str) or address not in addresses:
                continue
            if address in seen:
                duplicate = True
            seen.add(address)
            kind, name = address.split(".")
            if (entry.get("mode") != "managed" or entry.get("type") != kind or entry.get("name") != name or
                    entry.get("provider_name") != "registry.terraform.io/hashicorp/azurerm" or
                    any(field in entry for field in ("previous_address", "deposed", "index", "module_address"))):
                continue
            change = entry.get("change")
            actions = change.get("actions") if isinstance(change, dict) else None
            if not isinstance(actions, list) or not 1 <= len(actions) <= 2 or not all(
                    isinstance(action, str) for action in actions):
                continue
            action = DRIFT_DIAGNOSTIC_ACTIONS.get(tuple(actions))
            if action is not None:
                records.append(f"{prefix} resource={address} actions={action}")
                if key == "resource_changes" and address == "azurerm_kubernetes_cluster.this":
                    aks = aks_planned_diagnostics(change)
        # Duplicate source addresses cannot be interpreted as a unique resource inventory.
        if duplicate:
            records = []
            aks = []
        shown = len(records)
        status = "WITHHELD" if shown != count else "OK"
        lines.append(f"{prefix} entries={count} shown={shown} withheld={count - shown} status={status}")
        lines.extend(records)
        lines.extend(aks)
    return lines


def aks_planned_diagnostics(change):
    """Compare the default-pool candidate privately; never return values or discovered paths."""
    prefix = "aks planned diagnostic: "
    candidate = ("default_node_pool", 0, "upgrade_settings")
    path = "default_node_pool[0].upgrade_settings"
    unknown = [prefix + f"path={path} changed=unknown block=unknown",
               prefix + f"path={path}[0].max_surge changed=unknown",
               prefix + "other_changed_paths=unknown status=UNKNOWN"]
    if "after_unknown" not in change:
        return unknown
    mask = change["after_unknown"]
    for key in candidate:
        if mask is False:
            break
        if isinstance(key, str) and isinstance(mask, dict):
            mask = mask.get(key, False)
        elif isinstance(key, int) and isinstance(mask, list):
            mask = mask[key] if key < len(mask) else False
        else:
            return unknown
    if not known(mask):
        return unknown
    blocks = []
    for side in ("before", "after"):
        value = change.get(side)
        pool = value.get("default_node_pool") if isinstance(value, dict) else None
        if not isinstance(pool, list) or len(pool) != 1 or not isinstance(pool[0], dict):
            return unknown
        block = pool[0].get("upgrade_settings")
        if block is None:
            block = []
        if (not isinstance(block, list) or len(block) > 1 or
                (block and (not isinstance(block[0], dict) or
                            not isinstance(block[0].get("max_surge"), str)))):
            return unknown
        blocks.append(block)

    # Count changed leaf paths outside this one subtree, including sensitive fields,
    # without collecting their names. Added/removed containers count as one path.
    missing, visited = object(), 0

    def count(before, after, current=()):
        nonlocal visited
        visited += 1
        if visited > 10000 or len(current) > 64:
            raise ValueError()
        if current == candidate:
            return 0
        if isinstance(before, dict) and isinstance(after, dict):
            return sum(count(before.get(key, missing), after.get(key, missing), current + (key,))
                       for key in before.keys() | after.keys())
        if isinstance(before, list) and isinstance(after, list):
            return sum(count(before[i] if i < len(before) else missing,
                             after[i] if i < len(after) else missing, current + (i,))
                       for i in range(max(len(before), len(after))))
        return int(type(before) is not type(after) or before != after)

    try:
        other = count(change["before"], change["after"]) if known(change["after_unknown"]) else "unknown"
    except ValueError:
        return unknown
    before, after = blocks
    changed = json.dumps(before, sort_keys=True) != json.dumps(after, sort_keys=True)
    category = ("added" if not before else "removed" if not after else "changed") if changed else "unchanged"
    surge_before = before[0]["max_surge"] if before else missing
    surge_after = after[0]["max_surge"] if after else missing
    return [prefix + f"path={path} changed={str(changed).lower()} block={category}",
            prefix + f"path={path}[0].max_surge changed={str(surge_before != surge_after).lower()}",
            prefix + f"other_changed_paths={other} status={'UNKNOWN' if other == 'unknown' else 'KNOWN'}"]


def validate_plan(approval, stack, operation, plan, addresses):
    """Inspect the private JSON of the very saved plan passed to apply; never echo values."""
    rotation = approval.get("plan_policy") == ROTATION_POLICY
    plan_require(isinstance(plan, dict) and
            isinstance(plan.get("resource_changes", None if rotation else []), list), "RESOURCE_CHANGES")
    if not rotation:
        # Creation/cleanup retain their contract. Existing server mutation needs an explicit policy.
        if stack == "environment" and operation == "apply":
            for resource in plan.get("resource_changes", []):
                if resource["address"] == POSTGRESQL:
                    change = resource["change"]
                    plan_require(change["actions"] == ["no-op"] or
                            (change["actions"] == ["create"] and change.get("before") is None),
                            "POLICY_REQUIRED")
        return
    plan_require(stack == "environment" and operation in ("plan", "apply"), "POLICY_OPERATION")
    plan_require(isinstance(plan.get("format_version"), str) and
            re.fullmatch(r"1\.\d+", plan["format_version"]), "FORMAT_VERSION")
    plan_require(plan.get("applyable") is True and plan.get("complete") is True and
                 plan.get("errored") is False, "PLAN_STATUS")
    plan_require(plan.get("resource_drift", []) == [], "RESOURCE_DRIFT")
    plan_require(plan.get("deferred_changes", []) == [], "DEFERRED_CHANGES")
    plan_require(
            plan.get("action_invocations", []) == [] and plan.get("deferred_action_invocations", []) == [],
            "EXTRA_ACTIONS")
    seen = set()
    for resource in plan["resource_changes"]:
        plan_require(isinstance(resource, dict), "RESOURCE_STRUCTURE")
        address = resource.get("address")
        plan_require(isinstance(address, str) and address in addresses and address not in seen,
                "RESOURCE_ADDRESS")
        seen.add(address)
        kind, name = address.split(".")
        plan_require(resource.get("mode") == "managed" and resource.get("type") == kind and
                resource.get("name") == name and
                resource.get("provider_name") == "registry.terraform.io/hashicorp/azurerm" and
                not any(key in resource for key in ("previous_address", "deposed", "index", "module_address")),
                "RESOURCE_METADATA", address)
        change = resource.get("change")
        plan_require(isinstance(change, dict), "CHANGE_STRUCTURE", address)
        plan_require("after_unknown" in change and known(change["after_unknown"]), "UNKNOWN_VALUES", address)
        plan_require(change.get("replace_paths", []) == [] and "importing" not in change and
                "generated_config" not in change, "REPLACEMENT_IMPORT", address)
        plan_require(("before_identity" in change) == ("after_identity" in change) and
                json.dumps(change.get("before_identity"), sort_keys=True) ==
                json.dumps(change.get("after_identity"), sort_keys=True), "RESOURCE_IDENTITY", address)
        before, after = change.get("before"), change.get("after")
        plan_require(isinstance(before, dict) and isinstance(after, dict) and
                isinstance(before.get("id"), str) and bool(before["id"]) and
                before["id"] == after.get("id"), "RESOURCE_ID", address)
        expected = dict(before)
        if address == POSTGRESQL:
            version = "administrator_password_wo_version"
            plan_require(change.get("actions") == ["update"], "POSTGRESQL_ACTION", address)
            plan_require(type(before.get(version)) is int and before[version] == 1 and
                    type(after.get(version)) is int and after[version] == 2,
                    "PASSWORD_VERSION", address)
            plan_require(all(values.get(key) is None for values in (before, after)
                        for key in ("administrator_password", "administrator_password_wo")),
                    "PASSWORD_PERSISTED", address)
            expected[version] = 2
        else:
            plan_require(change.get("actions") == ["no-op"], "RESOURCE_ACTION", address)
        # Canonical JSON equality distinguishes bool/number and preserves every nested attribute/key.
        plan_require(json.dumps(expected, sort_keys=True) == json.dumps(after, sort_keys=True),
                "ATTRIBUTE_DIFF", address)
    plan_require(seen == addresses and POSTGRESQL in seen, "RESOURCE_INVENTORY")
    outputs = plan.get("output_changes", {})
    plan_require(isinstance(outputs, dict), "OUTPUT_STRUCTURE")
    for change in outputs.values():
        plan_require(isinstance(change, dict) and change.get("actions") == ["no-op"] and
                "before" in change and "after" in change and "after_unknown" in change and
                known(change["after_unknown"]) and
                json.dumps(change["before"], sort_keys=True) == json.dumps(change["after"], sort_keys=True),
                "OUTPUT_CHANGE")
    checks = plan.get("checks", [])
    plan_require(isinstance(checks, list) and all(isinstance(check, dict) and check.get("status") == "pass"
                                           for check in checks), "PLAN_CHECKS")


def execute(approval, config):
    """Private disposable plan/log files; diagnostics expose only source resource addresses."""
    env = os.environ
    stack, operation = validate(approval, config, env, dt.datetime.now(dt.timezone.utc))
    check_source(approval)
    source = ROOT / "infra/terraform" / stack
    addresses = set(re.findall(r'^resource "([^"]+)" "([^"]+)"',
                              "\n".join(p.read_text() for p in source.glob("*.tf")), re.M))
    addresses = {f"{kind}.{name}" for kind, name in addresses}
    with tempfile.TemporaryDirectory(prefix="p6-terraform-") as temporary:
        work = Path(temporary)
        work.chmod(0o700)
        for path in [*source.glob("*.tf"), source / ".terraform.lock.hcl"]:
            shutil.copyfile(path, work / path.name)
        (work / "terraform.rc").touch(mode=0o600)
        variables = work / "execution.tfvars.json"
        variables.touch(mode=0o600)
        variables.write_text(json.dumps(config[stack]))
        tfenv = {"PATH": env["PATH"], "HOME": temporary, "TF_IN_AUTOMATION": "1", "TF_INPUT": "0",
                 "TF_CLI_CONFIG_FILE": str(work / "terraform.rc"), "ARM_USE_OIDC": "true",
                 "ARM_USE_AZUREAD": "true", "ARM_USE_CLI": "false", "ARM_USE_MSI": "false",
                 "ARM_TENANT_ID": config["backend"]["tenant_id"],
                 "ARM_CLIENT_ID": config["backend"]["client_id"],
                 "ARM_SUBSCRIPTION_ID": config[stack]["subscription_id"],
                 "ARM_ENVIRONMENT": "public"}
        for field in ("ACTIONS_ID_TOKEN_REQUEST_URL", "ACTIONS_ID_TOKEN_REQUEST_TOKEN"):
            require(bool(env.get(field)), "GitHub OIDC request context missing")
            tfenv[field] = env[field]
        if stack == "environment":
            password = env.get("P6_POSTGRESQL_ADMINISTRATOR_PASSWORD", "")
            require(16 <= len(password) <= 128, "environment ephemeral password secret missing")
            tfenv["TF_VAR_postgresql_administrator_password"] = password
        terraform = str(ROOT / ".tmp/bin/terraform")

        def run(*args):
            # No inherited TF_CLI_ARGS, TF_LOG, ARM secret/key/SAS, CLI login or .terraform cache.
            print("Terraform step:", args[0], flush=True)
            completed = subprocess.run([terraform, f"-chdir={work}", *args], env=tfenv,
                                       stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            require(completed.returncode == 0, "Terraform step failed: " + args[0] +
                    "; raw provider output withheld (may contain credentials/state)")
            return completed.stdout

        initialized = False
        try:
            run("init", "-input=false", "-lockfile=readonly",
                *(f"-backend-config={key}={value}" for key, value in config["backend"].items()))
            initialized = True
            run("validate")
            # Approval/main freshness is rechecked immediately before each state-bearing operation.
            validate(approval, config, env, dt.datetime.now(dt.timezone.utc))
            check_source(approval)
            plan = ["plan", "-input=false", "-lock-timeout=60s", "-var-file=" + str(variables),
                    "-out=" + str(work / "execution.tfplan")]
            if operation == "destroy":
                plan.append("-destroy")
            run(*plan)
            plan_json = run("show", "-json", str(work / "execution.tfplan"))
            try:
                changes = json.loads(plan_json)
                validate_plan(approval, stack, operation, changes, addresses)
            except Exception as error:
                # Only fixed codes and source-allowlisted addresses cross this boundary.
                # Never stringify an unexpected exception (including JSON/provider payloads).
                code, address = "VALIDATION_EXCEPTION", None
                if isinstance(error, (json.JSONDecodeError, UnicodeDecodeError)):
                    code = "PLAN_JSON_INVALID"
                elif isinstance(error, PlanGuardError):
                    if isinstance(error.code, str) and error.code in PLAN_FAILURE_CODES:
                        code = error.code
                    if isinstance(error.address, str) and error.address in addresses:
                        address = error.address
                print("plan guard refused: " + code + (" resource=" + address if address else ""),
                      file=sys.stderr, flush=True)
                if code == "RESOURCE_DRIFT":
                    try:
                        print("\n".join(drift_diagnostics(changes, addresses)), file=sys.stderr, flush=True)
                    except Exception:
                        # Diagnostic failures must preserve the original refusal, without exception payloads.
                        print("drift diagnostic: unavailable", file=sys.stderr, flush=True)
                raise PlanGuardError(code, address) from None
            for change in changes.get("resource_changes", []):
                require(change["address"] in addresses, "plan contains an unexpected resource address")
                require(change["change"]["actions"] in (["no-op"], ["create"], ["read"], ["update"],
                                                       ["delete"], ["delete", "create"], ["create", "delete"]),
                        "unknown plan action")
                print("planned:", change["address"], "/".join(change["change"]["actions"]))
            if operation != "plan":
                validate(approval, config, env, dt.datetime.now(dt.timezone.utc))
                check_source(approval)
                run("apply", "-input=false", "-lock-timeout=60s", str(work / "execution.tfplan"))
            print(f"completed: {stack}:{operation}; source={approval['source_sha']}; "
                  "residual resources and actual cost require operator inspection")
        finally:
            if not initialized:
                print("backend initialization incomplete; operator must inspect state/locks, RBAC and Azure resources")
            if initialized:
                try:
                    state = run("state", "list").decode().splitlines()
                    for address in state:
                        if address in addresses:
                            print("state address:", address)
                    print("state inventory only; Azure residual absence is not established")
                except ValueError:
                    print("state inventory unavailable; operator must inspect backend/locks and Azure resources")
            # TemporaryDirectory removes state caches, plan, inputs and any crash logs on normal failure.
            # Runner termination/cancellation still requires operator reconciliation; never auto-destroy.


def main():
    require(len(sys.argv) == 2 and sys.argv[1] in ("gate", "execute", "digest-config"),
            "usage: azure-execution.py gate|execute|digest-config")
    # Decode only in Python memory; never export/print the JSON or encoded secret.
    config = json.loads(base64.b64decode(os.environ["P6_EXECUTION_CONFIG_B64"],
                                       validate=True).decode("utf-8"))
    if sys.argv[1] == "digest-config":
        print(digest(config))
        return
    approval = json.loads(os.environ["P6_CAMPAIGN_APPROVAL"])
    validate(approval, config, os.environ, dt.datetime.now(dt.timezone.utc))
    check_source(approval, merged_pr=sys.argv[1] == "gate")
    if sys.argv[1] == "execute":
        os.umask(0o077)
        execute(approval, config)
    else:
        print("gate passed: explicit campaign approval, merged exact source and bounded inputs")


if __name__ == "__main__":
    try:
        main()
    except (ValueError, KeyError, TypeError, OSError, subprocess.SubprocessError):
        # Payload/provider exceptions must not print actual values, credentials or private paths.
        print("P6 execution refused/failed; check approval, exact main, config, prerequisites and operator inventory",
              file=sys.stderr)
        sys.exit(1)
