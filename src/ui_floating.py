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
from typing import Optional, List
from datetime import datetime
from pathlib import Path

from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QTableWidget, QTableWidgetItem, QPushButton, QLabel, QMenu,
    QMessageBox, QHeaderView
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

        # Claude配置文件路径
        self.claude_settings_path = Path.home() / ".claude" / "settings.json"

        # 从Claude配置文件读取当前Token
        self.current_env_token = self._load_current_token()

        # 初始化UI
        self.init_ui()
        self.load_accounts()

        # 启动时为收缩状态
        self.set_collapsed_state()

        # 添加快捷键 - Esc快速退出
        from PyQt6.QtGui import QShortcut, QKeySequence
        self.quit_shortcut = QShortcut(QKeySequence("Ctrl+Q"), self)
        self.quit_shortcut.activated.connect(self.close)

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

    def init_ui(self):
        """初始化UI - 完全仿照原版"""
        self.setWindowTitle("余额监控")

        # 窗口大小设置
        self.collapsed_size = (50, 50)
        self.expanded_size = (320, 350)  # 增加高度以容纳退出按钮
        self.setFixedSize(*self.expanded_size)

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

        # 内容布局
        layout = QVBoxLayout(self.content_widget)
        layout.setContentsMargins(15, 15, 15, 15)
        layout.setSpacing(8)

        # 设置原版样式
        self.setStyleSheet("""
            #content {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:1,
                    stop:0 rgba(20, 20, 30, 230),
                    stop:1 rgba(30, 30, 45, 230));
                border-radius: 25px;
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
                border-radius: 18px;
                color: white;
                font-size: 13px;
                font-weight: bold;
                padding: 8px;
                min-height: 25px;
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
                border-radius: 8px;
                color: #e0e0e0;
                gridline-color: rgba(100, 100, 255, 0.05);
                selection-background-color: rgba(100, 100, 255, 0.3);
            }
            QTableWidget::item {
                padding: 4px;
                border: none;
            }
            QTableWidget::item:selected {
                background: rgba(100, 100, 255, 0.3);
            }
            QHeaderView::section {
                background: rgba(40, 40, 60, 180);
                color: #c0c0ff;
                border: none;
                padding: 4px;
                font-size: 12px;
                font-weight: bold;
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
                padding: 6px 18px;
                border-radius: 3px;
                margin: 2px 4px;
            }
            QMenu::item:selected {
                background: rgba(100, 100, 255, 0.3);
            }
            QMenu::separator {
                height: 1px;
                background: rgba(100, 100, 255, 0.1);
                margin: 4px 8px;
            }
        """)

        # 创建收缩状态的图标标签
        self.collapsed_label = QLabel("●")
        self.collapsed_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.collapsed_label.setStyleSheet("""
            QLabel {
                color: #8080ff;
                font-size: 20px;
                background: transparent;
            }
        """)
        self.collapsed_label.hide()
        layout.addWidget(self.collapsed_label)

        # 查询按钮
        self.btn = QPushButton("查 询")
        self.btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn.clicked.connect(self.query)
        layout.addWidget(self.btn)

        # 环境变量状态显示
        self.env_label = QLabel("Claude配置: 检测中...")
        self.env_label.setStyleSheet("font-size: 10px; color: #7070a0; padding: 2px;")
        layout.addWidget(self.env_label)

        # 表格
        self.table = QTableWidget()
        self.table.setColumnCount(3)
        self.table.setHorizontalHeaderLabels(["用户", "余额", "状态"])
        self.table.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.table.customContextMenuRequested.connect(self.show_context_menu)
        self.table.verticalHeader().setVisible(False)
        self.table.setAlternatingRowColors(True)

        # 设置列宽
        header = self.table.horizontalHeader()
        header.setStretchLastSection(True)

        layout.addWidget(self.table)

        # 总余额显示
        self.total_label = QLabel("总余额: --")
        self.total_label.setStyleSheet("""
            font-size: 12px;
            color: #90d090;
            padding: 4px;
            font-weight: bold;
        """)
        self.total_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self.total_label)

        # 退出按钮
        self.quit_btn = QPushButton("退 出")
        self.quit_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.quit_btn.clicked.connect(self.force_quit)
        self.quit_btn.setStyleSheet("""
            QPushButton {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
                    stop:0 #ff5555,
                    stop:1 #ff8855);
                border: none;
                border-radius: 15px;
                color: white;
                font-size: 11px;
                font-weight: bold;
                padding: 6px;
                min-height: 20px;
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
        layout.addWidget(self.quit_btn)

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

    def load_accounts(self):
        """加载账号列表"""
        accounts = self.config.accounts
        self.table.setRowCount(len(accounts))

        for i, account in enumerate(accounts):
            # 检查是否为当前环境变量使用的API key
            display_name = account.username
            if account.api_key and account.api_key == self.current_env_token:
                display_name = f"● {account.username}"

            self.table.setItem(i, 0, QTableWidgetItem(display_name))
            self.table.setItem(i, 1, QTableWidgetItem("等待"))
            self.table.setItem(i, 2, QTableWidgetItem("待机"))

        # 更新环境变量状态显示
        self.update_env_status_display()

    def update_env_status_display(self):
        """更新Claude配置状态显示"""
        if self.current_env_token:
            # 查找对应的用户名
            current_user = "未知"
            for account in self.config.accounts:
                if account.api_key == self.current_env_token:
                    current_user = account.username
                    break

            env_text = f"Claude配置: {current_user} ({self.current_env_token[:15]}...)"
        else:
            env_text = "Claude配置: 未设置"

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
        copy_action.triggered.connect(lambda: self.copy_apikey(apikey))
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
            env_action.triggered.connect(lambda: self.set_env_token(username, apikey))

        menu.addAction(env_action)

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
                return True
            else:
                QMessageBox.critical(
                    self,
                    "设置失败",
                    f"无法写入Claude配置文件\n\n"
                    f"请检查文件权限: {self.claude_settings_path}"
                )
                return False

        except Exception as e:
            QMessageBox.warning(self, "设置失败", f"Claude配置设置失败: {str(e)}")
            self.logger.error(f"设置Claude配置失败: {e}")
            return False

    def refresh_user_display(self):
        """刷新用户显示，更新环境变量标记"""
        for i, account in enumerate(self.config.accounts):
            display_name = account.username
            if account.api_key and account.api_key == self.current_env_token:
                display_name = f"● {account.username}"

            self.table.item(i, 0).setText(display_name)

    def force_quit(self):
        """强制退出程序"""
        self.logger.info("用户点击退出按钮，强制退出...")

        try:
            # 立即杀死所有Chrome进程
            import psutil
            import subprocess

            # Windows使用taskkill命令强制杀死
            if os.name == 'nt':
                try:
                    subprocess.run(['taskkill', '/F', '/IM', 'chrome.exe', '/T'],
                                 capture_output=True, timeout=1)
                    subprocess.run(['taskkill', '/F', '/IM', 'chromedriver.exe', '/T'],
                                 capture_output=True, timeout=1)
                except:
                    pass

            # 使用psutil杀死Chrome进程
            try:
                for proc in psutil.process_iter(['name']):
                    try:
                        name = proc.info['name'].lower()
                        if 'chrome' in name or 'chromedriver' in name:
                            proc.kill()
                    except:
                        pass
            except:
                pass
        except:
            pass

        # 直接强制退出，不等待任何清理
        import os
        os._exit(0)

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
        if self.worker and self.worker.isRunning():
            return

        self.btn.setText("查询中...")
        self.btn.setEnabled(False)

        # 查询时保持展开状态
        self.hover_timer.stop()

        for i in range(self.table.rowCount()):
            self.table.item(i, 1).setText("查询中...")
            self.table.item(i, 2).setText("...")

        # 创建并启动工作线程
        self.worker = MonitorWorker(self.service)
        self.worker.result.connect(self.update_result)
        self.worker.finished.connect(self.query_done)
        self.worker.start()

    def update_result(self, user, balance, success):
        """更新查询结果"""
        for i in range(self.table.rowCount()):
            # 检查用户名（可能带有●标记）
            current_display = self.table.item(i, 0).text()
            actual_username = current_display.replace("● ", "")  # 移除标记获取真实用户名

            if actual_username == user:
                self.table.item(i, 1).setText(balance)
                self.table.item(i, 2).setText("OK" if success else "ERR")

                # 设置状态颜色
                status_item = self.table.item(i, 2)
                if success:
                    status_item.setForeground(QColor("#4caf50"))  # 绿色
                else:
                    status_item.setForeground(QColor("#f44336"))  # 红色
                break

    def query_done(self):
        """查询完成"""
        self.btn.setText("查 询")
        self.btn.setEnabled(True)

        # 计算并显示总余额
        self.update_total_balance()

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

            # 只统计成功查询的余额
            if status_text == "OK":
                try:
                    # 尝试解析余额（移除可能的货币符号和格式）
                    balance_str = balance_text.replace('$', '').replace('¥', '').replace(',', '').strip()
                    balance = float(balance_str)
                    total += balance
                    success_count += 1
                except (ValueError, AttributeError):
                    # 无法解析的余额跳过
                    pass

        # 更新显示
        if success_count > 0:
            self.total_label.setText(f"总余额: ${total:.2f} ({success_count}个账号)")
            self.total_label.setStyleSheet("""
                font-size: 12px;
                color: #90ff90;
                padding: 4px;
                font-weight: bold;
            """)
        else:
            self.total_label.setText("总余额: --")
            self.total_label.setStyleSheet("""
                font-size: 12px;
                color: #a0a0c0;
                padding: 4px;
                font-weight: bold;
            """)

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
        """窗口关闭事件 - 快速清理所有资源"""
        self.logger.info("正在关闭窗口并清理资源...")

        try:
            # 停止计时器
            if self.hover_timer:
                self.hover_timer.stop()

            # 强制终止工作线程
            if self.worker and self.worker.isRunning():
                self.logger.info("强制终止工作线程...")
                self.worker.terminate()  # 立即终止，不等待
                self.worker.wait(500)  # 只等待500毫秒

            # 立即清理浏览器池，不等待
            try:
                from src.browser_pool import _global_pool
                if _global_pool:
                    self.logger.info("强制关闭浏览器池...")
                    # 直接遍历所有实例并强制quit
                    for instance in _global_pool.instances:
                        try:
                            instance.driver.quit()
                        except:
                            pass
                    _global_pool.instances.clear()
            except Exception as e:
                self.logger.debug(f"关闭浏览器池时出错: {e}")

            # 强制杀死所有Chrome进程
            try:
                import psutil
                for proc in psutil.process_iter(['name']):
                    try:
                        if 'chrome' in proc.info['name'].lower():
                            proc.kill()
                    except:
                        pass
            except:
                pass

        except Exception as e:
            self.logger.error(f"关闭窗口时出错: {e}")

        # 立即接受关闭事件，不等待
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