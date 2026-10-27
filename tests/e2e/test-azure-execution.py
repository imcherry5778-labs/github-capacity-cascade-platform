#!/usr/bin/env python3
"""Credential-free approval/source/command isolation regression. Never invokes Azure/Terraform."""
import base64
import copy
import contextlib
import datetime as dt
import hashlib
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


class EncodedInputTest(unittest.TestCase):
    def test_digest_preserves_original_canonical_json(self):
        _, config, env = fixture()
        config["foundation"]["resource_group_name"] = "fixture-한글"
        expected = hashlib.sha256(json.dumps(config, sort_keys=True, separators=(",", ":"),
                                             ensure_ascii=True).encode("ascii")).hexdigest()
        # Different key order, whitespace and UTF-8 representation keep the same approved digest.
        for raw in (json.dumps(config), json.dumps(dict(reversed(list(config.items()))),
                                                   indent=2, ensure_ascii=False)):
            encoded = base64.b64encode(raw.encode("utf-8")).decode("ascii")
            result = subprocess.run([sys.executable, str(ROOT / "scripts/azure-execution.py"), "digest-config"],
                                    env=env | {"P6_EXECUTION_CONFIG_B64": encoded}, capture_output=True, text=True)
            self.assertEqual(result.returncode, 0)
            self.assertEqual(result.stdout, expected + "\n")
            self.assertEqual(result.stderr, "")

    def test_gate_and_execute_decode_validate_before_external_calls(self):
        approval, config, env = fixture()
        raw = json.dumps(config)
        encoded = base64.b64encode(raw.encode()).decode("ascii")
        env.update(P6_EXECUTION_CONFIG_B64=encoded, P6_CAMPAIGN_APPROVAL=json.dumps(approval),
                   P6_EXECUTION_CONFIG='{"obsolete": "must-not-be-read"}')
        for mode in ("gate", "execute"):
            for failure in (None, "base64", "json", "utf8", "digest", "operation", "exact-inputs"):
                with self.subTest(mode=mode, failure=failure):
                    changed = dict(env)
                    if failure == "base64":
                        changed["P6_EXECUTION_CONFIG_B64"] = encoded + "!"
                    elif failure in ("json", "utf8"):
                        changed["P6_EXECUTION_CONFIG_B64"] = base64.b64encode(
                            b'{"private-input":' if failure == "json" else b"\xff").decode("ascii")
                    elif failure in ("digest", "operation"):
                        changed["P6_CAMPAIGN_APPROVAL"] = json.dumps(approval | (
                            {"config_sha256": "0" * 64} if failure == "digest" else {"allowed_operations": []}))
                    elif failure == "exact-inputs":
                        invalid = config | {"extra": "private-input"}
                        changed["P6_EXECUTION_CONFIG_B64"] = base64.b64encode(json.dumps(invalid).encode()).decode("ascii")
                        changed["P6_CAMPAIGN_APPROVAL"] = json.dumps(approval | {"config_sha256": execution.digest(invalid)})
                    output, errors = io.StringIO(), io.StringIO()
                    with patch.dict(os.environ, changed, clear=True), patch.object(sys, "argv", ["execution", mode]), \
                         patch.object(execution.dt, "datetime", FixedDateTime), \
                         patch.object(execution, "check_source") as source, \
                         patch.object(execution, "execute") as execute, \
                         patch.object(execution.os, "umask"), \
                         patch.object(execution.subprocess, "run") as run, \
                         contextlib.redirect_stdout(output), contextlib.redirect_stderr(errors):
                        if failure:
                            with self.assertRaises(ValueError):
                                execution.main()
                            source.assert_not_called()
                            execute.assert_not_called()
                        else:
                            execution.main()
                            source.assert_called_once_with(approval, merged_pr=mode == "gate")
                            if mode == "execute":
                                execute.assert_called_once_with(approval, config)
                            else:
                                execute.assert_not_called()
                        run.assert_not_called()
                    for value in (encoded, raw, "private-input", env["P6_POSTGRESQL_ADMINISTRATOR_PASSWORD"]):
                        self.assertNotIn(value, output.getvalue() + errors.getvalue())

    def test_cli_rejects_malformed_or_obsolete_input_without_echo(self):
        _, config, env = fixture()
        raw = json.dumps(config)
        encoded = base64.b64encode(raw.encode()).decode("ascii")
        for mode in ("gate", "execute", "digest-config"):
            for value in (None, "", "not-base64!", "e30", encoded + "\n",
                          base64.b64encode(b'{"private-input":').decode("ascii"),
                          base64.b64encode(b"\xff").decode("ascii"), "한글"):
                with self.subTest(mode=mode, value=value):
                    changed = env | {"P6_EXECUTION_CONFIG": raw}
                    if value is not None:
                        changed["P6_EXECUTION_CONFIG_B64"] = value
                    result = subprocess.run([sys.executable, str(ROOT / "scripts/azure-execution.py"), mode],
                                            env=changed, capture_output=True, text=True)
                    self.assertEqual(result.returncode, 1)
                    self.assertEqual(result.stdout, "")
                    self.assertEqual(result.stderr, "P6 execution refused/failed; check approval, exact main, config, "
                                     "prerequisites and operator inventory\n")


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
                             TF_CLI_ARGS="-target=danger", ARM_ACCESS_KEY="dummy", TF_VAR_extra="dummy",
                             P6_EXECUTION_CONFIG_B64=base64.b64encode(json.dumps(c).encode()).decode("ascii"))
                    calls, directories = [], []

                    def fake(command, *, env, **kwargs):
                        calls.append(command[2:])
                        directories.append(Path(command[1].removeprefix("-chdir=")))
                        self.assertFalse(set(env) & {"TF_LOG", "ARM_CLIENT_SECRET", "TF_CLI_ARGS", "ARM_ACCESS_KEY",
                                                     "TF_VAR_extra", "P6_EXECUTION_CONFIG", "P6_EXECUTION_CONFIG_B64"})
                        self.assertEqual(env["ARM_USE_OIDC"], "true")
                        self.assertEqual(env["ARM_USE_CLI"], "false")
                        self.assertEqual(env["ARM_USE_MSI"], "false")
                        self.assertEqual("TF_VAR_postgresql_administrator_password" in env, stack == "environment")
                        self.assertEqual(directories[-1].stat().st_mode & 0o777, 0o700)
                        inputs = directories[-1] / "execution.tfvars.json"
                        self.assertEqual(inputs.stat().st_mode & 0o777, 0o600)
                        self.assertEqual(json.loads(inputs.read_text()), c[stack])
                        self.assertNotIn("postgresql_administrator_password", inputs.read_text())
                        body = json.dumps({"resource_changes": [{"address": "azurerm_dns_zone.project",
                                           "change": {"actions": ["no-op"], "before": c, "after": c}}]}).encode() \
                            if command[2] == "show" and stack == "foundation" else b'{"resource_changes": []}'
                        if command[2] != "show":
                            body = json.dumps(c).encode() + e.get("P6_POSTGRESQL_ADMINISTRATOR_PASSWORD", "").encode()
                        return subprocess.CompletedProcess(command, 0, body, b"")

                    output, errors = io.StringIO(), io.StringIO()
                    with contextlib.redirect_stdout(output), contextlib.redirect_stderr(errors), \
                         patch.dict(os.environ, e, clear=True), patch.object(execution, "check_source"), \
                         patch.object(execution.subprocess, "run", side_effect=fake):
                        execution.execute(a, c)
                    for value in (json.dumps(c), c["backend"]["storage_account_name"],
                                  e["P6_EXECUTION_CONFIG_B64"], e.get("P6_POSTGRESQL_ADMINISTRATOR_PASSWORD", "absent-password")):
                        self.assertNotIn(value, output.getvalue() + errors.getvalue())
                    names = [call[0] for call in calls]
                    self.assertEqual(names, ["init", "validate", "plan", "show"] +
                                     (["apply"] if operation != "plan" else []) + ["state"])
                    self.assertEqual("-destroy" in calls[2], operation == "destroy")
                    self.assertFalse(any("-auto-approve" in call for call in calls))
                    self.assertTrue(all(not directory.exists() for directory in directories))

    def test_empty_saved_plan_compatibility_and_malformed_changes(self):
        # Terraform 1.16.7 omits resource_changes in an empty saved plan (including -destroy).
        empty = {"format_version": "1.2", "terraform_version": "1.16.7",
                 "applyable": False, "complete": True, "errored": False}
        cases = [("omitted", empty, True), ("empty", empty | {"resource_changes": []}, True)]
        cases.extend((repr(value), empty | {"resource_changes": value}, False)
                     for value in (None, {}, "", 0, False))
        for stack in ("foundation", "environment"):
            for operation in ("plan", "apply", "destroy"):
                for label, plan, allowed in cases:
                    with self.subTest(stack=stack, operation=operation, changes=label):
                        approval, config, env = fixture()
                        env.update(P6_STACK=stack, P6_OPERATION=operation)
                        calls = []

                        def fake(command, **kwargs):
                            calls.append(command[2:])
                            return subprocess.CompletedProcess(command, 0,
                                                               json.dumps(plan).encode() if command[2] == "show"
                                                               else b"", b"")

                        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()), \
                             patch.dict(os.environ, env, clear=True), \
                             patch.object(execution, "check_source"), \
                             patch.object(execution.subprocess, "run", side_effect=fake):
                            if allowed:
                                execution.execute(approval, config)
                            else:
                                with self.assertRaises(execution.PlanGuardError) as refused:
                                    execution.execute(approval, config)
                                self.assertEqual(refused.exception.code, "RESOURCE_CHANGES")
                        applied = allowed and operation != "plan"
                        self.assertEqual([call[0] for call in calls], ["init", "validate", "plan", "show"] +
                                         (["apply"] if applied else []) + ["state"])
                        saved = next(arg.removeprefix("-out=") for arg in calls[2] if arg.startswith("-out="))
                        self.assertEqual(calls[3], ["show", "-json", saved])
                        self.assertEqual("-destroy" in calls[2], operation == "destroy")
                        if applied:
                            self.assertEqual(calls[4][-1], saved)

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
        raw = json.dumps(c)
        encoded = base64.b64encode(raw.encode()).decode("ascii")
        e["P6_EXECUTION_CONFIG_B64"] = encoded
        now = dt.datetime.now(dt.timezone.utc)
        a.update(starts_at=now.isoformat(), expires_at=(now + dt.timedelta(hours=1)).isoformat())
        calls = []

        def fake(command, **kwargs):
            calls.append(command[2])
            body = (raw + encoded + e["P6_POSTGRESQL_ADMINISTRATOR_PASSWORD"]).encode()
            return subprocess.CompletedProcess(command, int(command[2] == "plan"), body, body)

        output, errors = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(output), contextlib.redirect_stderr(errors), \
             patch.dict(os.environ, e, clear=True), patch.object(execution, "check_source"), \
             patch.object(execution.subprocess, "run", side_effect=fake), self.assertRaises(ValueError) as error:
            execution.execute(a, c)
        self.assertEqual(calls, ["init", "validate", "plan", "state"])
        for value in (raw, encoded, e["P6_POSTGRESQL_ADMINISTRATOR_PASSWORD"]):
            self.assertNotIn(value, output.getvalue() + errors.getvalue() + str(error.exception))

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


