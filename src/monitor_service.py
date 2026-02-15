#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
余额监控服务 - 核心业务逻辑
"""

import time
import json
import logging
from typing import List, Dict, Tuple, Optional, Callable
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from threading import Lock
from pathlib import Path

try:
    import psutil
    CPU_COUNT = psutil.cpu_count()
except ImportError:
    import os
    CPU_COUNT = os.cpu_count() or 4

from src.config_manager import ConfigManager, Account
from src.browser_manager import BrowserManager
from src.auth_manager import AuthManager, BalanceExtractor
from src.api_balance_client import ApiBalanceClient
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

        # 每日网页登录切日时间（小时，0-23），默认早上8点
        self.daily_rollover_hour = int(
            self.performance_config.get("daily_rollover_hour", 8)
        )
        if self.daily_rollover_hour < 0 or self.daily_rollover_hour > 23:
            self.daily_rollover_hour = 8
        self.logger.info(f"每日网页登录切日时间: {self.daily_rollover_hour:02d}:00")

        # API秒查配置
        api_config = self.config.config.get("api", {})
        api_base_url = str(api_config.get("base_url", ApiBalanceClient.DEFAULT_BASE_URL)).strip()
        api_timeout = int(api_config.get("timeout", 8))
        self.api_fallback_to_web = bool(api_config.get("fallback_to_web", True))
        self.api_balance_client = ApiBalanceClient(
            base_url=api_base_url or ApiBalanceClient.DEFAULT_BASE_URL,
            timeout=max(api_timeout, 1)
        )
        self.logger.info(
            f"API秒查已启用: base_url={self.api_balance_client.base_url}, timeout={self.api_balance_client.timeout}s"
        )
        self.logger.info(
            f"API失败回退网页登录: {'启用' if self.api_fallback_to_web else '禁用'}"
        )

        # 初始化状态
        self.account_status: Dict[str, AccountStatus] = {}
        self.status_lock = Lock()

        # 余额缓存
        self.balance_cache_file = Path(self.config.config_dir) / "balance_cache.json"
        self.balance_cache_lock = Lock()
        self.balance_cache: Dict[str, Dict] = {}

        # 每日首查网页状态
        self.daily_web_state_file = Path(self.config.config_dir) / "daily_web_login_state.json"
        self.daily_web_state_lock = Lock()
        self.daily_web_state: Dict[str, str] = {}

        self._init_account_status()
        self._load_balance_cache()
        self._load_daily_web_state()

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

    def _load_balance_cache(self):
        """加载本地余额缓存"""
        if not self.balance_cache_file.exists():
            self.logger.info(f"余额缓存文件不存在，将在首次查询后创建: {self.balance_cache_file}")
            return

        try:
            with open(self.balance_cache_file, 'r', encoding='utf-8') as f:
                data = json.load(f)
        except Exception as e:
            self.logger.warning(f"读取余额缓存失败: {e}")
            return

        # 兼容两种结构：{accounts: {...}} 或直接 {username: ...}
        if isinstance(data, dict) and isinstance(data.get("accounts"), dict):
            raw_accounts = data.get("accounts", {})
        elif isinstance(data, dict):
            raw_accounts = data
        else:
            raw_accounts = {}

        normalized: Dict[str, Dict] = {}
        for username, item in raw_accounts.items():
            if isinstance(item, dict):
                balance_text = str(item.get("balance", "")).strip()
                updated_at = str(item.get("updated_at", "")).strip()
            else:
                balance_text = str(item).strip()
                updated_at = ""

            if not balance_text:
                continue

            normalized[str(username)] = {
                "balance": balance_text,
                "updated_at": updated_at
            }

        with self.balance_cache_lock:
            self.balance_cache = normalized

        # 启动时直接将缓存余额映射到状态，便于 UI 首屏展示
        with self.status_lock:
            for username, item in normalized.items():
                if username not in self.account_status:
                    continue
                status = self.account_status[username]
                status.balance = item.get("balance", "等待")
                status.status = "缓存"
                status.extra_info["cached_at"] = item.get("updated_at", "")

        if normalized:
            self.logger.info(f"已加载 {len(normalized)} 条余额缓存")

    def _save_balance_cache(self):
        """保存余额缓存到文件"""
        payload = {
            "version": 1,
            "updated_at": datetime.now().isoformat(timespec='seconds'),
            "accounts": self.balance_cache
        }

        tmp_file = self.balance_cache_file.with_suffix(".json.tmp")
        try:
            with open(tmp_file, 'w', encoding='utf-8') as f:
                json.dump(payload, f, indent=2, ensure_ascii=False)
            tmp_file.replace(self.balance_cache_file)
        except Exception as e:
            self.logger.warning(f"写入余额缓存失败: {e}")

    def _update_balance_cache(self, username: str, balance: str,
                              apikey_sync_success: Optional[bool] = None,
                              apikey_sync_message: str = ""):
        """更新单个账号余额缓存"""
        with self.balance_cache_lock:
            record = dict(self.balance_cache.get(username, {}))
            record["balance"] = balance
            record["updated_at"] = datetime.now().isoformat(timespec='seconds')
            if apikey_sync_success is not None:
                record["apikey_sync_success"] = apikey_sync_success
            if apikey_sync_message:
                record["apikey_sync_message"] = apikey_sync_message
            self.balance_cache[username] = record
            self._save_balance_cache()

    def get_cached_balances(self) -> Dict[str, Dict]:
        """获取余额缓存副本，供 UI 启动时加载"""
        with self.balance_cache_lock:
            return {username: dict(item) for username, item in self.balance_cache.items()}

    def _load_daily_web_state(self):
        """加载每日首查网页状态"""
        if not self.daily_web_state_file.exists():
            self.logger.info(f"每日首查状态文件不存在，将在首次网页查询成功后创建: {self.daily_web_state_file}")
            return

        try:
            with open(self.daily_web_state_file, 'r', encoding='utf-8') as f:
                data = json.load(f)
        except Exception as e:
            self.logger.warning(f"读取每日首查状态失败: {e}")
            return

        if isinstance(data, dict) and isinstance(data.get("accounts"), dict):
            raw_accounts = data.get("accounts", {})
        elif isinstance(data, dict):
            raw_accounts = data
        else:
            raw_accounts = {}

        normalized: Dict[str, str] = {}
        for username, day_str in raw_accounts.items():
            value = str(day_str).strip()
            # 仅接受 YYYY-MM-DD
            if len(value) == 10 and value[4] == '-' and value[7] == '-':
                normalized[str(username)] = value

        # 兼容修正：旧版本按00:00切日，若文件在切日前更新且记录为“今天”，自动回拨一天
        corrected_count = 0
        updated_at_raw = str(data.get("updated_at", "")).strip() if isinstance(data, dict) else ""
        if updated_at_raw:
            try:
                updated_at = datetime.fromisoformat(updated_at_raw)
                if updated_at.hour < self.daily_rollover_hour:
                    old_day = updated_at.date().isoformat()
                    new_day = (updated_at.date() - timedelta(days=1)).isoformat()
                    for username, day_str in list(normalized.items()):
                        if day_str == old_day:
                            normalized[username] = new_day
                            corrected_count += 1
            except Exception:
                pass

        with self.daily_web_state_lock:
            self.daily_web_state = normalized

        if corrected_count:
            self.logger.warning(
                f"检测到旧版午夜切日状态，已按{self.daily_rollover_hour:02d}:00规则修正 {corrected_count} 条"
            )
            self._save_daily_web_state()

        if normalized:
            self.logger.info(f"已加载 {len(normalized)} 条每日首查状态")

    def _save_daily_web_state(self):
        """保存每日首查网页状态"""
        payload = {
            "version": 1,
            "updated_at": datetime.now().isoformat(timespec='seconds'),
            "accounts": self.daily_web_state
        }

        tmp_file = self.daily_web_state_file.with_suffix(".json.tmp")
        try:
            with open(tmp_file, 'w', encoding='utf-8') as f:
                json.dump(payload, f, indent=2, ensure_ascii=False)
            tmp_file.replace(self.daily_web_state_file)
        except Exception as e:
            self.logger.warning(f"写入每日首查状态失败: {e}")

    def _should_force_web_query(self, username: str) -> bool:
        """判断账号当天是否必须先走网页登录查询"""
        today = self._current_web_cycle_day()
        with self.daily_web_state_lock:
            last_day = self.daily_web_state.get(username, "")
        should_force = last_day != today
        self.logger.debug(
            f"账号 {username} 每日首查判断: cycle_day={today}, last_day={last_day}, "
            f"rollover={self.daily_rollover_hour:02d}:00, force_web={should_force}"
        )
        return should_force

    def _mark_web_query_success(self, username: str):
        """记录账号当天已完成网页查询"""
        today = self._current_web_cycle_day()
        with self.daily_web_state_lock:
            self.daily_web_state[username] = today
            self._save_daily_web_state()
        self.logger.debug(
            f"账号 {username} 已记录当前周期网页查询成功: cycle_day={today}, "
            f"rollover={self.daily_rollover_hour:02d}:00"
        )

    def _current_web_cycle_day(self) -> str:
        """获取当前网页登录周期日（按切日时间计算）"""
        now = datetime.now()
        if now.hour < self.daily_rollover_hour:
            now = now - timedelta(days=1)
        return now.date().isoformat()

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

            # 每天首次查询强制走网页登录，后续才走API秒查
            force_web_today = self._should_force_web_query(username)
            if force_web_today:
                self.logger.info(f"账号 {username} 当天首次查询，强制走网页登录流程")

            # 非当天首次时，优先走API秒查（需要账号配置API Key）
            if (not force_web_today) and account.api_key:
                self.logger.debug(f"账号 {username} 开始尝试 API 秒查")
                api_result = self.api_balance_client.query_balance(account.api_key)
                if api_result.success and api_result.balance is not None:
                    fast_balance = f"${api_result.balance:.1f}"
                    self.logger.info(
                        f"账号 {username} API秒查成功: {fast_balance} (source={api_result.source})"
                    )

                    with self.status_lock:
                        if username in self.account_status:
                            status = self.account_status[username]
                            status.balance = fast_balance
                            status.status = "正常"
                            status.last_check = datetime.now()
                            status.error_count = 0
                            status.is_checking = False
                            status.extra_info["query_source"] = "api"
                            status.extra_info["query_source_detail"] = api_result.source

                    # 秒查成功也更新本地缓存，保证重启后可见
                    self._update_balance_cache(username=username, balance=fast_balance)

                    if self.on_balance_update:
                        self.on_balance_update(username, fast_balance, True)

                    return username, fast_balance, True

                if not self.api_fallback_to_web:
                    cached_balance = ""
                    with self.balance_cache_lock:
                        cached = self.balance_cache.get(username, {})
                        if isinstance(cached, dict):
                            cached_balance = str(cached.get("balance", "")).strip()

                    final_balance = cached_balance if cached_balance else "API失败"
                    final_success = bool(cached_balance)

                    self.logger.warning(
                        f"账号 {username} API秒查失败，已禁用网页回退: {api_result.message}"
                    )
                    if final_success:
                        self.logger.info(
                            f"账号 {username} 使用缓存余额返回: {final_balance}"
                        )

                    with self.status_lock:
                        if username in self.account_status:
                            status = self.account_status[username]
                            status.balance = final_balance
                            status.status = "正常" if final_success else "异常"
                            status.last_check = datetime.now()
                            status.error_count = 0 if final_success else status.error_count + 1
                            status.is_checking = False
                            status.extra_info["query_source"] = "api"
                            status.extra_info["query_source_detail"] = (
                                f"{api_result.source}|no_web_fallback|{api_result.message}"
                            )

                    if self.on_balance_update:
                        self.on_balance_update(username, final_balance, final_success)

                    return username, final_balance, final_success

                self.logger.debug(
                    f"账号 {username} API秒查失败，按配置回退网页登录: {api_result.message}"
                )

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
                    query_source = "web"
                    query_source_detail = "browser_login_flow"

                    # 查询成功后，尝试同步首个 API Key 额度为当前余额（失败不影响主流程）
                    sync_success = None
                    sync_message = ""
                    if success:
                        # 仅在余额提取成功后记录当天网页登录成功（签到成功）
                        self._mark_web_query_success(username)
                        sync_success, sync_message = auth_mgr.sync_first_apikey_limit(balance)
                        self.logger.debug(
                            f"账号 {username} 同步结果详情: success={sync_success}, message={sync_message}"
                        )
                        if sync_success:
                            self.logger.info(f"账号 {username} 首个 API Key 额度同步成功")
                        else:
                            self.logger.warning(f"账号 {username} 首个 API Key 额度同步失败: {sync_message}")

                        # 网页流程结束后，同轮立即尝试一次API秒查，避免必须等下一轮调度
                        if account.api_key:
                            self.logger.debug(f"账号 {username} 开始同轮 API 秒刷新")
                            post_web_api_result = self.api_balance_client.query_balance(account.api_key)
                            if post_web_api_result.success and post_web_api_result.balance is not None:
                                fast_balance = f"${post_web_api_result.balance:.1f}"
                                balance = fast_balance
                                query_source = "api"
                                query_source_detail = f"{post_web_api_result.source}|post_web_refresh"
                                self.logger.info(
                                    f"账号 {username} 同轮 API 秒刷新成功: {fast_balance} "
                                    f"(source={post_web_api_result.source})"
                                )
                            else:
                                self.logger.debug(
                                    f"账号 {username} 同轮 API 秒刷新失败，保留网页结果: "
                                    f"{post_web_api_result.message}"
                                )
                        else:
                            self.logger.debug(
                                f"账号 {username} 未配置 API Key，无法执行同轮 API 秒刷新"
                            )

                        # 使用最终余额更新本地缓存，供下次启动快速显示
                        self._update_balance_cache(
                            username=username,
                            balance=balance,
                            apikey_sync_success=sync_success,
                            apikey_sync_message=sync_message
                        )
                    else:
                        self.logger.debug(
                            f"账号 {username} 余额提取失败，本次不记录当天网页登录签到成功"
                        )

                    # 更新状态
                    with self.status_lock:
                        if username in self.account_status:
                            status = self.account_status[username]
                            status.balance = balance
                            status.status = "正常" if success else "异常"
                            status.last_check = datetime.now()
                            status.error_count = 0 if success else status.error_count + 1
                            status.is_checking = False
                            status.extra_info["query_source"] = query_source if success else "web"
                            status.extra_info["query_source_detail"] = query_source_detail if success else "browser_login_flow"

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
            with self.balance_cache_lock:
                if username in self.balance_cache:
                    del self.balance_cache[username]
                    self._save_balance_cache()
            with self.daily_web_state_lock:
                if username in self.daily_web_state:
                    del self.daily_web_state[username]
                    self._save_daily_web_state()
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
