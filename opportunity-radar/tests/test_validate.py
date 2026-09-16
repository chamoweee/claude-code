"""Validation is the gate between what the model said and what reaches the inbox.

These tests are written as adversarially as possible: the point is that a
confident, well-written, entirely unsupported claim does not get through.
"""

from __future__ import annotations

from datetime import date

import pytest

from radar.research import validate
from radar.research.schemas import SCORE_FIELDS

TODAY = date(2026, 9, 21)


def evidence(**overrides):
    base = {
        "claim": "Installs reached 500,000",
        "number_value": "500,000",
        "source_name": "Clean Energy Regulator",
        "source_url": "https://www.cleanenergyregulator.gov.au/report",
        "source_date": "2026-08-14",
        "source_strength": "primary",
    }
    base.update(overrides)
    return base


def validated(raw, *, max_age_days=90, rejected=None):
    return validate.validate_evidence(raw, today=TODAY, max_age_days=max_age_days,
                                      rejected=rejected if rejected is not None else [],
                                      context="test")


# ---------------------------------------------------------------------------
# Evidence
# ---------------------------------------------------------------------------


def test_good_evidence_passes():
    item = validated(evidence())
    assert item is not None
    assert item.source_strength == "primary"
    assert item.source_date == "2026-08-14"


def test_evidence_without_a_url_is_rejected():
    rejected = []
    assert validated(evidence(source_url=""), rejected=rejected) is None
    assert "no usable source URL" in rejected[0]


def test_a_bare_site_name_is_not_a_url():
    assert validated(evidence(source_url="cleanenergyregulator.gov.au")) is None


def test_evidence_without_a_date_is_rejected():
    rejected = []
    assert validated(evidence(source_date=""), rejected=rejected) is None
    assert "no parseable source date" in rejected[0]


def test_a_future_dated_source_is_rejected():
    """A source dated after today is fabricated or misread; either way it goes."""
    rejected = []
    assert validated(evidence(source_date="2027-01-01"), rejected=rejected) is None
    assert "dated in the future" in rejected[0]


def test_evidence_older_than_the_window_is_rejected_for_discovery():
    rejected = []
    assert validated(evidence(source_date="2025-01-01"), rejected=rejected) is None
    assert "older than the 90-day window" in rejected[0]


def test_old_evidence_is_allowed_where_there_is_no_window():
    """Theme evidence has no age limit: an old primary source still anchors a fact."""
    assert validated(evidence(source_date="2024-01-01"), max_age_days=None) is not None


def test_a_month_only_date_is_accepted():
    assert validated(evidence(source_date="2026-08")).source_date == "2026-08-01"


def test_a_written_date_is_accepted():
    assert validated(evidence(source_date="14 August 2026")).source_date == "2026-08-14"


def test_an_unknown_strength_falls_back_to_weak():
    assert validated(evidence(source_strength="excellent")).source_strength == "weak"


@pytest.mark.parametrize("url", [
    "https://medium.com/@someone/how-i-made-10k",
    "https://someguy.substack.com/p/the-real-money",
    "https://agency.com/blog/ai-automation-goldmine",
    "https://www.udemy.com/course/passive-income",
])
def test_self_promotional_hosts_are_forced_to_weak(url):
    """A course platform relabelled `primary` is still a course platform."""
    item = validated(evidence(source_url=url, source_strength="primary"))
    assert item.source_strength == "weak", url


def test_evidence_with_no_claim_is_rejected():
    assert validated(evidence(claim="")) is None


def test_a_non_object_evidence_entry_is_rejected():
    rejected = []
    assert validated("just a string", rejected=rejected) is None
    assert "not an object" in rejected[0]


# ---------------------------------------------------------------------------
# Theme updates
# ---------------------------------------------------------------------------


def test_theme_update_passes():
    rejected = []
    updates = validate.validate_theme_updates(
        {"themes": [{"slug": "home-batteries", "status": "RISING",
                     "reason": "Rebate step-down confirmed for 1 Jan 2027",
                     "evidence": [evidence()]}]},
        ["home-batteries"], today=TODAY, rejected=rejected)
    assert len(updates) == 1
    assert updates[0].status == "RISING"
    assert len(updates[0].evidence) == 1


