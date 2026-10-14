#!/usr/bin/env python3
"""CI change impact: PR base → checked-out exact HEAD 전체 changed-file set으로 Local runtime 필요 여부를 정한다.

모든 path가 Azure Terraform source/static verifier allowlist에 속할 때만 static-only다.
API 오류, HEAD 불일치, 불완전/잘린 file list 등 불확실한 결과는 항상 full-runtime으로 fail closed한다.

usage: ci-change-impact.py REPOSITORY PR_NUMBER PR_HEAD_SHA CHECKED_OUT_SHA
stdout: "<static-only|full-runtime>\t<reason>" 한 줄. Changed path는 stderr에 기록한다.
"""
import json
import os
import re
import sys
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
        return "full-runtime", "empty changed-file set"
    runtime = sorted(path for path in paths if not static_only_path(path))
    if runtime:
        more = f" (+{len(runtime) - 1} more)" if len(runtime) > 1 else ""
        return "full-runtime", f"runtime-impacting or unrecognized path {runtime[0]!r}{more}"
    return "static-only", f"all {len(paths)} changed paths are Azure Terraform static-only"


def pr_files(get_json, repository, number, head):
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
    paths, entries = set(), 0
    for page in range(1, FILES_API_LIMIT // PAGE_SIZE + 1):
        batch = get_json(f"/repos/{repository}/pulls/{number}/files?per_page={PAGE_SIZE}&page={page}")
        if not isinstance(batch, list):
            raise Uncertain(f"malformed files page {page}")
        for entry in batch:
            name = entry.get("filename") if isinstance(entry, dict) else None
            if not isinstance(name, str) or not name:
                raise Uncertain(f"files page {page} entry without filename")
            paths.add(name)
            previous = entry.get("previous_filename")
            if previous is not None:
                if not isinstance(previous, str) or not previous:
                    raise Uncertain(f"files page {page} entry with invalid previous_filename")
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
    return paths


def decide(get_json, repository, number, head, checked_out, log=lambda path: None):
    if not REPOSITORY.match(repository) or not re.fullmatch(r'[1-9][0-9]*', number):
        return "full-runtime", "invalid repository or PR number"
    if not SHA.match(head) or head != checked_out:
        return "full-runtime", "checked-out HEAD does not match PR head"
    try:
        paths = pr_files(get_json, repository, number, head)
    except Uncertain as error:
        return "full-runtime", f"PR diff uncertain: {error}"
    except Exception as error:  # API/network/JSON 오류. Raw response body는 출력하지 않는다.
        return "full-runtime", f"PR diff unavailable: {type(error).__name__}"
    for path in sorted(paths):
        log(path)
    return classify(paths)


def github_get_json(path):
    api = os.environ.get("GITHUB_API_URL", "https://api.github.com")
    request = urllib.request.Request(api + path, headers={
        "Authorization": "Bearer " + os.environ["GH_TOKEN"],
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    })
    with urllib.request.urlopen(request, timeout=30) as response:
        return json.load(response)


def main(argv):
    if len(argv) != 4:
        decision, reason = "full-runtime", "classifier usage error"
    else:
        decision, reason = decide(github_get_json, *argv,
                                  log=lambda path: print(f"PR path: {path}", file=sys.stderr))
    print(f"{decision}\t{' '.join(reason.split())}")


if __name__ == "__main__":
    main(sys.argv[1:])
