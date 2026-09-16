"""The gate between what the model said and what reaches the inbox.

The source rules are enforced here, mechanically, rather than trusted to a
prompt. A claim without a working source URL and a parseable date does not get
softened or flagged — it is removed. An opportunity left with no surviving
evidence is dropped entirely.

Every rejection is recorded with its reason, so the run log can show what was
thrown away and why. Silent filtering would be its own kind of dishonesty.
"""

from __future__ import annotations

import re
from datetime import date, datetime, timedelta
from typing import Any, Iterable

from .schemas import (
    SCORE_FIELDS,
    SOURCE_STRENGTHS,
    THEME_STATUSES,
    Action,
    Conflict,
    Evidence,
    NewsAlert,
    Opportunity,
    SubScores,
    ThemeUpdate,
)

URL_PATTERN = re.compile(r"^https?://[^\s]+\.[^\s]+$", re.IGNORECASE)

# Hosts that describe themselves as evidence but are selling something. Anything
# matching is forced to `weak` regardless of what the model claimed.
SELF_PROMOTIONAL_HINTS = (
    "medium.com", "substack.com", "linkedin.com/pulse", "blogspot.",
    "wordpress.com", "/blog/", "gumroad.com", "teachable.com", "kajabi.",
    "skool.com", "udemy.com",
)


def _items(payload: Any, key: str, *, allow_str: bool = False) -> Any:
    """Read a list off a payload defensively.

    A model that returns ``"opportunities": null`` instead of ``[]`` must not
    crash the run; neither must a bare string or a top-level list.
    """
    if not isinstance(payload, dict):
        return []
    value = payload.get(key)
    if allow_str and isinstance(value, str):
        return value
    return value if isinstance(value, list) else []


class Rejection(Exception):
    """Internal signal that an item failed validation."""


def _clean(value: Any, limit: int = 4000) -> str:
    return str(value or "").strip()[:limit]


def parse_date(value: Any) -> date | None:
    """Accept YYYY-MM-DD, or YYYY-MM which is treated as the first of the month."""
    text = _clean(value, 32)
    for fmt in ("%Y-%m-%d", "%Y-%m", "%d %B %Y", "%d %b %Y"):
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            continue
    return None


def validate_evidence(raw: Any, *, today: date, max_age_days: int | None,
                      rejected: list[str], context: str) -> Evidence | None:
    """One evidence item, or ``None`` with a reason appended to ``rejected``."""
    if not isinstance(raw, dict):
        rejected.append(f"{context}: evidence entry was not an object")
        return None

    claim = _clean(raw.get("claim"))
    url = _clean(raw.get("source_url"), 1000)
    source_date = parse_date(raw.get("source_date"))

    if not claim:
        rejected.append(f"{context}: evidence with no claim")
        return None
    if not URL_PATTERN.match(url):
        rejected.append(f"{context}: '{claim[:60]}' has no usable source URL")
        return None
    if source_date is None:
        rejected.append(f"{context}: '{claim[:60]}' has no parseable source date")
        return None
    if source_date > today + timedelta(days=1):
        rejected.append(f"{context}: '{claim[:60]}' is dated in the future ({source_date})")
        return None
    if max_age_days is not None and source_date < today - timedelta(days=max_age_days):
        rejected.append(
            f"{context}: '{claim[:60]}' is from {source_date}, older than the "
            f"{max_age_days}-day window")
        return None

    strength = _clean(raw.get("source_strength"), 32).lower()
    if strength not in SOURCE_STRENGTHS:
        strength = "weak"
    lowered = url.lower()
    if any(hint in lowered for hint in SELF_PROMOTIONAL_HINTS):
        # A blog or course platform is not a primary source, whatever it was labelled.
        strength = "weak"

    return Evidence(
        claim=claim,
        source_name=_clean(raw.get("source_name"), 200) or "unnamed source",
        source_url=url,
        source_date=source_date.isoformat(),
        source_strength=strength,
        number_value=_clean(raw.get("number_value"), 200),
    )