def rotation_fixture():
    approval, config, env = fixture()
    config["environment"]["postgresql"] = {"administrator_password_version": 2}
    approval.update(plan_policy=execution.ROTATION_POLICY, config_sha256=execution.digest(config),
                    allowed_operations=["environment:plan", "environment:apply"])
    env.update(P6_STACK="environment", P6_OPERATION="apply",
               ACTIONS_ID_TOKEN_REQUEST_TOKEN="dummy-private-oidc-token")
    addresses = {f"{kind}.{name}" for kind, name in re.findall(
        r'^resource "([^"]+)" "([^"]+)"', "\n".join(
            path.read_text() for path in (ROOT / "infra/terraform/environment").glob("*.tf")), re.M)}
    resources = []
    for address in sorted(addresses):
        kind, name = address.split(".")
        before = {"id": "/dummy/" + address, "tags": {"purpose": "dummy-private-plan-value"}}
        after = copy.deepcopy(before)
        actions = ["no-op"]
        if address == execution.POSTGRESQL:
            before.update(administrator_password_wo_version=1, administrator_password_wo=None,
                          administrator_password=None, authentication=[{"password_auth_enabled": True}])
            after = copy.deepcopy(before) | {"administrator_password_wo_version": 2}
            actions = ["update"]
        resources.append({"address": address, "mode": "managed", "type": kind, "name": name,
                          "provider_name": "registry.terraform.io/hashicorp/azurerm",
                          "change": {"actions": actions, "before": before, "after": after,
                                     "after_unknown": {}}})
    plan = {"format_version": "1.2", "applyable": True, "complete": True, "errored": False,
            "resource_changes": resources, "output_changes": {
                "postgresql": {"actions": ["no-op"], "before": {"id": "dummy"},
                               "after": {"id": "dummy"}, "after_unknown": False}}}
    return approval, config, env, plan, addresses


