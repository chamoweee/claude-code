"""Configuration loading.

Two kinds of configuration live here, and they are deliberately separated:

* **Repo config** (``config/*.toml``) is public. Thresholds, pricing, the
  watchlist, the tracked themes. Safe to read in a public repository.
* **Private config** is never committed. The personal profile used for
  fit-scoring and the report recipient arrive from environment variables
  (GitHub Secrets in CI) or from git-ignored ``*.local`` files when running on
  Chamk's own machine.

Nothing in this module reads the network or the database.
"""

from __future__ import annotations

import os
import tomllib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

PACKAGE_ROOT = Path(__file__).resolve().parent
PROJECT_ROOT = PACKAGE_ROOT.parent
CONFIG_DIR = PROJECT_ROOT / "config"
DATA_DIR = PROJECT_ROOT / "data"
DEFAULT_DB_PATH = DATA_DIR / "radar.db"
REPORTS_DIR = DATA_DIR / "reports"


class ConfigError(RuntimeError):
    """Raised when configuration is missing or self-contradictory."""


# ---------------------------------------------------------------------------
# Typed views over the TOML
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ScheduleConfig:
    timezone: str
    weekly_weekday: int  # Monday == 0, matching datetime.weekday()
    weekly_hour: int
    daily_weekdays: tuple[int, ...]
    daily_hour: int


@dataclass(frozen=True)
class BudgetConfig:
    monthly_cap_aud: float
    warn_at_fraction: float
    usd_to_aud: float
    reserve_aud: float


@dataclass(frozen=True)
class ModelPricing:
    """USD per million tokens, plus the per-search charge for the web tool."""

    model: str
    input_per_mtok_usd: float
    output_per_mtok_usd: float
    cache_read_per_mtok_usd: float
    cache_write_per_mtok_usd: float
    web_search_per_1k_usd: float


@dataclass(frozen=True)
class AlertThresholds:
    watchlist_move_pct: float
    commodity_move_pct: float
    fx_move_pct: float


@dataclass(frozen=True)
class ResearchConfig:
    model: str
    weekly_effort: str
    daily_effort: str
    max_new_trends: int
    evidence_max_age_days: int
    weak_source_score_cap: float
    no_individual_evidence_cap: float
    personal_fit_threshold: int
    max_action_minutes: int
    max_searches_themes: int
    max_searches_discovery: int
    max_searches_daily: int


@dataclass(frozen=True)
class WatchlistEntry:
    symbol: str
    name: str
    kind: str  # 'equity' | 'etf' | 'reit'
    exchange: str
    quote_symbol: str  # what the price source is queried with
    confirmed: bool  # False means the ticker is ambiguous and needs confirming
    active: bool = True  # False means resolved but no longer trading
    thesis: str = ""

    @property
    def quotable(self) -> bool:
        """Only a resolved, still-trading entry with a symbol may be priced."""
        return self.confirmed and self.active and bool(self.quote_symbol)


@dataclass(frozen=True)
class ThemeSeed:
    slug: str
    title: str
    description: str
    watch_for: str
    status: str
    evidence: tuple[dict[str, Any], ...] = ()


@dataclass(frozen=True)
class Settings:
    schedule: ScheduleConfig
    budget: BudgetConfig
    alerts: AlertThresholds
    research: ResearchConfig
    pricing: dict[str, ModelPricing]
    baseline_date: str
    db_path: Path = DEFAULT_DB_PATH
    raw: dict[str, Any] = field(default_factory=dict, repr=False)

    def pricing_for(self, model: str) -> ModelPricing:
        try:
            return self.pricing[model]
        except KeyError:
            raise ConfigError(
                f"No pricing configured for model {model!r}. Add a "
                f"[pricing.{model}] table to config/settings.toml — the budget "
                f"guard refuses to run against an unpriced model."
            ) from None


# ---------------------------------------------------------------------------
# Loading
# ---------------------------------------------------------------------------


def _read_toml(path: Path) -> dict[str, Any]:
    if not path.exists():
        raise ConfigError(f"Missing config file: {path}")
    with path.open("rb") as handle:
        return tomllib.load(handle)


