import asyncio
import time
from collections import defaultdict, deque

from livemap.api.errors import APIError


class RequestRateLimiter:
    def __init__(self, limit: int, window_seconds: int, code: str, message: str) -> None:
        self.limit = limit
        self.window_seconds = window_seconds
        self.code = code
        self.message = message
        self._requests: dict[str, deque[float]] = defaultdict(deque)
        self._lock = asyncio.Lock()

    async def check(self, client: str) -> None:
        now = time.monotonic()
        async with self._lock:
            if len(self._requests) > 10_000:
                self._requests = defaultdict(
                    deque,
                    {
                        key: values
                        for key, values in self._requests.items()
                        if values and values[-1] > now - self.window_seconds
                    },
                )
            values = self._requests[client]
            while values and values[0] <= now - self.window_seconds:
                values.popleft()
            if len(values) >= self.limit:
                raise APIError(self.code, self.message, 429)
            values.append(now)


search_limiter = RequestRateLimiter(30, 60, "rate_limited", "Search request limit exceeded")
login_limiter = RequestRateLimiter(10, 60, "rate_limited", "Login request limit exceeded")
