#!/usr/bin/env python3
"""GnuPG dummy-data backup/restore drill; no Terraform state or credentials."""
import os
import hashlib
import json
from pathlib import Path
import secrets
import subprocess
import tempfile
import tarfile
import unittest


class DummyRestoreTest(unittest.TestCase):
    def test_encrypted_backup_restore_and_wrong_passphrase(self):
        with tempfile.TemporaryDirectory(prefix="bootstrap-dummy-") as temporary:
            work = Path(temporary)
            work.chmod(0o700)
            gnupg = work / "gnupg"
            gnupg.mkdir(mode=0o700)
            data = b'{"fixture":"dummy-only-not-terraform-state","sequence":1}\n'
            source, backup, restored = [work / name for name in ("dummy.json", "bootstrap.tar.gpg", "restored.tar")]
            source.touch(mode=0o600)
            source.write_bytes(data)
            manifest = work / "manifest.json"
            manifest.touch(mode=0o600)
            manifest.write_text(json.dumps({"fixture": "dummy-only", "sha256": hashlib.sha256(data).hexdigest()}))
            archive = work / "bootstrap.tar"
            archive.touch(mode=0o600)
            with tarfile.open(archive, "w") as bundle:
                for path in (source, manifest):
                    bundle.add(path, arcname=path.name)
            key = work / "dummy-passphrase"
            key.touch(mode=0o600)
            key.write_text(secrets.token_hex(32))
            command = ["gpg", "--homedir", str(gnupg), "--batch", "--pinentry-mode", "loopback",
                       "--no-symkey-cache", "--passphrase-file", str(key)]
            # Explicit mode before encryption/decryption; no temporary plaintext copies in Git/CI artifacts.
            backup.touch(mode=0o600)
            restored.touch(mode=0o600)
            env = {"PATH": os.environ["PATH"]}
            subprocess.run(command + ["--yes", "--cipher-algo", "AES256", "--output", str(backup),
                                      "--symmetric", str(archive)], env=env, capture_output=True, check=True)
            self.assertNotIn(data, backup.read_bytes())
            source.unlink()
            manifest.unlink()
            archive.unlink()
            subprocess.run(command + ["--yes", "--output", str(restored), "--decrypt", str(backup)],
                           env=env, capture_output=True, check=True)
            with tarfile.open(restored) as bundle:
                self.assertEqual(set(bundle.getnames()), {"dummy.json", "manifest.json"})
                restored_data = bundle.extractfile("dummy.json").read()
                restored_manifest = json.load(bundle.extractfile("manifest.json"))
            self.assertEqual(restored_data, data)
            self.assertEqual(hashlib.sha256(restored_data).hexdigest(), restored_manifest["sha256"])
            self.assertEqual(work.stat().st_mode & 0o777, 0o700)
            for path in (backup, restored, key):
                self.assertEqual(path.stat().st_mode & 0o777, 0o600)
            key.write_text("deliberately-wrong-dummy-passphrase")
            failed = subprocess.run(command + ["--output", os.devnull, "--decrypt", str(backup)],
                                    env=env, capture_output=True)
            self.assertNotEqual(failed.returncode, 0)
            # Test agent only; never stop the operator's ordinary gpg-agent.
            subprocess.run(["gpgconf", "--homedir", str(gnupg), "--kill", "gpg-agent"],
                           env=env, capture_output=True, check=True)


if __name__ == "__main__":
    unittest.main()
