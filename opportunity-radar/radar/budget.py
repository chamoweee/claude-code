"""The spend ceiling.

The hard rule is "stop all runs if monthly API spend reaches $30 AUD". That is
enforced here as a *pre-flight* check, not a line in the report: every call to
the Claude API must go through :meth:`BudgetGuard.check` first, and the guard
raises :class:`BudgetExhausted` rather than letting the call happen.

Costs are computed from the usage the API reports back, priced from
``config/settings.toml``. USD is converted at a configured rate that the macro
fetcher refreshes weekly (Stage 2); the rate used is stored on each row so an
old report can always be re-derived.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from typing import Any

from .config import ModelPricing, Settings
from .db import utc_now_iso


class BudgetExhausted(RuntimeError):
    """Raised instead of spending past the monthly cap."""

    def __init__(self, spent_aud: float, cap_aud: float, month: str):
        self.spent_aud = spent_aud
        self.cap_aud = cap_aud
        self.month = month
        super().__init__(
            f"Monthly API budget reached: ${spent_aud:.2f} of ${cap_aud:.2f} AUD "
            f"spent in {month}. Runs are halted until the 1st."
        )


@dataclass(frozen=True)
class Usage:
    """Token counts for one API call, in the shape the Anthropic SDK reports."""

    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_tokens: int = 0
    cache_write_tokens: int = 0
    web_searches: int = 0

    @classmethod
    def from_response(cls, usage: Any) -> "Usage":
        """Build from a ``response.usage`` object (or any object with those attrs)."""
        server_tools = getattr(usage, "server_tool_use", None)
        return cls(
            input_tokens=int(getattr(usage, "input_tokens", 0) or 0),
            output_tokens=int(getattr(usage, "output_tokens", 0) or 0),
            cache_read_tokens=int(getattr(usage, "cache_read_input_tokens", 0) or 0),
            cache_write_tokens=int(getattr(usage, "cache_creation_input_tokens", 0) or 0),
            web_searches=int(getattr(server_tools, "web_search_requests", 0) or 0),
        )

    def __add__(self, other: "Usage") -> "Usage":
        return Usage(
            self.input_tokens + other.input_tokens,
            self.output_tokens + other.output_tokens,
            self.cache_read_tokens + other.cache_read_tokens,
            self.cache_write_tokens + other.cache_write_tokens,
            self.web_searches + other.web_searches,
        )


def cost_usd(usage: Usage, pricing: ModelPricing) -> float:
    """Price one call in USD. Kept separate from AUD so the FX rate is visible."""
    per_token = (
        usage.input_tokens * pricing.input_per_mtok_usd
        + usage.output_tokens * pricing.output_per_mtok_usd
        + usage.cache_read_tokens * pricing.cache_read_per_mtok_usd
        + usage.cache_write_tokens * pricing.cache_write_per_mtok_usd
    ) / 1_000_000
    searches = usage.web_searches * pricing.web_search_per_1k_usd / 1_000
    return per_token + searches


def month_key(sydney_date: str) -> str:
    """``2026-09-21`` -> ``2026-09``. Months are Sydney months, like the cap."""
    return sydney_date[:7]


def month_to_date_aud(conn: sqlite3.Connection, month: str) -> float:
    row = conn.execute(
        "SELECT COALESCE(SUM(cost_aud), 0.0) AS total FROM spend WHERE month = ?", (month,)
    ).fetchone()
    return float(row["total"])


@dataclass
class BudgetStatus:
    month: str
    spent_aud: float
    cap_aud: float
    reserve_aud: float

    @property
    def remaining_aud(self) -> float:
        return max(0.0, self.cap_aud - self.spent_aud)

    @property
    def fraction_used(self) -> float:
        return self.spent_aud / self.cap_aud if self.cap_aud else 1.0

    @property
    def exhausted(self) -> bool:
        return self.spent_aud >= self.cap_aud


class BudgetGuard:
    """Pre-flight gate plus ledger writer for one run."""

    def __init__(self, conn: sqlite3.Connection, settings: Settings, sydney_date: str,
                 run_id: int | None = None):
        self.conn = conn
        self.settings = settings
        self.month = month_key(sydney_date)
        self.run_id = run_id
        self.pricing = settings.pricing_for(settings.research.model)

    # -- reading ------------------------------------------------------------

    def status(self) -> BudgetStatus:
        return BudgetStatus(
            month=self.month,
            spent_aud=month_to_date_aud(self.conn, self.month),
            cap_aud=self.settings.budget.monthly_cap_aud,
            reserve_aud=self.settings.budget.reserve_aud,
        )

    def warning(self) -> str | None:
        """Text for the report when spend is close to the cap, else ``None``."""
        st = self.status()
        if st.exhausted:
            return f"Budget exhausted: ${st.spent_aud:.2f} of ${st.cap_aud:.2f} AUD used."
        if st.fraction_used >= self.settings.budget.warn_at_fraction:
            return (
                f"Budget {st.fraction_used * 100:.0f}% used "
                f"(${st.spent_aud:.2f} of ${st.cap_aud:.2f} AUD). "
                f"Runs halt automatically at the cap."
            )
        return None

    # -- gating -------------------------------------------------------------

    def check(self, estimated_aud: float = 0.0) -> BudgetStatus:
        """Raise :class:`BudgetExhausted` if this call would breach the cap.

        ``estimated_aud`` should be a generous upper bound for the call about to
        be made. A reserve is held back so that the error-notice email and the
        final report render can still be produced after a halt.
        """
        st = self.status()
        ceiling = st.cap_aud - self.settings.budget.reserve_aud
        if st.spent_aud >= st.cap_aud or st.spent_aud + estimated_aud > ceiling:
            raise BudgetExhausted(st.spent_aud, st.cap_aud, self.month)
        return st

    # -- writing ------------------------------------------------------------

    def record(self, usage: Usage, purpose: str = "",
               model: str | None = None) -> float:
        """Write a ledger row for a completed call. Returns its AUD cost."""
        pricing = (self.settings.pricing_for(model) if model else self.pricing)
        usd = cost_usd(usage, pricing)
        aud = usd * self.settings.budget.usd_to_aud
        self.conn.execute(
            "INSERT INTO spend (run_id, at, month, model, purpose, input_tokens, "
            "output_tokens, cache_read_tokens, cache_write_tokens, web_searches, "
            "cost_usd, cost_aud) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (self.run_id, utc_now_iso(), self.month, pricing.model, purpose,
             usage.input_tokens, usage.output_tokens, usage.cache_read_tokens,
             usage.cache_write_tokens, usage.web_searches, usd, aud),
        )
        self.conn.commit()
        return aud

    def month_breakdown(self) -> list[sqlite3.Row]:
        """Per-purpose spend for the month, for the report's spend section."""
        return list(self.conn.execute(
            "SELECT purpose, COUNT(*) AS calls, SUM(web_searches) AS searches, "
            "SUM(cost_aud) AS aud FROM spend WHERE month = ? "
            "GROUP BY purpose ORDER BY aud DESC",
            (self.month,),
        ))