def test_an_invented_theme_slug_is_rejected():
    rejected = []
    updates = validate.validate_theme_updates(
        {"themes": [{"slug": "crypto-moonshots", "status": "RISING", "reason": "x"}]},
        ["home-batteries"], today=TODAY, rejected=rejected)
    assert updates == []
    assert "unknown slug" in rejected[0]


def test_an_unknown_status_is_rejected():
    rejected = []
    updates = validate.validate_theme_updates(
        {"themes": [{"slug": "home-batteries", "status": "EXPLODING", "reason": "x"}]},
        ["home-batteries"], today=TODAY, rejected=rejected)
    assert updates == []
    assert "unknown status" in rejected[0]


def test_a_status_with_no_reason_is_rejected():
    rejected = []
    updates = validate.validate_theme_updates(
        {"themes": [{"slug": "home-batteries", "status": "RISING", "reason": ""}]},
        ["home-batteries"], today=TODAY, rejected=rejected)
    assert updates == []
    assert "no reason" in rejected[0]


def test_duplicate_theme_updates_keep_only_the_first():
    rejected = []
    updates = validate.validate_theme_updates(
        {"themes": [{"slug": "t", "status": "RISING", "reason": "a"},
                    {"slug": "t", "status": "DEAD", "reason": "b"}]},
        ["t"], today=TODAY, rejected=rejected)
    assert len(updates) == 1 and updates[0].status == "RISING"


def test_conflicts_are_preserved_for_both_sides():
    updates = validate.validate_theme_updates(
        {"themes": [{"slug": "t", "status": "STABLE", "reason": "disputed",
                     "conflicts": [{"topic": "install count",
                                    "side_a": "CER says 500k",
                                    "side_b": "industry body says 430k"}]}]},
        ["t"], today=TODAY, rejected=[])
    assert updates[0].conflicts[0].side_a and updates[0].conflicts[0].side_b


# ---------------------------------------------------------------------------
# Opportunities
# ---------------------------------------------------------------------------


def opportunity(**overrides):
    base = {
        "slug": "battery-install-referrals",
        "title": "Battery install referral fees",
        "summary": "Referring households to accredited installers.",
        "who_earns": "the installer, with a referral cut",
        "platform_revenue_evidence": "Installer revenue up 40%",
        "individual_earnings_evidence": "Referrers report $200-400 per install",
        "evidence": [evidence()],
        "scores": {name: 6 for name in SCORE_FIELDS},
    }
    base.update(overrides)
    return base


def validate_opps(items, max_items=5, rejected=None):
    return validate.validate_opportunities(
        {"opportunities": items}, today=TODAY, max_age_days=90, max_items=max_items,
        rejected=rejected if rejected is not None else [])


def test_a_good_opportunity_passes():
    out = validate_opps([opportunity()])
    assert len(out) == 1
    assert out[0].has_individual_evidence


def test_an_opportunity_with_no_surviving_evidence_is_dropped():
    """This is the rule that keeps plausible-sounding nothing out of the email."""
    rejected = []
    out = validate_opps([opportunity(evidence=[evidence(source_url="")])],
                        rejected=rejected)
    assert out == []
    assert any("DROPPED — no evidence survived" in reason for reason in rejected)


def test_an_opportunity_with_no_evidence_at_all_is_dropped():
    assert validate_opps([opportunity(evidence=[])]) == []


def test_missing_individual_evidence_is_kept_but_visible():
    """An absent individual-earnings field is a finding, not a reason to drop."""
    out = validate_opps([opportunity(individual_earnings_evidence="")])
    assert len(out) == 1
    assert not out[0].has_individual_evidence


def test_out_of_range_scores_drop_the_opportunity():
    rejected = []
    out = validate_opps([opportunity(scores={**{n: 6 for n in SCORE_FIELDS},
                                             "personal_fit": 47})], rejected=rejected)
    assert out == []
    assert any("outside 1-10" in reason for reason in rejected)


def test_missing_scores_drop_the_opportunity():
    scores = {n: 6 for n in SCORE_FIELDS}
    del scores["risk"]
    assert validate_opps([opportunity(scores=scores)]) == []


def test_score_reasons_survive_for_the_report():
    out = validate_opps([opportunity(scores={
        **{n: 6 for n in SCORE_FIELDS},
        "reasons": {"personal_fit": "requires a licence they do not hold"}})])
    assert out[0].scores.reasons["personal_fit"].startswith("requires a licence")


