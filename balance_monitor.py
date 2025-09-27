#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import sys
import time
import os
import subprocess
from concurrent.futures import ThreadPoolExecutor, as_completed
from contextlib import contextmanager

from PyQt6.QtWidgets import (QApplication, QMainWindow, QVBoxLayout,
                            QTableWidget, QTableWidgetItem, QPushButton, QWidget, QMenu, QLabel, QMessageBox,
                            QHBoxLayout)
from PyQt6.QtCore import pyqtSignal, QThread, Qt, QTimer, QRect, QPoint
from PyQt6.QtGui import QAction, QPainter, QBrush, QColor, QFont, QPalette, QLinearGradient, QPen

from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service

try:
    import psutil
    WORKERS = min(psutil.cpu_count(), 9)
except ImportError:
    WORKERS = 6


@contextmanager
def chrome(profile):
    driver = None
    try:
        options = Options()
        options.add_argument("--headless=new")
        options.add_argument("--no-sandbox")
        options.add_argument("--disable-dev-shm-usage")
        options.add_argument("--disable-extensions")
        options.add_argument("--disable-images")
        if profile:
            options.add_argument(f"--user-data-dir={os.getcwd()}/chrome_profiles/{profile}")

        driver = webdriver.Chrome(
            service=Service(f"{os.getcwd()}/chromedriver.exe"),
            options=options
        )
        driver.implicitly_wait(2)
        driver.set_page_load_timeout(20)
        yield driver
    except:
        yield None
    finally:
        if driver:
            try:
                driver.quit()
            except:
                pass


def get_balance(username, password, profile):
    with chrome(profile) as driver:
        if not driver:
            return username, "Chrome失败", False

        try:
            driver.get("https://anyrouter.top/console")
            time.sleep(2)

            if '/login' in driver.current_url:
                driver.get("https://anyrouter.top/login")
                time.sleep(3)

                try:
                    email_btn = driver.find_element(By.CSS_SELECTOR, "button[type='button'] span.semi-icon-mail")
                    driver.execute_script("arguments[0].click();", email_btn)
                    time.sleep(3)
                except:
                    pass

                username_input = WebDriverWait(driver, 8).until(
                    EC.presence_of_element_located((By.NAME, "username"))
                )
                password_input = driver.find_element(By.NAME, "password")
                username_input.send_keys(username)
                password_input.send_keys(password)

                submit_btn = driver.find_element(By.CSS_SELECTOR, "button[type='submit']")
                driver.execute_script("arguments[0].click();", submit_btn)
                time.sleep(4)

                driver.get("https://anyrouter.top/console")
                time.sleep(2)

            time.sleep(5)
            try:
                WebDriverWait(driver, 10).until_not(
                    EC.presence_of_element_located((By.CSS_SELECTOR, ".semi-skeleton-title"))
                )
            except:
                pass
            time.sleep(2)

            balance = driver.execute_script("""
                var text = document.body.innerText;
                var match = text.match(/当前余额\\s*\\$([\\d,]+\\.?\\d*)/);
                if (match) return '$' + parseFloat(match[1].replace(/,/g, '')).toFixed(1);

                var elements = document.querySelectorAll('.text-lg.font-semibold');
                for (var i = 0; i < elements.length; i++) {
                    var text = elements[i].textContent.trim();
                    var dollarMatch = text.match(/^\\$([\\d,]+\\.?\\d*)$/);
                    if (dollarMatch) return '$' + parseFloat(dollarMatch[1].replace(/,/g, '')).toFixed(1);
                }

                return null;
            """)

            return username, balance or "无数据", balance is not None

        except Exception as e:
            return username, f"错误", False


class Worker(QThread):
    result = pyqtSignal(str, str, bool)
    finished = pyqtSignal()

    def __init__(self, credentials):
        super().__init__()
        self.credentials = credentials

    def run(self):
        with ThreadPoolExecutor(max_workers=WORKERS) as executor:
            futures = [
                executor.submit(get_balance, user, pwd, f"p_{i}_{user}")
                for i, (user, pwd) in enumerate(self.credentials)  # 现在是两列格式
            ]

            for future in as_completed(futures):
                try:
                    user, balance, success = future.result(timeout=90)
                    self.result.emit(user, balance, success)
                except:
                    pass

        self.finished.emit()


