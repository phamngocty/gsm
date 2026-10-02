import unittest
from unittest.mock import patch, MagicMock
import sys
import os
import json

# Add parent directory to sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from gsm.api_utils import list_github_repos


class TestGitHubReposAPI(unittest.TestCase):

    @patch("gsm.api_utils.requests.get")
    def test_list_github_repos_success(self, mock_get):
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = [
            {
                "id": 12345,
                "name": "my-cool-project",
                "full_name": "octocat/my-cool-project",
                "description": "A demo repository",
                "clone_url": "https://github.com/octocat/my-cool-project.git",
                "private": False,
                "default_branch": "main",
                "updated_at": "2026-09-10T10:00:00Z",
            }
        ]
        mock_get.return_value = mock_response

        repos = list_github_repos("fake_token_123")
        self.assertEqual(len(repos), 1)
        self.assertEqual(repos[0]["name"], "my-cool-project")
        self.assertEqual(repos[0]["full_name"], "octocat/my-cool-project")
        self.assertEqual(repos[0]["clone_url"], "https://github.com/octocat/my-cool-project.git")
        self.assertFalse(repos[0]["private"])

    @patch("app.get_token")
    @patch("app.list_github_repos")
    def test_api_github_repos_endpoint(self, mock_list, mock_get_token):
        import app
        mock_get_token.return_value = "token_abc"
        mock_list.return_value = [{"id": 1, "name": "repo1"}]

        client = app.app.test_client()
        res = client.get("/api/github/repos")
        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        self.assertIn("repos", data)
        self.assertEqual(len(data["repos"]), 1)
        self.assertEqual(data["repos"][0]["name"], "repo1")


class TestGitArchive(unittest.TestCase):

    def test_git_archive_zip_success(self):
        import tempfile
        import zipfile
        from gsm.git_utils import git_archive_zip

        repo_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
        with tempfile.NamedTemporaryFile(suffix=".zip", delete=False) as tmp:
            tmp_path = tmp.name

        try:
            result = git_archive_zip(repo_dir, "HEAD", tmp_path)
            self.assertTrue(result["success"])
            self.assertTrue(os.path.exists(tmp_path))
            self.assertGreater(os.path.getsize(tmp_path), 0)
            with zipfile.ZipFile(tmp_path, "r") as z:
                names = z.namelist()
                self.assertIn("app.py", names)
        finally:
            if os.path.exists(tmp_path):
                os.remove(tmp_path)

    @patch("app.load_projects")
    def test_api_archive_zip_endpoint(self, mock_load_projects):
        import app
        repo_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
        mock_load_projects.return_value = [{"id": "test_p1", "name": "gsm_test", "path": repo_dir}]

        client = app.app.test_client()
        res = client.get("/api/projects/test_p1/archive-zip?ref=HEAD")
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.mimetype, "application/zip")
        self.assertIn("attachment", res.headers.get("Content-Disposition", ""))


class TestDiffAndConflict(unittest.TestCase):

    def test_git_diff_parsed(self):
        from gsm.git_utils import git_diff_parsed
        repo_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
        # Test with HEAD~1 vs HEAD
        diff_lines = git_diff_parsed(repo_dir, commit_hash="HEAD")
        self.assertIsInstance(diff_lines, list)
        if diff_lines:
            first = diff_lines[0]
            self.assertIn("type", first)
            self.assertIn("text", first)

    def test_git_resolve_conflict_interface(self):
        from gsm.git_utils import git_resolve_conflict
        repo_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
        # Non-existent file should return a clean error without crashing
        res = git_resolve_conflict(repo_dir, "non_existent_file.txt", "ours")
        self.assertIn("success", res)

    @patch("app.load_projects")
    def test_api_diff_detail_endpoint(self, mock_load_projects):
        import app
        repo_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
        mock_load_projects.return_value = [{"id": "test_p1", "name": "gsm_test", "path": repo_dir}]

        client = app.app.test_client()
        res = client.get("/api/projects/test_p1/diff-detail?commit=HEAD")
        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        self.assertIsInstance(data, list)


