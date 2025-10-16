import os
import subprocess
from pathlib import Path
from urllib.parse import urlparse
import requests
from git import Repo

FILENAME = "filename.yaml"

REPOS = [
    {"url": "https://github.com/andybalholm/brotli", "version": "v1.1.0"},
    {"url": "https://github.com/antihax/optional", "version": "v1.0.0"},
    {"url": "https://github.com/Microsoft/didx509go", "version": "v0.0.3"},
    {"url": "https://github.com/agext/levenshtein", "version": "v1.2.3"},
    {"url": "https://github.com/akavel/rsrc", "version": "v0.10.2"},
]

COMMAND = ["src-cmd", "init"]

def normalize_repo_url(repo_url: str) -> str:
    """Normalize repo name or URL to 'owner/repo' format."""
    if repo_url.startswith("http"):
        path = urlparse(repo_url).path.strip("/")
        return path[:-4] if path.endswith(".git") else path
    return repo_url

def get_repo_name(repo_url: str) -> str:
    """Extract repository name from URL or owner/repo string."""
    return normalize_repo_url(repo_url).split("/")[-1]

def fetch_repo_description(repo_full_name: str) -> str:
    """Fetch the GitHub repository description via API."""
    api_url = f"https://api.github.com/repos/{repo_full_name}"
    headers = {"Accept": "application/vnd.github.v3+json"}
    try:
        response = requests.get(api_url, headers=headers, timeout=10)
        if response.status_code == 200:
            return response.json().get("description", "(no description)")
        return f"(failed to fetch: {response.status_code})"
    except requests.RequestException as e:
        return f"(failed to fetch: {e})"


def clone_repo(repo_url: str, tag: str | None = None, dest_dir="repos") -> Path:
    Path(dest_dir).mkdir(parents=True, exist_ok=True)
    repo_name = normalize_repo_url(repo_url).split("/")[-1]
    repo_path = Path(dest_dir) / repo_name

    if repo_path.exists():
        print(f"Repo already cloned: {repo_name}")
        repo = Repo(repo_path)
    else:
        print(f"Cloning {repo_url} ...")
        repo = Repo.clone_from(f"https://github.com/{normalize_repo_url(repo_url)}", repo_path)

    if tag:
        try:
            print(f"Checking out tag: {tag}")
            repo.git.fetch("--tags")
            repo.git.checkout(tag)
        except Exception as e:
            print(f"Failed to checkout tag {tag}: {e}")

    return repo_path


def run_command_in_repo(repo_path: Path, base_command: list[str]):
    """Run a shell command inside the given repo."""
    skip_path = repo_path / FILENAME
    if skip_path.exists():
        return
    command = base_command.copy()
    if (repo_path / "go.mod").exists():
        command.append("--profile=go")

    try:
        subprocess.run(
            command, cwd=repo_path, capture_output=True, text=True, check=True, shell=True, executable="/bin/bash"
        )
    except subprocess.CalledProcessError as e:
        print(f"Command failed:\n{e.stderr.strip()}")

def update_yaml_file(repo_path: Path, name: str, version: str | None):
    """Replace {{ name }} and {{ version }} in a generated file."""
    file_path = repo_path / FILENAME
    if not file_path.exists():
        return

    content = file_path.read_text()
    content = content.replace("{{ name }}", name)
    content = content.replace("{{ version }}", version or "latest")
    file_path.write_text(content)

    print(f"Updated {file_path.name} with name={name}, version={version or 'latest'}")

def pack(repo_path: Path, base_command: str):
    """Attemps to see if the file succeeds."""
    command = base_command.copy()
    command[1] = "pack"
    try:
        subprocess.run(
            command, cwd=repo_path, capture_output=True, text=True, check=True, shell=True, executable="/bin/bash"
        )
    except subprocess.CalledProcessError as e:
        print(f"Command failed:\n{e.stderr.strip()}")
    return

def main():
    for repo_info in REPOS:
        repo_url = repo_info["url"]
        tag = repo_info.get("version")

        repo_full_name = normalize_repo_url(repo_url)
        repo_name = get_repo_name(repo_url)
        print(f"\n==={repo_full_name} ===")

        description = fetch_repo_description(repo_full_name)
        print(f"Description: {description}")

        repo_path = clone_repo(repo_url, tag=tag)
        run_command_in_repo(repo_path, COMMAND)
        update_yaml_file(repo_path, name=repo_name, version=tag)

if __name__ == "__main__":
    main()
