"""Read the latest published version for terminal-based Skill sessions."""

from http.client import HTTPException
import json
from pathlib import Path
import re
from tempfile import TemporaryDirectory
import time
from urllib.request import Request, urlopen


REPO = "Funny1Potato/FP-DataHelper"
RELEASES = f"https://github.com/{REPO}/releases"
LATEST = f"https://api.github.com/repos/{REPO}/releases/latest"
VERSION = re.compile(r"v?(\d+\.\d+\.\d+)")
CHECK_INTERVAL = 24 * 60 * 60
RETRY_INTERVAL = 60 * 60


def read_object(path):
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def save_cache(path, data):
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with TemporaryDirectory(prefix=".skill-check-", dir=path.parent) as directory:
            temporary = Path(directory) / path.name
            temporary.write_text(json.dumps(data), encoding="utf-8")
            temporary.replace(path)
    except OSError:
        pass


def fetch_release_tag():
    request = Request(LATEST, headers={"Accept": "application/vnd.github+json", "User-Agent": "FP-DataHelper-Skill"})
    with urlopen(request, timeout=4) as response:
        release = json.load(response)
    tag = release["tag_name"]
    version = VERSION.fullmatch(tag)
    if not version or release.get("draft") or release.get("prerelease"):
        raise ValueError("Unexpected GitHub release metadata.")
    archive = f"FP-DataHelper.-.{version[1]}.zip"
    if not any(asset.get("name") == archive and asset.get("state") == "uploaded" for asset in release["assets"]):
        raise ValueError("The latest release package is still unavailable.")
    return tag


def latest_tag(cache, force):
    now = time.time()
    saved = read_object(cache) if not force else {}
    tag = saved.get("tag")
    checked_at = saved.get("checked_at")
    lifetime = CHECK_INTERVAL if isinstance(tag, str) and VERSION.fullmatch(tag) else RETRY_INTERVAL
    if isinstance(checked_at, (int, float)) and 0 <= now - checked_at < lifetime:
        return tag if lifetime == CHECK_INTERVAL else None
    try:
        tag = fetch_release_tag()
    except (OSError, HTTPException, ValueError, KeyError, TypeError, AttributeError):
        tag = None
    save_cache(cache, {"tag": tag, "checked_at": time.time()})
    return tag


def skill_refresh_available(root, skill_dir):
    if skill_dir is None:
        return False
    try:
        installed = (skill_dir / "SKILL.md").read_text(encoding="utf-8")
        bundled = (root / "skills" / "fp-datahelper" / "SKILL.md").read_text(encoding="utf-8")
    except (OSError, ValueError):
        return False
    return installed != bundled


def check_update(root, skill_dir=None, *, force=False):
    version_header = (root / "Version").read_text(encoding="utf-8").splitlines()
    local = re.fullmatch(r"\d{4}\.\d{2}\.\d{2} v(\d+\.\d+\.\d+)", version_header[0] if version_header else "")
    if local is None:
        raise ValueError("Cannot read the installed version from Version.")
    result = {
        "current_version": local[1],
        "latest_version": None,
        "release_url": None,
        "status": "unavailable",
        "skill_refresh_available": skill_refresh_available(root, skill_dir),
    }
    user_data = root / "user_data"
    settings = user_data / "settings.json"
    if not settings.is_file():
        settings = root / "config" / "settings.json"
    if not force and read_object(settings).get("auto_check_update") is False:
        result["status"] = "disabled"
        return result
    tag = latest_tag(user_data / "skill_update_check.json", force)
    if tag is not None:
        remote = VERSION.fullmatch(tag)[1]
        newer = tuple(map(int, remote.split("."))) > tuple(map(int, local[1].split(".")))
        result.update(latest_version=remote, release_url=f"{RELEASES}/tag/{tag}",
                      status="update_available" if newer else "current")
    return result
