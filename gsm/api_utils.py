import requests
from typing import Optional, Any


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


def list_github_repos(token: str) -> list[dict]:
    try:
        resp = requests.get(
            "https://api.github.com/user/repos",
            headers={"Authorization": f"Bearer {token}", "Accept": "application/vnd.github.v3+json"},
            params={"per_page": 100, "sort": "updated"},
            timeout=15,
        )
        if resp.status_code == 200:
            repos = resp.json()
            return [{"id": r.get("id"), "name": r.get("name"), "full_name": r.get("full_name"),
                     "description": r.get("description", "") or "", "clone_url": r.get("clone_url"),
                     "ssh_url": r.get("ssh_url"), "private": r.get("private", False),
                     "default_branch": r.get("default_branch", "main"), "updated_at": r.get("updated_at")} for r in repos]
        return []
    except requests.RequestException:
        return []


def _get_gitea_auth_kwargs(auth: Any) -> dict:
    """Helper to return either auth=(user, pass) or headers={'Authorization': 'token ...'}."""
    if isinstance(auth, tuple) and len(auth) == 2 and auth[0]:
        return {"auth": auth}
    if isinstance(auth, str) and auth.strip():
        return {"headers": {"Authorization": f"token {auth.strip()}"}}
    return {}


def get_gitea_release_by_tag(auth: Any, server_url: str, owner: str, repo: str, tag_name: str) -> Optional[dict]:
    """Get existing release on Gitea by tag name."""
    server_url = server_url.rstrip("/")
    kw = _get_gitea_auth_kwargs(auth)
    try:
        resp = requests.get(
            f"{server_url}/api/v1/repos/{owner}/{repo}/releases/tags/{tag_name}",
            timeout=15,
            **kw
        )
        if resp.status_code == 200:
            return resp.json()
        return None
    except requests.RequestException:
        return None


def create_gitea_release(auth: Any, server_url: str, owner: str, repo: str,
                         tag_name: str, name: str = "", body: str = "",
                         draft: bool = False, prerelease: bool = False) -> Optional[dict]:
    """Create a Release on Gitea via API, fallback to existing if present."""
    server_url = server_url.rstrip("/")
    kw = _get_gitea_auth_kwargs(auth)
    try:
        resp = requests.post(
            f"{server_url}/api/v1/repos/{owner}/{repo}/releases",
            json={
                "tag_name": tag_name,
                "name": name or tag_name,
                "body": body,
                "draft": draft,
                "prerelease": prerelease,
            },
            timeout=15,
            **kw
        )
        if resp.status_code in (200, 201):
            return resp.json()
        # Fallback to fetch existing release if tag already exists
        return get_gitea_release_by_tag(auth, server_url, owner, repo, tag_name)
    except requests.RequestException:
        return get_gitea_release_by_tag(auth, server_url, owner, repo, tag_name)


def upload_gitea_asset(auth: Any, server_url: str, owner: str, repo: str, release_id: int, file_path: str, custom_name: Optional[str] = None) -> tuple[Optional[dict], Optional[str]]:
    """Upload asset file to Gitea Release, replacing existing asset if present."""
    import os
    server_url = server_url.rstrip("/")
    filename = custom_name or os.path.basename(file_path)
    kw = _get_gitea_auth_kwargs(auth)
    
    # 1. Delete existing asset with same filename if present
    try:
        get_assets_resp = requests.get(
            f"{server_url}/api/v1/repos/{owner}/{repo}/releases/{release_id}/assets",
            timeout=15,
            **kw
        )
        if get_assets_resp.status_code == 200:
            for asset in get_assets_resp.json():
                if asset.get("name") == filename:
                    asset_id = asset.get("id")
                    requests.delete(
                        f"{server_url}/api/v1/repos/{owner}/{repo}/releases/{release_id}/assets/{asset_id}",
                        timeout=15,
                        **kw
                    )
    except Exception:
        pass

    # 2. Upload asset file
    try:
        with open(file_path, "rb") as f:
            files = {"attachment": (filename, f, "application/octet-stream")}
            resp = requests.post(
                f"{server_url}/api/v1/repos/{owner}/{repo}/releases/{release_id}/assets?name={filename}",
                files=files,
                timeout=180,
                **kw
            )
            if resp.status_code in (200, 201):
                return resp.json(), None
            return None, f"HTTP {resp.status_code}: {resp.text[:150]}"
    except Exception as e:
        return None, str(e)


def get_github_release_by_tag(token: str, owner: str, repo: str, tag_name: str) -> Optional[dict]:
    """Get existing release on GitHub by tag name."""
    try:
        resp = requests.get(
            f"https://api.github.com/repos/{owner}/{repo}/releases/tags/{tag_name}",
            headers={"Authorization": f"Bearer {token}", "Accept": "application/vnd.github.v3+json"},
            timeout=15,
        )
        if resp.status_code == 200:
            return resp.json()
        return None
    except requests.RequestException:
        return None


def create_github_release(token: str, owner: str, repo: str, tag_name: str, name: str = "", body: str = "") -> Optional[dict]:
    """Create a Release on GitHub via API, fallback to existing if present."""
    try:
        resp = requests.post(
            f"https://api.github.com/repos/{owner}/{repo}/releases",
            headers={"Authorization": f"Bearer {token}", "Accept": "application/vnd.github.v3+json"},
            json={"tag_name": tag_name, "name": name or tag_name, "body": body},
            timeout=15,
        )
        if resp.status_code in (200, 201):
            return resp.json()
        return get_github_release_by_tag(token, owner, repo, tag_name)
    except requests.RequestException:
        return get_github_release_by_tag(token, owner, repo, tag_name)


def upload_github_asset(token: str, owner: str, repo: str, release_id: int, file_path: str, custom_name: Optional[str] = None) -> tuple[Optional[dict], Optional[str]]:
    """Upload asset file to GitHub Release, replacing existing asset if present."""
    import os
    filename = custom_name or os.path.basename(file_path)

    # 1. Delete existing asset with same filename if present
    try:
        get_assets_resp = requests.get(
            f"https://api.github.com/repos/{owner}/{repo}/releases/{release_id}/assets",
            headers={"Authorization": f"Bearer {token}", "Accept": "application/vnd.github.v3+json"},
            timeout=15,
        )
        if get_assets_resp.status_code == 200:
            for asset in get_assets_resp.json():
                if asset.get("name") == filename:
                    asset_id = asset.get("id")
                    requests.delete(
                        f"https://api.github.com/repos/{owner}/{repo}/releases/assets/{asset_id}",
                        headers={"Authorization": f"Bearer {token}", "Accept": "application/vnd.github.v3+json"},
                        timeout=15,
                    )
    except Exception:
        pass

    # 2. Upload asset file
    try:
        with open(file_path, "rb") as f:
            data = f.read()
        resp = requests.post(
            f"https://uploads.github.com/repos/{owner}/{repo}/releases/{release_id}/assets?name={filename}",
            headers={
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/octet-stream",
                "Accept": "application/vnd.github.v3+json"
            },
            data=data,
            timeout=180,
        )
        if resp.status_code in (200, 201):
            return resp.json(), None
        return None, f"HTTP {resp.status_code}: {resp.text[:150]}"
    except Exception as e:
        return None, str(e)

