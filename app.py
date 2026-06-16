"""Git Smart Manager — Flask application serving both REST API and frontend."""

import os
import sys
import json
import uuid
import logging
import webbrowser
from pathlib import Path
from threading import Timer

from flask import Flask, render_template, request, jsonify

from gsm.config import DATA_DIR, APP_NAME, APP_VERSION, DEFAULT_PORT
from gsm.storage import load_projects, save_projects, load_settings, save_settings, get_token, set_token
from gsm.git_utils import (
    is_git_repo, get_status, get_recent_commits, clone_repo,
    open_in_fork, setup_multi_push,
    git_init, git_stage_file, git_unstage_file, git_stage_all,
    git_commit, git_push, git_pull, git_fetch,
    git_branch_list, git_branch_create, git_branch_delete, git_branch_switch, git_branch_rename,
    git_merge, git_stash_push, git_stash_pop, git_stash_list, git_stash_drop,
    git_log_detailed, git_diff, git_remote_list, git_remote_add, git_remote_remove,
    git_reset, git_tag_list, git_tag_create, git_tag_delete,
    git_init, git_custom_command, git_tree, git_read_file, git_log_graph,
)
from gsm.api_utils import (
    check_github_token, check_gitea_token, check_gitea_password,
    create_github_repo, create_gitea_repo,
    list_gitea_repos, list_gitea_repos_basic_auth,
)

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger("gsm")
app = Flask(__name__)


# ═══════════════════════════════════════════════════════════════════════════
#  FRONTEND
# ═══════════════════════════════════════════════════════════════════════════

@app.route("/")
def index():
    return render_template("index.html", app_name=APP_NAME, version=APP_VERSION)


# ═══════════════════════════════════════════════════════════════════════════
#  API: PROJECTS
# ═══════════════════════════════════════════════════════════════════════════

@app.route("/api/projects", methods=["GET"])
def api_list_projects():
    projects = load_projects()
    for p in projects:
        p["status_summary"] = _cached_status(p)
    return jsonify(projects)


@app.route("/api/projects", methods=["POST"])
def api_create_project():
    data = request.get_json(force=True)
    if not data: return jsonify({"error": "Empty body"}), 400

    clone_url = data.get("clone_url")
    local_path = data.get("_local_path", data.get("target_dir", ""))

    # Add existing local directory
    if local_path and not clone_url:
        existing = load_projects()
        for p in existing:
            if os.path.abspath(p.get("path", "")) == os.path.abspath(local_path):
                return jsonify({"error": "Dự án đã tồn tại"}), 409
        name = os.path.basename(os.path.normpath(local_path))
        project = {"id": _new_id(), "name": name, "path": os.path.normpath(local_path),
                   "github_remote": "", "gitea_remote": "", "created_at": _now_iso()}
        projects = load_projects()
        projects.append(project)
        save_projects(projects)
        return jsonify({"project": project, "lines": []}), 201

    if clone_url:
        target_dir = data.get("target_dir", "")
        if not target_dir: return jsonify({"error": "Thiếu thư mục đích"}), 400
        try: lines = clone_repo(clone_url, target_dir)
        except RuntimeError as e: return jsonify({"error": str(e)}), 500
        name = Path(target_dir).name
        project = {"id": _new_id(), "name": name, "path": target_dir,
                   "github_remote": clone_url if "github" in clone_url.lower() else "",
                   "gitea_remote": clone_url if "gitea" in clone_url.lower() else "", "created_at": _now_iso()}
        projects = load_projects()
        projects.append(project)
        save_projects(projects)
        return jsonify({"project": project, "lines": lines}), 201

    # Create new repo
    name = data.get("name", "").strip()
    if not name: return jsonify({"error": "Thiếu tên repo"}), 400
    description = data.get("description", "")
    private = data.get("private", False)
    create_github = data.get("github", True)
    create_gitea = data.get("gitea", True)
    target_dir = data.get("target_dir", "")
    if not target_dir: return jsonify({"error": "Thiếu thư mục đích"}), 400
    full_path = os.path.join(target_dir, name)
    if os.path.exists(full_path): return jsonify({"error": f"{full_path} đã tồn tại"}), 409

    settings = load_settings()
    github_token = get_token("github_token")
    gitea_token = get_token("gitea_token")
    gitea_server = settings.get("gitea_server_url", "")
    github_url = None; gitea_url = None; errors = []

    if create_github:
        if not github_token: errors.append("Chưa cấu hình GitHub token")
        else:
            github_url = create_github_repo(github_token, name, description, private)
            if not github_url: errors.append("Tạo GitHub repo thất bại")
    if create_gitea:
        if not gitea_token or not gitea_server: errors.append("Chưa cấu hình Gitea")
        else:
            gitea_url = create_gitea_repo(gitea_token, gitea_server, name, description, private)
            if not gitea_url: errors.append("Tạo Gitea repo thất bại")
    if not github_url and not gitea_url:
        return jsonify({"error": "; ".join(errors) if errors else "Không thể tạo repo"}), 400

    clone_from = github_url or gitea_url
    try: lines = clone_repo(clone_from, full_path)
    except RuntimeError as e: return jsonify({"error": f"Clone thất bại: {str(e)}"}), 500

    try:
        if github_url and gitea_url: setup_multi_push(full_path, github_url, gitea_url)
        elif github_url: _run_simple_git(full_path, "remote", "add", "origin", github_url)
        elif gitea_url: _run_simple_git(full_path, "remote", "add", "origin", gitea_url)
    except RuntimeError: pass

    project = {"id": _new_id(), "name": name, "path": full_path,
               "github_remote": github_url or "", "gitea_remote": gitea_url or "", "created_at": _now_iso()}
    projects = load_projects()
    projects.append(project)
    save_projects(projects)
    return jsonify({"project": project, "lines": lines}), 201


