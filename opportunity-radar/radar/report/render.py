"""Email rendering.

Written for a phone screen first, because that is where a 7am email is read.
That forces some constraints which are not negotiable in email clients:

* **Inline styles only.** Gmail strips or partially honours ``<style>`` blocks,
  and strips them hardest on mobile.
* **Tables for layout.** Flexbox and grid are unreliable across clients.
* **No external resources.** No web fonts, no images, no tracking pixels.
* **A real plain-text alternative**, not an afterthought — some clients show it,
  and it is what survives forwarding.

Wide data tables are the one thing that genuinely does not fit a phone, so the
macro and watchlist sections render as stacked rows rather than as columns that
would need horizontal scrolling.

There is no template engine here: the whole thing is string building with
mandatory escaping, which keeps the runtime dependency list at one package.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from html import escape
from typing import Any, Iterable, Sequence

MAX_WIDTH = 600

# Colours chosen to stay legible on both light and dark client backgrounds.
INK = "#1a1a1a"
MUTED = "#5f6b7a"
RULE = "#e3e8ee"
ACCENT = "#1b4d7a"
GOOD = "#1a7f4b"
BAD = "#b3261e"
WARN = "#8a5a00"

STATUS_COLOURS = {
    "NEW": ACCENT, "RISING": GOOD, "STABLE": MUTED, "FADING": WARN, "DEAD": BAD,
}

BASE_FONT = ("-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,"
             "'Helvetica Neue',Arial,sans-serif")


def _esc(value: Any) -> str:
    return escape(str(value if value is not None else ""), quote=True)


def _pct(value: float | None, digits: int = 1) -> str:
    return "n/a" if value is None else f"{value:+.{digits}f}%"


def _colour_for(value: float | None) -> str:
    if value is None:
        return MUTED
    if value > 0.05:
        return GOOD
    if value < -0.05:
        return BAD
    return MUTED


# ---------------------------------------------------------------------------
# What a report needs
# ---------------------------------------------------------------------------


@dataclass
class ReportData:
    sydney_date: str
    summary: list[str] = field(default_factory=list)
    macro: list[Any] = field(default_factory=list)          # MetricChange
    themes: list[dict[str, str]] = field(default_factory=list)
    actionable: list[tuple] = field(default_factory=list)   # (Opportunity, ScoreResult)
    other_leads: list[tuple] = field(default_factory=list)
    watchlist: list[dict[str, Any]] = field(default_factory=list)
    alerts: list[Any] = field(default_factory=list)
    actions: list[Any] = field(default_factory=list)
    spend_status: Any = None
    spend_breakdown: Sequence = ()
    sources: list[dict[str, str]] = field(default_factory=list)
    rejected: list[str] = field(default_factory=list)
    failures: list[str] = field(default_factory=list)
    budget_warning: str = ""


# ---------------------------------------------------------------------------
# Small HTML helpers
# ---------------------------------------------------------------------------


def _section(title: str, body: str, number: int | None = None) -> str:
    label = f"{number}. {title}" if number else title
    return (
        f'<tr><td style="padding:26px 20px 0 20px;">'
        f'<h2 style="margin:0 0 10px 0;font:600 17px/1.3 {BASE_FONT};'
        f'color:{INK};border-bottom:2px solid {RULE};padding-bottom:6px;">'
        f'{_esc(label)}</h2>{body}</td></tr>'
    )


def _paragraph(text: str, colour: str = INK, size: int = 15) -> str:
    return (f'<p style="margin:0 0 10px 0;font:400 {size}px/1.5 {BASE_FONT};'
            f'color:{colour};">{text}</p>')


def _stacked_row(label: str, value: str, meta: str = "") -> str:
    """One data row that stacks rather than forcing a horizontal scroll."""
    meta_html = (f'<div style="font:400 13px/1.4 {BASE_FONT};color:{MUTED};'
                 f'margin-top:2px;">{meta}</div>') if meta else ""
    return (
        f'<tr><td style="padding:9px 0;border-bottom:1px solid {RULE};">'
        f'<div style="font:600 15px/1.4 {BASE_FONT};color:{INK};">{label}</div>'
        f'<div style="font:400 15px/1.4 {BASE_FONT};color:{INK};margin-top:2px;">'
        f'{value}</div>{meta_html}</td></tr>'
    )


def _table(rows: Iterable[str]) -> str:
    return ('<table role="presentation" cellpadding="0" cellspacing="0" border="0" '
            f'width="100%" style="width:100%;border-collapse:collapse;">'
            f'{"".join(rows)}</table>')


def _pill(text: str, colour: str) -> str:
    return (f'<span style="display:inline-block;padding:2px 8px;border-radius:10px;'
            f'background:{colour};color:#ffffff;font:600 12px/1.6 {BASE_FONT};'
            f'letter-spacing:.3px;">{_esc(text)}</span>')


# ---------------------------------------------------------------------------
# Sections
# ---------------------------------------------------------------------------


def _summary_section(data: ReportData) -> str:
    if not data.summary:
        body = _paragraph("No summary was produced this week — see the notes at the "
                          "end of this email.", MUTED)
    else:
        body = "".join(
            f'<p style="margin:0 0 9px 0;font:400 16px/1.5 {BASE_FONT};color:{INK};">'
            f'<span style="color:{ACCENT};font-weight:700;">{i}.</span> {_esc(line)}</p>'
            for i, line in enumerate(data.summary, start=1))
    return _section("What changed this week", body, 1)


def _macro_section(data: ReportData) -> str:
    if not data.macro:
        return _section("Macro", _paragraph("No macro readings this week.", MUTED), 2)
    rows = []
    for change in data.macro:
        colour = _colour_for(change.pct_change)
        value = (f'{change.latest:,.4g} <span style="color:{MUTED};font-size:13px;">'
                 f'{_esc(change.unit)}</span>')
        if change.previous_date:
            meta = (f'<span style="color:{colour};font-weight:600;">'
                    f'{_esc(change.format_change())}</span> since '
                    f'{_esc(change.previous_date)}')
        else:
            meta = f'<span style="color:{MUTED};">first reading — no change yet</span>'
        label = _esc(change.label)
        if getattr(change, "is_proxy", False):
            label += (f' <span style="color:{WARN};font-size:12px;font-weight:600;">'
                      f'PROXY</span>')
        rows.append(_stacked_row(label, value, meta))
    note = ""
    if any(getattr(c, "is_proxy", False) for c in data.macro):
        note = _paragraph(
            "A PROXY row is a stand-in series, not the underlying price — there is "
            "no free feed for it. Treat it as directional only.", MUTED, 13)
    return _section("Macro snapshot", _table(rows) + note, 2)


def _themes_section(data: ReportData) -> str:
    if not data.themes:
        return _section("Tracked themes",
                        _paragraph("No theme updates this week.", MUTED), 3)
    rows = []
    for theme in data.themes:
        status = theme.get("status", "STABLE")
        pill = _pill(status, STATUS_COLOURS.get(status, MUTED))
        rows.append(
            f'<tr><td style="padding:10px 0;border-bottom:1px solid {RULE};">'
            f'<div style="font:600 15px/1.4 {BASE_FONT};color:{INK};">'
            f'{pill} &nbsp;{_esc(theme.get("title", theme.get("slug", "")))}</div>'
            f'<div style="font:400 14px/1.5 {BASE_FONT};color:{MUTED};margin-top:4px;">'
            f'{_esc(theme.get("reason", ""))}</div></td></tr>')
    return _section("Tracked themes", _table(rows), 3)


def _evidence_list(evidence: Iterable[Any]) -> str:
    items = []
    for item in evidence:
        colour = {"primary": GOOD, "reputable_media": ACCENT}.get(
            item.source_strength, WARN)
        items.append(
            f'<li style="margin:0 0 6px 0;font:400 13px/1.5 {BASE_FONT};color:{MUTED};">'
            f'<span style="color:{colour};font-weight:600;">'
            f'{_esc(item.source_strength.replace("_", " "))}</span> — '
            f'{_esc(item.claim)}'
            + (f' <strong style="color:{INK};">{_esc(item.number_value)}</strong>'
               if item.number_value else "")
            + f'<br><a href="{_esc(item.source_url)}" '
              f'style="color:{ACCENT};text-decoration:underline;word-break:break-all;">'
              f'{_esc(item.source_name)}</a>, {_esc(item.source_date)}</li>')
    return (f'<ul style="margin:8px 0 0 0;padding-left:18px;">{"".join(items)}</ul>'
            if items else "")


def _opportunity_card(opportunity: Any, result: Any, scoring_rows: list) -> str:
    score_cells = "".join(
        f'<tr><td style="padding:3px 10px 3px 0;font:400 13px/1.5 {BASE_FONT};'
        f'color:{MUTED};white-space:nowrap;">{_esc(label)}</td>'
        f'<td style="padding:3px 8px 3px 0;font:700 13px/1.5 {BASE_FONT};'
        f'color:{INK};">{score}/10</td>'
        f'<td style="padding:3px 0;font:400 13px/1.5 {BASE_FONT};color:{MUTED};">'
        f'{_esc(reason)}</td></tr>'
        for label, score, reason in scoring_rows)

    individual = opportunity.individual_earnings_evidence
    if individual:
        individual_html = (f'<span style="color:{GOOD};font-weight:600;">'
                           f'Individuals:</span> {_esc(individual)}')
    else:
        individual_html = (f'<span style="color:{BAD};font-weight:600;">'
                           f'Individuals: no evidence found that individuals '
                           f'actually earn from this.</span>')

    blocks = [
        f'<div style="font:700 17px/1.35 {BASE_FONT};color:{INK};margin:0 0 4px 0;">'
        f'{result.total:.1f}/10 &nbsp;{_esc(opportunity.title)}</div>',
        _paragraph(_esc(opportunity.summary), INK, 14),
    ]
    if opportunity.who_earns:
        blocks.append(_paragraph(
            f'<span style="font-weight:600;">Who earns:</span> '
            f'{_esc(opportunity.who_earns)}', MUTED, 14))
    if opportunity.platform_revenue_evidence:
        blocks.append(_paragraph(
            f'<span style="font-weight:600;">Platform:</span> '
            f'{_esc(opportunity.platform_revenue_evidence)}', MUTED, 14))
    blocks.append(_paragraph(individual_html, MUTED, 14))

    facts = []
    if opportunity.startup_cost_aud_max is not None:
        facts.append(f"Startup ${opportunity.startup_cost_aud_min or 0:,.0f}–"
                     f"${opportunity.startup_cost_aud_max:,.0f} AUD")
    if opportunity.time_to_first_dollar_days is not None:
        facts.append(f"First dollar ~{opportunity.time_to_first_dollar_days} days")
    if opportunity.saturation:
        facts.append(f"Saturation: {opportunity.saturation}")
    if opportunity.au_eligibility:
        facts.append(f"AU access: {opportunity.au_eligibility}")
    if facts:
        blocks.append(_paragraph(" · ".join(_esc(f) for f in facts), MUTED, 13))

    if opportunity.red_flags:
        blocks.append(
            f'<p style="margin:0 0 10px 0;padding:8px 10px;background:#fdf1f0;'
            f'border-left:3px solid {BAD};font:400 13px/1.5 {BASE_FONT};color:{INK};">'
            f'<strong>Red flags:</strong> {_esc(opportunity.red_flags)}</p>')

    if result.was_capped:
        blocks.append(
            f'<p style="margin:0 0 10px 0;padding:8px 10px;background:#fdf8ec;'
            f'border-left:3px solid {WARN};font:400 13px/1.5 {BASE_FONT};color:{INK};">'
            f'<strong>Score held down:</strong> {_esc(result.capped_reason)} '
            f'(uncapped it would score {result.raw_total:.1f}).</p>')

    blocks.append(f'<table role="presentation" cellpadding="0" cellspacing="0" '
                  f'border="0" style="margin:6px 0 0 0;">{score_cells}</table>')
    blocks.append(_evidence_list(opportunity.evidence))

    return (f'<div style="margin:0 0 20px 0;padding:14px;border:1px solid {RULE};'
            f'border-radius:8px;">{"".join(blocks)}</div>')


def _opportunities_section(data: ReportData, scoring_rows_for) -> str:
    if not data.actionable:
        body = _paragraph(
            "Nothing new cleared the evidence bar for you this week. That usually "
            "means the candidates found were unsourced or too old, not that nothing "
            "exists — see the discarded list at the end.", MUTED)
    else:
        body = "".join(_opportunity_card(o, r, scoring_rows_for(o, r))
                       for o, r in data.actionable)
    return _section("New opportunities for you", body, 4)


def _other_leads_section(data: ReportData, scoring_rows_for) -> str:
    if not data.other_leads:
        return ""
    intro = _paragraph(
        "Real trends with good evidence that do not fit your hours, capital or "
        "skills. Reported because a trend you cannot act on today is still worth "
        "knowing about — it may be investable, or it may fit later.", MUTED, 14)
    body = intro + "".join(_opportunity_card(o, r, scoring_rows_for(o, r))
                           for o, r in data.other_leads)
    return _section("Real, but not a fit for you right now", body, 5)


def _watchlist_section(data: ReportData, number: int) -> str:
    blocks = []
    if data.alerts:
        alert_rows = "".join(
            f'<tr><td style="padding:8px 10px;background:#fdf1f0;border-left:3px '
            f'solid {BAD};font:400 14px/1.5 {BASE_FONT};color:{INK};">'
            f'<strong>{_esc(getattr(a, "headline", ""))}</strong></td></tr>'
            for a in data.alerts)
        blocks.append(_table([alert_rows]))
    if data.watchlist:
        rows = []
        for item in data.watchlist:
            pct = item.get("pct_change")
            colour = _colour_for(pct)
            value = (f'{item.get("close", 0):,.2f} '
                     f'<span style="color:{MUTED};font-size:13px;">'
                     f'{_esc(item.get("currency", ""))}</span> '
                     f'<span style="color:{colour};font-weight:600;">{_pct(pct)}</span>')
            rows.append(_stacked_row(_esc(item.get("symbol", "")), value,
                                     _esc(item.get("note", ""))))
        blocks.append(_table(rows))
    if not blocks:
        blocks.append(_paragraph("No watchlist quotes this week.", MUTED))
    blocks.append(_paragraph(
        "Research leads only — not advice. Prices are end-of-day closes from a "
        "data aggregator and can be wrong or stale.", MUTED, 12))
    return _section("Watchlist", "".join(blocks), number)


def _actions_section(data: ReportData, number: int) -> str:
    if not data.actions:
        body = _paragraph("No actions this week. Nothing found was worth your "
                          "evening.", MUTED)
    else:
        rows = []
        for action in data.actions:
            rows.append(
                f'<tr><td style="padding:11px 0;border-bottom:1px solid {RULE};">'
                f'<div style="font:600 15px/1.4 {BASE_FONT};color:{INK};">'
                f'<span style="color:{ACCENT};">{action.rank}.</span> '
                f'{_esc(action.title)} '
                f'<span style="color:{MUTED};font-weight:400;font-size:13px;">'
                f'({action.est_minutes} min)</span></div>'
                f'<div style="font:400 14px/1.5 {BASE_FONT};color:{MUTED};'
                f'margin-top:3px;">{_esc(action.why)}</div></td></tr>')
        body = _table(rows)
    return _section("Your top actions this week", body, number)


def _spend_section(data: ReportData, number: int) -> str:
    blocks = []
    if data.spend_status is not None:
        st = data.spend_status
        colour = BAD if st.fraction_used >= 0.8 else MUTED
        blocks.append(_paragraph(
            f'<span style="color:{colour};font-weight:600;">'
            f'${st.spent_aud:.2f} of ${st.cap_aud:.2f} AUD</span> used in '
            f'{_esc(st.month)} ({st.fraction_used * 100:.0f}%). '
            f'Runs halt automatically at the cap.', MUTED, 14))
    if data.budget_warning:
        blocks.append(_paragraph(_esc(data.budget_warning), BAD, 14))
    if data.spend_breakdown:
        rows = "".join(
            f'<tr><td style="padding:3px 12px 3px 0;font:400 13px/1.5 {BASE_FONT};'
            f'color:{MUTED};">{_esc(row["purpose"] or "other")}</td>'
            f'<td style="padding:3px 0;font:400 13px/1.5 {BASE_FONT};color:{INK};">'
            f'${row["aud"]:.2f}</td></tr>' for row in data.spend_breakdown)
        blocks.append(f'<table role="presentation" cellpadding="0" cellspacing="0" '
                      f'border="0">{rows}</table>')

    if data.sources:
        links = "".join(
            f'<li style="margin:0 0 4px 0;font:400 12px/1.5 {BASE_FONT};">'
            f'<a href="{_esc(s.get("url", ""))}" style="color:{ACCENT};'
            f'word-break:break-all;">{_esc(s.get("name") or s.get("url", ""))}</a></li>'
            for s in data.sources[:40])
        blocks.append(
            f'<p style="margin:14px 0 4px 0;font:600 14px/1.4 {BASE_FONT};'
            f'color:{INK};">Sources consulted ({len(data.sources)})</p>'
            f'<ul style="margin:0;padding-left:18px;">{links}</ul>')

    if data.rejected:
        items = "".join(
            f'<li style="margin:0 0 3px 0;font:400 12px/1.5 {BASE_FONT};'
            f'color:{MUTED};">{_esc(reason)}</li>' for reason in data.rejected[:25])
        blocks.append(
            f'<p style="margin:14px 0 4px 0;font:600 14px/1.4 {BASE_FONT};'
            f'color:{INK};">Discarded for weak sourcing ({len(data.rejected)})</p>'
            f'<ul style="margin:0;padding-left:18px;">{items}</ul>')

    if data.failures:
        items = "".join(
            f'<li style="margin:0 0 3px 0;font:400 12px/1.5 {BASE_FONT};'
            f'color:{BAD};">{_esc(failure)}</li>' for failure in data.failures)
        blocks.append(
            f'<p style="margin:14px 0 4px 0;font:600 14px/1.4 {BASE_FONT};'
            f'color:{BAD};">Parts of this run failed</p>'
            f'<ul style="margin:0;padding-left:18px;">{items}</ul>')

    return _section("Spend and sources", "".join(blocks), number)


# ---------------------------------------------------------------------------
# Whole documents
# ---------------------------------------------------------------------------


def _shell(title: str, preheader: str, body: str, footer: str) -> str:
    return f"""<!DOCTYPE html>