class TestOtaDecoupling(unittest.TestCase):

    @patch("gsm.storage.save_projects")
    @patch("gsm.storage.load_projects")
    def test_update_project_ota(self, mock_load, mock_save):
        from gsm.storage import update_project_ota
        mock_load.return_value = [{"id": "p1", "name": "proj1", "enable_ota": False}]
        
        ok = update_project_ota("p1", True)
        self.assertTrue(ok)
        mock_save.assert_called_once()
        saved_list = mock_save.call_args[0][0]
        self.assertTrue(saved_list[0]["enable_ota"])

    @patch("app.update_project_ota")
    def test_toggle_ota_endpoint(self, mock_update_ota):
        import app
        mock_update_ota.return_value = True
        client = app.app.test_client()
        res = client.post("/api/projects/p1/toggle-ota", json={"enable_ota": True})
        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        self.assertTrue(data.get("success"))
        self.assertTrue(data.get("enable_ota"))

    @patch("app.create_github_release")
    @patch("app.get_token")
    @patch("app.load_projects")
    def test_api_github_release_endpoint(self, mock_load, mock_get_token, mock_create_release):
        import app
        mock_load.return_value = [{
            "id": "p1",
            "name": "proj1",
            "github_remote": "https://github.com/octocat/my-project.git"
        }]
        mock_get_token.return_value = "ghp_fake123"
        mock_create_release.return_value = {
            "id": 99,
            "tag_name": "v1.0.0",
            "html_url": "https://github.com/octocat/my-project/releases/tag/v1.0.0"
        }

        client = app.app.test_client()
        res = client.post("/api/projects/p1/github-release", json={
            "tag_name": "v1.0.0",
            "name": "Release v1.0.0",
            "body": "Changelog details"
        })
        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        self.assertTrue(data.get("success"))
        self.assertEqual(data["release"]["tag_name"], "v1.0.0")

    @patch("app.load_projects")
    def test_api_archive_zip_alias(self, mock_load_projects):
        import app
        repo_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
        mock_load_projects.return_value = [{"id": "test_p1", "name": "gsm_test", "path": repo_dir}]

        client = app.app.test_client()
        res = client.get("/api/git/archive-zip?id=test_p1&ref=HEAD")
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.mimetype, "application/zip")

    @patch("app.load_projects")
    def test_api_init_ota_template_endpoint(self, mock_load_projects):
        import app
        import tempfile
        import shutil

        temp_dir = tempfile.mkdtemp()
        try:
            mock_load_projects.return_value = [{"id": "p_temp", "name": "temp_proj", "path": temp_dir}]
            client = app.app.test_client()
            res = client.post("/api/projects/p_temp/init-ota-template")
            self.assertEqual(res.status_code, 200)
            data = res.get_json()
            self.assertTrue(data.get("success"))
            self.assertIn("version.json", data.get("created", []))
            self.assertIn("OTA_GUIDE.md", data.get("created", []))

            # Verify files actually exist on disk
            self.assertTrue(os.path.exists(os.path.join(temp_dir, "version.json")))
            self.assertTrue(os.path.exists(os.path.join(temp_dir, "OTA_GUIDE.md")))
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)

    @patch("app.sync_version_to_nas")
    @patch("app.upload_gitea_asset")
    @patch("app.create_gitea_release")
    @patch("app.load_settings")
    @patch("app.get_token")
    @patch("app.load_projects")
    def test_api_ota_release_options_and_auto_detection(self, mock_load, mock_get_token, mock_settings, mock_create_rel, mock_upload_asset, mock_sync_nas):
        import app
        import tempfile
        import shutil
        import json

        temp_dir = tempfile.mkdtemp()
        try:
            mock_load.return_value = [{
                "id": "p_ota_test",
                "name": "ota_test",
                "path": temp_dir,
                "gitea_remote": "http://192.168.1.114:3002/nas152/ota_test.git"
            }]
            mock_get_token.return_value = "fake_tok"
            mock_settings.return_value = {"gitea_server": "http://192.168.1.114:3002"}
            mock_create_rel.return_value = {"id": 101}
            mock_upload_asset.return_value = ({"browser_download_url": "http://download/test.bin"}, None)
            mock_sync_nas.return_value = True

            client = app.app.test_client()
            res = client.post("/api/projects/p_ota_test/ota-release", json={
                "tag_name": "v1.0.2",
                "changelog": "Test update",
                "app_version_code": 2,
                "fw_version_code": 2,
                "sync_nas": False,
                "build_apk": False
            })
            self.assertEqual(res.status_code, 200)
            data = res.get_json()
            self.assertTrue(data.get("success"))
            # When sync_nas is False, sync_version_to_nas should not be called
            mock_sync_nas.assert_not_called()

            # Verify version.json written
            v_file = os.path.join(temp_dir, "version.json")
            self.assertTrue(os.path.exists(v_file))
            with open(v_file, "r", encoding="utf-8") as f:
                v_content = json.load(f)
            self.assertEqual(v_content["app"]["versionCode"], 2)
            self.assertEqual(v_content["firmware"]["versionCode"], 2)
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)

    @patch("gsm.ota_utils.sync_version_to_nas")
    @patch("app.upload_gitea_asset")
    @patch("app.create_gitea_release")
    @patch("app.load_settings")
    @patch("app.get_token")
    @patch("app.load_projects")
    def test_arbitrary_bin_detection_and_release(self, mock_load, mock_get_token, mock_settings, mock_create_rel, mock_upload_asset, mock_sync_nas):
        import app
        from gsm.ota_utils import find_release_assets
        import tempfile
        import shutil
        import json

        temp_dir = tempfile.mkdtemp()
        try:
            # Create arbitrary bin files
            bin1 = os.path.join(temp_dir, "custom_sensor.bin")
            bin2 = os.path.join(temp_dir, "display_module.bin")
            with open(bin1, "wb") as f:
                f.write(b"firmware_content_1")
            with open(bin2, "wb") as f:
                f.write(b"firmware_content_2")

            # 1. Test detection
            detected = find_release_assets(temp_dir)
            self.assertTrue(detected["bin_path"].endswith(".bin"))
            self.assertTrue(detected["oled_bin_path"].endswith(".bin"))
            self.assertNotEqual(detected["bin_path"], detected["oled_bin_path"])

            # 2. Test release with arbitrary bin files
            mock_load.return_value = [{
                "id": "p_ota_custom",
                "name": "ota_custom",
                "path": temp_dir,
                "gitea_remote": "http://192.168.1.114:3002/nas152/ota_custom.git"
            }]
            mock_get_token.return_value = "fake_tok"
            mock_settings.return_value = {"gitea_server": "http://192.168.1.114:3002"}
            mock_create_rel.return_value = {"id": 202}
            mock_upload_asset.return_value = ({"browser_download_url": "http://download/asset"}, None)

            client = app.app.test_client()
            res = client.post("/api/projects/p_ota_custom/ota-release", json={
                "tag_name": "v3.0.0",
                "changelog": "Arbitrary bin test",
                "bin_path": bin1,
                "oled_bin_path": bin2,
                "app_version_code": 3,
                "fw_version_code": 3,
                "sync_nas": False,
                "build_apk": False
            })
            self.assertEqual(res.status_code, 200)
            data = res.get_json()
            self.assertTrue(data.get("success"))

            # Check upload custom names passed to upload_gitea_asset
            upload_names = [call.kwargs.get("custom_name") or call.args[6] for call in mock_upload_asset.call_args_list if len(call.args) > 6 or "custom_name" in call.kwargs]
            self.assertIn("custom_sensor.bin", upload_names)
            self.assertIn("display_module.bin", upload_names)

            # Check version.json
            v_file = os.path.join(temp_dir, "version.json")
            with open(v_file, "r", encoding="utf-8") as f:
                v_content = json.load(f)
            self.assertEqual(v_content["firmware"]["binName"], "custom_sensor.bin")
            self.assertEqual(v_content["firmware"]["secondaryBinName"], "display_module.bin")
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)


