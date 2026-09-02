from __future__ import annotations

import time
from dataclasses import dataclass, field


class RateLimitExceeded(Exception):
    pass


@dataclass
class _Bucket:
    window_start: float
    count: int = 0


@dataclass
class ExportRateLimiter:
    max_exports_per_hour: int = 20
    _buckets: dict[str, _Bucket] = field(default_factory=dict)

    def check(self, user_id: str) -> None:
        now = time.monotonic()
        bucket = self._buckets.get(user_id)
        if bucket is None:
            bucket = _Bucket(window_start=now)
            self._buckets[user_id] = bucket
        if now - bucket.window_start >= 3600:
            bucket.window_start = now
            bucket.count = 0
        if bucket.count >= self.max_exports_per_hour:
            raise RateLimitExceeded(
                f"Export rate limit exceeded ({self.max_exports_per_hour} per hour)."
            )
        bucket.count += 1
