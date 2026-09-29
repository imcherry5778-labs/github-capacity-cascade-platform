#!/usr/bin/env python3
"""Fail-closed validation for one local coordinated recovery checkpoint/result."""

import hashlib
import json
import re
import sys
from pathlib import Path


COMPONENTS = ("database.dump", "application-data.tar", "secrets.json")
SECRET_NAMES = {
    "forgejo/forgejo-admin", "forgejo/forgejo-db",
    "forgejo/forgejo-inline-config", "postgres/postgres-credentials",
}
IDENTITY = re.compile(r"^[0-9a-f]{40}$")
DOCTOR_CHECKS = {
    "check-db-version": "default; pinned schema version",
    "check-db-consistency": "database integrity; read-only without --fix",
    "check-user-type": "default; enabled user model",
    "synchronize-repo-heads": "default; enabled Git repositories; read-only without --fix",
}
DOCTOR_DEFAULTS = set(DOCTOR_CHECKS) - {"check-db-consistency"} | {"paths", "authorized-keys"}
PATHS = {
    "Configuration File Path": "/data/gitea/conf/app.ini",
    "Repository Root Path": "/data/git/gitea-repositories",
    "Data Root Path": "/data",
    "Custom File Root Path": "/data/gitea",
    "Work directory": "/data",
    "Log Root Path": "/data/log",
}
ANSI = re.compile(r"\x1b\[[0-9;]*m")


def require(ok, message):
    if not ok:
        raise ValueError(message)


def load(path):
    with Path(path).open(encoding="utf-8") as stream:
        return json.load(stream)


def doctor_config(directory):
    # The pinned v15.0.9 binary defaults these absent keys to false/console/workdir/log.
    section = ""
    keys = {}
    for line in (directory / "app.ini").read_text().splitlines():
        line = line.strip()
        if line.startswith("[") and line.endswith("]"):
            section = line[1:-1].lower()
        elif "=" in line and not line.startswith(("#", ";")):
            key, value = (part.strip() for part in line.split("=", 1))
            if (section, key.upper()) in {
                ("server", "LFS_START_SERVER"), ("server", "DISABLE_SSH"),
                ("log", "MODE"), ("log", "ROOT_PATH")
            }:
                require((section, key.upper()) not in keys, "duplicate doctor config key")
                keys[(section, key.upper())] = value
    overrides = re.findall(r"^(?:FORGEJO|GITEA)__(?:server__(?:LFS_START_SERVER|DISABLE_SSH)|log__(?:MODE|ROOT_PATH))=.*$",
                           (directory / "env.txt").read_text(), re.MULTILINE | re.IGNORECASE)
    require(not overrides,
            "doctor config environment override")
    lfs = keys.get(("server", "LFS_START_SERVER"), "false").lower()
    ssh = keys.get(("server", "DISABLE_SSH"), "false").lower()
    mode = keys.get(("log", "MODE"), "console").lower()
    root = keys.get(("log", "ROOT_PATH"), "/data/log")
    require(lfs in {"false", "true"}, "LFS_START_SERVER value")
    require(ssh == "true", "authorized-keys N/A requires disabled SSH")
    require(mode == "console" and root == "/data/log", "logging baseline differs")
    require(lfs == "false", "gc-lfs N/A requires disabled LFS")
    return {"lfs_start_server": False, "ssh_disabled": True,
            "log_mode": mode, "log_root_path": root,
            "lfs_setting": "explicit" if ("server", "LFS_START_SERVER") in keys else "v15.0.9_default",
            "log_mode_setting": "explicit" if ("log", "MODE") in keys else "v15.0.9_default",
            "log_root_setting": "explicit" if ("log", "ROOT_PATH") in keys else "v15.0.9_workdir_default"}


def doctor_inventory(output):
    lines = output.splitlines()
    require(lines and lines[0] == "Default\tName\t\t\t\t\tTitle", "doctor inventory header")
    inventory = []
    for line in lines[1:]:
        match = re.fullmatch(r"(\*?)\t([a-z0-9-]+)\t+(.+)", line)
        require(match is not None, "doctor inventory line")
        inventory.append({"name": match[2], "default": bool(match[1]), "title": match[3]})
    names = [item["name"] for item in inventory]
    require(len(names) == len(set(names)), "duplicate doctor check")
    require(set(DOCTOR_CHECKS) | {"paths", "gc-lfs", "authorized-keys"} <= set(names),
            "selected doctor check absent")
    require({item["name"] for item in inventory if item["default"]} == DOCTOR_DEFAULTS,
            "doctor default inventory changed")
    return inventory


