"""Scoring, the Claude client, and the engine that ties them together.

No test here makes a network call. The client is exercised against a fake SDK
that returns canned messages, so the budget gating, JSON extraction, repair path
and web-search error handling are all covered at zero cost.
"""

from __future__ import annotations

import json

import pytest

from radar.budget import BudgetExhausted, BudgetGuard, Usage
from radar.config import load_settings
from radar.db import connect
from radar.research import client as client_mod
from radar.research import engine, scoring
from radar.research.client import ResearchClient, ResearchError, extract_json, render
from radar.research.schemas import SCORE_FIELDS, Evidence, Opportunity, SubScores
from radar.runlog import start_run
from radar.seed_baseline import seed

TODAY = "2026-09-21"


# ---------------------------------------------------------------------------
# Fake SDK
# ---------------------------------------------------------------------------


class FakeBlock:
    def __init__(self, type_: str, **kwargs):
        self.type = type_
        for key, value in kwargs.items():
            setattr(self, key, value)


class FakeUsage:
    def __init__(self, input_tokens=5_000, output_tokens=2_000, searches=0):
        self.input_tokens = input_tokens
        self.output_tokens = output_tokens
        self.cache_read_input_tokens = 0
        self.cache_creation_input_tokens = 0
        self.server_tool_use = type("S", (), {"web_search_requests": searches})()


class FakeMessage:
    def __init__(self, text: str, searches: int = 0, search_errors: list | None = None):
        self.content = [FakeBlock("text", text=text)]
        for _ in range(searches):
            self.content.append(FakeBlock("web_search_tool_result", content=[{"url": "x"}]))
        for error in search_errors or []:
            self.content.append(
                FakeBlock("web_search_tool_result", content={"error_code": error}))
        self.usage = FakeUsage(searches=searches)


class FakeStream:
    def __init__(self, message):
        self._message = message

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def get_final_message(self):
        return self._message


class FakeMessages:
    def __init__(self, responses):
        self._responses = list(responses)
        self.calls = []

    def stream(self, **kwargs):
        self.calls.append(kwargs)
        if not self._responses:
            raise AssertionError("fake SDK ran out of canned responses")
        return FakeStream(self._responses.pop(0))


class FakeAnthropic:
    def __init__(self, *responses):
        self.messages = FakeMessages(responses)


@pytest.fixture
def settings(tmp_path):
    return load_settings(db_path=tmp_path / "test.db")


@pytest.fixture
def conn(settings):
    connection = connect(settings.db_path)
    yield connection
    connection.close()


@pytest.fixture
def run(conn):
    return start_run(conn, "weekly", TODAY)


@pytest.fixture
def guard(conn, settings, run):
    return BudgetGuard(conn, settings, TODAY, run_id=run.id)


def make_client(settings, guard, run, *responses):
    return ResearchClient(settings, guard, run, client=FakeAnthropic(*responses))


# ---------------------------------------------------------------------------
# Scoring
# ---------------------------------------------------------------------------


def make_opportunity(*, strength="primary", individual="Contributors report $85/hr",
                     **score_overrides):
    scores = {name: 8 for name in SCORE_FIELDS}
    scores.update(score_overrides)
    return Opportunity(
        slug="x", title="X", summary="", who_earns="",
        platform_revenue_evidence="Platform revenue $2B",
        individual_earnings_evidence=individual,
        startup_cost_aud_min=0, startup_cost_aud_max=100,
        time_to_first_dollar_days=7, skills_required="", saturation="",
        red_flags="", au_eligibility="",
        evidence=(Evidence("c", "n", "https://example.gov.au/x", "2026-09-01", strength),),
        scores=SubScores(**scores))


def test_weights_sum_to_one_and_cover_every_subscore():
    assert set(scoring.WEIGHTS) == set(SCORE_FIELDS)
    assert sum(scoring.WEIGHTS.values()) == pytest.approx(1.0)


def test_all_eights_totals_eight(settings):
    result = scoring.score_opportunity(make_opportunity(), settings.research, 6.0)
    assert result.total == pytest.approx(8.0)
    assert not result.was_capped