class Monitor(QMainWindow):
    def __init__(self):
        super().__init__()
        self.credentials = []
        self.worker = None
        self.current_env_token = os.environ.get('ANTHROPIC_AUTH_TOKEN', '')
        self.is_expanded = False
        self.hover_timer = QTimer()
        self.hover_timer.timeout.connect(self.start_collapse)
        self.collapsed_center = None  # 记忆小圆圈的中心点
        self.init_ui()
        self.load_accounts()
        # 启动时为收缩状态
        self.set_collapsed_state()

    def init_ui(self):
        self.setWindowTitle("余额监控")
        self.collapsed_size = (50, 50)  # 收缩时更小一些
        self.expanded_size = (320, 280)  # 展开时稍微紧凑
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

        # 设置样式
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

        # 创建一个用于收缩状态的图标标签
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
        self.env_label = QLabel("环境变量: 检测中...")
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
        layout.addWidget(self.table)

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

    def create_env_status_label(self):
        """创建环境变量状态标签"""
        if self.current_env_token:
            # 查找对应的用户名
            current_user = "未知"
            for user, _, apikey in self.credentials:
                if apikey == self.current_env_token:
                    current_user = user
                    break

            env_text = f"环境变量: {current_user} ({self.current_env_token[:15]}...)"
        else:
            env_text = "环境变量: 未设置"

        from PyQt6.QtWidgets import QLabel
        label = QLabel(env_text)
        label.setStyleSheet("font-size: 10px; color: #666; padding: 2px;")
        return label

    def load_accounts(self):
        try:
            with open("credentials.txt", "r", encoding="utf-8") as f:
                self.credentials = []
                for line in f:
                    line = line.strip()
                    if ',' in line:
                        parts = line.split(',')
                        if len(parts) >= 3:
                            username, password, apikey = parts[0], parts[1], parts[2]
                            self.credentials.append((username.strip(), password.strip(), apikey.strip()))
                        elif len(parts) == 2:
                            username, password = parts[0], parts[1]
                            self.credentials.append((username.strip(), password.strip(), ""))

            self.table.setRowCount(len(self.credentials))
            for i, (user, _, apikey) in enumerate(self.credentials):
                # 检查是否为当前环境变量使用的API key
                display_name = user
                if apikey and apikey == self.current_env_token:
                    display_name = f"● {user}"  # 用圆点标记当前使用的

                self.table.setItem(i, 0, QTableWidgetItem(display_name))
                self.table.setItem(i, 1, QTableWidgetItem("等待"))
                self.table.setItem(i, 2, QTableWidgetItem("待机"))

            # 更新环境变量状态显示
            self.update_env_status_display()

        except:
            pass

    def update_env_status_display(self):
        """更新环境变量状态显示"""
        if self.current_env_token:
            # 查找对应的用户名
            current_user = "未知"
            for user, _, apikey in self.credentials:
                if apikey == self.current_env_token:
                    current_user = user
                    break

            env_text = f"环境变量: {current_user} ({self.current_env_token[:15]}...)"
        else:
            env_text = "环境变量: 未设置"

        self.env_label.setText(env_text)

    def show_context_menu(self, position):
        """显示右键菜单"""
        item = self.table.itemAt(position)
        if item is None:
            return

        row = item.row()
        if row >= len(self.credentials):
            return

        # 获取用户信息
        username = self.credentials[row][0]
        apikey = self.credentials[row][2] if len(self.credentials[row]) > 2 else ""

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

        # 设置环境变量选项
        is_current = apikey == self.current_env_token
        if is_current:
            env_action = QAction(f"● 当前环境变量", self)
            env_action.setEnabled(False)  # 禁用，只用于显示状态
        else:
            env_action = QAction(f"设置为环境变量", self)
            env_action.triggered.connect(lambda: self.set_env_token(username, apikey))

        menu.addAction(env_action)

        # 显示菜单
        menu.exec(self.table.mapToGlobal(position))

    def copy_apikey(self, apikey):
        """复制API key到剪贴板"""
        clipboard = QApplication.clipboard()
        clipboard.setText(apikey)
        print(f"已复制API Key: {apikey[:20]}...")

    def set_env_token(self, username, apikey):
        """设置系统环境变量（需要管理员权限）"""
        try:
            if os.name == 'nt':  # Windows
                # 直接使用 /M 参数设置系统环境变量
                result = subprocess.run(
                    ['setx', 'ANTHROPIC_AUTH_TOKEN', apikey, '/M'],
                    capture_output=True,
                    text=True,
                    timeout=10
                )

                if result.returncode == 0:
                    # 更新当前进程环境变量
                    os.environ['ANTHROPIC_AUTH_TOKEN'] = apikey
                    self.current_env_token = apikey

                    # 刷新显示
                    self.refresh_user_display()
                    self.update_env_status_display()

                    # 成功消息
                    QMessageBox.information(
                        self,
                        "系统环境变量设置成功",
                        f"已将 {username} 的API Key设置为系统环境变量\n\n"
                        f"作用域: 整个系统（所有用户）\n"
                        f"当前进程: 立即生效\n"
                        f"其他程序: 重启后生效"
                    )

                    print(f"系统环境变量设置成功: {username}")
                    return True
                else:
                    # 权限不足或其他错误
                    error_msg = result.stderr.strip()
                    if "拒绝访问" in error_msg or "Access is denied" in error_msg:
                        QMessageBox.critical(
                            self,
                            "权限不足",
                            f"设置系统环境变量需要管理员权限\n\n"
                            f"解决方法:\n"
                            f"1. 右键程序 → 以管理员身份运行\n"
                            f"2. 或在管理员命令行中启动程序"
                        )
                    else:
                        QMessageBox.warning(
                            self,
                            "设置失败",
                            f"系统环境变量设置失败\n\n错误: {error_msg}"
                        )
                    return False
            else:
                # 非Windows系统
                QMessageBox.warning(
                    self,
                    "不支持的系统",
                    f"系统环境变量设置仅支持Windows系统\n\n"
                    f"当前系统: {os.name}"
                )
                return False

        except subprocess.TimeoutExpired:
            QMessageBox.warning(self, "设置超时", "系统环境变量设置超时")
            return False
        except Exception as e:
            QMessageBox.warning(self, "设置失败", f"系统环境变量设置失败: {str(e)}")
            return False

    def refresh_user_display(self):
        """刷新用户显示，更新环境变量标记"""
        for i, (user, _, apikey) in enumerate(self.credentials):
            display_name = user
            if apikey and apikey == self.current_env_token:
                display_name = f"● {user}"

            self.table.item(i, 0).setText(display_name)

    def query(self):
        if self.worker and self.worker.isRunning():
            return

        self.btn.setText("查询中...")
        self.btn.setEnabled(False)

        # 查询时保持展开状态
        self.hover_timer.stop()

        for i in range(self.table.rowCount()):
            self.table.item(i, 1).setText("查询中...")
            self.table.item(i, 2).setText("...")

        # 只传递用户名和密码给Worker（前两列）
        login_credentials = [(user, pwd) for user, pwd, _ in self.credentials]
        self.worker = Worker(login_credentials)
        self.worker.result.connect(self.update_result)
        self.worker.finished.connect(self.query_done)
        self.worker.start()

    def update_result(self, user, balance, success):
        for i in range(self.table.rowCount()):
            # 检查用户名（可能带有●标记）
            current_display = self.table.item(i, 0).text()
            actual_username = current_display.replace("● ", "")  # 移除标记获取真实用户名

            if actual_username == user:
                self.table.item(i, 1).setText(balance)
                self.table.item(i, 2).setText("OK" if success else "ERR")
                break

    def query_done(self):
        self.btn.setText("查 询")
        self.btn.setEnabled(True)
        # 查询完成后启动自动收缩计时器
        if not self.underMouse():
            self.hover_timer.start(2000)  # 2秒后自动收缩

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

    def mouseMoveEvent(self, event):
        """鼠标移动事件（用于拖动）"""
        if event.buttons() == Qt.MouseButton.LeftButton and hasattr(self, 'drag_pos'):
            new_pos = event.globalPosition().toPoint() - self.drag_pos
            self.move(new_pos)
            # 拖动后更新中心点位置（无论是展开还是收缩状态都要更新）
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


def main():
    app = QApplication(sys.argv)
    window = Monitor()
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()