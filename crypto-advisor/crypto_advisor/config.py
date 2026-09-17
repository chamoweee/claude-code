"""Loads config.yaml, portfolio.yaml and .env into simple, validated objects."""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml
from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parent.parent


@dataclass
class Holding:
    coin_id: str
    units: float
    cost_base_aud: float
    purchase_date: str
    exchange: str = ""


@dataclass
class Portfolio:
    cash_aud: float
    holdings: list[Holding]
    watchlist: list[str]

    def holding_ids(self) -> set[str]:
        return {h.coin_id for h in self.holdings}


@dataclass
class Env:
    coingecko_api_key: str | None = None
    anthropic_api_key: str | None = None
    ccxt_exchange: str = "kraken"
    smtp_host: str | None = None
    smtp_port: int = 587
    smtp_user: str | None = None
    smtp_password: str | None = None
    smtp_from: str | None = None
    smtp_to: str | None = None

    @property
    def email_enabled(self) -> bool:
        return bool(self.smtp_host and self.smtp_user and self.smtp_password and self.smtp_to)


def load_config(path: str | Path | None = None) -> dict[str, Any]:
    path = Path(path) if path else PROJECT_ROOT / "config.yaml"
    with open(path) as f:
        return yaml.safe_load(f)


def load_portfolio(path: str | Path | None = None) -> Portfolio:
    path = Path(path) if path else PROJECT_ROOT / "portfolio.yaml"
    if not path.exists():
        example = PROJECT_ROOT / "portfolio.example.yaml"
        raise FileNotFoundError(
            f"{path} not found. Copy {example.name} to {path.name} and fill in your holdings."
        )
    with open(path) as f:
        raw = yaml.safe_load(f) or {}
    holdings = [Holding(**h) for h in raw.get("holdings", []) or []]
    return Portfolio(
        cash_aud=float(raw.get("cash_aud", 0.0)),
        holdings=holdings,
        watchlist=list(raw.get("watchlist", []) or []),
    )


def load_env(dotenv_path: str | Path | None = None) -> Env:
    load_dotenv(dotenv_path or (PROJECT_ROOT / ".env"))
    return Env(
        coingecko_api_key=os.getenv("COINGECKO_API_KEY") or None,
        anthropic_api_key=os.getenv("ANTHROPIC_API_KEY") or None,
        ccxt_exchange=os.getenv("CCXT_EXCHANGE", "kraken"),
        smtp_host=os.getenv("SMTP_HOST") or None,
        smtp_port=int(os.getenv("SMTP_PORT", "587") or 587),
        smtp_user=os.getenv("SMTP_USER") or None,
        smtp_password=os.getenv("SMTP_PASSWORD") or None,
        smtp_from=os.getenv("SMTP_FROM") or None,
        smtp_to=os.getenv("SMTP_TO") or None,
    )
