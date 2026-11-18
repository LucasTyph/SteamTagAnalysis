"""HTTP client with per-host rate limiting, retries and backoff."""

from __future__ import annotations

import random
import time
from urllib.parse import urlsplit

import httpx

from pipeline.config import FETCH, FetchConfig, HostLimit
from pipeline.fetch.control import RunControl

RETRY_STATUS = {429, 500, 502, 503, 504}


class FetchError(Exception):
    def __init__(self, message: str, status_code: int | None = None):
        super().__init__(message)
        self.status_code = status_code


class Stopped(Exception):
    """Raised when the run was asked to stop while waiting to send a request."""


class SteamClient:
    def __init__(
        self,
        control: RunControl,
        config: FetchConfig = FETCH,
        transport: httpx.BaseTransport | None = None,
    ):
        self.control = control
        self.config = config
        self._last_request: dict[str, float] = {}
        self._http = httpx.Client(
            timeout=config.timeout,
            headers={"User-Agent": config.user_agent},
            follow_redirects=True,
            transport=transport,
        )

    def close(self) -> None:
        self._http.close()

    def __enter__(self) -> SteamClient:
        return self

    def __exit__(self, *exc) -> None:
        self.close()

    def _limit_for(self, host: str) -> HostLimit:
        return self.config.host_limits.get(host, self.config.default_limit)

    def _wait_turn(self, host: str) -> None:
        limit = self._limit_for(host)
        last = self._last_request.get(host)
        if last is not None:
            wait = limit.min_interval + random.uniform(0, limit.jitter) - (time.monotonic() - last)
            if wait > 0:
                self.control.sleep(wait)
        if self.control.should_stop:
            raise Stopped(self.control.stop_reason)

    def get_json(self, url: str, params: dict | None = None) -> tuple[int, object]:
        """GET → (status_code, parsed JSON). Retries transient failures."""
        host = urlsplit(url).hostname or ""
        last_error = "unknown error"
        for attempt in range(self.config.max_retries + 1):
            self._wait_turn(host)
            self._last_request[host] = time.monotonic()
            self.control.count_request()
            retry_after: float | None = None
            try:
                resp = self._http.get(url, params=params)
            except httpx.TransportError as e:
                last_error = f"{type(e).__name__}: {e}"
            else:
                if resp.status_code in RETRY_STATUS:
                    last_error = f"HTTP {resp.status_code}"
                    retry_after = _retry_after_seconds(resp)
                elif resp.status_code >= 400:
                    raise FetchError(f"HTTP {resp.status_code} for {url}", resp.status_code)
                else:
                    try:
                        return resp.status_code, resp.json()
                    except ValueError as e:
                        # Steam occasionally serves an HTML error page with 200.
                        last_error = f"invalid JSON: {e}"

            if attempt == self.config.max_retries:
                break
            delay = retry_after or min(
                self.config.backoff_max, self.config.backoff_base * (2**attempt)
            )
            self.control.sleep(delay + random.uniform(0, min(1.0, self.config.backoff_base)))
            if self.control.should_stop:
                raise Stopped(self.control.stop_reason)

        raise FetchError(f"Giving up on {url} after retries: {last_error}")


def _retry_after_seconds(resp: httpx.Response) -> float | None:
    value = resp.headers.get("Retry-After")
    if value is None:
        return None
    try:
        return max(0.0, float(value))
    except ValueError:
        return None
