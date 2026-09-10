import unittest
from unittest.mock import patch, MagicMock
import sys
import os

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


if __name__ == "__main__":
    unittest.main()