def test_evidence_is_the_heaviest_weight():
    assert scoring.WEIGHTS["evidence_strength"] == max(scoring.WEIGHTS.values())


def test_weak_sources_cap_the_total(settings):
    result = scoring.score_opportunity(make_opportunity(strength="weak"),
                                       settings.research, 6.0)
    assert result.raw_total == pytest.approx(8.0)
    assert result.total == pytest.approx(settings.research.weak_source_score_cap)
    assert "no source better than a blog" in result.capped_reason


def test_no_individual_earnings_evidence_caps_the_total(settings):
    """The brief's central distinction, enforced as arithmetic."""
    result = scoring.score_opportunity(make_opportunity(individual=""),
                                       settings.research, 6.0)
    assert result.raw_total == pytest.approx(8.0)
    assert result.total == pytest.approx(6.0)
    assert "platform earns, not that individuals do" in result.capped_reason


def test_both_caps_can_apply_and_the_lower_wins(settings):
    result = scoring.score_opportunity(make_opportunity(strength="weak", individual=""),
                                       settings.research, 6.0)
    assert result.total == pytest.approx(settings.research.weak_source_score_cap)
    assert result.capped_reason.count("capped at") == 2


def test_a_cap_does_not_raise_a_low_score(settings):
    low = make_opportunity(strength="weak", **{name: 2 for name in SCORE_FIELDS})
    result = scoring.score_opportunity(low, settings.research, 6.0)
    assert result.total == pytest.approx(2.0)
    assert not result.was_capped


def test_low_risk_scores_high(settings):
    risky = scoring.score_opportunity(make_opportunity(risk=1), settings.research, 6.0)
    safe = scoring.score_opportunity(make_opportunity(risk=10), settings.research, 6.0)
    assert safe.total > risky.total


def test_ranking_is_by_capped_total(settings):
    strong_weak_source = make_opportunity(strength="weak")
    modest_primary = make_opportunity(**{name: 6 for name in SCORE_FIELDS})
    ranked = scoring.rank([strong_weak_source, modest_primary], settings.research, 6.0)
    assert ranked[0][1].total == pytest.approx(6.0), \
        "a modest well-sourced lead must outrank a great-sounding unsourced one"


def test_poor_fit_opportunities_go_to_their_own_section(settings):
    good_fit = make_opportunity(personal_fit=8)
    poor_fit = make_opportunity(personal_fit=2)
    scored = scoring.rank([good_fit, poor_fit], settings.research, 6.0)
    actionable, other = scoring.split_by_fit(scored, settings.research.personal_fit_threshold)
    assert len(actionable) == 1 and len(other) == 1
    assert other[0][0].scores.personal_fit == 2


def test_the_scoring_table_shows_the_working(settings):
    opportunity = make_opportunity()
    rows = scoring.format_scoring_table(
        opportunity, scoring.score_opportunity(opportunity, settings.research, 6.0))
    assert len(rows) == len(SCORE_FIELDS)
    assert all(isinstance(score, int) for _, score, _ in rows)


# ---------------------------------------------------------------------------
# JSON extraction
# ---------------------------------------------------------------------------


def test_extracts_bare_json():
    assert extract_json('{"a": 1}') == {"a": 1}


def test_extracts_from_a_code_fence():
    assert extract_json('Here you go:\n```json\n{"a": 1}\n```\nHope that helps')["a"] == 1


def test_extracts_json_surrounded_by_prose():
    assert extract_json('Sure thing. {"a": 1} Let me know.')["a"] == 1


def test_empty_response_raises():
    with pytest.raises(ResearchError, match="empty"):
        extract_json("   ")


def test_unparseable_response_raises():
    with pytest.raises(ResearchError, match="no JSON object"):
        extract_json("I could not complete this request.")


def test_render_rejects_unfilled_placeholders():
    with pytest.raises(ResearchError, match="unfilled placeholders"):
        render("Hello {{name}} from {{place}}", name="x")


# ---------------------------------------------------------------------------
# The client
# ---------------------------------------------------------------------------


