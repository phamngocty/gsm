"""Git Smart Manager — Flask application serving both REST API and frontend."""

import os
import sys
import json
import uuid
import logging
import webbrowser
from pathlib import Path
from threading import Timer

from flask import Flask, render_template, request, jsonify, send_file

from gsm.config import DATA_DIR, APP_NAME, APP_VERSION, DEFAULT_PORT
from gsm.storage import load_projects, save_projects, load_settings, save_settings, get_token, set_token
from gsm.git_utils import (
    is_git_repo, get_status, get_recent_commits, clone_repo,
    open_in_fork, setup_multi_push,
    git_init, git_stage_file, git_unstage_file, git_stage_all,
    git_commit, git_push, git_pull, git_fetch, git_push_tag,
    git_branch_list, git_branch_create, git_branch_delete, git_branch_switch, git_branch_rename,
    git_merge, git_stash_push, git_stash_pop, git_stash_list, git_stash_drop,
    git_log_detailed, git_diff, git_remote_list, git_remote_add, git_remote_remove,
    git_reset, git_tag_list, git_tag_create, git_tag_delete,
    git_init, git_custom_command, git_tree, git_read_file, git_log_graph,
    git_archive_zip, git_diff_parsed, git_resolve_conflict,
)
from gsm.api_utils import (
    check_github_token, check_gitea_token, check_gitea_password,
    create_github_repo, create_gitea_repo, create_gitea_release,
    list_gitea_repos, list_gitea_repos_basic_auth, list_github_repos,
    upload_gitea_asset, create_github_release, upload_github_asset,
)
from gsm.ota_utils import find_release_assets, sync_version_to_nas

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
    # Ensure error field is set for frontend
    if "error" not in result:
        result["error"] = (result.get("stderr") or result.get("stdout") or "").strip() or "Git command failed"
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
        "push":          lambda: git_push(path, data.get("remote", "origin"), data.get("branch", ""), data.get("force", False)),
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
        "diff_detail":   lambda: jsonify(git_diff_parsed(path, data.get("file", ""), data.get("staged", False), data.get("commit", ""))),
        "resolve_conflict": lambda: _git_result(git_resolve_conflict(path, data.get("file", ""), data.get("choice", "ours"))),
        "remote_list":   lambda: jsonify(git_remote_list(path)),
        "remote_add":    lambda: _git_result(git_remote_add(path, data.get("name", ""), data.get("url", ""))),
        "remote_remove": lambda: _git_result(git_remote_remove(path, data.get("name", ""))),
        "reset":         lambda: _git_result(git_reset(path, data.get("mode", "mixed"), data.get("target", "HEAD"))),
        "tag_list":      lambda: jsonify(git_tag_list(path)),
        "tag_create":    lambda: _git_result(git_tag_create(path, data.get("name", ""), data.get("message", ""))),
        "tag_delete":    lambda: _git_result(git_tag_delete(path, data.get("name", ""))),
        "push_tag":      lambda: _git_result(git_push_tag(path, data.get("tag", ""), data.get("remote", "origin"))),
        "init":          lambda: _git_result(git_init(path)),
        "tree":          lambda: jsonify(git_tree(path, data.get("branch", ""))),
        "read_file":     lambda: jsonify({"content": git_read_file(path, data.get("file", ""), data.get("branch", ""))}),
        "custom":        lambda: _git_result(git_custom_command(path, data.get("command", ""))),
    }
    fn = cmd_map.get(cmd)
    if not fn: return jsonify({"error": f"Unknown git command: {cmd}"}), 400
    try: return fn()
    except Exception as e: return jsonify({"error": str(e), "success": False}), 500


@app.route("/api/projects/<project_id>/diff-detail", methods=["GET", "POST"])
def api_project_diff_detail(project_id):
    project, err = _require_project(project_id, require_git=True)
    if err: return jsonify({"error": err}), 400
    data = request.get_json(silent=True) or {}
    file_path = request.args.get("file") or data.get("file", "")
    commit = request.args.get("commit") or data.get("commit", "")
    staged = request.args.get("staged", "false").lower() == "true" or data.get("staged", False)
    return jsonify(git_diff_parsed(project["path"], file_path=file_path, staged=staged, commit_hash=commit))


