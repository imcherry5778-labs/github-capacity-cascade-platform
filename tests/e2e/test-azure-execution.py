#!/usr/bin/env python3
"""Credential-free approval/source/command isolation regression. Never invokes Azure/Terraform."""
import copy
import contextlib
import datetime as dt
import importlib.util
import json
import io
import os
from pathlib import Path
import re
import subprocess
import sys
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location("execution", ROOT / "scripts/azure-execution.py")
execution = importlib.util.module_from_spec(spec)
spec.loader.exec_module(execution)
NOW = dt.datetime(2026, 10, 24, 0, tzinfo=dt.timezone.utc)
SOURCE = "a" * 40


class FixedDateTime(dt.datetime):
    @classmethod
    def now(cls, tz=None):
        return NOW.astimezone(tz) if tz else NOW.replace(tzinfo=None)


def fixture():
    identity = "00000000-0000-0000-0000-000000000001"
    config = {"backend": {"storage_account_name": "teststate123", "container_name": "tfstate",
                          "tenant_id": identity, "client_id": identity}}
    for stack in ("foundation", "environment"):
        names = re.findall(r'^variable "([^"]+)"',
                           (ROOT / f"infra/terraform/{stack}/variables.tf").read_text(), re.M)
        config[stack] = {key: "fixture" for key in names if key != "postgresql_administrator_password"}
        config[stack].update(tenant_id=identity, ci_client_id=identity, location="koreacentral",
                             resource_group_name=stack, subscription_id=identity)
    config["foundation"]["dns_zone_name"] = "example.test"
    config["environment"]["foundation_resource_group_name"] = "foundation"
    approval = {"status": "approved", "campaign_id": "test-campaign", "source_sha": SOURCE,
                "operator": "operator", "source_pr": 25, "approval_evidence": "https://example.test/approval",
                "preflight_evidence": "https://example.test/preflight", "starts_at": NOW.isoformat(),
                "expires_at": (NOW + dt.timedelta(hours=10)).isoformat(), "budget_usd": 50,
                "config_sha256": execution.digest(config),
                "allowed_operations": [f"{s}:{o}" for s in ("foundation", "environment")
                                       for o in ("plan", "apply", "destroy")],
                "prerequisite_evidence": {f"{s}:{o}": "https://example.test/predecessor"
                                          for s in ("foundation", "environment")
                                          for o in ("plan", "apply", "destroy")}}
    env = {"PATH": os.environ["PATH"], "GITHUB_ACTIONS": "true", "GITHUB_EVENT_NAME": "workflow_dispatch",
           "GITHUB_REF": "refs/heads/main", "GITHUB_REPOSITORY": execution.REPOSITORY,
           "GITHUB_RUN_ATTEMPT": "1", "P6_SOURCE_SHA": SOURCE, "GITHUB_SHA": SOURCE,
           "P6_CAMPAIGN_ID": "test-campaign", "P6_STACK": "foundation", "P6_OPERATION": "plan",
           "GITHUB_ACTOR": "operator", "GITHUB_TRIGGERING_ACTOR": "operator",
           "ACTIONS_ID_TOKEN_REQUEST_URL": "https://example.test/token", "ACTIONS_ID_TOKEN_REQUEST_TOKEN": "dummy",
           "P6_POSTGRESQL_ADMINISTRATOR_PASSWORD": "dummy-test-value-only"}
    return approval, config, env


