"""Build the GitHub release assets from the current application checkout."""

import argparse
import hashlib
import re
import shutil
import subprocess
import zipfile
from pathlib import Path, PurePosixPath


ROOT = Path(__file__).resolve().parents[1]
EMBEDDED_PYTHON = "python-3.10.11-embed-amd64"
ROOT_FILES = (
    "Datahelper.py", "updater.py", "method_process.py", "method_support.py",
    "fp_datahelper_cli.py", "skill_updates.py", "scripts/install_skill.py", "scripts/install_skill.ps1",
    "skills/fp-datahelper/SKILL.md", "INSTALL-SKILL.md",
    "builtin_workflows.json", "Version", "README.md", "LICENSE", "Requirement.txt",
    "启动.bat", "example.xlsx", "exampleRI.xlsx",
)


def sha256(path):
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def release_version():
    header = (ROOT / "Version").read_text(encoding="utf-8").splitlines()[0]
    match = re.fullmatch(r"(\d{4})\.(\d{2})\.(\d{2}) v(\d+\.\d+\.\d+)", header)
    if not match:
        raise ValueError("Version 第一行需要使用 YYYY.MM.DD vX.Y.Z 格式。")
    version = match[4]
    source = (ROOT / "Datahelper.py").read_text(encoding="utf-8")
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    if f'__version__ = "{version}"' not in source or f"**version: {version}**" not in readme:
        raise ValueError("Version、Datahelper.py 与 README.md 的版本号不一致。")
    return version, tuple(map(int, match.groups()[:3])) + (0, 0, 0)


def application_files():
    tracked = subprocess.check_output(
        ["git", "ls-files", "-z", "--", "Methods", "Database", "images",
         ":(exclude)Methods/Sorter-0.0.2/**"], cwd=ROOT
    ).decode("utf-8")
    resources = [
        path for path in tracked.split("\0")
        if (path.startswith("Methods/") and Path(path).name in {"__init__.py", "Config.json"})
        or (path.startswith("Database/") and path.endswith(".json"))
        or (path.startswith("images/") and path.endswith(".png"))
    ]
    return sorted((*ROOT_FILES, *resources))


def runtime_files(archive):
    """Select just the embedded runtime from a previously published full bundle."""
    files = {}
    for info in archive.infolist():
        path = PurePosixPath(info.filename.replace("\\", "/"))
        if info.is_dir() or EMBEDDED_PYTHON not in path.parts:
            continue
        if path.is_absolute() or any(part.endswith((".", " ")) or ":" in part for part in path.parts):
            raise ValueError("旧完整包包含无效的运行时路径。")
        name = PurePosixPath(*path.parts[path.parts.index(EMBEDDED_PYTHON):]).as_posix()
        if name.casefold() in files:
            raise ValueError(f"旧完整包包含重复的运行时文件：{name}")
        files[name.casefold()] = (name, info)
    required = (
        "python.exe", "pythonw.exe", "python310._pth",
        "Lib/site-packages/PyQt5/Qt5/plugins/platforms/qwindows.dll",
    )
    if any(f"{EMBEDDED_PYTHON}/{name}".casefold() not in files for name in required):
        raise ValueError("旧完整包缺少 Windows 嵌入式 Python 或 Qt 运行时。")
    return sorted(files.values())


def write_entry(archive, name, timestamp, source):
    info = zipfile.ZipInfo(f"FP-DataHelper/{name}", timestamp)
    info.compress_type = zipfile.ZIP_DEFLATED
    with archive.open(info, "w") as destination:
        shutil.copyfileobj(source, destination, length=1024 * 1024)


def build_archive(destination, timestamp, runtime=None):
    temporary = destination.with_suffix(".zip.tmp")
    try:
        with zipfile.ZipFile(temporary, "w") as archive:
            for name in application_files():
                with (ROOT / name).open("rb") as source:
                    write_entry(archive, name, timestamp, source)
            if runtime is not None:
                with zipfile.ZipFile(runtime) as original:
                    for name, info in runtime_files(original):
                        with original.open(info) as source:
                            write_entry(archive, name, timestamp, source)
        temporary.replace(destination)
    finally:
        temporary.unlink(missing_ok=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--runtime-zip", type=Path, help="Previously published full Windows ZIP")
    parser.add_argument("--runtime-sha256", help="SHA-256 from the source GitHub release asset")
    args = parser.parse_args()
    if bool(args.runtime_zip) != bool(args.runtime_sha256):
        parser.error("--runtime-zip and --runtime-sha256 must be supplied together")
    if args.runtime_zip and sha256(args.runtime_zip) != args.runtime_sha256.lower():
        parser.error("The runtime source ZIP does not match the supplied SHA-256")

    version, timestamp = release_version()
    output = (args.output or ROOT / "output" / "releases" / version).resolve()
    output.mkdir(parents=True, exist_ok=True)
    standard = output / f"FP-DataHelper.-.{version}.zip"
    build_archive(standard, timestamp)
    assets = [standard]
    if args.runtime_zip:
        full = output / f"FP-DataHelper.-.{version}.full.zip"
        build_archive(full, timestamp, args.runtime_zip)
        assets.append(full)

    checksums = "".join(f"{sha256(asset)}  {asset.name}\n" for asset in assets)
    (output / "SHA256SUMS.txt").write_text(checksums, encoding="ascii")
    print(checksums, end="")


if __name__ == "__main__":
    main()
