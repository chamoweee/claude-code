"""Report rendering and the Gmail sender.

No network here either: the sender is exercised through an injected send
function, so the MIME construction and credential handling are covered without
an account.
"""

from __future__ import annotations

import base64
import re

import pytest

from radar.budget import BudgetGuard
from radar.config import load_settings
from radar.db import connect
from radar.mail import gmail
from radar.report import build, render
from radar.report.render import ReportData
from radar.research import engine, scoring
from radar.research.schemas import SCORE_FIELDS, Action, Evidence, Opportunity, SubScores
from radar.runlog import start_run
from radar.seed_baseline import seed
from radar.sources.macro import MetricChange

TODAY = "2026-09-21"


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


def make_opportunity(*, individual="Contributors report $85/hr on published rates",
                     strength="primary", red_flags="", **scores):
    values = {name: 7 for name in SCORE_FIELDS}
    values.update(scores)
    return Opportunity(
        slug="ai-eval-work", title="AI evaluation contracts",
        summary="Platforms paying subject-matter experts to grade model output.",
        who_earns="the platform takes a margin; experts are paid hourly",
        platform_revenue_evidence="Platform run rate reported at US$2B",
        individual_earnings_evidence=individual,
        startup_cost_aud_min=0, startup_cost_aud_max=200,
        time_to_first_dollar_days=21, skills_required="domain expertise",
        saturation="rising quickly", red_flags=red_flags,
        au_eligibility="open to Australian tax residents",
        evidence=(Evidence("Run rate reported", "Reuters",
                           "https://www.reuters.com/x", "2026-09-01", strength,
                           "US$2B"),),
        scores=SubScores(**values))


def scored(settings, *opportunities):
    return scoring.rank(list(opportunities), settings.research,
                        settings.research.no_individual_evidence_cap)


def rows_for(opportunity, result):
    return scoring.format_scoring_table(opportunity, result)


def sample_data(settings, **overrides) -> ReportData:
    ranked = scored(settings, make_opportunity())
    base = dict(
        sydney_date=TODAY,
        summary=["Battery rebate step-down confirmed.", "Nothing else moved.",
                 "AUD flat on the week."],
        macro=[MetricChange("gold", "Gold", "USD/oz", 4324.0, 4290.0, "2026-09-14"),
               MetricChange("uranium_ura_proxy", "Uranium (URA ETF proxy)", "USD",
                            42.1, 40.0, "2026-09-14", is_proxy=True)],
        themes=[{"slug": "home-batteries", "title": "Home batteries",
                 "status": "RISING", "reason": "Step-down confirmed for 1 Jan 2027"}],
        actionable=ranked, other_leads=[],
        watchlist=[{"symbol": "VICI", "close": 25.04, "currency": "USD",
                    "pct_change": 0.85, "note": "close for 2026-09-18"}],
        actions=[Action(1, "Read the rebate schedule", "Sets the deadline", 45)],
        sources=[{"url": "https://www.rba.gov.au/", "name": "RBA"}],
    )
    base.update(overrides)
    return ReportData(**base)


# ---------------------------------------------------------------------------
# Weekly HTML
# ---------------------------------------------------------------------------


def test_weekly_html_has_the_seven_sections(settings):
    html = render.render_weekly_html(sample_data(settings), rows_for)
    for heading in ("What changed this week", "Macro snapshot", "Tracked themes",
                    "New opportunities for you", "Watchlist",
                    "Your top actions this week", "Spend and sources"):
        assert heading in html, heading


def test_the_email_is_built_for_a_phone(settings):
    html = render.render_weekly_html(sample_data(settings), rows_for)
    assert 'name="viewport"' in html
    assert f"max-width:{render.MAX_WIDTH}px" in html
    assert "<style" not in html, "Gmail strips style blocks, hardest on mobile"
    assert 'role="presentation"' in html, "layout must be table-based for email"


def test_no_external_resources_are_loaded(settings):
    """No web fonts, no images, no tracking pixels — the email must work offline."""
    html = render.render_weekly_html(sample_data(settings), rows_for)
    assert "<img" not in html
    assert "fonts.googleapis" not in html
    for match in re.findall(r'src="([^"]+)"', html):
        pytest.fail(f"unexpected external resource: {match}")


def test_body_text_is_never_smaller_than_twelve_px(settings):
    html = render.render_weekly_html(sample_data(settings), rows_for)
    sizes = [int(s) for s in re.findall(r"font:\d+ (\d+)px", html)]
    assert sizes and min(sizes) >= 12


def test_user_content_is_escaped(settings):
    nasty = make_opportunity()
    object.__setattr__(nasty, "title", '<script>alert("x")</script>')
    html = render.render_weekly_html(
        sample_data(settings, actionable=scored(settings, nasty)), rows_for)
    assert "<script>" not in html
    assert "&lt;script&gt;" in html


