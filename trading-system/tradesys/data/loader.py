"""Daily OHLCV loading: Twelve Data primary, yfinance fallback, local cache,
split/dividend adjustment applied uniformly regardless of source.

Network clients are injected (TwelveDataClient / YFinanceClient instances)
rather than constructed inside load_symbol_bars, so tests can substitute
fakes and never make a real HTTP call.
"""

from __future__ import annotations

from dataclasses import dataclass

import pandas as pd
import requests

from tradesys.config import TWELVE_DATA_API_KEY
from tradesys.data import cache as bar_cache
from tradesys.data.adjustments import adjust_ohlcv
from tradesys.data.quality import TruncationReport, truncate_before_anomaly

TWELVE_DATA_BASE = "https://api.twelvedata.com"


class TwelveDataClient:
    """Thin wrapper around the Twelve Data REST API (not the MCP connector —
    this runs standalone, so it needs its own API key in .env)."""

    def __init__(self, api_key: str = TWELVE_DATA_API_KEY, session: requests.Session | None = None):
        if not api_key:
            raise ValueError("TWELVE_DATA_API_KEY is not set (check your .env)")
        self.api_key = api_key
        self.session = session or requests.Session()

    def _get(self, path: str, params: dict) -> dict:
        params = {**params, "apikey": self.api_key}
        resp = self.session.get(f"{TWELVE_DATA_BASE}{path}", params=params, timeout=15)
        resp.raise_for_status()
        data = resp.json()
        if isinstance(data, dict) and data.get("status") == "error":
            raise RuntimeError(f"Twelve Data error for {path}: {data.get('message')}")
        return data

    def get_time_series(self, symbol: str, exchange: str, outputsize: int = 5000) -> pd.DataFrame:
        data = self._get(
            "/time_series",
            {"symbol": symbol, "exchange": exchange, "interval": "1day", "outputsize": outputsize},
        )
        values = data.get("values", [])
        df = pd.DataFrame(values)
        if df.empty:
            return pd.DataFrame(columns=["date", "open", "high", "low", "close", "volume"])
        df = df.rename(columns={"datetime": "date"})
        for col in ["open", "high", "low", "close", "volume"]:
            df[col] = df[col].astype(float)
        return df[["date", "open", "high", "low", "close", "volume"]]

    def get_splits(self, symbol: str, exchange: str) -> pd.DataFrame:
        data = self._get("/splits", {"symbol": symbol, "exchange": exchange})
        rows = data.get("splits", data if isinstance(data, list) else [])
        if not rows:
            return pd.DataFrame(columns=["date", "ratio"])
        df = pd.DataFrame(rows)
        df = df.rename(columns={"split_date": "date", "from_factor": "from_factor", "to_factor": "to_factor"})
        if "ratio" not in df.columns and {"from_factor", "to_factor"}.issubset(df.columns):
            df["ratio"] = df["to_factor"].astype(float) / df["from_factor"].astype(float)
        return df[["date", "ratio"]]

    def get_dividends(self, symbol: str, exchange: str) -> pd.DataFrame:
        data = self._get("/dividends", {"symbol": symbol, "exchange": exchange})
        rows = data.get("dividends", data if isinstance(data, list) else [])
        if not rows:
            return pd.DataFrame(columns=["date", "amount"])
        df = pd.DataFrame(rows)
        df = df.rename(columns={"ex_date": "date", "payment_date": "date"} if "ex_date" in df.columns else {})
        return df[["date", "amount"]]


class YFinanceClient:
    """Fallback source. yfinance's history() already returns split/dividend
    adjusted prices when auto_adjust=True, so no separate adjustment pass is
    needed for data that comes through this path."""

    def __init__(self, yf_module=None):
        if yf_module is None:
            import yfinance as yf_module  # imported lazily so it's an optional dep
        self.yf = yf_module

    def get_time_series(self, symbol: str, exchange: str, outputsize: int = 5000) -> pd.DataFrame:
        yahoo_symbol = f"{symbol}.AX" if exchange == "ASX" else symbol
        ticker = self.yf.Ticker(yahoo_symbol)
        hist = ticker.history(period="max", auto_adjust=True)
        if hist.empty:
            return pd.DataFrame(columns=["date", "open", "high", "low", "close", "volume"])
        hist = hist.reset_index().rename(
            columns={"Date": "date", "Open": "open", "High": "high", "Low": "low", "Close": "close", "Volume": "volume"}
        )
        hist["date"] = pd.to_datetime(hist["date"]).dt.tz_localize(None)
        return hist[["date", "open", "high", "low", "close", "volume"]].tail(outputsize)


@dataclass
class LoadResult:
    bars: pd.DataFrame
    source: str  # "cache" | "twelve_data" | "yfinance"
    quality: TruncationReport | None = None


def load_symbol_bars(
    symbol: str,
    exchange: str = "ASX",
    primary_client: TwelveDataClient | None = None,
    fallback_client: YFinanceClient | None = None,
    force_refresh: bool = False,
    cache_dir: str | None = None,
) -> LoadResult:
    """Loads adjusted daily bars for `symbol`, preferring the cache, then
    Twelve Data, then yfinance. Raises only if every source fails."""
    cache_kwargs = {"cache_dir": cache_dir} if cache_dir else {}

    if not force_refresh:
        cached = bar_cache.load_cached_bars(symbol, **cache_kwargs) if cache_dir else bar_cache.load_cached_bars(symbol)
        if cached is not None and not cached.empty:
            return LoadResult(bars=cached, source="cache")

    errors: list[str] = []

    if primary_client is not None:
        try:
            raw = primary_client.get_time_series(symbol, exchange)
            splits = primary_client.get_splits(symbol, exchange)
            dividends = primary_client.get_dividends(symbol, exchange)
            adjusted = adjust_ohlcv(raw, splits=splits, dividends=dividends)
            adjusted, quality = truncate_before_anomaly(adjusted)
            if cache_dir:
                bar_cache.save_bars(symbol, adjusted, cache_dir=cache_dir)
            else:
                bar_cache.save_bars(symbol, adjusted)
            return LoadResult(bars=adjusted, source="twelve_data", quality=quality)
        except Exception as exc:  # noqa: BLE001 - deliberately broad, we fall back
            errors.append(f"twelve_data: {exc}")

    if fallback_client is not None:
        try:
            bars = fallback_client.get_time_series(symbol, exchange)
            bars, quality = truncate_before_anomaly(bars)
            if cache_dir:
                bar_cache.save_bars(symbol, bars, cache_dir=cache_dir)
            else:
                bar_cache.save_bars(symbol, bars)
            return LoadResult(bars=bars, source="yfinance", quality=quality)
        except Exception as exc:  # noqa: BLE001
            errors.append(f"yfinance: {exc}")

    raise RuntimeError(f"Could not load bars for {symbol}: {'; '.join(errors) or 'no data sources configured'}")
