"""Git Smart Manager — Flask application serving both REST API and frontend."""

import os
import sys
import json
import uuid
import logging
import webbrowser
from pathlib import Path
from threading import Timer

from flask import Flask, render_template, request, jsonify, send_file, Response, stream_with_context

from gsm.config import DATA_DIR, APP_NAME, APP_VERSION, DEFAULT_PORT
from gsm.storage import (
    load_projects, save_projects, load_settings, save_settings,
    get_token, set_token, update_project_ota,
    get_saved_git_authors, save_git_author_profile, delete_saved_git_author,
)
from gsm.git_utils import (
    is_git_repo, get_status, get_recent_commits, clone_repo,
    open_in_fork, setup_multi_push,
    git_init, git_stage_file, git_unstage_file, git_stage_all, git_stage_all_progress,
    git_commit, git_push, git_push_all, git_pull, git_fetch, git_push_tag, git_unlock, git_check_index_lock,
    git_branch_list, git_branch_create, git_branch_delete, git_branch_switch, git_branch_rename,
    git_merge, git_stash_push, git_stash_pop, git_stash_list, git_stash_drop,
    git_log_detailed, git_diff, git_remote_list, git_remote_add, git_remote_remove, git_set_or_add_remote,
    git_reset, git_tag_list, git_tag_create, git_tag_delete,
    git_init, git_custom_command, git_tree, git_read_file, git_log_graph,
    git_archive_zip, git_diff_parsed, git_resolve_conflict,
    git_get_author, git_set_author, git_get_suggested_authors,
)
from gsm.api_utils import (
    check_github_token, check_gitea_token, check_gitea_password,
    create_github_repo, create_gitea_repo, create_gitea_release,
    list_gitea_repos, list_gitea_repos_basic_auth, list_github_repos,
    upload_gitea_asset, create_github_release, upload_github_asset,
)
from gsm.ota_utils import find_release_assets, sync_version_to_nas, publish_two_repo_ota

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
        elif github_url: git_set_or_add_remote(full_path, "origin", github_url)
        elif gitea_url: git_set_or_add_remote(full_path, "origin", gitea_url)
    except Exception: pass

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


@app.route("/api/projects/<project_id>/toggle-ota", methods=["POST"])
def api_project_toggle_ota(project_id):
    data = request.get_json(silent=True) or {}
    enable = data.get("enable_ota")
    if enable is None:
        p = _find_project(project_id)
        if not p: return jsonify({"error": "Không tìm thấy"}), 404
        enable = not p.get("enable_ota", False)
    ok = update_project_ota(project_id, enable)
    if not ok:
        return jsonify({"error": "Không tìm thấy"}), 404
    return jsonify({"success": True, "enable_ota": enable})