class TestGitGraphAndTree(unittest.TestCase):

    def test_git_log_graph_structure(self):
        from gsm.git_utils import git_log_graph
        repo_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
        commits = git_log_graph(repo_dir, limit=20)
        self.assertIsInstance(commits, list)
        self.assertGreater(len(commits), 0)
        for c in commits:
            self.assertTrue(bool(c.get("hash")), "Commit hash must not be empty (no blank rows)")
            self.assertIn("lane", c)
            self.assertIsInstance(c["lane"], int)
            self.assertIn("parent_lanes", c)
            self.assertIsInstance(c["parent_lanes"], list)
            self.assertIn("active_lanes", c)
            self.assertIsInstance(c["active_lanes"], list)

    def test_git_tree_no_duplicates(self):
        from gsm.git_utils import git_tree
        repo_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
        items = git_tree(repo_dir)
        self.assertIsInstance(items, list)
        paths = [item["path"] for item in items]
        self.assertEqual(len(paths), len(set(paths)), "Tree paths must be unique without duplicate dirs/files")

    @patch("app.load_projects")
    def test_api_graph_endpoint(self, mock_load_projects):
        import app
        repo_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
        mock_load_projects.return_value = [{"id": "test_p1", "name": "gsm_test", "path": repo_dir}]

        client = app.app.test_client()
        res = client.post("/api/projects/test_p1/git/graph", json={"limit": 10})
        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        self.assertIsInstance(data, list)
        self.assertGreater(len(data), 0)
        self.assertTrue(bool(data[0].get("hash")))


