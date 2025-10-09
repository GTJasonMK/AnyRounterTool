#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
认证模块 - 处理AnyRouter登录逻辑
"""

import time
import logging
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
            current_url = self.browser.get_current_url()
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
            current_url = self.browser.get_current_url()
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
            current_url = self.browser.get_current_url()
            is_logged_in = '/console' in current_url and '/login' not in current_url

            self.logger.debug(f"登录状态: {is_logged_in}")
            return is_logged_in

        except Exception as e:
            self.logger.error(f"检查登录状态失败: {e}")
            return False


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