class ApprovalTest(unittest.TestCase):
    def test_explicit_approved_fixture(self):
        a, c, e = fixture()
        for stack in ("foundation", "environment"):
            for operation in ("plan", "apply", "destroy"):
                with self.subTest(stack=stack, operation=operation):
                    self.assertEqual(execution.validate(a, c, e | {"P6_STACK": stack, "P6_OPERATION": operation}, NOW),
                                     (stack, operation))

    def test_foundation_only_approved_operations_and_digest(self):
        a, c, e = fixture()
        del c["environment"]
        with self.assertRaisesRegex(ValueError, "approved input digest mismatch"):
            execution.validate(a, c, e, NOW)
        a.update(config_sha256=execution.digest(c),
                 allowed_operations=[f"foundation:{operation}" for operation in ("plan", "apply", "destroy")])
        for operation in ("plan", "apply", "destroy"):
            with self.subTest(operation=operation):
                self.assertEqual(execution.validate(a, c, e | {"P6_OPERATION": operation}, NOW),
                                 ("foundation", operation))
                with self.assertRaisesRegex(ValueError, "operation is not approved"):
                    execution.validate(a | {"allowed_operations": []}, c, e | {"P6_OPERATION": operation}, NOW)

    def test_missing_environment_refused_even_with_approved_operation(self):
        a, c, e = fixture()
        del c["environment"]
        a["config_sha256"] = execution.digest(c)
        for operation in ("plan", "apply", "destroy"):
            with self.subTest(operation=operation), self.assertRaisesRegex(ValueError, "selected stack inputs required"):
                execution.validate(a, c, e | {"P6_STACK": "environment", "P6_OPERATION": operation}, NOW)

    def test_unknown_config_keys_and_incomplete_stack_inputs_refused(self):
        a, c, e = fixture()
        invalid = [c | {"extra": {}}, c | {"bootstrap": {}},
                   {key: value for key, value in c.items() if key != "foundation"}]
        for selected in ("foundation", "environment"):
            for field in c[selected]:
                changed = copy.deepcopy(c)
                del changed[selected][field]
                invalid.append(changed)
            invalid.append(c | {selected: c[selected] | {"extra": "dummy"}})
        foundation_only = {key: value for key, value in c.items() if key != "environment"}
        invalid.extend([foundation_only | {"extra": {}},
                        foundation_only | {"foundation": {}}, foundation_only | {"backend": {}}])
        for index, changed in enumerate(invalid):
            for stack in ("foundation", "environment"):
                with self.subTest(config=index, stack=stack), self.assertRaises(ValueError):
                    execution.validate(a | {"config_sha256": execution.digest(changed)}, changed,
                                       e | {"P6_STACK": stack}, NOW)

    def test_missing_approval_fails_cli_without_subprocess_or_credentials(self):
        result = subprocess.run([sys.executable, str(ROOT / "scripts/azure-execution.py"), "execute"],
                                env={"PATH": os.environ["PATH"]}, capture_output=True, text=True)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("refused/failed", result.stderr)
        self.assertNotIn("Traceback", result.stderr)

    def test_environment_only_or_dispatch_inputs_cannot_authorize(self):
        a, c, e = fixture()
        for field, value in (("status", "pending"), ("source_sha", "b" * 40),
                             ("campaign_id", "other"), ("operator", "someone"),
                             ("budget_usd", 51), ("budget_usd", True), ("budget_usd", 0),
                             ("expires_at", (NOW + dt.timedelta(hours=11)).isoformat()),
                             ("starts_at", (NOW + dt.timedelta(seconds=1)).isoformat()),
                             ("expires_at", NOW.isoformat()), ("expires_at", "2026-10-24T10:00:00"),
                             ("allowed_operations", []), ("prerequisite_evidence", {}),
                             ("allowed_operations", "foundation:plan"),
                             ("allowed_operations", ["foundation:plan", "bootstrap:apply"]),
                             ("config_sha256", "0" * 64), ("approval_evidence", ""),
                             ("preflight_evidence", ""), ("source_pr", 0)):
            with self.subTest(field=field, value=value):
                changed = copy.deepcopy(a)
                changed[field] = value
                with self.assertRaises((ValueError, TypeError)):
                    execution.validate(changed, c, e, NOW)

    def test_crossing_korea_midnight_requires_another_approval_window(self):
        a, c, e = fixture()
        start = NOW.replace(hour=14)
        a.update(starts_at=start.isoformat(), expires_at=(start + dt.timedelta(hours=2)).isoformat())
        with self.assertRaises(ValueError):
            execution.validate(a, c, e, start)

    def test_wrong_event_branch_actor_rerun_or_bootstrap_refused(self):
        a, c, e = fixture()
        for field, value in (("GITHUB_EVENT_NAME", "pull_request"), ("GITHUB_REF", "refs/tags/main"),
                             ("GITHUB_REF", "refs/heads/feature"), ("GITHUB_SHA", "b" * 40),
                             ("GITHUB_RUN_ATTEMPT", "2"), ("GITHUB_REPOSITORY", "other/repo"),
                             ("GITHUB_TRIGGERING_ACTOR", "someone"), ("P6_STACK", "bootstrap"),
                             ("P6_STACK", "../bootstrap"), ("P6_OPERATION", "apply; id")):
            with self.subTest(field=field), self.assertRaises(ValueError):
                execution.validate(a, c, e | {field: value}, NOW)

    def test_unapproved_config_and_auth_or_region_overrides_refused(self):
        a, c, e = fixture()
        for target, field, value in (("backend", "access_key", "dummy"),
                                     ("backend", "use_oidc", False), ("backend", "key", "bootstrap.tfstate"),
                                     ("environment", "postgresql_administrator_password", "dummy"),
                                     ("foundation", "tenant_id", "00000000-0000-0000-0000-000000000002"),
                                     ("foundation", "ci_client_id", "00000000-0000-0000-0000-000000000002"),
                                     ("foundation", "location", "eastus"),
                                     ("environment", "tenant_id", "00000000-0000-0000-0000-000000000002"),
                                     ("environment", "ci_client_id", "00000000-0000-0000-0000-000000000002"),
                                     ("environment", "location", "eastus"),
                                     ("environment", "subscription_id", "00000000-0000-0000-0000-000000000002"),
                                     ("environment", "foundation_resource_group_name", "other"),
                                     ("environment", "resource_group_name", "foundation"),
                                     ("environment", "resource_group_name", "FOUNDATION")):
            with self.subTest(field=field):
                changed = copy.deepcopy(c)
                changed[target][field] = value
                # Even an approved digest cannot expand this work unit's auth/region/stack boundary.
                changed_approval = a | {"config_sha256": execution.digest(changed)}
                with self.assertRaises(ValueError):
                    execution.validate(changed_approval, changed, e, NOW)

    def test_foundation_only_security_checks_remain_required(self):
        a, c, e = fixture()
        del c["environment"]
        a["config_sha256"] = execution.digest(c)
        for field, value in (("config_sha256", "0" * 64), ("operator", "someone"),
                             ("source_sha", "b" * 40), ("status", "pending"),
                             ("budget_usd", 51), ("expires_at", NOW.isoformat()),
                             ("prerequisite_evidence", {})):
            with self.subTest(approval=field), self.assertRaises(ValueError):
                execution.validate(a | {field: value}, c, e, NOW)
        for target, field, value in (("backend", "access_key", "dummy"), ("backend", "use_oidc", False),
                                     ("foundation", "tenant_id", "00000000-0000-0000-0000-000000000002"),
                                     ("foundation", "ci_client_id", "00000000-0000-0000-0000-000000000002"),
                                     ("foundation", "location", "eastus")):
            changed = copy.deepcopy(c)
            changed[target][field] = value
            with self.subTest(config=field), self.assertRaises(ValueError):
                execution.validate(a | {"config_sha256": execution.digest(changed)}, changed, e, NOW)

    def test_dns_zone_change_requires_approved_config_digest(self):
        a, c, e = fixture()
        changed = copy.deepcopy(c)
        changed["foundation"]["dns_zone_name"] = "other.test"
        with self.assertRaisesRegex(ValueError, "approved input digest mismatch"):
            execution.validate(a, changed, e, NOW)
        self.assertEqual(execution.validate(a | {"config_sha256": execution.digest(changed)}, changed, e, NOW),
                         ("foundation", "plan"))

    def test_moved_main_unmerged_or_wrong_source_pr_refused(self):
        a, _, _ = fixture()
        pr = {"merged": True, "state": "closed", "merge_commit_sha": SOURCE,
              "base": {"ref": "main", "repo": {"full_name": execution.REPOSITORY}}}
        with patch.object(execution.subprocess, "check_output", side_effect=[SOURCE, b""]), \
             patch.object(execution, "github", side_effect=[{"object": {"sha": SOURCE}}, pr]):
            execution.check_source(a, merged_pr=True)
        for changed in (pr | {"merged": False}, pr | {"merge_commit_sha": "b" * 40},
                        pr | {"base": {"ref": "other", "repo": {"full_name": execution.REPOSITORY}}}):
            with self.subTest(pr=changed), \
                 patch.object(execution.subprocess, "check_output", side_effect=[SOURCE, b""]), \
                 patch.object(execution, "github", side_effect=[{"object": {"sha": SOURCE}}, changed]), \
                 self.assertRaises(ValueError):
                execution.check_source(a, merged_pr=True)
        with patch.object(execution.subprocess, "check_output", return_value=SOURCE), \
             patch.object(execution, "github", return_value={"object": {"sha": "b" * 40}}), \
             self.assertRaises(ValueError):
            execution.check_source(a)


