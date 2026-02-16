#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
浏览器管理模块 - 封装Selenium操作
"""

import os
import time
import logging
import tempfile
from typing import Optional, Dict, Any
from contextlib import contextmanager
from pathlib import Path

from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import (
    TimeoutException, NoSuchElementException,
    WebDriverException, SessionNotCreatedException
)

try:
    from src.driver_manager import get_chromedriver_path
except ImportError:
    get_chromedriver_path = None


class BrowserManager:
    """浏览器管理器"""

    def __init__(self, config: Dict[str, Any] = None):
        """初始化浏览器管理器"""
        self.logger = logging.getLogger(__name__)
        self.config = config or {}
        self.driver: Optional[webdriver.Chrome] = None
        self.temp_dir: Optional[str] = None

    def _get_chrome_options(self, profile_name: Optional[str] = None) -> Options:
        """获取Chrome选项配置"""
        options = Options()

        # 基础配置
        if self.config.get("headless", True):
            options.add_argument("--headless")

        options.add_argument("--no-sandbox")
        options.add_argument("--disable-dev-shm-usage")
        options.add_argument("--disable-gpu")
        options.add_argument("--remote-debugging-port=0")  # 自动分配可用端口，避免冲突

        # 窗口大小
        window_size = self.config.get("window_size", "1920,1080")
        options.add_argument(f"--window-size={window_size}")

        # 性能优化
        if self.config.get("disable_images", True):
            prefs = {"profile.managed_default_content_settings.images": 2}
            options.add_experimental_option("prefs", prefs)

        # 禁用不必要的功能
        options.add_argument("--disable-extensions")
        options.add_argument("--disable-plugins")
        options.add_argument("--disable-logging")
        options.add_argument("--log-level=3")
        options.add_argument("--silent")
        options.add_argument("--disable-background-networking")
        options.add_argument("--disable-sync")
        options.add_argument("--disable-translate")
        options.add_argument("--disable-default-apps")
        options.add_argument("--no-default-browser-check")
        options.add_argument("--no-first-run")

        # 隐藏自动化特征
        options.add_argument("--disable-blink-features=AutomationControlled")
        options.add_experimental_option("excludeSwitches", ["enable-automation"])
        options.add_experimental_option('useAutomationExtension', False)

        # 用户代理
        if self.config.get("user_agent"):
            options.add_argument(f"--user-agent={self.config['user_agent']}")

        # 使用临时目录避免冲突
        self.temp_dir = tempfile.mkdtemp(prefix="anyrouter_chrome_")
        options.add_argument(f"--user-data-dir={self.temp_dir}")

        if profile_name:
            profile_dir = os.path.join(self.temp_dir, profile_name)
            os.makedirs(profile_dir, exist_ok=True)
            options.add_argument(f"--profile-directory={profile_name}")

        # 自动检测Chrome路径
        chrome_path = self._find_chrome_executable()
        if chrome_path:
            options.binary_location = chrome_path

        return options

    def _find_chrome_executable(self) -> Optional[str]:
        """查找Chrome可执行文件"""
        possible_paths = []

        # Windows路径
        if os.name == 'nt':
            possible_paths.extend([
                r"C:\Program Files\Google\Chrome\Application\chrome.exe",
                r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
                os.path.expandvars(r"%LOCALAPPDATA%\Google\Chrome\Application\chrome.exe"),
                os.path.expandvars(r"%PROGRAMFILES%\Google\Chrome\Application\chrome.exe"),
                os.path.expandvars(r"%PROGRAMFILES(X86)%\Google\Chrome\Application\chrome.exe"),
            ])

        # macOS路径
        elif os.name == 'posix' and os.uname().sysname == 'Darwin':
            possible_paths.extend([
                "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
                os.path.expanduser("~/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"),
            ])

        # Linux路径
        else:
            possible_paths.extend([
                "/usr/bin/google-chrome",
                "/usr/local/bin/google-chrome",
                "/usr/bin/chromium",
                "/usr/bin/chromium-browser",
                "/snap/bin/chromium",
            ])

        for path in possible_paths:
            if os.path.exists(path):
                self.logger.debug(f"找到Chrome: {path}")
                return path

        self.logger.warning("未能自动检测Chrome路径")
        return None

    def _get_chromedriver_path(self) -> str:
        """获取ChromeDriver路径 - 优先使用自动管理器"""
        # 优先使用自动管理器
        if get_chromedriver_path:
            try:
                auto_path = get_chromedriver_path()
                if auto_path and os.path.exists(auto_path):
                    self.logger.info(f"使用自动管理的ChromeDriver: {auto_path}")
                    return auto_path
            except Exception as e:
                self.logger.warning(f"自动获取ChromeDriver失败: {e}")

        # 备用方案：使用原始路径
        chromedriver_path = f"{os.getcwd()}/chromedriver.exe" if os.name == 'nt' else f"{os.getcwd()}/chromedriver"

        if not os.path.exists(chromedriver_path):
            self.logger.error(f"ChromeDriver不存在: {chromedriver_path}")
            # 尝试当前目录的相对路径
            chromedriver_path = "chromedriver.exe" if os.name == 'nt' else "chromedriver"
            self.logger.warning(f"尝试使用相对路径: {chromedriver_path}")
        else:
            self.logger.debug(f"使用ChromeDriver: {chromedriver_path}")

        return chromedriver_path

    @contextmanager
    def create_driver(self, profile_name: Optional[str] = None):
        """创建浏览器实例的上下文管理器"""
        driver = None
        try:
            options = self._get_chrome_options(profile_name)
            chromedriver_path = self._get_chromedriver_path()

            self.logger.info(f"启动Chrome (profile: {profile_name or 'default'})")

            driver = webdriver.Chrome(
                service=Service(chromedriver_path),
                options=options
            )

            # 设置超时
            driver.implicitly_wait(self.config.get("implicitly_wait", 2))
            driver.set_page_load_timeout(self.config.get("page_load_timeout", 30))

            # 注入JavaScript以隐藏自动化特征
            driver.execute_cdp_cmd("Page.addScriptToEvaluateOnNewDocument", {
                "source": """
                    Object.defineProperty(navigator, 'webdriver', {
                        get: () => undefined
                    });
                """
            })

            self.driver = driver
            yield driver

        except SessionNotCreatedException as e:
            self.logger.error(f"Chrome启动失败 - 版本不匹配: {e}")
            if "This version of ChromeDriver only supports Chrome version" in str(e):
                self.logger.error("请下载匹配的ChromeDriver版本")
            yield None

        except WebDriverException as e:
            self.logger.error(f"Chrome启动失败: {e}")
            yield None

        except Exception as e:
            self.logger.error(f"未知错误: {e}")
            yield None

        finally:
            if driver:
                try:
                    driver.quit()
                    self.logger.debug("Chrome已关闭")
                except:
                    pass

            # 清理临时目录
            if self.temp_dir and os.path.exists(self.temp_dir):
                try:
                    import shutil
                    shutil.rmtree(self.temp_dir, ignore_errors=True)
                except:
                    pass

            self.driver = None

    def wait_for_element(self, by: By, value: str, timeout: int = 10) -> Optional[Any]:
        """等待元素出现"""
        if not self.driver:
            return None

        try:
            element = WebDriverWait(self.driver, timeout).until(
                EC.presence_of_element_located((by, value))
            )
            return element
        except TimeoutException:
            self.logger.warning(f"等待元素超时: {by}={value}")
            return None

    def wait_for_clickable(self, by: By, value: str, timeout: int = 10) -> Optional[Any]:
        """等待元素可点击"""
        if not self.driver:
            return None

        try:
            element = WebDriverWait(self.driver, timeout).until(
                EC.element_to_be_clickable((by, value))
            )
            return element
        except TimeoutException:
            self.logger.warning(f"等待可点击元素超时: {by}={value}")
            return None

    def safe_click(self, element) -> bool:
        """安全点击元素"""
        if not element or not self.driver:
            return False

        try:
            # 尝试常规点击
            element.click()
            return True
        except:
            try:
                # 使用JavaScript点击
                self.driver.execute_script("arguments[0].click();", element)
                return True
            except Exception as e:
                self.logger.error(f"点击失败: {e}")
                return False

    def safe_send_keys(self, element, text: str) -> bool:
        """安全输入文本"""
        if not element:
            return False

        try:
            element.clear()
            element.send_keys(text)
            return True
        except Exception as e:
            self.logger.error(f"输入失败: {e}")
            return False

    def execute_script(self, script: str, *args) -> Any:
        """执行JavaScript脚本"""
        if not self.driver:
            return None

        try:
            return self.driver.execute_script(script, *args)
        except Exception as e:
            self.logger.error(f"脚本执行失败: {e}")
            return None

    def take_screenshot(self, filename: str) -> bool:
        """截图"""
        if not self.driver:
            return False

        try:
            self.driver.save_screenshot(filename)
            self.logger.info(f"截图保存: {filename}")
            return True
        except Exception as e:
            self.logger.error(f"截图失败: {e}")
            return False

    def get_page_source(self) -> Optional[str]:
        """获取页面源代码"""
        if not self.driver:
            return None

        try:
            return self.driver.page_source
        except:
            return None

    def refresh(self) -> bool:
        """刷新页面"""
        if not self.driver:
            return False

        try:
            self.driver.refresh()
            return True
        except:
            return False

    def navigate_to(self, url: str) -> bool:
        """导航到指定URL"""
        if not self.driver:
            return False

        try:
            self.driver.get(url)
            return True
        except Exception as e:
            self.logger.error(f"导航失败: {e}")
            return False

    def get_current_url(self) -> Optional[str]:
        """获取当前URL"""
        if not self.driver:
            return None

        try:
            return self.driver.current_url
        except:
            return None

    def wait_for_url_contains(self, substring: str, timeout: int = 10) -> bool:
        """等待URL包含特定字符串"""
        if not self.driver:
            return False

        try:
            WebDriverWait(self.driver, timeout).until(
                EC.url_contains(substring)
            )
            return True
        except TimeoutException:
            return False

    def check_element_exists(self, by: By, value: str) -> bool:
        """检查元素是否存在"""
        if not self.driver:
            return False

        try:
            self.driver.find_element(by, value)
            return True
        except NoSuchElementException:
            return False

    def get_element_text(self, by: By, value: str) -> Optional[str]:
        """获取元素文本"""
        if not self.driver:
            return None

        try:
            element = self.driver.find_element(by, value)
            return element.text
        except:
            return None


if __name__ == "__main__":
    # 测试浏览器管理器
    logging.basicConfig(level=logging.DEBUG)

    config = {
        "headless": False,
        "window_size": "1280,720",
        "disable_images": False
    }

    browser_mgr = BrowserManager(config)

    with browser_mgr.create_driver() as driver:
        if driver:
            browser_mgr.navigate_to("https://www.baidu.com")
            time.sleep(2)
            print(f"当前URL: {browser_mgr.get_current_url()}")
            browser_mgr.take_screenshot("test.png")