"""Which sectors a market has, and where this vendor keeps them.

A sector board is the anatomy of an index: eleven bars for the S&P 500, seventeen for the Nifty,
seventeen again for the Topix. Every market publishes its own set under its own names, and none of
them is a translation of another — India has an FMCG sector and a PSU Bank sector, and no GICS
bucket corresponds to either.

Hard-coding the American set was the original sin here. It put an eleven-sector board of US equity
funds under a Bitcoin summary, and it would have put the same board under a Nifty summary, which
is worse: the reader has no way to tell that the bars describe a different continent from the
instrument above them.

Two things differ between markets and both are recorded rather than inferred.

**Where the moves come from.** The American sectors are SPDR funds with years of daily history, so
their session move is read from bars like anything else. The Indian sector indices have a live
quote and no history at all — every window returns one row — so their move comes from the quote,
and only for the session that quote describes. A board built from quotes cannot answer a question
about last Tuesday, and saying so is better than answering it wrongly.

**Whether contribution can be computed.** Ranking sectors by how far each moved is one question;
ranking them by how much each carried the index is a better one, and it needs weights. Only the
American board has them, because SPY publishes sector weights in the same buckets its sector funds
are drawn on. Yahoo publishes no weights for the Nifty sector indices, and the one surface that
does — a US-listed MSCI India fund — reports GICS buckets that do not map onto NSE's categories.
So the Indian board ranks by move, the contribution reading hides itself, and nothing here invents
a mapping to fill the gap.
"""

from collections.abc import Mapping
from types import MappingProxyType
from typing import Final, NamedTuple


class Board(NamedTuple):
    """One market's sectors, how their moves are read, and whether they can be weighted."""

    market: str
    sectors: Mapping[str, str]
    proxies: Mapping[str, str]
    weights_from: str | None = None
    weight_keys: Mapping[str, str] = MappingProxyType({})
    from_history: bool = True


US: Final = "US"
INDIA: Final = "IN"
JAPAN: Final = "JP"

_US_SECTORS: Final[Mapping[str, str]] = MappingProxyType(
    {
        "XLB": "Materials",
        "XLC": "Communication Services",
        "XLE": "Energy",
        "XLF": "Financials",
        "XLI": "Industrials",
        "XLK": "Technology",
        "XLP": "Consumer Staples",
        "XLRE": "Real Estate",
        "XLU": "Utilities",
        "XLV": "Health Care",
        "XLY": "Consumer Discretionary",
    }
)

_US_PROXIES: Final[Mapping[str, str]] = MappingProxyType(
    {
        "Basic Materials": "XLB",
        "Communication Services": "XLC",
        "Consumer Cyclical": "XLY",
        "Consumer Defensive": "XLP",
        "Energy": "XLE",
        "Financial Services": "XLF",
        "Healthcare": "XLV",
        "Industrials": "XLI",
        "Real Estate": "XLRE",
        "Technology": "XLK",
        "Utilities": "XLU",
    }
)

_US_WEIGHT_KEYS: Final[Mapping[str, str]] = MappingProxyType(
    {
        "basic_materials": "XLB",
        "communication_services": "XLC",
        "consumer_cyclical": "XLY",
        "consumer_defensive": "XLP",
        "energy": "XLE",
        "financial_services": "XLF",
        "healthcare": "XLV",
        "industrials": "XLI",
        "realestate": "XLRE",
        "technology": "XLK",
        "utilities": "XLU",
    }
)

_INDIA_SECTORS: Final[Mapping[str, str]] = MappingProxyType(
    {
        "^NSEBANK": "Bank",
        "^CNXAUTO": "Auto",
        "^CNXCMDT": "Commodities",
        "^CNXCONSUM": "Consumption",
        "^CNXENERGY": "Energy",
        "^CNXFIN": "Financial Services",
        "^CNXFMCG": "FMCG",
        "^CNXINFRA": "Infrastructure",
        "^CNXIT": "IT",
        "^CNXMEDIA": "Media",
        "^CNXMETAL": "Metal",
        "^CNXPHARMA": "Pharma",
        "^CNXPSUBANK": "PSU Bank",
        "^CNXREALTY": "Realty",
    }
)

_INDIA_PROXIES: Final[Mapping[str, str]] = MappingProxyType(
    {
        "Basic Materials": "^CNXMETAL",
        "Consumer Cyclical": "^CNXCONSUM",
        "Consumer Defensive": "^CNXFMCG",
        "Energy": "^CNXENERGY",
        "Financial Services": "^CNXFIN",
        "Healthcare": "^CNXPHARMA",
        "Industrials": "^CNXINFRA",
        "Real Estate": "^CNXREALTY",
        "Technology": "^CNXIT",
    }
)

_JAPAN_SECTORS: Final[Mapping[str, str]] = MappingProxyType(
    {
        "1617.T": "Foods",
        "1618.T": "Energy Resources",
        "1619.T": "Construction & Materials",
        "1620.T": "Raw Materials & Chemicals",
        "1621.T": "Pharmaceutical",
        "1622.T": "Automobiles & Transport Equipment",
        "1623.T": "Steel & Nonferrous",
        "1624.T": "Machinery",
        "1625.T": "Electric & Precision Instruments",
        "1626.T": "IT & Services",
        "1627.T": "Electric Power & Gas",
        "1628.T": "Transportation & Logistics",
        "1629.T": "Commercial & Wholesale Trade",
        "1630.T": "Retail Trade",
        "1631.T": "Banks",
        "1632.T": "Financials excluding Banks",
        "1633.T": "Real Estate",
    }
)

_JAPAN_PROXIES: Final[Mapping[str, str]] = MappingProxyType(
    {
        "Basic Materials": "1620.T",
        "Consumer Cyclical": "1630.T",
        "Consumer Defensive": "1617.T",
        "Energy": "1618.T",
        "Financial Services": "1632.T",
        "Healthcare": "1621.T",
        "Industrials": "1624.T",
        "Real Estate": "1633.T",
        "Technology": "1626.T",
        "Utilities": "1627.T",
    }
)

BOARDS: Final[Mapping[str, Board]] = MappingProxyType(
    {
        US: Board(
            market="the US market",
            sectors=_US_SECTORS,
            proxies=_US_PROXIES,
            weights_from="SPY",
            weight_keys=_US_WEIGHT_KEYS,
        ),
        INDIA: Board(market="the Indian market", sectors=_INDIA_SECTORS, proxies=_INDIA_PROXIES, from_history=False),
        JAPAN: Board(market="the Japanese market", sectors=_JAPAN_SECTORS, proxies=_JAPAN_PROXIES),
    }
)

EXCHANGES: Final[Mapping[str, str]] = MappingProxyType(
    {
        "ASE": US,
        "BTS": US,
        "NCM": US,
        "NGM": US,
        "NMS": US,
        "NYQ": US,
        "NYS": US,
        "PCX": US,
        "PNK": US,
        "SNP": US,
        "BSE": INDIA,
        "NSI": INDIA,
        "JPX": JAPAN,
        "OSA": JAPAN,
        "TYO": JAPAN,
    }
)

DEFAULT_MARKET: Final = US


def of(exchange: str | None) -> Board:
    """The board for an exchange, falling back to the American one.

    A currency pair and a commodity future report exchanges of their own and belong to no equity
    market at all. They fall back like anything unrecognised, and the panel gate above decides
    whether a sector board means anything for them — which for those two it does not.
    """
    return BOARDS[EXCHANGES.get((exchange or "").upper(), DEFAULT_MARKET)]