def load_settings(config_dir: Path | None = None, db_path: Path | None = None) -> Settings:
    """Load ``config/settings.toml`` into a typed :class:`Settings`."""
    config_dir = config_dir or CONFIG_DIR
    raw = _read_toml(config_dir / "settings.toml")

    general = raw.get("general", {})
    sched = raw.get("schedule", {})
    budget = raw.get("budget", {})
    alerts = raw.get("alerts", {})
    research = raw.get("research", {})

    pricing: dict[str, ModelPricing] = {}
    for model, table in raw.get("pricing", {}).items():
        pricing[model] = ModelPricing(
            model=model,
            input_per_mtok_usd=float(table["input_per_mtok_usd"]),
            output_per_mtok_usd=float(table["output_per_mtok_usd"]),
            cache_read_per_mtok_usd=float(table["cache_read_per_mtok_usd"]),
            cache_write_per_mtok_usd=float(table["cache_write_per_mtok_usd"]),
            web_search_per_1k_usd=float(table["web_search_per_1k_usd"]),
        )

    settings = Settings(
        schedule=ScheduleConfig(
            timezone=general.get("timezone", "Australia/Sydney"),
            weekly_weekday=int(sched.get("weekly_weekday", 0)),
            weekly_hour=int(sched.get("weekly_hour", 7)),
            daily_weekdays=tuple(int(d) for d in sched.get("daily_weekdays", [0, 1, 2, 3, 4])),
            daily_hour=int(sched.get("daily_hour", 7)),
        ),
        budget=BudgetConfig(
            monthly_cap_aud=float(budget.get("monthly_cap_aud", 30.0)),
            warn_at_fraction=float(budget.get("warn_at_fraction", 0.8)),
            usd_to_aud=float(budget.get("usd_to_aud", 1.52)),
            reserve_aud=float(budget.get("reserve_aud", 1.0)),
        ),
        alerts=AlertThresholds(
            watchlist_move_pct=float(alerts.get("watchlist_move_pct", 8.0)),
            commodity_move_pct=float(alerts.get("commodity_move_pct", 3.0)),
            fx_move_pct=float(alerts.get("fx_move_pct", 3.0)),
        ),
        research=ResearchConfig(
            model=research.get("model", "claude-sonnet-5"),
            weekly_effort=research.get("weekly_effort", "high"),
            daily_effort=research.get("daily_effort", "low"),
            max_new_trends=int(research.get("max_new_trends", 5)),
            evidence_max_age_days=int(research.get("evidence_max_age_days", 90)),
            weak_source_score_cap=float(research.get("weak_source_score_cap", 5.0)),
            no_individual_evidence_cap=float(
                research.get("no_individual_evidence_cap", 6.0)),
            personal_fit_threshold=int(research.get("personal_fit_threshold", 5)),
            max_action_minutes=int(research.get("max_action_minutes", 180)),
            max_searches_themes=int(research.get("max_searches_themes", 14)),
            max_searches_discovery=int(research.get("max_searches_discovery", 16)),
            max_searches_daily=int(research.get("max_searches_daily", 6)),
        ),
        pricing=pricing,
        baseline_date=str(general.get("baseline_date", "2026-09-16")),
        db_path=db_path or Path(os.environ.get("RADAR_DB", DEFAULT_DB_PATH)),
        raw=raw,
    )

    _validate(settings)
    return settings


def _validate(settings: Settings) -> None:
    sched = settings.schedule
    if not 0 <= sched.weekly_weekday <= 6:
        raise ConfigError("schedule.weekly_weekday must be 0-6 (Monday is 0)")
    if not 0 <= sched.weekly_hour <= 23:
        raise ConfigError("schedule.weekly_hour must be 0-23")
    if not 0 <= sched.daily_hour <= 23:
        raise ConfigError("schedule.daily_hour must be 0-23")
    if any(not 0 <= d <= 6 for d in sched.daily_weekdays):
        raise ConfigError("schedule.daily_weekdays entries must be 0-6")
    if settings.budget.monthly_cap_aud <= 0:
        raise ConfigError("budget.monthly_cap_aud must be positive")
    if not 0 < settings.budget.warn_at_fraction <= 1:
        raise ConfigError("budget.warn_at_fraction must be between 0 and 1")
    if settings.budget.usd_to_aud <= 0:
        raise ConfigError("budget.usd_to_aud must be positive")
    if settings.research.model not in settings.pricing:
        raise ConfigError(
            f"research.model is {settings.research.model!r} but there is no "
            f"[pricing.{settings.research.model}] table"
        )


def load_watchlist(config_dir: Path | None = None) -> list[WatchlistEntry]:
    raw = _read_toml((config_dir or CONFIG_DIR) / "watchlist.toml")
    entries = []
    for item in raw.get("holding", []):
        entries.append(
            WatchlistEntry(
                symbol=item["symbol"],
                name=item.get("name", item["symbol"]),
                kind=item.get("kind", "equity"),
                exchange=item.get("exchange", ""),
                quote_symbol=item.get("quote_symbol", item["symbol"]),
                confirmed=bool(item.get("confirmed", False)),
                active=bool(item.get("active", True)),
                thesis=item.get("thesis", ""),
            )
        )
    if not entries:
        raise ConfigError("config/watchlist.toml contains no [[holding]] entries")
    return entries


def load_theme_seeds(config_dir: Path | None = None) -> list[ThemeSeed]:
    raw = _read_toml((config_dir or CONFIG_DIR) / "themes.toml")
    seeds = []
    for item in raw.get("theme", []):
        seeds.append(
            ThemeSeed(
                slug=item["slug"],
                title=item["title"],
                description=item.get("description", ""),
                watch_for=item.get("watch_for", ""),
                status=item.get("status", "STABLE"),
                evidence=tuple(item.get("evidence", [])),
            )
        )
    if not seeds:
        raise ConfigError("config/themes.toml contains no [[theme]] entries")
    return seeds


# ---------------------------------------------------------------------------
# Private config — never committed
# ---------------------------------------------------------------------------


def load_profile(config_dir: Path | None = None) -> str:
    """Return the personal profile used for fit-scoring.

    Resolution order: ``RADAR_PROFILE`` (a GitHub Secret in CI), then a
    git-ignored ``config/profile.local.md``, then the redacted example. The
    example is good enough for a dry run but will produce useless fit scores,
    so callers that actually score should check :func:`profile_is_real`.
    """
    config_dir = config_dir or CONFIG_DIR
    from_env = os.environ.get("RADAR_PROFILE", "").strip()
    if from_env:
        return from_env
    local = config_dir / "profile.local.md"
    if local.exists():
        return local.read_text(encoding="utf-8")
    return (config_dir / "profile.example.md").read_text(encoding="utf-8")


def profile_is_real(config_dir: Path | None = None) -> bool:
    config_dir = config_dir or CONFIG_DIR
    if os.environ.get("RADAR_PROFILE", "").strip():
        return True
    return (config_dir / "profile.local.md").exists()


def load_recipient() -> str:
    """The report recipient. Secret-only: there is no committed default."""
    recipient = os.environ.get("RADAR_RECIPIENT", "").strip()
    if not recipient:
        raise ConfigError(
            "RADAR_RECIPIENT is not set. The report recipient is kept out of "
            "this public repo — set it as a GitHub Secret, or export it locally."
        )
    return recipient