@app.route("/api/projects/<project_id>/init-ota-template", methods=["POST"])
def api_project_init_ota_template(project_id):
    project = _find_project(project_id)
    if not project: return jsonify({"error": "Không tìm thấy dự án"}), 404
    path = project.get("path", "")
    if not path or not os.path.isdir(path): return jsonify({"error": "Thư mục dự án không tồn tại"}), 400

    created = []
    version_file = os.path.join(path, "version.json")
    if not os.path.exists(version_file):
        sample_version = {
            "app": {
                "versionCode": 1,
                "versionName": "1.0.0",
                "apkUrl": "https://raw.githubusercontent.com/<user>/<repo>/releases/download/v1.0.0/app-release.apk",
                "changelog": "Khởi tạo phiên bản đầu tiên"
            },
            "firmware": {
                "versionCode": 1,
                "versionName": "1.0.0",
                "binUrl": "https://raw.githubusercontent.com/<user>/<repo>/releases/download/v1.0.0/firmware.bin",
                "oledBinUrl": "",
                "changelog": "Khởi tạo firmware ban đầu"
            }
        }
        with open(version_file, "w", encoding="utf-8") as f:
            json.dump(sample_version, f, indent=2, ensure_ascii=False)
        created.append("version.json")

    guide_file = os.path.join(path, "OTA_GUIDE.md")
    if not os.path.exists(guide_file):
        guide_content = """# 🚀 Hướng Dẫn Tích Hợp Cập Nhật OTA (Firmware & Android App)

Tài liệu này hướng dẫn cách kết nối và tạo hệ thống tự động cập nhật Firmware OTA (ESP32) và Android App từ xa thông qua GitHub/Gitea Release.

---

## 1. Cơ Chế Hoạt Động (Architecture)
1. **Lưu trữ Metadata (`version.json`)**: File `version.json` đặt tại root của repository hoặc trên hosting (GitHub Raw, Gitea Raw, NAS).
2. **Kiểm tra phiên bản**:
   - Thiết bị (ESP32) hoặc App (Android) định kỳ hoặc khi khởi động sẽ tải file `version.json`.
   - So sánh `versionCode` trên server với `versionCode` hiện tại trong thiết bị.
3. **Thực thi cập nhật**:
   - Nếu `server.versionCode > local.versionCode`: Thiết bị tải file `.bin` (firmware) hoặc `.apk` (app) về và nạp vào bộ nhớ.

---

## 2. Cấu Trúc File `version.json` Mẫu
```json
{
  "app": {
    "versionCode": 1,
    "versionName": "1.0.0",
    "apkUrl": "https://<domain>/releases/download/v1.0.0/app-release.apk",
    "changelog": "Khởi tạo phiên bản đầu tiên"
  },
  "firmware": {
    "versionCode": 1,
    "versionName": "1.0.0",
    "binUrl": "https://<domain>/releases/download/v1.0.0/firmware.bin",
    "changelog": "Khởi tạo firmware"
  }
}
```

---

## 3. Mã Nguồn Mẫu Cho ESP32 (Arduino / PlatformIO - WiFi HTTP OTA)

Thêm các thư viện cần thiết vào `platformio.ini`:
```ini
lib_deps =
    bblanchon/ArduinoJson @ ^6.21.3
```

Trong file C++ (`main.cpp`):
```cpp
#include <WiFi.h>
#include <HTTPClient.h>
#include <HTTPUpdate.h>
#include <ArduinoJson.h>

const int CURRENT_FW_VERSION = 1;
const char* VERSION_CHECK_URL = "https://raw.githubusercontent.com/<user>/<repo>/main/version.json";

void checkAndPerformOTA() {
    if (WiFi.status() != WL_CONNECTED) return;

    HTTPClient http;
    http.begin(VERSION_CHECK_URL);
    int httpCode = http.GET();

    if (httpCode == HTTP_CODE_OK) {
        String payload = http.getString();
        DynamicJsonDocument doc(1024);
        deserializeJson(doc, payload);

        int remoteVer = doc["firmware"]["versionCode"];
        const char* binUrl = doc["firmware"]["binUrl"];

        if (remoteVer > CURRENT_FW_VERSION && binUrl != nullptr && strlen(binUrl) > 0) {
            Serial.printf("Phat hien ban moi: v%d -> v%d. Tien hanh nap OTA...\\n", CURRENT_FW_VERSION, remoteVer);
            WiFiClient client;
            httpUpdate.setLedPin(2, LOW); // Đèn báo nạp
            t_httpUpdate_return ret = httpUpdate.update(client, binUrl);

            switch (ret) {
                case HTTP_UPDATE_FAILED:
                    Serial.printf("Loi OTA: (%d): %s\\n", httpUpdate.getLastError(), httpUpdate.getLastErrorString().c_str());
                    break;
                case HTTP_UPDATE_NO_UPDATES:
                    Serial.println("Khong co ban cap nhat moi.");
                    break;
                case HTTP_UPDATE_OK:
                    Serial.println("Cap nhat thanh cong! Dang khoi dong lai...");
                    break;
            }
        }
    }
    http.end();
}
```

---

## 4. Mã Nguồn Mẫu Cho Android (Kotlin)
Đọc `version.json`, so sánh `BuildConfig.VERSION_CODE`, và mở intent cài đặt APK qua `FileProvider`:
```kotlin
fun checkAppUpdate(context: Context, versionUrl: String) {
    CoroutineScope(Dispatchers.IO).launch {
        try {
            val jsonStr = URL(versionUrl).readText()
            val jsonObj = JSONObject(jsonStr)
            val appObj = jsonObj.getJSONObject("app")
            val remoteVerCode = appObj.getInt("versionCode")
            val apkUrl = appObj.getString("apkUrl")
            val changelog = appObj.optString("changelog")

            val currentVerCode = context.packageManager.getPackageInfo(context.packageName, 0).versionCode
            if (remoteVerCode > currentVerCode) {
                withContext(Dispatchers.Main) {
                    // Hiển thị thông báo & tải APK về cài đặt
                }
            }
        } catch (e: Exception) {
            e.printStackTrace()
        }
    }
}
```
"""
        with open(guide_file, "w", encoding="utf-8") as f:
            f.write(guide_content)
        created.append("OTA_GUIDE.md")

    return jsonify({
        "success": True,
        "created": created,
        "message": f"Đã khởi tạo thành công: {', '.join(created)}" if created else "Các file version.json và OTA_GUIDE.md đã tồn tại sẵn trong dự án."
    })


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