def validate_evidence_list(raw: Any, *, today: date, max_age_days: int | None,
                           rejected: list[str], context: str) -> tuple[Evidence, ...]:
    if not isinstance(raw, list):
        return ()
    items = [validate_evidence(item, today=today, max_age_days=max_age_days,
                               rejected=rejected, context=context) for item in raw]
    return tuple(item for item in items if item is not None)


def _validate_conflicts(raw: Any) -> tuple[Conflict, ...]:
    if not isinstance(raw, list):
        return ()
    out = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        topic, a, b = (_clean(item.get("topic")), _clean(item.get("side_a")),
                       _clean(item.get("side_b")))
        if topic and a and b:
            out.append(Conflict(topic=topic, side_a=a, side_b=b))
    return tuple(out)


# ---------------------------------------------------------------------------
# Theme updates
# ---------------------------------------------------------------------------


def validate_theme_updates(payload: Any, known_slugs: Iterable[str], *, today: date,
                           rejected: list[str]) -> list[ThemeUpdate]:
    """Theme evidence has no age window: an old primary source still anchors a fact."""
    known = set(known_slugs)
    updates: list[ThemeUpdate] = []
    seen: set[str] = set()

    for raw in _items(payload, "themes"):
        if not isinstance(raw, dict):
            continue
        slug = _clean(raw.get("slug"), 100)
        if slug not in known:
            rejected.append(f"theme update for unknown slug {slug!r}")
            continue
        if slug in seen:
            rejected.append(f"duplicate theme update for {slug!r}")
            continue
        status = _clean(raw.get("status"), 16).upper()
        if status not in THEME_STATUSES:
            rejected.append(f"theme {slug!r} returned unknown status {status!r}")
            continue
        reason = _clean(raw.get("reason"), 400)
        if not reason:
            rejected.append(f"theme {slug!r} gave no reason for its status")
            continue

        seen.add(slug)
        updates.append(ThemeUpdate(
            slug=slug, status=status, reason=reason,
            evidence=validate_evidence_list(raw.get("evidence"), today=today,
                                            max_age_days=None, rejected=rejected,
                                            context=f"theme {slug}"),
            conflicts=_validate_conflicts(raw.get("conflicts")),
        ))
    return updates


# ---------------------------------------------------------------------------
# Opportunities
# ---------------------------------------------------------------------------


def _validate_scores(raw: Any, context: str, rejected: list[str]) -> SubScores | None:
    if not isinstance(raw, dict):
        rejected.append(f"{context}: no scores returned")
        return None
    values: dict[str, int] = {}
    for name in SCORE_FIELDS:
        try:
            value = int(round(float(raw.get(name))))
        except (TypeError, ValueError):
            rejected.append(f"{context}: score {name} was missing or not a number")
            return None
        if not 1 <= value <= 10:
            rejected.append(f"{context}: score {name}={value} is outside 1-10")
            return None
        values[name] = value
    reasons = raw.get("reasons") if isinstance(raw.get("reasons"), dict) else {}
    return SubScores(**values,
                     reasons={k: _clean(v, 300) for k, v in reasons.items()
                              if k in SCORE_FIELDS})


