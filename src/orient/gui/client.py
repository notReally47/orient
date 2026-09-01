"""The orchestrator, as the front end sees it.

Everything the page needs comes from one service over plain HTTP. The tool server and the database
sit behind it, which is what keeps the browser unable to reach a tool that writes.

Responses are validated into models rather than read as dictionaries, so a field the service stops
sending fails here with a name attached instead of surfacing as a blank tile three screens later.

A run arrives as Server-Sent Events. `stream` yields them as they land and takes a stop flag the
caller can set from another thread: setting it closes the response, the orchestrator sees the
disconnected client, and the run ends where it stands rather than finishing unwatched.
"""

import json
import threading
from collections.abc import Iterator, Mapping
from datetime import date
from typing import Final
from uuid import UUID

import httpx
from pydantic import BaseModel, ConfigDict, TypeAdapter, ValidationError

from orient.domain.models import Bar, ReadingLevel, Summary
from orient.orchestrator.events import Event

READ_TIMEOUT: Final = 10.0
RUN_TIMEOUT: Final = 1800.0
DATA_PREFIX: Final = "data:"
DEFAULT_MATCHES: Final = 8
DEFAULT_LISTED: Final = 12
DEFAULT_SESSIONS: Final = 60
DEFAULT_WINDOW: Final = 180

Params = Mapping[str, str | int]


class Wire(BaseModel):
    """A response as this side reads it: frozen, and tolerant of fields it has no use for.

    A client that refuses a payload for carrying more than it asked for turns every addition
    to the service into an outage here, so unknown fields are dropped rather than rejected."""

    model_config = ConfigDict(frozen=True, extra="ignore")


class Match(Wire):
    """One instrument a search turned up, in the shape the picker lists it.

    The vendor names the kind of instrument `quote_type`, and a row can arrive without a
    name or a price, so every field but the ticker is optional and the picker falls back to
    the ticker rather than rendering an unlabelled button."""

    symbol: str
    name: str | None = None
    quote_type: str | None = None
    price: float | None = None
    change_percent: float | None = None

    @property
    def title(self) -> str:
        return self.name or self.symbol

    @property
    def kind(self) -> str:
        return (self.quote_type or "instrument").lower()

    @property
    def move(self) -> str:
        """The last price and the day, when the search knew them."""
        if self.price is None:
            return ""
        if self.change_percent is None:
            return f"{self.price:,.2f}"
        return f"{self.price:,.2f} ({self.change_percent:+.2f}%)"


class StoredSummary(Wire):
    """A row in the revisit list: enough to recognise it, not enough to render it."""

    id: UUID
    symbol: str
    session_date: date
    level: ReadingLevel
    thesis: str


class Shelf(Wire):
    """One screen of stored summaries, and how many the filters matched in all."""

    total: int = 0
    entries: tuple[StoredSummary, ...] = ()


class Written(Wire):
    """One instrument something has been written about, and how much of it there is."""

    symbol: str
    count: int
    latest: date


class Health(Wire):
    """What the service says about itself, including the ceiling a run is bounded by."""

    status: str = "unknown"
    tools: int = 0
    max_turns: int = 0


class _Matches(Wire):
    matches: tuple[Match, ...] = ()


class _History(Wire):
    bars: tuple[Bar, ...] = ()


_HEALTH: Final = TypeAdapter(Health)
_MATCHES: Final = TypeAdapter(_Matches)
_HISTORY: Final = TypeAdapter(_History)
_SHELF: Final = TypeAdapter(Shelf)
_WRITTEN: Final = TypeAdapter(tuple[Written, ...])
_DAYS: Final = TypeAdapter(tuple[date, ...])
_SUMMARY: Final = TypeAdapter(Summary)
_EVENT: Final[TypeAdapter[Event]] = TypeAdapter(Event)


class OrchestratorError(RuntimeError):
    """The service answered with something the page cannot use, carrying what it said."""


def connect(base_url: str) -> httpx.Client:
    """The transport the page holds for its session, long enough for a run to stream over."""
    return httpx.Client(base_url=base_url.rstrip("/"), timeout=httpx.Timeout(READ_TIMEOUT))