@app.route("/api/projects/<project_id>/push-all", methods=["POST"])
def api_push_all(project_id):
    project = _find_project(project_id)
    if not project: return jsonify({"error": "Không tìm thấy"}), 404
    path = project.get("path", "")
    if not path or not os.path.isdir(path): return jsonify({"error": "Thư mục không tồn tại"}), 400
    if not is_git_repo(path): return jsonify({"error": "Chưa phải git repo"}), 400

    # Ensure multi-push is configured with token if project has both remotes
    github_url = project.get("github_remote", "")
    gitea_url = project.get("gitea_remote", "")
    if not github_url or not gitea_url:
        existing_remotes = git_remote_list(path)
        for rm in existing_remotes:
            u = rm.get("url", "")
            if "github.com" in u and not github_url:
                github_url = u
            elif ("gitea" in u or ":3002" in u or "nas152" in u) and not gitea_url:
                gitea_url = u

    if github_url and gitea_url:
        try:
            setup_multi_push(path, github_url, gitea_url)
        except Exception as e_mp:
            log.warning(f"setup_multi_push error in push_all: {e_mp}")

    data = request.get_json(silent=True) or {}
    force = data.get("force", False)
    res = git_push_all(path, force=force)
    return jsonify(res), (200 if res.get("success") else 400)


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
        "stage_file":    lambda: _git_result(git_stage_file(path, data.get("file", ""))),
        "unstage_file":  lambda: _git_result(git_unstage_file(path, data.get("file", ""))),
        "stage_all":     lambda: _git_result(git_stage_all(path)),
        "commit":        lambda: _git_result(git_commit(path, data.get("message", ""))),
        "push":          lambda: _git_result(git_push(path, data.get("remote", "origin"), data.get("branch", ""), data.get("force", False))),
        "push_all":      lambda: _git_result(git_push_all(path, data.get("force", False))),
        "pull":          lambda: _git_result(git_pull(path, data.get("remote", "origin"), data.get("branch", ""))),
        "fetch":         lambda: _git_result(git_fetch(path, data.get("remote", ""))),
        "unlock":        lambda: _git_result(git_unlock(path)),
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


