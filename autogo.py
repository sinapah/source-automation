#!/usr/bin/env python3
import asyncio
import os
import re
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Set, Tuple

import aiohttp
import yaml


GITHUB_RE = re.compile(r"^https?://github\.com/(?P<owner>[^/]+)/(?P<repo>[^/#]+)(?:/.*)?$")


@dataclass
class RepoRef:
    host: str
    owner: str
    repo: str


def parse_repo(url: str) -> Optional[RepoRef]:
    m = GITHUB_RE.match(url)
    if m:
        return RepoRef(host="github", owner=m.group("owner"), repo=m.group("repo"))
    return None


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class GitHubClient:
    def __init__(self, token: Optional[str], concurrency: int = 8, timeout_s: int = 20):
        self._token = token
        self._sem = asyncio.Semaphore(concurrency)
        self._timeout = aiohttp.ClientTimeout(total=timeout_s)
        self._session: Optional[aiohttp.ClientSession] = None

    async def __aenter__(self):
        headers = {"Accept": "application/vnd.github+json"}
        if self._token:
            headers["Authorization"] = f"Bearer {self._token}"
        self._session = aiohttp.ClientSession(headers=headers, timeout=self._timeout)
        return self

    async def __aexit__(self, exc_type, exc, tb):
        if self._session:
            await self._session.close()

    async def _get_json(self, url: str) -> Tuple[Dict[str, Any], Dict[str, Any]]:
        assert self._session is not None
        async with self._sem:
            async with self._session.get(url) as resp:
                data = await resp.json(content_type=None)
                rate = {
                    "x-ratelimit-limit": resp.headers.get("x-ratelimit-limit"),
                    "x-ratelimit-remaining": resp.headers.get("x-ratelimit-remaining"),
                    "x-ratelimit-reset": resp.headers.get("x-ratelimit-reset"),
                    "status": resp.status,
                }
                if resp.status >= 400:
                    raise RuntimeError(f"HTTP {resp.status} for {url}: {data}")
                return data, rate

    async def get_default_branch(self, ref: RepoRef) -> Tuple[str, Dict[str, Any]]:
        data, rate = await self._get_json(f"https://api.github.com/repos/{ref.owner}/{ref.repo}")
        return data.get("default_branch", "main"), rate

    async def get_tree_paths(self, ref: RepoRef, branch: str) -> Tuple[Set[str], Dict[str, Any]]:
        data, rate = await self._get_json(
            f"https://api.github.com/repos/{ref.owner}/{ref.repo}/git/trees/{branch}?recursive=1"
        )
        paths = set()
        for item in data.get("tree", []):
            p = item.get("path")
            if p:
                paths.add(p)
        return paths, rate

    async def get_rate_limit_remaining(self) -> Optional[int]:
        try:
            data, _ = await self._get_json("https://api.github.com/rate_limit")
            core = data.get("resources", {}).get("core", {})
            remaining = core.get("remaining")
            if isinstance(remaining, int):
                return remaining
            return None
        except Exception:
            return None


def detect_build_systems(paths: Set[str]) -> Tuple[Dict[str, bool], Dict[str, Any]]:
    # Normalize to lowercase for comparisons where applicable
    lower_paths = {p.lower() for p in paths}

    def exists_any(candidates: List[str]) -> bool:
        return any(p in lower_paths for p in (c.lower() for c in candidates))

    # Build system files (root or anywhere in repo)
    makefile = exists_any(["makefile", "gnu\nmakefile", "gnu-makefile"]) or any(
        p.endswith("/Makefile") or p.endswith("/makefile") for p in paths
    )
    bazel = exists_any(["workspace", "workspace.bazel"]) or any(
        p.endswith("/WORKSPACE") or p.endswith("/WORKSPACE.bazel") or p.endswith(".bzl") or p.endswith("BUILD") or p.endswith("BUILD.bazel")
        for p in paths
    )
    justfile = exists_any(["justfile"]) or any(p.endswith("/Justfile") for p in paths)
    goreleaser = exists_any([".goreleaser.yml", ".goreleaser.yaml", "goreleaser.yml", "goreleaser.yaml"]) or any(
        p.lower().endswith("/.goreleaser.yml") or p.lower().endswith("/.goreleaser.yaml") for p in paths
    )
    dockerfile = exists_any(["dockerfile"]) or any(p.endswith("/Dockerfile") for p in paths)
    mage = any(p.lower().endswith("/magefile.go") or p.lower() == "magefile.go" for p in paths)
    gotask = any(p.lower().endswith("/taskfile.yml") or p.lower() == "taskfile.yml" for p in paths)
    gomod = any(p == "go.mod" or p.endswith("/go.mod") for p in paths)
    gowork = any(p == "go.work" or p.endswith("/go.work") for p in paths)
    buf = any(p == "buf.yaml" or p == "buf.yml" or p.endswith("/buf.yaml") or p.endswith("/buf.yml") for p in paths)
    drone = any(p == ".drone.yml" or p.endswith("/.drone.yml") for p in paths)
    github_actions = any(p.startswith(".github/workflows/") for p in paths)
    circleci = any(p == ".circleci/config.yml" or p.endswith("/.circleci/config.yml") for p in paths)
    gitlab_ci = any(p == ".gitlab-ci.yml" or p.endswith("/.gitlab-ci.yml") for p in paths)

    files_present: List[str] = []
    for name, present in [
        ("Makefile", makefile),
        ("Bazel", bazel),
        ("Justfile", justfile),
        ("Goreleaser", goreleaser),
        ("Dockerfile", dockerfile),
        ("Magefile", mage),
        ("Taskfile", gotask),
        ("go.mod", gomod),
        ("go.work", gowork),
        ("buf", buf),
        ("Drone", drone),
        ("GitHub Actions", github_actions),
        ("CircleCI", circleci),
        ("GitLab CI", gitlab_ci),
    ]:
        if present:
            files_present.append(name)

    ci_providers = [
        name for name, present in [
            ("github_actions", github_actions),
            ("circleci", circleci),
            ("gitlab_ci", gitlab_ci),
            ("drone", drone),
        ] if present
    ]

    booleans = {
        "makefile": bool(makefile),
        "bazel": bool(bazel),
        "justfile": bool(justfile),
        "goreleaser": bool(goreleaser),
        "dockerfile": bool(dockerfile),
        "mage": bool(mage),
        "gotask": bool(gotask),
        "gomod": bool(gomod),
        "gowork": bool(gowork),
        "buf": bool(buf),
        "drone": bool(drone),
        "github_actions": bool(github_actions),
        "circleci": bool(circleci),
        "gitlab_ci": bool(gitlab_ci),
    }

    meta = {
        "files_present": files_present,
        "ci_providers": ci_providers,
        "detected_file_count": len(files_present),
    }

    return booleans, meta


