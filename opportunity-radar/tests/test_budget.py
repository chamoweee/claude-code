"""The budget guard must refuse spend *before* it happens, not report it after."""

from __future__ import annotations

import pytest

from radar.budget import BudgetExhausted, BudgetGuard, Usage, cost_usd, month_key
from radar.config import load_settings
from radar.db import connect


@pytest.fixture
def conn(tmp_path):
    connection = connect(tmp_path / "test.db")
    yield connection
    connection.close()


@pytest.fixture
def settings():
    return load_settings()


@pytest.fixture
def guard(conn, settings):
    return BudgetGuard(conn, settings, "2026-09-21")


def test_month_key_uses_the_sydney_date(guard):
    assert month_key("2026-09-21") == "2026-09"
    assert guard.month == "2026-09"


def test_cost_is_priced_per_million_tokens(settings):
    pricing = settings.pricing_for("claude-sonnet-5")
    usage = Usage(input_tokens=1_000_000, output_tokens=1_000_000)
    assert cost_usd(usage, pricing) == pytest.approx(12.0)  # $2 in + $10 out


def test_web_searches_are_priced_per_thousand(settings):
    pricing = settings.pricing_for("claude-sonnet-5")
    assert cost_usd(Usage(web_searches=25), pricing) == pytest.approx(0.25)


def test_cache_reads_are_cheaper_than_fresh_input(settings):
    pricing = settings.pricing_for("claude-sonnet-5")
    fresh = cost_usd(Usage(input_tokens=500_000), pricing)
    cached = cost_usd(Usage(cache_read_tokens=500_000), pricing)
    assert cached < fresh


def test_usage_from_response_reads_the_sdk_shape():
    class ServerToolUse:
        web_search_requests = 7

    class SDKUsage:
        input_tokens = 100
        output_tokens = 200
        cache_read_input_tokens = 300
        cache_creation_input_tokens = 400
        server_tool_use = ServerToolUse()

    usage = Usage.from_response(SDKUsage())
    assert (usage.input_tokens, usage.output_tokens) == (100, 200)
    assert (usage.cache_read_tokens, usage.cache_write_tokens) == (300, 400)
    assert usage.web_searches == 7


def test_usage_from_response_tolerates_missing_fields():
    class Bare:
        input_tokens = 10

    usage = Usage.from_response(Bare())
    assert usage.input_tokens == 10
    assert usage.web_searches == 0


def test_usage_adds():
    total = Usage(1, 2, 3, 4, 5) + Usage(10, 20, 30, 40, 50)
    assert total == Usage(11, 22, 33, 44, 55)


# --- the gate itself --------------------------------------------------------


def test_check_passes_when_the_month_is_empty(guard):
    status = guard.check(estimated_aud=3.0)
    assert status.spent_aud == 0.0
    assert not status.exhausted


def test_check_raises_once_the_cap_is_reached(guard, conn):
    conn.execute(
        "INSERT INTO spend (at, month, model, cost_usd, cost_aud) "
        "VALUES ('2026-09-10T00:00:00+00:00', '2026-09', 'claude-sonnet-5', 20.0, 30.0)"
    )
    conn.commit()
    with pytest.raises(BudgetExhausted) as excinfo:
        guard.check()
    assert excinfo.value.spent_aud == pytest.approx(30.0)
    assert "2026-09" in str(excinfo.value)


def test_check_refuses_a_call_that_would_breach_the_cap(guard, conn):
    """$28 spent, $1 reserve, so a $2 call must be refused before it is made."""
    conn.execute(
        "INSERT INTO spend (at, month, model, cost_usd, cost_aud) "
        "VALUES ('2026-09-10T00:00:00+00:00', '2026-09', 'claude-sonnet-5', 18.0, 28.0)"
    )
    conn.commit()
    with pytest.raises(BudgetExhausted):
        guard.check(estimated_aud=2.0)
    guard.check(estimated_aud=0.5)  # fits under the $29 ceiling; must not raise


def test_spend_in_another_month_does_not_count(guard, conn):
    conn.execute(
        "INSERT INTO spend (at, month, model, cost_usd, cost_aud) "
        "VALUES ('2026-08-10T00:00:00+00:00', '2026-08', 'claude-sonnet-5', 20.0, 30.0)"
    )
    conn.commit()
    assert guard.status().spent_aud == 0.0
    guard.check(estimated_aud=5.0)


# --- ledger writing ---------------------------------------------------------


def test_record_writes_a_row_and_converts_to_aud(guard, settings, conn):
    aud = guard.record(Usage(input_tokens=1_000_000), purpose="weekly_macro")
    expected = 2.0 * settings.budget.usd_to_aud
    assert aud == pytest.approx(expected)
    row = conn.execute("SELECT * FROM spend").fetchone()
    assert row["purpose"] == "weekly_macro"
    assert row["month"] == "2026-09"
    assert row["cost_usd"] == pytest.approx(2.0)


def test_recorded_spend_feeds_straight_back_into_the_gate(guard):
    for _ in range(3):
        guard.record(Usage(output_tokens=1_000_000), purpose="discovery")
    assert guard.status().spent_aud > 0
    assert guard.status().spent_aud == pytest.approx(3 * 10.0 * 1.52)


def test_warning_fires_at_eighty_percent(guard, conn):
    assert guard.warning() is None
    conn.execute(
        "INSERT INTO spend (at, month, model, cost_usd, cost_aud) "
        "VALUES ('2026-09-10T00:00:00+00:00', '2026-09', 'claude-sonnet-5', 16.0, 25.0)"
    )
    conn.commit()
    assert "83%" in guard.warning()


def test_month_breakdown_groups_by_purpose(guard):
    guard.record(Usage(output_tokens=100_000), purpose="macro")
    guard.record(Usage(output_tokens=900_000), purpose="discovery")
    rows = guard.month_breakdown()
    assert [r["purpose"] for r in rows] == ["discovery", "macro"]


def test_unpriced_model_is_refused(settings):
    from radar.config import ConfigError

    with pytest.raises(ConfigError, match="No pricing configured"):
        settings.pricing_for("claude-imaginary-9")
