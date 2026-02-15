#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
悬浮窗口UI - 完全仿照原版设计
"""

import os
import sys
import json
import logging
import subprocess
from concurrent.futures import ThreadPoolExecutor, wait
from typing import Optional, List, Dict, Any, Tuple
from datetime import datetime
from pathlib import Path

from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QTableWidget, QTableWidgetItem, QPushButton, QLabel, QMenu,
    QMessageBox, QHeaderView, QTextEdit
)
from PyQt6.QtCore import (
    Qt, QThread, pyqtSignal, QTimer, QPoint, QRect, QSize
)
from PyQt6.QtGui import (
    QAction, QPainter, QBrush, QColor, QFont, QPen,
    QLinearGradient, QCursor
)

from src.config_manager import ConfigManager, Account
from src.monitor_service import BalanceMonitorService


class MonitorWorker(QThread):
    """监控工作线程"""
    result = pyqtSignal(str, str, bool)  # username, balance, success
    progress = pyqtSignal(str, str)  # username, progress_message
    finished = pyqtSignal()

    def __init__(self, service: BalanceMonitorService):
        super().__init__()
        self.service = service
        # 设置为守护线程，主程序退出时自动结束
        self.setTerminationEnabled(True)

    def run(self):
        """执行监控任务"""
        # 设置回调
        self.service.on_balance_update = lambda u, b, s: self.result.emit(u, b, s)
        self.service.on_progress = lambda u, m: self.progress.emit(u, m)

        # 执行检查
        results = self.service.check_all_accounts()

        self.finished.emit()


class FloatingMonitor(QMainWindow):
    """悬浮监控窗口 - 仿照原版"""

    def __init__(self):
        super().__init__()
        self.logger = logging.getLogger(__name__)

        # 初始化配置和服务
        self.config = ConfigManager()
        self.service = BalanceMonitorService(self.config)

        # 工作线程
        self.worker: Optional[MonitorWorker] = None

        # UI状态
        self.is_expanded = False
        self.drag_pos: Optional[QPoint] = None
        self.hover_timer = QTimer()
        self.hover_timer.timeout.connect(self.start_collapse)
        self.collapsed_center = None  # 记忆小圆圈的中心点

        # 配置文件路径
        self.claude_settings_path = Path.home() / ".claude" / "settings.json"
        self.codex_auth_path = self._resolve_codex_auth_path()

        # 读取当前外部配置
        self.current_env_token = self._load_current_token()
        self.current_openai_key = self._load_current_openai_key()

        # 初始化UI
        self.init_ui()
        self.load_accounts()

        # 启动时为收缩状态
        self.set_collapsed_state()

        # 添加键盘快捷键
        from PyQt6.QtGui import QShortcut, QKeySequence

        # Ctrl+Q - 退出
        self.quit_shortcut = QShortcut(QKeySequence("Ctrl+Q"), self)
        self.quit_shortcut.activated.connect(self.close)

        # F5 - 刷新查询
        self.refresh_shortcut = QShortcut(QKeySequence("F5"), self)
        self.refresh_shortcut.activated.connect(self.query)

        # Esc - 收缩窗口
        self.collapse_shortcut = QShortcut(QKeySequence("Esc"), self)
        self.collapse_shortcut.activated.connect(self.direct_collapse)

        # Ctrl+L - 切换进度日志
        self.toggle_log_shortcut = QShortcut(QKeySequence("Ctrl+L"), self)
        self.toggle_log_shortcut.activated.connect(self.toggle_progress)

        # Ctrl+Shift+C - 复制总余额
        self.copy_total_shortcut = QShortcut(QKeySequence("Ctrl+Shift+C"), self)
        self.copy_total_shortcut.activated.connect(self.copy_total_balance)

    def _load_current_token(self) -> str:
        """从Claude配置文件加载当前Token"""
        try:
            if not self.claude_settings_path.exists():
                self.logger.warning(f"Claude配置文件不存在: {self.claude_settings_path}")
                return ""

            with open(self.claude_settings_path, 'r', encoding='utf-8') as f:
                settings = json.load(f)
                # Claude配置格式: {"env": {"ANTHROPIC_AUTH_TOKEN": "..."}}
                env_settings = settings.get('env', {})
                token = env_settings.get('ANTHROPIC_AUTH_TOKEN', '')
                if token:
                    self.logger.info(f"从Claude配置加载Token: {token[:15]}...")
                return token

        except Exception as e:
            self.logger.error(f"读取Claude配置文件失败: {e}")
            return ""

    def _resolve_codex_auth_path(self) -> Path:
        """解析Codex配置路径，兼容 Windows 与 WSL"""
        self.local_codex_paths: List[Path] = []

        env_override = os.environ.get("CODEX_AUTH_PATH")
        if env_override:
            self.local_codex_paths.append(Path(env_override).expanduser())

        default_path = Path.home() / ".codex" / "auth.json"
        self.local_codex_paths.append(default_path)

        # 去除本地路径重复
        unique_local = []
        local_seen = set()
        for path in self.local_codex_paths:
            normalized = str(path)
            if normalized in local_seen:
                continue
            local_seen.add(normalized)
            unique_local.append(path)
        self.local_codex_paths = unique_local

        # 枚举 WSL 目标
        self.wsl_targets = self._discover_wsl_codex_targets()

        candidates: List[Path] = list(self.local_codex_paths)
        for target in self.wsl_targets:
            candidates.append(target["windows_path"])

        unique_candidates: List[Path] = []
        visited = set()
        for path in candidates:
            normalized = str(path)
            if normalized in visited:
                continue
            visited.add(normalized)
            unique_candidates.append(path)

        if not unique_candidates:
            self.logger.warning("未找到Codex配置候选路径，将使用默认路径: %s", default_path)
            self.local_codex_paths = [default_path]
            return default_path

        for path in unique_candidates:
            try:
                if path.exists():
                    self.logger.info(f"检测到Codex配置文件: {path}")
                    return path
            except Exception as e:
                self.logger.debug(f"检测Codex配置路径失败: {path} - {e}")

        fallback = unique_candidates[0]
        self.logger.info(f"未发现现有Codex配置文件，使用候选路径: {fallback}")
        return fallback

    def _decode_wsl_output(self, data: Optional[bytes]) -> str:
        if not data:
            return ""

        for encoding in ("utf-16-le", "utf-8", "gbk"):
            try:
                return data.decode(encoding)
            except UnicodeDecodeError:
                continue

        return data.decode("utf-8", errors="ignore")

    def _run_wsl_command(self, args: List[str], timeout: int = 5) -> Tuple[int, str, str]:
        try:
            result = subprocess.run(
                args,
                capture_output=True,
                text=False,
                check=False,
                timeout=timeout
            )
        except FileNotFoundError:
            raise
        except Exception as e:
            raise RuntimeError(str(e)) from e

        stdout = self._decode_wsl_output(result.stdout)
        stderr = self._decode_wsl_output(result.stderr)
        return result.returncode, stdout, stderr

    def _discover_wsl_codex_targets(self) -> List[Dict[str, Any]]:
        """枚举WSL目录下可能存在的Codex配置路径"""
        targets: List[Dict[str, Any]] = []

        if os.name != "nt":
            return targets

        try:
            returncode, stdout, stderr = self._run_wsl_command(["wsl.exe", "-l", "-q"], timeout=5)
        except FileNotFoundError:
            self.logger.debug("当前系统未安装 wsl.exe，跳过 WSL 路径枚举")
            return targets
        except Exception as e:
            self.logger.debug(f"执行 wsl.exe 枚举失败: {e}")
            return targets

        if returncode != 0:
            self.logger.debug(
                "wsl.exe -l -q 返回错误，stdout=%s stderr=%s",
                stdout.strip(),
                stderr.strip()
            )
            return targets

        normalized_stdout = stdout.replace('\x00', '').strip()

        if not normalized_stdout:
            self.logger.info("wsl.exe -l -q 未返回发行版列表")
            return targets

        distros = [line.strip("\ufeff \t") for line in normalized_stdout.splitlines() if line.strip()]
        if not distros:
            return targets

        for distro in distros:
            home_path = self._query_wsl_home(distro)
            if not home_path:
                continue

            linux_file = home_path.rstrip('/') + "/.codex/auth.json"

            windows_path = self._build_wsl_windows_path(distro, linux_file)

            targets.append({
                "distro": distro,
                "home": home_path,
                "windows_path": windows_path,
                "linux_path": linux_file
            })

        if targets:
            distro_summary = sorted({target["distro"] for target in targets if target.get("distro")})
            self.logger.info(
                "检测到 %d 个WSL Codex目标: %s",
                len(targets),
                ", ".join(distro_summary)
            )
        else:
            self.logger.info("未检测到任何WSL发行版的Codex目标")

        return targets

    def _build_wsl_windows_path(self, distro: str, linux_file: str) -> Path:
        preferred_roots = [Path(r"\\wsl.localhost"), Path(r"\\wsl$")]
        chosen_root: Optional[Path] = None

        for root in preferred_roots:
            base = root / distro
            try:
                if base.exists():
                    chosen_root = root
                    break
            except OSError:
                continue

        if chosen_root is None:
            chosen_root = preferred_roots[0]

        windows_path = chosen_root / distro
        for part in linux_file.split('/'):
            if part:
                windows_path /= part

        return windows_path

    def _read_openai_key_from_wsl(self, target: Dict[str, Any]) -> str:
        """通过 wsl.exe 从发行版读取 OpenAI Key"""
        distro = target.get("distro")
        linux_path = target.get("linux_path")
        if not distro or not linux_path:
            return ""

        script = f"if [ -f '{linux_path}' ]; then cat '{linux_path}'; fi"

        try:
            returncode, stdout, stderr = self._run_wsl_command(
                ["wsl.exe", "-d", distro, "-e", "sh", "-lc", script],
                timeout=5
            )
        except FileNotFoundError:
            self.logger.debug("wsl.exe 不存在，无法读取WSL配置")
            return ""
        except Exception as e:
            self.logger.debug(f"读取 WSL 配置失败: {distro} - {e}")
            return ""

        if returncode != 0 or not stdout.strip():
            return ""

        try:
            settings = json.loads(stdout)
            return settings.get('OPENAI_API_KEY', '')
        except json.JSONDecodeError as e:
            self.logger.error(f"解析WSL Codex配置失败({distro}): {e}")
        except Exception as e:
            self.logger.error(f"读取WSL Codex配置失败({distro}): {e}")

        return ""

    def _query_wsl_home(self, distro: str) -> str:
        """查询指定发行版的默认 HOME 路径"""
        try:
            returncode, stdout, stderr = self._run_wsl_command(
                ["wsl.exe", "-d", distro, "-e", "sh", "-lc", "printf %s \"$HOME\""],
                timeout=5
            )
        except FileNotFoundError:
            self.logger.debug("wsl.exe 不存在，无法查询 HOME")
            return ""
        except Exception as e:
            self.logger.debug(f"查询 WSL HOME 目录失败: {distro} - {e}")
            return ""

        if returncode != 0:
            self.logger.debug(
                "获取 WSL HOME 目录失败: %s stdout=%s stderr=%s",
                distro,
                stdout.strip(),
                stderr.strip()
            )
            return ""

        return stdout.replace('\x00', '').strip()

    def _load_current_openai_key(self) -> str:
        """从Codex配置文件加载当前OpenAI Key"""
        # 尝试本地 Windows 路径
        for path in getattr(self, "local_codex_paths", []):
            try:
                if not path.exists():
                    continue

                with open(path, 'r', encoding='utf-8') as f:
                    settings = json.load(f)
                    key = settings.get('OPENAI_API_KEY', '')
                    if key:
                        self.logger.info(f"从Codex配置加载OpenAI Key: {key[:15]}...")
                        return key
            except Exception as e:
                self.logger.debug(f"读取Codex配置失败({path}): {e}")

        # 尝试通过 WSL 读取
        for target in getattr(self, "wsl_targets", []):
            key = self._read_openai_key_from_wsl(target)
            if key:
                self.logger.info(
                    "从WSL发行版加载OpenAI Key: %s (%s)",
                    key[:15] + "...",
                    target.get('distro', 'unknown')
                )
                return key

        self.logger.warning("未读取到任何OpenAI Key")
        return ""

    def _save_token_to_claude_settings(self, token: str) -> bool:
        """保存Token到Claude配置文件"""
        try:
            # 确保目录存在
            self.claude_settings_path.parent.mkdir(parents=True, exist_ok=True)

            # 读取现有配置
            settings = {}
            if self.claude_settings_path.exists():
                try:
                    with open(self.claude_settings_path, 'r', encoding='utf-8') as f:
                        settings = json.load(f)
                except json.JSONDecodeError:
                    self.logger.warning("现有配置文件格式错误，将创建新配置")
                    settings = {}

            # 确保env字段存在
            if 'env' not in settings:
                settings['env'] = {}

            # 更新Token（保持Claude配置的嵌套结构）
            settings['env']['ANTHROPIC_AUTH_TOKEN'] = token

            # 保存配置
            with open(self.claude_settings_path, 'w', encoding='utf-8') as f:
                json.dump(settings, f, indent=2, ensure_ascii=False)

            self.logger.info(f"成功保存Token到Claude配置文件: {self.claude_settings_path}")
            return True

        except Exception as e:
            self.logger.error(f"保存Token到Claude配置失败: {e}")
            return False

    def _save_openai_key_to_codex_auth(self, token: str, target_path: Optional[Path] = None) -> Tuple[bool, str]:
        """保存OpenAI Key到Codex配置文件"""
        path = target_path or self.codex_auth_path
        try:
            # 确保目录存在
            path.parent.mkdir(parents=True, exist_ok=True)

            # 读取现有配置
            settings = {}
            if path.exists():
                try:
                    with open(path, 'r', encoding='utf-8') as f:
                        settings = json.load(f)
                except json.JSONDecodeError:
                    self.logger.warning("Codex配置文件格式错误，将创建新配置")
                    settings = {}

            # 更新Key
            settings['OPENAI_API_KEY'] = token

            # 保存配置
            with open(path, 'w', encoding='utf-8') as f:
                json.dump(settings, f, indent=2, ensure_ascii=False)

            self.logger.info(f"成功保存OpenAI Key到Codex配置文件: {path}")
            return True, ""

        except Exception as e:
            self.logger.error(f"保存OpenAI Key到Codex配置失败: {e}")
            return False, str(e)

    def _save_openai_key_to_wsl(self, target: Dict[str, Any], token: str) -> Tuple[bool, str]:
        """通过 wsl.exe 保存 OpenAI Key"""
        distro = target.get("distro")
        home_path = target.get("home")
        linux_path = target.get("linux_path")
        if not distro or not home_path or not linux_path:
            return False, "WSL 目标信息不完整"

        json_content = json.dumps({'OPENAI_API_KEY': token}, ensure_ascii=False, indent=2)
        linux_dir = home_path.rstrip('/') + "/.codex"

        script = (
            f"mkdir -p '{linux_dir}' && cat <<'EOF' > '{linux_path}'\n"
            f"{json_content}\nEOF"
        )

        try:
            returncode, stdout, stderr = self._run_wsl_command(
                ["wsl.exe", "-d", distro, "-e", "sh", "-lc", script],
                timeout=10
            )
        except FileNotFoundError:
            self.logger.error("wsl.exe 不存在，无法写入WSL配置")
            return False, "wsl.exe 不存在"
        except Exception as e:
            self.logger.error(f"写入WSL Codex配置失败({distro}): {e}")
            return False, str(e)

        if returncode != 0:
            self.logger.error(
                "写入WSL Codex配置失败(%s): return=%s stderr=%s",
                distro,
                returncode,
                stderr
            )
            return False, stderr or "执行命令失败"

        self.logger.info(
            "成功写入WSL Codex配置: %s (%s)",
            linux_path,
            distro
        )
        return True, ""

    def init_ui(self):
        """初始化UI - 紧凑版布局"""
        self.setWindowTitle("余额监控")

        # 窗口大小设置 - 进一步缩小高度，只显示3行
        self.collapsed_size = (50, 50)
        self.expanded_size = (320, 200)  # 大幅缩小高度
        self.setFixedSize(*self.expanded_size)

        # 存储总余额用于收缩态显示
        self.current_total_balance = 0.0

        # 设置窗口属性：无边框、置顶、透明背景
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint |
            Qt.WindowType.WindowStaysOnTopHint |
            Qt.WindowType.Tool
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)

        # 主容器
        self.container = QWidget()
        self.setCentralWidget(self.container)

        # 创建主布局
        main_layout = QVBoxLayout(self.container)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)

        # 创建内容区域
        self.content_widget = QWidget()
        self.content_widget.setObjectName("content")
        main_layout.addWidget(self.content_widget)

        # 内容布局 - 减小边距和间距
        layout = QVBoxLayout(self.content_widget)
        layout.setContentsMargins(8, 8, 8, 8)  # 15→8 节省空间
        layout.setSpacing(4)  # 8→4 节省高度

        # 设置紧凑版样式
        self.setStyleSheet("""
            #content {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:1,
                    stop:0 rgba(20, 20, 30, 230),
                    stop:1 rgba(30, 30, 45, 230));
                border-radius: 20px;
                border: 1px solid rgba(100, 100, 255, 0.2);
            }
            #content:hover {
                border: 1px solid rgba(150, 150, 255, 0.4);
            }
            QPushButton {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
                    stop:0 #5555ff,
                    stop:1 #8855ff);
                border: none;
                border-radius: 12px;
                color: white;
                font-size: 11px;
                font-weight: bold;
                padding: 4px 8px;
                min-height: 18px;
            }
            QPushButton:hover {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
                    stop:0 #6666ff,
                    stop:1 #9966ff);
            }
            QPushButton:pressed {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
                    stop:0 #4444ee,
                    stop:1 #7744ee);
            }
            QTableWidget {
                background: rgba(20, 20, 30, 100);
                border: 1px solid rgba(100, 100, 255, 0.1);
                border-radius: 6px;
                color: #e0e0e0;
                gridline-color: rgba(100, 100, 255, 0.05);
                selection-background-color: rgba(100, 100, 255, 0.3);
            }
            QTableWidget::item {
                padding: 2px;
                border: none;
            }
            QTableWidget::item:selected {
                background: rgba(100, 100, 255, 0.3);
            }
            QHeaderView::section {
                background: rgba(40, 40, 60, 180);
                color: #c0c0ff;
                border: none;
                padding: 2px;
                font-size: 10px;
                font-weight: bold;
            }
            QTextEdit {
                background: rgba(15, 15, 25, 80);
                border: none;
                color: #a0a0d0;
                font-size: 8px;
                padding: 2px;
                line-height: 1.3;
            }
            QScrollBar:vertical {
                background: rgba(20, 20, 30, 50);
                width: 6px;
                border-radius: 3px;
            }
            QScrollBar::handle:vertical {
                background: rgba(100, 100, 255, 0.3);
                border-radius: 3px;
                min-height: 15px;
            }
            QScrollBar::handle:vertical:hover {
                background: rgba(100, 100, 255, 0.5);
            }
            QScrollBar::add-line:vertical,
            QScrollBar::sub-line:vertical {
                height: 0px;
            }
            QLabel {
                color: #a0a0c0;
                background: transparent;
            }
            QMenu {
                background: rgba(25, 25, 35, 240);
                border: 1px solid rgba(100, 100, 255, 0.2);
                border-radius: 6px;
            }
            QMenu::item {
                color: #e0e0e0;
                padding: 5px 15px;
                border-radius: 3px;
                margin: 2px 3px;
            }
            QMenu::item:selected {
                background: rgba(100, 100, 255, 0.3);
            }
            QMenu::separator {
                height: 1px;
                background: rgba(100, 100, 255, 0.1);
                margin: 3px 6px;
            }
        """)

        # 创建收缩状态的标签 - 显示总余额
        self.collapsed_label = QLabel("$0")
        self.collapsed_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.collapsed_label.setStyleSheet("""
            QLabel {
                color: #e0e0ff;
                font-size: 13px;
                font-weight: bold;
                background: transparent;
            }
        """)
        self.collapsed_label.hide()
        layout.addWidget(self.collapsed_label)

        # 按钮行 - 查询和退出并排
        btn_layout = QHBoxLayout()
        btn_layout.setSpacing(4)

        self.btn = QPushButton("查询")
        self.btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn.clicked.connect(self.query)
        btn_layout.addWidget(self.btn)

        self.quit_btn = QPushButton("退出")
        self.quit_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.quit_btn.clicked.connect(self.force_quit)
        self.quit_btn.setStyleSheet("""
            QPushButton {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
                    stop:0 #ff5555,
                    stop:1 #ff8855);
                border: none;
                border-radius: 12px;
                color: white;
                font-size: 10px;
                font-weight: bold;
                padding: 4px 8px;
                min-height: 18px;
            }
            QPushButton:hover {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
                    stop:0 #ff6666,
                    stop:1 #ff9966);
            }
            QPushButton:pressed {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
                    stop:0 #ee4444,
                    stop:1 #ee7744);
            }
        """)
        btn_layout.addWidget(self.quit_btn)

        layout.addLayout(btn_layout)

        # 环境变量状态显示 - 精简
        self.env_label = QLabel("Claude: 检测中... | OpenAI: 检测中...")
        self.env_label.setStyleSheet("font-size: 8px; color: #7070a0; padding: 1px;")
        layout.addWidget(self.env_label)

        # 表格 - 固定高度只显示3行
        self.table = QTableWidget()
        self.table.setColumnCount(3)
        self.table.setHorizontalHeaderLabels(["用户", "余额", "状态"])
        self.table.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.table.customContextMenuRequested.connect(self.show_context_menu)
        self.table.verticalHeader().setVisible(False)
        self.table.setAlternatingRowColors(True)

        # 设置固定高度只显示3行
        # 表头约18px + 3行×18px = 72px
        self.table.setMaximumHeight(108)
        self.table.setMinimumHeight(108)

        # 设置行高
        self.table.verticalHeader().setDefaultSectionSize(18)

        # 设置列宽
        header = self.table.horizontalHeader()
        header.setStretchLastSection(True)
        header.setMinimumSectionSize(40)  # 最小列宽

        layout.addWidget(self.table)

        # 创建进度文本框（初始隐藏）- 同样限制高度
        self.progress_text = QTextEdit()
        self.progress_text.setReadOnly(True)
        self.progress_text.setPlaceholderText("查询进度...")
        self.progress_text.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.progress_text.setMaximumHeight(72)
        self.progress_text.setMinimumHeight(72)
        self.progress_text.hide()
        layout.addWidget(self.progress_text)

        # 底部控制行 - 切换按钮和总余额
        bottom_layout = QHBoxLayout()
        bottom_layout.setSpacing(4)

        # 添加切换进度按钮
        self.toggle_btn = QPushButton("▼进度")
        self.toggle_btn.setMaximumWidth(50)
        self.toggle_btn.setMaximumHeight(16)
        self.toggle_btn.clicked.connect(self.toggle_progress)
        self.toggle_btn.setStyleSheet("""
            QPushButton {
                background: rgba(60, 60, 80, 100);
                border: none;
                border-radius: 3px;
                color: #a0a0c0;
                font-size: 8px;
                padding: 1px 3px;
            }
            QPushButton:hover {
                background: rgba(80, 80, 100, 150);
            }
        """)
        bottom_layout.addWidget(self.toggle_btn)

        # 总余额显示
        self.total_label = QLabel("总余额: --")
        self.total_label.setStyleSheet("""
            font-size: 10px;
            color: #90d090;
            padding: 2px;
            font-weight: bold;
        """)
        self.total_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        bottom_layout.addWidget(self.total_label)

        layout.addLayout(bottom_layout)

        # 设置初始位置（右侧中央偏下）
        screen = QApplication.primaryScreen().availableGeometry()
        initial_x = screen.width() - 80
        initial_y = screen.height() // 2 + 100
        self.move(initial_x, initial_y)

        # 记录初始中心点
        self.collapsed_center = QPoint(
            initial_x + self.collapsed_size[0] // 2,
            initial_y + self.collapsed_size[1] // 2
        )

    def _build_account_display_name(self, account: Account) -> str:
        """构造账号显示名称，附带状态标记"""
        markers: List[str] = []
        if account.api_key and account.api_key == self.current_env_token:
            markers.append("●")
        if account.api_key and account.api_key == self.current_openai_key:
            markers.append("◎")

        if markers:
            return f"{''.join(markers)} {account.username}"
        return account.username

    def _find_username_by_key(self, key: str) -> str:
        """根据API Key查找用户名"""
        for account in self.config.accounts:
            if account.api_key == key:
                return account.username
        return "未知"

    def load_accounts(self):
        """加载账号列表"""
        try:
            accounts = self.config.accounts
            if not accounts:
                self.logger.warning("没有找到账号配置")
                self.add_progress("⚠ 没有找到账号配置，请检查 credentials.txt")
                return

            cached_balances = self.service.get_cached_balances()
            cache_hit_count = 0
            latest_cache_time = ""

            self.table.setRowCount(len(accounts))

            for i, account in enumerate(accounts):
                display_name = self._build_account_display_name(account)
                self.table.setItem(i, 0, QTableWidgetItem(display_name))

                cache_item = cached_balances.get(account.username, {})
                cached_balance = str(cache_item.get("balance", "")).strip()
                cached_at = str(cache_item.get("updated_at", "")).strip()

                if cached_balance:
                    cache_hit_count += 1
                    if cached_at and cached_at > latest_cache_time:
                        latest_cache_time = cached_at

                    self.table.setItem(i, 1, QTableWidgetItem(cached_balance))
                    status_item = QTableWidgetItem("缓存")
                    status_item.setForeground(QColor("#ffcc66"))
                    self.table.setItem(i, 2, status_item)
                else:
                    self.table.setItem(i, 1, QTableWidgetItem("等待"))
                    self.table.setItem(i, 2, QTableWidgetItem("待机"))

            # 更新环境变量状态显示
            self.update_env_status_display()
            self.update_total_balance()

            if cache_hit_count > 0:
                if latest_cache_time:
                    self.add_progress(f"已加载 {cache_hit_count} 个账号缓存余额（更新时间: {latest_cache_time}）")
                else:
                    self.add_progress(f"已加载 {cache_hit_count} 个账号缓存余额")

            self.logger.info(f"成功加载 {len(accounts)} 个账号")
        except Exception as e:
            self.logger.error(f"加载账号失败: {e}")
            QMessageBox.critical(
                self,
                "加载失败",
                f"加载账号配置失败: {str(e)}\n\n请检查 credentials.txt 文件格式"
            )

    def toggle_progress(self):
        """切换进度显示"""
        try:
            if self.progress_text.isVisible():
                # 切换回表格视图
                self.progress_text.hide()
                self.table.show()
                self.toggle_btn.setText("▼进度")
                self.logger.debug("切换到表格视图")
            else:
                # 切换到进度视图
                self.progress_text.show()
                self.table.hide()
                self.toggle_btn.setText("▲账号")
                self.logger.debug("切换到进度视图")
        except Exception as e:
            self.logger.error(f"切换视图失败: {e}")

    def add_progress(self, message: str):
        """添加进度信息"""
        try:
            from datetime import datetime
            timestamp = datetime.now().strftime("%H:%M:%S")
            self.progress_text.append(f"[{timestamp}] {message}")
            # 自动滚动到底部
            cursor = self.progress_text.textCursor()
            cursor.movePosition(cursor.MoveOperation.End)
            self.progress_text.setTextCursor(cursor)
        except Exception as e:
            self.logger.error(f"添加进度信息失败: {e}")

    def update_progress(self, username: str, message: str):
        """更新查询进度"""
        try:
            self.add_progress(f"{username}: {message}")
        except Exception as e:
            self.logger.error(f"更新进度失败: {e}")

    def copy_total_balance(self):
        """复制总余额到剪贴板"""
        try:
            clipboard = QApplication.clipboard()
            balance_text = f"${self.current_total_balance:.2f}"
            clipboard.setText(balance_text)
            self.logger.info(f"已复制总余额: {balance_text}")
            self.add_progress(f"已复制总余额到剪贴板: {balance_text}")
        except Exception as e:
            self.logger.error(f"复制总余额失败: {e}")
            self.add_progress(f"✗ 复制失败: {str(e)}")

    def update_env_status_display(self):
        """更新Claude配置状态显示 - 精简版"""
        claude_user = "未设置"
        if self.current_env_token:
            claude_user = self._find_username_by_key(self.current_env_token)

        openai_user = "未设置"
        if self.current_openai_key:
            openai_user = self._find_username_by_key(self.current_openai_key)

        env_text = f"Claude: {claude_user} | OpenAI: {openai_user}"
        self.env_label.setText(env_text)

    def show_context_menu(self, position):
        """显示右键菜单"""
        item = self.table.itemAt(position)
        if item is None:
            return

        row = item.row()
        if row >= len(self.config.accounts):
            return

        # 获取账号信息
        account = self.config.accounts[row]
        username = account.username
        apikey = account.api_key if account.api_key else ""

        if not apikey:
            return

        # 创建右键菜单
        menu = QMenu(self)

        # 复制API Key选项
        copy_action = QAction(f"复制 {username} 的API Key", self)
        copy_action.triggered.connect(lambda checked=False, key=apikey: self.copy_apikey(key))
        menu.addAction(copy_action)

        # 分隔线
        menu.addSeparator()

        # 设置Claude配置选项
        is_current = apikey == self.current_env_token
        if is_current:
            env_action = QAction(f"● 当前Claude配置", self)
            env_action.setEnabled(False)  # 禁用，只用于显示状态
        else:
            env_action = QAction(f"设为Claude配置Token", self)
            env_action.triggered.connect(
                lambda checked=False, name=username, key=apikey: self.set_env_token(name, key)
            )

        menu.addAction(env_action)

        # 设置OpenAI配置选项
        is_openai_current = apikey == self.current_openai_key
        if is_openai_current:
            openai_action = QAction("◎ 当前OpenAI配置", self)
            openai_action.setEnabled(False)
        else:
            openai_action = QAction("设为OpenAI配置Key", self)
            openai_action.triggered.connect(
                lambda checked=False, name=username, key=apikey: self.set_openai_key(name, key)
            )

        menu.addAction(openai_action)

        # 显示菜单
        menu.exec(self.table.mapToGlobal(position))

    def copy_apikey(self, apikey):
        """复制API key到剪贴板"""
        clipboard = QApplication.clipboard()
        clipboard.setText(apikey)
        self.logger.info(f"已复制API Key: {apikey[:20]}...")

    def set_env_token(self, username, apikey):
        """设置Claude配置文件中的Token"""
        try:
            self.logger.info(f"正在为 {username} 设置Claude配置Token...")

            # 保存到Claude配置文件
            if self._save_token_to_claude_settings(apikey):
                # 更新当前Token
                self.current_env_token = apikey

                # 刷新显示
                self.refresh_user_display()
                self.update_env_status_display()

                # 成功消息
                QMessageBox.information(
                    self,
                    "Claude配置更新成功",
                    f"已将 {username} 的API Key设置为Claude配置Token\n\n"
                    f"配置文件: {self.claude_settings_path}\n"
                    f"Token: {apikey[:15]}...\n\n"
                    f"配置已立即生效"
                )

                self.logger.info(f"Claude配置更新成功: {username}")
                self.add_progress(f"✓ 已设置 {username} 为Claude配置Token")
                return True
            else:
                error_msg = f"无法写入Claude配置文件\n\n请检查文件权限: {self.claude_settings_path}"
                QMessageBox.critical(self, "设置失败", error_msg)
                self.logger.error(f"保存Token到Claude配置失败: 文件写入失败")
                self.add_progress(f"✗ 设置Claude配置失败: 文件写入失败")
                return False

        except Exception as e:
            error_msg = f"Claude配置设置失败: {str(e)}"
            QMessageBox.warning(self, "设置失败", error_msg)
            self.logger.error(f"设置Claude配置失败: {e}", exc_info=True)
            self.add_progress(f"✗ 设置Claude配置失败: {str(e)}")
            return False

    def set_openai_key(self, username, apikey):
        """设置Codex配置文件中的OpenAI Key"""
        try:
            self.logger.info(f"正在为 {username} 设置OpenAI配置Key...")

            # 每次操作前重新解析路径，确保捕获最新环境
            self.codex_auth_path = self._resolve_codex_auth_path()

            wsl_targets = getattr(self, "wsl_targets", [])
            self.logger.debug(
                "WSL 目标数量: %d", len(wsl_targets)
            )
            if wsl_targets:
                self.add_progress(
                    f"检测到 {len(wsl_targets)} 个WSL目标: "
                    + ", ".join(sorted({t.get('distro', '?') for t in wsl_targets}))
                )
            else:
                self.add_progress("未检测到可写入的WSL目标，将仅写入Windows路径")

            results: List[Dict[str, Any]] = []

            for path in getattr(self, "local_codex_paths", []):
                success, error = self._save_openai_key_to_codex_auth(apikey, path)
                results.append({
                    "success": success,
                    "label": f"Windows路径: {path}",
                    "error": error,
                    "path": str(path)
                })

            for target in getattr(self, "wsl_targets", []):
                success, error = self._save_openai_key_to_wsl(target, apikey)
                label = f"WSL[{target.get('distro', 'unknown')}]: {target.get('linux_path', '')}"
                results.append({
                    "success": success,
                    "label": label,
                    "error": error,
                    "path": target.get('linux_path', '')
                })

            if not results:
                QMessageBox.warning(
                    self,
                    "未写入",
                    "未找到任何可写入的Codex配置目标，请检查环境配置。"
                )
                self.logger.warning("未找到可写入的Codex配置目标")
                self.add_progress("✗ 设置OpenAI配置失败: 无可用目标")
                return False

            success_count = sum(1 for item in results if item['success'])

            message_lines = [
                f"账号: {username}",
                f"Key: {apikey[:15]}...",
                ""
            ]

            summary_parts = []
            for item in results:
                symbol = "✓" if item['success'] else "✗"
                line = f"{symbol} {item['label']}"
                if item['error']:
                    line += f"\n   原因: {item['error']}"
                message_lines.append(line)
                summary_parts.append(f"{symbol}{item['label']}")
                progress_line = f"{symbol} {item['label']}"
                if item['error']:
                    progress_line += f" | 原因: {item['error']}"
                self.add_progress(progress_line)

            message_text = "\n".join(message_lines)

            if success_count > 0:
                self.current_openai_key = apikey
                self.refresh_user_display()
                self.update_env_status_display()

                QMessageBox.information(
                    self,
                    "OpenAI配置更新结果",
                    message_text
                )

                self.logger.info(f"OpenAI配置更新完成: {username} ({success_count}/{len(results)})")
                self.add_progress(f"OpenAI配置写入结果: {'; '.join(summary_parts)}")
                return True

            QMessageBox.critical(
                self,
                "设置失败",
                message_text
            )
            self.logger.error(f"OpenAI配置设置失败: 未能写入任何目标 ({username})")
            self.add_progress(f"✗ 设置OpenAI配置失败: {'; '.join(summary_parts)}")
            return False

        except Exception as e:
            error_msg = f"OpenAI配置设置失败: {str(e)}"
            QMessageBox.warning(self, "设置失败", error_msg)
            self.logger.error(f"设置OpenAI配置失败: {e}", exc_info=True)
            self.add_progress(f"✗ 设置OpenAI配置失败: {str(e)}")
            return False

    def refresh_user_display(self):
        """刷新用户显示，更新环境变量标记"""
        for i, account in enumerate(self.config.accounts):
            item = self.table.item(i, 0)
            if item is None:
                item = QTableWidgetItem()
                self.table.setItem(i, 0, item)
            item.setText(self._build_account_display_name(account))

    def _show_closing_dialog(self):
        """显示退出动画对话框 - 在软件窗口正中央"""
        from PyQt6.QtWidgets import QDialog, QVBoxLayout, QLabel, QTextEdit
        from PyQt6.QtCore import Qt, QTimer

        # 创建对话框 - 紧凑尺寸
        dialog = QDialog(self)
        dialog.setWindowTitle("正在退出")
        dialog.setModal(True)
        dialog.setFixedSize(260, 180)  # 更紧凑的尺寸

        # 无边框，置顶
        dialog.setWindowFlags(
            Qt.WindowType.FramelessWindowHint |
            Qt.WindowType.WindowStaysOnTopHint |
            Qt.WindowType.Dialog
        )

        # 设置样式 - 紧凑版本
        dialog.setStyleSheet("""
            QDialog {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:1,
                    stop:0 rgba(25, 25, 35, 245),
                    stop:1 rgba(35, 35, 50, 245));
                border-radius: 12px;
                border: 2px solid rgba(120, 120, 255, 0.5);
            }
            QLabel#title {
                color: #e0e0ff;
                font-size: 12px;
                font-weight: bold;
                background: transparent;
                padding: 4px;
            }
            QTextEdit {
                background: rgba(15, 15, 25, 150);
                border: 1px solid rgba(80, 80, 120, 0.3);
                border-radius: 6px;
                color: #b0b0e0;
                font-size: 8px;
                font-family: 'Consolas', 'Monaco', monospace;
                padding: 4px;
                line-height: 1.2;
            }
        """)

        layout = QVBoxLayout(dialog)
        layout.setContentsMargins(12, 10, 12, 10)  # 减小内边距
        layout.setSpacing(8)  # 减小间距

        # 标题 - 更简洁
        title_label = QLabel("清理资源中...")
        title_label.setObjectName("title")
        title_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(title_label)

        # 进度显示文本框
        progress_text = QTextEdit()
        progress_text.setReadOnly(True)
        progress_text.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        progress_text.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        layout.addWidget(progress_text)

        # 保存对话框引用
        self.cleanup_dialog = dialog
        self.cleanup_progress_text = progress_text

        # 计算位置 - 相对于主窗口居中
        main_geometry = self.geometry()
        dialog_x = main_geometry.x() + (main_geometry.width() - dialog.width()) // 2
        dialog_y = main_geometry.y() + (main_geometry.height() - dialog.height()) // 2
        dialog.move(dialog_x, dialog_y)

        # 显示对话框
        dialog.show()
        QApplication.processEvents()

        # 启动清理流程
        QTimer.singleShot(100, self._start_cleanup_sequence)

        return dialog

    def _add_cleanup_log(self, message: str, level: str = "info"):
        """添加清理日志到对话框"""
        from datetime import datetime
        timestamp = datetime.now().strftime("%H:%M:%S")  # 去掉毫秒

        # 根据级别设置颜色
        color_map = {
            "info": "#90b0ff",
            "success": "#50ff80",
            "warning": "#ffb050",
            "error": "#ff5050",
            "debug": "#a0a0d0"
        }
        color = color_map.get(level, "#b0b0e0")

        # 添加带颜色的HTML格式文本 - 紧凑格式
        html = f'<span style="color: {color};">[{timestamp}] {message}</span>'
        self.cleanup_progress_text.append(html)

        # 滚动到底部
        cursor = self.cleanup_progress_text.textCursor()
        cursor.movePosition(cursor.MoveOperation.End)
        self.cleanup_progress_text.setTextCursor(cursor)

        # 强制刷新UI
        QApplication.processEvents()

    def _start_cleanup_sequence(self):
        """启动清理序列，逐步执行并显示进度"""
        from PyQt6.QtCore import QTimer

        self._add_cleanup_log("="*40, "info")  # 减少分隔线长度
        self._add_cleanup_log("开始清理资源...", "info")
        self._add_cleanup_log("="*40, "info")

        # 步骤1: 停止计时器
        QTimer.singleShot(50, self._cleanup_step1_timers)

    def _cleanup_step1_timers(self):
        """清理步骤1: 停止计时器"""
        from PyQt6.QtCore import QTimer

        self._add_cleanup_log("► 1/5: 停止计时器", "info")  # 更简洁的步骤标题
        try:
            if hasattr(self, 'hover_timer') and self.hover_timer:
                self.hover_timer.stop()
                self._add_cleanup_log("  ✓ 已停止", "success")
            else:
                self._add_cleanup_log("  - 无计时器", "debug")
        except Exception as e:
            self._add_cleanup_log(f"  ✗ 失败: {e}", "error")

        QTimer.singleShot(80, self._cleanup_step2_worker)  # 减少等待时间

    def _cleanup_step2_worker(self):
        """清理步骤2: 终止工作线程"""
        from PyQt6.QtCore import QTimer

        self._add_cleanup_log("► 2/5: 终止工作线程", "info")
        try:
            if hasattr(self, 'worker') and self.worker and self.worker.isRunning():
                self._add_cleanup_log("  - 发现运行中线程", "debug")
                self.worker.terminate()
                if self.worker.wait(1000):
                    self._add_cleanup_log("  ✓ 已终止", "success")
                else:
                    self._add_cleanup_log("  ⚠ 强制结束", "warning")
            else:
                self._add_cleanup_log("  - 无线程", "debug")
        except Exception as e:
            self._add_cleanup_log(f"  ✗ 失败: {e}", "error")

        QTimer.singleShot(100, self._cleanup_step3_browser_pool)

    def _cleanup_step3_browser_pool(self):
        """清理步骤3: 清理浏览器池"""
        from PyQt6.QtCore import QTimer

        self._add_cleanup_log("► 3/5: 清理浏览器池", "info")
        try:
            from src.browser_pool import _global_pool
            if _global_pool and _global_pool.instances:
                count = len(_global_pool.instances)
                self._add_cleanup_log(f"  - 发现 {count} 个实例", "debug")

                for idx, instance in enumerate(_global_pool.instances):
                    try:
                        instance.driver.quit()
                        self._add_cleanup_log(f"  ✓ 实例 {idx+1}/{count}", "success")
                    except Exception as e:
                        self._add_cleanup_log(f"  ⚠ 实例 {idx+1} 失败", "warning")

                _global_pool.instances.clear()
                self._add_cleanup_log(f"  ✓ 已清空", "success")
            else:
                self._add_cleanup_log("  - 池为空", "debug")
        except Exception as e:
            self._add_cleanup_log(f"  ✗ 失败: {e}", "error")

        QTimer.singleShot(150, self._cleanup_step4_chrome_processes)

    def _cleanup_step4_chrome_processes(self):
        """清理步骤4: 清理Chrome进程"""
        from PyQt6.QtCore import QTimer

        self._add_cleanup_log("► 4/5: 清理Chrome进程", "info")
        try:
            import psutil
            import subprocess

            killed_count = 0

            # Windows使用taskkill
            if os.name == 'nt':
                self._add_cleanup_log("  - 运行taskkill...", "debug")
                try:
                    result = subprocess.run(
                        ['taskkill', '/F', '/IM', 'chrome.exe', '/T'],
                        capture_output=True, timeout=2, text=True
                    )
                    if result.returncode == 0:
                        self._add_cleanup_log("  ✓ chrome.exe", "success")

                    result = subprocess.run(
                        ['taskkill', '/F', '/IM', 'chromedriver.exe', '/T'],
                        capture_output=True, timeout=2, text=True
                    )
                    if result.returncode == 0:
                        self._add_cleanup_log("  ✓ chromedriver.exe", "success")
                except Exception as e:
                    self._add_cleanup_log(f"  ⚠ taskkill失败", "warning")

            # 使用psutil扫描残留进程
            self._add_cleanup_log("  - 扫描残留...", "debug")
            for proc in psutil.process_iter(['name', 'pid']):
                try:
                    name = proc.info['name'].lower()
                    if 'chrome' in name or 'chromedriver' in name:
                        proc.kill()
                        killed_count += 1
                        self._add_cleanup_log(f"  ✓ PID:{proc.info['pid']}", "success")
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    pass

            if killed_count > 0:
                self._add_cleanup_log(f"  ✓ 清理 {killed_count} 个进程", "success")
            else:
                self._add_cleanup_log("  - 无残留", "debug")

        except Exception as e:
            self._add_cleanup_log(f"  ✗ 失败: {e}", "error")

        QTimer.singleShot(150, self._cleanup_step5_finalize)

    def _cleanup_step5_finalize(self):
        """清理步骤5: 完成清理"""
        from PyQt6.QtCore import QTimer

        self._add_cleanup_log("► 5/5: 完成", "info")
        self._add_cleanup_log("="*40, "info")
        self._add_cleanup_log("✓ 清理完成", "success")
        self._add_cleanup_log("正在退出...", "info")
        self._add_cleanup_log("="*40, "info")

        # 等待800ms让用户看到完成消息
        QTimer.singleShot(800, self._do_final_exit)

    def _do_final_exit(self):
        """最终退出"""
        import os
        self.logger.info("程序退出")
        os._exit(0)

    def _cleanup_all_resources(self):
        """统一的资源清理方法"""
        self.logger.info("开始清理所有资源...")

        try:
            # 1. 停止计时器
            if hasattr(self, 'hover_timer') and self.hover_timer:
                self.hover_timer.stop()
                self.logger.debug("已停止悬停计时器")

            # 2. 强制终止工作线程
            if hasattr(self, 'worker') and self.worker and self.worker.isRunning():
                self.logger.info("正在终止工作线程...")
                self.worker.terminate()
                self.worker.wait(500)
                self.logger.info("工作线程已终止")

            # 3. 清理浏览器池
            try:
                from src.browser_pool import _global_pool
                if _global_pool:
                    self.logger.info(f"正在清理浏览器池 ({len(_global_pool.instances)} 个实例)...")
                    futures = []
                    max_workers = min(8, max(1, len(_global_pool.instances)))
                    with ThreadPoolExecutor(max_workers=max_workers) as executor:
                        for idx, instance in enumerate(_global_pool.instances):
                            futures.append(executor.submit(self._shutdown_browser_instance, idx, instance))
                        done, not_done = wait(futures, timeout=5)
                        for future in not_done:
                            future.cancel()
                            self.logger.debug("浏览器实例关闭超时，已取消任务")
                    _global_pool.instances.clear()
                    self.logger.info("浏览器池已清理")
            except Exception as e:
                self.logger.debug(f"清理浏览器池时出错: {e}")

            # 4. 强制杀死所有Chrome和ChromeDriver进程
            self.logger.info("正在清理Chrome进程...")
            import psutil
            import subprocess

            killed_count = 0

            # Windows使用taskkill命令
            if os.name == 'nt':
                try:
                    result = subprocess.run(
                        ['taskkill', '/F', '/IM', 'chrome.exe', '/T'],
                        capture_output=True, timeout=2, text=True
                    )
                    if result.returncode == 0:
                        self.logger.debug("taskkill已终止chrome.exe")

                    result = subprocess.run(
                        ['taskkill', '/F', '/IM', 'chromedriver.exe', '/T'],
                        capture_output=True, timeout=2, text=True
                    )
                    if result.returncode == 0:
                        self.logger.debug("taskkill已终止chromedriver.exe")
                except Exception as e:
                    self.logger.debug(f"taskkill命令失败: {e}")

            # 使用psutil杀死残留进程
            try:
                for proc in psutil.process_iter(['name', 'pid']):
                    try:
                        name = proc.info['name'].lower()
                        if 'chrome' in name or 'chromedriver' in name:
                            proc.kill()
                            killed_count += 1
                            self.logger.debug(f"已终止进程: {proc.info['name']} (PID: {proc.info['pid']})")
                    except (psutil.NoSuchProcess, psutil.AccessDenied):
                        pass
            except Exception as e:
                self.logger.debug(f"使用psutil清理进程失败: {e}")

            if killed_count > 0:
                self.logger.info(f"已清理 {killed_count} 个Chrome相关进程")
            else:
                self.logger.info("没有发现需要清理的Chrome进程")

            # 5. 清理临时目录（如果有）
            try:
                import tempfile
                import shutil
                temp_base = tempfile.gettempdir()
                self.logger.debug(f"检查临时目录: {temp_base}")
                # 这里可以添加清理特定临时文件的逻辑
            except Exception as e:
                self.logger.debug(f"清理临时目录时出错: {e}")

            self.logger.info("资源清理完成")

        except Exception as e:
            self.logger.error(f"清理资源时发生错误: {e}")

    def _shutdown_browser_instance(self, idx: int, instance: Any):
        """并行关闭浏览器实例"""
        try:
            self.logger.debug(f"正在关闭浏览器实例 {idx+1}...")

            driver = getattr(instance, 'driver', None)
            service = getattr(driver, 'service', None)

            # 优先直接终止 Chromedriver 进程，避免 quit 阻塞
            if service is not None:
                proc = getattr(service, 'process', None)
                if proc is not None and proc.poll() is None:
                    try:
                        proc.kill()
                        proc.wait(timeout=2)
                        self.logger.debug(f"已终止 Chromedriver 进程 (实例 {idx+1})")
                    except Exception as kill_err:
                        self.logger.debug(f"终止 Chromedriver 进程失败 (实例 {idx+1}): {kill_err}")

            if driver is not None:
                try:
                    driver.quit()
                except Exception as quit_err:
                    self.logger.debug(f"调用 driver.quit() 失败 (实例 {idx+1}): {quit_err}")
        except Exception as e:
            self.logger.debug(f"关闭浏览器实例 {idx+1} 失败: {e}")

    def _do_force_quit(self):
        """执行强制退出"""
        self.logger.info("执行强制退出...")

        # 调用统一的清理方法
        self._cleanup_all_resources()

        # 强制退出
        import os
        self.logger.info("程序即将退出")
        os._exit(0)

    def force_quit(self):
        """强制退出程序"""
        self.logger.info("用户点击退出按钮，准备退出...")
        # 显示退出动画对话框
        self._show_closing_dialog()

    def show_main_context_menu(self, pos):
        """显示主窗口右键菜单"""
        menu = QMenu(self)

        # 退出选项
        quit_action = QAction("退出 (Ctrl+Q)", self)
        quit_action.triggered.connect(self.close)
        menu.addAction(quit_action)

        # 显示菜单
        menu.exec(pos)

    def query(self):
        """开始查询"""
        try:
            if self.worker and self.worker.isRunning():
                self.add_progress("查询正在进行中，请稍候...")
                return

            # 检查是否有账号
            if self.table.rowCount() == 0:
                self.add_progress("✗ 没有账号可查询，请先配置账号")
                QMessageBox.warning(
                    self,
                    "无法查询",
                    "没有找到账号配置\n\n请检查 credentials.txt 文件"
                )
                return

            self.btn.setText("查询中...")
            self.btn.setEnabled(False)

            # 查询时保持展开状态
            self.hover_timer.stop()

            # 清空并初始化进度显示
            self.progress_text.clear()
            self.add_progress("="*50)
            self.add_progress("开始查询所有账号...")
            self.add_progress(f"共 {self.table.rowCount()} 个账号待查询")
            self.add_progress("="*50)

            # 自动切换到进度视图
            if not self.progress_text.isVisible():
                self.toggle_progress()

            for i in range(self.table.rowCount()):
                self.table.item(i, 1).setText("查询中...")
                self.table.item(i, 2).setText("...")

            # 创建并启动工作线程
            self.worker = MonitorWorker(self.service)
            self.worker.result.connect(self.update_result)
            self.worker.progress.connect(self.update_progress)
            self.worker.finished.connect(self.query_done)
            self.worker.start()

            self.logger.info(f"开始查询 {self.table.rowCount()} 个账号")

        except Exception as e:
            self.logger.error(f"启动查询失败: {e}", exc_info=True)
            self.add_progress(f"✗ 启动查询失败: {str(e)}")
            self.btn.setText("查 询")
            self.btn.setEnabled(True)
            QMessageBox.critical(
                self,
                "查询失败",
                f"启动查询时发生错误:\n\n{str(e)}"
            )

    def update_result(self, user, balance, success):
        """更新查询结果"""
        for i in range(self.table.rowCount()):
            # 检查用户名（可能带有●标记）
            current_display = self.table.item(i, 0).text()
            actual_username = current_display
            for marker in ("●", "◎"):
                actual_username = actual_username.replace(marker, "")
            actual_username = actual_username.strip()

            if actual_username == user:
                self.table.item(i, 1).setText(balance)
                self.table.item(i, 2).setText("OK" if success else "ERR")

                # 设置状态颜色
                status_item = self.table.item(i, 2)
                if success:
                    status_item.setForeground(QColor("#4caf50"))  # 绿色
                    # 添加成功日志
                    self.add_progress(f"✓ {user}: {balance} - 查询成功")
                else:
                    status_item.setForeground(QColor("#f44336"))  # 红色
                    # 添加失败日志
                    self.add_progress(f"✗ {user}: {balance} - 查询失败")
                break

    def query_done(self):
        """查询完成"""
        self.btn.setText("查 询")
        self.btn.setEnabled(True)

        # 计算并显示总余额
        self.update_total_balance()

        # 统计查询结果
        total_count = self.table.rowCount()
        success_count = 0
        fail_count = 0

        for i in range(total_count):
            status = self.table.item(i, 2).text()
            if status == "OK":
                success_count += 1
            elif status == "ERR":
                fail_count += 1

        # 添加汇总日志
        self.add_progress("="*50)
        self.add_progress(f"查询完成！成功: {success_count}/{total_count}, 失败: {fail_count}")
        if success_count > 0:
            self.add_progress(f"总余额: ${self.current_total_balance:.2f}")
        self.add_progress("="*50)

        # 查询完成后启动自动收缩计时器
        if not self.underMouse():
            self.hover_timer.start(2000)  # 2秒后自动收缩

    def update_total_balance(self):
        """计算并更新总余额显示"""
        total = 0.0
        success_count = 0

        for i in range(self.table.rowCount()):
            balance_text = self.table.item(i, 1).text()
            status_text = self.table.item(i, 2).text()

            # 统计成功查询与缓存余额
            if status_text in ("OK", "缓存"):
                try:
                    # 尝试解析余额（移除可能的货币符号和格式）
                    balance_str = balance_text.replace('$', '').replace('¥', '').replace(',', '').strip()
                    balance = float(balance_str)
                    total += balance
                    success_count += 1
                except (ValueError, AttributeError):
                    # 无法解析的余额跳过
                    pass

        # 保存总余额用于收缩状态显示
        self.current_total_balance = total

        # 更新展开状态的显示
        if success_count > 0:
            self.total_label.setText(f"总余额: ${total:.2f} ({success_count}个账号)")
            self.total_label.setStyleSheet("""
                font-size: 12px;
                color: #90ff90;
                padding: 4px;
                font-weight: bold;
            """)
            # 更新收缩状态的显示
            self.collapsed_label.setText(f"${total:.0f}")
        else:
            self.total_label.setText("总余额: --")
            self.total_label.setStyleSheet("""
                font-size: 12px;
                color: #a0a0c0;
                padding: 4px;
                font-weight: bold;
            """)
            # 无数据时显示$0
            self.collapsed_label.setText("$0")

    def set_collapsed_state(self):
        """设置为收缩状态"""
        self.is_expanded = False

        # 记忆当前中心点位置
        if self.collapsed_center is None:
            current_rect = self.geometry()
            self.collapsed_center = current_rect.center()

        # 隐藏所有控件除了收缩图标
        self.btn.hide()
        self.env_label.hide()
        self.table.hide()
        self.progress_text.hide()
        self.toggle_btn.hide()
        self.total_label.hide()
        self.quit_btn.hide()
        self.collapsed_label.show()

        # 调整窗口大小
        self.setFixedSize(*self.collapsed_size)

        # 更新样式为圆形
        self.content_widget.setStyleSheet("""
            #content {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:1,
                    stop:0 rgba(50, 50, 80, 200),
                    stop:1 rgba(80, 60, 100, 200));
                border-radius: 25px;
                border: 2px solid rgba(130, 130, 255, 0.5);
            }
            #content:hover {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:1,
                    stop:0 rgba(60, 60, 90, 220),
                    stop:1 rgba(90, 70, 110, 220));
                border: 2px solid rgba(150, 150, 255, 0.7);
            }
        """)

        # 设置鼠标样式为可移动
        self.setCursor(Qt.CursorShape.SizeAllCursor)

    def set_expanded_state(self):
        """设置为展开状态"""
        self.is_expanded = True

        # 显示所有控件
        self.collapsed_label.hide()
        self.btn.show()
        self.env_label.show()
        self.table.show()
        self.toggle_btn.show()
        self.total_label.show()
        self.quit_btn.show()

        # 恢复样式
        self.content_widget.setStyleSheet("""
            #content {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:1,
                    stop:0 rgba(20, 20, 30, 230),
                    stop:1 rgba(30, 30, 45, 230));
                border-radius: 25px;
                border: 1px solid rgba(100, 100, 255, 0.2);
            }
        """)

        # 设置展开状态的鼠标样式
        self.setCursor(Qt.CursorShape.ArrowCursor)

    def direct_expand(self):
        """直接展开 - 无动画"""
        if self.is_expanded:
            return

        # 保存当前小圆圈的中心点
        current_rect = self.geometry()
        self.collapsed_center = current_rect.center()
        center_x = self.collapsed_center.x()
        center_y = self.collapsed_center.y()

        # 计算展开后的位置（以小圆圈为中心）
        target_x = center_x - self.expanded_size[0] // 2
        target_y = center_y - self.expanded_size[1] // 2

        # 边界检测和调整
        screen = QApplication.primaryScreen().availableGeometry()
        target_x = max(10, min(target_x, screen.width() - self.expanded_size[0] - 10))
        target_y = max(10, min(target_y, screen.height() - self.expanded_size[1] - 10))

        # 直接设置为展开状态
        self.setFixedSize(*self.expanded_size)
        self.move(target_x, target_y)
        self.set_expanded_state()

    def direct_collapse(self):
        """直接收缩 - 无动画"""
        if not self.is_expanded:
            return

        # 获取当前窗口的中心
        current_rect = self.geometry()
        center_x = current_rect.center().x()
        center_y = current_rect.center().y()
        self.collapsed_center = QPoint(center_x, center_y)

        # 计算收缩后的位置
        target_x = center_x - self.collapsed_size[0] // 2
        target_y = center_y - self.collapsed_size[1] // 2

        # 直接设置为收缩状态
        self.setFixedSize(*self.collapsed_size)
        self.move(target_x, target_y)
        self.set_collapsed_state()

    def start_collapse(self):
        """开始收缩（延迟后）"""
        self.direct_collapse()
        self.hover_timer.stop()

    def enterEvent(self, event):
        """鼠标进入事件"""
        self.hover_timer.stop()
        self.direct_expand()
        super().enterEvent(event)

    def leaveEvent(self, event):
        """鼠标离开事件"""
        # 延迟收缩，避免误触
        if not self.worker or not self.worker.isRunning():
            self.hover_timer.stop()
            self.hover_timer.start(600)  # 600ms后收缩
        super().leaveEvent(event)

    def mousePressEvent(self, event):
        """鼠标按下事件（用于拖动）"""
        if event.button() == Qt.MouseButton.LeftButton:
            self.drag_pos = event.globalPosition().toPoint() - self.frameGeometry().topLeft()
            # 按下时改变光标
            if not self.is_expanded:
                self.setCursor(Qt.CursorShape.ClosedHandCursor)
            # 拖动时禁用悬停效果，避免干扰
            self.hover_timer.stop()
        elif event.button() == Qt.MouseButton.RightButton:
            # 右键菜单
            self.show_main_context_menu(event.globalPosition().toPoint())

    def mouseMoveEvent(self, event):
        """鼠标移动事件（用于拖动）"""
        if event.buttons() == Qt.MouseButton.LeftButton and hasattr(self, 'drag_pos'):
            new_pos = event.globalPosition().toPoint() - self.drag_pos
            self.move(new_pos)
            # 拖动后更新中心点位置
            self.collapsed_center = self.geometry().center()

    def mouseReleaseEvent(self, event):
        """鼠标释放事件"""
        if event.button() == Qt.MouseButton.LeftButton:
            # 释放时恢复光标
            if not self.is_expanded:
                self.setCursor(Qt.CursorShape.SizeAllCursor)
            else:
                self.setCursor(Qt.CursorShape.ArrowCursor)

            # 如果鼠标不在窗口上，启动收缩计时器
            if not self.underMouse() and self.is_expanded:
                self.hover_timer.start(600)
        super().mouseReleaseEvent(event)

    def paintEvent(self, event):
        """绘制事件 - 为小圆圈状态添加发光效果"""
        if not self.is_expanded:
            painter = QPainter(self)
            painter.setRenderHint(QPainter.RenderHint.Antialiasing)

            # 绘制发光效果
            center = QPoint(self.width() // 2, self.height() // 2)
            glow_color = QColor(128, 128, 255, 30)

            # 绘制多层光晕
            for i in range(3):
                painter.setBrush(QBrush(glow_color))
                painter.setPen(Qt.PenStyle.NoPen)
                radius = self.collapsed_size[0] // 2 - 2 + (i * 3)
                painter.drawEllipse(center, radius, radius)
                glow_color.setAlpha(glow_color.alpha() - 10)

        super().paintEvent(event)

    def closeEvent(self, event):
        """窗口关闭事件"""
        self.logger.info("正在关闭窗口...")

        try:
            # 调用统一的资源清理方法
            self._cleanup_all_resources()
        except Exception as e:
            self.logger.error(f"关闭窗口时出错: {e}")

        # 接受关闭事件
        event.accept()

        # 强制退出
        import os
        os._exit(0)


def main():
    """主函数"""
    app = QApplication(sys.argv)
    window = FloatingMonitor()
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
