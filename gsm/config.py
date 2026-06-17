import os
import sys
from pathlib import Path

APP_NAME = "Git Smart Manager"
APP_VERSION = "1.0.0"
DEFAULT_PORT = 8765

def get_app_data_dir() -> Path:
    """Get the application data directory (created on first use)."""
    if sys.platform == "win32":
        base = Path(os.environ.get("APPDATA", Path.home() / "AppData" / "Roaming"))
    elif sys.platform == "darwin":
        base = Path.home() / "Library" / "Application Support"
    else:
        base = Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local" / "share"))
    data_dir = base / "gsm"
    data_dir.mkdir(parents=True, exist_ok=True)
    return data_dir

DATA_DIR = get_app_data_dir()
PROJECTS_FILE = DATA_DIR / "projects.json"
SETTINGS_FILE = DATA_DIR / "settings.json"
CREDENTIALS_FILE = DATA_DIR / "credentials.json"

KEYRING_SERVICE = "gsm"
KEYRING_KEYS = {
    "github_token": "github_token",
    "gitea_token": "gitea_token",
    "gitea_username": "gitea_username",
    "gitea_password": "gitea_password",
}
