"""Per-coin metrics: volatility, drawdown, beta/correlation vs BTC, liquidity,
supply inflation, fees/revenue, exchange concentration. Every metric that
can't be computed from available data is set to None and logged via
`logutil.log_data_quality` -- never guessed or interpolated.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Optional

import numpy as np

from .fetch import CoinGeckoClient, DefiLlamaClient
from .logutil import get_logger, log_data_quality
from .universe import UniverseCoin

logger = get_logger(__name__)

DAY_MS = 86_400_000


@dataclass
class CoinMetrics:
    coin_id: str
    fully_diluted_valuation_aud: Optional[float] = None
    supply_ratio: Optional[float] = None  # circulating / max
    annual_supply_inflation_pct: Optional[float] = None
    unlock_risk_flag: bool = False
    unlock_data_available: bool = False
    avg_volume_30d_aud: Optional[float] = None
    avg_volume_90d_aud: Optional[float] = None
    volume_to_mcap_ratio: Optional[float] = None
    fees_ttm_usd: Optional[float] = None
    revenue_ttm_usd: Optional[float] = None
    revenue_quarters_present: Optional[int] = None  # out of trailing 8
    price_to_fees: Optional[float] = None
    price_to_revenue: Optional[float] = None
    volatility_30d_annualized_pct: Optional[float] = None
    volatility_90d_annualized_pct: Optional[float] = None
    volatility_365d_annualized_pct: Optional[float] = None
    max_drawdown_pct: Optional[float] = None
    days_since_ath: Optional[int] = None
    pct_below_ath: Optional[float] = None
    correlation_to_btc_2y: Optional[float] = None
    beta_to_btc_2y: Optional[float] = None
    top_exchange_volume_share_pct: Optional[float] = None
    exchange_concentration_flag: bool = False
    sma_50: Optional[float] = None
    sma_200: Optional[float] = None
    week52_high: Optional[float] = None
    week52_low: Optional[float] = None
    ccxt_exchange: Optional[str] = None
    ccxt_avg_volume_30d_usd: Optional[float] = None
    ccxt_volume_cross_check: Optional[str] = None


def _series(prices: list[tuple[int, float]]) -> tuple[np.ndarray, np.ndarray]:
    if not prices:
        return np.array([]), np.array([])
    arr = np.array(prices, dtype=float)
    return arr[:, 0], arr[:, 1]


def _log_returns(values: np.ndarray) -> np.ndarray:
    if len(values) < 2:
        return np.array([])
    with np.errstate(divide="ignore", invalid="ignore"):
        returns = np.diff(np.log(values))
    return returns[np.isfinite(returns)]


def annualized_volatility_pct(prices: list[float], window_days: int) -> Optional[float]:
    window = prices[-(window_days + 1):] if len(prices) > window_days else prices
    returns = _log_returns(np.array(window, dtype=float))
    if len(returns) < 5:
        return None
    return float(np.std(returns, ddof=1) * np.sqrt(365) * 100)


def max_drawdown_pct(prices: list[float]) -> Optional[float]:
    if len(prices) < 2:
        return None
    arr = np.array(prices, dtype=float)
    running_max = np.maximum.accumulate(arr)
    drawdowns = (arr - running_max) / running_max
    return float(np.min(drawdowns) * 100)


def sma(prices: list[float], window: int) -> Optional[float]:
    if len(prices) < window:
        return None
    return float(np.mean(prices[-window:]))


def historical_weekly_return_range(prices: list[float], min_samples: int = 10) -> Optional[dict]:
    """Real distribution of trailing 7-day returns over the available price
    history -- how much this coin has actually swung in a week, in either
    direction. NOT a forecast: it says nothing about what happens next, only
    what has already happened. Returns None (never a guess) if there isn't
    enough history for the stat to mean anything.

    p10/p90 are used instead of raw min/max because a short or synthetic
    history's extremes are typically outliers, not a picture of "typical"."""
    if len(prices) < 8:
        return None
    arr = np.array(prices, dtype=float)
    weekly_returns = (arr[7:] / arr[:-7] - 1) * 100
    weekly_returns = weekly_returns[np.isfinite(weekly_returns)]
    if len(weekly_returns) < min_samples:
        return None
    return {
        "p10": float(np.percentile(weekly_returns, 10)),
        "median": float(np.median(weekly_returns)),
        "p90": float(np.percentile(weekly_returns, 90)),
        "samples": len(weekly_returns),
    }