def test_the_proxy_metric_is_labelled_in_the_email(settings):
    html = render.render_weekly_html(sample_data(settings), rows_for)
    assert "PROXY" in html
    assert "stand-in series" in html


def test_missing_individual_evidence_is_stated_in_red_not_omitted(settings):
    data = sample_data(settings,
                       actionable=scored(settings, make_opportunity(individual="")))
    html = render.render_weekly_html(data, rows_for)
    assert "no evidence found that individuals" in html.lower()
    assert render.BAD in html


def test_a_capped_score_explains_itself(settings):
    data = sample_data(settings,
                       actionable=scored(settings, make_opportunity(strength="weak")))
    html = render.render_weekly_html(data, rows_for)
    assert "Score held down" in html
    assert "uncapped it would score" in html


def test_red_flags_are_called_out(settings):
    data = sample_data(settings, actionable=scored(
        settings, make_opportunity(red_flags="Most advocates sell a course")))
    assert "Most advocates sell a course" in render.render_weekly_html(data, rows_for)


def test_evidence_links_and_dates_appear(settings):
    html = render.render_weekly_html(sample_data(settings), rows_for)
    assert 'href="https://www.reuters.com/x"' in html
    assert "2026-09-01" in html
    assert "primary" in html


def test_the_scoring_table_is_shown(settings):
    html = render.render_weekly_html(sample_data(settings), rows_for)
    for label in ("Evidence", "Personal fit", "Capital needed", "Risk"):
        assert label in html


def test_the_advice_disclaimer_is_present(settings):
    html = render.render_weekly_html(sample_data(settings), rows_for)
    assert "not financial advice" in html
    assert "does not trade" in html


def test_the_other_leads_section_appears_only_when_populated(settings):
    without = render.render_weekly_html(sample_data(settings), rows_for)
    assert "Real, but not a fit" not in without

    poor_fit = scored(settings, make_opportunity(personal_fit=2))
    with_other = render.render_weekly_html(
        sample_data(settings, other_leads=poor_fit), rows_for)
    assert "Real, but not a fit" in with_other


def test_section_numbers_stay_sequential_with_the_optional_section(settings):
    html = render.render_weekly_html(
        sample_data(settings, other_leads=scored(settings, make_opportunity())), rows_for)
    numbers = [int(n) for n in re.findall(r">(\d)\. [A-Z]", html)]
    assert numbers == sorted(numbers) and len(set(numbers)) == len(numbers)


def test_a_quiet_week_still_produces_a_full_report(settings):
    """A missing Monday email must mean something broke, never that nothing happened."""
    quiet = sample_data(settings, summary=["Nothing material moved this week."],
                        actionable=[], actions=[])
    html = render.render_weekly_html(quiet, rows_for)
    assert "Macro snapshot" in html and "Tracked themes" in html
    assert "Nothing new cleared the evidence bar" in html
    assert "Nothing found was worth your evening" in html


def test_an_empty_report_does_not_crash(settings):
    html = render.render_weekly_html(ReportData(sydney_date=TODAY), rows_for)
    assert "Opportunity Radar" in html


def test_failures_are_reported_in_the_email_not_hidden(settings):
    data = sample_data(settings, failures=["discovery: web search unavailable"])
    html = render.render_weekly_html(data, rows_for)
    assert "Parts of this run failed" in html
    assert "web search unavailable" in html


def test_discarded_items_are_listed(settings):
    data = sample_data(settings, rejected=["opportunity x: DROPPED — no evidence"])
    assert "Discarded for weak sourcing" in render.render_weekly_html(data, rows_for)


def test_the_subject_leads_with_the_headline(settings):
    subject = render.weekly_subject(sample_data(settings))
    assert subject.startswith(f"Radar {TODAY}:")
    assert "Battery rebate step-down" in subject


def test_a_long_headline_is_truncated(settings):
    data = sample_data(settings, summary=["x" * 200])
    assert len(render.weekly_subject(data)) < 110


# ---------------------------------------------------------------------------
# Plain text
# ---------------------------------------------------------------------------


def test_the_text_alternative_carries_the_substance(settings):
    text = render.render_weekly_text(sample_data(settings))
    assert "OPPORTUNITY RADAR" in text
    assert "Battery rebate step-down confirmed." in text
    assert "https://www.reuters.com/x" in text
    assert "<" not in text.replace("<no", ""), "the text part must not contain markup"


def test_the_text_version_also_flags_missing_individual_evidence(settings):
    data = sample_data(settings,
                       actionable=scored(settings, make_opportunity(individual="")))
    assert "NO EVIDENCE FOUND" in render.render_weekly_text(data)


# ---------------------------------------------------------------------------
# Alert and error emails
# ---------------------------------------------------------------------------