@app.route("/api/projects/<project_id>/archive-zip", methods=["GET"])
@app.route("/api/git/archive-zip", methods=["GET"])
def api_archive_zip(project_id=None):
    pid = project_id or request.args.get("id") or request.args.get("project_id")
    if not pid:
        return jsonify({"error": "Thiếu project_id"}), 400
    project, err = _require_project(pid, require_git=True)
    if err:
        return jsonify({"error": err}), 400
    ref = request.args.get("ref", "HEAD").strip() or "HEAD"
    import tempfile
    tmp_file = tempfile.NamedTemporaryFile(suffix=".zip", delete=False)
    tmp_path = tmp_file.name
    tmp_file.close()

    res = git_archive_zip(project["path"], ref, tmp_path)
    if not res.get("success"):
        if os.path.exists(tmp_path):
            os.remove(tmp_path)
        return jsonify({"error": res.get("error", "Lỗi tạo file zip")}), 500

    safe_name = "".join(c if c.isalnum() or c in "-_" else "_" for c in project.get("name", "project"))
    safe_ref = "".join(c if c.isalnum() or c in "-_." else "_" for c in ref)
    download_filename = f"{safe_name}-{safe_ref}.zip"
    return send_file(tmp_path, as_attachment=True, download_name=download_filename, mimetype="application/zip")


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
#  API: GITEA RELEASE
# ═══════════════════════════════════════════════════════════════════════════

@app.route("/api/projects/<project_id>/gitea-release", methods=["POST"])
def api_create_gitea_release(project_id):
    from urllib.parse import urlparse
    project = _find_project(project_id)
    if not project: return jsonify({"error": "Không tìm thấy"}), 404
    gitea_url = project.get("gitea_remote", "")
    if not gitea_url: return jsonify({"error": "Chưa có remote Gitea"}), 400

    settings = load_settings()
    token = get_token("gitea_token") or ""
    server_url = settings.get("gitea_server_url", "").rstrip("/")
    if not token or not server_url: return jsonify({"error": "Chưa cấu hình Gitea token"}), 400

    # Parse owner/repo from remote URL
    # e.g. http://192.168.1.114:3002/nas152/gsm.git → owner=nas152, repo=gsm
    parsed = urlparse(gitea_url)
    parts = parsed.path.strip("/").rstrip(".git").split("/")
    if len(parts) < 2: return jsonify({"error": "URL remote không hợp lệ"}), 400
    owner, repo = parts[-2], parts[-1]

    data = request.get_json(force=True) or {}
    tag_name = data.get("tag_name", "")
    name = data.get("name", tag_name)
    body = data.get("body", "")
    if not tag_name: return jsonify({"error": "Thiếu tên tag"}), 400

    result = create_gitea_release(token, server_url, owner, repo, tag_name, name, body)
    if result:
        return jsonify({"success": True, "release": result, "html_url": result.get("html_url", "")})
    return jsonify({"error": "Tạo release trên Gitea thất bại"}), 400


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
#  API: GITHUB REPOS
# ═══════════════════════════════════════════════════════════════════════════

@app.route("/api/github/repos", methods=["GET"])
def api_github_repos():
    token = get_token("github_token")
    if not token:
        return jsonify({"error": "Chưa cấu hình GitHub token"}), 400
    repos = list_github_repos(token)
    return jsonify({"repos": repos})


@app.route("/api/github/repos/import", methods=["POST"])
def api_github_import_repo():
    data = request.get_json(force=True)
    clone_url = data.get("clone_url", "")
    target_dir = data.get("target_dir", "")
    if not clone_url or not target_dir:
        return jsonify({"error": "Thiếu thông tin"}), 400
    try:
        lines = clone_repo(clone_url, target_dir)
    except RuntimeError as e:
        return jsonify({"error": str(e)}), 500
    name = Path(target_dir).name
    project = {
        "id": _new_id(), "name": name, "path": target_dir,
        "github_remote": clone_url, "gitea_remote": "", "created_at": _now_iso()
    }
    projects = load_projects()
    projects.append(project)
    save_projects(projects)
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

