"""统一限流模块: IP 冷却、全局间隔、并发槽位、集群失败检测。

将原本分散在 runtime.py 和 account_manager.py 中的限流逻辑收归一处。
"""
from __future__ import annotations

import logging
import threading
import time
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .db import AccountDB

_logger = logging.getLogger(__name__)


class RateLimiter:
    """管理所有与请求频率/风控相关的限制逻辑。"""

    def __init__(
        self,
        db: AccountDB,
        *,
        global_min_interval: float = 1.0,
        max_concurrent_captchas: int = 2,
    ) -> None:
        self.db = db
        self.global_min_interval = global_min_interval
        self.max_concurrent_captchas = max_concurrent_captchas

        # IP 级别全局冷却
        self._global_cooldown_until: float = 0.0
        self._global_cooldown_lock = threading.Lock()

        # 全局请求时间戳 (用于 GLOBAL_MIN_INTERVAL)
        self._last_global_request_time: float = 0.0

        # 集群失败滑动窗口: (timestamp, account_id)
        self._cluster_failures: list[tuple[float, int]] = []
        self._cluster_lock = threading.Lock()

        # Captcha 并发槽位
        self._captcha_in_flight = 0
        self._captcha_slot_lock = threading.Lock()
        self._captcha_slot_cv = threading.Condition(self._captcha_slot_lock)

    # ------------------------------------------------------------------
    # IP 冷却
    # ------------------------------------------------------------------
    def check_ip_cooldown(self) -> float | None:
        """检查是否在全局 IP 冷却期。返回剩余秒数, None 表示不在冷却。"""
        with self._global_cooldown_lock:
            now = time.time()
            if now < self._global_cooldown_until:
                return self._global_cooldown_until - now
            return None

    def trigger_ip_cooldown(self, minutes: int, reason: str = "") -> None:
        """触发全局 IP 冷却, 所有账号暂停。"""
        with self._global_cooldown_lock:
            self._global_cooldown_until = time.time() + minutes * 60
            _logger.warning("IP level rate limit: global cooldown %d minutes (%s)", minutes, reason)
        self.db.record_event("ip_cooldown", detail=f"{minutes}min: {reason}")

    # ------------------------------------------------------------------
    # 全局请求间隔
    # ------------------------------------------------------------------
    def acquire_ip_slot(self) -> float:
        """获取全局请求槽位: 阻塞直到距上次请求 ≥ global_min_interval。

        返回实际等待的秒数。
        """
        while True:
            with self._global_cooldown_lock:
                wait = self._last_global_request_time + self.global_min_interval - time.time()
                if wait <= 0:
                    self._last_global_request_time = time.time()
                    return 0.0
            time.sleep(min(wait, 0.5))

    # ------------------------------------------------------------------
    # Captcha 并发槽位
    # ------------------------------------------------------------------
    def acquire_captcha_slot(self) -> None:
        """获取 captcha 槽位: 阻塞直到 in-flight captcha < max_concurrent_captchas。"""
        with self._captcha_slot_cv:
            while self._captcha_in_flight >= self.max_concurrent_captchas:
                self._captcha_slot_cv.wait(timeout=0.5)
            self._captcha_in_flight += 1

    def release_captcha_slot(self) -> None:
        """释放 captcha 槽位。"""
        with self._captcha_slot_cv:
            self._captcha_in_flight = max(0, self._captcha_in_flight - 1)
            self._captcha_slot_cv.notify_all()

    # ------------------------------------------------------------------
    # 集群失败检测
    # ------------------------------------------------------------------
    def report_failure(self, kind: str, body: str = "", account_id: int = 0) -> None:
        """汇报一次请求失败, 用于 IP 级别的集群失败检测。

        限流类错误才会触发集群检测; 单账号反复失败不等于 IP 问题。
        """
        is_rate_signal = (
            "限流" in kind
            or "verify_failed" in (body or "")
            or "FRONTEND_CAPTCHA_REQUIRED" in (body or "")
            or "F018" in (body or "")
        )
        if not is_rate_signal:
            return

        with self._cluster_lock:
            now = time.time()
            self._cluster_failures.append((now, account_id))
            # 60s 滑动窗口
            cutoff = now - 60
            self._cluster_failures = [
                (t, aid) for (t, aid) in self._cluster_failures if t >= cutoff
            ]

            unique_accounts = {aid for (_, aid) in self._cluster_failures if aid}
            active_count = len(self.db.list_active_accounts())
            threshold = max(3, active_count // 2)

            if len(unique_accounts) >= threshold:
                self.trigger_ip_cooldown(
                    minutes=30,
                    reason=f"60s 内 {len(unique_accounts)}/{active_count} 个账号触发限流",
                )
                self._cluster_failures.clear()

    def report_success(self) -> None:
        """汇报一次请求成功, 清空集群失败窗口。"""
        with self._cluster_lock:
            self._cluster_failures.clear()