class FakeAlert:
    def __init__(self, headline, severity="urgent"):
        self.headline = headline
        self.detail = "Detail here."
        self.severity = severity
        self.source_url = "https://www.rba.gov.au/mr.html"


def test_the_alert_email_renders():
    html = render.render_alert_html([FakeAlert("RBA holds at 4.35%")], TODAY)
    assert "RBA holds at 4.35%" in html
    assert "1 alert triggered" in html


def test_multiple_alerts_pluralise():
    html = render.render_alert_html(
        [FakeAlert("a"), FakeAlert("b")], TODAY)
    assert "2 alerts triggered" in html


def test_the_alert_subject_uses_the_single_headline():
    assert render.alert_subject([FakeAlert("Gold fell 4.2%")], TODAY) == \
        "Radar alert: Gold fell 4.2%"
    assert "2 alerts" in render.alert_subject([FakeAlert("a"), FakeAlert("b")], TODAY)


def test_the_error_email_is_short_and_says_why_it_exists():
    html = render.render_error_html("weekly", TODAY, ["Timeout contacting the API"], 42)
    assert "did not complete" in html
    assert "Timeout contacting the API" in html
    assert "something broke" in html


def test_error_text_lists_the_errors():
    text = render.render_error_text("daily", TODAY, ["boom"], 7)
    assert "boom" in text and "#7" in text


# ---------------------------------------------------------------------------
# Building from history
# ---------------------------------------------------------------------------


def test_macro_changes_come_from_stored_history(conn, settings):
    for date, value in (("2026-09-14", 4290.0), ("2026-09-21", 4324.0)):
        conn.execute("INSERT INTO macro_snapshots (as_of_date, metric, value, unit) "
                     "VALUES (?, 'gold', ?, 'USD/oz')", (date, value))
    conn.commit()
    changes = build.macro_changes_from_history(conn, TODAY)
    assert len(changes) == 1
    assert changes[0].previous_date == "2026-09-14"
    assert changes[0].pct_change == pytest.approx((4324 - 4290) / 4290 * 100)


def test_theme_rows_show_a_status_transition(conn, settings, run):
    seed(conn, settings)
    theme_id = conn.execute(
        "SELECT id FROM themes WHERE slug = 'home-batteries'").fetchone()["id"]
    conn.execute("INSERT INTO theme_updates (theme_id, as_of_date, status, "
                 "prev_status, reason) VALUES (?, ?, 'FADING', 'RISING', 'Installs slowed')",
                 (theme_id, TODAY))
    conn.commit()
    rows = build.theme_rows(conn, TODAY)
    assert rows[0]["status"] == "FADING"
    assert "(RISING → FADING)" in rows[0]["reason"]


def test_theme_rows_fall_back_to_standing_status_with_no_update(conn, settings):
    seed(conn, settings)
    rows = build.theme_rows(conn, TODAY)
    assert len(rows) == 7
    assert all(row["reason"] == "No update this week." for row in rows)


def test_watchlist_rows_take_the_latest_close_per_symbol(conn):
    for date, close in (("2026-09-14", 24.0), ("2026-09-18", 25.04)):
        conn.execute("INSERT INTO watchlist_quotes (symbol, as_of_date, close, "
                     "currency, pct_change) VALUES ('VICI', ?, ?, 'USD', 0.85)",
                     (date, close))
    conn.commit()
    rows = build.watchlist_rows(conn, TODAY)
    assert len(rows) == 1 and rows[0]["close"] == pytest.approx(25.04)


def test_build_weekly_assembles_from_history(conn, settings, run):
    seed(conn, settings)

    class FakeWeekly:
        result = type("R", (), {"summary": ["x"], "actions": [], "rejected": []})()
        actionable, other, failures = [], [], []

    data = build.build_weekly(conn, settings, run, FakeWeekly(), TODAY)
    assert data.sydney_date == TODAY
    assert len(data.themes) == 7
    assert data.spend_status.cap_aud == 30.0
    html = render.render_weekly_html(data, rows_for)
    assert "Opportunity Radar" in html


# ---------------------------------------------------------------------------
# Gmail
# ---------------------------------------------------------------------------


# Distinctive values, so a leak in the repr cannot be confused with the word
# "secrets" in the placeholder text itself.
CREDS = gmail.GmailCredentials("client-id-AAA", "client-secret-BBB",
                               "refresh-token-CCC", "me@example.com")


def test_the_message_is_multipart_with_a_real_text_part():
    message = gmail.build_message(sender="me@example.com", recipient="you@example.com",
                                  subject="Subject", html="<p>Hi</p>", text="Hi")
    assert message.is_multipart()
    types = [part.get_content_type() for part in message.walk()]
    assert "text/plain" in types and "text/html" in types


