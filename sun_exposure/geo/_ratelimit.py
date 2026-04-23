"""
Token-bucket rate limiter for external API calls.

Usage:
    limiter = TokenBucketLimiter(rate=1.0)   # 1 request per second
    limiter.acquire()                         # blocks until a token is available
    # ... make request ...
"""

import threading
import time


class TokenBucketLimiter:
    """
    Thread-safe token-bucket rate limiter.

    Parameters
    ----------
    rate    : maximum requests per second
    burst   : maximum burst size (tokens the bucket can hold); defaults to rate
    """

    def __init__(self, rate: float, burst: float | None = None):
        self._rate = rate
        self._capacity = burst if burst is not None else rate
        self._tokens = self._capacity
        self._last = time.monotonic()
        self._lock = threading.Lock()

    def acquire(self) -> None:
        """Block until a token is available, then consume one."""
        while True:
            with self._lock:
                now = time.monotonic()
                elapsed = now - self._last
                self._tokens = min(self._capacity, self._tokens + elapsed * self._rate)
                self._last = now
                if self._tokens >= 1.0:
                    self._tokens -= 1.0
                    return
                wait = (1.0 - self._tokens) / self._rate
            time.sleep(wait)
