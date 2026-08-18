"""Client-side pacing for model calls.

Gemini's free tier meters per Google Cloud project rather than per key, so every call this
process makes competes for one allowance. Spacing them evenly turns what would be a burst of
429s partway through a run into a run that merely takes longer.
"""

import asyncio
from collections.abc import Awaitable, Callable
from time import monotonic
from typing import Final

SECONDS_PER_MINUTE: Final = 60.0

Clock = Callable[[], float]
Sleep = Callable[[float], Awaitable[None]]


class RateLimiter:
    """At most `per_minute` calls, spaced evenly rather than allowed to burst and then stall.

    The clock and the sleep are injected so a test drives a whole minute of traffic without
    waiting one, and so the pacing itself is what gets asserted rather than the elapsed time.
    """

    def __init__(self, per_minute: int, clock: Clock = monotonic, sleep: Sleep = asyncio.sleep) -> None:
        self._interval: Final = SECONDS_PER_MINUTE / per_minute
        self._clock: Final = clock
        self._sleep: Final = sleep
        self._lock: Final = asyncio.Lock()
        self._ready_at: float = 0.0

    async def acquire(self) -> None:
        """Returns once the caller may make its request. Held across the wait, so callers queue."""
        async with self._lock:
            now = self._clock()
            delay = self._ready_at - now
            if delay > 0:
                await self._sleep(delay)
            self._ready_at = max(now, self._ready_at) + self._interval
