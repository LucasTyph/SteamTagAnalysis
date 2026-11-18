"""Run control: graceful Ctrl+C, time budgets and request caps.

First Ctrl+C asks the run to stop after the current request is saved.
A second Ctrl+C aborts immediately (still safe: jobs are transactional).
"""

from __future__ import annotations

import re
import signal
import time
from contextlib import contextmanager

_UNITS = {"s": 1, "m": 60, "h": 3600, "d": 86400}


def parse_duration(text: str) -> float:
    """'90s', '30m', '1h30m', '2h' → seconds."""
    text = text.strip().lower()
    parts = re.findall(r"(\d+(?:\.\d+)?)([smhd])", text)
    if not parts or "".join(n + u for n, u in parts) != text:
        raise ValueError(f"Invalid duration {text!r}; use e.g. 90s, 30m, 1h30m")
    return sum(float(n) * _UNITS[u] for n, u in parts)


class StopReason:
    INTERRUPT = "interrupted (Ctrl+C)"
    BUDGET = "time budget reached"
    MAX_REQUESTS = "request limit reached"


class RunControl:
    def __init__(self, budget_s: float | None = None, max_requests: int | None = None):
        self.deadline = time.monotonic() + budget_s if budget_s else None
        self.max_requests = max_requests
        self.requests = 0
        self.interrupted = False

    def count_request(self) -> None:
        self.requests += 1

    @property
    def stop_reason(self) -> str | None:
        if self.interrupted:
            return StopReason.INTERRUPT
        if self.deadline is not None and time.monotonic() >= self.deadline:
            return StopReason.BUDGET
        if self.max_requests is not None and self.requests >= self.max_requests:
            return StopReason.MAX_REQUESTS
        return None

    @property
    def should_stop(self) -> bool:
        return self.stop_reason is not None

    def sleep(self, seconds: float) -> None:
        """Sleep in short slices so Ctrl+C and budgets take effect quickly."""
        end = time.monotonic() + seconds
        while not self.should_stop:
            remaining = end - time.monotonic()
            if remaining <= 0:
                return
            time.sleep(min(0.2, remaining))

    @contextmanager
    def handle_sigint(self):
        def handler(signum, frame):
            if self.interrupted:
                raise KeyboardInterrupt
            self.interrupted = True

        # SIGTERM too: CI runners (GitHub Actions cancel) send it before killing the job.
        signals = [signal.SIGINT, signal.SIGTERM]
        previous = {s: signal.signal(s, handler) for s in signals}
        try:
            yield self
        finally:
            for s, prev in previous.items():
                signal.signal(s, prev)
