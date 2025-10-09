#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
配置管理模块 - 处理所有配置相关功能
"""

import os
import json
import logging
from typing import List, Dict, Tuple, Optional
from dataclasses import dataclass, asdict
from pathlib import Path

@dataclass
class Account:
    """账号数据类"""
    username: str
    password: str
    api_key: str = ""

    def __str__(self):
        return f"Account({self.username})"

    def to_dict(self):
        return asdict(self)

class ConfigManager:
    """配置管理器"""

    DEFAULT_CONFIG = {
        "browser": {
            "headless": True,
            "timeout": 10,
            "page_load_timeout": 20,  # 原始脚本的值
            "implicitly_wait": 2,      # 原始脚本的值
            "window_size": "1920,1080",
            "user_agent": None,
            "disable_images": True,
            "disable_javascript": False
        },
        "performance": {
            "max_workers": 9,  # 增加默认工作线程
            "auto_detect_workers": True,
            "query_interval": 60,
            "retry_times": 2,  # 减少重试次数
            "retry_delay": 3  # 减少重试延迟
        },
        "ui": {
            "window_size": [320, 280],
            "collapsed_size": [50, 50],
            "stay_on_top": True,
            "collapse_delay": 600  # 毫秒
        },
        "logging": {
            "level": "INFO",
            "file": "anyrouter_monitor.log"
        }
    }

    def __init__(self, config_dir: str = "."):
        """初始化配置管理器"""
        self.config_dir = Path(config_dir)
        self.config_file = self.config_dir / "config.json"
        self.credentials_file = self.config_dir / "credentials.txt"
        self.accounts: List[Account] = []
        self.config: Dict = {}

        # 初始化日志
        self.setup_logging()
        self.logger = logging.getLogger(__name__)

        # 加载配置
        self.load_config()
        self.load_accounts()

    def setup_logging(self):
        """设置日志系统"""
        log_config = self.DEFAULT_CONFIG.get("logging", {})
        logging.basicConfig(
            level=getattr(logging, log_config.get("level", "INFO")),
            format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
            datefmt='%Y-%m-%d %H:%M:%S'
        )

    def load_config(self) -> Dict:
        """加载配置文件"""
        try:
            if self.config_file.exists():
                with open(self.config_file, 'r', encoding='utf-8') as f:
                    user_config = json.load(f)
                    # 合并用户配置和默认配置
                    self.config = self._merge_configs(self.DEFAULT_CONFIG, user_config)
                    self.logger.info(f"配置文件加载成功: {self.config_file}")
            else:
                self.config = self.DEFAULT_CONFIG.copy()
                self.save_config()
                self.logger.info(f"创建默认配置文件: {self.config_file}")
        except Exception as e:
            self.logger.error(f"加载配置文件失败: {e}")
            self.config = self.DEFAULT_CONFIG.copy()

        return self.config

    def save_config(self):
        """保存配置到文件"""
        try:
            with open(self.config_file, 'w', encoding='utf-8') as f:
                json.dump(self.config, f, indent=2, ensure_ascii=False)
            self.logger.info(f"配置已保存到: {self.config_file}")
        except Exception as e:
            self.logger.error(f"保存配置失败: {e}")

    def _merge_configs(self, default: Dict, user: Dict) -> Dict:
        """递归合并配置字典"""
        result = default.copy()
        for key, value in user.items():
            if key in result and isinstance(result[key], dict) and isinstance(value, dict):
                result[key] = self._merge_configs(result[key], value)
            else:
                result[key] = value
        return result

    def load_accounts(self) -> List[Account]:
        """加载账号信息"""
        self.accounts = []

        if not self.credentials_file.exists():
            self.logger.warning(f"账号文件不存在: {self.credentials_file}")
            # 创建示例文件
            self.create_sample_credentials()
            return self.accounts

        try:
            with open(self.credentials_file, 'r', encoding='utf-8') as f:
                for line_num, line in enumerate(f, 1):
                    line = line.strip()
                    if not line or line.startswith('#'):
                        continue

                    parts = line.split(',')
                    if len(parts) >= 2:
                        username = parts[0].strip()
                        password = parts[1].strip()
                        api_key = parts[2].strip() if len(parts) >= 3 else ""

                        account = Account(username, password, api_key)
                        self.accounts.append(account)
                        self.logger.debug(f"加载账号: {account}")
                    else:
                        self.logger.warning(f"第{line_num}行格式错误: {line}")

            self.logger.info(f"成功加载 {len(self.accounts)} 个账号")
        except Exception as e:
            self.logger.error(f"加载账号文件失败: {e}")

        return self.accounts

    def create_sample_credentials(self):
        """创建示例账号文件"""
        sample_content = """# AnyRouter账号配置文件
