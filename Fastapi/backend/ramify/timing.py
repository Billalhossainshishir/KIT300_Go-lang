"""Stage timing and the clock.

Latencies are integer microseconds wherever they are signed; the millisecond
float is display-only. `RAMIFY_DEMO_DETERMINISTIC=1` pins the clock and every
measurement for parity testing — a live demo signs live values.
"""

import time
from contextlib import contextmanager
from datetime import datetime, timezone

from ramify.data import seed

PINNED_CLOCK = datetime(2026, 7, 24, 9, 30, 0, tzinfo=timezone.utc)
PINNED_LATENCY_US = 100


def now() -> datetime:
    if seed.deterministic_mode():
        return PINNED_CLOCK
    return datetime.now(timezone.utc)


class Stopwatch:
    """Collects per-stage latencies in integer microseconds."""

    def __init__(self) -> None:
        self.latencies_us: dict[str, int] = {}

    @contextmanager
    def stage(self, name: str):
        start = time.perf_counter_ns()
        try:
            yield
        finally:
            self.record(name, (time.perf_counter_ns() - start) // 1000)

    def record(self, name: str, microseconds: int) -> None:
        self.latencies_us[name] = (
            PINNED_LATENCY_US if seed.deterministic_mode() else int(microseconds)
        )

    def total(self) -> int:
        if seed.deterministic_mode():
            return PINNED_LATENCY_US * max(len(self.latencies_us), 1)
        return sum(self.latencies_us.values())


def to_display_ms(microseconds: int) -> float:
    """Display only — never write this into a receipt."""
    return round(microseconds / 1000, 3)
