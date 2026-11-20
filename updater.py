# -*- coding: utf-8 -*-
"""
FP-DataHelper 自动更新模块
"""
import os
import re
import tempfile
import shutil
import zipfile
from pathlib import Path, PurePosixPath
from stat import S_ISLNK
import requests
from PyQt5.QtCore import QLockFile, QThread, pyqtSignal


class Updater:
    """自动更新器"""
    
    # Version 文件地址（纯文本，第一行包含最新版本）
    VERSION_URL = "https://raw.githubusercontent.com/{repo}/main/Version"
    # Release 下载链接模板
    DOWNLOAD_URL_TPL = "https://github.com/{repo}/releases/download/{tag}/FP-DataHelper.-.{tag}.zip"
    
    PROGRAM_FILES = {
        "Datahelper.py", "updater.py", "method_process.py", "method_support.py",
        "Requirement.txt", "Version", "README.md", "LICENSE", "启动.bat",
        "example.xlsx", "exampleRI.xlsx", "builtin_workflows.json", "config/builtin_workflows.json",
    }
    PROGRAM_DIRS = {"Methods", "Database", "images"}

    def __init__(self, repo: str, current_version: str):
        self.repo = repo
        self.current_version = current_version
        self.program_dir = Path(__file__).resolve().parent
    
    def check_update(self) -> dict | None:
        """
        检查是否有新版本
        返回: {version, download_url, changelog} 或 None
        """
        url = self.VERSION_URL.format(repo=self.repo)
        resp = requests.get(url, timeout=10)
        resp.raise_for_status()
        
        # 解析第一行提取版本号：2026.08.26 v0.2.0
        lines = resp.text.strip().splitlines()
        if not lines:
            return None
        
        # 从第一行提取版本号
        first_line = lines[0]
        version_match = re.search(r'v([\d.]+)', first_line)
        if not version_match:
            return None
        
        remote_version = version_match.group(1)
        
        # 比较版本
        if not self._is_newer(remote_version, self.current_version):
            return None
        
        # 构造下载链接
        download_url = self.DOWNLOAD_URL_TPL.format(repo=self.repo, tag=remote_version)
        
        # 提取更新日志（第一行之后的内容，直到下一个版本行）
        changelog_lines = []
        for line in lines[1:]:
            if re.search(r'^\d{4}\.\d{2}\.\d{2}\s+v', line):
                break
            if line.strip():
                changelog_lines.append(line.strip())
        
        return {
            "version": remote_version,
            "download_url": download_url,
            "changelog": "\n".join(changelog_lines) if changelog_lines else "无更新日志"
        }
    
    def download(self, url: str, progress_callback=None, cancelled=None) -> str:
        """Stream a release into a temporary file."""
        with tempfile.NamedTemporaryFile(prefix="fp-datahelper-", suffix=".zip", delete=False) as stream:
            zip_path = Path(stream.name)
        try:
            with requests.get(url, stream=True, timeout=30) as response, zip_path.open("wb") as stream:
                response.raise_for_status()
                total = int(response.headers.get("content-length", 0))
                downloaded = 0
                for chunk in response.iter_content(chunk_size=8192):
                    if cancelled and cancelled():
                        raise InterruptedError("更新下载已取消。")
                    stream.write(chunk)
                    downloaded += len(chunk)
                    if progress_callback and total > 0:
                        progress_callback(downloaded, total)
                if total and downloaded != total and not response.headers.get("content-encoding"):
                    raise ValueError("更新包下载不完整。")
        except BaseException:
            zip_path.unlink(missing_ok=True)
            raise
        return str(zip_path)

    def archive_files(self, archive):
        """Find the application inside a flat or wrapped release archive."""
        members = {}
        for info in archive.infolist():
            if info.is_dir():
                continue
            filename = info.filename
            if not info.flag_bits & 0x800:
                try:
                    filename = filename.encode("cp437").decode("gbk")
                except UnicodeError:
                    pass
            path = PurePosixPath(filename.replace("\\", "/"))
            if (path.is_absolute() or ":" in filename
                    or any(part.endswith((".", " ")) for part in path.parts)
                    or S_ISLNK(info.external_attr >> 16)):
                raise ValueError("更新包包含无效路径。")
            if path in members:
                raise ValueError("更新包包含重复文件。")
            members[path] = info

        roots = [
            path.parent for path in members
            if path.name == "Datahelper.py" and path.with_name("updater.py") in members
        ]
        if len(roots) != 1:
            raise ValueError("更新包缺少唯一的 FP-DataHelper 程序目录。")

        files = {}
        for path, info in members.items():
            if not path.is_relative_to(roots[0]):
                continue
            relative = path.relative_to(roots[0])
            if relative.as_posix() in self.PROGRAM_FILES or (
                len(relative.parts) > 1 and relative.parts[0] in self.PROGRAM_DIRS
            ):
                files[relative] = info
        if len({path.as_posix().casefold() for path in files}) != len(files):
            raise ValueError("更新包包含名称冲突的程序文件。")
        return files

    def apply_update(self, zip_path: str):
        """Stage and validate all files, then replace them with rollback on failure."""
        program = Path(self.program_dir).resolve()
        lock = QLockFile(str(program / ".fp-update.lock"))
        lock.setStaleLockTime(0)
        if not lock.tryLock(0):
            raise OSError("无法锁定程序目录，可能已有另一个更新正在运行。")
        try:
            self.replace_program_files(program, zip_path)
        finally:
            lock.unlock()

    def replace_program_files(self, program, zip_path):
        work = Path(tempfile.mkdtemp(prefix=".fp-update-", dir=program))
        staged = work / "staged"
        backup = work / "backup"
        replaced = []
        created_dirs = []
        keep_backup = False
        try:
            with zipfile.ZipFile(zip_path) as archive:
                files = self.archive_files(archive)
                for relative, info in files.items():
                    target = staged / relative
                    target.parent.mkdir(parents=True, exist_ok=True)
                    with archive.open(info) as source, target.open("wb") as destination:
                        shutil.copyfileobj(source, destination)

            targets = {}
            for relative in files:
                target = program / relative
                if target.resolve() != target:
                    raise ValueError(f"更新目标指向其他位置：{target}")
                if target.exists() and not target.is_file():
                    raise ValueError(f"更新目标不是文件：{target}")
                saved = None
                if target.is_file():
                    saved = backup / relative
                    saved.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(target, saved)
                targets[relative] = (target, saved)

            # Install the entry point after its supporting files.
            for relative in sorted(files, key=lambda path: (path.name == "Datahelper.py", path.as_posix())):
                target, saved = targets[relative]
                missing_parents = []
                parent = target.parent
                while not parent.exists():
                    missing_parents.append(parent)
                    parent = parent.parent
                for directory in reversed(missing_parents):
                    directory.mkdir()
                    created_dirs.append(directory)
                os.replace(staged / relative, target)
                replaced.append((target, saved))
        except BaseException as error:
            restore_errors = []
            for target, saved in reversed(replaced):
                try:
                    if saved is None:
                        target.unlink()
                    else:
                        os.replace(saved, target)
                except OSError as restore_error:
                    restore_errors.append(str(restore_error))
            for directory in reversed(created_dirs):
                try:
                    directory.rmdir()
                except OSError as restore_error:
                    restore_errors.append(str(restore_error))
            if restore_errors:
                keep_backup = True
                raise RuntimeError(f"更新失败且回滚不完整，备份位于 {backup}：{restore_errors[0]}") from error
            raise
        finally:
            if not keep_backup:
                shutil.rmtree(work, ignore_errors=True)

    @staticmethod
    def _is_newer(remote: str, local: str) -> bool:
        """比较版本号 v0.3.0 > v0.2.0"""
        try:
            r = [int(x) for x in remote.split('.')]
            l = [int(x) for x in local.split('.')]
            return r > l
        except:
            return False


class CheckThread(QThread):
    """后台检查更新线程"""
    
    update_found = pyqtSignal(dict)
    check_done = pyqtSignal()      # 检查完成（无更新）
    check_failed = pyqtSignal(str)
    
    def __init__(self, updater: Updater):
        super().__init__()
        self.updater = updater
    
    def run(self):
        try:
            result = self.updater.check_update()
            if result:
                self.update_found.emit(result)
            else:
                self.check_done.emit()
        except Exception as e:
            self.check_failed.emit(str(e))


class DownloadThread(QThread):
    """后台下载线程"""
    
    progress = pyqtSignal(int, int)  # downloaded, total
    downloaded = pyqtSignal(str)     # zip_path
    error = pyqtSignal(str)          # error message
    
    def __init__(self, updater: Updater, url: str):
        super().__init__()
        self.updater = updater
        self.url = url
    
    def run(self):
        try:
            zip_path = self.updater.download(
                self.url,
                progress_callback=self.progress.emit,
                cancelled=self.isInterruptionRequested,
            )
            if self.isInterruptionRequested():
                Path(zip_path).unlink(missing_ok=True)
            else:
                self.downloaded.emit(zip_path)
        except Exception as e:
            if not self.isInterruptionRequested():
                self.error.emit(str(e))
