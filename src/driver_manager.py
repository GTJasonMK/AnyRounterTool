#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
ChromeDriver自动管理器 - 自动检测Chrome版本并下载匹配的驱动
"""

import os
import re
import json
import platform
import subprocess
import logging
import zipfile
import threading
import requests
from pathlib import Path
from typing import Optional, Tuple


class ChromeDriverManager:
    """ChromeDriver自动管理器"""

    # ChromeDriver下载源
    DRIVER_SOURCES = {
        "googlechromelabs": "https://googlechromelabs.github.io/chrome-for-testing/",
        "npm_mirror": "https://registry.npmmirror.com/-/binary/chromedriver/",
        "cnpm_mirror": "https://cdn.npmmirror.com/binaries/chromedriver/"
    }

    # Chrome版本API
    VERSION_API = "https://googlechromelabs.github.io/chrome-for-testing/last-known-good-versions-with-downloads.json"
    FALLBACK_API = "https://chromedriver.storage.googleapis.com/LATEST_RELEASE_{major_version}"

    def __init__(self, cache_dir: str = None):
        """初始化驱动管理器"""
        self.logger = logging.getLogger(__name__)
        self.system = platform.system().lower()
        self.machine = platform.machine().lower()
        self._download_lock = threading.Lock()  # 下载锁，防止并发下载冲突

        # 缓存目录
        if cache_dir:
            self.cache_dir = Path(cache_dir)
        else:
            self.cache_dir = Path.home() / ".cache" / "chromedriver"

        self.cache_dir.mkdir(parents=True, exist_ok=True)

    def get_chrome_version(self) -> Optional[str]:
        """获取本地Chrome浏览器版本"""
        try:
            if self.system == "windows":
                # Windows注册表查询
                import winreg
                paths = [
                    r"SOFTWARE\Google\Chrome\BLBeacon",
                    r"SOFTWARE\Wow6432Node\Google\Chrome\BLBeacon"
                ]

                for path in paths:
                    try:
                        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, path) as key:
                            version = winreg.QueryValueEx(key, "version")[0]
                            self.logger.info(f"检测到Chrome版本: {version}")
                            return version
                    except:
                        pass

                # 备用方法：通过命令行
                chrome_paths = [
                    r"C:\Program Files\Google\Chrome\Application\chrome.exe",
                    r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe"
                ]

                for chrome_path in chrome_paths:
                    if os.path.exists(chrome_path):
                        result = subprocess.run(
                            [chrome_path, "--version"],
                            capture_output=True,
                            text=True
                        )
                        if result.returncode == 0:
                            version = result.stdout.strip().split()[-1]
                            self.logger.info(f"检测到Chrome版本: {version}")
                            return version

            elif self.system == "darwin":  # macOS
                result = subprocess.run(
                    ["/Applications/Google Chrome.app/Contents/MacOS/Google Chrome", "--version"],
                    capture_output=True,
                    text=True
                )
                if result.returncode == 0:
                    version = result.stdout.strip().split()[-1]
                    self.logger.info(f"检测到Chrome版本: {version}")
                    return version

            else:  # Linux
                result = subprocess.run(
                    ["google-chrome", "--version"],
                    capture_output=True,
                    text=True
                )
                if result.returncode == 0:
                    version = result.stdout.strip().split()[-1]
                    self.logger.info(f"检测到Chrome版本: {version}")
                    return version

        except Exception as e:
            self.logger.warning(f"无法检测Chrome版本: {e}")

        return None

    def get_major_version(self, version: str) -> int:
        """获取主版本号"""
        match = re.match(r"(\d+)", version)
        if match:
            return int(match.group(1))
        return 0

    def find_cached_driver(self, version: str) -> Optional[str]:
        """查找缓存的驱动"""
        major = self.get_major_version(version)
        driver_name = "chromedriver.exe" if self.system == "windows" else "chromedriver"

        # 精确匹配
        exact_path = self.cache_dir / f"chromedriver_{version}" / driver_name
        if exact_path.exists():
            self.logger.info(f"使用缓存的驱动: {exact_path}")
            return str(exact_path)

        # 主版本匹配
        for path in self.cache_dir.glob(f"chromedriver_{major}.*"):
            driver_path = path / driver_name
            if driver_path.exists():
                self.logger.info(f"使用缓存的驱动(主版本匹配): {driver_path}")
                return str(driver_path)

        return None

    def download_driver(self, chrome_version: str) -> Optional[str]:
        """下载ChromeDriver"""
        try:
            major_version = self.get_major_version(chrome_version)
            driver_name = "chromedriver.exe" if self.system == "windows" else "chromedriver"

            # 先检查目标文件是否已存在（可能之前下载过但缓存检查没找到）
            target_dir = self.cache_dir / f"chromedriver_{chrome_version}"
            if target_dir.exists():
                for root, dirs, files in os.walk(target_dir):
                    if driver_name in files:
                        driver_path = Path(root) / driver_name
                        if driver_path.exists():
                            self.logger.info(f"ChromeDriver已存在，跳过下载: {driver_path}")
                            return str(driver_path)

            # 确定平台
            if self.system == "windows":
                platform_name = "win64" if "64" in self.machine else "win32"
            elif self.system == "darwin":
                platform_name = "mac-arm64" if "arm" in self.machine else "mac-x64"
            else:
                platform_name = "linux64"

            # 尝试从Chrome for Testing获取
            driver_url = self._get_driver_url_from_chrome_for_testing(major_version, platform_name)

            if not driver_url:
                # 备用方案
                driver_url = self._get_driver_url_fallback(chrome_version, platform_name)

            if not driver_url:
                self.logger.error("无法找到匹配的ChromeDriver下载链接")
                return None

            # 下载驱动
            self.logger.info(f"下载ChromeDriver: {driver_url}")
            response = requests.get(driver_url, stream=True, timeout=60)
            response.raise_for_status()

            # 保存到临时文件（使用唯一文件名避免冲突）
            import time
            temp_file = self.cache_dir / f"chromedriver_temp_{int(time.time()*1000)}.zip"
            with open(temp_file, "wb") as f:
                for chunk in response.iter_content(chunk_size=8192):
                    f.write(chunk)

            # 解压
            target_dir.mkdir(exist_ok=True)

            with zipfile.ZipFile(temp_file, 'r') as zip_ref:
                zip_ref.extractall(target_dir)

            # 清理临时文件
            try:
                temp_file.unlink()
            except:
                pass  # 忽略临时文件删除失败

            # 查找驱动文件
            for root, dirs, files in os.walk(target_dir):
                if driver_name in files:
                    driver_path = Path(root) / driver_name

                    # Linux/Mac需要添加执行权限
                    if self.system != "windows":
                        os.chmod(driver_path, 0o755)

                    self.logger.info(f"ChromeDriver下载完成: {driver_path}")
                    return str(driver_path)

            self.logger.error("下载的压缩包中未找到ChromeDriver")
            return None

        except Exception as e:
            self.logger.error(f"下载ChromeDriver失败: {e}")
            return None

    def _get_driver_url_from_chrome_for_testing(self, major_version: int, platform: str) -> Optional[str]:
        """从Chrome for Testing获取驱动URL"""
        try:
            response = requests.get(self.VERSION_API, timeout=10)
            data = response.json()

            channels = data.get("channels", {})
            for channel in ["Stable", "Beta", "Dev", "Canary"]:
                if channel in channels:
                    channel_data = channels[channel]
                    version = channel_data.get("version", "")

                    if self.get_major_version(version) == major_version:
                        downloads = channel_data.get("downloads", {})
                        chromedriver = downloads.get("chromedriver", [])

                        for item in chromedriver:
                            if platform in item.get("platform", ""):
                                return item.get("url")

        except Exception as e:
            self.logger.debug(f"Chrome for Testing API失败: {e}")

        return None

    def _get_driver_url_direct(self, chrome_version: str, platform: str) -> Optional[str]:
        """直接构建Chrome for Testing下载URL（适用于Chrome 115+）"""
        # Chrome for Testing URL格式
        # https://storage.googleapis.com/chrome-for-testing-public/{version}/{platform}/chromedriver-{platform}.zip
        url = f"https://storage.googleapis.com/chrome-for-testing-public/{chrome_version}/{platform}/chromedriver-{platform}.zip"

        # 验证URL是否有效
        try:
            response = requests.head(url, timeout=10)
            if response.status_code == 200:
                self.logger.info(f"找到Chrome for Testing驱动: {url}")
                return url
        except Exception as e:
            self.logger.debug(f"直接URL验证失败: {e}")

        return None

    def _get_driver_url_fallback(self, chrome_version: str, platform: str) -> Optional[str]:
        """备用方案获取驱动URL"""
        major = self.get_major_version(chrome_version)

        # Chrome 115+ 使用新的 Chrome for Testing URL格式
        if major >= 115:
            # 先尝试完整版本号
            url = self._get_driver_url_direct(chrome_version, platform)
            if url:
                return url

            # 如果完整版本没找到，尝试使用已知的补丁版本API
            try:
                patch_api = "https://googlechromelabs.github.io/chrome-for-testing/latest-patch-versions-per-build-with-downloads.json"
                response = requests.get(patch_api, timeout=10)
                data = response.json()

                # 查找匹配的build版本（如144.0.7559）
                build_prefix = ".".join(chrome_version.split(".")[:3])
                builds = data.get("builds", {})

                if build_prefix in builds:
                    build_data = builds[build_prefix]
                    downloads = build_data.get("downloads", {})
                    chromedriver = downloads.get("chromedriver", [])

                    for item in chromedriver:
                        if platform in item.get("platform", ""):
                            return item.get("url")
            except Exception as e:
                self.logger.debug(f"补丁版本API失败: {e}")

            return None

        # Chrome 114及以下使用旧API
        try:
            version_url = self.FALLBACK_API.format(major_version=major)
            response = requests.get(version_url, timeout=10)
            driver_version = response.text.strip()

            # 验证返回值是否是有效的版本号（防止返回XML错误信息）
            if not driver_version or '<' in driver_version or len(driver_version) > 20:
                self.logger.debug(f"旧API返回无效版本: {driver_version[:50]}")
                return None

            # 构建下载URL
            if self.system == "windows":
                file_name = "chromedriver_win32.zip"
            elif self.system == "darwin":
                file_name = "chromedriver_mac64.zip"
            else:
                file_name = "chromedriver_linux64.zip"

            download_url = f"https://chromedriver.storage.googleapis.com/{driver_version}/{file_name}"
            return download_url

        except Exception as e:
            self.logger.debug(f"备用方案失败: {e}")

        return None

    def get_or_download_driver(self, chrome_version: str = None) -> Optional[str]:
        """获取或下载ChromeDriver（线程安全）"""
        # 如果没有指定版本，自动检测
        if not chrome_version:
            chrome_version = self.get_chrome_version()
            if not chrome_version:
                self.logger.error("无法检测Chrome版本，请手动指定")
                return None

        # 查找缓存（无锁快速检查）
        driver_path = self.find_cached_driver(chrome_version)
        if driver_path:
            return driver_path

        # 加锁下载，使用双重检查防止重复下载
        with self._download_lock:
            # 再次检查缓存（可能其他线程已经下载完成）
            driver_path = self.find_cached_driver(chrome_version)
            if driver_path:
                self.logger.info("其他线程已完成下载，使用缓存的驱动")
                return driver_path

            # 下载新驱动
            self.logger.info(f"未找到缓存的驱动，开始下载...")
            driver_path = self.download_driver(chrome_version)

        return driver_path

    def get_driver_path(self) -> str:
        """获取可用的ChromeDriver路径"""
        # 优先检查当前目录
        local_driver = "chromedriver.exe" if self.system == "windows" else "chromedriver"
        if os.path.exists(local_driver):
            self.logger.info(f"使用本地驱动: {local_driver}")
            return local_driver

        # 自动下载匹配的驱动
        driver_path = self.get_or_download_driver()
        if driver_path:
            return driver_path

        # 最后的备用方案
        self.logger.warning("使用默认驱动路径，可能不兼容")
        return local_driver


# 全局实例
_driver_manager = None
_driver_lock = threading.Lock()


def get_chromedriver_path() -> str:
    """获取ChromeDriver路径的便捷函数（线程安全）"""
    global _driver_manager

    with _driver_lock:
        if _driver_manager is None:
            _driver_manager = ChromeDriverManager()

        return _driver_manager.get_driver_path()


if __name__ == "__main__":
    # 测试
    logging.basicConfig(level=logging.DEBUG)

    manager = ChromeDriverManager()

    # 检测Chrome版本
    version = manager.get_chrome_version()
    print(f"Chrome版本: {version}")

    # 获取驱动
    driver_path = manager.get_driver_path()
    print(f"驱动路径: {driver_path}")