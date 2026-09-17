"""Builds the investable universe: full CoinGecko coin list/market data,
filtered down per config.yaml's `universe` section. Every excluded coin is
logged with its reason via `logutil.log_excluded` -- nothing is silently
dropped.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from .fetch import CoinGeckoClient
from .logutil import get_logger, log_data_quality, log_excluded

logger = get_logger(__name__)


@dataclass
class UniverseCoin:
    coin_id: str
    symbol: str
    name: str
    market_cap_aud: float
    price_aud: float
    volume_24h_aud: float
    price_change_pct_1h: float | None
    price_change_pct_24h: float | None
    price_change_pct_7d: float | None
    price_change_pct_30d: float | None
    ath_aud: float | None
    ath_date: str | None
    circulating_supply: float | None
    total_supply: float | None
    max_supply: float | None
    avg_volume_30d_aud: float | None = None
    price_history_days: int | None = None
    listed_exchanges: list[str] = field(default_factory=list)
    daily_prices: list[tuple[int, float]] = field(default_factory=list)  # (ts_ms, price) in vs_currency, for metrics
    daily_volumes: list[tuple[int, float]] = field(default_factory=list)  # (ts_ms, volume) in vs_currency


def _fetch_excluded_category_ids(cg: CoinGeckoClient, vs_currency: str, categories: list[str]) -> dict[str, str]:
    """Returns {coin_id: category} for every coin CoinGecko tags into one of
    the excluded categories (stablecoins, wrapped tokens, LSDs, ...)."""
    excluded: dict[str, str] = {}
    for category in categories:
        page = 1
        while True:
            rows = cg.coins_markets(vs_currency=vs_currency, category=category, page=page, per_page=250)
            if not rows:
                break
            for row in rows:
                excluded.setdefault(row["id"], category)
            if len(rows) < 250:
                break
            page += 1
    return excluded


def _is_major_exchange_listed(tickers: list[dict], major_exchanges: list[str]) -> list[str]:
    listed = set()
    majors_lower = [m.lower() for m in major_exchanges]
    for t in tickers:
        market_name = (t.get("market") or {}).get("name", "")
        if any(m in market_name.lower() for m in majors_lower):
            listed.add(market_name)
    return sorted(listed)


def build_universe(cg: CoinGeckoClient, config: dict) -> tuple[list[UniverseCoin], list[dict]]:
    """Returns (investable_universe, movers_candidate_pool). The second element
    is the wider set of raw CoinGecko market rows (stablecoins/wrapped/LSD
    already excluded, but not yet cap/volume/history/exchange filtered) used
    by movers.py so thin/small coins can still show up in the report."""
    ucfg = config["universe"]
    vs_currency = config["general"]["vs_currency"]

    logger.info("Fetching excluded-category coin ids...")
    excluded_by_category = _fetch_excluded_category_ids(cg, vs_currency, ucfg["excluded_categories"])

    logger.info("Fetching candidate market data (top %d by market cap)...", ucfg["max_coins_scanned"])
    candidates: list[dict] = []
    per_page = 250
    pages = (ucfg["max_coins_scanned"] + per_page - 1) // per_page
    for page in range(1, pages + 1):
        rows = cg.coins_markets(vs_currency=vs_currency, page=page, per_page=per_page)
        if not rows:
            break
        candidates.extend(rows)
        if len(rows) < per_page:
            break
    candidates = candidates[: ucfg["max_coins_scanned"]]

    denylist = {s.lower() for s in ucfg["excluded_symbol_denylist"]}

    # stage0: only the "never investable" category/denylist exclusions are applied.
    # This broader pool (still excludes stablecoins/wrapped/LSD tokens, but keeps
    # small/thin coins) is what movers.py scans for top movers and high-risk movers --
    # the movers universe is intentionally wider than the fully-filtered investable one.
    stage0: list[dict] = []
    for row in candidates:
        coin_id = row["id"]
        symbol = (row.get("symbol") or "").lower()
        if coin_id in excluded_by_category:
            log_excluded(coin_id, symbol, f"excluded_category:{excluded_by_category[coin_id]}")
            continue
        if symbol in denylist:
            log_excluded(coin_id, symbol, "excluded_symbol_denylist")
            continue
        if row.get("market_cap") is None:
            log_excluded(coin_id, symbol, "missing_market_cap")
            continue
        if row.get("current_price") is None:
            log_excluded(coin_id, symbol, "missing_price")
            continue
        stage0.append(row)

    stage1: list[dict] = []
    for row in stage0:
        coin_id = row["id"]
        symbol = (row.get("symbol") or "").lower()
        market_cap = row["market_cap"]
        if market_cap < ucfg["min_market_cap_aud"]:
            log_excluded(coin_id, symbol, "below_min_market_cap", market_cap, ucfg["min_market_cap_aud"])
            continue
        stage1.append(row)

    logger.info("%d coins passed cheap filters, checking history/volume/exchange listing...", len(stage1))

    universe: list[UniverseCoin] = []
    for row in stage1:
        coin = _build_coin_from_row(cg, row, vs_currency, ucfg["major_exchanges"])
        if coin is None:
            log_excluded(row["id"], (row.get("symbol") or "").lower(), "missing_price_history")
            continue
        if coin.price_history_days < ucfg["min_price_history_days"]:
            log_excluded(coin.coin_id, coin.symbol, "insufficient_price_history_days", coin.price_history_days,
                         ucfg["min_price_history_days"])
            continue
        if coin.avg_volume_30d_aud is None:
            log_excluded(coin.coin_id, coin.symbol, "missing_volume_history")
            continue
        if coin.avg_volume_30d_aud < ucfg["min_avg_daily_volume_aud_30d"]:
            log_excluded(coin.coin_id, coin.symbol, "below_min_avg_volume_30d", round(coin.avg_volume_30d_aud, 2),
                         ucfg["min_avg_daily_volume_aud_30d"])
            continue
        if not coin.listed_exchanges:
            log_excluded(coin.coin_id, coin.symbol, "not_on_major_exchange")
            continue
        universe.append(coin)

    logger.info("Universe built: %d coins passed all filters", len(universe))
    return universe, stage0


def _build_coin_from_row(cg: CoinGeckoClient, row: dict, vs_currency: str, major_exchanges: list[str]) -> UniverseCoin | None:
    """Fetches history/volume/exchange data for one CoinGecko market row and
    builds a `UniverseCoin`, without applying any threshold filters. Returns
    None only if CoinGecko has no price history at all for the coin."""
    coin_id = row["id"]
    symbol = (row.get("symbol") or "").lower()

    chart = cg.coin_market_chart(coin_id, vs_currency, days="max")
    if not chart or not chart.get("prices"):
        return None
    prices = chart["prices"]
    span_days = (prices[-1][0] - prices[0][0]) / 86_400_000
    volumes = chart.get("total_volumes", [])
    recent_volumes = [v for _, v in volumes[-30:]] if volumes else []
    avg_volume_30d = sum(recent_volumes) / len(recent_volumes) if recent_volumes else None
    if avg_volume_30d is None:
        log_data_quality(coin_id, "coingecko", "total_volumes", "no volume series in market_chart")

    tickers = cg.coin_tickers(coin_id)
    listed = _is_major_exchange_listed(tickers, major_exchanges)

    return UniverseCoin(
        coin_id=coin_id,
        symbol=symbol,
        name=row.get("name", coin_id),
        market_cap_aud=row.get("market_cap"),
        price_aud=row.get("current_price"),
        volume_24h_aud=row.get("total_volume"),
        price_change_pct_1h=row.get("price_change_percentage_1h_in_currency"),
        price_change_pct_24h=row.get("price_change_percentage_24h_in_currency"),
        price_change_pct_7d=row.get("price_change_percentage_7d_in_currency"),
        price_change_pct_30d=row.get("price_change_percentage_30d_in_currency"),
        ath_aud=row.get("ath"),
        ath_date=row.get("ath_date"),
        circulating_supply=row.get("circulating_supply"),
        total_supply=row.get("total_supply"),
        max_supply=row.get("max_supply"),
        avg_volume_30d_aud=avg_volume_30d,
        price_history_days=round(span_days),
        listed_exchanges=listed,
        daily_prices=[(int(ts), p) for ts, p in prices],
        daily_volumes=[(int(ts), v) for ts, v in volumes],
    )


def fetch_forced_coin(cg: CoinGeckoClient, coin_id: str, vs_currency: str, major_exchanges: list[str]) -> UniverseCoin | None:
    """Used for portfolio holdings/watchlist coins that may have fallen out of
    the top-N scan or would fail universe filters -- we still need to advise
    on them. Returns None if CoinGecko no longer has market data for the id
    at all (a strong signal the coin may be delisted/defunct)."""
    rows = cg.coins_markets(vs_currency=vs_currency, ids=[coin_id], per_page=1)
    if not rows:
        log_data_quality(coin_id, "coingecko", "coins_markets", "no market data returned -- possible delisting")
        return None
    return _build_coin_from_row(cg, rows[0], vs_currency, major_exchanges)