def test_the_item_limit_is_enforced():
    rejected = []
    items = [opportunity(slug=f"item-{i}", title=f"Item {i}") for i in range(8)]
    out = validate_opps(items, max_items=5, rejected=rejected)
    assert len(out) == 5
    assert any("over the 5-item limit" in reason for reason in rejected)


def test_duplicate_slugs_are_dropped():
    out = validate_opps([opportunity(), opportunity()])
    assert len(out) == 1


def test_a_slug_is_derived_when_missing():
    out = validate_opps([opportunity(slug="", title="Mobile Coffee Rounds!")])
    assert out[0].slug == "mobile-coffee-rounds"


def test_best_source_strength_prefers_the_strongest():
    out = validate_opps([opportunity(evidence=[
        evidence(source_url="https://medium.com/@x/post", source_strength="weak"),
        evidence(source_strength="primary"),
    ])])
    assert out[0].best_source_strength == "primary"


def test_an_all_weak_opportunity_reports_weak():
    out = validate_opps([opportunity(evidence=[
        evidence(source_url="https://medium.com/@x/post", source_strength="primary")])])
    assert out[0].best_source_strength == "weak"


# ---------------------------------------------------------------------------
# Actions
# ---------------------------------------------------------------------------


def test_an_action_over_three_hours_is_rejected():
    rejected = []
    actions = validate.validate_actions(
        {"actions": [{"title": "Build a whole website", "est_minutes": 600}]},
        max_minutes=180, rejected=rejected)
    assert actions == []
    assert "exceeds the 180-minute limit" in rejected[0]


def test_actions_are_capped_at_three_and_ranked():
    actions = validate.validate_actions(
        {"actions": [{"title": f"Do thing {i}", "est_minutes": 60} for i in range(6)]},
        max_minutes=180, rejected=[])
    assert len(actions) == 3
    assert [a.rank for a in actions] == [1, 2, 3]


def test_an_action_without_a_time_estimate_is_rejected():
    rejected = []
    assert validate.validate_actions({"actions": [{"title": "Vague thing"}]},
                                     max_minutes=180, rejected=rejected) == []
    assert "no usable time estimate" in rejected[0]


def test_fewer_than_three_actions_is_allowed():
    actions = validate.validate_actions(
        {"actions": [{"title": "One good thing", "est_minutes": 45}]},
        max_minutes=180, rejected=[])
    assert len(actions) == 1


# ---------------------------------------------------------------------------
# News alerts and summary
# ---------------------------------------------------------------------------


def news(**overrides):
    base = {"rule": "rate_decision", "subject": "RBA",
            "headline": "RBA holds at 4.35%", "detail": "...",
            "source_url": "https://www.rba.gov.au/media-releases/2026/mr-26-20.html",
            "source_date": "2026-09-20", "severity": "urgent"}
    base.update(overrides)
    return base


def test_a_recent_sourced_alert_passes():
    alerts = validate.validate_news_alerts({"alerts": [news()]}, today=TODAY, rejected=[])
    assert len(alerts) == 1 and alerts[0].severity == "urgent"


def test_stale_news_is_not_news():
    rejected = []
    alerts = validate.validate_news_alerts({"alerts": [news(source_date="2026-07-01")]},
                                           today=TODAY, rejected=rejected)
    assert alerts == []
    assert "not recent enough" in rejected[0]


def test_an_unsourced_alert_never_wakes_anyone():
    rejected = []
    assert validate.validate_news_alerts({"alerts": [news(source_url="")]},
                                         today=TODAY, rejected=rejected) == []
    assert "no usable source URL" in rejected[0]


def test_an_empty_alert_list_is_the_normal_case():
    assert validate.validate_news_alerts({"alerts": []}, today=TODAY, rejected=[]) == []


def test_summary_is_capped_at_three_lines():
    assert len(validate.validate_summary({"summary": ["a", "b", "c", "d"]})) == 3


def test_summary_accepts_a_single_string():
    assert validate.validate_summary({"summary": "one\ntwo"}) == ["one", "two"]


def test_malformed_payloads_do_not_raise():
    for junk in (None, [], "text", {"themes": "not a list"}, {"opportunities": None}):
        assert validate.validate_theme_updates(junk, [], today=TODAY, rejected=[]) == []
        assert validate.validate_opportunities(junk, today=TODAY, max_age_days=90,
                                               max_items=5, rejected=[]) == []
        assert validate.validate_summary(junk) == []
