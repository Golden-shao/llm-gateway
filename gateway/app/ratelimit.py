"""进程内令牌桶限流（单实例）。多副本场景下由 K8s HPA 分摊流量，
如需跨实例精确限流，可替换为 Redis 实现（留作扩展点）。"""
import threading
import time
from collections import defaultdict


class TokenBucket:
    def __init__(self, rpm: int) -> None:
        self.rate = max(1, rpm)
        self.capacity = max(1, rpm)
        self.tokens = float(self.capacity)
        self.updated = time.monotonic()
        self.lock = threading.Lock()

    def allow(self) -> bool:
        with self.lock:
            now = time.monotonic()
            self.tokens = min(self.capacity, self.tokens + (now - self.updated) * self.rate / 60.0)
            self.updated = now
            if self.tokens >= 1.0:
                self.tokens -= 1.0
                return True
            return False


class RateLimiter:
    def __init__(self, rpm: int) -> None:
        self.rpm = rpm
        self._buckets: dict[str, TokenBucket] = {}
        self._lock = threading.Lock()

    def _bucket(self, key: str) -> TokenBucket:
        with self._lock:
            if key not in self._buckets:
                self._buckets[key] = TokenBucket(self.rpm)
            return self._buckets[key]

    def allow(self, key: str) -> bool:
        return self._bucket(key).allow()