def doctor_paths(output, exit_code):
    output = ANSI.sub("", output)
    lines = output.splitlines()
    observed = {}
    for line in lines:
        match = re.fullmatch(r' - \[I\] (.+?):\s+"([^"]+)"', line)
        if match:
            require(match[1] not in observed, "duplicate doctor path")
            observed[match[1]] = match[2]
    require(observed == PATHS, "doctor path inventory changed")
    diagnostics = [line for line in lines if re.match(r"^ - \[[WEC]\]", line)]
    require(diagnostics == [
        " - [E]     Is REQUIRED but is not accessible. ERROR: stat /data/log: no such file or directory",
        " - [E] Please check your configuration files and try again.",
    ], "unexpected doctor paths diagnostic")
    summary = "Command error: 1 configuration files with errors"
    termination = "command terminated with exit code 1"
    require(exit_code == 1 and lines.count("[1] Check paths and basic configuration") == 1 and
            lines.count("FAIL") == 1 and lines.count(summary) == 1 and
            lines.count(termination) == 1,
            "doctor paths baseline exit/summary changed")
    allowed = set(diagnostics + [summary, termination, "FAIL"])
    require(not any(line not in allowed and re.search(
        r"\b(?:ERROR|WARNING|FAILED|FAIL|CRITICAL)\b", line, re.I) for line in lines),
        "doctor paths extra diagnostic")
    return {"status": "known_source_baseline_diagnostic", "finding": "missing_/data/log",
            "scope": "console_logging_only", "command_exit": exit_code}


def doctor_integrity(name, title, output, exit_code):
    output = ANSI.sub("", output)
    lines = output.splitlines()
    require(exit_code == 0 and "OK" in lines and "All done (checks: 1)." in lines,
            f"doctor {name} failed")
    require(not any(re.match(r"^ - \[[WEC]\]", line) or
                    re.search(r"\b(?:ERROR|FAIL|WARNING|CRITICAL)\b", line, re.I)
                    for line in lines), f"doctor {name} diagnostic")
    require(lines.count(f"[1] {title}") == 1 and lines.count("OK") == 1 and
            lines.count("All done (checks: 1).") == 1,
            f"doctor {name} output incomplete")
    return {"status": "pass", "command_exit": exit_code, "diagnostics": 0}


def validate_doctor(directory, source=None):
    directory = Path(directory)
    meta = load(directory / "metadata.json")
    require(meta.get("forgejo_version", "").startswith("15.0.9+") and
            meta.get("forgejo_image_id"), "doctor runtime version/image")
    config = doctor_config(directory)
    inventory = doctor_inventory((directory / "inventory.txt").read_text())
    paths = doctor_paths((directory / "paths.txt").read_text(),
                         int((directory / "paths.exit").read_text()))
    titles = {item["name"]: item["title"] for item in inventory}
    checks = {name: doctor_integrity(name, titles[name], (directory / f"{name}.txt").read_text(),
                                     int((directory / f"{name}.exit").read_text()))
              for name in DOCTOR_CHECKS}
    result = {"forgejo_version": meta["forgejo_version"],
              "forgejo_image_id": meta["forgejo_image_id"],
              "effective_config": config, "inventory": inventory,
              "selected": [{"name": name, "reason": reason} for name, reason in DOCTOR_CHECKS.items()],
              "checks": checks, "paths": paths,
              "not_applicable": {
                  "gc-lfs": "LFS_START_SERVER=false",
                  "authorized-keys": "SSH disabled in current Core configuration",
              }}
    if source is not None:
        for key in ("forgejo_version", "forgejo_image_id", "effective_config", "inventory",
                    "selected", "paths", "not_applicable"):
            require(result[key] == source.get(key), f"target doctor {key} differs from source")
    return result