@app.route("/api/projects/<project_id>", methods=["DELETE"])
def api_delete_project(project_id):
    data = request.get_json(silent=True) or {}
    remove_local = data.get("remove_local", False)
    projects = load_projects()
    idx = None
    for i, p in enumerate(projects):
        if p["id"] == project_id: idx = i; break
    if idx is None: return jsonify({"error": "Không tìm thấy"}), 404
    project = projects.pop(idx)
    save_projects(projects)
    if remove_local:
        import shutil
        p = project.get("path", "")
        if p and os.path.isdir(p): shutil.rmtree(p, ignore_errors=True)
    return jsonify({"message": "Đã xóa"})


@app.route("/api/projects/<project_id>/status", methods=["GET"])
def api_project_status(project_id):
    project = _find_project(project_id)
    if not project: return jsonify({"error": "Không tìm thấy"}), 404
    path = project.get("path", "")
    if not path or not os.path.isdir(path): return jsonify({"error": "Thư mục không tồn tại"}), 404
    if not is_git_repo(path): return jsonify({"error": "Không phải git repo"}), 400
    return jsonify(get_status(path))


@app.route("/api/projects/<project_id>/commits", methods=["GET"])
def api_project_commits(project_id):
    limit = request.args.get("limit", 10, type=int)
    project = _find_project(project_id)
    if not project: return jsonify({"error": "Không tìm thấy"}), 404
    path = project.get("path", "")
    if not path or not os.path.isdir(path): return jsonify({"error": "Thư mục không tồn tại"}), 404
    return jsonify(get_recent_commits(path, limit=limit))


@app.route("/api/projects/<project_id>/open", methods=["POST"])
def api_project_open(project_id):
    project = _find_project(project_id)
    if not project: return jsonify({"error": "Không tìm thấy"}), 404
    settings = load_settings()
    fork_path = settings.get("fork_path", "")
    if not fork_path or not os.path.isfile(fork_path): return jsonify({"error": "Chưa cấu hình Fork"}), 400
    path = project.get("path", "")
    if not path or not os.path.isdir(path): return jsonify({"error": "Thư mục không tồn tại"}), 404
    try: open_in_fork(fork_path, path); return jsonify({"message": "Đã mở trong Fork"})
    except Exception as e: return jsonify({"error": str(e)}), 500