def test_ask_parses_records_cost_and_counts_searches(settings, guard, run):
    client = make_client(settings, guard, run,
                         FakeMessage('{"themes": []}', searches=3))
    answer = client.ask(system="s", user="u", purpose="theme_update")
    assert answer.payload == {"themes": []}
    assert answer.searches == 3
    assert answer.cost_aud > 0
    assert guard.status().spent_aud == pytest.approx(answer.cost_aud)


def test_the_request_uses_adaptive_thinking_and_the_right_tool(settings, guard, run):
    client = make_client(settings, guard, run, FakeMessage('{"ok": 1}'))
    client.ask(system="s", user="u", purpose="p", max_searches=5, effort="high")
    sent = client.client.messages.calls[0]
    assert sent["model"] == "claude-sonnet-5"
    assert sent["thinking"] == {"type": "adaptive"}
    assert "budget_tokens" not in json.dumps(sent), "rejected with a 400 on Sonnet 5"
    assert sent["output_config"]["effort"] == "high"
    assert sent["tools"][0]["type"] == client_mod.WEB_SEARCH_TOOL_TYPE
    assert sent["tools"][0]["max_uses"] == 5


def test_no_tools_are_sent_when_searches_are_disabled(settings, guard, run):
    client = make_client(settings, guard, run, FakeMessage('{"ok": 1}'))
    client.ask(system="s", user="u", purpose="synthesis", max_searches=0)
    assert "tools" not in client.client.messages.calls[0]


def test_budget_is_checked_before_the_call_not_after(settings, guard, run, conn):
    conn.execute("INSERT INTO spend (at, month, model, cost_usd, cost_aud) VALUES "
                 "('2026-09-01T00:00:00+00:00', '2026-09', 'claude-sonnet-5', 20, 29.5)")
    conn.commit()
    client = make_client(settings, guard, run, FakeMessage('{"themes": []}'))
    with pytest.raises(BudgetExhausted):
        client.ask(system="s", user="u", purpose="theme_update")
    assert client.client.messages.calls == [], "no request may be sent once the cap is hit"


def test_web_search_errors_are_surfaced_not_swallowed(settings, guard, run):
    """Search failures arrive as HTTP 200 with an error object, so they never raise."""
    client = make_client(settings, guard, run,
                         FakeMessage('{"themes": []}', searches=1,
                                     search_errors=["max_uses_exceeded"]))
    answer = client.ask(system="s", user="u", purpose="theme_update")
    assert answer.search_errors == ["max_uses_exceeded"]
    assert any(e["event"] == "web_search_error" for e in run.events())


def test_unparseable_output_triggers_one_repair_attempt(settings, guard, run):
    client = make_client(settings, guard, run,
                         FakeMessage("Sorry, here is a summary in prose."),
                         FakeMessage('{"themes": []}'))
    answer = client.ask(system="s", user="u", purpose="theme_update")
    assert answer.repaired
    assert answer.payload == {"themes": []}
    assert len(client.client.messages.calls) == 2


def test_a_failed_repair_raises_rather_than_returning_junk(settings, guard, run):
    client = make_client(settings, guard, run,
                         FakeMessage("prose"), FakeMessage("still prose"))
    with pytest.raises(ResearchError, match="repair attempt failed"):
        client.ask(system="s", user="u", purpose="theme_update")


def test_the_repair_call_is_billed_too(settings, guard, run):
    client = make_client(settings, guard, run,
                         FakeMessage("prose"), FakeMessage('{"ok": 1}'))
    client.ask(system="s", user="u", purpose="theme_update")
    purposes = [r["purpose"] for r in guard.month_breakdown()]
    assert "theme_update" in purposes and "theme_update_repair" in purposes


def test_the_estimate_scales_with_searches(settings, guard, run):
    client = make_client(settings, guard, run)
    assert client.estimate_aud(20, 16_000) > client.estimate_aud(2, 16_000)


# ---------------------------------------------------------------------------
# Prompts
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("name", ["system", "theme_update", "discovery",
                                  "synthesis", "daily_news"])
def test_every_prompt_template_loads(name):
    assert len(client_mod.load_prompt(name)) > 200


