# -*- coding: utf-8 -*-
"""
FP-DataHelper 自动更新模块
"""
import os
import sys
import re
import json
import tempfile
import shutil
import zipfile
import requests
from PyQt5.QtCore import QThread, pyqtSignal


class Updater:
    """自动更新器"""
    
    # Version 文件地址（纯文本，第一行包含最新版本）
    VERSION_URL = "https://raw.githubusercontent.com/{repo}/main/Version"
    # Release 下载链接模板
    DOWNLOAD_URL_TPL = "https://github.com/{repo}/releases/download/{tag}/FP-DataHelper.-.{tag}.zip"
    
    def __init__(self, repo: str, current_version: str):
        self.repo = repo
        self.current_version = current_version
        self.program_dir = os.path.dirname(os.path.abspath(sys.argv[0]))
    
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
    
    def download(self, url: str, progress_callback=None) -> str:
        """
        下载更新包到临时目录
        返回: 下载文件路径
        """
        temp_dir = tempfile.mkdtemp()
        zip_path = os.path.join(temp_dir, "update.zip")
        
        resp = requests.get(url, stream=True, timeout=30)
        resp.raise_for_status()
        
        total_size = int(resp.headers.get("content-length", 0))
        downloaded = 0
        
        with open(zip_path, "wb") as f:
            for chunk in resp.iter_content(chunk_size=8192):
                f.write(chunk)
                downloaded += len(chunk)
                if progress_callback and total_size > 0:
                    progress_callback(downloaded, total_size)
        
        return zip_path
    
    def apply_update(self, zip_path: str):
        """
        解压并替换当前程序文件
        """
        temp_dir = os.path.dirname(zip_path)
        extract_dir = os.path.join(temp_dir, "extracted")
        os.makedirs(extract_dir, exist_ok=True)
        
        # 使用 Python zipfile 解压，手动处理中文文件名编码
        with zipfile.ZipFile(zip_path, "r") as zf:
            for info in zf.infolist():
                # 处理中文文件名：CP437 -> GBK
                try:
                    # 尝试将文件名从 CP437 转换为 GBK
                    raw_bytes = info.filename.encode('cp437')
                    decoded_filename = raw_bytes.decode('gbk')
                except:
                    # 如果转换失败，使用原始文件名
                    decoded_filename = info.filename
                
                # 构建目标路径
                target_path = os.path.join(extract_dir, decoded_filename)
                
                # 创建目录
                if info.is_dir():
                    os.makedirs(target_path, exist_ok=True)
                else:
                    # 确保父目录存在
                    os.makedirs(os.path.dirname(target_path), exist_ok=True)
                    # 解压文件
                    with zf.open(info) as source, open(target_path, 'wb') as target:
                        target.write(source.read())
        
        # 查找解压后的实际目录（可能有一层嵌套）
        items = os.listdir(extract_dir)
        if len(items) == 1 and os.path.isdir(os.path.join(extract_dir, items[0])):
            source_dir = os.path.join(extract_dir, items[0])
        else:
            source_dir = extract_dir
        
        # 复制文件覆盖当前目录
        for item in os.listdir(source_dir):
            src = os.path.join(source_dir, item)
            dst = os.path.join(self.program_dir, item)
            
            if os.path.isdir(src):
                if os.path.exists(dst):
                    shutil.rmtree(dst)
                shutil.copytree(src, dst)
            else:
                shutil.copy2(src, dst)
        
        # 清理临时目录
        shutil.rmtree(temp_dir, ignore_errors=True)
    
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
    finished = pyqtSignal(str)       # zip_path
    error = pyqtSignal(str)          # error message
    
    def __init__(self, updater: Updater, url: str):
        super().__init__()
        self.updater = updater
        self.url = url
    
    def run(self):
        try:
            zip_path = self.updater.download(
                self.url,
                progress_callback=lambda d, t: self.progress.emit(d, t)
            )
            self.finished.emit(zip_path)
        except Exception as e:
            self.error.emit(str(e))
