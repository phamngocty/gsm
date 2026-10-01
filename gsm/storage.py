import json
import base64
import keyring
from typing import Optional
from .config import PROJECTS_FILE, SETTINGS_FILE, CREDENTIALS_FILE, KEYRING_SERVICE


# ── Simple obfuscation for file-based credential storage ──
# This is NOT cryptographic security — it prevents casual plaintext reading.
# The primary secure store is the OS keyring (Windows Credential Manager).
# The file is a fallback so credentials survive keyring failures.
_ENCODING_KEY = 0xA3


def _obfuscate(text: str) -> str:
    """Simple XOR + base64 obfuscation."""
    encoded = bytearray(text.encode("utf-8"))
    for i in range(len(encoded)):
        encoded[i] ^= _ENCODING_KEY
    return base64.b64encode(bytes(encoded)).decode("ascii")


def _deobfuscate(obfuscated: str) -> str:
    """Reverse XOR + base64."""
    try:
        decoded = base64.b64decode(obfuscated)
        buf = bytearray(decoded)
        for i in range(len(buf)):
            buf[i] ^= _ENCODING_KEY
        return buf.decode("utf-8")
    except Exception:
        return ""


def _load_credential_file() -> dict:
    if not CREDENTIALS_FILE.exists():
        return {}
    try:
        with open(CREDENTIALS_FILE, "r", encoding="utf-8") as f:
            raw = json.load(f)
        # Deobfuscate values
        result = {}
        for k, v in raw.items():
            result[k] = _deobfuscate(v) if v else ""
        return result
    except (json.JSONDecodeError, OSError):
        return {}


def _save_credential_file(creds: dict) -> None:
    """Save credentials to file (obfuscated)."""
    raw = {}
    for k, v in creds.items():
        raw[k] = _obfuscate(v) if v else ""
    with open(CREDENTIALS_FILE, "w", encoding="utf-8") as f:
        json.dump(raw, f, indent=2, ensure_ascii=False)


def load_projects() -> list:
    if not PROJECTS_FILE.exists():
        return []
    try:
        with open(PROJECTS_FILE, "r", encoding="utf-8") as f:
            projects = json.load(f)
            for p in projects:
                if "enable_ota" not in p:
                    p["enable_ota"] = False
            return projects
    except (json.JSONDecodeError, OSError):
        return []


def save_projects(projects: list) -> None:
    with open(PROJECTS_FILE, "w", encoding="utf-8") as f:
        json.dump(projects, f, indent=2, ensure_ascii=False)


def update_project_ota(project_id: str, enable_ota: bool) -> bool:
    """Update enable_ota flag for a given project."""
    projects = load_projects()
    found = False
    for p in projects:
        if p.get("id") == project_id:
            p["enable_ota"] = bool(enable_ota)
            found = True
            break
    if found:
        save_projects(projects)
    return found


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
    """Get token from keyring, fall back to credential file."""
    # Try keyring first
    try:
        val = keyring.get_password(KEYRING_SERVICE, key)
        if val:
            return val
    except Exception:
        pass
    # Fall back to file
    creds = _load_credential_file()
    return creds.get(key) or None


def set_token(key: str, token: str) -> None:
    """Save token to both keyring and credential file."""
    # Save to keyring
    try:
        keyring.set_password(KEYRING_SERVICE, key, token)
    except Exception:
        pass
    # Save to file as fallback
    creds = _load_credential_file()
    creds[key] = token
    _save_credential_file(creds)


def delete_token(key: str) -> None:
    """Delete token from both keyring and credential file."""
    try:
        keyring.delete_password(KEYRING_SERVICE, key)
    except Exception:
        pass
    creds = _load_credential_file()
    creds.pop(key, None)
    _save_credential_file(creds)


def get_saved_git_authors() -> list:
    """Load saved git author accounts from settings."""
    settings = load_settings()
    authors = settings.get("saved_git_authors")
    if authors is None:
        authors = []
    return authors


def save_git_author_profile(name: str, email: str) -> list:
    """Add or update an author profile in settings."""
    name = name.strip()
    email = email.strip()
    if not name or not email:
        return get_saved_git_authors()

    settings = load_settings()
    authors = settings.get("saved_git_authors", [])
    found = False
    for a in authors:
        if a.get("email", "").lower() == email.lower():
            a["name"] = name
            found = True
            break
    if not found:
        authors.append({"name": name, "email": email})

    settings["saved_git_authors"] = authors
    save_settings(settings)
    return authors


def delete_saved_git_author(email: str) -> list:
    """Delete a saved author profile by email."""
    settings = load_settings()
    authors = [
        a for a in settings.get("saved_git_authors", [])
        if a.get("email", "").lower() != email.strip().lower()
    ]
    settings["saved_git_authors"] = authors
    save_settings(settings)
    return authors