# 格式: 用户名,密码,API_KEY(可选)
# 示例:
# user1,password1,sk-xxxxxxxx
# user2,password2,sk-yyyyyyyy
"""
        try:
            with open(self.credentials_file, 'w', encoding='utf-8') as f:
                f.write(sample_content)
            self.logger.info(f"创建示例账号文件: {self.credentials_file}")
        except Exception as e:
            self.logger.error(f"创建示例文件失败: {e}")

    def add_account(self, username: str, password: str, api_key: str = "") -> bool:
        """添加账号"""
        account = Account(username, password, api_key)

        # 检查是否已存在
        for acc in self.accounts:
            if acc.username == username:
                self.logger.warning(f"账号已存在: {username}")
                return False

        self.accounts.append(account)
        self.save_accounts()
        self.logger.info(f"添加账号: {username}")
        return True

    def remove_account(self, username: str) -> bool:
        """删除账号"""
        for i, acc in enumerate(self.accounts):
            if acc.username == username:
                del self.accounts[i]
                self.save_accounts()
                self.logger.info(f"删除账号: {username}")
                return True

        self.logger.warning(f"账号不存在: {username}")
        return False

    def update_account(self, username: str, password: Optional[str] = None,
                      api_key: Optional[str] = None) -> bool:
        """更新账号信息"""
        for acc in self.accounts:
            if acc.username == username:
                if password is not None:
                    acc.password = password
                if api_key is not None:
                    acc.api_key = api_key
                self.save_accounts()
                self.logger.info(f"更新账号: {username}")
                return True

        self.logger.warning(f"账号不存在: {username}")
        return False

    def save_accounts(self):
        """保存账号到文件"""
        try:
            lines = ["# AnyRouter账号配置文件\n", "# 格式: 用户名,密码,API_KEY(可选)\n"]
            for acc in self.accounts:
                line = f"{acc.username},{acc.password}"
                if acc.api_key:
                    line += f",{acc.api_key}"
                lines.append(line + "\n")

            with open(self.credentials_file, 'w', encoding='utf-8') as f:
                f.writelines(lines)

            self.logger.info(f"账号已保存到: {self.credentials_file}")
        except Exception as e:
            self.logger.error(f"保存账号失败: {e}")

    def get_account(self, username: str) -> Optional[Account]:
        """获取指定账号"""
        for acc in self.accounts:
            if acc.username == username:
                return acc
        return None

    def get_account_by_api_key(self, api_key: str) -> Optional[Account]:
        """通过API Key获取账号"""
        for acc in self.accounts:
            if acc.api_key == api_key:
                return acc
        return None

    def get_browser_config(self) -> Dict:
        """获取浏览器配置"""
        return self.config.get("browser", {})

    def get_performance_config(self) -> Dict:
        """获取性能配置"""
        return self.config.get("performance", {})

    def get_ui_config(self) -> Dict:
        """获取UI配置"""
        return self.config.get("ui", {})

    def update_config_value(self, section: str, key: str, value):
        """更新配置值"""
        if section in self.config:
            self.config[section][key] = value
            self.save_config()
            self.logger.info(f"更新配置: {section}.{key} = {value}")
            return True
        return False

if __name__ == "__main__":
    # 测试配置管理器
    config = ConfigManager()

    print(f"加载账号数: {len(config.accounts)}")
    print(f"浏览器配置: {config.get_browser_config()}")
    print(f"性能配置: {config.get_performance_config()}")
    print(f"UI配置: {config.get_ui_config()}")