def correlation_and_beta(coin_prices: list[float], btc_prices: list[float]) -> tuple[Optional[float], Optional[float]]:
    n = min(len(coin_prices), len(btc_prices))
    if n < 30:
        return None, None
    coin_returns = _log_returns(np.array(coin_prices[-n:], dtype=float))
    btc_returns = _log_returns(np.array(btc_prices[-n:], dtype=float))
    m = min(len(coin_returns), len(btc_returns))
    if m < 30:
        return None, None
    coin_returns, btc_returns = coin_returns[-m:], btc_returns[-m:]
    if np.std(btc_returns) == 0:
        return None, None
    corr = float(np.corrcoef(coin_returns, btc_returns)[0, 1])
    cov = float(np.cov(coin_returns, btc_returns)[0, 1])
    var_btc = float(np.var(btc_returns, ddof=1))
    beta = cov / var_btc if var_btc > 0 else None
    return corr, beta


def _ttm_and_quarters(daily_series: list[list[float]] | None) -> tuple[Optional[float], Optional[int]]:
    """daily_series: [[ts_seconds_or_ms, value], ...]. Returns (TTM sum, quarters
    with >0 value out of trailing 8)."""
    if not daily_series:
        return None, None
    now = datetime.now(timezone.utc)
    points: list[tuple[datetime, float]] = []
    for ts, value in daily_series:
        ts = float(ts)
        if ts > 10**12:  # milliseconds
            ts /= 1000
        points.append((datetime.fromtimestamp(ts, tz=timezone.utc), float(value)))
    if not points:
        return None, None
    ttm_cutoff = now - timedelta(days=365)
    ttm_sum = sum(v for dt, v in points if dt >= ttm_cutoff)

    quarters_with_data = 0
    for q in range(8):
        q_end = now - timedelta(days=90 * q)
        q_start = now - timedelta(days=90 * (q + 1))
        q_total = sum(v for dt, v in points if q_start <= dt < q_end)
        if q_total > 0:
            quarters_with_data += 1
    return ttm_sum, quarters_with_data


def compute_supply_inflation(cg: CoinGeckoClient, coin: UniverseCoin) -> tuple[Optional[float], bool]:
    """Returns (annual_inflation_pct, available). Compares current circulating
    supply to circulating supply ~365 days ago via CoinGecko's history endpoint."""
    if coin.circulating_supply is None:
        log_data_quality(coin.coin_id, "coingecko", "circulating_supply", "missing current circulating supply")
        return None, False
    year_ago = datetime.now(timezone.utc) - timedelta(days=365)
    date_str = year_ago.strftime("%d-%m-%Y")
    history = cg.coin_history(coin.coin_id, date_str)
    if not history:
        log_data_quality(coin.coin_id, "coingecko", "history", "no snapshot ~365d ago")
        return None, False
    past_supply = (history.get("market_data") or {}).get("circulating_supply")
    if not past_supply or past_supply <= 0:
        log_data_quality(coin.coin_id, "coingecko", "history.circulating_supply", "missing/zero supply 365d ago")
        return None, False
    inflation = (coin.circulating_supply - past_supply) / past_supply * 100
    return round(inflation, 3), True


