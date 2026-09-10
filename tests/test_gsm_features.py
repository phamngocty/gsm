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


if __name__ == "__main__":
    unittest.main()