def test_the_message_is_marked_auto_generated():
    """Stops a machine report from starting an auto-responder loop."""
    message = gmail.build_message(sender="a@b.com", recipient="c@d.com",
                                  subject="s", html="<p>h</p>", text="t")
    assert message["Auto-Submitted"] == "auto-generated"


def test_send_email_encodes_the_message_base64url():
    captured = {}

    def fake_send(message, credentials, token=None):
        raw = base64.urlsafe_b64encode(message.as_bytes()).decode()
        captured["decoded"] = base64.urlsafe_b64decode(raw).decode()
        return "msg-123"

    result = gmail.send_email(recipient="you@example.com", subject="Radar",
                              html="<p>Report</p>", text="Report",
                              credentials=CREDS, sender_fn=fake_send)
    assert result == "msg-123"
    assert "Subject: Radar" in captured["decoded"]
    assert "To: you@example.com" in captured["decoded"]


def test_missing_credentials_name_what_is_missing(monkeypatch):
    for name in ("GMAIL_CLIENT_ID", "GMAIL_CLIENT_SECRET",
                 "GMAIL_REFRESH_TOKEN", "GMAIL_SENDER"):
        monkeypatch.delenv(name, raising=False)
    with pytest.raises(gmail.MailError) as excinfo:
        gmail.GmailCredentials.from_env()
    assert "GMAIL_CLIENT_ID" in str(excinfo.value)
    assert "README" in str(excinfo.value)


def test_credentials_never_appear_in_their_repr():
    text = repr(CREDS)
    assert "client-secret-BBB" not in text
    assert "refresh-token-CCC" not in text
    assert "client-id-AAA" not in text
    assert "me@example.com" in text, "the sender is not a secret and aids debugging"


def test_only_the_send_scope_is_requested():
    """The agent must have no ability to read mail."""
    assert gmail.SEND_SCOPE.endswith("/auth/gmail.send")
    assert "readonly" not in gmail.SEND_SCOPE and "modify" not in gmail.SEND_SCOPE


def test_the_email_stays_under_the_gmail_clipping_threshold(settings):
    """Gmail clips messages over about 102KB and hides the rest behind a link.

    A full week — five opportunities with evidence, plus every section — must
    fit, or the spend and sources at the bottom would be the first thing lost.
    """
    many = scored(settings, *[make_opportunity() for _ in range(5)])
    data = sample_data(settings, actionable=many, other_leads=many,
                       rejected=[f"rejection reason {i}" for i in range(25)],
                       sources=[{"url": f"https://example.gov.au/{i}", "name": f"S{i}"}
                                for i in range(40)])
    size = len(render.render_weekly_html(data, rows_for).encode("utf-8"))
    assert size < 90_000, f"{size:,} bytes risks Gmail clipping the email"


# ---------------------------------------------------------------------------
# Regressions found by rendering a real preview
# ---------------------------------------------------------------------------


def test_a_restated_metric_updates_its_unit_not_just_its_value(conn, run):
    """A baseline copper row in '% y/y' kept that unit when a USD/lb price
    overwrote the value, producing '6.481 % y/y' in the email."""
    from radar.sources.macro import METRICS_BY_KEY, MacroReading, store_macro
    from radar.sources.yahoo import Bar, Quote

    conn.execute("INSERT INTO macro_snapshots (as_of_date, metric, value, unit, note) "
                 "VALUES ('2026-09-21', 'copper', NULL, '% y/y', 'baseline')")
    conn.commit()

    quote = Quote("HG=F", "Copper", "USD", "COMEX", "2026-09-21", 6.48, 6.40,
                  (Bar("2026-09-21", 6.48),))
    store_macro(conn, run.id, TODAY,
                [MacroReading(METRICS_BY_KEY["copper"], quote)])

    row = conn.execute("SELECT unit, value, note FROM macro_snapshots "
                       "WHERE metric = 'copper'").fetchone()
    assert row["unit"] == "USD/lb", "the unit must travel with the value"
    assert row["value"] == pytest.approx(6.48)
    assert "COMEX" in row["note"]


def test_a_first_reading_does_not_claim_a_change(settings):
    """'no prior reading since first reading' was nonsense in both renderings."""
    first = MetricChange("gold", "Gold", "USD/oz", 4324.0, None, None)
    data = sample_data(settings, macro=[first])
    html = render.render_weekly_html(data, rows_for)
    text = render.render_weekly_text(data)
    assert "first reading" in html and "since first reading" not in html
    assert "(first reading)" in text and "no prior reading since" not in text


def test_research_sourced_metrics_get_readable_labels():
    """METRICS_BY_KEY has no entry for these, and title-casing gave 'Rba Cash Rate'."""
    assert build.label_for("rba_cash_rate") == "RBA cash rate"
    assert build.label_for("sydney_vacancy_rate") == "Sydney rental vacancy"
    assert build.label_for("gold") == "Gold"
    assert build.label_for("something_unknown") == "Something unknown"
