"""REST clients: CoinGecko, ccxt (OHLCV), DefiLlama -- all with disk caching,
rate limiting and retry/backoff. Every failure is caught, logged via
`logutil.log_data_quality`, and returns None/[] to the caller rather than
raising, so a single flaky endpoint never crashes a whole pipeline run.
"""
from __future__ import annotations

import hashlib
import json
import os
import time
from pathlib import Path
from typing import Any

import requests

from .config import PROJECT_ROOT, load_config
from .logutil import get_logger, log_data_quality

logger = get_logger(__name__)

RAW_DIR = PROJECT_ROOT / "data" / "raw"


class DiskCache:
    """Simple TTL cache: one JSON file per (source, endpoint, params) hash."""

    def __init__(self, source: str):
        self.dir = RAW_DIR / source
        self.dir.mkdir(parents=True, exist_ok=True)

    def _path(self, key: str) -> Path:
        digest = hashlib.sha256(key.encode()).hexdigest()[:24]
        return self.dir / f"{digest}.json"

    def get(self, key: str, ttl_seconds: int) -> Any | None:
        path = self._path(key)
        if not path.exists():
            return None
        try:
            payload = json.loads(path.read_text())
        except (json.JSONDecodeError, OSError):
            return None
        if time.time() - payload.get("_cached_at", 0) > ttl_seconds:
            return None
        return payload.get("data")

    def set(self, key: str, data: Any) -> None:
        path = self._path(key)
        try:
            path.write_text(json.dumps({"_cached_at": time.time(), "data": data}))
        except OSError as exc:
            logger.warning("cache write failed for %s: %s", path, exc)


class RateLimiter:
    """Minimum-interval limiter: blocks just long enough between calls."""

    def __init__(self, min_interval_seconds: float):
        self.min_interval = min_interval_seconds
        self._last_call = 0.0

    def wait(self) -> None:
        elapsed = time.monotonic() - self._last_call
        remaining = self.min_interval - elapsed
        if remaining > 0:
            time.sleep(remaining)
        self._last_call = time.monotonic()


def _request_with_backoff(
    session: requests.Session,
    url: str,
    params: dict | None,
    headers: dict | None,
    timeout: int,
    limiter: RateLimiter,
    max_retries: int = 6,
) -> requests.Response | None:
    delay = 5.0
    for attempt in range(max_retries):
        limiter.wait()
        try:
            resp = session.get(url, params=params, headers=headers, timeout=timeout)
        except requests.RequestException as exc:
            logger.warning("request error (attempt %d) %s: %s", attempt + 1, url, exc)
            time.sleep(delay)
            delay *= 2
            continue
        if resp.status_code == 429 or resp.status_code >= 500:
            logger.warning("HTTP %d from %s (attempt %d), backing off", resp.status_code, url, attempt + 1)
            time.sleep(delay)
            delay *= 2
            continue
        return resp
    return None