def validate_opportunities(payload: Any, *, today: date, max_age_days: int,
                           max_items: int, rejected: list[str],
                           known_theme_slugs: Iterable[str] = ()) -> list[Opportunity]:
    known_themes = set(known_theme_slugs)
    out: list[Opportunity] = []
    seen: set[str] = set()

    raw_items = _items(payload, "opportunities")
    for raw in raw_items:
        if not isinstance(raw, dict):
            continue
        title = _clean(raw.get("title"), 200)
        slug = _clean(raw.get("slug"), 100) or re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")
        context = f"opportunity {slug or title or '<unnamed>'}"

        if not title or not slug:
            rejected.append(f"{context}: no title")
            continue
        if slug in seen:
            rejected.append(f"{context}: duplicate")
            continue

        evidence = validate_evidence_list(raw.get("evidence"), today=today,
                                          max_age_days=max_age_days,
                                          rejected=rejected, context=context)
        if not evidence:
            # This is the rule that keeps plausible-sounding nothing out of the email.
            rejected.append(f"{context}: DROPPED — no evidence survived validation")
            continue

        scores = _validate_scores(raw.get("scores"), context, rejected)
        if scores is None:
            rejected.append(f"{context}: DROPPED — unusable scores")
            continue

        theme_slug = _clean(raw.get("theme_slug"), 100)
        if theme_slug and theme_slug not in known_themes:
            theme_slug = ""

        seen.add(slug)
        out.append(Opportunity(
            slug=slug, title=title,
            summary=_clean(raw.get("summary"), 1500),
            who_earns=_clean(raw.get("who_earns"), 600),
            platform_revenue_evidence=_clean(raw.get("platform_revenue_evidence"), 1500),
            individual_earnings_evidence=_clean(raw.get("individual_earnings_evidence"), 1500),
            startup_cost_aud_min=_number(raw.get("startup_cost_aud_min")),
            startup_cost_aud_max=_number(raw.get("startup_cost_aud_max")),
            time_to_first_dollar_days=_integer(raw.get("time_to_first_dollar_days")),
            skills_required=_clean(raw.get("skills_required"), 600),
            saturation=_clean(raw.get("saturation"), 600),
            red_flags=_clean(raw.get("red_flags"), 900),
            au_eligibility=_clean(raw.get("au_eligibility"), 600),
            evidence=evidence, scores=scores, theme_slug=theme_slug,
        ))

    if len(out) > max_items:
        for extra in out[max_items:]:
            rejected.append(f"opportunity {extra.slug}: over the {max_items}-item limit")
        out = out[:max_items]
    return out


def _number(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _integer(value: Any) -> int | None:
    number = _number(value)
    return int(round(number)) if number is not None else None


# ---------------------------------------------------------------------------
# Actions and news
# ---------------------------------------------------------------------------


def validate_actions(payload: Any, *, max_minutes: int, rejected: list[str]) -> list[Action]:
    """Actions must fit the brief's under-three-hours rule, which is a hard cap."""
    out: list[Action] = []
    raw_items = _items(payload, "actions")
    for index, raw in enumerate(raw_items, start=1):
        if not isinstance(raw, dict):
            continue
        title = _clean(raw.get("title"), 300)
        if not title:
            continue
        minutes = _integer(raw.get("est_minutes"))
        if minutes is None or minutes <= 0:
            rejected.append(f"action '{title[:50]}': no usable time estimate")
            continue
        if minutes > max_minutes:
            rejected.append(
                f"action '{title[:50]}': {minutes} min exceeds the "
                f"{max_minutes}-minute limit")
            continue
        out.append(Action(rank=len(out) + 1, title=title,
                          why=_clean(raw.get("why"), 600), est_minutes=minutes,
                          opportunity_slug=_clean(raw.get("opportunity_slug"), 100)))
        if len(out) == 3:
            break
    return out


def validate_news_alerts(payload: Any, *, today: date, rejected: list[str],
                         max_age_days: int = 7) -> list[NewsAlert]:
    out: list[NewsAlert] = []
    raw_items = _items(payload, "alerts")
    for raw in raw_items:
        if not isinstance(raw, dict):
            continue
        headline = _clean(raw.get("headline"), 300)
        url = _clean(raw.get("source_url"), 1000)
        source_date = parse_date(raw.get("source_date"))
        if not headline:
            continue
        if not URL_PATTERN.match(url):
            rejected.append(f"news alert '{headline[:50]}': no usable source URL")
            continue
        if source_date is None or source_date < today - timedelta(days=max_age_days):
            rejected.append(f"news alert '{headline[:50]}': not recent enough to be news")
            continue
        severity = _clean(raw.get("severity"), 16).lower()
        out.append(NewsAlert(
            rule=_clean(raw.get("rule"), 50) or "theme_news",
            subject=_clean(raw.get("subject"), 100) or "general",
            headline=headline,
            detail=_clean(raw.get("detail"), 1500),
            source_url=url, source_date=source_date.isoformat(),
            severity=severity if severity in ("info", "notable", "urgent") else "notable",
        ))
    return out


def validate_summary(payload: Any) -> list[str]:
    raw = _items(payload, "summary", allow_str=True)
    if isinstance(raw, str):
        raw = [line for line in raw.splitlines() if line.strip()]
    return [_clean(line, 300) for line in raw if _clean(line)][:3]
