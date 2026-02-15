#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
认证模块 - 处理AnyRouter登录逻辑
"""

import time
import logging
import re
from typing import Optional, Dict, Tuple
from dataclasses import dataclass

from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException

from src.browser_manager import BrowserManager


@dataclass
class LoginResult:
    """登录结果"""
    success: bool
    message: str
    balance: Optional[str] = None
    session_data: Optional[Dict] = None


class AuthManager:
    """认证管理器"""

    LOGIN_URL = "https://anyrouter.top/login"
    CONSOLE_URL = "https://anyrouter.top/console"
    QUOTA_UNIT_PER_DOLLAR = 500000

    def __init__(self, browser_manager: BrowserManager):
        """初始化认证管理器"""
        self.browser = browser_manager
        self.logger = logging.getLogger(__name__)

    def login(self, username: str, password: str, retry_times: int = 3) -> LoginResult:
        """执行登录"""
        for attempt in range(retry_times):
            result = self._attempt_login(username, password)
            if result.success:
                return result

            self.logger.warning(f"登录失败 (尝试 {attempt + 1}/{retry_times}): {result.message}")

            if attempt < retry_times - 1:
                time.sleep(5)  # 重试前等待

        return LoginResult(False, f"登录失败，已重试{retry_times}次")

    def _attempt_login(self, username: str, password: str) -> LoginResult:
        """性能优化版 - 减少等待时间但保持稳定"""
        try:
            # Step 1: 访问console页面
            self.browser.navigate_to(self.CONSOLE_URL)
            time.sleep(0.8)  # 轻微减少等待

            # 检查是否被重定向到登录页
            current_url = self.browser.get_current_url() or ""
            if '/login' in current_url:
                # Step 2: 处理公告弹窗（立即检查）
                time.sleep(0.5)  # 短暂等待弹窗
                if self._close_announcement_popup():
                    self.logger.info("成功关闭公告弹窗")

                # Step 3: 切换到邮箱登录
                try:
                    email_btn = self.browser.driver.find_element(
                        By.CSS_SELECTOR,
                        "button[type='button'] span.semi-icon-mail"
                    )
                    self.browser.execute_script("arguments[0].click();", email_btn)
                    time.sleep(1.5)  # 确保切换成功
                except:
                    pass

                # Step 4: 输入凭证
                username_input = self.browser.wait_for_element(
                    By.NAME, "username", timeout=5
                )

                if not username_input:
                    return LoginResult(False, "未找到用户名输入框")

                password_input = self.browser.driver.find_element(By.NAME, "password")

                # 清空并输入
                username_input.clear()
                username_input.send_keys(username)
                password_input.clear()
                password_input.send_keys(password)

                # Step 5: 提交登录
                submit_btn = self.browser.driver.find_element(
                    By.CSS_SELECTOR, "button[type='submit']"
                )
                self.browser.execute_script("arguments[0].click();", submit_btn)
                time.sleep(2)  # 确保登录处理完成

                # Step 6: 确认登录
                self.browser.navigate_to(self.CONSOLE_URL)
                time.sleep(0.8)

            # 检查登录结果
            current_url = self.browser.get_current_url() or ""
            if '/console' in current_url:
                self.logger.info(f"用户 {username} 登录成功")
                return LoginResult(True, "登录成功")
            else:
                error_msg = self._check_error_message()
                return LoginResult(False, error_msg or "登录失败")

        except Exception as e:
            self.logger.error(f"登录异常: {e}")
            return LoginResult(False, f"登录异常: {str(e)}")


    def _close_announcement_popup(self) -> bool:
        """超快速关闭公告弹窗"""
        try:
            # 优先尝试最可能的关闭按钮（减少遍历）
            # 直接使用CSS选择器查找
            close_btn = None

            # 方法1: 快速查找.semi-modal-close按钮
            try:
                close_btn = self.browser.driver.find_element(
                    By.CSS_SELECTOR, ".semi-modal-close"
                )
                if close_btn and close_btn.is_displayed():
                    self.browser.execute_script("arguments[0].click();", close_btn)
                    self.logger.debug("关闭了公告弹窗(X按钮)")
                    return True
            except:
                pass

            # 方法2: 查找包含"关闭"文本的按钮（使用JavaScript更快）
            result = self.browser.execute_script("""
                var buttons = document.querySelectorAll('button');
                for (var btn of buttons) {
                    var text = btn.textContent;
                    if (text.includes('今日关闭') || text.includes('关闭公告') || text.includes('关闭')) {
                        btn.click();
                        return true;
                    }
                }
                return false;
            """)

            if result:
                self.logger.debug("关闭了公告弹窗(关闭按钮)")
                return True

            self.logger.debug("未找到公告弹窗")
            return False

        except Exception as e:
            self.logger.debug(f"关闭弹窗异常: {e}")
            return False


    def _check_error_message(self) -> Optional[str]:
        """检查登录错误信息"""
        try:
            # 查找可能的错误提示元素
            error_selectors = [
                ".error-message",
                ".alert-danger",
                ".toast-error",
                "[role='alert']"
            ]

            for selector in error_selectors:
                error_text = self.browser.get_element_text(By.CSS_SELECTOR, selector)
                if error_text:
                    return error_text

        except:
            pass

        return None

    def logout(self) -> bool:
        """登出"""
        try:
            # 查找登出按钮或链接
            logout_selectors = [
                "a[href*='logout']",
                ".logout-button"
            ]

            for selector in logout_selectors:
                if self.browser.check_element_exists(By.CSS_SELECTOR, selector):
                    element = self.browser.driver.find_element(By.CSS_SELECTOR, selector)
                    self.browser.safe_click(element)
                    self.logger.info("已登出")
                    return True

            # 尝试使用XPath查找包含'退出'或'登出'文本的按钮
            logout_xpaths = [
                "//button[contains(text(), '退出')]",
                "//button[contains(text(), '登出')]",
                "//a[contains(text(), '退出')]",
                "//a[contains(text(), '登出')]"
            ]

            for xpath in logout_xpaths:
                try:
                    element = self.browser.driver.find_element(By.XPATH, xpath)
                    if element.is_displayed():
                        self.browser.safe_click(element)
                        self.logger.info("已登出")
                        return True
                except:
                    continue

            self.logger.warning("未找到登出按钮")
            return False

        except Exception as e:
            self.logger.error(f"登出失败: {e}")
            return False

    def check_login_status(self) -> bool:
        """检查登录状态（优化版本）"""
        try:
            # 访问控制台页面
            self.browser.navigate_to(self.CONSOLE_URL)
            time.sleep(1)  # 减少等待时间

            # 检查是否被重定向到登录页
            current_url = self.browser.get_current_url() or ""
            is_logged_in = '/console' in current_url and '/login' not in current_url

            self.logger.debug(f"登录状态: {is_logged_in}")
            return is_logged_in

        except Exception as e:
            self.logger.error(f"检查登录状态失败: {e}")
            return False

    @staticmethod
    def parse_balance_number(balance: Optional[str]) -> Optional[float]:
        """将余额文本解析为浮点数"""
        if balance is None:
            return None

        text = str(balance).strip()
        if not text:
            return None

        match = re.search(r'-?[\d,]+(?:\.\d+)?', text)
        if not match:
            return None

        try:
            return float(match.group(0).replace(',', ''))
        except ValueError:
            return None

    def sync_first_apikey_limit(self, balance: Optional[str], timeout: int = 12) -> Tuple[bool, str]:
        """
        登录后尝试将首个 API Key 的额度同步为当前余额。
        该逻辑为增强功能，同步失败不影响主流程。
        """
        if not self.browser or not self.browser.driver:
            return False, "浏览器会话不可用"

        self.logger.debug(f"开始同步首个 API Key 额度，原始余额文本: {balance}")
        amount = self.parse_balance_number(balance)
        if amount is None:
            return False, "余额格式无法解析"
        self.logger.debug(f"余额解析成功: {amount:.6f}")

        try:
            # 1) 进入 API令牌 页面
            ok, msg = self._open_apikey_page(timeout=timeout)
            if not ok:
                return False, msg
            self.logger.debug("步骤1完成：已进入 API令牌 页面")

            # 2) 打开第一条令牌的编辑弹窗
            ok, msg = self._open_first_token_editor(timeout=timeout)
            if not ok:
                return False, msg
            self.logger.debug("步骤2完成：首条令牌编辑弹窗已打开")

            # 3) 自动识别额度换算比例，计算目标额度值
            unit_rate = self._detect_quota_unit_rate()
            target_quota = max(int(round(amount * unit_rate)), 0)
            self.logger.debug(
                f"步骤3完成：额度换算比例={unit_rate:.6f}, 目标额度值={target_quota}"
            )

            # 4) 写入额度并提交
            ok, msg = self._set_modal_quota_value(target_quota)
            if not ok:
                return False, msg
            self.logger.debug("步骤4完成：额度输入已写入")

            ok, msg = self._submit_quota_modal(timeout=timeout)
            if not ok:
                return False, msg
            self.logger.debug("步骤5完成：额度提交成功且弹窗已关闭")

            self.logger.info(
                f"首个 API Key 额度已同步: 余额=${amount:.2f}, 额度值={target_quota}, 比例={unit_rate:.2f}"
            )
            return True, f"额度已更新为 ${amount:.2f}"

        except Exception as e:
            self.logger.warning(f"同步首个 API Key 额度失败: {e}")
            return False, str(e)

    def _open_apikey_page(self, timeout: int = 8) -> Tuple[bool, str]:
        """按页面路径进入 API令牌 页面"""
        driver = self.browser.driver
        self.logger.debug("准备进入 API令牌 页面")

        # 优先通过左侧菜单点击进入，符合实际操作路径
        menu_xpath = (
            "//*[self::a or self::button or self::span or self::div]"
            "[normalize-space(text())='API令牌']"
        )

        try:
            menu_node = WebDriverWait(driver, timeout).until(
                EC.presence_of_element_located((By.XPATH, menu_xpath))
            )
            clickable = driver.execute_script(
                """
                let node = arguments[0];
                while (node) {
                    const tag = (node.tagName || '').toLowerCase();
                    const role = node.getAttribute ? (node.getAttribute('role') || '').toLowerCase() : '';
                    const cls = node.className ? String(node.className).toLowerCase() : '';
                    if (tag === 'a' || tag === 'button' || role === 'button' || cls.includes('semi-navigation-item')) {
                        return node;
                    }
                    node = node.parentElement;
                }
                return arguments[0];
                """,
                menu_node
            )
            driver.execute_script("arguments[0].click();", clickable)
            self.logger.debug("已点击左侧 API令牌 菜单")
        except TimeoutException:
            self.logger.debug("未找到左侧 API令牌 菜单节点")
            return False, "未找到左侧 API令牌 菜单"
        except Exception as e:
            self.logger.debug(f"点击 API令牌 菜单异常: {e}")
            return False, f"进入 API令牌 页面失败: {e}"

        # 等待页面关键控件出现
        try:
            WebDriverWait(driver, timeout).until(
                lambda d: d.execute_script(
                    """
                    const text = document.body && document.body.innerText ? document.body.innerText : '';
                    return text.includes('添加令牌') || text.includes('复制所选令牌到剪贴板');
                    """
                )
            )
            current_url = driver.current_url if driver else ""
            self.logger.debug(f"API令牌 页面已加载，当前URL: {current_url}")
            return True, ""
        except TimeoutException:
            self.logger.debug("等待 API令牌 页面关键控件超时")
            return False, "API令牌 页面未加载完成"

    def _open_first_token_editor(self, timeout: int = 8) -> Tuple[bool, str]:
        """打开第一条令牌的编辑弹窗"""
        driver = self.browser.driver
        self.logger.debug("准备打开第一条令牌编辑弹窗")

        editor_open_script = """
            function isVisible(node) {
                if (!node) return false;
                const style = window.getComputedStyle(node);
                if (style.display === 'none' || style.visibility === 'hidden') return false;
                const rect = node.getBoundingClientRect();
                return rect.width > 0 && rect.height > 0;
            }

            const hasEditorHeader = Array.from(document.querySelectorAll('*')).some((node) => {
                if (!isVisible(node)) return false;
                const text = (node.textContent || '').trim();
                return text.includes('更新令牌信息') || text.includes('额度设置') || text.includes('编辑令牌');
            });

            const hasQuotaLabel = Array.from(document.querySelectorAll('*')).some((node) => {
                if (!isVisible(node)) return false;
                return (node.textContent || '').trim() === '额度';
            });

            const hasSubmit = Array.from(document.querySelectorAll('button, [role="button"]')).some((btn) => {
                if (!isVisible(btn)) return false;
                if (btn.disabled) return false;
                const text = (btn.innerText || btn.textContent || '').trim();
                return text.includes('提交');
            });

            return hasEditorHeader || (hasQuotaLabel && hasSubmit);
        """

        wait_row_script = """
            function isVisible(node) {
                if (!node) return false;
                const style = window.getComputedStyle(node);
                if (style.display === 'none' || style.visibility === 'hidden') return false;
                const rect = node.getBoundingClientRect();
                return rect.width > 0 && rect.height > 0;
            }
            function normalizeText(text) {
                return String(text || '').replace(/\\s+/g, ' ').trim();
            }
            function hasTokenActions(row) {
                if (!row) return false;
                const texts = Array.from(row.querySelectorAll('button, a, [role="button"], span, div'))
                    .map((node) => normalizeText(node.innerText || node.textContent || ''))
                    .filter((text) => !!text);
                const hasCopy = texts.some((text) => text === '复制');
                const hasEdit = texts.some((text) => text === '编辑');
                return hasCopy && hasEdit;
            }
            function isLikelyTokenRow(row) {
                const text = normalizeText(row ? row.innerText : '');
                if (!text) return false;
                if (row && row.querySelector('th')) return false;
                if (hasTokenActions(row)) return true;
                return text.includes('已启用') && text.includes('用户分组') && text.includes('编辑');
            }
            function hasAction(row) {
                const controls = Array.from(row.querySelectorAll('button, a, [role="button"], span, div'));
                return controls.some((node) => {
                    const text = normalizeText(node.innerText || node.textContent || '');
                    return text.includes('编辑') || text.includes('更多') || text.includes('操作');
                });
            }
            const rows = Array.from(
                document.querySelectorAll('tbody tr, .semi-table-tbody .semi-table-row, .semi-table-row')
            ).filter((row) => isVisible(row) && isLikelyTokenRow(row) && hasAction(row));
            return rows.length > 0;
        """

        direct_click_script = """
            function isVisible(node) {
                if (!node) return false;
                const style = window.getComputedStyle(node);
                if (style.display === 'none' || style.visibility === 'hidden') return false;
                const rect = node.getBoundingClientRect();
                return rect.width > 0 && rect.height > 0;
            }
            function normalizeText(text) {
                return String(text || '').replace(/\\s+/g, ' ').trim();
            }
            function toClickable(node) {
                let cursor = node;
                while (cursor) {
                    const tag = (cursor.tagName || '').toLowerCase();
                    const role = cursor.getAttribute ? (cursor.getAttribute('role') || '').toLowerCase() : '';
                    if (tag === 'button' || tag === 'a' || role === 'button') {
                        return cursor;
                    }
                    cursor = cursor.parentElement;
                }
                return node;
            }
            function isEnabled(node) {
                if (!node) return false;
                if (node.disabled) return false;
                const aria = node.getAttribute ? (node.getAttribute('aria-disabled') || '').toLowerCase() : '';
                if (aria === 'true') return false;
                const style = window.getComputedStyle(node);
                if (style.pointerEvents === 'none') return false;
                return true;
            }
            function hasTokenActions(row) {
                if (!row) return false;
                const texts = Array.from(row.querySelectorAll('button, a, [role="button"], span, div'))
                    .map((node) => normalizeText(node.innerText || node.textContent || ''))
                    .filter((text) => !!text);
                const hasCopy = texts.some((text) => text === '复制');
                const hasEdit = texts.some((text) => text === '编辑');
                return hasCopy && hasEdit;
            }
            function isLikelyTokenRow(row) {
                const text = normalizeText(row ? row.innerText : '');
                if (!text) return false;
                if (row && row.querySelector('th')) return false;
                if (hasTokenActions(row)) return true;
                return text.includes('已启用') && text.includes('用户分组') && text.includes('编辑');
            }
            function collectEditCandidates(root) {
                const exact = [];
                const fuzzy = [];
                const nodes = Array.from(root.querySelectorAll('button, a, [role="button"], span, div'));
                for (const node of nodes) {
                    const text = normalizeText(node.innerText || node.textContent || '');
                    if (!text || !text.includes('编辑') || !isVisible(node)) continue;

                    const hasChildExactEdit = Array.from(node.querySelectorAll('*')).some((child) => {
                        const childText = normalizeText(child.innerText || child.textContent || '');
                        return childText === '编辑';
                    });
                    if (hasChildExactEdit && text !== '编辑') continue;

                    const clickable = toClickable(node);
                    if (!isVisible(clickable) || !isEnabled(clickable)) continue;
                    const clickableText = normalizeText(clickable.innerText || clickable.textContent || '');
                    if (clickableText.includes('复制') && clickableText.includes('编辑') && text !== '编辑') {
                        continue;
                    }

                    const bucket = (text === '编辑' || clickableText === '编辑') ? exact : fuzzy;
                    if (!bucket.includes(clickable)) {
                        bucket.push(clickable);
                    }
                }
                return exact.concat(fuzzy);
            }
            function clickWithEvents(node) {
                if (!node) return { clicked: false, reason: 'no_target' };
                node.scrollIntoView({ block: 'center', inline: 'center' });
                const rect = node.getBoundingClientRect();
                const x = Math.floor(rect.left + rect.width / 2);
                const y = Math.floor(rect.top + rect.height / 2);
                const target = node;
                const events = ['pointerover', 'mouseover', 'pointerdown', 'mousedown', 'pointerup', 'mouseup', 'click'];
                for (const name of events) {
                    const Ctor = name.startsWith('pointer') ? PointerEvent : MouseEvent;
                    target.dispatchEvent(new Ctor(name, {
                        bubbles: true,
                        cancelable: true,
                        view: window,
                        clientX: x,
                        clientY: y
                    }));
                }
                if (typeof node.click === 'function') {
                    node.click();
                }
                return {
                    clicked: true,
                    x: x,
                    y: y,
                    targetTag: (target.tagName || '').toLowerCase(),
                    targetText: normalizeText(target.innerText || target.textContent || '').slice(0, 40)
                };
            }

            const rows = Array.from(
                document.querySelectorAll('tbody tr, .semi-table-tbody .semi-table-row, .semi-table-row')
            ).filter((row) => isVisible(row) && isLikelyTokenRow(row));
            const row = rows.length ? rows[0] : null;
            if (!row) {
                return { clicked: false, reason: 'no_token_row' };
            }

            row.scrollIntoView({ block: 'center', inline: 'nearest' });
            row.dispatchEvent(new MouseEvent('mouseenter', { bubbles: true, cancelable: true, view: window }));
            row.dispatchEvent(new MouseEvent('mouseover', { bubbles: true, cancelable: true, view: window }));

            const candidates = collectEditCandidates(row);
            if (!candidates.length) {
                return {
                    clicked: false,
                    reason: 'row_no_direct_edit',
                    rowText: normalizeText(row.innerText || '').slice(0, 120)
                };
            }

            const target = candidates[0];
            const clickInfo = clickWithEvents(target);
            return {
                clicked: clickInfo.clicked,
                reason: 'row_direct',
                candidateCount: candidates.length,
                rowText: normalizeText(row.innerText || '').slice(0, 120),
                candidateText: normalizeText(target.innerText || target.textContent || '').slice(0, 40),
                x: clickInfo.x,
                y: clickInfo.y,
                targetTag: clickInfo.targetTag,
                targetText: clickInfo.targetText
            };
        """

        dropdown_click_script = """
            function isVisible(node) {
                if (!node) return false;
                const style = window.getComputedStyle(node);
                if (style.display === 'none' || style.visibility === 'hidden') return false;
                const rect = node.getBoundingClientRect();
                return rect.width > 0 && rect.height > 0;
            }
            function normalizeText(text) {
                return String(text || '').replace(/\\s+/g, ' ').trim();
            }
            function toClickable(node) {
                let cursor = node;
                while (cursor) {
                    const tag = (cursor.tagName || '').toLowerCase();
                    const role = cursor.getAttribute ? (cursor.getAttribute('role') || '').toLowerCase() : '';
                    if (tag === 'button' || tag === 'a' || role === 'button') {
                        return cursor;
                    }
                    cursor = cursor.parentElement;
                }
                return node;
            }
            function isEnabled(node) {
                if (!node) return false;
                if (node.disabled) return false;
                const aria = node.getAttribute ? (node.getAttribute('aria-disabled') || '').toLowerCase() : '';
                if (aria === 'true') return false;
                const style = window.getComputedStyle(node);
                if (style.pointerEvents === 'none') return false;
                return true;
            }
            function hasTokenActions(row) {
                if (!row) return false;
                const texts = Array.from(row.querySelectorAll('button, a, [role="button"], span, div'))
                    .map((node) => normalizeText(node.innerText || node.textContent || ''))
                    .filter((text) => !!text);
                const hasCopy = texts.some((text) => text === '复制');
                const hasEdit = texts.some((text) => text === '编辑');
                return hasCopy && hasEdit;
            }
            function isLikelyTokenRow(row) {
                const text = normalizeText(row ? row.innerText : '');
                if (!text) return false;
                if (row && row.querySelector('th')) return false;
                if (hasTokenActions(row)) return true;
                return text.includes('已启用') && text.includes('用户分组') && text.includes('编辑');
            }
            function clickWithEvents(node) {
                if (!node) return { clicked: false, reason: 'no_target' };
                node.scrollIntoView({ block: 'center', inline: 'center' });
                const rect = node.getBoundingClientRect();
                const x = Math.floor(rect.left + rect.width / 2);
                const y = Math.floor(rect.top + rect.height / 2);
                const target = node;
                const events = ['pointerover', 'mouseover', 'pointerdown', 'mousedown', 'pointerup', 'mouseup', 'click'];
                for (const name of events) {
                    const Ctor = name.startsWith('pointer') ? PointerEvent : MouseEvent;
                    target.dispatchEvent(new Ctor(name, {
                        bubbles: true,
                        cancelable: true,
                        view: window,
                        clientX: x,
                        clientY: y
                    }));
                }
                if (typeof node.click === 'function') {
                    node.click();
                }
                return {
                    clicked: true,
                    x: x,
                    y: y,
                    targetTag: (target.tagName || '').toLowerCase(),
                    targetText: normalizeText(target.innerText || target.textContent || '').slice(0, 40)
                };
            }

            const rows = Array.from(
                document.querySelectorAll('tbody tr, .semi-table-tbody .semi-table-row, .semi-table-row')
            ).filter((row) => isVisible(row) && isLikelyTokenRow(row));
            const row = rows.length ? rows[0] : null;
            if (!row) {
                return { clicked: false, reason: 'no_token_row' };
            }

            row.scrollIntoView({ block: 'center', inline: 'nearest' });
            row.dispatchEvent(new MouseEvent('mouseenter', { bubbles: true, cancelable: true, view: window }));
            row.dispatchEvent(new MouseEvent('mouseover', { bubbles: true, cancelable: true, view: window }));

            const controls = [];
            for (const node of Array.from(row.querySelectorAll('button, a, [role="button"], span, div, i'))) {
                const clickable = toClickable(node);
                if (!clickable || !isVisible(clickable) || !isEnabled(clickable)) continue;
                if (!controls.includes(clickable)) {
                    controls.push(clickable);
                }
            }
            controls.sort((a, b) => b.getBoundingClientRect().left - a.getBoundingClientRect().left);

            const triggerCandidates = controls.filter((node) => {
                const text = normalizeText(node.innerText || node.textContent || '');
                const cls = String(node.className || '').toLowerCase();
                const aria = String(node.getAttribute ? node.getAttribute('aria-label') || '' : '').toLowerCase();
                if (text.includes('更多') || text.includes('操作') || text === '...' || text === '…') return true;
                return (
                    cls.includes('more') || cls.includes('ellipsis') || cls.includes('semi-icon-more') ||
                    cls.includes('semi-icons-more') || aria.includes('more') || aria.includes('更多')
                );
            });
            const ordered = triggerCandidates.length ? triggerCandidates : controls.slice(0, 3);
            if (!ordered.length) {
                return {
                    clicked: false,
                    reason: 'no_action_trigger',
                    rowText: normalizeText(row.innerText || '').slice(0, 120)
                };
            }

            for (let idx = 0; idx < ordered.length && idx < 3; idx += 1) {
                const trigger = ordered[idx];
                clickWithEvents(trigger);

                const menus = Array.from(document.querySelectorAll(
                    '.semi-dropdown-item, .semi-dropdown-menu-item, [role="menuitem"], ' +
                    '.semi-popover-content button, .semi-popover-content [role="button"], ' +
                    '.semi-portal [role="menuitem"], .semi-portal button'
                ));

                const exactEditItems = [];
                const fuzzyEditItems = [];
                for (const item of menus) {
                    if (!isVisible(item)) continue;
                    const clickable = toClickable(item);
                    if (!isVisible(clickable) || !isEnabled(clickable)) continue;
                    const text = normalizeText(clickable.innerText || clickable.textContent || '');
                    if (!text.includes('编辑')) continue;
                    if (text.includes('复制') && text.includes('编辑')) continue;
                    const bucket = text === '编辑' ? exactEditItems : fuzzyEditItems;
                    if (!bucket.includes(clickable)) {
                        bucket.push(clickable);
                    }
                }

                const editItems = exactEditItems.concat(fuzzyEditItems);
                if (!editItems.length) continue;

                const editInfo = clickWithEvents(editItems[0]);
                return {
                    clicked: editInfo.clicked,
                    reason: 'menu_edit',
                    triggerIndex: idx + 1,
                    triggerText: normalizeText(trigger.innerText || trigger.textContent || '').slice(0, 40),
                    menuEditCount: editItems.length,
                    rowText: normalizeText(row.innerText || '').slice(0, 120),
                    x: editInfo.x,
                    y: editInfo.y,
                    targetTag: editInfo.targetTag,
                    targetText: editInfo.targetText
                };
            }

            return {
                clicked: false,
                reason: 'menu_edit_not_found',
                triggerCount: ordered.length,
                rowText: normalizeText(row.innerText || '').slice(0, 120)
            };
        """

        global_click_script = """
            function isVisible(node) {
                if (!node) return false;
                const style = window.getComputedStyle(node);
                if (style.display === 'none' || style.visibility === 'hidden') return false;
                const rect = node.getBoundingClientRect();
                return rect.width > 0 && rect.height > 0;
            }
            function normalizeText(text) {
                return String(text || '').replace(/\\s+/g, ' ').trim();
            }
            function toClickable(node) {
                let cursor = node;
                while (cursor) {
                    const tag = (cursor.tagName || '').toLowerCase();
                    const role = cursor.getAttribute ? (cursor.getAttribute('role') || '').toLowerCase() : '';
                    if (tag === 'button' || tag === 'a' || role === 'button') {
                        return cursor;
                    }
                    cursor = cursor.parentElement;
                }
                return node;
            }
            function isEnabled(node) {
                if (!node) return false;
                if (node.disabled) return false;
                const aria = node.getAttribute ? (node.getAttribute('aria-disabled') || '').toLowerCase() : '';
                if (aria === 'true') return false;
                const style = window.getComputedStyle(node);
                if (style.pointerEvents === 'none') return false;
                return true;
            }
            function hasTokenActions(row) {
                if (!row) return false;
                const texts = Array.from(row.querySelectorAll('button, a, [role="button"], span, div'))
                    .map((node) => normalizeText(node.innerText || node.textContent || ''))
                    .filter((text) => !!text);
                const hasCopy = texts.some((text) => text === '复制');
                const hasEdit = texts.some((text) => text === '编辑');
                return hasCopy && hasEdit;
            }
            function isLikelyTokenRow(row) {
                const text = normalizeText(row ? row.innerText : '');
                if (!text) return false;
                if (row && row.querySelector('th')) return false;
                if (hasTokenActions(row)) return true;
                return text.includes('已启用') && text.includes('用户分组') && text.includes('编辑');
            }
            function collectEditCandidates(root) {
                const exact = [];
                const fuzzy = [];
                const nodes = Array.from(root.querySelectorAll('button, a, [role="button"], span, div'));
                for (const node of nodes) {
                    const text = normalizeText(node.innerText || node.textContent || '');
                    if (!text || !text.includes('编辑') || !isVisible(node)) continue;

                    const hasChildExactEdit = Array.from(node.querySelectorAll('*')).some((child) => {
                        const childText = normalizeText(child.innerText || child.textContent || '');
                        return childText === '编辑';
                    });
                    if (hasChildExactEdit && text !== '编辑') continue;

                    const clickable = toClickable(node);
                    if (!isVisible(clickable) || !isEnabled(clickable)) continue;
                    const clickableText = normalizeText(clickable.innerText || clickable.textContent || '');
                    if (clickableText.includes('复制') && clickableText.includes('编辑') && text !== '编辑') {
                        continue;
                    }

                    const bucket = (text === '编辑' || clickableText === '编辑') ? exact : fuzzy;
                    if (!bucket.includes(clickable)) {
                        bucket.push(clickable);
                    }
                }
                return exact.concat(fuzzy);
            }
            function clickWithEvents(node) {
                if (!node) return { clicked: false, reason: 'no_target' };
                node.scrollIntoView({ block: 'center', inline: 'center' });
                const rect = node.getBoundingClientRect();
                const x = Math.floor(rect.left + rect.width / 2);
                const y = Math.floor(rect.top + rect.height / 2);
                const target = node;
                const events = ['pointerover', 'mouseover', 'pointerdown', 'mousedown', 'pointerup', 'mouseup', 'click'];
                for (const name of events) {
                    const Ctor = name.startsWith('pointer') ? PointerEvent : MouseEvent;
                    target.dispatchEvent(new Ctor(name, {
                        bubbles: true,
                        cancelable: true,
                        view: window,
                        clientX: x,
                        clientY: y
                    }));
                }
                if (typeof node.click === 'function') {
                    node.click();
                }
                return {
                    clicked: true,
                    x: x,
                    y: y,
                    targetTag: (target.tagName || '').toLowerCase(),
                    targetText: normalizeText(target.innerText || target.textContent || '').slice(0, 40)
                };
            }

            const rows = Array.from(
                document.querySelectorAll('tbody tr, .semi-table-tbody .semi-table-row, .semi-table-row')
            ).filter((row) => isVisible(row) && isLikelyTokenRow(row));
            const row = rows.length ? rows[0] : null;
            const tableRoot = row ? (row.closest('table, .semi-table, .semi-table-wrapper') || row.parentElement) : document.body;
            const searchRoot = row || tableRoot || document.body;

            const candidates = collectEditCandidates(searchRoot);
            if (!candidates.length) {
                return {
                    clicked: false,
                    reason: 'no_global_edit',
                    rowText: row ? normalizeText(row.innerText || '').slice(0, 120) : ''
                };
            }

            const target = candidates[0];
            const clickInfo = clickWithEvents(target);
            return {
                clicked: clickInfo.clicked,
                reason: 'global_edit',
                candidateCount: candidates.length,
                rowText: row ? normalizeText(row.innerText || '').slice(0, 120) : '',
                candidateText: normalizeText(target.innerText || target.textContent || '').slice(0, 40),
                x: clickInfo.x,
                y: clickInfo.y,
                targetTag: clickInfo.targetTag,
                targetText: clickInfo.targetText
            };
        """

        try:
            WebDriverWait(driver, timeout).until(lambda d: d.execute_script(wait_row_script))
            self.logger.debug("检测到页面存在可操作令牌行")
        except TimeoutException:
            self.logger.debug("未检测到可操作令牌行")
            return False, "未找到可编辑的令牌"

        strategies = [
            ("首行直点编辑", direct_click_script, 2),
            ("首行菜单编辑", dropdown_click_script, 2),
            ("表格范围编辑兜底", global_click_script, 3),
        ]
        last_result = "none"

        try:
            for round_index in range(1, 4):
                self.logger.debug(f"打开编辑弹窗第 {round_index}/3 轮尝试")
                for strategy_name, script, wait_seconds in strategies:
                    result = driver.execute_script(script)
                    self.logger.debug(f"{strategy_name} 返回: {result}")

                    if not isinstance(result, dict) or not result.get("clicked"):
                        last_result = result
                        continue

                    try:
                        WebDriverWait(driver, wait_seconds).until(
                            lambda d: d.execute_script(editor_open_script)
                        )
                        self.logger.debug(f"{strategy_name} 成功打开编辑弹窗")
                        return True, ""
                    except TimeoutException:
                        self.logger.debug(f"{strategy_name} 已点击但弹窗仍未出现")
                        last_result = result
                        time.sleep(0.2)
                        continue

                try:
                    driver.execute_script(
                        """
                        if (document && document.body) {
                            document.body.dispatchEvent(new MouseEvent('click', {
                                bubbles: true,
                                cancelable: true,
                                view: window
                            }));
                        }
                        """
                    )
                except Exception:
                    pass
                time.sleep(0.2)
        except Exception as e:
            self.logger.debug(f"点击编辑按钮流程异常: {e}")
            return False, f"点击编辑按钮失败: {e}"

        diag = self._collect_editor_open_diag()
        self.logger.debug(f"所有策略尝试后仍未打开弹窗，最后结果: {last_result}")
        return False, f"编辑弹窗未正常打开 ({diag},last={last_result})"

    def _collect_editor_open_diag(self) -> str:
        """收集编辑弹窗打开失败时的诊断信息"""
        driver = self.browser.driver
        try:
            info = driver.execute_script(
                """
                function isVisible(node) {
                    if (!node) return false;
                    const style = window.getComputedStyle(node);
                    if (style.display === 'none' || style.visibility === 'hidden') return false;
                    const rect = node.getBoundingClientRect();
                    return rect.width > 0 && rect.height > 0;
                }

                const editCount = Array.from(
                    document.querySelectorAll('button, a, [role="button"], span, div')
                ).filter((node) => {
                    const text = (node.innerText || node.textContent || '').trim();
                    return text.includes('编辑') && isVisible(node);
                }).length;

                const enabledEditCount = Array.from(
                    document.querySelectorAll('button, a, [role="button"], span, div')
                ).filter((node) => {
                    const text = (node.innerText || node.textContent || '').trim();
                    if (!text.includes('编辑') || !isVisible(node)) return false;
                    let clickable = node;
                    while (clickable) {
                        const tag = (clickable.tagName || '').toLowerCase();
                        const role = clickable.getAttribute ? (clickable.getAttribute('role') || '').toLowerCase() : '';
                        if (tag === 'button' || tag === 'a' || role === 'button') break;
                        clickable = clickable.parentElement;
                    }
                    clickable = clickable || node;
                    if (!isVisible(clickable)) return false;
                    if (clickable.disabled) return false;
                    const aria = clickable.getAttribute ? (clickable.getAttribute('aria-disabled') || '').toLowerCase() : '';
                    if (aria === 'true') return false;
                    const style = window.getComputedStyle(clickable);
                    if (style.pointerEvents === 'none') return false;
                    return true;
                }).length;

                function isTokenRow(row) {
                    if (!isVisible(row)) return false;
                    if (row.querySelector('th')) return false;
                    const text = (row.innerText || '').replace(/\\s+/g, '');
                    const actionTexts = Array.from(row.querySelectorAll('button, a, [role="button"], span, div'))
                        .map((node) => (node.innerText || node.textContent || '').replace(/\\s+/g, '').trim())
                        .filter((item) => !!item);
                    const hasCopy = actionTexts.some((item) => item === '复制');
                    const hasEdit = actionTexts.some((item) => item === '编辑');
                    if (hasCopy && hasEdit) return true;
                    return text.includes('已启用') && text.includes('用户分组') && text.includes('编辑');
                }

                const tokenRows = Array.from(
                    document.querySelectorAll('tbody tr, .semi-table-tbody .semi-table-row, .semi-table-row')
                ).filter((row) => isTokenRow(row));

                const rowEditCount = tokenRows.filter((row) => {
                    const hasEdit = Array.from(row.querySelectorAll('button, a, [role="button"], span, div')).some((node) => {
                        const t = (node.innerText || node.textContent || '').trim();
                        return t.includes('编辑') && isVisible(node);
                    });
                    return hasEdit;
                }).length;

                const rowEnabledEditCount = tokenRows.filter((row) => {
                    const hasEnabledEdit = Array.from(row.querySelectorAll('button, a, [role="button"], span, div')).some((node) => {
                        const t = (node.innerText || node.textContent || '').trim();
                        if (!t.includes('编辑') || !isVisible(node)) return false;
                        let clickable = node;
                        while (clickable) {
                            const tag = (clickable.tagName || '').toLowerCase();
                            const role = clickable.getAttribute ? (clickable.getAttribute('role') || '').toLowerCase() : '';
                            if (tag === 'button' || tag === 'a' || role === 'button') break;
                            clickable = clickable.parentElement;
                        }
                        clickable = clickable || node;
                        if (!isVisible(clickable)) return false;
                        if (clickable.disabled) return false;
                        const aria = clickable.getAttribute ? (clickable.getAttribute('aria-disabled') || '').toLowerCase() : '';
                        if (aria === 'true') return false;
                        const style = window.getComputedStyle(clickable);
                        if (style.pointerEvents === 'none') return false;
                        return true;
                    });
                    return hasEnabledEdit;
                }).length;

                const firstRow = tokenRows.length ? tokenRows[0] : null;
                const firstRowText = firstRow ? (firstRow.innerText || '').replace(/\\s+/g, ' ').trim().slice(0, 120) : '';

                const dialogCount = Array.from(
                    document.querySelectorAll(
                        '.semi-modal-content, .semi-modal, .semi-sidesheet, .semi-sidesheet-content, .semi-sideSheet, [class*="sidesheet"], [class*="sideSheet"], [role="dialog"]'
                    )
                ).filter(isVisible).length;

                const quotaCount = Array.from(document.querySelectorAll('*')).filter((node) => {
                    return isVisible(node) && (node.textContent || '').trim() === '额度';
                }).length;

                const submitCount = Array.from(document.querySelectorAll('button, [role="button"]')).filter((btn) => {
                    const text = (btn.innerText || btn.textContent || '').trim();
                    return isVisible(btn) && text.includes('提交') && !btn.disabled;
                }).length;

                return {
                    editCount,
                    enabledEditCount,
                    rowEditCount,
                    rowEnabledEditCount,
                    dialogCount,
                    quotaCount,
                    submitCount,
                    firstRowText,
                    url: window.location.href || ''
                };
                """
            )
            if isinstance(info, dict):
                return (
                    f"url={info.get('url','')},edit={info.get('editCount')},"
                    f"enabledEdit={info.get('enabledEditCount')},rowEdit={info.get('rowEditCount')},"
                    f"rowEnabledEdit={info.get('rowEnabledEditCount')},"
                    f"dialog={info.get('dialogCount')},quota={info.get('quotaCount')},"
                    f"submit={info.get('submitCount')},rowText={info.get('firstRowText','')}"
                )
        except Exception as e:
            self.logger.debug(f"收集编辑弹窗诊断信息失败: {e}")
        return "diag_unavailable"

    def _detect_quota_unit_rate(self) -> float:
        """从弹窗文案中识别额度换算比例，失败时使用默认值"""
        driver = self.browser.driver
        default_rate = float(self.QUOTA_UNIT_PER_DOLLAR)
        self.logger.debug(f"开始检测额度换算比例，默认比例={default_rate:.0f}")

        try:
            result = driver.execute_script(
                """
                function isVisible(node) {
                    if (!node) return false;
                    const style = window.getComputedStyle(node);
                    if (style.display === 'none' || style.visibility === 'hidden') return false;
                    const rect = node.getBoundingClientRect();
                    return rect.width > 0 && rect.height > 0;
                }
                const roots = Array.from(document.querySelectorAll(
                    '.semi-modal-content, .semi-modal, .semi-sidesheet, .semi-sidesheet-content, .semi-sideSheet, [class*="sidesheet"], [class*="sideSheet"], [role="dialog"]'
                ));
                let root = roots.find((item) => item && isVisible(item) && (
                    (item.innerText || '').includes('更新令牌信息') || (item.innerText || '').includes('额度设置')
                ));
                if (!root) {
                    root = roots.find((item) => item && isVisible(item));
                }
                if (!root) {
                    root = document.body;
                }

                const text = root.innerText || '';
                const amountMatch = text.match(/等价金额[:：]\\s*\\$\\s*(-?[\\d,.]+)/);
                const amountValue = amountMatch ? Number((amountMatch[1] || '').replace(/,/g, '')) : null;

                const labels = Array.from(root.querySelectorAll('*')).filter((el) => {
                    const t = (el.textContent || '').trim();
                    return t === '额度';
                });

                function findInput(startNode) {
                    let node = startNode;
                    for (let i = 0; i < 6 && node; i += 1) {
                        const parent = node.parentElement;
                        if (!parent) break;
                        const input = parent.querySelector('input');
                        if (input && isVisible(input)) return input;
                        node = parent;
                    }
                    return null;
                }

                let quotaValue = null;
                for (const label of labels) {
                    const input = findInput(label);
                    if (!input) continue;
                    const raw = (input.value || '').replace(/,/g, '').trim();
                    if (!raw) continue;
                    const num = Number(raw);
                    if (!Number.isNaN(num)) {
                        quotaValue = num;
                        break;
                    }
                }

                return {quotaValue, amountValue};
                """
            )

            if not isinstance(result, dict):
                self.logger.debug("换算比例识别返回非字典结果，使用默认比例")
                return default_rate

            quota_value = result.get("quotaValue")
            amount_value = result.get("amountValue")
            self.logger.debug(
                f"换算比例识别原始数据: quotaValue={quota_value}, amountValue={amount_value}"
            )

            if quota_value is None or amount_value in (None, 0):
                self.logger.debug("换算比例识别缺少有效数据，使用默认比例")
                return default_rate

            rate = abs(float(quota_value) / float(amount_value))
            if 1000 <= rate <= 10000000:
                self.logger.debug(f"换算比例识别成功: {rate:.6f}")
                return rate
            self.logger.debug(f"换算比例超出范围({rate:.6f})，使用默认比例")
            return default_rate

        except Exception:
            self.logger.debug("换算比例识别异常，使用默认比例")
            return default_rate

    def _set_modal_quota_value(self, quota_value: int) -> Tuple[bool, str]:
        """在编辑弹窗中填写额度"""
        driver = self.browser.driver
        self.logger.debug(f"准备写入额度值: {quota_value}")

        try:
            write_result = driver.execute_script(
                """
                const targetQuota = String(arguments[0]);

                function isVisible(node) {
                    if (!node) return false;
                    const style = window.getComputedStyle(node);
                    if (style.display === 'none' || style.visibility === 'hidden') return false;
                    const rect = node.getBoundingClientRect();
                    return rect.width > 0 && rect.height > 0;
                }

                function normalizeText(text) {
                    return String(text || '').replace(/\\s+/g, ' ').trim();
                }

                function normalizeDigits(text) {
                    return String(text || '').replace(/[,\\s]/g, '').trim();
                }

                function locateRoot() {
                    const roots = Array.from(document.querySelectorAll(
                        '.semi-modal-content, .semi-modal, .semi-sidesheet, .semi-sidesheet-content, .semi-sideSheet, [class*="sidesheet"], [class*="sideSheet"], [role="dialog"]'
                    ));
                    let root = roots.find((item) => item && isVisible(item) && (
                        (item.innerText || '').includes('更新令牌信息') || (item.innerText || '').includes('额度设置')
                    ));
                    if (!root) {
                        root = roots.find((item) => item && isVisible(item));
                    }
                    return root || document.body;
                }

                function isWritableInput(input) {
                    if (!input) return false;
                    if (!isVisible(input)) return false;
                    if (input.disabled) return false;
                    const type = String(input.type || '').toLowerCase();
                    if (type === 'hidden') return false;
                    return true;
                }

                function addCandidate(list, input, strategy) {
                    if (!isWritableInput(input)) return;
                    if (!list.some((item) => item.input === input)) {
                        list.push({ input, strategy });
                    }
                }

                function collectCandidates(root) {
                    const list = [];

                    // 优先：根据“额度”标签向上回溯输入框
                    const labels = Array.from(root.querySelectorAll('*')).filter((el) => {
                        return normalizeText(el.textContent || '') === '额度';
                    });
                    for (const label of labels) {
                        let node = label;
                        for (let i = 0; i < 8 && node; i += 1) {
                            const parent = node.parentElement;
                            if (!parent) break;
                            const input = parent.querySelector('input');
                            if (input) {
                                addCandidate(list, input, 'label_quota');
                            }
                            node = parent;
                        }
                    }

                    // 次优：按语义属性匹配
                    const semanticInputs = Array.from(root.querySelectorAll('input')).filter((input) => {
                        if (!isWritableInput(input)) return false;
                        const haystack = [
                            input.getAttribute('placeholder') || '',
                            input.getAttribute('name') || '',
                            input.getAttribute('id') || '',
                            input.getAttribute('aria-label') || '',
                            input.className || ''
                        ].join(' ').toLowerCase();
                        return (
                            haystack.includes('额度') ||
                            haystack.includes('quota') ||
                            haystack.includes('limit')
                        );
                    });
                    for (const input of semanticInputs) {
                        addCandidate(list, input, 'semantic');
                    }

                    // 最后：弹窗内可写输入框兜底
                    const fallbackInputs = Array.from(root.querySelectorAll('input'));
                    for (const input of fallbackInputs) {
                        addCandidate(list, input, 'fallback');
                    }

                    return list;
                }

                function writeInputValue(input, value) {
                    try {
                        input.removeAttribute('readonly');
                    } catch (e) {}

                    const descriptor = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, 'value');
                    if (descriptor && descriptor.set) {
                        descriptor.set.call(input, value);
                    } else {
                        input.value = value;
                    }

                    input.dispatchEvent(new Event('input', { bubbles: true }));
                    input.dispatchEvent(new Event('change', { bubbles: true }));
                    input.dispatchEvent(new Event('blur', { bubbles: true }));
                    input.dispatchEvent(new KeyboardEvent('keyup', {
                        bubbles: true,
                        key: 'Enter',
                        code: 'Enter'
                    }));
                }

                const root = locateRoot();
                const candidates = collectCandidates(root);

                if (!candidates.length) {
                    return {
                        ok: false,
                        reason: 'quota_input_not_found',
                        candidateCount: 0
                    };
                }

                const targetDigits = normalizeDigits(targetQuota);
                const tried = [];
                for (let idx = 0; idx < candidates.length; idx += 1) {
                    const item = candidates[idx];
                    const input = item.input;

                    try {
                        input.focus();
                    } catch (e) {}

                    writeInputValue(input, targetQuota);
                    const currentDigits = normalizeDigits(input.value || '');
                    const currentText = normalizeText(input.value || '');

                    tried.push({
                        index: idx + 1,
                        strategy: item.strategy,
                        value: currentText
                    });

                    if (currentDigits === targetDigits) {
                        return {
                            ok: true,
                            reason: 'written',
                            strategy: item.strategy,
                            index: idx + 1,
                            value: currentText,
                            candidateCount: candidates.length,
                            tried
                        };
                    }
                }

                return {
                    ok: false,
                    reason: 'write_verify_failed',
                    candidateCount: candidates.length,
                    tried
                };
                """,
                quota_value
            )

            if not isinstance(write_result, dict):
                self.logger.debug(f"额度输入返回异常结果: {write_result}")
                return False, "额度输入返回异常结果"

            if not write_result.get("ok"):
                self.logger.debug(f"额度输入失败详情: {write_result}")
                return False, f"未能写入额度值: {write_result.get('reason')}"

            self.logger.debug(
                "额度输入框赋值成功: "
                f"strategy={write_result.get('strategy')},"
                f"index={write_result.get('index')}/{write_result.get('candidateCount')},"
                f"value={write_result.get('value')}"
            )
            return True, ""
        except Exception as e:
            self.logger.debug(f"额度输入写入异常: {e}")
            return False, f"填写额度失败: {e}"

    def _submit_quota_modal(self, timeout: int = 8) -> Tuple[bool, str]:
        """提交编辑弹窗并等待关闭"""
        driver = self.browser.driver
        self.logger.debug("准备提交额度编辑弹窗")

        try:
            submit_button = driver.execute_script(
                """
                function isVisible(node) {
                    if (!node) return false;
                    const style = window.getComputedStyle(node);
                    if (style.display === 'none' || style.visibility === 'hidden') return false;
                    const rect = node.getBoundingClientRect();
                    return rect.width > 0 && rect.height > 0;
                }
                const roots = Array.from(document.querySelectorAll(
                    '.semi-modal-content, .semi-modal, .semi-sidesheet, .semi-sidesheet-content, .semi-sideSheet, [class*="sidesheet"], [class*="sideSheet"], [role="dialog"]'
                ));
                let root = roots.find((item) => item && isVisible(item) && (
                    (item.innerText || '').includes('更新令牌信息') || (item.innerText || '').includes('额度设置')
                ));
                if (!root) {
                    root = roots.find((item) => item && isVisible(item));
                }
                if (!root) {
                    root = document.body;
                }

                const buttons = Array.from(root.querySelectorAll('button'))
                    .filter((btn) => {
                        const text = (btn.innerText || btn.textContent || '').trim();
                        return text.includes('提交') && isVisible(btn) && !btn.disabled;
                    });
                return buttons.length ? buttons[0] : null;
                """
            )

            if not submit_button:
                self.logger.debug("未定位到提交按钮")
                return False, "未找到提交按钮"

            driver.execute_script("arguments[0].click();", submit_button)
            self.logger.debug("已点击提交按钮")
        except Exception as e:
            self.logger.debug(f"点击提交按钮异常: {e}")
            return False, f"提交额度失败: {e}"

        try:
            WebDriverWait(driver, timeout).until(
                lambda d: not d.execute_script(
                    """
                    function isVisible(node) {
                        if (!node) return false;
                        const style = window.getComputedStyle(node);
                        if (style.display === 'none' || style.visibility === 'hidden') return false;
                        const rect = node.getBoundingClientRect();
                        return rect.width > 0 && rect.height > 0;
                    }
                    const roots = Array.from(document.querySelectorAll(
                        '.semi-modal-content, .semi-modal, .semi-sidesheet, .semi-sidesheet-content, .semi-sideSheet, [class*="sidesheet"], [class*="sideSheet"], [role="dialog"]'
                    ));
                    return roots.some((root) => {
                        if (!root || !isVisible(root)) return false;
                        const text = root.innerText || '';
                        return text.includes('更新令牌信息') || text.includes('额度设置');
                    });
                    """
                )
            )
            self.logger.debug("提交后弹窗已关闭")
            return True, ""
        except TimeoutException:
            self.logger.debug("提交后弹窗未关闭（超时）")
            return False, "提交后弹窗未关闭，可能保存失败"


class BalanceExtractor:
    """余额提取器"""

    def __init__(self, browser_manager: BrowserManager):
        """初始化余额提取器"""
        self.browser = browser_manager
        self.logger = logging.getLogger(__name__)

    def extract_balance(self, wait_time: int = 3) -> Tuple[Optional[str], bool]:
        """高性能余额提取 - 优化DOM查询效率"""
        try:
            # 增加初始等待时间，确保页面完全加载
            time.sleep(wait_time)

            # 等待骨架屏消失
            try:
                WebDriverWait(self.browser.driver, 10).until_not(
                    EC.presence_of_element_located((By.CSS_SELECTOR, ".semi-skeleton"))
                )
            except:
                pass

            # 额外等待确保数据完全渲染
            time.sleep(1)

            # 使用优化的提取脚本 - 避免全局DOM遍历
            balance = self.browser.execute_script("""
                // 性能优化版余额提取脚本
                function extractBalance() {
                    // 策略1: 通过已知的特定选择器查找（最快）
                    const knownSelectors = [
                        '.balance-amount',
                        '[data-balance]',
                        '.amount-display',
                        '.wallet-balance',
                        '.user-balance',
                        '.account-balance',
                        '.current-balance',
                        'span[class*="balance"]',
                        'div[class*="balance"]'
                    ];

                    for (const selector of knownSelectors) {
                        try {
                            const elem = document.querySelector(selector);
                            if (elem && elem.textContent.includes('$')) {
                                const match = elem.textContent.match(/\\$([\\d,]+\\.?\\d*)/);
                                if (match) {
                                    return '$' + parseFloat(match[1].replace(/,/g, '')).toFixed(1);
                                }
                            }
                        } catch (e) {}
                    }

                    // 策略2: 通过文本内容查找包含"余额"的元素（次快）
                    const balanceTexts = ['余额', 'Balance', '当前余额', 'Current Balance'];
                    for (const text of balanceTexts) {
                        const xpath = `//*[contains(text(), '${text}')]`;
                        const result = document.evaluate(xpath, document, null, XPathResult.FIRST_ORDERED_NODE_TYPE, null);
                        const node = result.singleNodeValue;

                        if (node) {
                            // 查找相邻元素中的金额
                            const parent = node.parentElement;
                            if (parent) {
                                const siblings = Array.from(parent.children);
                                for (const sibling of siblings) {
                                    const match = sibling.textContent.match(/\\$([\\d,]+\\.?\\d*)/);
                                    if (match) {
                                        return '$' + parseFloat(match[1].replace(/,/g, '')).toFixed(1);
                                    }
                                }

                                // 检查父元素本身
                                const parentMatch = parent.textContent.match(/\\$([\\d,]+\\.?\\d*)/);
                                if (parentMatch) {
                                    return '$' + parseFloat(parentMatch[1].replace(/,/g, '')).toFixed(1);
                                }
                            }
                        }
                    }

                    // 策略3: 通过特定样式类查找大字体元素（中速）
                    const largeTextSelectors = [
                        '.text-lg', '.text-xl', '.text-2xl', '.text-3xl',
                        'h1', 'h2', 'h3',
                        '[style*="font-size: 2"], [style*="font-size: 3"]'
                    ];

                    for (const selector of largeTextSelectors) {
                        const elements = document.querySelectorAll(selector);
                        for (const elem of elements) {
                            if (elem.textContent.match(/^\\$[\\d,]+\\.?\\d*$/)) {
                                const value = parseFloat(elem.textContent.replace(/[$,]/g, ''));
                                if (value > 0) {
                                    return '$' + value.toFixed(1);
                                }
                            }
                        }
                    }

                    // 策略4: 在特定容器内查找（避免全局搜索）
                    const containerSelectors = [
                        '.dashboard', '.console', '.account-info',
                        '.user-panel', '.wallet', 'main', '#app'
                    ];

                    for (const containerSel of containerSelectors) {
                        const container = document.querySelector(containerSel);
                        if (container) {
                            // 只在容器内搜索
                            const spans = container.querySelectorAll('span, div, p');
                            for (const elem of spans) {
                                const text = elem.textContent.trim();
                                if (text.match(/^\\$\\s*[\\d,]+\\.?\\d*$/) && elem.childElementCount === 0) {
                                    const value = parseFloat(text.replace(/[$,\\s]/g, ''));
                                    if (value > 0) {
                                        return '$' + value.toFixed(1);
                                    }
                                }
                            }
                        }
                    }

                    // 策略5: 使用正则表达式在页面文本中查找（最后手段）
                    const bodyText = document.body.innerText;
                    const patterns = [
                        /当前余额[：:\\s]*\\$([\\d,]+\\.?\\d*)/,
                        /余额[：:\\s]*\\$([\\d,]+\\.?\\d*)/,
                        /Balance[：:\\s]*\\$([\\d,]+\\.?\\d*)/i,
                        /\\$([\\d,]+\\.?\\d*)\\s*(?:USD|美元)?/
                    ];

                    for (const pattern of patterns) {
                        const match = bodyText.match(pattern);
                        if (match) {
                            return '$' + parseFloat(match[1].replace(/,/g, '')).toFixed(1);
                        }
                    }

                    return null;
                }

                // 执行提取
                return extractBalance();
            """)

            if balance:
                self.logger.info(f"成功提取余额: {balance}")
                return balance, True
            else:
                # 如果还是失败，使用备用方案
                balance = self._fallback_extraction()
                if balance:
                    self.logger.info(f"备用方案提取余额: {balance}")
                    return balance, True
                else:
                    self.logger.warning("未能提取到余额信息")
                    return "无数据", False

        except Exception as e:
            self.logger.error(f"提取余额异常: {e}")
            return "错误", False

    def _fallback_extraction(self) -> Optional[str]:
        """备用提取方案 - 简化版"""
        try:
            # 再等待2秒
            time.sleep(2)

            # 尝试获取页面所有文本并用正则匹配
            page_text = self.browser.execute_script("return document.body.innerText;")
            if page_text:
                # 查找美元金额
                import re
                matches = re.findall(r'\$\s*([\d,]+\.?\d*)', page_text)
                if matches:
                    # 过滤并选择最可能的余额（通常是较大的数值）
                    amounts = []
                    for match in matches:
                        try:
                            amount = float(match.replace(',', ''))
                            if 0 < amount < 1000000:  # 合理范围
                                amounts.append(amount)
                        except:
                            pass

                    if amounts:
                        # 选择一个合理的值（通常余额会是一个整数或.0结尾）
                        for amount in amounts:
                            if amount % 1 == 0 or str(amount).endswith('.0'):
                                return f'${amount:.1f}'
                        # 如果没有整数，返回第一个
                        return f'${amounts[0]:.1f}'

            return None
        except:
            return None



if __name__ == "__main__":
    # 测试认证管理器
    import sys
    sys.path.append('..')

    logging.basicConfig(level=logging.DEBUG)

    browser_config = {
        "headless": False,
        "window_size": "1280,720"
    }

    browser_mgr = BrowserManager(browser_config)

    with browser_mgr.create_driver() as driver:
        if driver:
            auth_mgr = AuthManager(browser_mgr)
            balance_ext = BalanceExtractor(browser_mgr)

            # 测试登录
            result = auth_mgr.login("test_user", "test_password")
            print(f"登录结果: {result}")

            if result.success:
                # 提取余额
                balance, success = balance_ext.extract_balance()
                print(f"余额: {balance}, 成功: {success}")