def test_the_system_prompt_carries_the_source_rules_and_the_profile(settings, conn):
    prompt = engine.system_prompt(settings, TODAY)
    assert "platform makes money" in prompt
    assert "realistically make money" in prompt
    assert "Never invent a number" in prompt
    assert TODAY in prompt


def test_the_system_prompt_forbids_narrowing_the_search(settings):
    prompt = engine.system_prompt(settings, TODAY)
    assert "narrow your" in prompt and "search" in prompt


# ---------------------------------------------------------------------------
# Context blocks
# ---------------------------------------------------------------------------


def test_context_blocks_render_from_the_seeded_database(conn, settings):
    seed(conn, settings)
    assert "home-batteries" in engine.themes_block(conn)
    assert "brent" in engine.macro_block(conn, TODAY)
    assert "Tracked themes:" in engine.existing_block(conn)


def test_the_verify_block_lists_the_unsourced_baseline_claims(conn, settings):
    seed(conn, settings)
    block = engine.verify_block(conn)
    assert "home-batteries" in block and "500,000" in block


def test_the_verify_block_empties_once_claims_are_sourced(conn, settings):
    seed(conn, settings)
    conn.execute("DELETE FROM evidence WHERE source_url LIKE 'baseline://%'")
    conn.commit()
    assert "none outstanding" in engine.verify_block(conn)


def test_empty_blocks_do_not_break(conn):
    assert "no themes tracked" in engine.themes_block(conn)
    assert "no macro readings" in engine.macro_block(conn, TODAY)
    assert "no recent quotes" in engine.watchlist_block(conn)


def test_the_opportunities_block_flags_missing_individual_evidence(settings):
    scored = scoring.rank([make_opportunity(individual="")], settings.research, 6.0)
    assert "no evidence individuals actually earn" in engine.opportunities_block(scored)


def test_an_empty_week_says_so(settings):
    assert "nothing cleared the evidence bar" in engine.opportunities_block([])


# ---------------------------------------------------------------------------
# The weekly orchestration
# ---------------------------------------------------------------------------


THEME_JSON = json.dumps({"themes": [{
    "slug": "home-batteries", "status": "RISING",
    "reason": "Rebate step-down confirmed for 1 Jan 2027",
    "evidence": [{"claim": "500,000 installs", "number_value": "500,000",
                  "source_name": "Clean Energy Regulator",
                  "source_url": "https://www.cleanenergyregulator.gov.au/x",
                  "source_date": "2026-09-10", "source_strength": "primary"}]}]})

DISCOVERY_JSON = json.dumps({"opportunities": [{
    "slug": "grid-battery-maintenance", "title": "Grid battery maintenance contracts",
    "summary": "Servicing community batteries.",
    "who_earns": "accredited electricians",
    "platform_revenue_evidence": "Sector revenue up 40% y/y",
    "individual_earnings_evidence": "Technicians report $95/hr on published awards",
    "startup_cost_aud_min": 500, "startup_cost_aud_max": 4000,
    "time_to_first_dollar_days": 60, "skills_required": "electrical licence",
    "saturation": "thin outside metro", "red_flags": "none found",
    "au_eligibility": "requires a NSW licence",
    "evidence": [{"claim": "Sector revenue up 40%", "number_value": "+40% y/y",
                  "source_name": "Clean Energy Council",
                  "source_url": "https://www.cleanenergycouncil.org.au/y",
                  "source_date": "2026-09-05", "source_strength": "primary"}],
    "scores": {"evidence_strength": 8, "personal_fit": 3, "capital_fit": 6,
               "hours_fit": 4, "speed_to_dollar": 4, "risk": 6,
               "reasons": {"personal_fit": "needs an electrical licence"}}}]})

SYNTHESIS_JSON = json.dumps({
    "summary": ["Battery rebate step-down confirmed.", "Nothing else moved.", "AUD flat."],
    "actions": [{"rank": 1, "title": "Read the rebate step-down schedule",
                 "why": "Sets the deadline for any battery-related move",
                 "est_minutes": 45, "opportunity_slug": ""}]})


