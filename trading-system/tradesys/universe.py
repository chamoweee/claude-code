"""Fixed, hand-picked symbol universe.

Deliberately NOT derived from "current ASX 200 membership" or any other
live index lookup — reconstructing history from today's index membership is
exactly how survivorship bias sneaks in (companies that got delisted or
dropped out don't show up, silently flattering backtests). The list below
is fixed at authoring time and should only be extended going forward, never
re-derived from hindsight.
"""

from __future__ import annotations

from tradesys.config import ASX_EXCHANGE, BENCHMARK_SYMBOLS, UNIVERSE_SYMBOLS


def all_symbols() -> list[str]:
    return [*BENCHMARK_SYMBOLS, *UNIVERSE_SYMBOLS]


def exchange_for(symbol: str) -> str:
    return ASX_EXCHANGE
