"""The limiter is what stops a run throwing 429s halfway through, so the pacing itself is asserted.

Time is injected, so a full minute of traffic is driven without waiting one.
"""

from typing import Final

from orient.llm.limiter import SECONDS_PER_MINUTE, RateLimiter

BUDGET: Final = 15
SPACING: Final = SECONDS_PER_MINUTE / BUDGET


class _FakeClock:
    def __init__(self) -> None:
        self.now: float = 0.0
        self.slept: list[float] = []

    def read(self) -> float:
        return self.now

    async def sleep(self, seconds: float) -> None:
        self.slept.append(seconds)
        self.now += seconds


def _limiter(clock: _FakeClock) -> RateLimiter:
    return RateLimiter(per_minute=BUDGET, clock=clock.read, sleep=clock.sleep)


async def test_calls_are_spaced_evenly_rather_than_bursting() -> None:
    clock: Final = _FakeClock()
    limiter: Final = _limiter(clock)

    for _ in range(4):
        await limiter.acquire()

    assert clock.slept == [SPACING, SPACING, SPACING]


async def test_the_first_call_of_a_run_is_not_delayed() -> None:
    clock: Final = _FakeClock()
    await _limiter(clock).acquire()
    assert clock.slept == []


async def test_an_idle_gap_is_credited_rather_than_slept_through() -> None:
    """Waiting on the model or on Yahoo already spends the interval; charging for it twice is wrong."""
    clock: Final = _FakeClock()
    limiter: Final = _limiter(clock)

    await limiter.acquire()
    clock.now += SECONDS_PER_MINUTE
    await limiter.acquire()

    assert clock.slept == []


async def test_the_budget_holds_across_a_minute() -> None:
    clock: Final = _FakeClock()
    limiter: Final = _limiter(clock)

    for _ in range(BUDGET):
        await limiter.acquire()
    assert clock.now < SECONDS_PER_MINUTE

    await limiter.acquire()
    assert clock.now >= SECONDS_PER_MINUTE
