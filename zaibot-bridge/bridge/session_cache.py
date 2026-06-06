"""TTL + LRU Session 缓存：自动淘汰过期和超容量 session，防止 OOM。

设计要点：
- 每个会话记录最后访问时间，超过 TTL 未活跃则可被清理
- 容量上限：超过 max_size 时淘汰最久未访问的 session
- 线程安全：所有操作加锁
- 后台清理：由调用方定期调用 sweep_expired() 或启动 asyncio 后台任务
"""
from __future__ import annotations

import threading
import time
from collections import OrderedDict
from dataclasses import dataclass, field
from typing import Generic, TypeVar

V = TypeVar("V")


@dataclass
class CacheStats:
    """缓存统计快照。"""
    size: int
    max_size: int
    ttl_seconds: float
    evicted_ttl: int
    evicted_lru: int


@dataclass
class _Entry(Generic[V]):
    value: V
    last_access: float = field(default_factory=time.monotonic)


class TTLCache(Generic[V]):
    """线程安全的 TTL + LRU 缓存。

    - TTL: 超过 ttl_seconds 未访问的条目视为过期，sweep 时清除
    - LRU: 超过 max_size 时，淘汰最久未访问的条目
    - 接口兼容 dict：__getitem__, __contains__, __setitem__, __delitem__, __len__
    """

    def __init__(
        self,
        *,
        max_size: int = 256,
        ttl_seconds: float = 1800.0,
    ) -> None:
        if max_size < 1:
            raise ValueError("max_size must be >= 1")
        if ttl_seconds <= 0:
            raise ValueError("ttl_seconds must be > 0")

        self._max_size = max_size
        self._ttl = ttl_seconds
        self._data: OrderedDict[str, _Entry[V]] = OrderedDict()
        self._lock = threading.Lock()
        self._evicted_ttl = 0
        self._evicted_lru = 0

    def __contains__(self, key: str) -> bool:
        with self._lock:
            entry = self._data.get(key)
            if entry is None:
                return False
            if (time.monotonic() - entry.last_access) > self._ttl:
                return False
            return True

    def __getitem__(self, key: str) -> V:
        with self._lock:
            entry = self._data[key]
            entry.last_access = time.monotonic()
            self._data.move_to_end(key)
            return entry.value

    def __setitem__(self, key: str, value: V) -> None:
        with self._lock:
            if key in self._data:
                entry = self._data[key]
                entry.value = value
                entry.last_access = time.monotonic()
                self._data.move_to_end(key)
            else:
                self._data[key] = _Entry(value=value)
                while len(self._data) > self._max_size:
                    self._data.popitem(last=False)
                    self._evicted_lru += 1

    def __delitem__(self, key: str) -> None:
        with self._lock:
            del self._data[key]

    def __len__(self) -> int:
        with self._lock:
            return len(self._data)

    def get(self, key: str, default=None):
        with self._lock:
            entry = self._data.get(key)
            if entry is None:
                return default
            entry.last_access = time.monotonic()
            self._data.move_to_end(key)
            return entry.value

    def pop(self, key: str, *default):
        with self._lock:
            entry = self._data.pop(key, *default)
            if isinstance(entry, _Entry):
                return entry.value
            return entry

    def keys(self):
        with self._lock:
            return list(self._data.keys())

    def sweep_expired(self) -> int:
        """清除所有过期条目，返回清除数量。"""
        now = time.monotonic()
        evicted = 0
        with self._lock:
            expired_keys = []
            for key, entry in self._data.items():
                if (now - entry.last_access) > self._ttl:
                    expired_keys.append(key)
                else:
                    break
            for key in expired_keys:
                del self._data[key]
                evicted += 1
            self._evicted_ttl += evicted
        return evicted

    def stats(self) -> CacheStats:
        with self._lock:
            return CacheStats(
                size=len(self._data),
                max_size=self._max_size,
                ttl_seconds=self._ttl,
                evicted_ttl=self._evicted_ttl,
                evicted_lru=self._evicted_lru,
            )