class TestStageAndStatus(unittest.TestCase):

    def test_parse_porcelain_unmodified_name_and_status(self):
        from gsm.git_utils import get_status
        import tempfile
        import subprocess

        with tempfile.TemporaryDirectory() as td:
            subprocess.run(["git", "init"], cwd=td, capture_output=True)
            subprocess.run(["git", "config", "user.name", "Test"], cwd=td, capture_output=True)
            subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=td, capture_output=True)

            # Create file1 and commit
            f1 = os.path.join(td, "app.py")
            with open(f1, "w") as f:
                f.write("print('hello')")
            subprocess.run(["git", "add", "app.py"], cwd=td, capture_output=True)
            subprocess.run(["git", "commit", "-m", "init"], cwd=td, capture_output=True)

            # Modify file1 (unstaged)
            with open(f1, "a") as f:
                f.write("\nprint('world')")

            # Create file with spaces
            f2 = os.path.join(td, "folder name")
            os.makedirs(f2, exist_ok=True)
            f2_file = os.path.join(f2, "space file.txt")
            with open(f2_file, "w") as f:
                f.write("content")

            status = get_status(td)
            files = {f["path"]: f["status"] for f in status["files"]}

            # app.py should be Modified, NOT Staged, and NOT pp.py!
            self.assertIn("app.py", files)
            self.assertEqual(files["app.py"], "Modified")
            self.assertNotIn("pp.py", files)

            # space file should be Untracked and NOT have enclosing quotes
            self.assertTrue(any("space file.txt" in p and not p.startswith('"') and not p.endswith('"') for p in files.keys()))

    def test_git_unlock_removes_stale_lock(self):
        from gsm.git_utils import git_unlock, git_check_index_lock
        import tempfile
        import subprocess

        with tempfile.TemporaryDirectory() as td:
            subprocess.run(["git", "init"], cwd=td, capture_output=True)
            lock_path = os.path.join(td, ".git", "index.lock")
            with open(lock_path, "w") as f:
                f.write("dummy lock")

            self.assertTrue(os.path.exists(lock_path))
            check = git_check_index_lock(td)
            self.assertTrue(check["is_locked"])

            res = git_unlock(td)
            self.assertTrue(res["success"])
            self.assertFalse(os.path.exists(lock_path))

    def test_git_stage_all_progress_generator(self):
        from gsm.git_utils import git_stage_all_progress
        import tempfile
        import subprocess

        with tempfile.TemporaryDirectory() as td:
            subprocess.run(["git", "init"], cwd=td, capture_output=True)
            for i in range(3):
                with open(os.path.join(td, f"file_{i}.txt"), "w") as f:
                    f.write(f"content {i}")

            events = list(git_stage_all_progress(td))
            self.assertGreater(len(events), 0)
            last_event = events[-1]
            self.assertTrue(last_event.get("success"))
            self.assertEqual(last_event.get("percent"), 100)

    @patch("app.load_projects")
    def test_api_stage_all_stream_endpoint(self, mock_load_projects):
        import app
        import tempfile
        import subprocess

        with tempfile.TemporaryDirectory() as td:
            subprocess.run(["git", "init"], cwd=td, capture_output=True)
            with open(os.path.join(td, "hello.py"), "w") as f:
                f.write("print(1)")

            mock_load_projects.return_value = [{"id": "p_stream_test", "name": "p_stream", "path": td}]
            client = app.app.test_client()
            res = client.post("/api/projects/p_stream_test/stage-all-stream")
            self.assertEqual(res.status_code, 200)
            data_str = res.get_data(as_text=True)
            lines = [json.loads(l) for l in data_str.strip().splitlines() if l.strip()]
            self.assertGreater(len(lines), 0)
            self.assertTrue(lines[-1].get("success"))
            self.assertEqual(lines[-1].get("percent"), 100)

    def test_git_stage_all_handles_deleted_files(self):
        from gsm.git_utils import git_stage_all_progress, _parse_porcelain
        import tempfile
        import subprocess

        # Test porcelain statuses
        self.assertEqual(_parse_porcelain("AM"), "Staged+Modified")
        self.assertEqual(_parse_porcelain("UU"), "Conflict")
        self.assertEqual(_parse_porcelain("AU"), "Conflict")
        self.assertEqual(_parse_porcelain(" D"), "Deleted")
        self.assertEqual(_parse_porcelain("D "), "Staged")

        with tempfile.TemporaryDirectory() as td:
            subprocess.run(["git", "init"], cwd=td, capture_output=True)
            subprocess.run(["git", "config", "user.name", "Tester"], cwd=td, capture_output=True)
            subprocess.run(["git", "config", "user.email", "test@test.com"], cwd=td, capture_output=True)
            f_path = os.path.join(td, "to_delete.txt")
            with open(f_path, "w") as f:
                f.write("delete me")
            subprocess.run(["git", "add", "to_delete.txt"], cwd=td, capture_output=True)
            subprocess.run(["git", "commit", "-m", "commit file"], cwd=td, capture_output=True)

            # Delete the file
            os.remove(f_path)
            events = list(git_stage_all_progress(td))
            self.assertGreater(len(events), 0)
            self.assertTrue(events[-1].get("success"))
            self.assertEqual(events[-1].get("percent"), 100)


