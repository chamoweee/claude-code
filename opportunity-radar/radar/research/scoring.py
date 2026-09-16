"""Turning six sub-scores into one number.

The model supplies the sub-scores and a reason for each; the arithmetic happens
here. That keeps the ranking auditable — you can check the maths — and stable
week to week, because the weights do not drift with the model's mood.

Two caps are applied after the weighted total, and both exist because of
explicit rules in the brief:

* **Weak sources cap the total.** If nothing better than a blog or a marketing
  page supports an opportunity, it cannot outrank something with filings behind
  it, however good the story sounds.
* **"The platform earns" is not "you can earn".** An opportunity with no
  evidence that individuals actually make money is capped too. This is the most
  common failure mode in this space: a real, growing, well-funded platform
  whose contributors earn far less than the headline suggests.

Caps are recorded with their reason so the report can say why a number is held
down, rather than quietly showing a lower score.
"""

from __future__ import annotations

from dataclasses import dataclass

from ..config import ResearchConfig
from .schemas import SCORE_FIELDS, Opportunity, SubScores

# Weights sum to 1.0, so the total stays on the same 1-10 scale as the parts.
WEIGHTS: dict[str, float] = {
    "evidence_strength": 0.25,   # heaviest: an unevidenced lead is not a lead
    "personal_fit": 0.20,
    "capital_fit": 0.15,
    "hours_fit": 0.15,
    "risk": 0.15,
    "speed_to_dollar": 0.10,
}

LABELS: dict[str, str] = {
    "evidence_strength": "Evidence",
    "personal_fit": "Personal fit",
    "capital_fit": "Capital needed",
    "hours_fit": "Hours needed",
    "speed_to_dollar": "Time to first dollar",
    "risk": "Risk",
}

assert set(WEIGHTS) == set(SCORE_FIELDS), "every sub-score must carry a weight"
assert abs(sum(WEIGHTS.values()) - 1.0) < 1e-9, "weights must sum to 1.0"


@dataclass(frozen=True)
class ScoreResult:
    raw_total: float
    total: float
    capped_reason: str = ""

    @property
    def was_capped(self) -> bool:
        return bool(self.capped_reason)


def weighted_total(scores: SubScores) -> float:
    return sum(getattr(scores, name) * weight for name, weight in WEIGHTS.items())


def score_opportunity(opportunity: Opportunity, research: ResearchConfig,
                      no_individual_evidence_cap: float) -> ScoreResult:
    raw = weighted_total(opportunity.scores)
    caps: list[tuple[float, str]] = []

    if opportunity.best_source_strength == "weak":
        caps.append((research.weak_source_score_cap,
                     "no source better than a blog or marketing page"))
    if not opportunity.has_individual_evidence:
        caps.append((no_individual_evidence_cap,
                     "evidence shows the platform earns, not that individuals do"))

    # Each cap is judged against the raw total independently, so a second reason
    # is still reported even when a harder cap has already pulled the score
    # below it. Both facts matter to the reader; only the lowest sets the number.
    binding = [(value, why) for value, why in caps if raw > value]
    total = min([raw] + [value for value, _ in binding])

    return ScoreResult(
        raw_total=round(raw, 2), total=round(total, 2),
        capped_reason="; ".join(f"capped at {value:.1f}: {why}" for value, why in binding))


def rank(opportunities: list[Opportunity], research: ResearchConfig,
         no_individual_evidence_cap: float) -> list[tuple[Opportunity, ScoreResult]]:
    scored = [(item, score_opportunity(item, research, no_individual_evidence_cap))
              for item in opportunities]
    return sorted(scored, key=lambda pair: pair[1].total, reverse=True)


def split_by_fit(scored: list[tuple[Opportunity, ScoreResult]],
                 fit_threshold: int) -> tuple[list, list]:
    """Separate leads Chamk could act on from ones that are real but not for him.

    The brief is explicit that opportunities must not be limited to his skills, so
    a strong trend with a poor personal fit still gets reported — in its own
    section, scored honestly, rather than buried at the bottom of one list or
    filtered out.
    """
    actionable, other = [], []
    for opportunity, result in scored:
        (actionable if opportunity.scores.personal_fit >= fit_threshold
         else other).append((opportunity, result))
    return actionable, other


def format_scoring_table(opportunity: Opportunity, result: ScoreResult) -> list[tuple[str, int, str]]:
    """Rows of (label, score, reason) so the report can show the working."""
    return [(LABELS[name], getattr(opportunity.scores, name),
             opportunity.scores.reasons.get(name, ""))
            for name in SCORE_FIELDS]
