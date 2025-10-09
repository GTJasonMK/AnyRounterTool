#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
浏览器池管理器 - 复用浏览器实例提高性能
"""

import logging
import threading
import time
import queue
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Optional, List, Dict, Any
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime

from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.common.exceptions import WebDriverException

from src.browser_manager import BrowserManager

try:
    from src.driver_manager import get_chromedriver_path
except ImportError:
    get_chromedriver_path = None


@dataclass
class BrowserInstance:
    """浏览器实例封装"""
    driver: webdriver.Chrome
    browser_id: str
    created_at: datetime
    last_used: datetime
    temp_dir: Optional[str] = None  # 记录临时目录路径
    use_count: int = 0
    is_busy: bool = False

    def is_alive(self) -> bool:
        """检查浏览器是否存活"""
        try:
            _ = self.driver.current_url
            return True
        except:
            return False

    def cleanup(self):
        """清理浏览器实例和临时文件"""
        try:
            if self.driver:
                self.driver.quit()
        except:
            pass

        # 清理临时目录
        if self.temp_dir:
            try:
                import shutil
                import os
                if os.path.exists(self.temp_dir):
                    shutil.rmtree(self.temp_dir, ignore_errors=True)
            except:
                pass


class BrowserPool:
    """浏览器实例池 - 复用浏览器实例显著提升性能"""

    def __init__(self, pool_size: int = 3, max_pool_size: int = 9, config: Dict[str, Any] = None):
        """
        初始化浏览器池

        Args:
            pool_size: 初始池大小
            max_pool_size: 最大池大小
            config: 浏览器配置
        """
        self.logger = logging.getLogger(__name__)
        self.pool_size = min(pool_size, max_pool_size)
        self.max_pool_size = max_pool_size
        self.config = config or {}

        # 池管理
        self.instances: List[BrowserInstance] = []
        self.available = queue.Queue()
        self.lock = threading.Lock()
        self.shutdown = False

        # 性能统计
        self.stats = {
            'total_created': 0,
            'total_reused': 0,
            'total_requests': 0,
            'average_wait_time': 0
        }

        # 预创建实例
        self._init_pool()

    def _init_pool(self):
        """并行预创建浏览器实例池 - 显著提升启动速度"""
        self.logger.info(f"初始化浏览器池，大小: {self.pool_size}，使用并行创建...")

        start_time = time.time()

        # 使用线程池并行创建浏览器实例
        with ThreadPoolExecutor(max_workers=self.pool_size) as executor:
            # 提交所有创建任务
            futures = {
                executor.submit(self._create_browser_instance, f"browser_{i}"): i
                for i in range(self.pool_size)
            }

            # 收集结果
            for future in as_completed(futures):
                i = futures[future]
                try:
                    instance = future.result()
                    if instance:
                        self.instances.append(instance)
                        self.available.put(instance)
                        self.logger.debug(f"创建浏览器实例 {i+1}/{self.pool_size} 成功")
                    else:
                        self.logger.error(f"创建浏览器实例 {i+1}/{self.pool_size} 失败")
                except Exception as e:
                    self.logger.error(f"创建浏览器实例 {i+1}/{self.pool_size} 异常: {e}")

        elapsed = time.time() - start_time
        self.logger.info(f"浏览器池初始化完成，成功创建 {len(self.instances)}/{self.pool_size} 个实例，耗时 {elapsed:.2f}秒")

    def _create_browser_instance(self, browser_id: str) -> Optional[BrowserInstance]:
        """创建新的浏览器实例"""
        temp_dir = None
        try:
            # 使用BrowserManager的方法，避免代码重复
            manager = BrowserManager(self.config)

            # 获取Chrome选项（会创建临时目录）
            options = manager._get_chrome_options(profile_name=browser_id)
            temp_dir = manager.temp_dir  # 记录临时目录

            # 获取ChromeDriver路径
            chromedriver_path = manager._get_chromedriver_path()

            # 创建driver
            from selenium.webdriver.chrome.service import Service
            driver = webdriver.Chrome(
                service=Service(chromedriver_path),
                options=options
            )

            # 设置超时
            timeout_config = self.config.get("page_load_timeout", 20)
            implicitly_wait = self.config.get("implicitly_wait", 2)
            driver.implicitly_wait(implicitly_wait)
            driver.set_page_load_timeout(timeout_config)

            # 注入反检测脚本
            driver.execute_cdp_cmd("Page.addScriptToEvaluateOnNewDocument", {
                "source": """
                    Object.defineProperty(navigator, 'webdriver', {
                        get: () => undefined
                    });
                """
            })

            instance = BrowserInstance(
                driver=driver,
                browser_id=browser_id,
                created_at=datetime.now(),
                last_used=datetime.now(),
                temp_dir=temp_dir  # 保存临时目录路径
            )

            self.stats['total_created'] += 1
            return instance

        except Exception as e:
            self.logger.error(f"创建浏览器失败: {e}")
            # 创建失败时清理临时目录
            if temp_dir:
                try:
                    import shutil
                    import os
                    if os.path.exists(temp_dir):
                        shutil.rmtree(temp_dir, ignore_errors=True)
                except:
                    pass
            return None

    @contextmanager
    def get_browser(self, timeout: int = 30):
        """
        获取浏览器实例（上下文管理器）

        使用示例:
            with pool.get_browser() as driver:
                driver.get("https://example.com")
        """
        instance = None
        start_time = time.time()
        self.stats['total_requests'] += 1

        try:
            # 尝试从池中获取可用实例
            try:
                instance = self.available.get(timeout=timeout)
                wait_time = time.time() - start_time

                # 更新平均等待时间
                self.stats['average_wait_time'] = (
                    self.stats['average_wait_time'] * 0.9 + wait_time * 0.1
                )

                # 检查实例是否存活
                if not instance.is_alive():
                    self.logger.warning(f"浏览器实例 {instance.browser_id} 已失效，重新创建")
                    instance.cleanup()  # 使用cleanup方法清理
                    instance = self._create_browser_instance(instance.browser_id)

                if instance:
                    instance.is_busy = True
                    instance.use_count += 1
                    instance.last_used = datetime.now()
                    self.stats['total_reused'] += 1

                    # 清理浏览器状态
                    self._reset_browser_state(instance.driver)

                    yield instance.driver
                else:
                    yield None

            except queue.Empty:
                # 池中没有可用实例，尝试创建新的
                with self.lock:
                    if len(self.instances) < self.max_pool_size:
                        browser_id = f"browser_{len(self.instances)}"
                        instance = self._create_browser_instance(browser_id)
                        if instance:
                            self.instances.append(instance)
                            instance.is_busy = True
                            instance.use_count += 1
                            yield instance.driver
                        else:
                            yield None
                    else:
                        self.logger.warning("达到最大池大小限制，无法创建新实例")
                        yield None

        finally:
            # 归还实例到池中
            if instance and not self.shutdown:
                instance.is_busy = False
                self.available.put(instance)

    def _reset_browser_state(self, driver: webdriver.Chrome):
        """重置浏览器状态，为下次使用做准备"""
        try:
            # 清除cookies
            driver.delete_all_cookies()

            # 清除localStorage和sessionStorage
            driver.execute_script("""
                if (window.localStorage) {
                    window.localStorage.clear();
                }
                if (window.sessionStorage) {
                    window.sessionStorage.clear();
                }
            """)

            # 导航到空白页
            driver.get("about:blank")

            # 关闭多余的窗口/标签
            windows = driver.window_handles
            if len(windows) > 1:
                for window in windows[1:]:
                    driver.switch_to.window(window)
                    driver.close()
                driver.switch_to.window(windows[0])

        except Exception as e:
            self.logger.debug(f"重置浏览器状态时出错: {e}")

    def get_stats(self) -> Dict:
        """获取池统计信息"""
        with self.lock:
            alive_count = sum(1 for inst in self.instances if inst.is_alive())
            busy_count = sum(1 for inst in self.instances if inst.is_busy)

            return {
                **self.stats,
                'pool_size': len(self.instances),
                'alive_count': alive_count,
                'busy_count': busy_count,
                'available_count': self.available.qsize(),
                'reuse_rate': (self.stats['total_reused'] / max(self.stats['total_requests'], 1)) * 100
            }

    def cleanup_idle_instances(self, max_idle_time: int = 300):
        """清理空闲时间过长的实例"""
        current_time = datetime.now()
        with self.lock:
            for instance in self.instances[:]:
                if not instance.is_busy:
                    idle_time = (current_time - instance.last_used).total_seconds()
                    if idle_time > max_idle_time:
                        instance.cleanup()  # 使用cleanup方法
                        self.instances.remove(instance)
                        self.logger.info(f"清理空闲实例 {instance.browser_id}")

    def shutdown_pool(self):
        """关闭所有浏览器实例并清理临时文件"""
        self.shutdown = True
        self.logger.info("关闭浏览器池...")

        with self.lock:
            for instance in self.instances:
                instance.cleanup()  # 使用cleanup方法清理临时文件
                self.logger.debug(f"关闭浏览器 {instance.browser_id}")

            self.instances.clear()

        # 清空队列
        while not self.available.empty():
            try:
                self.available.get_nowait()
            except:
                break

        self.logger.info(f"浏览器池已关闭，统计信息: {self.get_stats()}")

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.shutdown_pool()


# 全局池实例（单例模式）
_global_pool: Optional[BrowserPool] = None
_pool_lock = threading.Lock()


def get_global_pool(config: Dict[str, Any] = None) -> BrowserPool:
    """获取全局浏览器池实例"""
    global _global_pool

    if _global_pool is None:
        with _pool_lock:
            if _global_pool is None:
                _global_pool = BrowserPool(
                    pool_size=4,
                    max_pool_size=9,
                    config=config
                )

    return _global_pool


def reset_global_pool():
    """重置全局池"""
    global _global_pool

    with _pool_lock:
        if _global_pool:
            _global_pool.shutdown_pool()
            _global_pool = None


if __name__ == "__main__":
    # 测试浏览器池
    logging.basicConfig(level=logging.DEBUG)

    config = {
        "headless": False,
        "window_size": "1280,720"
    }

    # 创建池
    with BrowserPool(pool_size=2, max_pool_size=4, config=config) as pool:

        # 测试获取浏览器
        for i in range(5):
            with pool.get_browser() as driver:
                if driver:
                    driver.get("https://www.baidu.com")
                    print(f"请求 {i+1}: {driver.current_url}")
                    time.sleep(1)

        # 查看统计
        print("\n池统计信息:")
        for key, value in pool.get_stats().items():
            print(f"  {key}: {value}")