class TestTwoRepoOtaDistribution(unittest.TestCase):

    def test_parse_github_repo_url(self):
        from gsm.api_utils import parse_github_repo_url
        self.assertEqual(parse_github_repo_url("https://github.com/octocat/ota-public.git"), ("octocat", "ota-public"))
        self.assertEqual(parse_github_repo_url("https://github.com/octocat/ota-public"), ("octocat", "ota-public"))
        self.assertEqual(parse_github_repo_url("git@github.com:octocat/ota-public.git"), ("octocat", "ota-public"))
        self.assertEqual(parse_github_repo_url(""), ("", ""))

    @patch("gsm.ota_utils.upload_github_asset")
    @patch("gsm.ota_utils.create_github_release")
    @patch("gsm.ota_utils.subprocess.run")
    def test_publish_two_repo_ota_flow(self, mock_subproc, mock_create_rel, mock_upload_asset):
        from gsm.ota_utils import publish_two_repo_ota
        import tempfile
        import shutil

        # Configure subprocess mock
        mock_proc = MagicMock()
        mock_proc.returncode = 0
        mock_proc.stdout = "M docs/version.json"
        mock_proc.stderr = ""
        mock_subproc.return_value = mock_proc

        mock_create_rel.return_value = {
            "id": 888,
            "tag_name": "v2.0.0",
            "html_url": "https://github.com/octocat/ota-dist/releases/tag/v2.0.0"
        }
        mock_upload_asset.return_value = ({"browser_download_url": "https://github.com/asset"}, None)

        temp_proj = tempfile.mkdtemp()
        try:
            # Create a sample web folder in Repo 1
            web_dir = os.path.join(temp_proj, "web")
            os.makedirs(web_dir)
            with open(os.path.join(web_dir, "index.html"), "w") as f:
                f.write("<h1>My Web App</h1>")

            # Create dummy bin, apk and an extra file (e.g. spiffs.bin)
            bin_file = os.path.join(temp_proj, "firmware.bin")
            with open(bin_file, "wb") as f: f.write(b"\x00\x01\x02")
            apk_file = os.path.join(temp_proj, "app-release.apk")
            with open(apk_file, "wb") as f: f.write(b"PK")
            extra_file = os.path.join(temp_proj, "spiffs.bin")
            with open(extra_file, "wb") as f: f.write(b"FS_DATA")

            res = publish_two_repo_ota(
                project_path=temp_proj,
                public_repo_url="https://github.com/octocat/ota-dist.git",
                tag_name="v2.0.0",
                app_ver_code=10,
                fw_ver_code=10,
                changelog="Big OTA release",
                apk_path=apk_file,
                bin_path=bin_file,
                extra_files=[{"label": "SPIFFS File", "path": extra_file}],
                github_token="ghp_test_token"
            )

            self.assertTrue(res["success"])
            self.assertEqual(res["public_repo"], "octocat/ota-dist")
            self.assertEqual(res["release_id"], 888)
            self.assertEqual(len(res["extra_assets"]), 1)
            mock_create_rel.assert_called_once()
            # 3 assets (bin + apk + extra spiffs.bin) uploaded
            self.assertEqual(mock_upload_asset.call_count, 3)
        finally:
            shutil.rmtree(temp_proj, ignore_errors=True)

    @patch("app.publish_two_repo_ota")
    @patch("app.load_settings")
    @patch("app.save_projects")
    @patch("app.load_projects")
    def test_api_release_ota_two_repo_endpoint(self, mock_load_proj, mock_save_proj, mock_settings, mock_publish_2repo):
        import app
        import tempfile
        import shutil

        temp_dir = tempfile.mkdtemp()
        try:
            mock_load_proj.return_value = [{
                "id": "p_two_repo",
                "name": "private_project",
                "path": temp_dir
            }]
            mock_settings.return_value = {"github_token": "ghp_mock"}
            mock_publish_2repo.return_value = {
                "success": True,
                "logs": ["Step 1", "Step 2", "Step 3", "Step 4"],
                "public_repo": "octocat/public-ota",
                "apk_url": "https://dl/apk",
                "bin_url": "https://dl/bin",
                "release_id": 999,
                "html_url": "https://github.com/octocat/public-ota/releases/tag/v3.0.0"
            }

            client = app.app.test_client()
            res = client.post("/api/projects/p_two_repo/release-ota", json={
                "tag_name": "v3.0.0",
                "changelog": "Two-repo isolated OTA",
                "ota_public_repo_url": "https://github.com/octocat/public-ota.git",
                "sync_nas": False,
                "build_apk": False
            })

            self.assertEqual(res.status_code, 200)
            data = res.get_json()
            self.assertTrue(data.get("success"))
            self.assertEqual(data.get("public_repo"), "octocat/public-ota")
            mock_publish_2repo.assert_called_once()
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)


