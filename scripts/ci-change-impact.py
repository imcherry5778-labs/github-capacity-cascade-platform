#!/usr/bin/env python3
"""CI change impact: PR base → checked-out exact HEAD 전체 changed-file set으로 Local runtime 필요 여부를 정한다.

Decision (machine-readable):
  static-only        complete PR diff의 모든 path가 Azure Terraform source/static verifier allowlist에 속함
  runtime-impacting  complete PR diff에 allowlist 밖 path가 있음
  p9-only-synchronize / docs-only-synchronize: immutable delta + previous full runtime proof
  uncertain          API 오류, HEAD/base 불일치, 불완전/잘린/malformed file list 등 complete diff를 증명하지 못함
Workflow는 uncertain(및 classifier 실패/잘못된 출력)에서 어떤 shortcut도 없이 full runtime을 실행한다.

usage: ci-change-impact.py REPOSITORY PR_NUMBER PR_HEAD_SHA CHECKED_OUT_SHA [PREVIOUS_SHA EVENT_ACTION]
stdout: "<decision>\t<reason>" 한 줄. Changed path는 stderr에 기록한다.
"""
import json
import os
import re
import sys
import subprocess
import urllib.request

sys.dont_write_bytecode = True
# Local Kubernetes runtime 구현에 영향을 주지 않는 Azure Terraform source/static verification path만 둔다.
STATIC_ONLY_PREFIXES = ("infra/terraform/",)
STATIC_ONLY_FILES = ("scripts/terraform-verify.sh",)
PAGE_SIZE = 100
# GitHub PR files API는 최대 3000 files만 반환하므로 그 이상은 complete diff로 볼 수 없다.
FILES_API_LIMIT = 3000
SHA = re.compile(r'^[0-9a-f]{40}$')
REPOSITORY = re.compile(r'^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$')


class Uncertain(Exception):
    pass


def static_only_path(path):
    parts = path.split("/")
    if not path or path.startswith("/") or any(part in ("", ".", "..") for part in parts):
        return False
    return path in STATIC_ONLY_FILES or path.startswith(STATIC_ONLY_PREFIXES)


def classify(paths):
    if not paths:
        return "uncertain", "empty changed-file set"
    runtime = sorted(path for path in paths if not static_only_path(path))
    if runtime:
        more = f" (+{len(runtime) - 1} more)" if len(runtime) > 1 else ""
        return "runtime-impacting", f"runtime-impacting or unrecognized path {runtime[0]!r}{more}"
    return "static-only", f"all {len(paths)} changed paths are Azure Terraform static-only"


