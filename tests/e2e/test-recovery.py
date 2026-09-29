#!/usr/bin/env python3
"""Deterministic rejection cases for a coordinated recovery proof."""

import copy
import hashlib
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))
import importlib.util

module_path = Path(__file__).resolve().parents[2] / "scripts" / "validate-recovery.py"
spec = importlib.util.spec_from_file_location("recovery_validator", module_path)
validator = importlib.util.module_from_spec(spec)
spec.loader.exec_module(validator)


def storage(seed):
    return {
        "forgejo": {"pvc_uid": seed + "f", "pv_name": seed + "fv", "pv_uid": seed + "fp"},
        "postgres": {"pvc_uid": seed + "p", "pv_name": seed + "pv", "pv_uid": seed + "pp"},
    }


class RecoveryValidationTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.root.chmod(0o700)
        fixture_records = [
            {"metadata": {"namespace": ns, "name": name}, "data": {"key": "YQ=="}}
            for ns, name in (
                ("forgejo", "forgejo-admin"), ("forgejo", "forgejo-db"),
                ("forgejo", "forgejo-inline-config"), ("postgres", "postgres-credentials")
            )
        ]
        components = {}
        for name, content in (
            ("database.dump", b"PGDMP example"),
            ("application-data.tar", b"tar example"),
            ("secrets.json", json.dumps(fixture_records).encode()),
        ):
            path = self.root / name
            fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            with os.fdopen(fd, "wb") as stream:
                stream.write(content)
            components[name] = {
                "filename": name, "size": len(content),
                "sha256": hashlib.sha256(content).hexdigest(), "result": "success",
            }
        self.manifest = {
            "schema_version": 1, "backup_complete": True, "checkpoint_id": "test",
            "source_sha": "a" * 40, "source_server_id": "server-a",
            "argo_values_revision": "b" * 40, "forgejo_image_id": "sha256:f",
            "postgres_image_id": "sha256:p", "forgejo_chart_digest": "sha256:c",
            "forgejo_version": "15.0.9", "source_storage": storage("a"),
            "components": components,
            "fixture": {key: "present" for key in (
                "user", "repository", "main_sha", "feature_sha",
                "pull_number", "issue_number", "pat_precheck", "session_precheck"
            )},
        }
        self.write_manifest()

    def write_manifest(self):
        (self.root / "manifest.json").write_text(json.dumps(self.manifest))

    def test_complete_bundle(self):
        validator.validate_bundle(self.root)

    def test_incomplete_bundle(self):
        self.manifest["backup_complete"] = False
        self.write_manifest()
        with self.assertRaisesRegex(ValueError, "incomplete backup"):
            validator.validate_bundle(self.root)

    def test_checksum_mismatch(self):
        (self.root / "database.dump").write_bytes(b"changed text")
        with self.assertRaisesRegex(ValueError, "size mismatch|checksum mismatch"):
            validator.validate_bundle(self.root)

    def test_missing_component(self):
        (self.root / "application-data.tar").unlink()
        with self.assertRaisesRegex(ValueError, "missing"):
            validator.validate_bundle(self.root)

    def result(self):
        phases = {name: True for name in (
            "source_ready", "fixture_ready", "autosync_stopped", "forgejo_stopped",
            "bundle_validated", "source_cleaned", "target_prepared", "database_restored",
            "application_data_restored", "secrets_restored", "forgejo_started", "healthz",
            "source_doctor_calibrated", "target_doctor_verified", "retained_state",
            "same_pat", "same_session", "new_write",
            "database_write", "filesystem_write", "argo_return", "post_reconcile_state",
            "regression", "target_cleaned", "raw_cleaned"
        )}
        return {
            "schema_version": 1, "completed": True, "checkpoint_id": "test",
            "source_server_id": "server-a", "target_server_id": "server-b",
            "source_storage": storage("a"), "target_storage": storage("b"),
            "phases": phases, "pat_identity": "pre_backup_token",
            "session_identity": "pre_backup_cookie",
            "doctor": {
                "selected_integrity_checks": list(validator.DOCTOR_CHECKS),
                "applicable_status": "pass",
                "paths_status": "known_source_baseline_diagnostic",
                "paths_finding": "missing_/data/log",
                "gc_lfs_status": "not_applicable", "lfs_start_server": False,
            },
            "restore_completed_before_start": True,
            "argo_policy": {"enabled": True, "selfHeal": True, "prune": False},
        }

    def assert_result_rejected(self, result, message):
        path = self.root / "result.json"
        path.write_text(json.dumps(result))
        with self.assertRaisesRegex(ValueError, message):
            validator.validate_result(path)

    def test_complete_result(self):
        path = self.root / "result.json"
        path.write_text(json.dumps(self.result()))
        validator.validate_result(path)

    def test_reused_storage_or_cluster(self):
        result = self.result()
        result["target_storage"] = copy.deepcopy(result["source_storage"])
        self.assert_result_rejected(result, "storage reused")
        result = self.result()
        result["target_server_id"] = result["source_server_id"]
        self.assert_result_rejected(result, "source server reused")

    def test_ambiguous_ownership(self):
        result = self.result()
        result["source_server_id"] = ""
        self.assert_result_rejected(result, "cluster identity absent")

    def test_restore_or_doctor_failure(self):
        result = self.result()
        result["phases"]["database_restored"] = False
        self.assert_result_rejected(result, "required recovery phase")
        result = self.result()
        result["doctor"]["applicable_status"] = "failed"
        self.assert_result_rejected(result, "doctor classification")

    def test_missing_target_uid(self):
        result = self.result()
        result["target_storage"]["postgres"]["pv_uid"] = ""
        self.assert_result_rejected(result, "storage identity absent")

    def test_doctor_not_promoted_to_restored(self):
        result = self.result()
        result["phases"]["target_doctor_verified"] = False
        self.assert_result_rejected(result, "required recovery phase")

    def doctor_fixture(self):
        directory = self.root / "doctor"
        directory.mkdir(mode=0o700)
        (directory / "app.ini").write_text("APP_NAME = Forgejo\n[server]\nDISABLE_SSH = true\n[log]\n")
        (directory / "env.txt").write_text("PATH=/usr/bin\n")
        (directory / "metadata.json").write_text(json.dumps({
            "forgejo_version": "15.0.9+gitea-1.22.0", "forgejo_image_id": "sha256:test"
        }))
        inventory = ["Default\tName\t\t\t\t\tTitle"]
        for name in ("gc-lfs", "paths", *validator.DOCTOR_CHECKS, "authorized-keys"):
            mark = "*" if name in validator.DOCTOR_DEFAULTS else ""
            inventory.append(f"{mark}\t{name}\t\tTitle for {name}")
        (directory / "inventory.txt").write_text("\n".join(inventory) + "\n")
        paths = ["", "[1] Check paths and basic configuration"]
        for label, path in validator.PATHS.items():
            paths.append(f' - [I] {label}:  "{path}"')
            if label == "Log Root Path":
                paths.append(" - [E]     Is REQUIRED but is not accessible. ERROR: stat /data/log: no such file or directory")
        paths += [" - [E] Please check your configuration files and try again.", "FAIL",
                  "Command error: 1 configuration files with errors",
                  "command terminated with exit code 1"]
        (directory / "paths.txt").write_text("\n".join(paths) + "\n")
        (directory / "paths.exit").write_text("1\n")
        for name in validator.DOCTOR_CHECKS:
            (directory / f"{name}.txt").write_text(
                f"\n[1] Title for {name}\nOK\n\nAll done (checks: 1).\n")
            (directory / f"{name}.exit").write_text("0\n")
        return directory

    def test_selected_doctor_inventory_and_bounded_paths(self):
        directory = self.doctor_fixture()
        snapshot = validator.validate_doctor(directory)
        self.assertEqual([check["name"] for check in snapshot["selected"]],
                         list(validator.DOCTOR_CHECKS))
        self.assertEqual(snapshot["not_applicable"]["gc-lfs"], "LFS_START_SERVER=false")
        self.assertEqual(snapshot["paths"]["status"], "known_source_baseline_diagnostic")

    def test_gc_lfs_na_only_when_disabled(self):
        directory = self.doctor_fixture()
        (directory / "app.ini").write_text(
            "[server]\nLFS_START_SERVER = true\nDISABLE_SSH = true\n[log]\n")
        with self.assertRaisesRegex(ValueError, "gc-lfs N/A requires disabled LFS"):
            validator.validate_doctor(directory)

    def test_unexpected_source_doctor_failure(self):
        directory = self.doctor_fixture()
        (directory / "check-db-consistency.txt").write_text(
            "\n[1] Title for check-db-consistency\n - [W] Found 1 orphaned issue\nOK\n\nAll done (checks: 1).\n")
        with self.assertRaisesRegex(ValueError, "doctor check-db-consistency diagnostic"):
            validator.validate_doctor(directory)

    def test_target_only_doctor_failure(self):
        directory = self.doctor_fixture()
        source = validator.validate_doctor(directory)
        (directory / "check-user-type.exit").write_text("1\n")
        with self.assertRaisesRegex(ValueError, "doctor check-user-type failed"):
            validator.validate_doctor(directory, source)

    def test_second_path_error_rejected(self):
        directory = self.doctor_fixture()
        path = directory / "paths.txt"
        path.write_text(path.read_text().replace(
            " - [E] Please check",
            " - [E]     Is REQUIRED but is not accessible. ERROR: stat /data/git: no such file or directory\n - [E] Please check"))
        with self.assertRaisesRegex(ValueError, "unexpected doctor paths diagnostic"):
            validator.validate_doctor(directory)

    def test_selected_check_missing_from_inventory(self):
        directory = self.doctor_fixture()
        inventory = directory / "inventory.txt"
        inventory.write_text("\n".join(
            line for line in inventory.read_text().splitlines()
            if "\tcheck-db-consistency\t" not in line) + "\n")
        with self.assertRaisesRegex(ValueError, "selected doctor check absent"):
            validator.validate_doctor(directory)

    def test_paths_exception_is_not_a_wildcard(self):
        directory = self.doctor_fixture()
        path = directory / "paths.txt"
        path.write_text(path.read_text().replace("/data/log: no such file", "/data/other: no such file"))
        with self.assertRaisesRegex(ValueError, "unexpected doctor paths diagnostic"):
            validator.validate_doctor(directory)

    def test_credential_substitution(self):
        result = self.result()
        result["pat_identity"] = "reissued"
        self.assert_result_rejected(result, "credential continuity substituted")
        result = self.result()
        result["session_identity"] = "new_login"
        self.assert_result_rejected(result, "credential continuity substituted")

    def test_pre_restore_start(self):
        result = self.result()
        result["restore_completed_before_start"] = False
        self.assert_result_rejected(result, "Forgejo started before restore")


if __name__ == "__main__":
    unittest.main()