<html lang="en"><head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="color-scheme" content="light dark">
<title>{_esc(title)}</title>
</head>
<body style="margin:0;padding:0;background:#f4f6f8;-webkit-text-size-adjust:100%;">
<div style="display:none;max-height:0;overflow:hidden;opacity:0;">{_esc(preheader)}</div>
<table role="presentation" cellpadding="0" cellspacing="0" border="0" width="100%"
       style="background:#f4f6f8;">
<tr><td align="center" style="padding:16px 8px;">
<table role="presentation" cellpadding="0" cellspacing="0" border="0" width="{MAX_WIDTH}"
       style="width:100%;max-width:{MAX_WIDTH}px;background:#ffffff;border-radius:10px;
              overflow:hidden;">
{body}
<tr><td style="padding:22px 20px 26px 20px;border-top:1px solid {RULE};
               font:400 12px/1.6 {BASE_FONT};color:{MUTED};">{footer}</td></tr>
</table></td></tr></table></body></html>"""


def _header(title: str, subtitle: str) -> str:
    return (f'<tr><td style="padding:22px 20px 0 20px;">'
            f'<div style="font:700 21px/1.25 {BASE_FONT};color:{INK};">{_esc(title)}</div>'
            f'<div style="font:400 13px/1.5 {BASE_FONT};color:{MUTED};margin-top:3px;">'
            f'{_esc(subtitle)}</div></td></tr>')


FOOTER = ("Opportunity Radar is a private research agent. Everything here is a "
          "research lead, not financial advice, and every figure can be wrong — "
          "follow the source links before acting on anything. The agent does not "
          "trade, buy, publish, create accounts or contact anyone.")


def render_weekly_html(data: ReportData, scoring_rows_for) -> str:
    """The Monday report. Always sent, even in a quiet week.

    A missing Monday email should mean something is broken, never that nothing
    happened — so a quiet week still carries the macro table, theme statuses,
    watchlist and spend, and says plainly that little moved.
    """
    other = _other_leads_section(data, scoring_rows_for)
    watchlist_number = 6 if other else 5
    body = (
        _header("Opportunity Radar", f"Weekly deep scan · {data.sydney_date} Sydney")
        + _summary_section(data)
        + _macro_section(data)
        + _themes_section(data)
        + _opportunities_section(data, scoring_rows_for)
        + other
        + _watchlist_section(data, watchlist_number)
        + _actions_section(data, watchlist_number + 1)
        + _spend_section(data, watchlist_number + 2)
    )
    preheader = data.summary[0] if data.summary else "Weekly research briefing"
    return _shell(f"Opportunity Radar — {data.sydney_date}", preheader, body, FOOTER)


def render_weekly_text(data: ReportData) -> str:
    lines = [f"OPPORTUNITY RADAR — weekly deep scan, {data.sydney_date} Sydney", ""]
    lines += ["WHAT CHANGED THIS WEEK"]
    lines += [f"  {i}. {line}" for i, line in enumerate(data.summary, 1)] or \
             ["  (no summary produced)"]

    lines += ["", "MACRO"]
    for change in data.macro:
        proxy = " [PROXY]" if getattr(change, "is_proxy", False) else ""
        since = (f"{change.format_change()} since {change.previous_date}"
                 if change.previous_date else "first reading")
        lines.append(f"  {change.label}{proxy}: {change.latest:,.4g} "
                     f"{change.unit} ({since})")

    lines += ["", "THEMES"]
    for theme in data.themes:
        lines.append(f"  [{theme.get('status', '')}] "
                     f"{theme.get('title', theme.get('slug', ''))} — "
                     f"{theme.get('reason', '')}")

    for heading, group in (("NEW OPPORTUNITIES FOR YOU", data.actionable),
                           ("REAL, BUT NOT A FIT RIGHT NOW", data.other_leads)):
        if not group:
            continue
        lines += ["", heading]
        for opportunity, result in group:
            lines.append(f"  {result.total:.1f}/10  {opportunity.title}")
            lines.append(f"    {opportunity.summary}")
            lines.append(f"    Platform: {opportunity.platform_revenue_evidence or '—'}")
            lines.append(f"    Individuals: "
                         f"{opportunity.individual_earnings_evidence or 'NO EVIDENCE FOUND'}")
            if result.was_capped:
                lines.append(f"    Score held down: {result.capped_reason}")
            for item in opportunity.evidence:
                lines.append(f"    [{item.source_strength}] {item.claim} — "
                             f"{item.source_name}, {item.source_date}")
                lines.append(f"      {item.source_url}")

    lines += ["", "WATCHLIST"]
    for item in data.watchlist:
        lines.append(f"  {item.get('symbol', '')}: {item.get('close', 0):,.2f} "
                     f"{item.get('currency', '')} {_pct(item.get('pct_change'))}")

    lines += ["", "YOUR TOP ACTIONS"]
    for action in data.actions:
        lines.append(f"  {action.rank}. {action.title} ({action.est_minutes} min)")
        lines.append(f"     {action.why}")

    if data.spend_status is not None:
        st = data.spend_status
        lines += ["", f"SPEND: ${st.spent_aud:.2f} of ${st.cap_aud:.2f} AUD in {st.month}"]
    if data.sources:
        lines += ["", f"SOURCES ({len(data.sources)})"]
        lines += [f"  {s.get('url', '')}" for s in data.sources[:40]]
    if data.rejected:
        lines += ["", f"DISCARDED FOR WEAK SOURCING ({len(data.rejected)})"]
        lines += [f"  - {reason}" for reason in data.rejected[:25]]

    lines += ["", FOOTER]
    return "\n".join(lines)


def render_alert_html(alerts: Sequence[Any], sydney_date: str) -> str:
    """The daily email. Only ever built when something actually fired."""
    cards = []
    for alert in alerts:
        severity = getattr(alert, "severity", "notable")
        colour = BAD if severity == "urgent" else WARN
        url = getattr(alert, "source_url", "")
        link = (f'<div style="margin-top:6px;"><a href="{_esc(url)}" '
                f'style="color:{ACCENT};font:400 13px/1.5 {BASE_FONT};'
                f'word-break:break-all;">{_esc(url)}</a></div>') if url else ""
        cards.append(
            f'<div style="margin:0 0 14px 0;padding:12px 14px;border-left:4px solid '
            f'{colour};background:#fbfbfc;">'
            f'{_pill(severity, colour)}'
            f'<div style="font:700 16px/1.4 {BASE_FONT};color:{INK};margin-top:7px;">'
            f'{_esc(getattr(alert, "headline", ""))}</div>'
            f'<div style="font:400 14px/1.5 {BASE_FONT};color:{MUTED};margin-top:4px;">'
            f'{_esc(getattr(alert, "detail", ""))}</div>{link}</div>')

    body = (_header("Opportunity Radar", f"Daily alert · {sydney_date} Sydney")
            + _section(f"{len(alerts)} alert{'s' if len(alerts) != 1 else ''} "
                       f"triggered", "".join(cards)))
    preheader = getattr(alerts[0], "headline", "Alert") if alerts else "Alert"
    return _shell(f"Radar alert — {sydney_date}", preheader, body, FOOTER)


def render_alert_text(alerts: Sequence[Any], sydney_date: str) -> str:
    lines = [f"OPPORTUNITY RADAR — daily alert, {sydney_date} Sydney", ""]
    for alert in alerts:
        lines.append(f"[{getattr(alert, 'severity', 'notable').upper()}] "
                     f"{getattr(alert, 'headline', '')}")
        if getattr(alert, "detail", ""):
            lines.append(f"  {alert.detail}")
        if getattr(alert, "source_url", ""):
            lines.append(f"  {alert.source_url}")
        lines.append("")
    lines.append(FOOTER)
    return "\n".join(lines)


def render_error_html(kind: str, sydney_date: str, errors: Sequence[str],
                      run_id: int | None = None) -> str:
    """The failure notice. Short on purpose — it exists so silence means silence."""
    items = "".join(
        f'<li style="margin:0 0 6px 0;font:400 13px/1.5 {BASE_FONT};color:{INK};'
        f'word-break:break-word;">{_esc(error)}</li>' for error in errors[:10])
    body = (
        _header("Opportunity Radar", f"Run failed · {sydney_date} Sydney")
        + _section(f"The {kind} run did not complete",
                   _paragraph(
                       "This notice exists so that a missing report always means "
                       "something broke, rather than leaving you guessing.", MUTED, 14)
                   + f'<ul style="margin:8px 0 0 0;padding-left:18px;">{items}</ul>'
                   + _paragraph(f"Run #{run_id}. Full detail is in the run log in "
                                f"data/radar.db.", MUTED, 13))
    )
    return _shell(f"Radar {kind} run failed — {sydney_date}",
                  "A scheduled run failed", body, FOOTER)


def render_error_text(kind: str, sydney_date: str, errors: Sequence[str],
                      run_id: int | None = None) -> str:
    lines = [f"OPPORTUNITY RADAR — {kind} run failed, {sydney_date} Sydney", ""]
    lines += [f"  - {error}" for error in errors[:10]]
    lines += ["", f"Run #{run_id}. Detail is in the run log in data/radar.db."]
    return "\n".join(lines)


def weekly_subject(data: ReportData) -> str:
    lead = data.summary[0] if data.summary else "Weekly research briefing"
    lead = lead[:70].rstrip(" .,;") + ("…" if len(lead) > 70 else "")
    return f"Radar {data.sydney_date}: {lead}"


def alert_subject(alerts: Sequence[Any], sydney_date: str) -> str:
    if len(alerts) == 1:
        return f"Radar alert: {getattr(alerts[0], 'headline', '')}"[:120]
    return f"Radar: {len(alerts)} alerts — {sydney_date}"