def pr_files(get_json, repository, number, head, metadata=None):
    """Exact HEAD의 complete PR changed-file set. Rename은 이전/새 path를 모두 포함한다."""
    def snapshot():
        pr = get_json(f"/repos/{repository}/pulls/{number}")
        if not isinstance(pr, dict) or not isinstance(pr.get("head"), dict) or not isinstance(pr.get("base"), dict):
            raise Uncertain("malformed pull request response")
        if pr["head"].get("sha") != head:
            raise Uncertain("API PR head differs from checked-out HEAD")
        base_ref, base_sha = pr["base"].get("ref"), pr["base"].get("sha")
        if not isinstance(base_ref, str) or not base_ref or not isinstance(base_sha, str) or not SHA.match(base_sha):
            raise Uncertain("PR base ref/SHA is missing or invalid")
        count = pr.get("changed_files")
        if type(count) is not int or count < 1:
            raise Uncertain("PR changed_files is missing or empty")
        if count >= FILES_API_LIMIT:
            raise Uncertain(f"PR changed_files {count} reaches files API limit {FILES_API_LIMIT}")
        return base_ref, base_sha, count

    before = snapshot()
    count = before[2]
    paths, filenames, entries = set(), set(), 0
    for page in range(1, FILES_API_LIMIT // PAGE_SIZE + 1):
        batch = get_json(f"/repos/{repository}/pulls/{number}/files?per_page={PAGE_SIZE}&page={page}")
        if not isinstance(batch, list):
            raise Uncertain(f"malformed files page {page}")
        for entry in batch:
            name = entry.get("filename") if isinstance(entry, dict) else None
            if not isinstance(name, str) or not name:
                raise Uncertain(f"files page {page} entry without filename")
            # 같은 filename이 다시 오면 count는 맞아도 다른 changed path가 빠졌을 수 있다.
            if name in filenames:
                raise Uncertain(f"files page {page} repeats a filename")
            filenames.add(name)
            paths.add(name)
            previous = entry.get("previous_filename")
            if previous is not None or entry.get("status") == "renamed":
                if not isinstance(previous, str) or not previous:
                    raise Uncertain(f"files page {page} entry with missing or invalid previous_filename")
                paths.add(previous)
        entries += len(batch)
        if len(batch) < PAGE_SIZE:
            break
    else:
        raise Uncertain("files pagination did not terminate within API limit")
    if entries != count:
        raise Uncertain(f"files API returned {entries} entries but PR reports {count}")
    # Listing 중 PR head/base(retarget, base rewrite)가 바뀌면 page들이 서로 다른 diff에 속할 수 있다.
    # Head는 snapshot()이 다시 검사하고, base ref/SHA와 changed_files는 listing 전과 같아야 한다.
    after = snapshot()
    if after[:2] != before[:2]:
        raise Uncertain("PR base ref/SHA changed during listing")
    if after[2] != count:
        raise Uncertain("PR changed_files changed during listing")
    if metadata is not None:
        metadata.update(base_ref=before[0], base_sha=before[1])
    return paths


def decide(get_json, repository, number, head, checked_out, log=lambda path: None):
    if not REPOSITORY.match(repository) or not re.fullmatch(r'[1-9][0-9]*', number):
        return "uncertain", "invalid repository or PR number"
    if not SHA.match(head) or head != checked_out:
        return "uncertain", "checked-out HEAD does not match PR head"
    try:
        paths = pr_files(get_json, repository, number, head)
    except Uncertain as error:
        return "uncertain", f"PR diff uncertain: {error}"
    except Exception as error:  # API/network/JSON 오류. Raw response body는 출력하지 않는다.
        return "uncertain", f"PR diff unavailable: {type(error).__name__}"
    for path in sorted(paths):
        log(path)
    return classify(paths)


# Exclusive P9 surfaces: shared fixture resources, generic scripts, workflows and unrelated docs are excluded.
P9_FILES = {'scripts/azure-mitigation.py', 'tests/e2e/test-azure-mitigation.py',
            'experiments/fixtures/shared-gate/mitigation-candidate.json', 'docs/p9-mitigation-recovery.md'}
RUNTIME_STEPS = {'Source / static / render validation', 'Fresh lifecycle (make local) + owned cleanup',
                 'Verify same-cluster healthy gate and removal evidence',
                 'Verify frozen saturation and bounded retry evidence', 'Fresh coordinated backup and restore',
                 'Forgejo patch upgrade and fresh state-aware rollback', 'Guard cluster owned by another invocation',
                 'Ownership guard (existing / concurrent create-delete / replaced / ambiguous / uninspectable cluster)',
                 'Cleanup error path (k3d cluster delete failure)', 'Cleanup'}


def delta_path(path):
    parts = path.split('/')
    return (all(p not in {'', '.', '..'} for p in parts) and
            (path in P9_FILES or
             re.fullmatch(r'docs/evidence/p9-[a-z0-9-]+/[^\s]+', path) is not None))


def git(*args):
    return subprocess.check_output(['git', *args], stderr=subprocess.DEVNULL).decode().strip()


def incremental(get_json, repository, number, head, previous, paths, meta):
    """One-hop reuse only. A skipped predecessor can never seed another skipped runtime."""
    if not SHA.fullmatch(previous) or previous == head:
        raise Uncertain('missing/invalid previous SHA')
    git('merge-base', '--is-ancestor', previous, head)
    # Immutable local full PR diff must agree with the complete, twice-read API file set.
    def names(spec):
        raw = git('diff', '--name-status', '-z', '--find-renames', spec)
        rows = raw.split('\0')[:-1] if raw else []
        if not rows:
            return set()
        result = set()
        for i in range(0, len(rows), 2):
            if i + 1 >= len(rows) or rows[i] not in {'A', 'M', 'D'} or rows[i + 1] in result:
                raise Uncertain('rename/ambiguous changed path')
            result.add(rows[i + 1])
        return result
    if names(f"{meta['base_sha']}...{head}") != paths:
        raise Uncertain('local/API full PR changed-file set differs')
    delta = names(f'{previous}..{head}')
    if not delta or delta != {'docs/local-operations.md'} and not all(delta_path(p) for p in delta):
        raise Uncertain('delta includes shared/unknown path or is empty')
    endpoint = f'/repos/{repository}'
    runs = get_json(endpoint + f'/actions/workflows/local-platform.yml/runs?head_sha={previous}&per_page=100')
    candidates = runs['workflow_runs']
    if not 0 < runs['total_count'] == len(candidates) < 100:
        raise Uncertain('previous workflow run set incomplete')
    run = max(candidates, key=lambda r: r['id'])
    if not (run['head_sha'] == previous and run['path'] == '.github/workflows/local-platform.yml' and
            run['event'] == 'pull_request' and run['status'] == 'completed' and run['conclusion'] == 'success' and
            len(run['pull_requests']) == 1):
        raise Uncertain('previous exact-head workflow not successful/unique')
    pr = run['pull_requests'][0]
    if not (str(pr['number']) == number and pr['head']['sha'] == previous and
            pr['base']['sha'] == meta['base_sha'] and pr['base']['ref'] == meta['base_ref']):
        raise Uncertain('previous PR head/base binding differs')
    jobs = get_json(endpoint + f"/actions/runs/{run['id']}/attempts/{run['run_attempt']}/jobs?per_page=100")
    matches = [j for j in jobs['jobs'] if j['name'] == 'static + fresh local lifecycle']
    if jobs['total_count'] != len(jobs['jobs']) or len(matches) != 1:
        raise Uncertain('previous job set incomplete/ambiguous')
    job = matches[0]
    steps = job['steps']
    if not (job['head_sha'] == previous and job['status'] == 'completed' and job['conclusion'] == 'success' and
            all(len([s for s in steps if s['name'] == name and s['status'] == 'completed' and
                     s['conclusion'] == 'success' and s.get('started_at') and s.get('completed_at') and
                     s['completed_at'] >= s['started_at']]) == 1 for name in RUNTIME_STEPS)):
        raise Uncertain('previous full runtime execution not proven (skipped stages cannot seed reuse)')
    # Reject PR movement while checking history/jobs too.
    final = get_json(endpoint + f'/pulls/{number}')
    if final['head']['sha'] != head or final['base']['sha'] != meta['base_sha'] or final['base']['ref'] != meta['base_ref']:
        raise Uncertain('PR head/base moved during runtime proof')
    classification = 'docs-only-synchronize' if delta == {'docs/local-operations.md'} else 'p9-only-synchronize'
    return classification, f"{len(delta)} exclusive delta paths; previous full runtime {previous} run {run['id']} attempt {run['run_attempt']}; runtime SKIPPED/not verified for current HEAD"


def decide_update(get_json, repository, number, head, checked_out, previous, action):
    decision, reason = decide(get_json, repository, number, head, checked_out)
    if decision != 'runtime-impacting' or action != 'synchronize':
        return decision, reason
    try:
        meta = {}
        paths = pr_files(get_json, repository, number, head, meta)
        return incremental(get_json, repository, number, head, previous, paths, meta)
    except Uncertain as error:
        return 'runtime-impacting', f'{reason}; incremental unavailable: {error}'
    except Exception as error:
        return 'runtime-impacting', f'{reason}; incremental unavailable: {type(error).__name__}'


def github_get_json(path):
    api = os.environ.get("GITHUB_API_URL", "https://api.github.com")
    headers = {
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    # Public Actions metadata supports anonymous reads; do not expand GITHUB_TOKEN permissions.
    # Private repositories/rate limits/API errors safely fall back to full runtime.
    if '/actions/' not in path:
        headers['Authorization'] = 'Bearer ' + os.environ['GH_TOKEN']
    request = urllib.request.Request(api + path, headers=headers)
    with urllib.request.urlopen(request, timeout=30) as response:
        return json.load(response)


def main(argv):
    if len(argv) not in {4, 6}:
        decision, reason = "uncertain", "classifier usage error"
    elif len(argv) == 6:
        decision, reason = decide_update(github_get_json, *argv)
    else:
        decision, reason = decide(github_get_json, *argv,
                                  log=lambda path: print(f"PR path: {path}", file=sys.stderr))
    print(f"{decision}\t{' '.join(reason.split())}")


if __name__ == "__main__":
    main(sys.argv[1:])
