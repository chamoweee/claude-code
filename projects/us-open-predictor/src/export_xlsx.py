"""Export the round-by-round US Open predictions to a formatted Excel workbook.

Usage:
    python3 src/export_xlsx.py [--sims 20000] [--out ../predictions/us_open_2026_predictions.xlsx]
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from openpyxl import Workbook
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter
from openpyxl.worksheet.worksheet import Worksheet

from bracket_sim import ROUND_REACHED, build_initial_bracket, predict_next_round_matches, simulate
from name_match import NameMatcher, load_elo_table, resolve_rating
from predict import DRAWS, build_ratings

DATA_DIR = Path(__file__).resolve().parent.parent / "data"

FONT_NAME = "Arial"
HEADER_FILL = PatternFill("solid", fgColor="1F4E78")
HEADER_FONT = Font(name=FONT_NAME, bold=True, color="FFFFFF", size=10)
TITLE_FONT = Font(name=FONT_NAME, bold=True, size=14)
SUBTITLE_FONT = Font(name=FONT_NAME, italic=True, size=9, color="555555")
BODY_FONT = Font(name=FONT_NAME, size=10)
BOLD_BODY_FONT = Font(name=FONT_NAME, size=10, bold=True)
FALLBACK_FONT = Font(name=FONT_NAME, size=10, italic=True, color="B45309")
THIN = Side(style="thin", color="D9D9D9")
BORDER = Border(left=THIN, right=THIN, top=THIN, bottom=THIN)
STRIPE_FILL = PatternFill("solid", fgColor="F2F6FA")
PCT_FMT = "0.0%"


def style_header_row(ws: Worksheet, row: int, ncols: int):
    for c in range(1, ncols + 1):
        cell = ws.cell(row=row, column=c)
        cell.font = HEADER_FONT
        cell.fill = HEADER_FILL
        cell.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
        cell.border = BORDER


def autosize(ws: Worksheet, widths: list[int]):
    for i, w in enumerate(widths, start=1):
        ws.column_dimensions[get_column_letter(i)].width = w


def write_pending_sheet(ws: Worksheet, label: str, pending: list[dict], fetched_at: str):
    ws["A1"] = f"{label} -- Pending Match Predictions"
    ws["A1"].font = TITLE_FONT
    ws["A2"] = f"Data snapshot: {fetched_at}  |  Model: 70% hard-court Elo / 30% overall Elo (Tennis Abstract), logistic win probability"
    ws["A2"].font = SUBTITLE_FONT
    ws.merge_cells("A1:F1")
    ws.merge_cells("A2:F2")

    headers = ["Round", "Player 1", "Player 2", "Predicted Winner", "Win Probability", "Margin"]
    header_row = 4
    for c, h in enumerate(headers, start=1):
        ws.cell(row=header_row, column=c, value=h)
    style_header_row(ws, header_row, len(headers))

    r = header_row + 1
    for m in pending:
        p1 = f"({m['p1_seed']}) {m['p1']}" if m["p1_seed"] else m["p1"]
        p2 = f"({m['p2_seed']}) {m['p2']}" if m["p2_seed"] else m["p2"]
        vals = [m["round"], p1, p2, m["predicted_winner"], m["win_probability"], m["win_probability"] - 0.5]
        for c, v in enumerate(vals, start=1):
            cell = ws.cell(row=r, column=c, value=v)
            cell.font = BOLD_BODY_FONT if c == 4 else BODY_FONT
            cell.border = BORDER
            if c in (5, 6):
                cell.number_format = PCT_FMT
                cell.alignment = Alignment(horizontal="center")
            if r % 2 == 0:
                cell.fill = STRIPE_FILL
        r += 1

    if not pending:
        ws.cell(row=r, column=1, value="No matches currently pending in this data snapshot.").font = BODY_FONT

    ws.freeze_panes = f"A{header_row + 1}"
    ws.auto_filter.ref = f"A{header_row}:F{r - 1}" if pending else f"A{header_row}:F{header_row}"
    autosize(ws, [16, 26, 26, 22, 15, 10])


def write_bracket_sheet(ws: Worksheet, label: str, bracket_order, ratings, sim_results, fetched_at: str):
    ws["A1"] = f"{label} -- Full Draw Championship Probabilities"
    ws["A1"].font = TITLE_FONT
    ws["A2"] = f"Data snapshot: {fetched_at}  |  {len(bracket_order)}-player draw, ranked by simulated title probability (20,000-trial Monte Carlo)"
    ws["A2"].font = SUBTITLE_FONT
    ws.merge_cells("A1:K1")
    ws.merge_cells("A2:K2")

    headers = ["Rank", "Seed", "Player", "Matched Elo Name", "Overall Elo", "Hard-Court Elo"] + ROUND_REACHED
    header_row = 4
    for c, h in enumerate(headers, start=1):
        ws.cell(row=header_row, column=c, value=h)
    style_header_row(ws, header_row, len(headers))

    ranked = sorted(
        bracket_order,
        key=lambda p: sim_results[p["name"]]["Champion"],
        reverse=True,
    )

    r = header_row + 1
    for i, p in enumerate(ranked, start=1):
        name = p["name"]
        rating = ratings[name]
        probs = sim_results[name]
        row_vals = [i, p["seed"] or "", name, rating["matched_name"] or "(no match -- fallback rating)", rating["elo"], rating["helo"]]
        row_vals += [probs[lbl] for lbl in ROUND_REACHED]
        for c, v in enumerate(row_vals, start=1):
            cell = ws.cell(row=r, column=c, value=v)
            cell.border = BORDER
            if c == 3:
                cell.font = BOLD_BODY_FONT
            elif c == 4 and rating["is_fallback"]:
                cell.font = FALLBACK_FONT
            else:
                cell.font = BODY_FONT
            if c in (5, 6):
                cell.number_format = "0.0"
                cell.alignment = Alignment(horizontal="center")
            if c >= 7:
                cell.number_format = PCT_FMT
                cell.alignment = Alignment(horizontal="center")
            if r % 2 == 0:
                cell.fill = STRIPE_FILL
        r += 1

    ws.freeze_panes = f"D{header_row + 1}"
    ws.auto_filter.ref = f"A{header_row}:{get_column_letter(len(headers))}{r - 1}"
    autosize(ws, [6, 6, 22, 24, 12, 14] + [13] * len(ROUND_REACHED))


def write_readme_sheet(ws: Worksheet, fetched_men: str, fetched_women: str):
    ws.sheet_view.showGridLines = False
    ws["A1"] = "2026 US Open -- Round-by-Round Winner Predictions"
    ws["A1"].font = Font(name=FONT_NAME, bold=True, size=16)
    lines = [
        "",
        "Model: Elo rating-based win probability, blending 70% hard-court Elo / 30% overall Elo",
        "(ratings published by Tennis Abstract), run through a 20,000-trial Monte Carlo",
        "simulation of the real 128-player bracket. Already-decided matches are applied",
        "deterministically; everything else is simulated from the win-probability model.",
        "",
        f"Men's draw snapshot fetched:   {fetched_men}",
        f"Women's draw snapshot fetched: {fetched_women}",
        "",
        "Sheets:",
        "  - Men Pending / Women Pending   : predicted winner + win probability for every",
        "                                    match not yet decided in the snapshot",
        "  - Men Full Draw / Women Full Draw: all 128 players per draw, ranked by simulated",
        "                                    championship probability, with the probability",
        "                                    of reaching every round from the Second Round",
        "                                    through Champion",
        "",
        "Notes:",
        "  - Players shown in orange under 'Matched Elo Name' were not found in the Tennis",
        "    Abstract Elo table (typically deep qualifiers/wildcards/lucky losers with too",
        "    few tracked tour-level matches) and were given a flat, below-average fallback",
        "    rating -- treat predictions involving them as lower-confidence.",
        "  - Probabilities are model estimates, not certainties -- a 65% favorite still",
        "    loses more than a third of the time in reality.",
        "  - Source code and methodology: projects/us-open-predictor/ in this repository.",
    ]
    for i, line in enumerate(lines, start=2):
        cell = ws.cell(row=i, column=1, value=line)
        cell.font = BODY_FONT
    autosize(ws, [95])


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--sims", type=int, default=20000)
    ap.add_argument("--out", default=None)
    args = ap.parse_args()

    out_path = Path(args.out) if args.out else Path(__file__).resolve().parent.parent / "predictions" / "us_open_2026_predictions.xlsx"

    wb = Workbook()
    wb.remove(wb.active)

    fetched = {}
    per_draw = {}
    for draw_key in ("men", "women"):
        cfg = DRAWS[draw_key]
        elo_rows = load_elo_table(DATA_DIR / cfg["elo_csv"])
        matcher = NameMatcher(elo_rows)
        draw_json = json.loads((DATA_DIR / cfg["draw_json"]).read_text(encoding="utf-8"))

        bracket_order, known_results = build_initial_bracket(draw_json)
        bracket_names = [p["name"] for p in bracket_order]
        ratings, _ = build_ratings(bracket_order, matcher)
        sim_results = simulate(bracket_names, known_results, ratings, n_sims=args.sims)
        pending = predict_next_round_matches(draw_json, ratings)

        fetched[draw_key] = draw_json.get("fetched_at", "?")
        per_draw[draw_key] = (bracket_order, ratings, sim_results, pending)

    readme_ws = wb.create_sheet("README")
    write_readme_sheet(readme_ws, fetched["men"], fetched["women"])

    for draw_key, label in (("men", "Men's Singles"), ("women", "Women's Singles")):
        bracket_order, ratings, sim_results, pending = per_draw[draw_key]
        pending_ws = wb.create_sheet(f"{label.split()[0]} Pending")
        write_pending_sheet(pending_ws, label, pending, fetched[draw_key])

        bracket_ws = wb.create_sheet(f"{label.split()[0]} Full Draw")
        write_bracket_sheet(bracket_ws, label, bracket_order, ratings, sim_results, fetched[draw_key])

    wb.save(out_path)
    print(f"Wrote {out_path}")


if __name__ == "__main__":
    main()