@app.route("/api/projects/<project_id>/setup-multipush", methods=["POST"])
def api_setup_multipush(project_id):
    project = _find_project(project_id)
    if not project: return jsonify({"error": "Không tìm thấy"}), 404
    github_url = project.get("github_remote", ""); gitea_url = project.get("gitea_remote", "")
    if not github_url or not gitea_url: return jsonify({"error": "Thiếu remote URL"}), 400
    try: lines = setup_multi_push(project["path"], github_url, gitea_url); return jsonify({"message": "OK", "lines": lines})
    except RuntimeError as e: return jsonify({"error": str(e)}), 500


# ═══════════════════════════════════════════════════════════════════════════
#  API: GIT COMMANDS (generic)
# ═══════════════════════════════════════════════════════════════════════════

def _require_project(project_id: str, require_git: bool = True):
    project = _find_project(project_id)
    if not project: return None, "Không tìm thấy"
    path = project.get("path", "")
    if not path or not os.path.isdir(path): return None, "Thư mục không tồn tại"
    if require_git and not is_git_repo(path): return None, "Không phải git repository"
    return project, None


def _git_result(result: dict):
    if result.get("success"): return jsonify(result), 200
    return jsonify(result), 400


@app.route("/api/projects/<project_id>/git/<cmd>", methods=["POST"])
def api_git_command(project_id, cmd):
    no_git_cmds = ["init"]
    project, err = _require_project(project_id, require_git=cmd not in no_git_cmds)
    if err: return jsonify({"error": err}), 400
    path = project["path"]
    data = request.get_json(silent=True) or {}

    cmd_map = {
        "stage_file":    lambda: git_stage_file(path, data.get("file", "")),
        "unstage_file":  lambda: git_unstage_file(path, data.get("file", "")),
        "stage_all":     lambda: git_stage_all(path),
        "commit":        lambda: git_commit(path, data.get("message", "")),
        "push":          lambda: git_push(path, data.get("remote", "origin"), data.get("branch", "")),
        "pull":          lambda: git_pull(path, data.get("remote", "origin"), data.get("branch", "")),
        "fetch":         lambda: git_fetch(path, data.get("remote", "")),
        "branch_list":   lambda: jsonify(git_branch_list(path)),
        "branch_create": lambda: _git_result(git_branch_create(path, data.get("name", ""), data.get("from", ""))),
        "branch_delete": lambda: _git_result(git_branch_delete(path, data.get("name", ""))),
        "branch_switch": lambda: _git_result(git_branch_switch(path, data.get("name", ""))),
        "merge":         lambda: _git_result(git_merge(path, data.get("branch", ""))),
        "stash_push":    lambda: _git_result(git_stash_push(path, data.get("message", ""))),
        "stash_pop":     lambda: _git_result(git_stash_pop(path)),
        "stash_list":    lambda: jsonify(git_stash_list(path)),
        "stash_drop":    lambda: _git_result(git_stash_drop(path, data.get("ref", "stash@{0}"))),
        "log":           lambda: jsonify(git_log_detailed(path, data.get("limit", 50), data.get("branch", ""))),
        "graph":         lambda: jsonify(git_log_graph(path, data.get("limit", 50), data.get("all", True))),
        "diff":          lambda: jsonify({"content": git_diff(path, data.get("file", ""), data.get("staged", False))}),
        "remote_list":   lambda: jsonify(git_remote_list(path)),
        "remote_add":    lambda: _git_result(git_remote_add(path, data.get("name", ""), data.get("url", ""))),
        "remote_remove": lambda: _git_result(git_remote_remove(path, data.get("name", ""))),
        "reset":         lambda: _git_result(git_reset(path, data.get("mode", "mixed"), data.get("target", "HEAD"))),
        "tag_list":      lambda: jsonify(git_tag_list(path)),
        "tag_create":    lambda: _git_result(git_tag_create(path, data.get("name", ""), data.get("message", ""))),
        "tag_delete":    lambda: _git_result(git_tag_delete(path, data.get("name", ""))),
        "init":          lambda: _git_result(git_init(path)),
        "tree":          lambda: jsonify(git_tree(path, data.get("branch", ""))),
        "read_file":     lambda: jsonify({"content": git_read_file(path, data.get("file", ""), data.get("branch", ""))}),
        "custom":        lambda: _git_result(git_custom_command(path, data.get("command", ""))),
    }
    fn = cmd_map.get(cmd)
    if not fn: return jsonify({"error": f"Unknown git command: {cmd}"}), 400
    try: return fn()
    except Exception as e: return jsonify({"error": str(e), "success": False}), 500