class CoinGeckoClient:
    def __init__(self, config: dict | None = None, api_key: str | None = None):
        self.config = config or load_config()
        self.base_url = self.config["data_sources"]["coingecko_base_url"]
        self.ttl = self.config["data_sources"]["cache_ttl_seconds"]
        self.timeout = self.config["general"]["request_timeout_seconds"]
        self.api_key = api_key
        self.session = requests.Session()
        # The public (no-key) API rate limit is tight, and shared across whatever else
        # is on the same egress IP in practice -- 6.5s/call still produced sustained
        # 429s in testing behind a shared sandbox proxy. A demo API key gets a
        # materially higher limit; tune this further via COINGECKO_MIN_INTERVAL_SECONDS
        # if you're still seeing 429s in `data/data_quality_log.csv`.
        default_interval = 12.0 if not api_key else 1.5
        interval = float(os.environ.get("COINGECKO_MIN_INTERVAL_SECONDS", default_interval))
        self.limiter = RateLimiter(interval)
        self.cache = DiskCache("coingecko")

    def _headers(self) -> dict:
        if self.api_key:
            return {"x-cg-demo-api-key": self.api_key}
        return {}

    def _get(self, endpoint: str, params: dict | None, ttl: int) -> Any | None:
        url = f"{self.base_url}{endpoint}"
        cache_key = f"{endpoint}?{json.dumps(params or {}, sort_keys=True)}"
        cached = self.cache.get(cache_key, ttl)
        if cached is not None:
            return cached
        resp = _request_with_backoff(self.session, url, params, self._headers(), self.timeout, self.limiter)
        if resp is None:
            log_data_quality("*", "coingecko", endpoint, "request failed after retries")
            return None
        if resp.status_code != 200:
            log_data_quality("*", "coingecko", endpoint, f"HTTP {resp.status_code}: {resp.text[:200]}")
            return None
        try:
            data = resp.json()
        except json.JSONDecodeError:
            log_data_quality("*", "coingecko", endpoint, "invalid JSON response")
            return None
        self.cache.set(cache_key, data)
        return data

    def ping(self) -> bool:
        return self._get("/ping", None, 60) is not None

    def coins_list(self) -> list[dict]:
        data = self._get("/coins/list", {"include_platform": "false"}, self.ttl["markets"])
        return data or []

    def coins_markets(
        self,
        vs_currency: str,
        ids: list[str] | None = None,
        category: str | None = None,
        page: int = 1,
        per_page: int = 250,
        price_change_percentage: str = "1h,24h,7d,30d",
    ) -> list[dict]:
        params = {
            "vs_currency": vs_currency,
            "order": "market_cap_desc",
            "per_page": per_page,
            "page": page,
            "price_change_percentage": price_change_percentage,
            "sparkline": "false",
        }
        if ids:
            params["ids"] = ",".join(ids)
        if category:
            params["category"] = category
        data = self._get("/coins/markets", params, self.ttl["markets"])
        return data or []

    def coin_detail(self, coin_id: str) -> dict | None:
        params = {
            "localization": "false",
            "tickers": "false",
            "market_data": "true",
            "community_data": "false",
            "developer_data": "false",
            "sparkline": "false",
        }
        return self._get(f"/coins/{coin_id}", params, self.ttl["coin_detail"])

    def coin_market_chart(self, coin_id: str, vs_currency: str, days: int) -> dict | None:
        params = {"vs_currency": vs_currency, "days": days, "interval": "daily"}
        return self._get(f"/coins/{coin_id}/market_chart", params, self.ttl["market_chart"])

    def coin_history(self, coin_id: str, date_ddmmyyyy: str) -> dict | None:
        """date_ddmmyyyy format: dd-mm-yyyy, per CoinGecko's /coins/{id}/history."""
        params = {"date": date_ddmmyyyy, "localization": "false"}
        return self._get(f"/coins/{coin_id}/history", params, self.ttl["coin_detail"])

    def coin_tickers(self, coin_id: str) -> list[dict]:
        data = self._get(f"/coins/{coin_id}/tickers", {"include_exchange_logo": "false"}, self.ttl["tickers"])
        return (data or {}).get("tickers", []) if data else []

    def categories(self) -> list[dict]:
        data = self._get("/coins/categories", None, self.ttl["categories"])
        return data or []

    def global_data(self) -> dict | None:
        data = self._get("/global", None, self.ttl["global"])
        return (data or {}).get("data")

    def exchange_rates(self) -> dict | None:
        data = self._get("/exchange_rates", None, self.ttl["global"])
        return (data or {}).get("rates")

    def usd_to_aud_rate(self) -> float | None:
        """AUD per 1 USD, derived from BTC's price in each currency."""
        rates = self.exchange_rates()
        if not rates:
            return None
        try:
            return float(rates["aud"]["value"]) / float(rates["usd"]["value"])
        except (KeyError, TypeError, ZeroDivisionError, ValueError):
            log_data_quality("*", "coingecko", "exchange_rates", "could not derive AUD/USD rate")
            return None