@app.route("/api/projects/<project_id>/stage-all-stream", methods=["POST"])
def api_stage_all_stream(project_id):
    project, err = _require_project(project_id, require_git=True)
    if err: return jsonify({"error": err, "success": False}), 400
    path = project["path"]

    def generate():
        for event in git_stage_all_progress(path):
            yield json.dumps(event) + "\n"

    return Response(stream_with_context(generate()), mimetype="application/x-ndjson")


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

        from gsm.git_utils import setup_multi_push, git_set_or_add_remote
        if github_url and gitea_url:
            try: setup_multi_push(path, github_url, gitea_url)
            except: pass
        elif github_url:
            git_set_or_add_remote(path, "origin", github_url)
        elif gitea_url:
            git_set_or_add_remote(path, "origin", gitea_url)

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
    from gsm.git_utils import git_remote_list, setup_multi_push, git_push, git_set_or_add_remote
    existing_remotes = git_remote_list(path)
    remote_names = [rm["name"] for rm in existing_remotes]
    origin_remote = next((rm for rm in existing_remotes if rm["name"] == "origin"), None)

    if platform == "github":
        token = get_token("github_token")
        if not token: return jsonify({"error": "Chưa cấu hình GitHub token. Hãy vào ⚙️ Cài đặt -> Dịch vụ & Token để lưu Token."}), 400
        clone_url = create_github_repo(token, name, description, private, auto_init=False)
        if not clone_url: return jsonify({"error": "Tạo GitHub repo thất bại. Hãy kiểm tra lại kết nối mạng hoặc quyền của Token."}), 500

        # Nếu origin đã tồn tại và là Gitea/NAS
        if origin_remote and ("gitea" in origin_remote["url"].lower() or "3002" in origin_remote["url"] or "nas152" in origin_remote["url"].lower() or "192.168." in origin_remote["url"]):
            try:
                setup_multi_push(path, clone_url, origin_remote["url"])
            except Exception:
                git_set_or_add_remote(path, "github", clone_url)
        else:
            git_set_or_add_remote(path, "origin", clone_url)

    elif platform == "gitea":
        token = get_token("gitea_token")
        server_url = settings.get("gitea_server_url", "")
        if not token or not server_url: return jsonify({"error": "Chưa cấu hình Gitea trong Cài đặt"}), 400
        clone_url = create_gitea_repo(token, server_url, name, description, private, auto_init=False)
        if not clone_url: return jsonify({"error": "Tạo Gitea repo thất bại. Hãy kiểm tra URL máy chủ hoặc Token."}), 500

        if origin_remote and "github" in origin_remote["url"].lower():
            try:
                setup_multi_push(path, origin_remote["url"], clone_url)
            except Exception:
                git_set_or_add_remote(path, "gitea", clone_url)
        else:
            git_set_or_add_remote(path, "origin", clone_url)
    else:
        return jsonify({"error": "Platform phải là 'github', 'gitea' hoặc 'both'"}), 400

    projects = load_projects()
    for p in projects:
        if p["id"] == project_id:
            if platform == "github": p["github_remote"] = clone_url
            elif platform == "gitea": p["gitea_remote"] = clone_url
            break
    save_projects(projects)

    # Tự động push nếu có yêu cầu
    push_msg = ""
    if data.get("push_now", False):
        try:
            push_res = git_push(path)
            if not push_res.get("success"):
                push_err = (push_res.get("error") or push_res.get("stderr") or "").strip()
                if push_err:
                    push_msg = f" (Đẩy code gặp lỗi: {push_err})"
        except Exception as e_push:
            log.warning(f"Push after create remote error: {e_push}")
            push_msg = f" (Không thể tự động đẩy: {e_push})"

    return jsonify({"success": True, "message": f"Đã kết nối repo trên {platform} thành công!{push_msg}", "clone_url": clone_url})


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


@app.route("/api/projects/<project_id>/github-release", methods=["POST"])
def api_create_github_release(project_id):
    from urllib.parse import urlparse
    project = _find_project(project_id)
    if not project: return jsonify({"error": "Không tìm thấy"}), 404
    github_url = project.get("github_remote", "")
    if not github_url: return jsonify({"error": "Chưa có remote GitHub"}), 400

    token = get_token("github_token") or ""
    if not token: return jsonify({"error": "Chưa cấu hình GitHub token"}), 400

    parsed = urlparse(github_url)
    parts = parsed.path.strip("/").rstrip(".git").split("/")
    if len(parts) < 2: return jsonify({"error": "URL remote không hợp lệ"}), 400
    owner, repo = parts[-2], parts[-1]

    data = request.get_json(force=True) or {}
    tag_name = data.get("tag_name", "")
    name = data.get("name", tag_name)
    body = data.get("body", "")
    if not tag_name: return jsonify({"error": "Thiếu tên tag"}), 400

    result = create_github_release(token, owner, repo, tag_name, name, body)
    if result:
        return jsonify({"success": True, "release": result, "html_url": result.get("html_url", "")})
    return jsonify({"error": "Tạo release trên GitHub thất bại"}), 400


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
    settings["saved_git_authors"] = get_saved_git_authors()
    settings["git_author"] = git_get_author()
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

    # If git author info is also provided
    git_name = data.get("git_name", "").strip()
    git_email = data.get("git_email", "").strip()
    git_scope = data.get("git_scope", "global").strip()
    project_path = data.get("project_path", "").strip()
    if git_name and git_email:
        git_set_author(git_name, git_email, scope=git_scope, project_path=project_path)
        if data.get("save_author_profile", True):
            save_git_author_profile(git_name, git_email)

    return jsonify({"message": "Đã lưu cài đặt"})