# ═══════════════════════════════════════════════════════════════════════════
#  API: FILE BROWSER & OTA RELEASE MANAGEMENT
# ═══════════════════════════════════════════════════════════════════════════

@app.route("/api/browse-file", methods=["POST"])
def api_browse_file():
    """Trigger native Windows file dialog to browse for APK or BIN files."""
    try:
        import tkinter as tk
        from tkinter import filedialog
        data = request.get_json(force=True) or {}
        file_type = data.get("type", "all")
        
        root = tk.Tk()
        root.withdraw()
        root.attributes("-topmost", True)
        
        if file_type == "apk":
            filetypes = [("Android APK", "*.apk"), ("All Files", "*.*")]
            title = "Chọn file ứng dụng Android (.apk)"
        elif file_type == "bin":
            filetypes = [("ESP32 GC9A01 Firmware BIN", "*.bin"), ("All Files", "*.*")]
            title = "Chọn file Firmware ESP32 GC9A01 (.bin)"
        elif file_type == "oled_bin":
            filetypes = [("ESP32 OLED Firmware BIN", "*.bin"), ("All Files", "*.*")]
            title = "Chọn file Firmware ESP32 OLED (.bin)"
        else:
            filetypes = [("All Files", "*.*")]
            title = "Chọn file"
            
        file_path = filedialog.askopenfilename(title=title, filetypes=filetypes)
        root.destroy()
        return jsonify({"file_path": file_path or ""})
    except Exception as e:
        return jsonify({"error": f"Lỗi mở hộp thoại chọn file: {str(e)}", "file_path": ""}), 500


@app.route("/api/projects/<project_id>/ota-detect", methods=["GET"])
def api_ota_detect(project_id):
    """Tự động quét thư mục dự án để tìm APK, BIN và thông tin version.json."""
    projects = load_projects()
    project = next((p for p in projects if p["id"] == project_id), None)
    if not project:
        return jsonify({"error": "Dự án không tồn tại"}), 404

    local_path = project.get("path", "")
    data = find_release_assets(local_path)
    return jsonify(data)


