"""Static-only only for a complete Terraform-only PR diff; every uncertain result falls back to full runtime."""
import importlib.util
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
import urllib.error

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location("impact", ROOT / "scripts/ci-change-impact.py")
impact = importlib.util.module_from_spec(spec)
spec.loader.exec_module(impact)

REPO, PR, HEAD, BASE = "owner/repo", "7", "a" * 40, "c" * 40
TF = "infra/terraform/environment/main.tf"


def api(files, head=HEAD, changed_files=None, pages=None, heads=None):
    """Fake GitHub API. `pages`로 page 응답을, `heads`로 연속 PR 조회의 (head, count[, base ref, base SHA])를 바꿀 수 있다."""
    entries = [f if isinstance(f, dict) else {"filename": f} for f in files]
    count = len(entries) if changed_files is None else changed_files
    pr_calls = iter(heads or [])

    def get_json(path):
        if path == f"/repos/{REPO}/pulls/{PR}":
            sha, n, ref, base = (*next(pr_calls, (head, count)), "main", BASE)[:4]
            return {"head": {"sha": sha}, "base": {"ref": ref, "sha": base}, "changed_files": n}
        prefix = f"/repos/{REPO}/pulls/{PR}/files?per_page=100&page="
        assert path.startswith(prefix), path
        page = int(path[len(prefix):])
        if pages is not None:
            return pages(page)
        return entries[(page - 1) * 100:page * 100]
    return get_json


def decide(get_json, head=HEAD, checked_out=HEAD):
    return impact.decide(get_json, REPO, PR, head, checked_out)