class Orchestrator:
    """One client per session. Reads are short; a run holds its connection open for the duration."""

    def __init__(self, http: httpx.Client) -> None:
        self._http: Final = http

    def _read(self, path: str, params: Params | None = None) -> bytes:
        try:
            response = self._http.get(path, params=dict(params or {}))
        except httpx.HTTPError as exc:
            message = f"{type(exc).__name__}: {exc}"
            raise OrchestratorError(message) from exc
        if not response.is_success:
            message = f"HTTP {response.status_code}: {response.text[:200]}"
            raise OrchestratorError(message)
        return response.content

    def health(self) -> Health:
        """Asked once a session, for the turn ceiling a progress bar fills against."""
        try:
            return _HEALTH.validate_json(self._read("/health"))
        except (OrchestratorError, ValidationError):
            return Health()

    def search(self, query: str, limit: int = DEFAULT_MATCHES, asset_class: str | None = None) -> tuple[Match, ...]:
        """Narrowed to one kind when the reader has already said which, because a phrase matches
        across several: "S&P 500" on its own answers with the futures before the index."""
        asked: Final[dict[str, str | int]] = {"q": query, "limit": limit}
        if asset_class:
            asked["asset_class"] = asset_class
        body: Final = self._read("/instruments", asked)
        try:
            return _MATCHES.validate_json(body).matches
        except ValidationError as exc:
            message = f"the search answered in an unexpected shape: {exc.error_count()} problems"
            raise OrchestratorError(message) from exc

    def bars(self, symbol: str, session_date: date, days: int = DEFAULT_WINDOW) -> tuple[Bar, ...]:
        """The whole session behind each day, oldest first, for a chart that needs more than a close."""
        body: Final = self._read(f"/prices/{symbol}", {"session_date": session_date.isoformat(), "days": days})
        try:
            history = _HISTORY.validate_json(body)
        except ValidationError:
            return ()
        return tuple(sorted(history.bars, key=lambda bar: bar.session_date))

    def closes(self, symbol: str, session_date: date, days: int = DEFAULT_WINDOW) -> tuple[tuple[date, float], ...]:
        """The series behind the line chart, oldest first."""
        return tuple((bar.session_date, bar.close) for bar in self.bars(symbol, session_date, days))

    def sessions(self, symbol: str, limit: int = DEFAULT_SESSIONS) -> tuple[date, ...]:
        """The days this instrument traded, newest first. An empty answer is a live result: an
        instrument with nothing recent on file has no session to summarise yet."""
        try:
            return _DAYS.validate_json(self._read(f"/sessions/{symbol}", {"limit": limit}))
        except ValidationError as exc:
            message = "the trading calendar answered in an unexpected shape"
            raise OrchestratorError(message) from exc

    def stored(
        self,
        symbol: str | None = None,
        level: ReadingLevel | None = None,
        limit: int = DEFAULT_LISTED,
        offset: int = 0,
    ) -> Shelf:
        """One screen of what has been written, with the size of the whole behind it.

        The filters and the page go to the service rather than being applied to everything it
        sent, because an archive grows and a screen does not.
        """
        asked: Final[dict[str, str | int]] = {"limit": limit, "offset": offset}
        if symbol:
            asked["symbol"] = symbol
        if level:
            asked["level"] = level
        try:
            return _SHELF.validate_json(self._read("/summaries", asked))
        except ValidationError as exc:
            message = "the stored summaries answered in an unexpected shape"
            raise OrchestratorError(message) from exc

    def written(self) -> tuple[Written, ...]:
        """Which instruments have something on file, most written about first."""
        try:
            return _WRITTEN.validate_json(self._read("/written"))
        except ValidationError as exc:
            message = "the written instruments answered in an unexpected shape"
            raise OrchestratorError(message) from exc

    def summary(self, summary_id: UUID) -> Summary:
        try:
            return _SUMMARY.validate_json(self._read(f"/summaries/{summary_id}"))
        except ValidationError as exc:
            message = f"summary {summary_id} answered in an unexpected shape"
            raise OrchestratorError(message) from exc

    def stream(
        self,
        symbol: str,
        session_date: date,
        level: ReadingLevel,
        stop: threading.Event,
    ) -> Iterator[Event]:
        """A run, event by event. Returns early and quietly once `stop` is set."""
        body: Final = {"symbol": symbol, "session_date": session_date.isoformat(), "level": level}
        with self._http.stream("POST", "/runs", json=body, timeout=RUN_TIMEOUT) as response:
            if not response.is_success:
                response.read()
                message = f"HTTP {response.status_code}: {response.text[:200]}"
                raise OrchestratorError(message)
            for line in response.iter_lines():
                if stop.is_set():
                    return
                if not line.startswith(DATA_PREFIX):
                    continue
                try:
                    yield _EVENT.validate_json(line[len(DATA_PREFIX) :].strip())
                except (ValidationError, json.JSONDecodeError):
                    continue