def compute_unlock_risk(defillama: DefiLlamaClient, coin: UniverseCoin, config: dict) -> tuple[bool, bool]:
    """Best-effort: DefiLlama's free unlock/emissions data is sparse. Returns
    (flag_large_unlock, data_available). Never invents an unlock event."""
    if defillama is None:
        return False, False
    slug = config["data_sources"]["defillama_slug_map"].get(coin.coin_id)
    if not slug:
        return False, False
    data = defillama._get(f"/emissions/{slug}")
    if not data or "events" not in data:
        log_data_quality(coin.coin_id, "defillama", "emissions", "no unlock schedule available")
        return False, False
    threshold_pct = config["risk"]["large_unlock_flag_pct_of_supply"]
    now_s = datetime.now(timezone.utc).timestamp()
    horizon_s = now_s + 30 * 86400
    for event in data.get("events", []):
        ts = event.get("timestamp")
        pct_supply = event.get("percentOfSupply") or event.get("percentOfMaxSupply")
        if ts is None or pct_supply is None:
            continue
        if now_s <= ts <= horizon_s and pct_supply >= threshold_pct:
            return True, True
    return False, True


def compute_exchange_concentration(cg: CoinGeckoClient, coin: UniverseCoin, config: dict) -> tuple[Optional[float], bool]:
    tickers = cg.coin_tickers(coin.coin_id)
    volumes = [(t.get("converted_volume") or {}).get("usd") for t in tickers]
    volumes = [v for v in volumes if v is not None and v > 0]
    if not volumes:
        log_data_quality(coin.coin_id, "coingecko", "tickers", "no ticker volume data for concentration check")
        return None, False
    top_share = max(volumes) / sum(volumes) * 100
    flag = top_share >= config["liquidity_risk"]["max_single_exchange_volume_share_pct"]
    return round(top_share, 1), flag


def compute_fees_and_revenue(defillama: DefiLlamaClient, coin: UniverseCoin, config: dict) -> dict:
    slug = config["data_sources"]["defillama_slug_map"].get(coin.coin_id)
    result = {"fees_ttm_usd": None, "revenue_ttm_usd": None, "revenue_quarters_present": None}
    if not slug:
        log_data_quality(coin.coin_id, "defillama", "slug_map", "no DefiLlama mapping configured")
        return result
    payload = defillama.fees_and_revenue(slug)
    if not payload:
        log_data_quality(coin.coin_id, "defillama", "fees/revenue", "fetch failed or unavailable for protocol")
        return result
    fees_chart = ((payload.get("fees") or {}).get("totalDataChart")) or []
    revenue_chart = ((payload.get("revenue") or {}).get("totalDataChart")) or []
    fees_ttm, _ = _ttm_and_quarters(fees_chart)
    revenue_ttm, rev_quarters = _ttm_and_quarters(revenue_chart)
    result["fees_ttm_usd"] = fees_ttm
    result["revenue_ttm_usd"] = revenue_ttm
    result["revenue_quarters_present"] = rev_quarters
    return result


def compute_ccxt_volume_check(ccxt_client, coin: UniverseCoin, usd_to_aud_rate: Optional[float]) -> tuple[Optional[str], Optional[float], Optional[str]]:
    """Cross-checks CoinGecko's 30d avg volume against ccxt (Kraken/Binance)
    OHLCV volume for the coin's USD pair, where one exists. Never overrides
    the CoinGecko-derived figure used elsewhere -- purely an additional,
    cited data point and a data-quality flag on large discrepancies."""
    if ccxt_client is None:
        return None, None, None
    rows = ccxt_client.daily_ohlcv(coin.symbol, quote="USD", days=45)
    if not rows or len(rows) < 5:
        return ccxt_client.exchange_id, None, None
    recent = rows[-30:] if len(rows) >= 30 else rows
    # ccxt OHLCV volume (index 5) is in BASE-asset units (e.g. BTC traded), not USD
    # notional -- multiply by the day's close to get USD volume before averaging.
    avg_volume_usd = sum(r[5] * r[4] for r in recent) / len(recent)
    note = None
    if usd_to_aud_rate and coin.avg_volume_30d_aud:
        cg_volume_usd = coin.avg_volume_30d_aud / usd_to_aud_rate
        if cg_volume_usd > 0:
            ratio = avg_volume_usd / cg_volume_usd
            if ratio > 5 or ratio < 0.2:
                note = f"ccxt {ccxt_client.exchange_id} 30d avg volume ${avg_volume_usd:,.0f} vs CoinGecko-derived ${cg_volume_usd:,.0f} (ratio {ratio:.2f}x)"
                log_data_quality(coin.coin_id, ccxt_client.exchange_id, "volume_cross_check", note)
    return ccxt_client.exchange_id, avg_volume_usd, note