# ═══════════════════════════════════════════════════════════════════════════
#  API: CREATE REMOTE
# ═══════════════════════════════════════════════════════════════════════════

@app.route("/api/projects/<project_id>/create-remote", methods=["POST"])
def api_create_remote(project_id):
    project = _find_project(project_id)
    if not project: return jsonify({"error": "Không tìm thấy"}), 404
    path = project.get("path", "")
    if not path or not os.path.isdir(path): return jsonify({"error": "Thư mục không tồn tại"}), 400
    if not is_git_repo(path): return jsonify({"error": "Chưa phải git repo"}), 400
    data = request.get_json(force=True) or {}
    platform = data.get("platform", "")
    private = data.get("private", False)
    description = data.get("description", "")
    name = project.get("name", "")
    if not name: return jsonify({"error": "Tên không hợp lệ"}), 400
    settings = load_settings()

    # ── Handle 'both' platform ────────────────────────────────────────────
    if platform == "both":
        github_token = get_token("github_token")
        gitea_token = get_token("gitea_token")
        gitea_server = settings.get("gitea_server_url", "")
        errors = []
        github_url = None
        gitea_url = None

        if github_token:
            github_url = create_github_repo(github_token, name, description, private, auto_init=False)
            if not github_url: errors.append("GitHub thất bại")
        else:
            errors.append("Chưa có GitHub token")

        if gitea_token and gitea_server:
            gitea_url = create_gitea_repo(gitea_token, gitea_server, name, description, private, auto_init=False)
            if not gitea_url: errors.append("Gitea thất bại")
        else:
            errors.append("Chưa cấu hình Gitea")

        if not github_url and not gitea_url:
            return jsonify({"error": f"Không tạo được repo nào: {'; '.join(errors)}"}), 500

        from gsm.git_utils import setup_multi_push, _run_git
        try:
            _run_git(["remote", "add", "origin", github_url or gitea_url], cwd=path)
        except:
            pass
        if github_url and gitea_url:
            try: setup_multi_push(path, github_url, gitea_url)
            except: pass
        elif github_url:
            _run_simple_git_result(path, "remote", "set-url", "origin", github_url)
        elif gitea_url:
            _run_simple_git_result(path, "remote", "set-url", "origin", gitea_url)

        projects = load_projects()
        for p in projects:
            if p["id"] == project_id:
                if github_url: p["github_remote"] = github_url
                if gitea_url: p["gitea_remote"] = gitea_url
                break
        save_projects(projects)

        msg = "Đã tạo remote trên GitHub & Gitea" if github_url and gitea_url else \
              f"Đã tạo remote trên {'GitHub' if github_url else 'Gitea'}"
        return jsonify({"success": True, "message": msg, "github_url": github_url, "gitea_url": gitea_url})

    # ── Single platform ───────────────────────────────────────────────────
    if platform == "github":
        token = get_token("github_token")
        if not token: return jsonify({"error": "Chưa cấu hình GitHub token"}), 400
        clone_url = create_github_repo(token, name, description, private, auto_init=False)
        if not clone_url: return jsonify({"error": "Tạo GitHub repo thất bại"}), 500
    elif platform == "gitea":
        token = get_token("gitea_token")
        server_url = settings.get("gitea_server_url", "")
        if not token or not server_url: return jsonify({"error": "Chưa cấu hình Gitea"}), 400
        clone_url = create_gitea_repo(token, server_url, name, description, private, auto_init=False)
        if not clone_url: return jsonify({"error": "Tạo Gitea repo thất bại"}), 500
    else:
        return jsonify({"error": "Platform phải là 'github', 'gitea' hoặc 'both'"}), 400

    r = _run_simple_git_result(path, "remote", "add", "origin", clone_url)
    if not r.get("success"):
        r = _run_simple_git_result(path, "remote", "set-url", "origin", clone_url)
        if not r.get("success"): return jsonify({"error": f"Set remote thất bại: {r.get('stderr', '')}"}), 500

    projects = load_projects()
    for p in projects:
        if p["id"] == project_id:
            if platform == "github": p["github_remote"] = clone_url
            elif platform == "gitea": p["gitea_remote"] = clone_url
            break
    save_projects(projects)
    return jsonify({"success": True, "message": f"Đã tạo remote {platform}", "clone_url": clone_url})