class CommandIsolationTest(unittest.TestCase):
    def setUp(self):
        # Fixture 생성과 execute()의 재검사 모두 같은 낮 시각을 사용한다.
        # 실제 23:00 KST 실행이 one-hour window를 다음 날로 넘기지 않게 한다.
        clock = patch.object(execution.dt, "datetime", FixedDateTime)
        clock.start()
        self.addCleanup(clock.stop)

    def test_plan_apply_destroy_and_secret_isolation(self):
        for stack, foundation_only in (("foundation", False), ("environment", False), ("foundation", True)):
            for operation in ("plan", "apply", "destroy"):
                with self.subTest(stack=stack, operation=operation, foundation_only=foundation_only):
                    a, c, e = fixture()
                    if foundation_only:
                        del c["environment"]
                        del e["P6_POSTGRESQL_ADMINISTRATOR_PASSWORD"]
                        a.update(config_sha256=execution.digest(c), allowed_operations=[f"foundation:{operation}"])
                    now = dt.datetime.now(dt.timezone.utc)
                    a.update(starts_at=now.isoformat(), expires_at=(now + dt.timedelta(hours=1)).isoformat())
                    e.update(P6_STACK=stack, P6_OPERATION=operation, TF_LOG="TRACE", ARM_CLIENT_SECRET="dummy",
                             TF_CLI_ARGS="-target=danger", ARM_ACCESS_KEY="dummy", TF_VAR_extra="dummy")
                    calls, directories = [], []

                    def fake(command, *, env, **kwargs):
                        calls.append(command[2:])
                        directories.append(Path(command[1].removeprefix("-chdir=")))
                        self.assertFalse(set(env) & {"TF_LOG", "ARM_CLIENT_SECRET", "TF_CLI_ARGS", "ARM_ACCESS_KEY", "TF_VAR_extra"})
                        self.assertEqual(env["ARM_USE_OIDC"], "true")
                        self.assertEqual(env["ARM_USE_CLI"], "false")
                        self.assertEqual(env["ARM_USE_MSI"], "false")
                        self.assertEqual("TF_VAR_postgresql_administrator_password" in env, stack == "environment")
                        self.assertEqual(directories[-1].stat().st_mode & 0o777, 0o700)
                        inputs = directories[-1] / "execution.tfvars.json"
                        self.assertEqual(inputs.stat().st_mode & 0o777, 0o600)
                        self.assertEqual(json.loads(inputs.read_text()), c[stack])
                        self.assertNotIn("postgresql_administrator_password", inputs.read_text())
                        body = b'{"resource_changes": []}' if command[2] == "show" else b""
                        return subprocess.CompletedProcess(command, 0, body, b"")

                    with contextlib.redirect_stdout(io.StringIO()), \
                         patch.dict(os.environ, e, clear=True), patch.object(execution, "check_source"), \
                         patch.object(execution.subprocess, "run", side_effect=fake):
                        execution.execute(a, c)
                    names = [call[0] for call in calls]
                    self.assertEqual(names, ["init", "validate", "plan", "show"] +
                                     (["apply"] if operation != "plan" else []) + ["state"])
                    self.assertEqual("-destroy" in calls[2], operation == "destroy")
                    self.assertFalse(any("-auto-approve" in call for call in calls))
                    self.assertTrue(all(not directory.exists() for directory in directories))

    def test_foundation_only_cannot_execute_environment(self):
        a, c, e = fixture()
        del c["environment"]
        a["config_sha256"] = execution.digest(c)
        for operation in ("plan", "apply", "destroy"):
            with self.subTest(operation=operation), \
                 patch.dict(os.environ, e | {"P6_STACK": "environment", "P6_OPERATION": operation}, clear=True), \
                 patch.object(execution, "check_source") as source, \
                 patch.object(execution.subprocess, "run") as run:
                with self.assertRaisesRegex(ValueError, "selected stack inputs required"):
                    execution.execute(a, c)
                source.assert_not_called()
                run.assert_not_called()

    def test_foundation_only_requires_oidc_context_before_terraform(self):
        a, c, e = fixture()
        del c["environment"]
        a["config_sha256"] = execution.digest(c)
        for field in ("ACTIONS_ID_TOKEN_REQUEST_URL", "ACTIONS_ID_TOKEN_REQUEST_TOKEN"):
            with self.subTest(field=field), patch.dict(os.environ, e | {field: ""}, clear=True), \
                 patch.object(execution, "check_source"), patch.object(execution.subprocess, "run") as run:
                with self.assertRaisesRegex(ValueError, "GitHub OIDC request context missing"):
                    execution.execute(a, c)
                run.assert_not_called()

    def test_failure_diagnoses_without_apply_or_raw_output(self):
        a, c, e = fixture()
        now = dt.datetime.now(dt.timezone.utc)
        a.update(starts_at=now.isoformat(), expires_at=(now + dt.timedelta(hours=1)).isoformat())
        calls = []

        def fake(command, **kwargs):
            calls.append(command[2])
            return subprocess.CompletedProcess(command, int(command[2] == "plan"), b"sensitive-dummy", b"sensitive-dummy")

        with contextlib.redirect_stdout(io.StringIO()), \
             patch.dict(os.environ, e, clear=True), patch.object(execution, "check_source"), \
             patch.object(execution.subprocess, "run", side_effect=fake), self.assertRaises(ValueError) as error:
            execution.execute(a, c)
        self.assertEqual(calls, ["init", "validate", "plan", "state"])
        self.assertNotIn("sensitive-dummy", str(error.exception))

    def test_main_moving_after_plan_prevents_apply(self):
        a, c, e = fixture()
        now = dt.datetime.now(dt.timezone.utc)
        a.update(starts_at=now.isoformat(), expires_at=(now + dt.timedelta(minutes=1)).isoformat())
        e["P6_OPERATION"] = "apply"
        calls = []

        def fake(command, **kwargs):
            calls.append(command[2])
            return subprocess.CompletedProcess(command, 0, b'{"resource_changes": []}'
                                               if command[2] == "show" else b"", b"")

        with contextlib.redirect_stdout(io.StringIO()), patch.dict(os.environ, e, clear=True), \
             patch.object(execution, "check_source", side_effect=[None, None, ValueError("main moved")]), \
             patch.object(execution.subprocess, "run", side_effect=fake), self.assertRaises(ValueError):
            execution.execute(a, c)
        self.assertEqual(calls, ["init", "validate", "plan", "show", "state"])