def compute_metrics_for_coin(
    coin: UniverseCoin,
    btc_prices: list[float],
    cg: CoinGeckoClient,
    defillama: DefiLlamaClient,
    config: dict,
    usd_to_aud_rate: Optional[float],
    ccxt_client=None,
) -> CoinMetrics:
    m = CoinMetrics(coin_id=coin.coin_id)

    if coin.max_supply and coin.price_aud and coin.circulating_supply:
        m.fully_diluted_valuation_aud = coin.price_aud * coin.max_supply
        m.supply_ratio = coin.circulating_supply / coin.max_supply if coin.max_supply else None
    else:
        log_data_quality(coin.coin_id, "coingecko", "max_supply", "no max supply -> FDV/supply ratio N/A")

    m.annual_supply_inflation_pct, inflation_available = compute_supply_inflation(cg, coin)
    if not inflation_available:
        log_data_quality(coin.coin_id, "coingecko", "supply_inflation", "annual inflation unavailable")

    m.unlock_risk_flag, m.unlock_data_available = compute_unlock_risk(defillama, coin, config)

    _, volumes = _series(coin.daily_volumes)
    if len(volumes) >= 30:
        m.avg_volume_30d_aud = float(np.mean(volumes[-30:]))
    if len(volumes) >= 90:
        m.avg_volume_90d_aud = float(np.mean(volumes[-90:]))
    if m.avg_volume_30d_aud and coin.market_cap_aud:
        m.volume_to_mcap_ratio = m.avg_volume_30d_aud / coin.market_cap_aud

    fee_data = compute_fees_and_revenue(defillama, coin, config)
    m.fees_ttm_usd = fee_data["fees_ttm_usd"]
    m.revenue_ttm_usd = fee_data["revenue_ttm_usd"]
    m.revenue_quarters_present = fee_data["revenue_quarters_present"]
    if usd_to_aud_rate and coin.market_cap_aud:
        if m.fees_ttm_usd:
            m.price_to_fees = coin.market_cap_aud / (m.fees_ttm_usd * usd_to_aud_rate)
        if m.revenue_ttm_usd:
            m.price_to_revenue = coin.market_cap_aud / (m.revenue_ttm_usd * usd_to_aud_rate)

    _, prices = _series(coin.daily_prices)
    prices_list = prices.tolist()
    m.volatility_30d_annualized_pct = annualized_volatility_pct(prices_list, 30)
    m.volatility_90d_annualized_pct = annualized_volatility_pct(prices_list, 90)
    m.volatility_365d_annualized_pct = annualized_volatility_pct(prices_list, 365)
    m.max_drawdown_pct = max_drawdown_pct(prices_list)
    m.sma_50 = sma(prices_list, 50)
    m.sma_200 = sma(prices_list, 200)
    if prices_list:
        window_365 = prices_list[-365:] if len(prices_list) > 365 else prices_list
        m.week52_high = max(window_365)
        m.week52_low = min(window_365)

    if coin.ath_date:
        try:
            ath_dt = datetime.fromisoformat(coin.ath_date.replace("Z", "+00:00"))
            m.days_since_ath = (datetime.now(timezone.utc) - ath_dt).days
        except ValueError:
            log_data_quality(coin.coin_id, "coingecko", "ath_date", f"unparseable ath_date: {coin.ath_date}")
    if coin.ath_aud and coin.price_aud:
        m.pct_below_ath = (coin.price_aud - coin.ath_aud) / coin.ath_aud * 100

    m.correlation_to_btc_2y, m.beta_to_btc_2y = correlation_and_beta(prices_list, btc_prices)

    m.top_exchange_volume_share_pct, m.exchange_concentration_flag = compute_exchange_concentration(cg, coin, config)

    m.ccxt_exchange, m.ccxt_avg_volume_30d_usd, m.ccxt_volume_cross_check = compute_ccxt_volume_check(ccxt_client, coin, usd_to_aud_rate)

    return m