async def enrich_entry(entry: Dict[str, Any], gh: GitHubClient) -> Dict[str, Any]:
    url = entry.get("url")
    if not isinstance(url, str):
        return entry

    reporef = parse_repo(url)
    if not reporef:
        # Non-GitHub URLs unsupported for now; annotate minimal info
        entry.setdefault("build_metadata", {})
        entry["build_metadata"].update({
            "repo_host": "unknown",
            "note": "Non-GitHub repositories not yet supported",
            "detection_timestamp": now_iso(),
        })
        return entry

    try:
        default_branch, rate_repo = await gh.get_default_branch(reporef)
        paths, rate_tree = await gh.get_tree_paths(reporef, default_branch)
        booleans, meta = detect_build_systems(paths)

        # Update entry preserving existing keys
        for k, v in booleans.items():
            entry[k] = v

        entry.setdefault("build_metadata", {})
        entry["build_metadata"].update({
            "repo_host": reporef.host,
            "owner": reporef.owner,
            "repo": reporef.repo,
            "repo_default_branch": default_branch,
            "detection_timestamp": now_iso(),
            "api_rate_limit_remaining": rate_tree.get("x-ratelimit-remaining"),
            **meta,
        })
        return entry
    except Exception as e:
        entry.setdefault("build_metadata", {})
        entry["build_metadata"].update({
            "repo_host": reporef.host,
            "owner": reporef.owner,
            "repo": reporef.repo,
            "error": str(e),
            "detection_timestamp": now_iso(),
        })
        return entry


async def process_file(path: str, token: Optional[str], concurrency: int) -> None:
    # Read YAML
    with open(path, "r", encoding="utf-8") as f:
        try:
            data = yaml.safe_load(f) or []
        except yaml.YAMLError as e:
            print(f"Failed to parse YAML: {e}", file=sys.stderr)
            sys.exit(1)

    if not isinstance(data, list):
        print("Expected a YAML list of package objects", file=sys.stderr)
        sys.exit(1)

    async with GitHubClient(token=token, concurrency=concurrency) as gh:
        # If no token provided, do a quick preflight check to warn about potential rate limiting.
        if not token:
            remaining = await gh.get_rate_limit_remaining()
            # Rough estimate: 2 requests per repo (repo info + tree)
            estimated_needed = max(1, len(data) * 2)
            if remaining is not None and remaining < estimated_needed:
                print(
                    (
                        f"Warning: GitHub unauthenticated rate limit remaining={remaining} seems lower than "
                        f"the estimated calls needed (~{estimated_needed}). Consider setting GITHUB_TOKEN to avoid rate limiting."
                    ),
                    file=sys.stderr,
                )
        tasks = [enrich_entry(entry, gh) for entry in data]
        updated: List[Dict[str, Any]] = await asyncio.gather(*tasks)

    # Write YAML with 2-space indent and preserved order
    with open(path, "w", encoding="utf-8") as f:
        yaml.safe_dump(
            updated,
            f,
            default_flow_style=False,
            sort_keys=False,
            indent=2,
            allow_unicode=True,
        )


def main(argv: List[str]) -> int:
    import argparse

    parser = argparse.ArgumentParser(description="Annotate go-packages.yaml with build system metadata.")
    parser.add_argument("--file", dest="file", default=os.environ.get("GO_PACKAGES_YAML", "go-packages.yaml"))
    parser.add_argument("--concurrency", type=int, default=int(os.environ.get("CONCURRENCY", "8")))
    parser.add_argument("--token", dest="token", default=os.environ.get("GITHUB_TOKEN"))
    args = parser.parse_args(argv)

    # Normalize to absolute path for reliability
    yaml_path = os.path.abspath(args.file)
    if not os.path.exists(yaml_path):
        print(f"YAML file not found: {yaml_path}", file=sys.stderr)
        return 2

    asyncio.run(process_file(yaml_path, token=args.token, concurrency=args.concurrency))
    print(f"Updated {yaml_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