class TestPushAllFeature(unittest.TestCase):

    @patch("gsm.git_utils._run_git_lines")
    @patch("gsm.git_utils._run_git")
    def test_git_push_all(self, mock_run, mock_lines):
        from gsm.git_utils import git_push_all
        # mock git remote listing
        mock_run.return_value = MagicMock(returncode=0, stdout="origin\ngitea\n")
        mock_lines.return_value = {"success": True, "stdout": "Everything up-to-date", "stderr": ""}

        res = git_push_all("/fake/path")
        self.assertTrue(res["success"])
        self.assertEqual(len(res["results"]), 2)
        self.assertEqual(res["results"][0]["remote"], "origin")
        self.assertEqual(res["results"][1]["remote"], "gitea")

    @patch("app.git_remote_list")
    @patch("app.git_push_all")
    @patch("app._find_project")
    @patch("app.is_git_repo")
    @patch("os.path.isdir")
    def test_api_push_all(self, mock_isdir, mock_is_git, mock_find, mock_push_all, mock_remote_list):
        import app
        mock_find.return_value = {"id": "p1", "path": "/fake/path", "name": "Fake"}
        mock_isdir.return_value = True
        mock_is_git.return_value = True
        mock_remote_list.return_value = []
        mock_push_all.return_value = {"success": True, "message": "OK", "results": []}

        client = app.app.test_client()
        res = client.post("/api/projects/p1/push-all", json={})
        self.assertEqual(res.status_code, 200)
        self.assertTrue(res.get_json()["success"])