def _run_simple_git_result(cwd: str, *args: str) -> dict:
    import subprocess
    try:
        r = subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True, timeout=30)
        return {"success": r.returncode == 0, "stdout": r.stdout.strip(), "stderr": r.stderr.strip()}
    except Exception as e: return {"success": False, "stderr": str(e)}


# ═══════════════════════════════════════════════════════════════════════════
#  API: SETTINGS
# ═══════════════════════════════════════════════════════════════════════════

@app.route("/api/settings", methods=["GET"])
def api_get_settings():
    settings = load_settings()
    settings["has_github_token"] = get_token("github_token") is not None
    settings["has_gitea_token"] = get_token("gitea_token") is not None
    settings["has_gitea_username"] = get_token("gitea_username") is not None
    settings["has_gitea_password"] = get_token("gitea_password") is not None
    return jsonify(settings)


@app.route("/api/settings", methods=["POST"])
def api_save_settings():
    data = request.get_json(force=True)
    if not data: return jsonify({"error": "Empty body"}), 400
    github_token = data.get("github_token", "").strip()
    if github_token: set_token("github_token", github_token)
    gitea_token = data.get("gitea_token", "").strip()
    if gitea_token: set_token("gitea_token", gitea_token)
    gitea_username = data.get("gitea_username", "").strip()
    if gitea_username: set_token("gitea_username", gitea_username)
    gitea_password = data.get("gitea_password", "").strip()
    if gitea_password: set_token("gitea_password", gitea_password)
    settings = load_settings()
    for key in ("fork_path", "gitea_server_url"):
        if key in data: settings[key] = data[key].strip()
    save_settings(settings)
    return jsonify({"message": "Đã lưu cài đặt"})


@app.route("/api/settings/check-token", methods=["POST"])
def api_check_token():
    data = request.get_json(force=True)
    platform = data.get("platform", "")
    if platform == "gitea_password":
        username = data.get("username", ""); password = data.get("password", "")
        if not username or not password: return jsonify({"valid": False, "error": "Thiếu user/pass"})
        server = load_settings().get("gitea_server_url", "")
        if not server: return jsonify({"valid": False, "error": "Thiếu Gitea server URL"})
        info = check_gitea_password(server, username, password)
        if info: return jsonify({"valid": True, "info": info})
        return jsonify({"valid": False, "error": "Sai user/pass"})
    token = data.get("token", "")
    if not token: return jsonify({"valid": False, "error": "Token trống"})
    if platform == "github":
        info = check_github_token(token)
    elif platform == "gitea":
        server = load_settings().get("gitea_server_url", "")
        if not server: return jsonify({"valid": False, "error": "Thiếu Gitea server URL"})
        info = check_gitea_token(token, server)
    else: return jsonify({"valid": False, "error": f"Unknown: {platform}"})
    if info: return jsonify({"valid": True, "info": info})
    return jsonify({"valid": False, "error": "Token không hợp lệ"})


# ═══════════════════════════════════════════════════════════════════════════
#  API: GITEA REPOS
# ═══════════════════════════════════════════════════════════════════════════

