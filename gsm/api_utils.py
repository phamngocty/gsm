import requests
from typing import Optional


def check_github_token(token: str) -> Optional[dict]:
    try:
        resp = requests.get(
            "https://api.github.com/user",
            headers={"Authorization": f"Bearer {token}", "Accept": "application/vnd.github.v3+json"},
            timeout=10,
        )
        if resp.status_code == 200:
            data = resp.json()
            return {"username": data.get("login"), "name": data.get("name")}
        return None
    except requests.RequestException:
        return None


def check_gitea_token(token: str, server_url: str) -> Optional[dict]:
    server_url = server_url.rstrip("/")
    try:
        resp = requests.get(
            f"{server_url}/api/v1/user",
            headers={"Authorization": f"token {token}"},
            timeout=10,
        )
        if resp.status_code == 200:
            data = resp.json()
            return {"username": data.get("login"), "name": data.get("full_name")}
        return None
    except requests.RequestException:
        return None


def check_gitea_password(server_url: str, username: str, password: str) -> Optional[dict]:
    server_url = server_url.rstrip("/")
    try:
        resp = requests.get(
            f"{server_url}/api/v1/user",
            auth=(username, password),
            timeout=10,
        )
        if resp.status_code == 200:
            data = resp.json()
            return {"username": data.get("login"), "name": data.get("full_name")}
        return None
    except requests.RequestException:
        return None


def create_github_repo(token: str, name: str, description: str = "", private: bool = False, auto_init: bool = True) -> Optional[str]:
    try:
        resp = requests.post(
            "https://api.github.com/user/repos",
            headers={"Authorization": f"Bearer {token}", "Accept": "application/vnd.github.v3+json"},
            json={"name": name, "description": description, "private": private, "auto_init": auto_init},
            timeout=15,
        )
        if resp.status_code in (200, 201):
            return resp.json().get("clone_url")
        return None
    except requests.RequestException:
        return None


def create_gitea_repo(token: str, server_url: str, name: str, description: str = "", private: bool = False, auto_init: bool = True) -> Optional[str]:
    server_url = server_url.rstrip("/")
    try:
        resp = requests.post(
            f"{server_url}/api/v1/user/repos",
            headers={"Authorization": f"token {token}"},
            json={"name": name, "description": description, "private": private, "auto_init": auto_init},
            timeout=15,
        )
        if resp.status_code in (200, 201):
            return resp.json().get("clone_url")
        return None
    except requests.RequestException:
        return None


def list_gitea_repos(token: str, server_url: str) -> list[dict]:
    server_url = server_url.rstrip("/")
    try:
        resp = requests.get(
            f"{server_url}/api/v1/user/repos",
            headers={"Authorization": f"token {token}"},
            params={"limit": 100},
            timeout=15,
        )
        if resp.status_code == 200:
            repos = resp.json()
            return [{"id": r.get("id"), "name": r.get("name"), "full_name": r.get("full_name"),
                     "description": r.get("description", ""), "clone_url": r.get("clone_url"),
                     "ssh_url": r.get("ssh_url"), "private": r.get("private", False),
                     "default_branch": r.get("default_branch", "main"), "updated_at": r.get("updated_at")} for r in repos]
        return []
    except requests.RequestException:
        return []


def list_gitea_repos_basic_auth(server_url: str, username: str, password: str) -> list[dict]:
    server_url = server_url.rstrip("/")
    try:
        resp = requests.get(
            f"{server_url}/api/v1/user/repos",
            auth=(username, password),
            params={"limit": 100},
            timeout=15,
        )
        if resp.status_code == 200:
            repos = resp.json()
            return [{"id": r.get("id"), "name": r.get("name"), "full_name": r.get("full_name"),
                     "description": r.get("description", ""), "clone_url": r.get("clone_url"),
                     "ssh_url": r.get("ssh_url"), "private": r.get("private", False),
                     "default_branch": r.get("default_branch", "main"), "updated_at": r.get("updated_at")} for r in repos]
        return []
    except requests.RequestException:
        return []


def create_gitea_release(token: str, server_url: str, owner: str, repo: str,
                         tag_name: str, name: str = "", body: str = "",
                         draft: bool = False, prerelease: bool = False) -> Optional[dict]:
    """Create a Release on Gitea via API."""
    server_url = server_url.rstrip("/")
    try:
        resp = requests.post(
            f"{server_url}/api/v1/repos/{owner}/{repo}/releases",
            headers={"Authorization": f"token {token}"},
            json={
                "tag_name": tag_name,
                "name": name or tag_name,
                "body": body,
                "draft": draft,
                "prerelease": prerelease,
                "auto_init": True,
            },
            timeout=15,
        )
        if resp.status_code in (200, 201):
            return resp.json()
        return None
    except requests.RequestException:
        return None