@app.route("/api/git/author", methods=["GET"])
def api_get_git_author():
    project_path = request.args.get("project_path", "").strip()
    author = git_get_author(project_path)
    saved = get_saved_git_authors()

    # Find suggestions from known project histories
    projects = load_projects()
    paths = [p.get("path") for p in projects if p.get("path")]
    suggestions = git_get_suggested_authors(paths)

    return jsonify({
        "author": author,
        "saved_authors": saved,
        "suggestions": suggestions,
    })


@app.route("/api/git/author", methods=["POST"])
def api_set_git_author():
    data = request.get_json(force=True) or {}
    name = data.get("name", "").strip()
    email = data.get("email", "").strip()
    scope = data.get("scope", "global").strip()
    project_path = data.get("project_path", "").strip()
    save_profile = data.get("save_profile", True)

    if not name or not email:
        return jsonify({"error": "Tên và email không được để trống"}), 400

    res = git_set_author(name, email, scope=scope, project_path=project_path)
    if not res.get("success"):
        return jsonify({"error": res.get("error", "Lỗi cấu hình Git")}), 400

    if save_profile:
        save_git_author_profile(name, email)

    return jsonify({
        "success": True,
        "message": f"Đã cập nhật tác giả Git ({'Toàn hệ thống' if scope == 'global' else 'Dự án'})",
        "author": git_get_author(project_path),
        "saved_authors": get_saved_git_authors(),
    })


