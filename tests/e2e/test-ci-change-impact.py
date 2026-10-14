"""Static-only only for a complete Terraform-only PR diff; every uncertain result falls back to full runtime.

ChangeImpactTest는 classifier를, WorkflowDecisionTest는 workflow의 실제 classify run block을 검증한다.
"""
import http.server
import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import threading
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


def git_env(work):
    return {"PATH": os.environ["PATH"], "HOME": str(work), "GIT_CONFIG_NOSYSTEM": "1",
            "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@example.invalid",
            "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@example.invalid"}


def git(work, *args):
    return subprocess.run(["git", "-C", str(work), *args], env=git_env(work), check=True, capture_output=True,
                          text=True).stdout


def commit(work, *paths):
    for path in paths:
        target = Path(work, path)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(f"{path} {len(target.read_text()) if target.exists() else 0}\n")
        git(work, "add", path)
    git(work, "commit", "-qm", " ".join(paths))
    return git(work, "rev-parse", "HEAD").strip()


class ChangeImpactTest(unittest.TestCase):
    def assert_static(self, *files):
        decision, reason = decide(api(files))
        self.assertEqual(decision, "static-only", reason)

    def assert_decision(self, expected_decision, get_json, expected, **kwargs):
        decision, reason = decide(get_json, **kwargs)
        self.assertEqual(decision, expected_decision, reason)
        self.assertIn(expected, reason)

    def assert_runtime(self, get_json, expected, **kwargs):
        """Complete diff가 검증됐고 allowlist 밖 path가 있다."""
        self.assert_decision("runtime-impacting", get_json, expected, **kwargs)

    def assert_uncertain(self, get_json, expected, **kwargs):
        """Complete diff를 증명하지 못했다. Workflow는 어떤 shortcut도 없이 full runtime이다."""
        self.assert_decision("uncertain", get_json, expected, **kwargs)

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
                self.assert_runtime(api([TF, path]), repr(path))

    def test_unrecognized_or_lookalike_paths(self):
        for path in ("unknown/file", "infra/terraform", "infra/terraform-legacy/main.tf", "infra/main.tf",
                     "scripts/terraform-verify.sh.bak", "infra/terraform/../../platform/local/k3d.yaml",
                     "/infra/terraform/main.tf", "infra//terraform/main.tf"):
            with self.subTest(path=path):
                self.assert_runtime(api([TF, path]), repr(path))

    def test_rename_from_runtime_path(self):
        moved = {"filename": "infra/terraform/environment/moved.tf", "previous_filename": "platform/local/k3d.yaml",
                 "status": "renamed"}
        self.assert_runtime(api([moved]), "'platform/local/k3d.yaml'")

    def test_earlier_commit_runtime_file_is_not_hidden(self):
        # 최신 commit은 Terraform만 바꿨지만 PR 전체 diff에는 이전 commit의 runtime path가 남아 있다.
        # Classifier는 commit delta가 아니라 PR base → HEAD 전체 file set만 입력으로 받는다.
        self.assert_runtime(api(["platform/forgejo/values-common.yaml", TF]), "platform/forgejo/values-common.yaml")

    def test_git_history_latest_commit_does_not_hide_earlier_file(self):
        # 실제 Git history로도 같은 상황을 만들어, PR 전체 3-dot diff와 latest-commit delta가 다름을 확인한다.
        with tempfile.TemporaryDirectory() as work:
            git(work, "init", "-q", "-b", "main")
            commit(work, "README.md")
            git(work, "switch", "-qc", "feature")
            commit(work, "platform/local/k3d.yaml")
            head = commit(work, TF)
            latest = git(work, "diff", "--name-only", "HEAD~1", "HEAD").split()
            full = git(work, "diff", "--name-only", "main...HEAD").split()
        self.assertEqual(impact.classify(set(latest))[0], "static-only")
        self.assert_runtime(api(full, head=head), "platform/local/k3d.yaml", head=head, checked_out=head)

    # Fail closed: diff/HEAD/API/pagination이 불확실하면 full runtime.
    def test_empty_diff(self):
        self.assert_uncertain(api([]), "changed_files is missing or empty")

    def test_incomplete_diff(self):
        self.assert_uncertain(api([TF], changed_files=2), "returned 1 entries but PR reports 2")
        self.assert_uncertain(api([TF, TF.replace("main", "x")], changed_files=1), "returned 2 entries but PR reports 1")

    def test_files_api_limit(self):
        self.assert_uncertain(api([TF], changed_files=3000), "reaches files API limit")

    def test_pagination_does_not_terminate(self):
        def page(n):
            return [{"filename": f"infra/terraform/environment/p{n}-{i}.tf"} for i in range(100)]
        self.assert_uncertain(api([], changed_files=2999, pages=page), "pagination did not terminate")

    def test_truncated_or_malformed_page(self):
        for label, pages in (("short first page", lambda n: [{"filename": TF}] if n == 1 else []),
                             ("non-list page", lambda n: {"message": "error"}),
                             ("missing filename", lambda n: [{"status": "modified"}]),
                             ("invalid previous_filename", lambda n: [{"filename": TF, "previous_filename": ""}])):
            with self.subTest(label):
                self.assert_uncertain(api([TF, TF + ".x"], pages=pages), "PR diff uncertain:")

    def test_renamed_entry_without_previous_filename(self):
        # Rename 원본이 platform/ 아래여도 previous_filename이 없으면 Terraform-only로 보일 수 있다.
        for entry in ({"filename": TF, "status": "renamed"},
                      {"filename": TF, "status": "renamed", "previous_filename": None},
                      {"filename": TF, "status": "renamed", "previous_filename": ["platform/local/k3d.yaml"]}):
            with self.subTest(entry=entry):
                self.assert_uncertain(api([entry]), "missing or invalid previous_filename")

    def test_duplicate_filename(self):
        # 같은 filename이 다시 오면 entries == changed_files여도 다른 changed path가 빠졌을 수 있다.
        files = [f"infra/terraform/environment/f{i}.tf" for i in range(100)]
        for label, entries in (("same page", [TF, TF]), ("across pages", [*files, files[0]])):
            with self.subTest(label):
                self.assert_uncertain(api(entries), "repeats a filename")

    def test_invalid_head(self):
        self.assert_uncertain(api([TF]), "checked-out HEAD does not match", head="not-a-sha", checked_out="not-a-sha")
        self.assert_uncertain(api([TF]), "checked-out HEAD does not match", checked_out="b" * 40)
        self.assert_uncertain(api([TF], head="b" * 40), "API PR head differs")

    def test_head_moves_during_listing(self):
        self.assert_uncertain(api([TF], heads=[(HEAD, 1), ("b" * 40, 1)]), "API PR head differs")
        self.assert_uncertain(api([TF], heads=[(HEAD, 1), (HEAD, 2)]), "changed_files changed during listing")

    def test_base_moves_during_listing(self):
        # Retarget 또는 base rewrite: head와 changed_files가 같아도 base가 바뀌면 page들이 같은 diff라고 볼 수 없다.
        for label, after in (("retarget", (HEAD, 1, "release", BASE)), ("base rewrite", (HEAD, 1, "main", "d" * 40))):
            with self.subTest(label):
                self.assert_uncertain(api([TF], heads=[(HEAD, 1), after]), "base ref/SHA changed during listing")

    def test_missing_or_invalid_base(self):
        for base in ({}, {"ref": "main"}, {"ref": "", "sha": BASE}, {"ref": "main", "sha": "not-a-sha"}):
            with self.subTest(base=base):
                get_json = api([TF])
                pr = lambda path: ({"head": {"sha": HEAD}, "base": base, "changed_files": 1}
                                   if path.endswith(f"/pulls/{PR}") else get_json(path))
                self.assert_uncertain(pr, "base ref/SHA is missing or invalid")

    def test_api_failure(self):
        def failing(error):
            def get_json(path):
                raise error
            return get_json
        http_error = urllib.error.HTTPError("u", 502, "bad gateway", {}, None)
        self.addCleanup(http_error.close)
        for error in (http_error, urllib.error.URLError("down"),
                      TimeoutError(), ValueError("invalid JSON"), KeyError("GH_TOKEN")):
            with self.subTest(error=type(error).__name__):
                self.assert_uncertain(failing(error), f"PR diff unavailable: {type(error).__name__}")

    def test_invalid_arguments(self):
        self.assertEqual(impact.decide(api([TF]), "bad repo", PR, HEAD, HEAD)[0], "uncertain")
        self.assertEqual(impact.decide(api([TF]), REPO, "0", HEAD, HEAD)[0], "uncertain")

    def test_cli_fails_closed_without_credentials(self):
        # Token/network 없이 실제 CLI를 실행해도 한 줄 uncertain 판정을 내고 Azure/GitHub credential을 요구하지 않는다.
        env = {"PATH": os.environ["PATH"], "GITHUB_API_URL": "http://127.0.0.1:9"}
        for args in ([], [REPO, PR, HEAD, HEAD]):
            with self.subTest(args=args):
                out = subprocess.run([sys.executable, str(ROOT / "scripts/ci-change-impact.py"), *args], env=env,
                                     check=True, capture_output=True, text=True).stdout
                self.assertEqual(out.count("\n"), 1)
                self.assertTrue(out.startswith("uncertain\t"), out)


