"""The shapes research returns.

The model answers in JSON and these dataclasses are what a *validated* answer
becomes. Nothing here trusts the model: every field is copied across explicitly,
and anything unrecognised is dropped rather than carried into the report.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

THEME_STATUSES = ("NEW", "RISING", "STABLE", "FADING", "DEAD")
SOURCE_STRENGTHS = ("primary", "reputable_media", "weak")
SCORE_FIELDS = ("evidence_strength", "personal_fit", "capital_fit",
                "hours_fit", "speed_to_dollar", "risk")


@dataclass(frozen=True)
class Evidence:
    claim: str
    source_name: str
    source_url: str
    source_date: str
    source_strength: str
    number_value: str = ""

    @property
    def is_weak(self) -> bool:
        return self.source_strength == "weak"

    @property
    def is_primary(self) -> bool:
        return self.source_strength == "primary"


@dataclass(frozen=True)
class Conflict:
    """Two sources that disagree. The report shows both rather than picking one."""

    topic: str
    side_a: str
    side_b: str


@dataclass(frozen=True)
class ThemeUpdate:
    slug: str
    status: str
    reason: str
    evidence: tuple[Evidence, ...] = ()
    conflicts: tuple[Conflict, ...] = ()


@dataclass(frozen=True)
class SubScores:
    evidence_strength: int
    personal_fit: int
    capital_fit: int
    hours_fit: int
    speed_to_dollar: int
    risk: int
    reasons: dict[str, str] = field(default_factory=dict)

    def as_dict(self) -> dict[str, int]:
        return {name: getattr(self, name) for name in SCORE_FIELDS}


@dataclass(frozen=True)
class Opportunity:
    slug: str
    title: str
    summary: str
    who_earns: str
    platform_revenue_evidence: str
    individual_earnings_evidence: str
    startup_cost_aud_min: float | None
    startup_cost_aud_max: float | None
    time_to_first_dollar_days: int | None
    skills_required: str
    saturation: str
    red_flags: str
    au_eligibility: str
    evidence: tuple[Evidence, ...]
    scores: SubScores
    theme_slug: str = ""

    @property
    def has_individual_evidence(self) -> bool:
        """Whether anyone has shown an *individual* can earn, not just the platform."""
        return bool(self.individual_earnings_evidence.strip())

    @property
    def best_source_strength(self) -> str:
        for strength in SOURCE_STRENGTHS:
            if any(item.source_strength == strength for item in self.evidence):
                return strength
        return "weak"


@dataclass(frozen=True)
class Action:
    rank: int
    title: str
    why: str
    est_minutes: int
    opportunity_slug: str = ""


@dataclass(frozen=True)
class NewsAlert:
    """A research-driven daily trigger: rate decisions, CPI, rebate or theme news."""

    rule: str
    subject: str
    headline: str
    detail: str
    source_url: str
    source_date: str
    severity: str = "notable"


@dataclass
class ResearchResult:
    """Everything one research pass produced, after validation."""

    theme_updates: list[ThemeUpdate] = field(default_factory=list)
    opportunities: list[Opportunity] = field(default_factory=list)
    actions: list[Action] = field(default_factory=list)
    news_alerts: list[NewsAlert] = field(default_factory=list)
    summary: list[str] = field(default_factory=list)
    rejected: list[str] = field(default_factory=list)
    raw: dict[str, Any] = field(default_factory=dict, repr=False)
