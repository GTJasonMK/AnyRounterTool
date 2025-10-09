#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
余额监控服务 - 核心业务逻辑
"""

import time
import logging
from typing import List, Dict, Tuple, Optional, Callable
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from datetime import datetime
from threading import Lock

try:
    import psutil
    CPU_COUNT = psutil.cpu_count()
except ImportError:
    import os
    CPU_COUNT = os.cpu_count() or 4

from src.config_manager import ConfigManager, Account
from src.browser_manager import BrowserManager
from src.auth_manager import AuthManager, BalanceExtractor
from src.browser_pool import BrowserPool, get_global_pool
from src.performance_monitor import get_performance_monitor, OperationTimer


@dataclass
class AccountStatus:
    """账号状态"""
    username: str
    balance: str = "等待"
    status: str = "待机"
    last_check: Optional[datetime] = None
    error_count: int = 0
    is_checking: bool = False
    extra_info: Dict = field(default_factory=dict)


class BalanceMonitorService:
    """余额监控服务"""

    def __init__(self, config_manager: ConfigManager):
        """初始化监控服务"""
        self.config = config_manager
        self.logger = logging.getLogger(__name__)

        # 获取配置
        self.browser_config = self.config.get_browser_config()
        self.performance_config = self.config.get_performance_config()

        # 强制使用headless模式（无感查询）
        self.browser_config["headless"] = True

        # 初始化浏览器池
        self.browser_pool = get_global_pool(self.browser_config)
        self.logger.info(f"使用浏览器池，初始大小: {self.browser_pool.pool_size}")

        # 初始化性能监控
        self.perf_monitor = get_performance_monitor()

        # 初始化状态
        self.account_status: Dict[str, AccountStatus] = {}
        self.status_lock = Lock()
        self._init_account_status()

        # 线程池
        self.max_workers = self._get_max_workers()
        self.executor: Optional[ThreadPoolExecutor] = None

        # 回调函数
        self.on_balance_update: Optional[Callable] = None
        self.on_status_change: Optional[Callable] = None
        self.on_error: Optional[Callable] = None

    def _get_max_workers(self) -> int:
        """获取最大工作线程数"""
        if self.performance_config.get("auto_detect_workers", True):
            # 自动检测：CPU核心数，最多9个
            workers = min(CPU_COUNT, 9)
        else:
            workers = self.performance_config.get("max_workers", 6)

        self.logger.info(f"使用 {workers} 个工作线程")
        return workers

    def _init_account_status(self):
        """初始化账号状态"""
        for account in self.config.accounts:
            self.account_status[account.username] = AccountStatus(
                username=account.username
            )

    def check_single_account(self, account: Account) -> Tuple[str, str, bool]:
        """检查单个账号余额 - 使用浏览器池优化版"""
        username = account.username

        # 启动性能监控
        with OperationTimer(self.perf_monitor, f"查询账号_{username}",
                           {"username": username}) as metrics:

            self.logger.info(f"开始检查账号: {username}")

            # 更新状态
            with self.status_lock:
                if username in self.account_status:
                    self.account_status[username].is_checking = True
                    self.account_status[username].status = "查询中"

            # 触发状态变更回调
            if self.on_status_change:
                self.on_status_change(username, "查询中")

            try:
                # 从池中获取浏览器实例
                with self.browser_pool.get_browser() as driver:
                    if not driver:
                        raise Exception("无法获取浏览器实例")

                    # 创建临时的BrowserManager包装器(为了兼容现有的AuthManager)
                    browser_mgr = BrowserManager(self.browser_config)
                    browser_mgr.driver = driver  # 直接设置driver

                    # 登录
                    auth_mgr = AuthManager(browser_mgr)
                    login_result = auth_mgr.login(
                        account.username,
                        account.password,
                        retry_times=self.performance_config.get("retry_times", 3)
                    )

                    if not login_result.success:
                        raise Exception(login_result.message)

                    # 提取余额
                    balance_ext = BalanceExtractor(browser_mgr)
                    balance, success = balance_ext.extract_balance()

                    # 更新状态
                    with self.status_lock:
                        if username in self.account_status:
                            status = self.account_status[username]
                            status.balance = balance
                            status.status = "正常" if success else "异常"
                            status.last_check = datetime.now()
                            status.error_count = 0 if success else status.error_count + 1
                            status.is_checking = False

                    # 触发余额更新回调
                    if self.on_balance_update:
                        self.on_balance_update(username, balance, success)

                    self.logger.info(f"账号 {username} 检查完成: {balance} (耗时: {time.time() - metrics.start_time:.2f}秒)")
                    return username, balance, success

            except Exception as e:
                error_msg = str(e)
                self.logger.error(f"账号 {username} 检查失败: {error_msg}")

                # 更新错误状态
                with self.status_lock:
                    if username in self.account_status:
                        status = self.account_status[username]
                        status.balance = "错误"
                        status.status = "异常"
                        status.last_check = datetime.now()
                        status.error_count += 1
                        status.is_checking = False

                # 触发错误回调
                if self.on_error:
                    self.on_error(username, error_msg)

                raise  # 重新抛出异常，让OperationTimer记录失败

    def check_all_accounts(self, accounts: Optional[List[Account]] = None) -> List[Tuple[str, str, bool]]:
        """检查所有账号 - 使用并行查询（无头模式）"""
        return self.check_all_accounts_parallel(accounts)

    def check_all_accounts_parallel(self, accounts: Optional[List[Account]] = None) -> List[Tuple[str, str, bool]]:
        """并发检查所有账号（headless模式下并行查询）- 性能优化版"""
        if accounts is None:
            accounts = self.config.accounts

        if not accounts:
            self.logger.warning("没有账号需要检查")
            return []

        # 启动总体性能监控
        with OperationTimer(self.perf_monitor, "批量查询账号",
                           {"count": len(accounts)}) as batch_metrics:

            self.logger.info(f"开始检查 {len(accounts)} 个账号")
            results = []

            # 使用线程池并发执行
            with ThreadPoolExecutor(max_workers=self.max_workers) as executor:
                # 提交所有任务
                futures = {
                    executor.submit(self.check_single_account, account): account
                    for account in accounts
                }

                # 收集结果
                for future in as_completed(futures):
                    try:
                        result = future.result(
                            timeout=self.performance_config.get("timeout", 90)
                        )
                        results.append(result)
                    except Exception as e:
                        account = futures[future]
                        self.logger.error(f"账号 {account.username} 执行异常: {e}")
                        results.append((account.username, "超时", False))

            self.logger.info(f"所有账号检查完成，共 {len(results)} 个结果 (总耗时: {time.time() - batch_metrics.start_time:.2f}秒)")

            # 打印性能报告
            if self.logger.isEnabledFor(logging.INFO):
                pool_stats = self.browser_pool.get_stats()
                self.logger.info(f"浏览器池统计: 复用率={pool_stats.get('reuse_rate', 0):.1f}%, "
                               f"可用实例={pool_stats.get('available_count', 0)}")

            return results

    def start_periodic_check(self, interval: Optional[int] = None):
        """启动定期检查"""
        if interval is None:
            interval = self.performance_config.get("query_interval", 60)

        self.logger.info(f"启动定期检查，间隔 {interval} 秒")

        import threading
        self.check_thread = threading.Thread(
            target=self._periodic_check_worker,
            args=(interval,),
            daemon=True
        )
        self.check_thread.start()

    def _periodic_check_worker(self, interval: int):
        """定期检查工作线程"""
        while True:
            try:
                self.check_all_accounts()
            except Exception as e:
                self.logger.error(f"定期检查异常: {e}")

            time.sleep(interval)

    def get_account_status(self, username: str) -> Optional[AccountStatus]:
        """获取账号状态"""
        with self.status_lock:
            return self.account_status.get(username)

    def get_all_status(self) -> Dict[str, AccountStatus]:
        """获取所有账号状态"""
        with self.status_lock:
            return self.account_status.copy()

    def reset_account_status(self, username: str):
        """重置账号状态"""
        with self.status_lock:
            if username in self.account_status:
                self.account_status[username] = AccountStatus(username=username)
                self.logger.info(f"重置账号状态: {username}")

    def add_account(self, account: Account) -> bool:
        """添加账号到监控"""
        if self.config.add_account(account.username, account.password, account.api_key):
            with self.status_lock:
                self.account_status[account.username] = AccountStatus(
                    username=account.username
                )
            return True
        return False

    def remove_account(self, username: str) -> bool:
        """从监控中移除账号"""
        if self.config.remove_account(username):
            with self.status_lock:
                if username in self.account_status:
                    del self.account_status[username]
            return True
        return False

    def get_statistics(self) -> Dict:
        """获取统计信息"""
        with self.status_lock:
            total = len(self.account_status)
            normal = sum(1 for s in self.account_status.values() if s.status == "正常")
            error = sum(1 for s in self.account_status.values() if s.status == "异常")
            checking = sum(1 for s in self.account_status.values() if s.is_checking)

            # 添加性能统计
            perf_stats = self.perf_monitor.get_stats()
            system_metrics = self.perf_monitor.get_system_metrics()
            pool_stats = self.browser_pool.get_stats() if self.browser_pool else {}

            return {
                "total": total,
                "normal": normal,
                "error": error,
                "checking": checking,
                "success_rate": f"{(normal/total*100):.1f}%" if total > 0 else "0%",
                "performance": perf_stats,
                "system": system_metrics,
                "browser_pool": pool_stats
            }

    def get_performance_report(self) -> str:
        """获取性能报告"""
        return self.perf_monitor.generate_report()


if __name__ == "__main__":
    # 测试监控服务
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )

    # 初始化配置
    config = ConfigManager()

    # 创建监控服务
    service = BalanceMonitorService(config)

    # 设置回调
    def on_update(username, balance, success):
        status = "✓" if success else "✗"
        print(f"[{status}] {username}: {balance}")

    service.on_balance_update = on_update

    # 检查所有账号
    results = service.check_all_accounts()

    # 打印统计
    stats = service.get_statistics()
    print(f"\n统计信息: {stats}")