class ChangeImpactTest(unittest.TestCase):
    def assert_static(self, *files):
        decision, reason = decide(api(files))
        self.assertEqual(decision, "static-only", reason)

    def assert_full(self, get_json, expected, **kwargs):
        decision, reason = decide(get_json, **kwargs)
        self.assertEqual(decision, "full-runtime", reason)
        self.assertIn(expected, reason)

    # Positive: allowlist만 포함한 complete PR diff.
    def test_terraform_source_only(self):
        self.assert_static(TF, "infra/terraform/bootstrap/main.tf", "infra/terraform/foundation/tests/security.tftest.hcl")

    def test_terraform_readme_and_lockfile_only(self):
        self.assert_static("infra/terraform/environment/README.md", "infra/terraform/foundation/.terraform.lock.hcl")

    def test_terraform_verifier_only(self):
        self.assert_static("scripts/terraform-verify.sh")

    def test_terraform_source_and_verifier(self):
        self.assert_static(TF, "scripts/terraform-verify.sh")

    def test_paginated_terraform_only(self):
        files = [f"infra/terraform/environment/f{i}.tf" for i in range(250)]
        decision, reason = decide(api(files))
        self.assertEqual((decision, reason), ("static-only", "all 250 changed paths are Azure Terraform static-only"))

    def test_exact_page_multiple(self):
        self.assert_static(*[f"infra/terraform/environment/f{i}.tf" for i in range(200)])

    # Negative: allowlist 밖의 path가 하나라도 있으면 full runtime.
    def test_runtime_impacting_paths(self):
        for path in ("platform/local/k3d.yaml", "scripts/local-up.sh", "Makefile", "versions.env",
                     ".github/workflows/local-platform.yml", "experiments/fixtures/shared-gate/gate.yaml",
                     "tests/e2e/forgejo-developer-journey.sh", "cmd/ext-authz-sim/main.py", ".gitignore",
                     "scripts/ci-change-impact.py", "docs/local-operations.md"):
            with self.subTest(path=path):
                self.assert_full(api([TF, path]), repr(path))

    def test_unrecognized_or_lookalike_paths(self):
        for path in ("unknown/file", "infra/terraform", "infra/terraform-legacy/main.tf", "infra/main.tf",
                     "scripts/terraform-verify.sh.bak", "infra/terraform/../../platform/local/k3d.yaml",
                     "/infra/terraform/main.tf", "infra//terraform/main.tf"):
            with self.subTest(path=path):
                self.assert_full(api([TF, path]), repr(path))

    def test_rename_from_runtime_path(self):
        moved = {"filename": "infra/terraform/environment/moved.tf", "previous_filename": "platform/local/k3d.yaml",
                 "status": "renamed"}
        self.assert_full(api([moved]), "'platform/local/k3d.yaml'")

    def test_earlier_commit_runtime_file_is_not_hidden(self):
        # 최신 commit은 Terraform만 바꿨지만 PR 전체 diff에는 이전 commit의 runtime path가 남아 있다.
        # Classifier는 commit delta가 아니라 PR base → HEAD 전체 file set만 입력으로 받는다.
        self.assert_full(api(["platform/forgejo/values-common.yaml", TF]), "platform/forgejo/values-common.yaml")

    def test_git_history_latest_commit_does_not_hide_earlier_file(self):
        # 실제 Git history로도 같은 상황을 만들어, PR 전체 3-dot diff와 latest-commit delta가 다름을 확인한다.
        with tempfile.TemporaryDirectory() as work:
            env = {"PATH": os.environ["PATH"], "HOME": work, "GIT_CONFIG_NOSYSTEM": "1",
                   "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@example.invalid",
                   "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@example.invalid"}

            def git(*args):
                return subprocess.run(["git", "-C", work, *args], env=env, check=True, capture_output=True,
                                      text=True).stdout

            def commit(path, message):
                target = Path(work, path)
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text(message)
                git("add", path)
                git("commit", "-qm", message)
            git("init", "-q", "-b", "main")
            commit("README.md", "base")
            git("switch", "-qc", "feature")
            commit("platform/local/k3d.yaml", "runtime")
            commit(TF, "terraform")
            latest = git("diff", "--name-only", "HEAD~1", "HEAD").split()
            full = git("diff", "--name-only", "main...HEAD").split()
            head = git("rev-parse", "HEAD").strip()
        self.assertEqual(impact.classify(set(latest))[0], "static-only")
        self.assert_full(api(full, head=head), "platform/local/k3d.yaml", head=head, checked_out=head)

    # Fail closed: diff/HEAD/API/pagination이 불확실하면 full runtime.
    def test_empty_diff(self):
        self.assert_full(api([]), "changed_files is missing or empty")

    def test_incomplete_diff(self):
        self.assert_full(api([TF], changed_files=2), "returned 1 entries but PR reports 2")
        self.assert_full(api([TF, TF.replace("main", "x")], changed_files=1), "returned 2 entries but PR reports 1")

    def test_files_api_limit(self):
        self.assert_full(api([TF], changed_files=3000), "reaches files API limit")

    def test_pagination_does_not_terminate(self):
        page = [{"filename": f"infra/terraform/environment/f{i}.tf"} for i in range(100)]
        self.assert_full(api([], changed_files=2999, pages=lambda n: page), "pagination did not terminate")

    def test_truncated_or_malformed_page(self):
        for label, pages in (("short first page", lambda n: [{"filename": TF}] if n == 1 else []),
                             ("non-list page", lambda n: {"message": "error"}),
                             ("missing filename", lambda n: [{"status": "modified"}]),
                             ("invalid previous_filename", lambda n: [{"filename": TF, "previous_filename": ""}])):
            with self.subTest(label):
                decision, reason = decide(api([TF, TF + ".x"], pages=pages))
                self.assertEqual(decision, "full-runtime", reason)
                self.assertTrue(reason.startswith("PR diff uncertain:"), reason)

    def test_invalid_head(self):
        self.assert_full(api([TF]), "checked-out HEAD does not match", head="not-a-sha", checked_out="not-a-sha")
        self.assert_full(api([TF]), "checked-out HEAD does not match", checked_out="b" * 40)
        self.assert_full(api([TF], head="b" * 40), "API PR head differs")

    def test_head_moves_during_listing(self):
        self.assert_full(api([TF], heads=[(HEAD, 1), ("b" * 40, 1)]), "API PR head differs")
        self.assert_full(api([TF], heads=[(HEAD, 1), (HEAD, 2)]), "changed_files changed during listing")

    def test_base_moves_during_listing(self):
        # Retarget 또는 base rewrite: head와 changed_files가 같아도 base가 바뀌면 page들이 같은 diff라고 볼 수 없다.
        for label, after in (("retarget", (HEAD, 1, "release", BASE)), ("base rewrite", (HEAD, 1, "main", "d" * 40))):
            with self.subTest(label):
                self.assert_full(api([TF], heads=[(HEAD, 1), after]), "base ref/SHA changed during listing")

    def test_missing_or_invalid_base(self):
        for base in ({}, {"ref": "main"}, {"ref": "", "sha": BASE}, {"ref": "main", "sha": "not-a-sha"}):
            with self.subTest(base=base):
                get_json = api([TF])
                pr = lambda path: ({"head": {"sha": HEAD}, "base": base, "changed_files": 1}
                                   if path.endswith(f"/pulls/{PR}") else get_json(path))
                self.assert_full(pr, "base ref/SHA is missing or invalid")

    def test_api_failure(self):
        def failing(error):
            def get_json(path):
                raise error
            return get_json
        for error in (urllib.error.HTTPError("u", 502, "bad gateway", {}, None), urllib.error.URLError("down"),
                      TimeoutError(), ValueError("invalid JSON"), KeyError("GH_TOKEN")):
            with self.subTest(error=type(error).__name__):
                self.assert_full(failing(error), f"PR diff unavailable: {type(error).__name__}")

    def test_invalid_arguments(self):
        self.assertEqual(impact.decide(api([TF]), "bad repo", PR, HEAD, HEAD)[0], "full-runtime")
        self.assertEqual(impact.decide(api([TF]), REPO, "0", HEAD, HEAD)[0], "full-runtime")

    def test_cli_fails_closed_without_credentials(self):
        # Token/network 없이 실제 CLI를 실행해도 한 줄 full-runtime 판정을 내고 Azure/GitHub credential을 요구하지 않는다.
        env = {"PATH": os.environ["PATH"], "GITHUB_API_URL": "http://127.0.0.1:9"}
        for args in ([], [REPO, PR, HEAD, HEAD]):
            with self.subTest(args=args):
                out = subprocess.run([sys.executable, str(ROOT / "scripts/ci-change-impact.py"), *args], env=env,
                                     check=True, capture_output=True, text=True).stdout
                self.assertEqual(out.count("\n"), 1)
                self.assertTrue(out.startswith("full-runtime\t"), out)


if __name__ == "__main__":
    unittest.main(verbosity=1)