@app.route("/api/projects/<project_id>/ota-release", methods=["POST"])
def api_create_ota_release(project_id):
    """Release OTA assets (APK & BIN) and update version.json to Gitea/GitHub."""
    projects = load_projects()
    project = next((p for p in projects if p["id"] == project_id), None)
    if not project:
        return jsonify({"error": "Dự án không tồn tại"}), 404

    data = request.get_json(force=True) or {}
    tag_name = data.get("tag_name", "").strip()
    release_name = data.get("release_name", tag_name).strip()
    changelog = data.get("changelog", "").strip()
    apk_path = data.get("apk_path", "").strip()
    bin_path = data.get("bin_path", "").strip()
    oled_bin_path = data.get("oled_bin_path", "").strip()
    app_ver_code = data.get("app_version_code", 1)
    fw_ver_code = data.get("fw_version_code", 1)

    if not tag_name:
        return jsonify({"error": "Thiếu Tag Name (ví dụ: v1.0.1)"}), 400

    logs = []
    local_path = project.get("path", "")
    
    # 1. Stage ALL changes, write version.json, commit ALL files & create tag
    if local_path and is_git_repo(local_path):
        try:
            # Stage ALL modified/untracked files in repo
            git_stage_all(local_path)
            
            # Write version.json locally
            version_data = {
                "app": {
                    "versionCode": int(app_ver_code),
                    "versionName": tag_name.lstrip("v"),
                    "apkUrl": "",
                    "changelog": changelog
                },
                "firmware": {
                    "versionCode": int(fw_ver_code),
                    "versionName": tag_name.lstrip("v"),
                    "binUrl": "",
                    "oledBinUrl": "",
                    "changelog": changelog
                },
                "firmware_oled": {
                    "versionCode": int(fw_ver_code),
                    "versionName": tag_name.lstrip("v"),
                    "binUrl": "",
                    "changelog": changelog
                }
            }
            v_path = os.path.join(local_path, "version.json")
            with open(v_path, "w", encoding="utf-8") as f:
                json.dump(version_data, f, ensure_ascii=False, indent=2)
            
            # Tự động Build lại APK Android mang chính xác mã phiên bản mới
            tymap_path = os.path.join(local_path, "TYMAP")
            if os.path.exists(tymap_path):
                logs.append(f"🔨 Đang tự động biên dịch Android APK cho phiên bản {tag_name}...")
                gradle_cmd = "gradlew.bat assembleDebug" if sys.platform == "win32" else "./gradlew assembleDebug"
                try:
                    res_gradle = subprocess.run(gradle_cmd, shell=True, cwd=tymap_path, capture_output=True, text=True)
                    if res_gradle.returncode == 0:
                        logs.append(f"✅ Đã build APK thành công với mã phiên bản {app_ver_code} ({tag_name})")
                    else:
                        logs.append(f"⚠️ Cảnh báo biên dịch APK: {res_gradle.stderr[:200] if res_gradle.stderr else res_gradle.stdout[:200]}")
                except Exception as e_build:
                    logs.append(f"⚠️ Không thể chạy build APK: {e_build}")

            git_stage_file(local_path, "version.json")
            git_stage_all(local_path)
            
            try:
                git_commit(local_path, f"release({tag_name}): full update release including version.json")
                logs.append(f"💾 Đã commit toàn bộ file dự án cho phiên bản {tag_name}")
            except Exception:
                pass # If nothing to commit

            try:
                git_tag_create(local_path, tag_name, f"Release {tag_name}")
                logs.append(f"✅ Đã tạo Git Tag cục bộ: {tag_name}")
            except Exception:
                pass
                
            git_push(local_path)
            git_push_tag(local_path, tag_name)
            logs.append(f"🚀 Đã push TOÀN BỘ file & Tag {tag_name} lên các Remote Git (Gitea/GitHub)")
        except Exception as e:
            logs.append(f"⚠️ Cảnh báo Git commit/push: {str(e)}")

    settings = load_settings()
    gitea_token = get_token("gitea_token") or settings.get("gitea_token", "")
    gitea_username = get_token("gitea_username") or settings.get("gitea_username", "") or "nas152"
    gitea_password = get_token("gitea_password") or settings.get("gitea_password", "") or "271000"
    gitea_server = settings.get("gitea_server", "").strip() or "http://192.168.1.114:3002"
    github_token = get_token("github_token") or settings.get("github_token", "")

    gitea_auth = gitea_token if gitea_token else (gitea_username, gitea_password)

    if not github_token:
        logs.append("💡 Gợi ý: Nếu muốn đẩy Release lên cả GitHub, bạn hãy điền GitHub Token trong Cài Đặt (⚙️ Settings -> GitHub Token)")
    
    gitea_apk_url = ""
    gitea_bin_url = ""
    gitea_oled_bin_url = ""
    github_apk_url = ""
    github_bin_url = ""
    github_oled_bin_url = ""

    # Parse owner/repo from remotes or setting
    gitea_remote = project.get("gitea_remote", "")
    github_remote = project.get("github_remote", "")
    if local_path and is_git_repo(local_path):
        try:
            r_list = git_remote_list(local_path)
            for r_name, r_url in r_list:
                if not gitea_remote and ("gitea" in r_url.lower() or "3002" in r_url or "3000" in r_url or "nas152" in r_url.lower() or "vostore" in r_url.lower()):
                    gitea_remote = r_url
                if not github_remote and "github" in r_url.lower():
                    github_remote = r_url
                if not gitea_remote and not github_remote and r_name == "origin":
                    if "github" in r_url.lower(): github_remote = r_url
                    else: gitea_remote = r_url
        except Exception: pass

    def parse_owner_repo(url):
        if not url: return "", ""
        clean = url.rstrip("/").removesuffix(".git")
        if ":" in clean and not clean.startswith("http://") and not clean.startswith("https://"):
            clean = clean.split(":")[-1]
        parts = clean.split("/")
        if len(parts) >= 2:
            return parts[-2], parts[-1]
        return "", ""

    # File availability warnings & auto-fallback
    if apk_path and not os.path.exists(apk_path):
        detected = find_release_assets(local_path)
        if detected.get("apk_path") and os.path.exists(detected["apk_path"]):
            logs.append(f"ℹ️ Tự động chuyển đường dẫn APK sang: {detected['apk_path']}")
            apk_path = detected["apk_path"]
        else:
            logs.append(f"⚠️ Không tìm thấy file APK tại: {apk_path}")
    if bin_path and not os.path.exists(bin_path):
        logs.append(f"⚠️ Không tìm thấy file Firmware GC9A01 BIN tại: {bin_path}")
    if oled_bin_path and not os.path.exists(oled_bin_path):
        logs.append(f"⚠️ Không tìm thấy file Firmware OLED BIN tại: {oled_bin_path}")

    # 2. Release on Gitea
    if gitea_auth and gitea_server:
        owner, repo = parse_owner_repo(gitea_remote)
        if not owner or not repo:
            owner, repo = "nas152", "Tdriver"
        
        rel = create_gitea_release(gitea_auth, gitea_server, owner, repo, tag_name, release_name, changelog)
        if rel:
            rel_id = rel.get("id")
            logs.append(f"✅ Đã tạo Release trên Gitea NAS (ID {rel_id})")
            if apk_path and os.path.exists(apk_path):
                asset, err = upload_gitea_asset(gitea_auth, gitea_server, owner, repo, rel_id, apk_path, custom_name=os.path.basename(apk_path))
                if asset:
                    gitea_apk_url = asset.get("browser_download_url", "")
                    logs.append(f"📦 Đã đính kèm Android APK lên Gitea Release: {gitea_apk_url}")
                else:
                    logs.append(f"❌ Lỗi upload APK lên Gitea Release: {err or 'Lỗi không xác định'}")
            if bin_path and os.path.exists(bin_path):
                asset, err = upload_gitea_asset(gitea_auth, gitea_server, owner, repo, rel_id, bin_path, custom_name="firmware.bin")
                if asset:
                    gitea_bin_url = asset.get("browser_download_url", "")
                    logs.append(f"📦 Đã đính kèm Firmware GC9A01 BIN lên Gitea Release: {gitea_bin_url}")
                else:
                    logs.append(f"❌ Lỗi upload Firmware GC9A01 BIN lên Gitea Release: {err or 'Lỗi không xác định'}")
            if oled_bin_path and os.path.exists(oled_bin_path):
                # Upload OLED bin with custom name firmware_oled.bin to avoid overwriting GC9A01 firmware.bin
                asset, err = upload_gitea_asset(gitea_auth, gitea_server, owner, repo, rel_id, oled_bin_path, custom_name="firmware_oled.bin")
                if asset:
                    gitea_oled_bin_url = asset.get("browser_download_url", "")
                    logs.append(f"📦 Đã đính kèm Firmware OLED BIN lên Gitea Release: {gitea_oled_bin_url}")
                else:
                    logs.append(f"❌ Lỗi upload Firmware OLED BIN lên Gitea Release: {err or 'Lỗi không xác định'}")
        else:
            logs.append(f"⚠️ Không thể tạo/tìm Release trên Gitea cho repo {owner}/{repo}")

    # 3. Release on GitHub
    if github_token:
        owner, repo = parse_owner_repo(github_remote)
        if owner and repo:
            rel = create_github_release(github_token, owner, repo, tag_name, release_name, changelog)
            if rel:
                rel_id = rel.get("id")
                logs.append(f"✅ Release GitHub Sẵn Sàng (ID {rel_id})")
                if apk_path and os.path.exists(apk_path):
                    asset, err = upload_github_asset(github_token, owner, repo, rel_id, apk_path, custom_name=os.path.basename(apk_path))
                    if asset:
                        github_apk_url = asset.get("browser_download_url", "")
                        logs.append(f"📦 Đã upload APK lên GitHub: {github_apk_url}")
                    else:
                        logs.append(f"❌ Lỗi upload APK lên GitHub Release: {err or 'Lỗi không xác định'}")
                if bin_path and os.path.exists(bin_path):
                    asset, err = upload_github_asset(github_token, owner, repo, rel_id, bin_path, custom_name="firmware.bin")
                    if asset:
                        github_bin_url = asset.get("browser_download_url", "")
                        logs.append(f"📦 Đã upload Firmware GC9A01 BIN lên GitHub: {github_bin_url}")
                    else:
                        logs.append(f"❌ Lỗi upload Firmware GC9A01 BIN lên GitHub Release: {err or 'Lỗi không xác định'}")
                if oled_bin_path and os.path.exists(oled_bin_path):
                    asset, err = upload_github_asset(github_token, owner, repo, rel_id, oled_bin_path, custom_name="firmware_oled.bin")
                    if asset:
                        github_oled_bin_url = asset.get("browser_download_url", "")
                        logs.append(f"📦 Đã upload Firmware OLED BIN lên GitHub: {github_oled_bin_url}")
                    else:
                        logs.append(f"❌ Lỗi upload Firmware OLED BIN lên GitHub Release: {err or 'Lỗi không xác định'}")
            else:
                logs.append(f"⚠️ Không thể tạo/tìm Release trên GitHub cho repo {owner}/{repo}")

    # 4. Update final asset URLs inside version.json and push
    # Ưu tiên URL NAS trực tiếp HTTPS (hoặc GitHub nếu có cấu hình)
    nas_apk_url = "https://alert.nas152.duckdns.org/downloads/app-debug.apk"
    nas_bin_url = "https://alert.nas152.duckdns.org/downloads/firmware.bin"
    nas_oled_bin_url = "https://alert.nas152.duckdns.org/downloads/firmware_oled.bin"

    final_apk_url = github_apk_url or nas_apk_url if (apk_path and os.path.exists(apk_path)) else (gitea_apk_url or "")
    final_bin_url = github_bin_url or nas_bin_url if (bin_path and os.path.exists(bin_path)) else (gitea_bin_url or "")
    final_oled_bin_url = github_oled_bin_url or nas_oled_bin_url if (oled_bin_path and os.path.exists(oled_bin_path)) else (gitea_oled_bin_url or final_bin_url)
    
    if local_path and os.path.exists(local_path):
        version_data = {
            "app": {
                "versionCode": int(app_ver_code),
                "versionName": tag_name.lstrip("v"),
                "apkUrl": final_apk_url,
                "changelog": changelog
            },
            "firmware": {
                "versionCode": int(fw_ver_code),
                "versionName": tag_name.lstrip("v"),
                "binUrl": final_bin_url,
                "oledBinUrl": final_oled_bin_url,
                "changelog": changelog
            },
            "firmware_oled": {
                "versionCode": int(fw_ver_code),
                "versionName": tag_name.lstrip("v"),
                "binUrl": final_oled_bin_url,
                "changelog": changelog
            }
        }
        v_path = os.path.join(local_path, "version.json")
        with open(v_path, "w", encoding="utf-8") as f:
            json.dump(version_data, f, ensure_ascii=False, indent=2)
        logs.append(f"📄 Đã cập nhật URL chính thức vào version.json")
        
        try:
            git_stage_file(local_path, "version.json")
            git_commit(local_path, f"chore(ota): update release asset URLs in version.json for {tag_name}")
            git_push(local_path)
            logs.append("🚀 Đã push version.json hoàn chỉnh lên tất cả Remote Git")
        except Exception:
            pass

        # Sync version.json và toàn bộ file APK/BIN trực tiếp sang NAS Fusion Engine
        try:
            if sync_version_to_nas(version_data, apk_path=apk_path, bin_path=bin_path, oled_bin_path=oled_bin_path):
                logs.append("📡 Đã đồng bộ version.json & file nhị phân OTA sang máy chủ NAS (https://alert.nas152.duckdns.org)")
        except Exception as e:
            logs.append(f"⚠️ Cảnh báo đồng bộ NAS: {e}")

    return jsonify({"success": True, "logs": logs, "apk_url": final_apk_url, "bin_url": final_bin_url, "oled_bin_url": final_oled_bin_url})


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