class TestRemoteCreationFixes(unittest.TestCase):

    @patch("requests.get")
    @patch("requests.post")
    def test_create_github_repo_already_exists(self, mock_post, mock_get):
        from gsm.api_utils import create_github_repo
        # Post returns 422 name already exists
        mock_post_resp = MagicMock()
        mock_post_resp.status_code = 422
        mock_post_resp.json.return_value = {
            "message": "Repository creation failed.",
            "errors": [{"message": "name already exists on this account"}]
        }
        mock_post.return_value = mock_post_resp

        # Get user returns login
        mock_user_resp = MagicMock()
        mock_user_resp.status_code = 200
        mock_user_resp.json.return_value = {"login": "testuser"}

        # Get repo returns existing clone_url
        mock_repo_resp = MagicMock()
        mock_repo_resp.status_code = 200
        mock_repo_resp.json.return_value = {"clone_url": "https://github.com/testuser/my-repo.git"}

        mock_get.side_effect = [mock_user_resp, mock_repo_resp]

        clone_url = create_github_repo("token123", "my-repo")
        self.assertEqual(clone_url, "https://github.com/testuser/my-repo.git")

    @patch("gsm.git_utils._run_git_lines")
    @patch("gsm.git_utils._run_git")
    def test_git_set_or_add_remote_when_origin_exists(self, mock_run, mock_lines):
        from gsm.git_utils import git_set_or_add_remote
        # Remote origin already exists in git remote listing
        mock_run.return_value = MagicMock(returncode=0, stdout="origin\n")
        mock_lines.return_value = {"success": True, "stdout": "", "stderr": ""}

        res = git_set_or_add_remote("/fake/path", "origin", "https://github.com/user/repo.git")
        self.assertTrue(res.get("success"))
        # Should have called set-url, not add
        mock_lines.assert_called_with(["remote", "set-url", "origin", "https://github.com/user/repo.git"], cwd="/fake/path")

    @patch("gsm.git_utils._run_git_lines")
    @patch("gsm.git_utils._run_git")
    def test_git_set_or_add_remote_fallback_on_already_exists_error(self, mock_run, mock_lines):
        from gsm.git_utils import git_set_or_add_remote
        # Remote listing did not list it
        mock_run.return_value = MagicMock(returncode=0, stdout="")
        # First call to 'remote add' returns error 'remote origin already exists'
        mock_lines.side_effect = [
            {"success": False, "error": "fatal: remote origin already exists."},
            {"success": True, "stdout": "", "stderr": ""}
        ]

        res = git_set_or_add_remote("/fake/path", "origin", "https://github.com/user/repo.git")
        self.assertTrue(res.get("success"))
        # Verify fallback set-url was called
        self.assertEqual(mock_lines.call_count, 2)

    @patch("gsm.git_utils._run_git")
    @patch("gsm.git_utils.is_git_repo")
    @patch("gsm.storage.get_token")
    def test_setup_multi_push_configures_both_urls(self, mock_token, mock_is_git, mock_run):
        from gsm.git_utils import setup_multi_push
        mock_is_git.return_value = True
        mock_token.return_value = "fake_token_123"
        mock_run.return_value = MagicMock(returncode=0, stdout="")

        setup_multi_push("/fake/path", "https://github.com/user/repo.git", "http://gitea.local/repo.git")

        calls = [c[0][0] for c in mock_run.call_args_list]
        # Must unset all previous pushurls
        self.assertIn(["config", "--unset-all", "remote.origin.pushurl"], calls)
        # Must add GitHub pushurl with token
        self.assertIn(["remote", "set-url", "--add", "--push", "origin", "https://fake_token_123@github.com/user/repo.git"], calls)
        # Must add Gitea pushurl
        self.assertIn(["remote", "set-url", "--add", "--push", "origin", "http://gitea.local/repo.git"], calls)


if __name__ == "__main__":
    unittest.main()