@app.route("/api/git/saved-authors", methods=["POST", "DELETE"])
def api_manage_saved_authors():
    data = request.get_json(force=True) or {}
    if request.method == "POST":
        name = data.get("name", "").strip()
        email = data.get("email", "").strip()
        if not name or not email:
            return jsonify({"error": "Tên và email không được để trống"}), 400
        saved = save_git_author_profile(name, email)
        return jsonify({"success": True, "saved_authors": saved})
    else:  # DELETE
        email = data.get("email", "").strip()
        if not email:
            return jsonify({"error": "Thiếu email để xoá"}), 400
        saved = delete_saved_git_author(email)
        return jsonify({"success": True, "saved_authors": saved})



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
            filetypes = [("ESP32 Firmware BIN (*.bin)", "*.bin"), ("All Files", "*.*")]
            title = "Chọn file Firmware ESP32 (.bin)"
        elif file_type == "oled_bin":
            filetypes = [("ESP32 Firmware BIN (*.bin)", "*.bin"), ("All Files", "*.*")]
            title = "Chọn file Firmware ESP32 phụ / tùy chọn (.bin)"
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
@app.route("/api/projects/<project_id>/release-ota", methods=["POST"])
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
    extra_files = data.get("extra_files", []) or []
    app_ver_code = data.get("app_version_code", 1)
    fw_ver_code = data.get("fw_version_code", 1)
    sync_nas = data.get("sync_nas", True)
    build_apk = data.get("build_apk", True)
    public_repo_url = (data.get("ota_public_repo_url") or data.get("public_repo_url") or project.get("ota_public_repo_url", "")).strip()

    if not tag_name:
        return jsonify({"error": "Thiếu Tag Name (ví dụ: v1.0.1)"}), 400

    # Ghi nhớ ota_public_repo_url vào project settings nếu có thay đổi
    if public_repo_url and project.get("ota_public_repo_url") != public_repo_url:
        project["ota_public_repo_url"] = public_repo_url
        for p in projects:
            if p["id"] == project_id:
                p["ota_public_repo_url"] = public_repo_url
                break
        save_projects(projects)

    logs = []
    local_path = project.get("path", "")
    
    # 1. Stage ALL changes, write version.json, commit ALL files & create tag (Repo 1 - Private)
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
            
            # Đồng bộ trực tiếp vào app/build.gradle.kts nếu có
            tymap_path = os.path.join(local_path, "TYMAP")
            gradle_file = os.path.join(tymap_path, "app", "build.gradle.kts")
            if os.path.exists(gradle_file):
                try:
                    import re
                    with open(gradle_file, "r", encoding="utf-8") as gf:
                        g_content = gf.read()
                    g_content = re.sub(r'versionCode\s*=\s*\d+', f'versionCode = {int(app_ver_code)}', g_content)
                    g_content = re.sub(r'versionName\s*=\s*"[^"]+"', f'versionName = "{tag_name.lstrip("v")}"', g_content)
                    with open(gradle_file, "w", encoding="utf-8") as gf:
                        gf.write(g_content)
                    logs.append(f"📝 Đã đồng bộ build.gradle.kts: versionCode = {app_ver_code}, versionName = \"{tag_name.lstrip('v')}\"")
                except Exception as e_gradle:
                    logs.append(f"⚠️ Không thể cập nhật build.gradle.kts: {e_gradle}")

            # Tự động Build lại APK Android mang chính xác mã phiên bản mới (nếu bật tùy chọn)
            if build_apk and os.path.exists(tymap_path):
                logs.append(f"🔨 Đang tự động biên dịch Android APK cho phiên bản {tag_name}...")
                gradle_cmd = "gradlew.bat assembleDebug" if sys.platform == "win32" else "./gradlew assembleDebug"
                try:
                    res_gradle = subprocess.run(gradle_cmd, shell=True, cwd=tymap_path, capture_output=True, text=True)
                    if res_gradle.returncode == 0:
                        logs.append(f"✅ Đã build APK thành công với mã phiên bản {app_ver_code} ({tag_name})")
                        # Tự động phát hiện file APK mới tạo nếu apk_path chưa có hoặc chưa tồn tại
                        detected = find_release_assets(local_path)
                        if detected.get("apk_path") and os.path.exists(detected["apk_path"]):
                            apk_path = detected["apk_path"]
                            logs.append(f"📦 Đã nhận diện APK mới tại: {apk_path}")
                    else:
                        logs.append(f"⚠️ Cảnh báo biên dịch APK: {res_gradle.stderr[:200] if res_gradle.stderr else res_gradle.stdout[:200]}")
                except Exception as e_build:
                    logs.append(f"⚠️ Không thể chạy build APK: {e_build}")

            git_stage_file(local_path, "version.json")
            git_stage_all(local_path)
            
            try:
                git_commit(local_path, f"release({tag_name}): full update release including version.json")
                logs.append(f"💾 Đã commit toàn bộ file dự án Repo 1 cho phiên bản {tag_name}")
            except Exception:
                pass # If nothing to commit

            try:
                git_tag_create(local_path, tag_name, f"Release {tag_name}")
                logs.append(f"✅ Đã tạo Git Tag cục bộ Repo 1: {tag_name}")
            except Exception:
                pass
                
            git_push(local_path)
            git_push_tag(local_path, tag_name)
            logs.append(f"🚀 Đã push TOÀN BỘ file & Tag {tag_name} lên các Remote Git (Repo 1)")
        except Exception as e:
            logs.append(f"⚠️ Cảnh báo Git commit/push: {str(e)}")

    settings = load_settings()
    github_token = get_token("github_token") or settings.get("github_token", "")

    # 2. XỬ LÝ THEO KIẾN TRÚC 2 REPOSITORY (Nếu người dùng cung cấp URL Repo 2 OTA Public)
    if public_repo_url:
        try:
            two_repo_res = publish_two_repo_ota(
                project_path=local_path,
                public_repo_url=public_repo_url,
                tag_name=tag_name,
                app_ver_code=int(app_ver_code),
                fw_ver_code=int(fw_ver_code),
                changelog=changelog,
                apk_path=apk_path,
                bin_path=bin_path,
                oled_bin_path=oled_bin_path,
                extra_files=extra_files,
                github_token=github_token,
            )
            logs.extend(two_repo_res.get("logs", []))

            # Sync sang NAS nếu bật
            if sync_nas:
                try:
                    nas_ip = settings.get("nas_ip", "192.168.1.114")
                    nas_user = settings.get("nas_user", "nas152")
                    nas_pass = get_token("nas_password") or settings.get("nas_password", "271000")
                    version_payload = {
                        "app": {
                            "versionCode": int(app_ver_code),
                            "versionName": tag_name.lstrip("v"),
                            "apkUrl": two_repo_res.get("apk_url", ""),
                            "apkName": os.path.basename(apk_path) if apk_path else "",
                            "changelog": changelog,
                        },
                        "firmware": {
                            "versionCode": int(fw_ver_code),
                            "versionName": tag_name.lstrip("v"),
                            "binUrl": two_repo_res.get("bin_url", ""),
                            "binName": os.path.basename(bin_path) if bin_path else "firmware.bin",
                            "secondaryBinUrl": two_repo_res.get("oled_bin_url", ""),
                            "oledBinUrl": two_repo_res.get("oled_bin_url", ""),
                            "changelog": changelog,
                        },
                    }
                    if sync_version_to_nas(version_payload, nas_ip=nas_ip, username=nas_user, password=nas_pass, apk_path=apk_path, bin_path=bin_path, oled_bin_path=oled_bin_path):
                        logs.append("📡 Đã đồng bộ version.json & file nhị phân OTA sang máy chủ NAS")
                except Exception as e_nas:
                    logs.append(f"⚠️ Cảnh báo đồng bộ NAS: {e_nas}")

            return jsonify({
                "success": True,
                "logs": logs,
                "public_repo": two_repo_res.get("public_repo", ""),
                "apk_url": two_repo_res.get("apk_url", ""),
                "bin_url": two_repo_res.get("bin_url", ""),
                "oled_bin_url": two_repo_res.get("oled_bin_url", ""),
                "release_id": two_repo_res.get("release_id"),
                "html_url": two_repo_res.get("html_url", ""),
            })
        except Exception as e_2repo:
            logs.append(f"❌ Lỗi quy trình 2 Repo OTA: {str(e_2repo)}")
            return jsonify({"success": False, "error": str(e_2repo), "logs": logs}), 500
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
    bin_filename = os.path.basename(bin_path) if bin_path else "firmware.bin"
    oled_bin_filename = os.path.basename(oled_bin_path) if oled_bin_path else "firmware_secondary.bin"
    if oled_bin_path and bin_path and bin_filename == oled_bin_filename:
        oled_bin_filename = f"secondary_{oled_bin_filename}"

    if bin_path and not os.path.exists(bin_path):
        logs.append(f"⚠️ Không tìm thấy file Firmware BIN tại: {bin_path}")
    if oled_bin_path and not os.path.exists(oled_bin_path):
        logs.append(f"⚠️ Không tìm thấy file Firmware phụ BIN tại: {oled_bin_path}")

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
                asset, err = upload_gitea_asset(gitea_auth, gitea_server, owner, repo, rel_id, bin_path, custom_name=bin_filename)
                if asset:
                    gitea_bin_url = asset.get("browser_download_url", "")
                    logs.append(f"📦 Đã đính kèm Firmware BIN ({bin_filename}) lên Gitea Release: {gitea_bin_url}")
                else:
                    logs.append(f"❌ Lỗi upload Firmware BIN ({bin_filename}) lên Gitea Release: {err or 'Lỗi không xác định'}")
            if oled_bin_path and os.path.exists(oled_bin_path):
                asset, err = upload_gitea_asset(gitea_auth, gitea_server, owner, repo, rel_id, oled_bin_path, custom_name=oled_bin_filename)
                if asset:
                    gitea_oled_bin_url = asset.get("browser_download_url", "")
                    logs.append(f"📦 Đã đính kèm Firmware phụ BIN ({oled_bin_filename}) lên Gitea Release: {gitea_oled_bin_url}")
                else:
                    logs.append(f"❌ Lỗi upload Firmware phụ BIN ({oled_bin_filename}) lên Gitea Release: {err or 'Lỗi không xác định'}")
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
                    asset, err = upload_github_asset(github_token, owner, repo, rel_id, bin_path, custom_name=bin_filename)
                    if asset:
                        github_bin_url = asset.get("browser_download_url", "")
                        logs.append(f"📦 Đã upload Firmware BIN ({bin_filename}) lên GitHub: {github_bin_url}")
                    else:
                        logs.append(f"❌ Lỗi upload Firmware BIN ({bin_filename}) lên GitHub Release: {err or 'Lỗi không xác định'}")
                if oled_bin_path and os.path.exists(oled_bin_path):
                    asset, err = upload_github_asset(github_token, owner, repo, rel_id, oled_bin_path, custom_name=oled_bin_filename)
                    if asset:
                        github_oled_bin_url = asset.get("browser_download_url", "")
                        logs.append(f"📦 Đã upload Firmware phụ BIN ({oled_bin_filename}) lên GitHub: {github_oled_bin_url}")
                    else:
                        logs.append(f"❌ Lỗi upload Firmware phụ BIN ({oled_bin_filename}) lên GitHub Release: {err or 'Lỗi không xác định'}")
                if extra_files and isinstance(extra_files, list):
                    for ef in extra_files:
                        ef_p = ef.get("path", "").strip() if isinstance(ef, dict) else str(ef).strip()
                        ef_lbl = ef.get("label", "").strip() if isinstance(ef, dict) else ""
                        if ef_p and os.path.exists(ef_p):
                            ef_name = os.path.basename(ef_p)
                            asset, err = upload_github_asset(github_token, owner, repo, rel_id, ef_p, custom_name=ef_name)
                            if asset:
                                logs.append(f"📦 Đã upload file bổ sung ({ef_name} - {ef_lbl or 'Tùy chọn'}) lên GitHub: {asset.get('browser_download_url')}")
                            else:
                                logs.append(f"❌ Lỗi upload file bổ sung ({ef_name}) lên GitHub: {err or 'Lỗi'}")
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
                "apkName": os.path.basename(apk_path) if apk_path else "",
                "changelog": changelog
            },
            "firmware": {
                "versionCode": int(fw_ver_code),
                "versionName": tag_name.lstrip("v"),
                "binUrl": final_bin_url,
                "binName": bin_filename if bin_path else "firmware.bin",
                "secondaryBinUrl": final_oled_bin_url if oled_bin_path else "",
                "secondaryBinName": oled_bin_filename if oled_bin_path else "",
                "oledBinUrl": final_oled_bin_url,
                "changelog": changelog
            },
            "firmware_oled": {
                "versionCode": int(fw_ver_code),
                "versionName": tag_name.lstrip("v"),
                "binUrl": final_oled_bin_url,
                "binName": oled_bin_filename if oled_bin_path else "firmware_oled.bin",
                "changelog": changelog
            },
            "assets": []
        }
        if extra_files and isinstance(extra_files, list):
            for ef in extra_files:
                ef_p = ef.get("path", "").strip() if isinstance(ef, dict) else str(ef).strip()
                ef_lbl = ef.get("label", "").strip() if isinstance(ef, dict) else ""
                if ef_p and os.path.exists(ef_p):
                    version_data["assets"].append({
                        "name": os.path.basename(ef_p),
                        "label": ef_lbl or os.path.basename(ef_p),
                        "path": ef_p
                    })
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

        # Sync version.json và toàn bộ file APK/BIN trực tiếp sang NAS Fusion Engine nếu bật
        if sync_nas:
            try:
                nas_ip = settings.get("nas_ip", "192.168.1.114")
                nas_user = settings.get("nas_user", "nas152")
                nas_pass = get_token("nas_password") or settings.get("nas_password", "271000")
                if sync_version_to_nas(version_data, nas_ip=nas_ip, username=nas_user, password=nas_pass, apk_path=apk_path, bin_path=bin_path, oled_bin_path=oled_bin_path):
                    logs.append("📡 Đã đồng bộ version.json & file nhị phân OTA sang máy chủ NAS (https://alert.nas152.duckdns.org)")
            except Exception as e:
                logs.append(f"⚠️ Cảnh báo đồng bộ NAS: {e}")
        else:
            logs.append("ℹ️ Đã bỏ qua bước đồng bộ trực tiếp lên máy chủ NAS theo tùy chọn người dùng.")

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