def validate_bundle(directory):
    directory = Path(directory)
    require(directory.stat().st_mode & 0o777 == 0o700, "raw bundle directory mode")
    manifest = load(directory / "manifest.json")
    require(manifest.get("schema_version") == 1, "bundle schema")
    require(manifest.get("backup_complete") is True, "incomplete backup")
    require(IDENTITY.fullmatch(manifest.get("source_sha", "")), "source SHA")
    require(manifest.get("checkpoint_id"), "checkpoint ID")
    require(manifest.get("source_server_id"), "source server identity")
    require(manifest.get("argo_values_revision"), "Argo values revision")
    require(manifest.get("forgejo_image_id") and manifest.get("postgres_image_id"), "runtime images")
    require(manifest.get("forgejo_chart_digest") and manifest.get("forgejo_version"), "Forgejo version/chart")
    for name in ("forgejo", "postgres"):
        storage = manifest.get("source_storage", {}).get(name, {})
        require(storage.get("pvc_uid") and storage.get("pv_name") and storage.get("pv_uid"),
                f"{name} source storage identity")
    require(set(manifest.get("components", {})) == set(COMPONENTS), "component inventory")
    for name in COMPONENTS:
        item = manifest["components"][name]
        require(item.get("result") == "success", f"{name} backup failed")
        require(item.get("filename") == name, f"{name} filename")
        component = directory / name
        require(component.is_file() and not component.is_symlink(), f"{name} missing")
        require(component.stat().st_mode & 0o777 == 0o600, f"{name} file mode")
        require(component.stat().st_size > 0 and component.stat().st_size == item.get("size"),
                f"{name} size mismatch")
        digest = hashlib.sha256(component.read_bytes()).hexdigest()
        require(digest == item.get("sha256"), f"{name} checksum mismatch")
    secrets = load(directory / "secrets.json")
    require(isinstance(secrets, list) and len(secrets) == 4, "secret component count")
    names = {f'{s["metadata"]["namespace"]}/{s["metadata"]["name"]}' for s in secrets}
    require(names == SECRET_NAMES and all(s.get("data") for s in secrets), "secret component inventory")
    fixture = manifest.get("fixture", {})
    require(all(fixture.get(k) for k in ("user", "repository", "main_sha", "feature_sha",
                                         "pull_number", "issue_number", "pat_precheck", "session_precheck")),
            "recovery fixture incomplete")
    return manifest


def validate_result(path):
    result = load(path)
    require(result.get("schema_version") == 1 and result.get("completed") is True, "result incomplete")
    require(result.get("source_server_id") != result.get("target_server_id"), "source server reused")
    require(result.get("source_server_id") and result.get("target_server_id"), "cluster identity absent")
    for name in ("forgejo", "postgres"):
        source = result.get("source_storage", {}).get(name, {})
        target = result.get("target_storage", {}).get(name, {})
        require(source.get("pvc_uid") != target.get("pvc_uid") and
                source.get("pv_name") != target.get("pv_name") and
                source.get("pv_uid") != target.get("pv_uid"), f"{name} storage reused")
        require(all(source.get(k) and target.get(k) for k in ("pvc_uid", "pv_name", "pv_uid")),
                f"{name} storage identity absent")
    required = ("source_ready", "fixture_ready", "autosync_stopped", "forgejo_stopped",
                "bundle_validated", "source_cleaned", "target_prepared", "database_restored",
                "application_data_restored", "secrets_restored", "forgejo_started", "healthz",
                "source_doctor_calibrated", "target_doctor_verified", "retained_state",
                "same_pat", "same_session", "new_write",
                "database_write", "filesystem_write", "argo_return", "post_reconcile_state",
                "regression",
                "target_cleaned", "raw_cleaned")
    phases = result.get("phases", {})
    require(all(phases.get(name) is True for name in required), "required recovery phase failed")
    require(result.get("pat_identity") == "pre_backup_token" and
            result.get("session_identity") == "pre_backup_cookie", "credential continuity substituted")
    doctor = result.get("doctor", {})
    require(doctor.get("selected_integrity_checks") == list(DOCTOR_CHECKS) and
            doctor.get("applicable_status") == "pass" and
            doctor.get("paths_status") == "known_source_baseline_diagnostic" and
            doctor.get("paths_finding") == "missing_/data/log" and
            doctor.get("gc_lfs_status") == "not_applicable" and
            doctor.get("lfs_start_server") is False,
            "doctor classification incomplete or failed")
    require(result.get("restore_completed_before_start") is True, "Forgejo started before restore")
    require(result.get("argo_policy") == {"enabled": True, "selfHeal": True, "prune": False},
            "Argo policy mismatch")
    return result


def main():
    if len(sys.argv) == 5 and sys.argv[1] == "doctor":
        source = load(sys.argv[3]) if sys.argv[3] != "-" else None
        result = validate_doctor(sys.argv[2], source)
        Path(sys.argv[4]).write_text(json.dumps(result, indent=2) + "\n")
        print("valid applicable doctor checks and bounded paths baseline")
        return
    if len(sys.argv) != 3 or sys.argv[1] not in {"bundle", "result"}:
        raise SystemExit("usage: validate-recovery.py bundle DIR | result RESULT.json | doctor RAW_DIR SOURCE_OR_- OUTPUT")
    if sys.argv[1] == "bundle":
        manifest = validate_bundle(sys.argv[2])
        print(f'valid bundle: {manifest["checkpoint_id"]}')
    else:
        result = validate_result(sys.argv[2])
        print(f'valid recovery: {result["checkpoint_id"]}')


if __name__ == "__main__":
    try:
        main()
    except (OSError, ValueError, KeyError, TypeError, json.JSONDecodeError) as exc:
        print(f"invalid recovery evidence: {exc}", file=sys.stderr)
        sys.exit(1)
