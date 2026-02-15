#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
API余额查询客户端 - 通过API Key快速获取余额
"""

import json
import logging
import re
from dataclasses import dataclass
from datetime import date
from typing import Any, Dict, Optional

import requests


@dataclass
class ApiBalanceResult:
    """API余额查询结果"""
    success: bool
    balance: Optional[float] = None
    source: str = ""
    message: str = ""


class ApiBalanceClient:
    """基于API Key的快速余额查询客户端"""

    DEFAULT_BASE_URL = "https://anyrouter.top"
    # 与页面额度换算保持一致
    QUOTA_UNIT_PER_DOLLAR = 500000.0

    def __init__(self, base_url: str = DEFAULT_BASE_URL, timeout: int = 8):
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.logger = logging.getLogger(__name__)

    def query_balance(self, api_key: str) -> ApiBalanceResult:
        """尝试多个API端点查询余额，成功即返回"""
        key = (api_key or "").strip()
        if not key:
            return ApiBalanceResult(False, message="缺少 API Key")

        headers = {
            "Authorization": f"Bearer {key}",
            "Accept": "application/json"
        }

        # 优先走已验证可用的账单路由：subscription + usage
        billing_result = self._query_via_billing_routes(headers)
        if billing_result.success:
            return billing_result

        # 兼容常见 OpenAI/代理接口的余额端点
        candidates = [
            ("GET", f"/v1/dashboard/billing/usage?start_date={self._month_start()}&end_date={self._today()}", None),
            ("GET", "/v1/dashboard/billing/subscription", None),
            ("GET", "/v1/dashboard/billing/credit_grants", None),
            ("GET", "/dashboard/billing/credit_grants", None),
            ("GET", "/api/user/balance", None),
            ("GET", "/api/user/self", None),
            ("GET", "/api/user/info", None),
            ("GET", "/api/token/self", None),
            ("GET", "/api/token/info", None),
            ("GET", "/v1/models", None),
        ]

        last_error = "未命中可用余额接口"

        for method, path, payload in candidates:
            url = f"{self.base_url}{path}"
            try:
                response = requests.request(
                    method=method,
                    url=url,
                    headers=headers,
                    json=payload,
                    timeout=self.timeout
                )
            except Exception as e:
                last_error = f"请求异常({path}): {e}"
                self.logger.debug(last_error)
                continue

            if response.status_code >= 400:
                last_error = f"HTTP {response.status_code} ({path})"
                self.logger.debug(last_error)
                continue

            # 优先从响应头提取（部分网关会返回余额头）
            header_value = self._extract_balance_from_headers(response.headers)
            if header_value is not None:
                return ApiBalanceResult(
                    success=True,
                    balance=header_value,
                    source=f"header:{path}",
                    message="通过响应头获取余额"
                )

            # 再从响应体提取
            body_value = self._extract_balance_from_response(response)
            if body_value is not None:
                return ApiBalanceResult(
                    success=True,
                    balance=body_value,
                    source=f"body:{path}",
                    message="通过响应体获取余额"
                )

            last_error = f"接口无可解析余额字段({path})"

        return ApiBalanceResult(False, message=last_error)

    def _query_via_billing_routes(self, headers: Dict[str, str]) -> ApiBalanceResult:
        """
        通过已验证的账单路由计算余额：
        1) /v1/dashboard/billing/subscription -> hard_limit_usd
        2) /v1/dashboard/billing/usage -> total_usage
        balance = hard_limit_usd - usage_usd
        """
        sub_path = "/v1/dashboard/billing/subscription"
        usage_path = (
            f"/v1/dashboard/billing/usage?"
            f"start_date={self._month_start()}&end_date={self._today()}"
        )
        sub_url = f"{self.base_url}{sub_path}"
        usage_url = f"{self.base_url}{usage_path}"

        try:
            sub_resp = requests.get(sub_url, headers=headers, timeout=self.timeout)
            usage_resp = requests.get(usage_url, headers=headers, timeout=self.timeout)
        except Exception as e:
            self.logger.debug(f"账单路由请求异常: {e}")
            return ApiBalanceResult(False, message=f"账单路由请求异常: {e}")

        if sub_resp.status_code >= 400 or usage_resp.status_code >= 400:
            self.logger.debug(
                "账单路由返回异常: "
                f"subscription={sub_resp.status_code}, usage={usage_resp.status_code}"
            )
            return ApiBalanceResult(
                False,
                message=(
                    "账单路由HTTP异常: "
                    f"subscription={sub_resp.status_code},usage={usage_resp.status_code}"
                )
            )

        sub_data = self._safe_json(sub_resp)
        usage_data = self._safe_json(usage_resp)
        if not isinstance(sub_data, dict) or not isinstance(usage_data, dict):
            return ApiBalanceResult(False, message="账单路由响应非JSON对象")

        hard_limit = self._to_float(
            sub_data.get("hard_limit_usd", sub_data.get("soft_limit_usd"))
        )
        usage_raw = self._to_float(usage_data.get("total_usage"))
        if hard_limit is None or usage_raw is None:
            return ApiBalanceResult(False, message="账单路由缺少 hard_limit_usd 或 total_usage")

        usage_usd = self._usage_to_usd(usage_raw, hard_limit)
        remain = max(float(hard_limit) - float(usage_usd), 0.0)

        self.logger.debug(
            "账单路由余额计算: "
            f"hard_limit_usd={hard_limit:.6f}, total_usage_raw={usage_raw:.6f}, "
            f"usage_usd={usage_usd:.6f}, remain={remain:.6f}"
        )
        return ApiBalanceResult(
            success=True,
            balance=remain,
            source="billing:subscription+usage",
            message="通过账单路由计算余额"
        )

    @staticmethod
    def _month_start() -> str:
        today = date.today()
        return today.replace(day=1).isoformat()

    @staticmethod
    def _today() -> str:
        return date.today().isoformat()

    @staticmethod
    def _usage_to_usd(usage_value: float, hard_limit_usd: float) -> float:
        """
        将 usage 统一换算到美元。
        已验证 anyrouter 返回的 total_usage 为“美分”，但保留兼容判断。
        """
        usage = float(usage_value)
        hard = max(float(hard_limit_usd), 0.0)
        if hard > 0 and usage > hard * 2:
            return usage / 100.0
        return usage

    def _extract_balance_from_headers(self, headers: Dict[str, Any]) -> Optional[float]:
        """从HTTP响应头提取余额字段"""
        if not headers:
            return None

        # requests 的 headers 大小写不敏感，这里统一字符串对比
        header_map = {str(k).lower(): str(v) for k, v in headers.items()}

        usd_keys = [
            "x-balance", "x-user-balance", "x-credit-balance",
            "x-remaining-balance", "x-total-available", "x-account-balance"
        ]
        quota_keys = [
            "x-quota", "x-remaining-quota", "x-total-quota"
        ]

        for key in usd_keys:
            if key in header_map:
                value = self._parse_first_number(header_map[key])
                if value is not None:
                    return max(value, 0.0)

        for key in quota_keys:
            if key in header_map:
                value = self._parse_first_number(header_map[key])
                if value is not None:
                    return max(value / self.QUOTA_UNIT_PER_DOLLAR, 0.0)

        return None

    def _extract_balance_from_response(self, response: requests.Response) -> Optional[float]:
        """从响应体中提取余额字段"""
        data = self._safe_json(response)
        if data is None:
            return None

        # OpenAI credit_grants 常见结构
        if isinstance(data, dict):
            if "total_available" in data:
                value = self._to_float(data.get("total_available"))
                if value is not None:
                    return max(value, 0.0)

            if "balance" in data:
                value = self._to_float(data.get("balance"))
                if value is not None:
                    # balance 字段可能是额度单位，优先按美元解释；异常大值按额度换算
                    return max(self._normalize_balance_value(value, key_hint="balance"), 0.0)

            # 递归扫描常见余额字段
            found = self._scan_balance_value(data)
            if found is not None:
                return max(found, 0.0)

        return None

    def _safe_json(self, response: requests.Response) -> Optional[Any]:
        """安全解析JSON"""
        try:
            return response.json()
        except Exception:
            text = (response.text or "").strip()
            if not text:
                return None
            try:
                return json.loads(text)
            except Exception:
                return None

    def _scan_balance_value(self, obj: Any, depth: int = 0) -> Optional[float]:
        """递归扫描对象中的余额/额度字段"""
        if depth > 5:
            return None

        if isinstance(obj, dict):
            usd_field_patterns = [
                "balance", "remaining_balance", "available_balance",
                "current_balance", "credit_balance", "total_available",
                "available_credit", "remain_amount"
            ]
            quota_field_patterns = [
                "quota", "remaining_quota", "remain_quota", "left_quota", "available_quota"
            ]

            # 先尝试美元字段
            for key, value in obj.items():
                key_lower = str(key).lower()
                if any(pattern in key_lower for pattern in usd_field_patterns):
                    parsed = self._to_float(value)
                    if parsed is not None:
                        return self._normalize_balance_value(parsed, key_hint=key_lower)

            # 再尝试额度字段
            for key, value in obj.items():
                key_lower = str(key).lower()
                if any(pattern in key_lower for pattern in quota_field_patterns):
                    parsed = self._to_float(value)
                    if parsed is not None:
                        return parsed / self.QUOTA_UNIT_PER_DOLLAR

            # 递归遍历
            for value in obj.values():
                nested = self._scan_balance_value(value, depth + 1)
                if nested is not None:
                    return nested

        elif isinstance(obj, list):
            for item in obj:
                nested = self._scan_balance_value(item, depth + 1)
                if nested is not None:
                    return nested

        return None

    def _normalize_balance_value(self, value: float, key_hint: str = "") -> float:
        """
        归一化余额值。
        经验规则：若字段名偏向 quota 或数值异常大，按额度单位转美元。
        """
        normalized = float(value)
        if "quota" in key_hint:
            return normalized / self.QUOTA_UNIT_PER_DOLLAR

        if abs(normalized) > 100000:
            return normalized / self.QUOTA_UNIT_PER_DOLLAR

        return normalized

    @staticmethod
    def _parse_first_number(text: str) -> Optional[float]:
        """从字符串提取第一个数值"""
        if not text:
            return None
        match = re.search(r"-?[\d,]+(?:\.\d+)?", text)
        if not match:
            return None
        try:
            return float(match.group(0).replace(",", ""))
        except ValueError:
            return None

    def _to_float(self, value: Any) -> Optional[float]:
        """将任意值转换为浮点数"""
        if value is None:
            return None

        if isinstance(value, (int, float)):
            return float(value)

        if isinstance(value, str):
            return self._parse_first_number(value)

        return None