def weekly_client(settings, guard, run):
    return make_client(settings, guard, run,
                       FakeMessage(THEME_JSON, searches=4),
                       FakeMessage(DISCOVERY_JSON, searches=6),
                       FakeMessage(SYNTHESIS_JSON))


def test_a_full_weekly_run(conn, settings, guard, run):
    seed(conn, settings)
    out = engine.run_weekly(conn, settings, run, weekly_client(settings, guard, run), TODAY)
    assert len(out.result.theme_updates) == 1
    assert len(out.result.opportunities) == 1
    assert len(out.result.actions) == 1
    assert out.result.summary[0].startswith("Battery rebate")
    assert out.searches == 10
    assert out.cost_aud > 0
    assert out.failures == []


def test_a_poor_fit_lead_is_reported_separately_not_dropped(conn, settings, guard, run):
    seed(conn, settings)
    out = engine.run_weekly(conn, settings, run, weekly_client(settings, guard, run), TODAY)
    assert out.actionable == []
    assert len(out.other) == 1, "personal_fit 3 belongs in the other-leads section"


def test_one_failing_pass_does_not_lose_the_others(conn, settings, guard, run):
    seed(conn, settings)
    client = make_client(settings, guard, run,
                         FakeMessage("prose"), FakeMessage("still prose"),  # theme + repair
                         FakeMessage(DISCOVERY_JSON, searches=6),
                         FakeMessage(SYNTHESIS_JSON))
    out = engine.run_weekly(conn, settings, run, client, TODAY)
    assert out.result.theme_updates == []
    assert len(out.result.opportunities) == 1, "discovery still ran"
    assert len(out.failures) == 1 and "theme_update" in out.failures[0]


def test_budget_exhaustion_stops_the_whole_run(conn, settings, guard, run):
    seed(conn, settings)
    conn.execute("INSERT INTO spend (at, month, model, cost_usd, cost_aud) VALUES "
                 "('2026-09-01T00:00:00+00:00', '2026-09', 'claude-sonnet-5', 20, 29.8)")
    conn.commit()
    with pytest.raises(BudgetExhausted):
        engine.run_weekly(conn, settings, run, weekly_client(settings, guard, run), TODAY)


def test_rejections_are_logged_for_the_run(conn, settings, guard, run):
    seed(conn, settings)
    bad = json.dumps({"opportunities": [{"slug": "junk", "title": "Junk",
                                         "evidence": [], "scores": {}}]})
    client = make_client(settings, guard, run, FakeMessage(THEME_JSON),
                         FakeMessage(bad), FakeMessage(SYNTHESIS_JSON))
    out = engine.run_weekly(conn, settings, run, client, TODAY)
    assert out.result.opportunities == []
    assert any(e["event"] == "rejected" for e in run.events())


# ---------------------------------------------------------------------------
# Persistence
# ---------------------------------------------------------------------------


def test_theme_updates_are_persisted_and_change_the_theme(conn, settings, guard, run):
    seed(conn, settings)
    out = engine.run_weekly(conn, settings, run, weekly_client(settings, guard, run), TODAY)
    engine.store_theme_updates(conn, run.id, TODAY, out.result.theme_updates)

    theme = conn.execute("SELECT status FROM themes WHERE slug = 'home-batteries'").fetchone()
    assert theme["status"] == "RISING"
    update = conn.execute("SELECT * FROM theme_updates WHERE as_of_date = ?",
                          (TODAY,)).fetchone()
    assert update["prev_status"] == "RISING"
    assert conn.execute(
        "SELECT COUNT(*) AS n FROM evidence WHERE source_strength = 'primary'"
    ).fetchone()["n"] == 1


def test_opportunities_scores_and_evidence_are_persisted(conn, settings, guard, run):
    seed(conn, settings)
    out = engine.run_weekly(conn, settings, run, weekly_client(settings, guard, run), TODAY)
    engine.store_opportunities(conn, run.id, TODAY, out.scored)

    opportunity = conn.execute("SELECT * FROM opportunities").fetchone()
    assert opportunity["slug"] == "grid-battery-maintenance"
    assert "95/hr" in opportunity["individual_earnings_evidence"]
    score = conn.execute("SELECT * FROM scores").fetchone()
    assert score["personal_fit"] == 3
    assert "needs an electrical licence" in score["rationale"]


