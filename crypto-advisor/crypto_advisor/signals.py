"""Composite, transparent rules-based scoring -> one action per coin.

Score = w_fundamentals*F + w_valuation*V + w_trend*T + w_regime*R, each
component in [0,1], weights from config.yaml (`signals`). This module only
produces the *score-based* action; `risk.py` applies the hard gates
(classification eligibility, position caps, stops, fundamentals-broke) on
top and can only ever downgrade what's produced here.

Top-mover status is deliberately never an input to any component below --
see `tests/test_signals.py` for the regression test on that rule.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from .classify import Classification
from .metrics import CoinMetrics
from .universe import UniverseCoin

BUY, ADD, HOLD, TRIM, SELL, WATCH = "BUY", "ADD", "HOLD", "TRIM", "SELL", "WATCH"


@dataclass
class SignalResult:
    coin_id: str
    action: str
    score: float
    confidence: str
    component_scores: dict
    reasons: list[str] = field(default_factory=list)


def fundamentals_score(classification: Classification, metrics: CoinMetrics, config: dict) -> tuple[float, list[str]]:
    base_by_tier = {"core": 0.9, "revenue-generating": 0.65, "speculative": 0.3}
    score = base_by_tier[classification.tier]
    reasons = [f"classification={classification.tier} (base fundamentals score {score:.2f})"]

    if metrics.annual_supply_inflation_pct is not None:
        penalty = min(max(metrics.annual_supply_inflation_pct, 0), 20) / 20 * 0.2
        score -= penalty
        reasons.append(f"annual supply inflation {metrics.annual_supply_inflation_pct:.2f}% (-{penalty:.2f})")
    else:
        reasons.append("annual supply inflation unavailable (no adjustment)")

    if metrics.unlock_risk_flag:
        score -= 0.15
        reasons.append("large token unlock (>=threshold of supply) within 30 days (-0.15)")

    if metrics.revenue_quarters_present is not None and metrics.revenue_quarters_present >= 6:
        score += 0.05
        reasons.append(f"revenue present {metrics.revenue_quarters_present}/8 trailing quarters (+0.05)")

    return max(0.0, min(1.0, score)), reasons


def valuation_score(metrics: CoinMetrics, peer_price_to_fees_median: Optional[float], pct_below_ath: Optional[float]) -> tuple[float, list[str]]:
    if metrics.price_to_fees is not None and peer_price_to_fees_median:
        ratio = metrics.price_to_fees / peer_price_to_fees_median
        score = max(0.0, min(1.0, 1 - (ratio - 1)))
        reasons = [f"price-to-fees {metrics.price_to_fees:.1f} vs peer median {peer_price_to_fees_median:.1f} "
                   f"(ratio {ratio:.2f}) -> valuation score {score:.2f}"]
        return score, reasons
    if pct_below_ath is not None:
        score = max(0.0, min(1.0, abs(pct_below_ath) / 80))
        reasons = [f"no fees-based valuation available; using {abs(pct_below_ath):.1f}% drawdown from ATH as proxy "
                   f"-> valuation score {score:.2f}"]
        return score, reasons
    return 0.5, ["no valuation data available (fees or ATH) -- neutral 0.50 default"]


def trend_score(coin: UniverseCoin, metrics: CoinMetrics) -> tuple[float, list[str]]:
    score = 0.0
    reasons = []
    if metrics.sma_50 is not None and coin.price_aud is not None:
        if coin.price_aud > metrics.sma_50:
            score += 0.4
            reasons.append(f"price A${coin.price_aud:,.4f} > SMA50 A${metrics.sma_50:,.4f} (+0.40)")
        else:
            reasons.append(f"price A${coin.price_aud:,.4f} <= SMA50 A${metrics.sma_50:,.4f} (+0.00)")
    else:
        reasons.append("SMA50 unavailable (+0.00)")
    if metrics.sma_200 is not None and coin.price_aud is not None:
        if coin.price_aud > metrics.sma_200:
            score += 0.4
            reasons.append(f"price A${coin.price_aud:,.4f} > SMA200 A${metrics.sma_200:,.4f} (+0.40)")
        else:
            reasons.append(f"price A${coin.price_aud:,.4f} <= SMA200 A${metrics.sma_200:,.4f} (+0.00)")
    else:
        reasons.append("SMA200 unavailable (+0.00)")
    if metrics.sma_50 is not None and metrics.sma_200 is not None and metrics.sma_50 > metrics.sma_200:
        score += 0.2
        reasons.append("SMA50 > SMA200 (golden-cross state) (+0.20)")
    return max(0.0, min(1.0, score)), reasons


def regime_score(btc_above_200sma: Optional[bool]) -> tuple[float, list[str]]:
    if btc_above_200sma is None:
        return 0.5, ["BTC regime unknown (SMA200 unavailable) -- neutral 0.50 default"]
    if btc_above_200sma:
        return 0.75, ["BTC trading above its 200-day moving average -- bullish regime (0.75)"]
    return 0.35, ["BTC trading below its 200-day moving average -- bearish regime (0.35)"]


def _action_from_score(score: float, held: bool, config: dict) -> str:
    scfg = config["signals"]
    if score >= scfg["buy_score_threshold"]:
        return ADD if held else BUY
    if score >= scfg["add_score_threshold"]:
        return ADD if held else WATCH
    if score >= scfg["trim_score_threshold"]:
        return HOLD if held else WATCH
    if score >= scfg["sell_score_threshold"]:
        return TRIM if held else WATCH
    return SELL if held else WATCH


def _confidence(score: float, completeness: float, config: dict) -> str:
    scfg = config["signals"]
    thresholds = [scfg["buy_score_threshold"], scfg["add_score_threshold"], scfg["trim_score_threshold"], scfg["sell_score_threshold"]]
    margin = min(abs(score - t) for t in thresholds)
    if completeness < config["risk"]["min_confidence_data_completeness"]:
        return "low"
    if margin >= 0.15:
        return "high"
    if margin >= 0.07:
        return "medium"
    return "low"


def score_coin(
    coin: UniverseCoin,
    metrics: CoinMetrics,
    classification: Classification,
    held: bool,
    btc_above_200sma: Optional[bool],
    peer_price_to_fees_median: Optional[float],
    config: dict,
) -> SignalResult:
    scfg = config["signals"]

    f_score, f_reasons = fundamentals_score(classification, metrics, config)
    v_score, v_reasons = valuation_score(metrics, peer_price_to_fees_median, metrics.pct_below_ath)
    t_score, t_reasons = trend_score(coin, metrics)
    r_score, r_reasons = regime_score(btc_above_200sma)

    composite = (
        scfg["weight_fundamentals"] * f_score
        + scfg["weight_valuation"] * v_score
        + scfg["weight_trend"] * t_score
        + scfg["weight_regime"] * r_score
    )

    completeness_fields = [
        metrics.annual_supply_inflation_pct, metrics.revenue_quarters_present, metrics.price_to_fees,
        metrics.beta_to_btc_2y, metrics.sma_50, metrics.sma_200,
    ]
    completeness = sum(1 for f in completeness_fields if f is not None) / len(completeness_fields)

    action = _action_from_score(composite, held, config)
    confidence = _confidence(composite, completeness, config)

    reasons = (
        [f"composite score {composite:.3f} "
         f"(fundamentals {f_score:.2f}*{scfg['weight_fundamentals']} + valuation {v_score:.2f}*{scfg['weight_valuation']} "
         f"+ trend {t_score:.2f}*{scfg['weight_trend']} + regime {r_score:.2f}*{scfg['weight_regime']})"]
        + f_reasons + v_reasons + t_reasons + r_reasons
    )

    return SignalResult(
        coin_id=coin.coin_id,
        action=action,
        score=round(composite, 4),
        confidence=confidence,
        component_scores={"fundamentals": f_score, "valuation": v_score, "trend": t_score, "regime": r_score},
        reasons=reasons,
    )
