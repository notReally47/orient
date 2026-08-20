"""Everything the tools reach for, passed in rather than imported.

Storage and market data are named by port, so no tool knows which vendor answers it. The bar
table is absent on purpose: it is reached through the price cache that satisfies `Prices`, so no
tool knows a cache exists either.

The write path is here too. A summary is finished when `save_summary` accepts it, so the tool
layer needs the repositories, the skill tree and a model for claim extraction. That is what makes
the grounding check something a caller cannot skip rather than something the orchestrator
remembers to run.
"""

from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, date, datetime
from uuid import UUID, uuid4

from orient.llm.chat import ChatModel
from orient.llm.embeddings import EmbeddingClient
from orient.llm.judge import JudgeClient
from orient.llm.research import Researcher
from orient.providers.protocols import Calendars, Discovery, Earnings, MarketData, Prices, Reference
from orient.skills.loader import Skills
from orient.store.claims import ClaimRepository
from orient.store.instruments import InstrumentRepository
from orient.store.sessions import SessionRepository
from orient.store.summaries import SummaryRepository


def today() -> date:
    return datetime.now(tz=UTC).date()


@dataclass(frozen=True, slots=True)
class ToolDeps:
    prices: Prices
    discovery: Discovery
    reference: Reference
    earnings: Earnings
    market: MarketData
    calendars: Calendars
    research: Researcher
    skills: Skills
    chat: ChatModel
    fast_model: str
    judge: JudgeClient
    embeddings: EmbeddingClient
    instruments: InstrumentRepository
    sessions: SessionRepository
    summaries: SummaryRepository
    claims: ClaimRepository
    clock: Callable[[], date] = today
    new_id: Callable[[], UUID] = uuid4
