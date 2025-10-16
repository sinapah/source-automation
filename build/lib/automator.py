import os
import subprocess
from pathlib import Path
from urllib.parse import urlparse
import requests
from git import Repo

# --- Configuration ---
# Replace this list with your own repo URLs or owner/repo names
REPOS = [
    "https://github.com/psf/requests",
    "openai/openai-python",
]

# Placeholder command to execute inside each repo (e.g. tests, builds)
COMMAND = ["echo", "Hello from inside the repo!"]

# Optional: GitHub API token (recommended to avoid rate limits)
GITHUB_TOKEN = os.getenv("GITHUB_TOKEN")


def normalize_repo_url(repo):
    """Normalize repo name or URL to 'owner/repo' format."""
    if repo.startswith("http"):
        path = urlparse(repo).path.strip("/")
        return path[:-4] if path.endswith(".git") else path
    return repo


def fetch_repo_description(repo_full_name):
    """Fetch the GitHub repository description via API."""
    api_url = f"https://api.github.com/repos/{repo_full_name}"
    headers = {"Accept": "application/vnd.github.v3+json"}
    if GITHUB_TOKEN:
        headers["Authorization"] = f"token {GITHUB_TOKEN}"
    response = requests.get(api_url, headers=headers, timeout=10)
    if response.status_code == 200:
        data = response.json()
        return data.get("description", "(no description)")
    else:
        return f"(failed to fetch: {response.status_code})"


def clone_repo(repo_url, dest_dir="repos"):
    """Clone the repo if not already cloned."""
    Path(dest_dir).mkdir(parents=True, exist_ok=True)
    repo_name = normalize_repo_url(repo_url).split("/")[-1]
    repo_path = Path(dest_dir) / repo_name

    if repo_path.exists():
        print(f"✅ Repo already cloned: {repo_name}")
    else:
        print(f"📥 Cloning {repo_url} ...")
        Repo.clone_from(f"https://github.com/{normalize_repo_url(repo_url)}", repo_path)
    return repo_path


def run_command_in_repo(repo_path):
    """Run a shell command inside the given repo."""
    print(f"⚙️  Running command in {repo_path.name} ...")
    try:
        result = subprocess.run(
            COMMAND, cwd=repo_path, capture_output=True, text=True, check=True
        )
        print(f"   ✅ Output:\n{result.stdout.strip()}")
    except subprocess.CalledProcessError as e:
        print(f"   ❌ Command failed:\n{e.stderr.strip()}")


def main():
    for repo in REPOS:
        repo_full_name = normalize_repo_url(repo)
        print(f"\n=== 🧠 {repo_full_name} ===")

        description = fetch_repo_description(repo_full_name)
        print(f"📘 Description: {description}")

        path = clone_repo(repo)
        run_command_in_repo(path)


if __name__ == "__main__":
    main()