class DefiLlamaClient:
    def __init__(self, config: dict | None = None):
        self.config = config or load_config()
        self.base_url = self.config["data_sources"]["defillama_base_url"]
        self.timeout = self.config["general"]["request_timeout_seconds"]
        self.session = requests.Session()
        self.limiter = RateLimiter(0.6)
        self.cache = DiskCache("defillama")
        self.ttl = self.config["data_sources"]["cache_ttl_seconds"]["defillama"]

    def _get(self, endpoint: str, params: dict | None = None) -> Any | None:
        url = f"{self.base_url}{endpoint}"
        cache_key = f"{endpoint}?{json.dumps(params or {}, sort_keys=True)}"
        cached = self.cache.get(cache_key, self.ttl)
        if cached is not None:
            return cached
        resp = _request_with_backoff(self.session, url, params, None, self.timeout, self.limiter)
        if resp is None or resp.status_code != 200:
            code = resp.status_code if resp is not None else "no-response"
            log_data_quality("*", "defillama", endpoint, f"fetch failed ({code})")
            return None
        try:
            data = resp.json()
        except json.JSONDecodeError:
            log_data_quality("*", "defillama", endpoint, "invalid JSON response")
            return None
        self.cache.set(cache_key, data)
        return data

    def fees_and_revenue(self, protocol_slug: str) -> dict | None:
        """Returns {'total_fees_ttm_usd', 'total_revenue_ttm_usd', 'quarterly': [...]}."""
        fees = self._get(f"/summary/fees/{protocol_slug}", {"dataType": "dailyFees"})
        revenue = self._get(f"/summary/fees/{protocol_slug}", {"dataType": "dailyRevenue"})
        if fees is None and revenue is None:
            return None
        return {"fees": fees, "revenue": revenue}


class CcxtOhlcvClient:
    """Wraps ccxt to fetch daily OHLCV history for a coin's USD (or AUD) pair."""

    def __init__(self, exchange_id: str = "kraken"):
        import os

        import ccxt  # local import: keeps ccxt optional for pure-metrics unit tests

        self.exchange_id = exchange_id
        self.exchange = getattr(ccxt, exchange_id)({"enableRateLimit": True})
        # ccxt's requests session ignores the process's proxy/CA env vars by default
        # (trust_env=False, to avoid surprising users with an unwanted system proxy).
        # Honour them explicitly when set, so this works unchanged behind a corporate
        # proxy or a sandboxed egress proxy -- a no-op on a normal host with no proxy.
        ca_bundle = os.environ.get("REQUESTS_CA_BUNDLE") or os.environ.get("SSL_CERT_FILE")
        if ca_bundle:
            self.exchange.session.verify = ca_bundle
        https_proxy = os.environ.get("HTTPS_PROXY") or os.environ.get("https_proxy")
        if https_proxy:
            self.exchange.session.trust_env = True
            self.exchange.session.proxies = {"http": https_proxy, "https": https_proxy}
        self._markets_loaded = False
        self.cache = DiskCache(f"ccxt_{exchange_id}")

    def _ensure_markets(self) -> bool:
        if self._markets_loaded:
            return True
        try:
            self.exchange.load_markets()
            self._markets_loaded = True
            return True
        except Exception as exc:  # noqa: BLE001 - ccxt raises many exception types
            logger.warning("failed to load markets for %s: %s", self.exchange_id, exc)
            log_data_quality("*", self.exchange_id, "markets", f"load_markets failed: {exc}")
            return False

    def symbol_for(self, coin_symbol: str, quote: str = "USD") -> str | None:
        if not self._ensure_markets():
            return None
        candidate = f"{coin_symbol.upper()}/{quote.upper()}"
        if candidate in self.exchange.markets:
            return candidate
        return None

    def daily_ohlcv(self, coin_symbol: str, quote: str = "USD", days: int = 800) -> list[list[float]]:
        """Returns rows of [timestamp_ms, open, high, low, close, volume], oldest first."""
        symbol = self.symbol_for(coin_symbol, quote)
        if symbol is None:
            log_data_quality(coin_symbol, self.exchange_id, "ohlcv", f"no {quote} market on {self.exchange_id}")
            return []
        cache_key = f"ohlcv:{symbol}:{days}"
        cached = self.cache.get(cache_key, 3600)
        if cached is not None:
            return cached
        since = self.exchange.milliseconds() - days * 24 * 60 * 60 * 1000
        rows: list[list[float]] = []
        try:
            while True:
                batch = self.exchange.fetch_ohlcv(symbol, timeframe="1d", since=since, limit=1000)
                if not batch:
                    break
                rows.extend(batch)
                last_ts = batch[-1][0]
                if last_ts <= since or len(batch) < 2:
                    break
                since = last_ts + 24 * 60 * 60 * 1000
                if since >= self.exchange.milliseconds():
                    break
        except Exception as exc:  # noqa: BLE001
            logger.warning("fetch_ohlcv failed for %s on %s: %s", symbol, self.exchange_id, exc)
            log_data_quality(coin_symbol, self.exchange_id, "ohlcv", f"fetch_ohlcv failed: {exc}")
            return rows
        self.cache.set(cache_key, rows)
        return rows