WORKFLOW = ROOT / ".github/workflows/local-platform.yml"
DOCS = "docs/local-operations.md"
RUNTIME = "platform/local/k3d.yaml"


def check_runs(conclusion):
    return json.dumps({"check_runs": [{"name": "static + fresh local lifecycle", "status": "completed",
                                       "conclusion": conclusion}]})


def classify_block():
    """Workflow `Classify current PR update` step의 run block을 그대로 꺼낸다."""
    lines = WORKFLOW.read_text().splitlines()
    run = lines.index("        run: |", lines.index("      - name: Classify current PR update"))
    body = []
    for line in lines[run + 1:]:
        if line.strip() and not line.startswith(" " * 10):
            break
        body.append(line[10:])
    return "\n".join(body) + "\n"


class FakeGitHub(http.server.ThreadingHTTPServer):
    """api()의 get_json을 HTTP로 노출한다. get_json 예외는 HTTP 502다."""
    def __init__(self, get_json):
        self.get_json = get_json
        super().__init__(("127.0.0.1", 0), FakeGitHubHandler)


class FakeGitHubHandler(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        try:
            body, status = json.dumps(self.server.get_json(self.path)).encode(), 200
        except Exception:
            body, status = b'{"message": "error"}', 502
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args):
        pass


class WorkflowDecisionTest(unittest.TestCase):
    """Classifier 판정 → workflow runtime_changed 판정. Docs-only shortcut은 검증된 complete diff 뒤에만 열린다."""
    def setUp(self):
        self.work = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.work)
        self.repo, self.bin = self.work / "repo", self.work / "bin"
        self.repo.mkdir()
        self.bin.mkdir()
        git(self.repo, "init", "-q", "-b", "main")
        commit(self.repo, "README.md")
        git(self.repo, "switch", "-qc", "feature")
        self.before = commit(self.repo, TF, RUNTIME)
        self.after = commit(self.repo, DOCS)  # 최신 push delta는 docs-only
        (self.repo / "scripts").mkdir()
        shutil.copy(ROOT / "scripts/ci-change-impact.py", self.repo / "scripts/ci-change-impact.py")
        # 직전 head check-run 조회만 대체한다. Classifier는 curl이 아니라 urllib로 fake API를 호출한다.
        curl = self.bin / "curl"
        curl.write_text('#!/bin/sh\nprintf "%s" "$FAKE_CHECK_RUNS"\n')
        curl.chmod(0o755)

    def run_block(self, get_json, event="synchronize", after=None, previous=check_runs("success")):
        server = FakeGitHub(get_json)
        threading.Thread(target=server.serve_forever, kwargs={"poll_interval": 0.05}, daemon=True).start()
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        (self.work / "classify.sh").write_text(classify_block())
        output = self.work / "github-output"
        output.write_text("")
        env = git_env(self.work) | {
            "PATH": f"{self.bin}:{os.environ['PATH']}", "EVENT_ACTION": event, "BEFORE_SHA": self.before,
            "AFTER_SHA": after or self.after, "PR_NUMBER": PR, "REPOSITORY": REPO, "GH_TOKEN": "test-token",
            "GITHUB_OUTPUT": str(output), "GITHUB_API_URL": f"http://127.0.0.1:{server.server_port}",
            "FAKE_CHECK_RUNS": previous}
        # GitHub Actions의 bash run step 기본 호출과 같다.
        result = subprocess.run(["bash", "--noprofile", "--norc", "-eo", "pipefail", str(self.work / "classify.sh")],
                                cwd=self.repo, env=env, capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        return dict(line.split("=", 1) for line in output.read_text().splitlines())

    def stub_classifier(self, stdout, code=0):
        (self.repo / "scripts/ci-change-impact.py").write_text(
            f"import sys\nsys.stdout.write({stdout!r})\nsys.exit({code})\n")

    def assert_outcome(self, out, runtime_changed, classification, pr_diff):
        self.assertEqual(out["runtime_changed"], runtime_changed, out)
        self.assertEqual(out["classification"], classification, out)
        self.assertEqual(out["pr_diff"], pr_diff, out)

    def complete(self, files=(TF, RUNTIME, DOCS), **kwargs):
        return api(files, head=self.after, **kwargs)

    # 1-3. 검증된 complete diff
    def test_terraform_only_complete_diff_skips_runtime(self):
        self.assert_outcome(self.run_block(self.complete([TF]), event="opened"), "false", "static-only", "static-only")

    def test_runtime_path_complete_diff_requires_runtime(self):
        out = self.run_block(self.complete(), event="opened")
        self.assert_outcome(out, "true", "full-runtime", "runtime-impacting")

    def test_verified_runtime_diff_keeps_docs_only_shortcut(self):
        out = self.run_block(self.complete())
        self.assert_outcome(out, "false", "docs-only-synchronize", "runtime-impacting")

    def test_docs_only_shortcut_still_requires_previous_success(self):
        out = self.run_block(self.complete(), previous=check_runs("failure"))
        self.assert_outcome(out, "true", "full-runtime", "runtime-impacting")

    # 4-9. Docs-only delta + 직전 성공이 있어도 uncertain이면 shortcut 없이 full runtime
    def test_uncertain_diff_never_uses_docs_only_shortcut(self):
        files = (TF, RUNTIME, DOCS)
        terraform = [f"infra/terraform/environment/f{i}.tf" for i in range(100)]

        def api_error(path):
            raise RuntimeError("simulated PR files API failure")
        for label, get_json in (
                ("files API error", api_error),
                ("base retarget", self.complete(heads=[(self.after, 3), (self.after, 3, "release", BASE)])),
                ("base rewrite", self.complete(heads=[(self.after, 3), (self.after, 3, "main", "d" * 40)])),
                ("API PR head mismatch", api(files, head="b" * 40)),
                ("incomplete count", self.complete(changed_files=4)),
                ("renamed without previous_filename", self.complete([TF, {"filename": DOCS, "status": "renamed"}])),
                ("duplicate filename across pages", self.complete([*terraform, terraform[0]]))):
            with self.subTest(label):
                out = self.run_block(get_json)
                self.assert_outcome(out, "true", "full-runtime", "uncertain")

    def test_event_head_differs_from_checkout(self):
        out = self.run_block(self.complete(), after="b" * 40)
        self.assert_outcome(out, "true", "full-runtime", "uncertain")

    def test_malformed_or_failed_classifier_never_uses_docs_only_shortcut(self):
        for label, stdout, code in (("command failure after valid line", "static-only\tok\n", 1),
                                    ("crash without output", "", 3),
                                    ("missing tab", "static-only\n", 0),
                                    ("extra line", "static-only\tok\nruntime-impacting\tx\n", 0),
                                    ("unknown decision", "full-runtime\tlegacy vocabulary\n", 0),
                                    ("extra field", "runtime-impacting\tx\ty\n", 0)):
            with self.subTest(label):
                self.stub_classifier(stdout, code)
                out = self.run_block(self.complete())
                self.assert_outcome(out, "true", "full-runtime", "uncertain")

    def test_malformed_classifier_never_skips_runtime_on_open(self):
        # 정상 static-only 앞부분만 보고 runtime을 생략하지 않는다.
        self.stub_classifier("static-only\tok\nextra\n")
        out = self.run_block(self.complete([TF]), event="opened")
        self.assert_outcome(out, "true", "full-runtime", "uncertain")


if __name__ == "__main__":
    unittest.main(verbosity=1)
