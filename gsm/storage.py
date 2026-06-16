import json
import keyring
from typing import Optional
from .config import PROJECTS_FILE, SETTINGS_FILE, KEYRING_SERVICE


def load_projects() -> list:
    if not PROJECTS_FILE.exists():
        return []
    try:
        with open(PROJECTS_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return []


def save_projects(projects: list) -> None:
    with open(PROJECTS_FILE, "w", encoding="utf-8") as f:
        json.dump(projects, f, indent=2, ensure_ascii=False)


def load_settings() -> dict:
    if not SETTINGS_FILE.exists():
        return {}
    try:
        with open(SETTINGS_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return {}


def save_settings(settings: dict) -> None:
    with open(SETTINGS_FILE, "w", encoding="utf-8") as f:
        json.dump(settings, f, indent=2, ensure_ascii=False)


def get_token(key: str) -> Optional[str]:
    try:
        return keyring.get_password(KEYRING_SERVICE, key)
    except Exception:
        return None


def set_token(key: str, token: str) -> None:
    keyring.set_password(KEYRING_SERVICE, key, token)


def delete_token(key: str) -> None:
    try:
        keyring.delete_password(KEYRING_SERVICE, key)
    except keyring.errors.PasswordDeleteError:
        pass