class RotationTest(unittest.TestCase):
    def test_policy_metadata_cannot_expand_approval_or_inputs(self):
        a, c, e, _, _ = rotation_fixture()
        for operation in ("plan", "apply"):
            self.assertEqual(execution.validate(a, c, e | {"P6_OPERATION": operation}, NOW),
                             ("environment", operation))
        for value in (None, {}, "", "unknown-policy"):
            with self.subTest(policy=value), self.assertRaises(ValueError):
                execution.validate(a | {"plan_policy": value}, c, e, NOW)
        for phase in ("foundation:plan", "foundation:apply", "environment:destroy"):
            stack, operation = phase.split(":")
            with self.subTest(phase=phase), self.assertRaises(ValueError):
                execution.validate(a | {"allowed_operations": [phase]}, c,
                                   e | {"P6_STACK": stack, "P6_OPERATION": operation}, NOW)
        for version in (None, 1, 3, True, "2", 2.0):
            changed = copy.deepcopy(c)
            changed["environment"]["postgresql"]["administrator_password_version"] = version
            with self.subTest(version=version), self.assertRaises(ValueError):
                execution.validate(a | {"config_sha256": execution.digest(changed)}, changed, e, NOW)

    def test_exact_saved_plan_guard_and_refusal_before_apply(self):
        a, c, e, valid, addresses = rotation_fixture()
        self.assertEqual(len(addresses), 34)
        pg_index = next(i for i, resource in enumerate(valid["resource_changes"])
                        if resource["address"] == execution.POSTGRESQL)
        other_index = next(i for i in range(len(addresses)) if i != pg_index)
        cases = [("exact update", valid, True)]

        def mutate(label, path, value=None, remove=False):
            plan = copy.deepcopy(valid)
            selected = plan
            for key in path[:-1]:
                selected = selected[key]
            if remove:
                del selected[path[-1]]
            else:
                selected[path[-1]] = value
            cases.append((label, plan, False))

        for index in (pg_index, other_index):
            resource = ["resource_changes", index]
            change = resource + ["change"]
            for actions in (["create"], ["delete"], ["delete", "create"], ["create", "delete"],
                            ["read"], [], ["dummy-private-plan-value"], ["update", "update"]):
                mutate(f"actions {index} {actions}", change + ["actions"], actions)
            mutate(f"unknown {index}", change + ["after_unknown"], {"tags": {"purpose": True}})
            mutate(f"missing unknown mask {index}", change + ["after_unknown"], remove=True)
            mutate(f"malformed unknown mask {index}", change + ["after_unknown"], None)
            mutate(f"replacement path {index}", change + ["replace_paths"], [["id"]])
            mutate(f"import {index}", change + ["importing"], {"id": "dummy"})
            mutate(f"identity change {index}", change + ["after_identity"], {"id": "changed"})
            mutate(f"move {index}", resource + ["previous_address"], "dummy")
            mutate(f"deposed {index}", resource + ["deposed"], "dummy")
            mutate(f"missing identity {index}", resource + ["mode"], remove=True)
            for field in ("before", "after"):
                mutate(f"missing {field} {index}", change + [field], remove=True)
                mutate(f"null {field} {index}", change + [field], None)
                mutate(f"changed ID {field} {index}", change + [field, "id"], "changed")
            mutate(f"other attribute {index}", change + ["after", "tags"], {"purpose": "changed"})
        pg = ["resource_changes", pg_index, "change"]
        for field in ("before", "after"):
            version = pg + [field, "administrator_password_wo_version"]
            for value in (None, 0, 1 if field == "after" else 2, 3, True, "2", 2.0):
                mutate(f"version {field} {value}", version, value)
            mutate(f"missing version {field}", version, remove=True)
        mutate("nested PG setting", pg + ["after", "authentication"], [{"password_auth_enabled": False}])
        mutate("extra PG setting", pg + ["after", "extra"], "changed")
        mutate("PG no-op", pg + ["actions"], ["no-op"])
        mutate("other update", ["resource_changes", other_index, "change", "actions"], ["update"])
        mutate("duplicate resource", ["resource_changes"], valid["resource_changes"] * 2)
        mutate("missing PG", ["resource_changes"], [r for r in valid["resource_changes"]
                                                       if r["address"] != execution.POSTGRESQL])
        mutate("missing other resource", ["resource_changes"], [valid["resource_changes"][pg_index]])
        mutate("unknown address", ["resource_changes", other_index, "address"], "dummy.unexpected")
        mutate("malformed resource", ["resource_changes", pg_index], None)
        mutate("absent changes", ["resource_changes"], remove=True)
        mutate("empty changes", ["resource_changes"], [])
        mutate("null changes", ["resource_changes"], None)
        for field, value in (("format_version", "2.0"), ("format_version", None), ("applyable", False),
                             ("complete", False), ("errored", True), ("resource_drift", [{}]),
                             ("resource_drift", None), ("deferred_changes", [{}]), ("action_invocations", [{}]),
                             ("deferred_action_invocations", [{}]),
                             ("checks", [{"status": "unknown"}]), ("output_changes", None)):
            mutate(field, [field], value)
        for field in ("format_version", "applyable", "complete", "errored"):
            mutate(f"missing {field}", [field], remove=True)
        mutate("changed output", ["output_changes", "postgresql", "after"], {"id": "changed"})
        mutate("unknown output", ["output_changes", "postgresql", "after_unknown"], True)
        mutate("malformed change", ["resource_changes", pg_index, "change"], None)
        for field in ("administrator_password", "administrator_password_wo"):
            mutate(field, pg + ["after", field], "dummy-private-plan-value")
        cases.extend((label, plan, False) for label, plan in (("not object", []), ("empty object", {})))
        expected_codes = {
            "absent changes": "RESOURCE_CHANGES", "format_version": "FORMAT_VERSION",
            "applyable": "PLAN_STATUS", "resource_drift": "RESOURCE_DRIFT",
            "deferred_changes": "DEFERRED_CHANGES", "action_invocations": "EXTRA_ACTIONS",
            "malformed resource": "RESOURCE_STRUCTURE", "unknown address": "RESOURCE_ADDRESS",
            f"move {pg_index}": "RESOURCE_METADATA", "malformed change": "CHANGE_STRUCTURE",
            f"unknown {pg_index}": "UNKNOWN_VALUES", f"import {pg_index}": "REPLACEMENT_IMPORT",
            f"identity change {pg_index}": "RESOURCE_IDENTITY", f"changed ID before {pg_index}": "RESOURCE_ID",
            "PG no-op": "POSTGRESQL_ACTION", "version before None": "PASSWORD_VERSION",
            "administrator_password": "PASSWORD_PERSISTED", "other update": "RESOURCE_ACTION",
            "nested PG setting": "ATTRIBUTE_DIFF", "missing PG": "RESOURCE_INVENTORY",
            "output_changes": "OUTPUT_STRUCTURE", "changed output": "OUTPUT_CHANGE", "checks": "PLAN_CHECKS",
        }
        for label, plan, allowed in cases:
            with self.subTest(case=label):
                calls, directories = [], []
                output, errors = io.StringIO(), io.StringIO()

                def fake(command, *, env, **kwargs):
                    calls.append(command[2:])
                    directories.append(Path(command[1].removeprefix("-chdir=")))
                    self.assertEqual(env["ARM_USE_OIDC"], "true")
                    self.assertEqual(env["TF_VAR_postgresql_administrator_password"],
                                     e["P6_POSTGRESQL_ADMINISTRATOR_PASSWORD"])
                    self.assertNotIn("GH_TOKEN", env)
                    body = json.dumps(plan).encode() if command[2] == "show" else b"dummy-provider-diagnostic"
                    return subprocess.CompletedProcess(command, 0, body, b"dummy-provider-diagnostic")

                with contextlib.redirect_stdout(output), contextlib.redirect_stderr(errors), \
                     patch.dict(os.environ, e, clear=True), \
                     patch.object(execution.dt, "datetime", FixedDateTime), \
                     patch.object(execution, "check_source"), \
                     patch.object(execution.subprocess, "run", side_effect=fake):
                    if allowed:
                        execution.execute(a, c)
                    else:
                        with self.assertRaises(execution.PlanGuardError) as refused:
                            execution.execute(a, c)
                        code, address = refused.exception.code, refused.exception.address
                        self.assertIn(code, execution.PLAN_FAILURE_CODES)
                        self.assertNotEqual(code, "VALIDATION_EXCEPTION")
                        if label in expected_codes:
                            self.assertEqual(code, expected_codes[label])
                        expected = "plan guard refused: " + code + (" resource=" + address if address else "") + "\n"
                        if code == "RESOURCE_DRIFT":
                            expected += "\n".join(execution.drift_diagnostics(plan, addresses)) + "\n"
                        self.assertEqual(errors.getvalue(), expected)
                        self.assertTrue(address is None or address in addresses)
                        self.assertNotIn("planned:", output.getvalue())
                self.assertEqual([call[0] for call in calls],
                                 ["init", "validate", "plan", "show"] + (["apply"] if allowed else []) + ["state"])
                if allowed:
                    saved = next(arg.removeprefix("-out=") for arg in calls[2] if arg.startswith("-out="))
                    self.assertEqual(calls[3], ["show", "-json", saved])
                    self.assertEqual(calls[4][-1], saved)
                self.assertTrue(all(not path.exists() for path in directories))
                for private in ("dummy-private-plan-value", "dummy-provider-diagnostic", json.dumps(plan),
                                e["P6_POSTGRESQL_ADMINISTRATOR_PASSWORD"], e["ACTIONS_ID_TOKEN_REQUEST_TOKEN"]):
                    self.assertNotIn(private, output.getvalue() + errors.getvalue())

    def test_drift_diagnostic_projection_is_bounded_and_fail_closed(self):
        _, _, _, plan, addresses = rotation_fixture()
        sentinel = "private-secret-token-resource-id-attribute-path-sentinel"
        resource = copy.deepcopy(plan["resource_changes"][0])
        address = resource["address"]
        resource["change"].update({"before": {sentinel: sentinel}, "after": {sentinel: sentinel},
                                  "after_unknown": {sentinel: True}, "before_sensitive": {sentinel: True},
                                  "after_sensitive": {sentinel: True}, "replace_paths": [[sentinel]],
                                  "importing": {"id": sentinel}})
        resource["action_reason"] = sentinel
        prefix = "drift diagnostic: "
        actions = [(["no-op"], "no-op"), (["create"], "create"), (["read"], "read"),
                   (["update"], "update"), (["delete"], "delete"),
                   (["delete", "create"], "delete,create"), (["create", "delete"], "create,delete")]
        for key in ("resource_drift", "resource_changes"):
            for value, label in actions:
                with self.subTest(key=key, actions=label):
                    resource["change"]["actions"] = value
                    lines = execution.drift_diagnostics({key: [resource]}, addresses)
                    self.assertIn(prefix + key + " entries=1 shown=1 withheld=0 status=OK", lines)
                    self.assertIn(prefix + key + f" resource={address} actions={label}", lines)
                    self.assertNotIn(sentinel, "\n".join(lines))

            invalid = [None, sentinel, [], {}, resource | {"address": sentinel},
                       resource | {"address": address + "[" + sentinel + "]"},
                       resource | {"address": [sentinel]}, resource | {"address": {sentinel: sentinel}},
                       resource | {"address": address + "\n" + sentinel}]
            invalid.extend(resource | {key: sentinel} for key in ("mode", "type", "name", "provider_name"))
            invalid.extend(resource | {key: sentinel} for key in
                           ("previous_address", "deposed", "index", "module_address"))
            invalid.extend(resource | {"change": value} for value in (None, [], sentinel, {}))
            invalid.extend(resource | {"change": {"actions": value}} for value in
                           (None, sentinel, {}, [None], [[sentinel]], [{sentinel: sentinel}],
                            [sentinel], [], ["update", "update"], ["read", "delete"], ["forget"],
                            ["create", "delete", "create"]))
            for entry in invalid:
                with self.subTest(key=key, invalid=entry):
                    lines = execution.drift_diagnostics({key: [entry]}, addresses)
                    self.assertIn(prefix + key + " entries=1 shown=0 withheld=1 status=WITHHELD", lines)
                    self.assertFalse(any(" resource=" in line for line in lines))
                    self.assertNotIn(sentinel, "\n".join(lines))
            for entries in (None, {}, sentinel, True, 1):
                lines = execution.drift_diagnostics({key: entries}, addresses)
                self.assertIn(prefix + key + " entries=unknown shown=0 withheld=unknown status=INVALID", lines)
                self.assertNotIn(sentinel, "\n".join(lines))
            lines = execution.drift_diagnostics({key: [resource, resource]}, addresses)
            self.assertIn(prefix + key + " entries=2 shown=0 withheld=2 status=WITHHELD", lines)
            self.assertFalse(any(" resource=" in line for line in lines))
            for count in (35, 1000):
                lines = execution.drift_diagnostics({key: [resource] * count}, addresses)
                self.assertIn(prefix + key + f" entries={count} shown=0 withheld={count} status=LIMIT", lines)
                self.assertFalse(any(" resource=" in line for line in lines))

        lines = execution.drift_diagnostics({"resource_drift": plan["resource_changes"],
                                            "resource_changes": plan["resource_changes"]}, addresses)
        self.assertEqual(len(lines), 107)  # Two counts, 68 entries, 34 field summaries, three AKS lines.
        self.assertEqual(sum(line.startswith("drift diagnostic: ") and " resource=" in line
                             for line in lines), 68)

    def test_drift_fields_are_fixed_per_resource_and_never_emit_values_or_other_names(self):
        sentinel = "private-secret-token-resource-id-arbitrary-path"
        for address, fields in execution.DRIFT_DIAGNOSTIC_FIELDS.items():
            change = {"before": {field: sentinel for field in fields},
                      "after": {field: "different-private-value" for field in fields},
                      "after_unknown": {}, "before_sensitive": {}, "after_sensitive": {}}
            change["before"].update({sentinel: {sentinel: sentinel}, "typed": 1, "removed": None})
            change["after"].update({sentinel: {sentinel: "different"}, "typed": True, "added": None})
            prefix = f"drift fields diagnostic: resource={address} "
            with self.subTest(address=address):
                line = execution.drift_field_diagnostic(address, change)
                self.assertEqual(line, prefix + "named_changed_fields=" + ",".join(fields) +
                                 " other_changed_fields=4 status=KNOWN")
                for private in (sentinel, "different-private-value", "typed", "removed", "added"):
                    self.assertNotIn(private, line)
                # Sensitive or absent/malformed masks suppress names, while counts remain available.
                for mask in (True, None, {field: True for field in fields}):
                    self.assertEqual(execution.drift_field_diagnostic(
                        address, change | {"after_sensitive": mask}), prefix +
                        f"named_changed_fields=none other_changed_fields={len(fields) + 4} status=KNOWN")
                no_mask = {key: value for key, value in change.items() if key != "before_sensitive"}
                self.assertEqual(execution.drift_field_diagnostic(address, no_mask), prefix +
                                 f"named_changed_fields=none other_changed_fields={len(fields) + 4} status=KNOWN")
        # Matching field names on any other source resource are counted without being named.
        line = execution.drift_field_diagnostic("azurerm_application_insights.this", change)
        self.assertEqual(line, "drift fields diagnostic: resource=azurerm_application_insights.this "
                         f"named_changed_fields=none other_changed_fields={len(fields) + 4} status=KNOWN")

    def test_drift_field_unknown_malformed_and_comparison_limits(self):
        address = "azurerm_kubernetes_cluster.this"
        base = {"before": {"default_node_pool": [{"node_count": 2}]},
                "after": {"default_node_pool": [{"node_count": 3}]},
                "after_unknown": {}, "before_sensitive": {}, "after_sensitive": {}}
        unknown = (f"drift fields diagnostic: resource={address} "
                   "named_changed_fields=unknown other_changed_fields=unknown status=UNKNOWN")
        deep = False
        for _ in range(sys.getrecursionlimit() + 10):
            deep = [deep]
        cases = [base | {"after_unknown": mask} for mask in (True, None, [], 0, "private", {"private": True}, deep)]
        cases += [base | {side: value} for side in ("before", "after") for value in (None, [], True)]
        cases += [{key: value for key, value in base.items() if key != "after_unknown"},
                  base | {"before": {str(i): False for i in range(129)}},
                  base | {"after": {"private": "x" * 262144}}]
        for index, change in enumerate(cases):
            with self.subTest(case=index):
                self.assertEqual(execution.drift_field_diagnostic(address, change), unknown)
        with patch.object(execution.json, "dumps", side_effect=RecursionError("private")):
            self.assertEqual(execution.drift_field_diagnostic(address, base), unknown)
        self.assertEqual(execution.drift_field_diagnostic(address, base | {"after": base["before"]}),
                         f"drift fields diagnostic: resource={address} "
                         "named_changed_fields=none other_changed_fields=0 status=KNOWN")

    def test_aks_candidate_paths_and_other_change_count(self):
        _, _, _, plan, addresses = rotation_fixture()
        resource = next(entry for entry in plan["resource_changes"]
                        if entry["address"] == "azurerm_kubernetes_cluster.this")
        sentinel = "private-sensitive-value-resource-id-arbitrary-path-sentinel"
        empty, block = [], [{"max_surge": sentinel, "drain_timeout_in_minutes": 0}]
        prefix = "aks planned diagnostic: "
        path = "default_node_pool[0].upgrade_settings"
        cases = [
            (empty, block, True, "added", True),
            (block, empty, True, "removed", True),
            (block, [{"max_surge": "other-private-value"}], True, "changed", True),
            (block, [block[0] | {"drain_timeout_in_minutes": 1}], True, "changed", False),
            (block, block, False, "unchanged", False),
            (empty, empty, False, "unchanged", False),
        ]
        for before, after, changed, category, surge_changed in cases:
            with self.subTest(category=category, surge_changed=surge_changed):
                resource["change"].update(
                    actions=["update"],
                    before={"id": sentinel, "default_node_pool": [{"upgrade_settings": before}]},
                    after={"id": sentinel, "default_node_pool": [{"upgrade_settings": after}]},
                    before_sensitive={"default_node_pool": True}, after_sensitive={"default_node_pool": True})
                lines = execution.drift_diagnostics({"resource_changes": [resource]}, addresses)
                self.assertIn("drift diagnostic: resource_changes resource=azurerm_kubernetes_cluster.this "
                              "actions=update", lines)
                self.assertEqual(lines[-3:], [
                    prefix + f"path={path} changed={str(changed).lower()} block={category}",
                    prefix + f"path={path}[0].max_surge changed={str(surge_changed).lower()}",
                    prefix + "other_changed_paths=0 status=KNOWN"])
                self.assertNotIn(sentinel, "\n".join(lines))

        # Same-named fields outside the exact candidate subtree must still count.
        resource["change"]["before"].update({sentinel: [{"max_surge": "old"}], "upgrade_settings": [],
                                             "typed": 1, "removed": {sentinel: sentinel}})
        resource["change"]["after"].update({sentinel: [{"max_surge": "new"}], "upgrade_settings": [sentinel],
                                            "typed": True, "added": {sentinel: sentinel}})
        resource["change"]["before"]["default_node_pool"][0][sentinel] = "old"
        resource["change"]["after"]["default_node_pool"][0][sentinel] = "new"
        lines = execution.drift_diagnostics({"resource_changes": [resource]}, addresses)
        self.assertEqual(lines[-1], prefix + "other_changed_paths=6 status=KNOWN")
        self.assertNotIn(sentinel, "\n".join(lines))
        # The drift list must never be used as a planned attribute diff.
        self.assertFalse(any(line.startswith(prefix) for line in execution.drift_diagnostics(
            {"resource_drift": [resource]}, addresses)))
        self.assertFalse(any(line.startswith(prefix) for line in execution.drift_diagnostics(
            {"resource_changes": [resource, resource]}, addresses)))
        invalid = [resource | {"provider_name": sentinel}, resource | {"address": sentinel},
                   resource | {"change": resource["change"] | {"actions": [sentinel]}}]
        for entry in invalid:
            lines = execution.drift_diagnostics({"resource_changes": [entry]}, addresses)
            self.assertFalse(any(line.startswith(prefix) for line in lines))
            self.assertNotIn(sentinel, "\n".join(lines))

    def test_aks_unknown_and_malformed_values_are_not_reported_as_removal(self):
        base = {"before": {"default_node_pool": [{"upgrade_settings": [{"max_surge": "private"}]}]},
                "after": {"default_node_pool": [{"upgrade_settings": []}]}, "after_unknown": {}}
        prefix = "aks planned diagnostic: "
        expected = [prefix + "path=default_node_pool[0].upgrade_settings changed=unknown block=unknown",
                    prefix + "path=default_node_pool[0].upgrade_settings[0].max_surge changed=unknown",
                    prefix + "other_changed_paths=unknown status=UNKNOWN"]
        sentinel = "private-unknown-path-value-sentinel"
        masks = [True, None, sentinel, {"default_node_pool": True},
                 {"default_node_pool": [{"upgrade_settings": True}]},
                 {"default_node_pool": [{"upgrade_settings": [{"max_surge": True}]}]}]
        changes = [base | {"after_unknown": mask} for mask in masks]
        changes.append({key: value for key, value in base.items() if key != "after_unknown"})
        for side in ("before", "after"):
            changes.extend(base | {side: value} for value in (None, [], sentinel, {}))
            changes.extend(base | {side: {"default_node_pool": value}} for value in
                           (None, {}, [], [None], [{}, {}], sentinel))
            changes.extend(base | {side: {"default_node_pool": [{"upgrade_settings": value}]}} for value in
                           (True, {}, sentinel, [None], [{}, {}], [{}], [{"max_surge": None}]))
        changes.append(base | {"before": base["before"] | {sentinel: [sentinel] * 10001},
                               "after": base["after"] | {sentinel: ["changed"] * 10001}})
        for index, change in enumerate(changes):
            with self.subTest(case=index):
                lines = execution.aks_planned_diagnostics(change)
                self.assertEqual(lines, expected)
                self.assertNotIn(sentinel, "\n".join(lines))
        for absent in (None, []):
            change = base | {"after": {"default_node_pool": [{"upgrade_settings": absent}]}}
            self.assertIn("block=removed", execution.aks_planned_diagnostics(change)[0])
        self.assertIn("block=removed", execution.aks_planned_diagnostics(
            base | {"after": {"default_node_pool": [{}]}})[0])
        # An unrelated computed unknown must not hide the known candidate removal,
        # and its null placeholder must not be counted as a confirmed difference.
        for mask in ({sentinel: True}, {"default_node_pool": [{sentinel: True}]}):
            lines = execution.aks_planned_diagnostics(base | {"after_unknown": mask})
            self.assertEqual(lines, [
                prefix + "path=default_node_pool[0].upgrade_settings changed=true block=removed",
                prefix + "path=default_node_pool[0].upgrade_settings[0].max_surge changed=true",
                prefix + "other_changed_paths=unknown status=UNKNOWN"])
            self.assertNotIn(sentinel, "\n".join(lines))

    def test_drift_summary_keeps_refusal_and_never_calls_apply(self):
        a, c, e, plan, addresses = rotation_fixture()
        sentinel = "private-password-token-provider-stderr-path-version-sentinel"
        drift = copy.deepcopy(plan["resource_changes"][0])
        drift["change"].update({"actions": ["update"], "before": {sentinel: sentinel},
                                "after": {sentinel: sentinel}})
        plan["resource_drift"] = [drift, {"address": sentinel, "change": {"actions": [sentinel]}}]
        plan["resource_changes"][-1] = {"address": sentinel, "change": {"actions": [sentinel]}}
        aks = next(entry for entry in plan["resource_changes"]
                   if entry["address"] == "azurerm_kubernetes_cluster.this")
        aks["change"].update(actions=["update"],
                             before={"id": sentinel, "default_node_pool": [
                                 {"upgrade_settings": [{"max_surge": sentinel}]}]},
                             after={"id": sentinel, "default_node_pool": [{"upgrade_settings": []}]})
        for operation in ("plan", "apply"):
            for fail_diagnostic in (False, True, "aks", "fields"):
                with self.subTest(operation=operation, fail_diagnostic=fail_diagnostic):
                    calls, directories = [], []
                    output, errors = io.StringIO(), io.StringIO()

                    def fake(command, **kwargs):
                        calls.append(command[2])
                        directories.append(Path(command[1].removeprefix("-chdir=")))
                        return subprocess.CompletedProcess(command, 0, json.dumps(plan).encode()
                                                           if command[2] == "show" else sentinel.encode(),
                                                           sentinel.encode())

                    diagnostic = execution.drift_diagnostics
                    with contextlib.redirect_stdout(output), contextlib.redirect_stderr(errors), \
                         patch.dict(os.environ, e | {"P6_OPERATION": operation}, clear=True), \
                         patch.object(execution.dt, "datetime", FixedDateTime), \
                         patch.object(execution, "check_source"), \
                         patch.object(execution, "drift_diagnostics", side_effect=RuntimeError(sentinel)
                                      if fail_diagnostic is True else diagnostic), \
                         patch.object(execution, "aks_planned_diagnostics", side_effect=RuntimeError(sentinel)
                                      if fail_diagnostic == "aks" else execution.aks_planned_diagnostics), \
                         patch.object(execution, "drift_field_diagnostic", side_effect=RuntimeError(sentinel)
                                      if fail_diagnostic == "fields" else execution.drift_field_diagnostic), \
                         patch.object(execution.subprocess, "run", side_effect=fake), \
                         self.assertRaises(execution.PlanGuardError) as refused:
                        execution.execute(a, c)
                    self.assertEqual(refused.exception.code, "RESOURCE_DRIFT")
                    expected = ["plan guard refused: RESOURCE_DRIFT"]
                    if fail_diagnostic:
                        expected.append("drift diagnostic: unavailable")
                    else:
                        # Literal expectations verify both counts independently of the implementation.
                        expected.extend([
                            "drift diagnostic: resource_drift entries=2 shown=1 withheld=1 status=WITHHELD",
                            "drift diagnostic: resource_drift resource=" + drift["address"] + " actions=update",
                            "drift fields diagnostic: resource=" + drift["address"] +
                            " named_changed_fields=none other_changed_fields=0 status=KNOWN",
                            "drift diagnostic: resource_changes entries=34 shown=33 withheld=1 status=WITHHELD",
                        ])
                        for entry in plan["resource_changes"][:-1]:
                            action = "update" if entry["address"] in (
                                execution.POSTGRESQL, "azurerm_kubernetes_cluster.this") else "no-op"
                            expected.append("drift diagnostic: resource_changes resource=" + entry["address"] +
                                            " actions=" + action)
                        expected.extend([
                            "aks planned diagnostic: path=default_node_pool[0].upgrade_settings "
                            "changed=true block=removed",
                            "aks planned diagnostic: path=default_node_pool[0].upgrade_settings[0].max_surge "
                            "changed=true",
                            "aks planned diagnostic: other_changed_paths=0 status=KNOWN",
                        ])
                    self.assertEqual(errors.getvalue(), "\n".join(expected) + "\n")
                    self.assertEqual(calls, ["init", "validate", "plan", "show", "state"])
                    self.assertTrue(all(not path.exists() for path in directories))
                    self.assertNotIn("planned:", output.getvalue())
                    for private in (sentinel, json.dumps(plan), e["P6_POSTGRESQL_ADMINISTRATOR_PASSWORD"],
                                    e["ACTIONS_ID_TOKEN_REQUEST_TOKEN"]):
                        self.assertNotIn(private, output.getvalue() + errors.getvalue())

    def test_policy_on_plan_dispatch_and_missing_policy_on_apply(self):
        a, _, _, plan, addresses = rotation_fixture()
        execution.validate_plan(a, "environment", "plan", plan, addresses)
        a.pop("plan_policy")
        with self.assertRaises(execution.PlanGuardError) as refused:
            execution.validate_plan(a, "environment", "apply", plan, addresses)
        self.assertEqual(refused.exception.code, "POLICY_REQUIRED")
        with self.assertRaises(execution.PlanGuardError) as refused:
            execution.validate_plan(a | {"plan_policy": execution.ROTATION_POLICY},
                                    "foundation", "apply", plan, addresses)
        self.assertEqual(refused.exception.code, "POLICY_OPERATION")
        # An unguarded plan-only dispatch is still inspection, never mutation.
        execution.validate_plan(a, "environment", "plan", plan, addresses)

    def test_cli_sanitizes_json_and_unexpected_guard_exceptions(self):
        a, c, e, plan, _ = rotation_fixture()
        sentinel = "private-password-token-provider-stderr-path-version-sentinel"
        entrypoint = (ROOT / "scripts/azure-execution.py").read_text().split('if __name__ == "__main__":', 1)[1]
        cases = [
            (b'{"' + sentinel.encode(), None, "PLAN_JSON_INVALID"),
            (b'\xff' + sentinel.encode(), None, "PLAN_JSON_INVALID"),
            (json.dumps(plan).encode(), ValueError(sentinel), "VALIDATION_EXCEPTION"),
            (json.dumps(plan).encode(), KeyError(sentinel), "VALIDATION_EXCEPTION"),
            (json.dumps(plan).encode(), TypeError(sentinel), "VALIDATION_EXCEPTION"),
            (json.dumps(plan).encode(), RuntimeError(sentinel), "VALIDATION_EXCEPTION"),
            (json.dumps(plan).encode(), execution.PlanGuardError(sentinel, sentinel), "VALIDATION_EXCEPTION"),
            (json.dumps(plan).encode(), execution.PlanGuardError("ATTRIBUTE_DIFF", sentinel), "ATTRIBUTE_DIFF"),
        ]
        for operation in ("plan", "apply"):
            for body, error, expected in cases:
                with self.subTest(operation=operation, code=expected):
                    calls, directories = [], []
                    output, errors = io.StringIO(), io.StringIO()

                    def fake(command, **kwargs):
                        calls.append(command[2])
                        directories.append(Path(command[1].removeprefix("-chdir=")))
                        return subprocess.CompletedProcess(command, 0, body if command[2] == "show"
                                                           else sentinel.encode(), sentinel.encode())

                    with contextlib.redirect_stdout(output), contextlib.redirect_stderr(errors), \
                         patch.dict(os.environ, e | {"P6_OPERATION": operation}, clear=True), \
                         patch.object(execution.dt, "datetime", FixedDateTime), \
                         patch.object(execution, "check_source"), \
                         patch.object(execution, "validate_plan", side_effect=error), \
                         patch.object(execution.subprocess, "run", side_effect=fake), \
                         self.assertRaises(SystemExit) as exit_status:
                        # Exercise the real CLI exception handler as well as execute's diagnostic boundary.
                        exec('if True:' + entrypoint, execution.__dict__ | {"main": lambda: execution.execute(a, c)})
                    self.assertEqual(exit_status.exception.code, 1)
                    self.assertEqual(calls, ["init", "validate", "plan", "show", "state"])
                    self.assertTrue(all(not path.exists() for path in directories))
                    self.assertIn("plan guard refused: " + expected + "\n", errors.getvalue())
                    self.assertIn("P6 execution refused/failed;", errors.getvalue())
                    self.assertNotIn("resource=", errors.getvalue())
                    self.assertNotIn(sentinel, output.getvalue() + errors.getvalue())
                    self.assertNotIn("Traceback", errors.getvalue())


class WorkflowBoundaryTest(unittest.TestCase):
    def test_config_secret_is_scoped_to_python_steps_without_shell_decode(self):
        workflow = (ROOT / ".github/workflows/azure-execution.yml").read_text()
        self.assertNotRegex(workflow, r"\bP6_EXECUTION_CONFIG\b")
        self.assertNotIn("P6_EXECUTION_CONFIG_B64", workflow.split("\njobs:", 1)[0])
        uses = []
        for step in re.split(r"^      - ", workflow, flags=re.M)[1:]:
            if "P6_EXECUTION_CONFIG_B64" in step:
                self.assertIn("        env:\n          P6_EXECUTION_CONFIG_B64: ${{ secrets.P6_EXECUTION_CONFIG_B64 }}", step)
                self.assertEqual(step.count("P6_EXECUTION_CONFIG_B64"), 2)
                command = re.search(r"^        run: (.+)$", step, re.M).group(1)
                uses.append(command)
        self.assertEqual(uses, ["python3 scripts/azure-execution.py gate", "python3 scripts/azure-execution.py execute"])
        self.assertNotIn("GITHUB_ENV", workflow)
        self.assertNotIn("GITHUB_OUTPUT", workflow)

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