class WorkflowBoundaryTest(unittest.TestCase):
    def test_dispatch_only_gate_before_oidc_and_no_state_artifact(self):
        workflow = (ROOT / ".github/workflows/azure-execution.yml").read_text()
        trigger = workflow.split("\non:\n", 1)[1].split("\npermissions:", 1)[0]
        self.assertEqual(re.findall(r"^  ([a-z_]+):", trigger, re.M), ["workflow_dispatch"])
        self.assertIn("\npermissions: {}", workflow)
        gate, terraform = workflow.split("  gate:\n", 1)[1].split("  terraform:\n", 1)
        self.assertNotIn("id-token:", gate)
        self.assertIn("pull-requests: read", gate)
        self.assertIn("needs: gate", terraform)
        self.assertIn("environment: azure", terraform)
        self.assertIn("id-token: write", terraform)
        self.assertNotIn("pull-requests:", terraform)
        self.assertNotIn("upload-artifact", workflow)
        self.assertNotIn("azure/login", workflow)
        self.assertEqual(workflow.count("persist-credentials: false"), 2)
        fic = (ROOT / "infra/terraform/bootstrap/main.tf").read_text()
        self.assertIn("repo:imcherry5778-labs@273613742/github-capacity-cascade-platform@1384941385:environment:azure", fic)


if __name__ == "__main__":
    unittest.main()
