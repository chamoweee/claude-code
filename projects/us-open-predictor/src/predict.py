"""Generate round-by-round US Open winner predictions for one draw (men's or
women's) from the fetched Elo ratings + bracket snapshot.

Usage:
    python3 src/predict.py --draw men   [--sims 20000] [--top 20]
    python3 src/predict.py --draw women
"""
from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path

from bracket_sim import ROUND_REACHED, build_initial_bracket, predict_next_round_matches, simulate
from name_match import NameMatcher, load_elo_table, resolve_rating

DATA_DIR = Path(__file__).resolve().parent.parent / "data"
OUT_DIR = Path(__file__).resolve().parent.parent / "predictions"

DRAWS = {
    "men": {"elo_csv": "atp_elo.csv", "draw_json": "mens_draw.json", "label": "Men's Singles"},
    "women": {"elo_csv": "wta_elo.csv", "draw_json": "womens_draw.json", "label": "Women's Singles"},
}


def build_ratings(bracket_order, matcher: NameMatcher) -> tuple[dict, list[str]]:
    ratings = {}
    fallback_names = []
    for p in bracket_order:
        r = resolve_rating(matcher, p["name"])
        ratings[p["name"]] = r
        if r["is_fallback"]:
            fallback_names.append(p["name"])
    return ratings, fallback_names


def fmt_pct(x: float) -> str:
    return f"{100 * x:.1f}%"


def generate_report(draw_key: str, n_sims: int, top_n: int) -> str:
    cfg = DRAWS[draw_key]
    elo_rows = load_elo_table(DATA_DIR / cfg["elo_csv"])
    matcher = NameMatcher(elo_rows)
    draw_json = json.loads((DATA_DIR / cfg["draw_json"]).read_text(encoding="utf-8"))

    bracket_order_full, known_results = build_initial_bracket(draw_json)
    bracket_names = [p["name"] for p in bracket_order_full]
    seed_by_name = {p["name"]: p["seed"] for p in bracket_order_full}

    ratings, fallback_names = build_ratings(bracket_order_full, matcher)

    sim_results = simulate(bracket_names, known_results, ratings, n_sims=n_sims)
    pending = predict_next_round_matches(draw_json, ratings)

    lines = []
    lines.append(f"# 2026 US Open -- {cfg['label']}: Round-by-Round Predictions\n")
    lines.append(
        f"Generated from a snapshot fetched {draw_json.get('fetched_at', '?')} "
        f"(source: {draw_json.get('source', '?')}). Model: Elo win-probability "
        f"(70% hard-court Elo / 30% overall Elo, from Tennis Abstract) with a "
        f"{n_sims:,}-trial Monte Carlo bracket simulation. See `../README.md` for methodology.\n"
    )

    completed = sum(1 for m in draw_json["section_matches"] if m["round"] == "First round" and m["winner"])
    lines.append(f"First round completed so far: {completed}/64.\n")

    lines.append("## Predicted winners of currently pending matches\n")
    lines.append("| Round | Player 1 | Player 2 | Predicted winner | Win probability |")
    lines.append("|---|---|---|---|---|")
    for m in pending:
        p1 = f"({m['p1_seed']}) {m['p1']}" if m["p1_seed"] else m["p1"]
        p2 = f"({m['p2_seed']}) {m['p2']}" if m["p2_seed"] else m["p2"]
        lines.append(f"| {m['round']} | {p1} | {p2} | **{m['predicted_winner']}** | {fmt_pct(m['win_probability'])} |")
    if not pending:
        lines.append("| _none -- no matches currently pending in the snapshot_ | | | | |")
    lines.append("")

    lines.append(f"## Title contenders (top {top_n} by simulated championship probability)\n")
    header = "| Rank | Player | Seed | " + " | ".join(ROUND_REACHED) + " |"
    lines.append(header)
    lines.append("|---" * (2 + len(ROUND_REACHED)) + "|")
    ranked = sorted(sim_results.items(), key=lambda kv: kv[1]["Champion"], reverse=True)[:top_n]
    for i, (name, probs) in enumerate(ranked, start=1):
        seed = seed_by_name.get(name) or ""
        row = [str(i), name, seed] + [fmt_pct(probs[r]) for r in ROUND_REACHED]
        lines.append("| " + " | ".join(row) + " |")
    lines.append("")

    lines.append("## Predicted champion\n")
    champ_name, champ_probs = ranked[0]
    lines.append(f"**{champ_name}** -- {fmt_pct(champ_probs['Champion'])} simulated title probability.\n")

    if fallback_names:
        lines.append("## Data notes\n")
        lines.append(
            f"{len(fallback_names)} player(s) in this draw were not found in the Tennis Abstract "
            f"Elo table (usually qualifiers/wildcards with too few recent tour-level matches) and were "
            f"given a flat below-average fallback rating, so predictions involving them are lower-confidence: "
            + ", ".join(fallback_names)
            + "\n"
        )

    # full per-player CSV for reference
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    csv_stem = "mens" if draw_key == "men" else "womens"
    csv_path = OUT_DIR / f"{csv_stem}_full_probabilities.csv"
    with csv_path.open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["player", "seed", "matched_elo_name", "elo", "helo"] + ROUND_REACHED)
        for name in bracket_names:
            r = ratings[name]
            probs = sim_results[name]
            w.writerow(
                [name, seed_by_name.get(name) or "", r["matched_name"] or "", r["elo"], r["helo"]]
                + [f"{probs[lbl]:.4f}" for lbl in ROUND_REACHED]
            )

    lines.append(f"\nFull 128-player round-by-round probability table: `{csv_path.relative_to(OUT_DIR.parent)}`\n")

    return "\n".join(lines)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--draw", choices=["men", "women", "both"], default="both")
    ap.add_argument("--sims", type=int, default=20000)
    ap.add_argument("--top", type=int, default=20)
    args = ap.parse_args()

    draws = ["men", "women"] if args.draw == "both" else [args.draw]
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    for d in draws:
        report = generate_report(d, args.sims, args.top)
        out_path = OUT_DIR / ("mens_2026.md" if d == "men" else "womens_2026.md")
        out_path.write_text(report, encoding="utf-8")
        print(f"Wrote {out_path}")


if __name__ == "__main__":
    main()
