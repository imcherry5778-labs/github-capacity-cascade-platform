#!/usr/bin/env python3
"""P6 dispatch gate and one approved remote-state operation. No bootstrap execution."""
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
    require(isinstance(approval["prerequisite_evidence"], dict), "prerequisite evidence object required")
    evidence = approval["prerequisite_evidence"].get(phase, "")
    require(isinstance(evidence, str) and evidence.startswith("https://"),
            "operation-specific predecessor/cleanup evidence required")
    require(type(approval["source_pr"]) is int and approval["source_pr"] > 0, "merged source PR required")
    backend = config["backend"]
    require(set(backend) == {"storage_account_name", "container_name", "tenant_id", "client_id"},
            "only non-secret bootstrap backend coordinates are accepted")
    require(re.fullmatch(r"[a-z0-9]{3,24}", backend["storage_account_name"]) and
            re.fullmatch(r"[a-z0-9][a-z0-9-]{1,61}[a-z0-9]", backend["container_name"]),
            "invalid backend coordinates")
    for field in ("tenant_id", "client_id"):
        require(re.fullmatch(r"[0-9a-fA-F-]{36}", backend[field]), "invalid identity coordinate")
    for selected in ("foundation", "environment"):
        variables = config[selected]
        allowed = set(re.findall(r'^variable "([^"]+)"',
                                 (ROOT / f"infra/terraform/{selected}/variables.tf").read_text(), re.M))
        require(set(variables) == allowed - {"postgresql_administrator_password"},
                "config must contain exactly the non-secret Terraform inputs")
        require(variables["tenant_id"] == backend["tenant_id"] and
                variables["ci_client_id"] == backend["client_id"] and
                variables["location"] == "koreacentral", "identity/region mismatch")
    require(config["foundation"]["subscription_id"] == config["environment"]["subscription_id"] and
            config["foundation"]["resource_group_name"].lower() != config["environment"]["resource_group_name"].lower() and
            config["foundation"]["resource_group_name"] == config["environment"]["foundation_resource_group_name"],
            "subscription/RG boundaries mismatch")
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
            changes = json.loads(run("show", "-json", str(work / "execution.tfplan")))
            for change in changes.get("resource_changes", []):
                require(change["address"] in addresses, "plan contains an unexpected resource address")
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
    config = json.loads(os.environ["P6_EXECUTION_CONFIG"])
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