def test_storing_twice_updates_rather_than_duplicating(conn, settings, guard, run):
    seed(conn, settings)
    out = engine.run_weekly(conn, settings, run, weekly_client(settings, guard, run), TODAY)
    engine.store_opportunities(conn, run.id, TODAY, out.scored)
    engine.store_opportunities(conn, run.id, TODAY, out.scored)
    assert conn.execute("SELECT COUNT(*) AS n FROM opportunities").fetchone()["n"] == 1
    assert conn.execute("SELECT COUNT(*) AS n FROM evidence WHERE "
                        "subject_type = 'opportunity'").fetchone()["n"] == 1


def test_actions_are_persisted_with_their_rank(conn, settings, guard, run):
    seed(conn, settings)
    out = engine.run_weekly(conn, settings, run, weekly_client(settings, guard, run), TODAY)
    engine.store_actions(conn, run.id, TODAY, out.result.actions)
    action = conn.execute("SELECT * FROM actions").fetchone()
    assert action["rank"] == 1 and action["est_minutes"] == 45
    assert action["outcome"] == "pending"


def test_baseline_claims_retire_once_real_evidence_arrives(conn, settings, guard, run):
    seed(conn, settings)
    before = len(engine.verify_block(conn).splitlines())
    out = engine.run_weekly(conn, settings, run, weekly_client(settings, guard, run), TODAY)
    engine.store_theme_updates(conn, run.id, TODAY, out.result.theme_updates)

    removed = engine.retire_baseline_claims(conn, "home-batteries")
    assert removed == 2, "both battery baseline claims had no source"
    assert len(engine.verify_block(conn).splitlines()) < before


def test_retiring_does_nothing_without_real_evidence(conn, settings):
    seed(conn, settings)
    assert engine.retire_baseline_claims(conn, "home-batteries") == 0, \
        "unsourced claims must not be deleted until something sourced replaces them"


# ---------------------------------------------------------------------------
# The daily pass
# ---------------------------------------------------------------------------


def test_a_quiet_day_returns_nothing(conn, settings, guard, run):
    seed(conn, settings)
    client = make_client(settings, guard, run, FakeMessage('{"alerts": []}', searches=2))
    alerts, rejected = engine.run_daily(conn, settings, run, client, TODAY)
    assert alerts == [] and rejected == []


def test_a_rate_decision_becomes_an_alert(conn, settings, guard, run):
    seed(conn, settings)
    payload = json.dumps({"alerts": [{
        "rule": "rate_decision", "subject": "RBA", "headline": "RBA holds at 4.35%",
        "detail": "Held.", "source_url": "https://www.rba.gov.au/mr-26-20.html",
        "source_date": TODAY, "severity": "urgent"}]})
    client = make_client(settings, guard, run, FakeMessage(payload, searches=3))
    alerts, _ = engine.run_daily(conn, settings, run, client, TODAY)
    assert len(alerts) == 1 and alerts[0].rule == "rate_decision"


def test_the_daily_pass_uses_low_effort_and_few_searches(conn, settings, guard, run):
    seed(conn, settings)
    client = make_client(settings, guard, run, FakeMessage('{"alerts": []}'))
    engine.run_daily(conn, settings, run, client, TODAY)
    sent = client.client.messages.calls[0]
    assert sent["output_config"]["effort"] == settings.research.daily_effort
    assert sent["tools"][0]["max_uses"] == settings.research.max_searches_daily


def test_a_daily_run_costs_far_less_than_a_weekly_one(conn, settings, guard, run):
    seed(conn, settings)
    client = make_client(settings, guard, run, FakeMessage('{"alerts": []}'))
    daily_estimate = client.estimate_aud(settings.research.max_searches_daily, 4_000)
    weekly_estimate = client.estimate_aud(settings.research.max_searches_discovery, 16_000)
    assert daily_estimate < weekly_estimate / 2
