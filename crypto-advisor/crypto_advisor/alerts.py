"""Email delivery: instant high-priority alerts (with a cooldown so the same
alert doesn't repeat) and the two daily digests. All email is best-effort --
missing SMTP config disables it and logs why, it never crashes the pipeline.
"""
from __future__ import annotations

import json
import smtplib
from dataclasses import dataclass
from datetime import datetime
from email.mime.text import MIMEText
from pathlib import Path
from zoneinfo import ZoneInfo

from .config import PROJECT_ROOT, Env
from .logutil import get_logger
from .report import ReportContext

logger = get_logger(__name__)

DATA_DIR = PROJECT_ROOT / "data"
COOLDOWN_PATH = DATA_DIR / "alert_cooldowns.json"
DIGEST_MARKER_PATH = DATA_DIR / "digest_last_sent.json"


@dataclass
class CooldownStore:
    last_sent: dict[str, str]  # f"{coin_id}:{alert_type}" -> ISO timestamp

    @classmethod
    def load(cls) -> "CooldownStore":
        if COOLDOWN_PATH.exists():
            try:
                return cls(json.loads(COOLDOWN_PATH.read_text()))
            except json.JSONDecodeError:
                logger.warning("alert_cooldowns.json corrupt, resetting")
        return cls({})

    def save(self) -> None:
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        COOLDOWN_PATH.write_text(json.dumps(self.last_sent, indent=2))

    def should_fire(self, coin_id: str, alert_type: str, cooldown_minutes: int, now: datetime) -> bool:
        key = f"{coin_id}:{alert_type}"
        last = self.last_sent.get(key)
        if last is None:
            return True
        last_dt = datetime.fromisoformat(last)
        return (now - last_dt).total_seconds() >= cooldown_minutes * 60

    def record(self, coin_id: str, alert_type: str, now: datetime) -> None:
        self.last_sent[f"{coin_id}:{alert_type}"] = now.isoformat()


def send_email(subject: str, body: str, env: Env) -> bool:
    if not env.email_enabled:
        logger.info("Email not configured (missing SMTP_HOST/USER/PASSWORD/TO) -- skipping: %s", subject)
        return False
    try:
        msg = MIMEText(body)
        msg["Subject"] = subject
        msg["From"] = env.smtp_from or env.smtp_user
        msg["To"] = env.smtp_to
        with smtplib.SMTP(env.smtp_host, env.smtp_port, timeout=20) as server:
            server.starttls()
            server.login(env.smtp_user, env.smtp_password)
            server.sendmail(msg["From"], [env.smtp_to], msg.as_string())
        logger.info("Sent email: %s", subject)
        return True
    except (smtplib.SMTPException, OSError) as exc:
        logger.warning("Failed to send email '%s': %s", subject, exc)
        return False


def check_instant_alerts(ctx: ReportContext, previous_actions: dict[str, dict], env: Env, config: dict, store: CooldownStore) -> list[str]:
    """Returns messages sent (for logging/testing); applies cooldowns per (coin, alert_type)."""
    acfg = config["alerts"]
    holding_ids = ctx.portfolio.holding_ids()
    now = ctx.fetch_time
    sent = []

    for a in ctx.final_actions:
        if a.coin_id not in holding_ids:
            continue

        prev = previous_actions.get(a.coin_id)
        if prev and prev.get("action") != a.action and store.should_fire(a.coin_id, "action_change", acfg["cooldown_minutes"], now):
            msg = f"[Action change] {a.coin_id}: {prev.get('action')} -> {a.action} (score {a.score:.2f}, {a.confidence} confidence)"
            if send_email(f"Crypto advisor: {a.coin_id} action changed to {a.action}", msg, env):
                store.record(a.coin_id, "action_change", now)
                sent.append(msg)

        if a.stop_price_aud and a.entry_price_aud and a.entry_price_aud <= a.stop_price_aud and store.should_fire(a.coin_id, "stop_hit", acfg["cooldown_minutes"], now):
            msg = f"[Stop hit] {a.coin_id}: price A${a.entry_price_aud:,.4f} <= stop A${a.stop_price_aud:,.4f}"
            if send_email(f"Crypto advisor: {a.coin_id} stop-loss hit", msg, env):
                store.record(a.coin_id, "stop_hit", now)
                sent.append(msg)

    coin_by_id = {c.coin_id: c for c in ctx.universe}
    for coin_id in holding_ids:
        coin = coin_by_id.get(coin_id)
        if not coin or coin.price_change_pct_24h is None:
            continue
        if abs(coin.price_change_pct_24h) >= acfg["holding_move_pct_threshold"] and store.should_fire(coin_id, "big_move", acfg["cooldown_minutes"], now):
            msg = f"[Big move] {coin_id} moved {coin.price_change_pct_24h:+.1f}% in 24h (A${coin.price_aud:,.4f})"
            if send_email(f"Crypto advisor: {coin_id} moved {coin.price_change_pct_24h:+.1f}%", msg, env):
                store.record(coin_id, "big_move", now)
                sent.append(msg)

    store.save()
    return sent


def _load_digest_markers() -> dict:
    if DIGEST_MARKER_PATH.exists():
        try:
            return json.loads(DIGEST_MARKER_PATH.read_text())
        except json.JSONDecodeError:
            return {}
    return {}


def _save_digest_markers(markers: dict) -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    DIGEST_MARKER_PATH.write_text(json.dumps(markers, indent=2))


def maybe_send_digests(ctx: ReportContext, env: Env, config: dict) -> list[str]:
    """Fires the 8am Sydney and end-of-US-session digests at most once per day
    each, tracked via a marker file so restarts don't duplicate."""
    gcfg = config["general"]
    sydney = ZoneInfo(gcfg["timezone"])
    us = ZoneInfo(gcfg["us_session_close_timezone"])
    now_sydney = ctx.fetch_time.astimezone(sydney)
    now_us = ctx.fetch_time.astimezone(us)
    markers = _load_digest_markers()
    sent = []

    if now_sydney.hour >= gcfg["digest_hour_sydney"] and markers.get("morning") != now_sydney.date().isoformat():
        body = _digest_body(ctx, "Morning digest (8am Sydney)")
        if send_email("Crypto advisor: morning digest", body, env):
            markers["morning"] = now_sydney.date().isoformat()
            sent.append("morning")

    if now_us.hour >= gcfg["us_session_close_hour"] and markers.get("us_close") != now_us.date().isoformat():
        body = _digest_body(ctx, "End-of-US-session digest")
        if send_email("Crypto advisor: end-of-US-session digest", body, env):
            markers["us_close"] = now_us.date().isoformat()
            sent.append("us_close")

    if sent:
        _save_digest_markers(markers)
    return sent


def _digest_body(ctx: ReportContext, title: str) -> str:
    lines = [title, f"Data as of {ctx.fetch_time.isoformat()}", ""]
    lines.append("Top insights:")
    for i in ctx.insights[:5]:
        lines.append(f"- {i.message}")
    lines.append("\nActions on your holdings/watchlist:")
    holding_ids = ctx.portfolio.holding_ids() | set(ctx.portfolio.watchlist)
    for a in ctx.final_actions:
        if a.coin_id in holding_ids:
            lines.append(f"- {a.coin_id}: {a.action} ({a.confidence} confidence)")
    lines.append("\nRule-based research output. Not financial advice.")
    return "\n".join(lines)