@app.route("/api/gitea/repos", methods=["GET"])
def api_gitea_repos():
    settings = load_settings()
    server_url = settings.get("gitea_server_url", "")
    if not server_url: return jsonify({"error": "Chưa cấu hình Gitea server"}), 400
    token = get_token("gitea_token")
    if token:
        repos = list_gitea_repos(token, server_url)
        if repos: return jsonify({"repos": repos, "auth_method": "token"})
    username = get_token("gitea_username"); password = get_token("gitea_password")
    if username and password:
        repos = list_gitea_repos_basic_auth(server_url, username, password)
        if repos: return jsonify({"repos": repos, "auth_method": "basic"})
    repos = list_gitea_repos("", server_url)
    if repos: return jsonify({"repos": repos, "auth_method": "none"})
    return jsonify({"error": "Không thể kết nối Gitea"}), 400


@app.route("/api/gitea/repos/import", methods=["POST"])
def api_gitea_import_repo():
    data = request.get_json(force=True)
    clone_url = data.get("clone_url", ""); target_dir = data.get("target_dir", "")
    if not clone_url or not target_dir: return jsonify({"error": "Thiếu thông tin"}), 400
    try: lines = clone_repo(clone_url, target_dir)
    except RuntimeError as e: return jsonify({"error": str(e)}), 500
    name = Path(target_dir).name
    project = {"id": _new_id(), "name": name, "path": target_dir, "github_remote": "", "gitea_remote": clone_url, "created_at": _now_iso()}
    projects = load_projects(); projects.append(project); save_projects(projects)
    return jsonify({"project": project, "lines": lines}), 201


# ═══════════════════════════════════════════════════════════════════════════
#  API: DIALOGS
# ═══════════════════════════════════════════════════════════════════════════

@app.route("/api/dialogs/select-folder", methods=["POST"])
def api_select_folder():
    try:
        import tkinter as tk
        from tkinter import filedialog
        root = tk.Tk(); root.withdraw(); root.attributes('-topmost', True)
        folder = filedialog.askdirectory(title="Chọn thư mục dự án")
        root.destroy()
        if folder: return jsonify({"path": folder})
        return jsonify({"path": "", "cancelled": True})
    except ImportError:
        return jsonify({"error": "tkinter not available", "path": ""})


# ═══════════════════════════════════════════════════════════════════════════
#  HELPERS
# ═══════════════════════════════════════════════════════════════════════════

def _new_id() -> str: return uuid.uuid4().hex[:12]

def _now_iso() -> str:
    from datetime import datetime
    return datetime.now().isoformat(timespec="seconds")

def _find_project(project_id: str) -> dict | None:
    projects = load_projects()
    for p in projects:
        if p["id"] == project_id: return p
    return None

def _cached_status(project: dict) -> dict:
    path = project.get("path", "")
    if not path or not is_git_repo(path):
        return {"branch": "—", "has_changes": False, "has_conflict": False}
    try:
        status = get_status(path)
        return {"branch": status.get("branch", "—"), "has_changes": len(status.get("files", [])) > 0, "has_conflict": status.get("has_conflict", False)}
    except Exception:
        return {"branch": "?", "has_changes": False, "has_conflict": False}

def _run_simple_git(cwd: str, *args: str) -> None:
    import subprocess
    r = subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True)
    if r.returncode != 0: raise RuntimeError(r.stderr.strip())


# ═══════════════════════════════════════════════════════════════════════════
#  ENTRY
# ═══════════════════════════════════════════════════════════════════════════

def find_free_port(start: int = DEFAULT_PORT, max_tries: int = 50) -> int:
    import socket
    for port in range(start, start + max_tries):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            if s.connect_ex(("127.0.0.1", port)) != 0: return port
    raise RuntimeError("No free port found")

def open_browser(port: int, delay: float = 1.0) -> None:
    def _open(): webbrowser.open(f"http://127.0.0.1:{port}")
    Timer(delay, _open).start()

def main():
    port = find_free_port()
    log.info("=" * 50)
    log.info(f"  {APP_NAME} v{APP_VERSION}")
    log.info(f"  Data dir: {DATA_DIR}")
    log.info(f"  Server:   http://127.0.0.1:{port}")
    log.info("=" * 50)
    open_browser(port, delay=1.5)
    app.run(host="127.0.0.1", port=port, debug=False, use_reloader=False)

if __name__ == "__main__":
    main()
