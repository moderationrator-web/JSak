"""Minimal client for Polymarket's public (unauthenticated) Data and Gamma APIs.

Standard library only. The transport is injectable so the whole pipeline can run
against a simulator in tests and in ``pmscout demo``.
"""

from __future__ import annotations

import json
import random
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Any, Callable, Dict, Mapping, Optional, Tuple

DATA_API = "https://data-api.polymarket.com"
GAMMA_API = "https://gamma-api.polymarket.com"

USER_AGENT = "pmscout/0.1 (+https://github.com/moderationrator-web/JSak)"

# transport(url, timeout) -> (status, headers, body)
Transport = Callable[[str, float], Tuple[int, Mapping[str, str], bytes]]


class ApiError(Exception):
    def __init__(self, status: int, url: str, body: str = ""):
        super().__init__(f"HTTP {status} for {url}: {body[:200]}")
        self.status = status
        self.url = url
        self.body = body


class RateLimiter:
    """Token bucket shared by all worker threads."""

    def __init__(self, rate: float, burst: Optional[float] = None):
        self.rate = max(rate, 0.01)
        self.capacity = burst if burst is not None else max(1.0, rate)
        self.tokens = self.capacity
        self.updated = time.monotonic()
        self.lock = threading.Lock()

    def acquire(self) -> None:
        while True:
            with self.lock:
                now = time.monotonic()
                self.tokens = min(self.capacity, self.tokens + (now - self.updated) * self.rate)
                self.updated = now
                if self.tokens >= 1:
                    self.tokens -= 1
                    return
                wait = (1 - self.tokens) / self.rate
            time.sleep(wait)


def urllib_transport(url: str, timeout: float) -> Tuple[int, Mapping[str, str], bytes]:
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.status, dict(resp.headers), resp.read()
    except urllib.error.HTTPError as e:
        return e.code, dict(e.headers or {}), e.read() or b""


class Client:
    def __init__(
        self,
        transport: Optional[Transport] = None,
        rate: float = 8.0,
        max_retries: int = 5,
        timeout: float = 30.0,
        sleep: Callable[[float], None] = time.sleep,
    ):
        self.transport = transport or urllib_transport
        self.limiter = RateLimiter(rate)
        self.max_retries = max_retries
        self.timeout = timeout
        self.sleep = sleep
        self.requests = 0
        self._count_lock = threading.Lock()

    @staticmethod
    def build_url(base: str, path: str, params: Optional[Mapping[str, Any]] = None) -> str:
        url = base.rstrip("/") + "/" + path.lstrip("/")
        if params:
            clean = []
            for k, v in params.items():
                if v is None:
                    continue
                if isinstance(v, bool):
                    v = "true" if v else "false"
                if isinstance(v, (list, tuple)):
                    clean.extend((k, str(x)) for x in v)
                else:
                    clean.append((k, str(v)))
            if clean:
                url += "?" + urllib.parse.urlencode(clean)
        return url

    def get(self, base: str, path: str, params: Optional[Mapping[str, Any]] = None) -> Any:
        url = self.build_url(base, path, params)
        last_err: Optional[Exception] = None
        for attempt in range(self.max_retries + 1):
            self.limiter.acquire()
            with self._count_lock:
                self.requests += 1
            try:
                status, headers, body = self.transport(url, self.timeout)
            except (urllib.error.URLError, TimeoutError, ConnectionError, OSError) as e:
                last_err = e
                self.sleep(self._backoff(attempt))
                continue
            if status == 200:
                try:
                    return json.loads(body.decode("utf-8") or "null")
                except ValueError as e:
                    raise ApiError(status, url, "invalid JSON") from e
            if status == 429 or status >= 500:
                last_err = ApiError(status, url, body.decode("utf-8", "replace"))
                self.sleep(self._retry_after(headers) or self._backoff(attempt))
                continue
            raise ApiError(status, url, body.decode("utf-8", "replace"))
        assert last_err is not None
        raise last_err

    def data(self, path: str, **params: Any) -> Any:
        return self.get(DATA_API, path, params)

    def gamma(self, path: str, **params: Any) -> Any:
        return self.get(GAMMA_API, path, params)

    @staticmethod
    def _backoff(attempt: int) -> float:
        return min(30.0, 1.5 * (2 ** attempt)) * (0.75 + random.random() * 0.5)

    @staticmethod
    def _retry_after(headers: Mapping[str, str]) -> Optional[float]:
        for k, v in headers.items():
            if k.lower() == "retry-after":
                try:
                    return min(60.0, max(0.0, float(v)))
                except ValueError:
                    return None
        return None
