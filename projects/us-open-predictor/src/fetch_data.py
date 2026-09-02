"""Fetch and snapshot the data this predictor needs.

Downloads:
  - ATP and WTA Elo ratings (overall + surface-specific) from Tennis Abstract
  - The men's and women's US Open singles draw pages from Wikipedia

and writes cleaned CSV/JSON snapshots into ../data/. Re-run this script to
refresh predictions as the tournament progresses (new results get filled
into the Wikipedia draw tables as matches finish).

Usage:
    python3 src/fetch_data.py --year 2026
"""
from __future__ import annotations

import argparse
import csv
import json
import re
import sys
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

from bs4 import BeautifulSoup

DATA_DIR = Path(__file__).resolve().parent.parent / "data"
UA = "Mozilla/5.0 (compatible; us-open-predictor/1.0)"


def fetch(url: str) -> str:
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=30) as resp:
        return resp.read().decode("utf-8", errors="ignore")


def save(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


# ---------------------------------------------------------------------------
# Elo ratings (Tennis Abstract)
# ---------------------------------------------------------------------------

def parse_elo_table(html: str) -> list[dict]:
    soup = BeautifulSoup(html, "lxml")
    table = soup.find_all("table")[2]
    rows = table.find_all("tr")
    out = []
    for r in rows[1:]:
        cells = [c.get_text(strip=True) for c in r.find_all(["th", "td"])]
        if len(cells) < 17:
            continue
        rank, player, age, elo, _, helo_rank, helo, celo_rank, celo, gelo_rank, gelo, _, peak, peakmonth, _, atprank, logdiff = cells[:17]
        player = player.replace("\xa0", " ")

        def f(x):
            try:
                return float(x)
            except ValueError:
                return None

        out.append(
            {
                "elo_rank": rank,
                "player": player,
                "age": age,
                "elo": f(elo),
                "helo": f(helo),  # hard-court Elo -- most relevant for the US Open
                "celo": f(celo),  # clay
                "gelo": f(gelo),  # grass
                "atp_rank": atprank,
            }
        )
    return out


def write_csv(rows: list[dict], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=["elo_rank", "player", "age", "elo", "helo", "celo", "gelo", "atp_rank"])
        w.writeheader()
        w.writerows(rows)


# ---------------------------------------------------------------------------
# Draw brackets (Wikipedia)
# ---------------------------------------------------------------------------

def clean_name(wt: str | None) -> str | None:
    if not wt:
        return None
    s = wt.replace("'''", "")
    s = re.sub(r"\{\{flagicon(?:\|[^}]*)?\}\}", "", s)

    def link_sub(m):
        inner = m.group(1)
        return inner.split("|", 1)[1] if "|" in inner else inner

    s = re.sub(r"\[\[([^\]]+)\]\]", link_sub, s)
    s = re.sub(r"<[^>]+>", "", s)
    s = s.strip()
    return s or None


def get_bracket_params(table_soup):
    dmw = json.loads(table_soup["data-mw"])
    for p in dmw.get("parts", []):
        if not isinstance(p, dict):
            continue
        tgt = p.get("template", {}).get("target", {}).get("wt", "").strip()
        if "TeamBracket" in tgt:
            return tgt, p.get("template", {}).get("params", {})
    return None, None


def parse_bracket_table(params: dict, size: int) -> dict:
    nrounds = size.bit_length() - 1
    rounds = {}
    for rd in range(1, nrounds + 1):
        nslots = size // (2 ** (rd - 1))
        teams = []
        for slot in range(1, nslots + 1):
            team_raw = params.get(f"RD{rd}-team{slot:02d}", {}).get("wt", "")
            seed_raw = params.get(f"RD{rd}-seed{slot:02d}", {}).get("wt", "")
            teams.append({"name": clean_name(team_raw), "seed": (seed_raw or "").strip() or None})
        rounds[rd] = teams
    return rounds, nrounds


ROUND_NAMES_SECTION = ["First round", "Second round", "Third round", "Fourth round"]
ROUND_NAMES_FINALS = ["Quarterfinals", "Semifinals", "Final"]


def build_matches(rounds: dict, nrounds: int, round_names: list[str], section) -> list[dict]:
    matches = []
    for rd in range(1, nrounds + 1):
        teams = rounds[rd]
        for i in range(0, len(teams), 2):
            p1, p2 = teams[i], teams[i + 1]
            winner = None
            if rd < nrounds:
                nxt = rounds[rd + 1][i // 2]
                if nxt["name"]:
                    if p1["name"] and nxt["name"] == p1["name"]:
                        winner = p1["name"]
                    elif p2["name"] and nxt["name"] == p2["name"]:
                        winner = p2["name"]
            matches.append(
                {
                    "section": section,
                    "round": round_names[rd - 1] if rd - 1 < len(round_names) else f"R{rd}",
                    "round_num": rd,
                    "p1": p1["name"],
                    "p1_seed": p1["seed"],
                    "p2": p2["name"],
                    "p2_seed": p2["seed"],
                    "winner": winner,
                }
            )
    return matches


def parse_draw(html: str) -> dict:
    soup = BeautifulSoup(html, "lxml")
    tables = soup.find_all("table", attrs={"data-mw": True})
    section_tables, final_table = [], None
    for t in tables:
        tgt, params = get_bracket_params(t)
        if not tgt:
            continue
        if tgt.startswith("16TeamBracket"):
            section_tables.append(params)
        elif tgt.startswith("8TeamBracket") or tgt.startswith("4TeamBracket"):
            final_table = params

    section_matches = []
    for idx, params in enumerate(section_tables, start=1):
        rounds, nrounds = parse_bracket_table(params, 16)
        section_matches.extend(build_matches(rounds, nrounds, ROUND_NAMES_SECTION, idx))

    final_matches = []
    if final_table is not None:
        rounds, nrounds = parse_bracket_table(final_table, 8)
        final_matches = build_matches(rounds, nrounds, ROUND_NAMES_FINALS, "FINALS")

    return {"section_matches": section_matches, "final_matches": final_matches}


# ---------------------------------------------------------------------------

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--year", type=int, default=datetime.now().year)
    ap.add_argument("--skip-raw", action="store_true", help="don't keep raw HTML snapshots")
    args = ap.parse_args()

    raw_dir = DATA_DIR / "raw"
    fetched_at = datetime.now(timezone.utc).isoformat()

    print("Fetching ATP Elo ratings...", file=sys.stderr)
    atp_html = fetch("https://tennisabstract.com/reports/atp_elo_ratings.html")
    if not args.skip_raw:
        save(raw_dir / "atp_elo.html", atp_html)
    write_csv(parse_elo_table(atp_html), DATA_DIR / "atp_elo.csv")

    print("Fetching WTA Elo ratings...", file=sys.stderr)
    wta_html = fetch("https://tennisabstract.com/reports/wta_elo_ratings.html")
    if not args.skip_raw:
        save(raw_dir / "wta_elo.html", wta_html)
    write_csv(parse_elo_table(wta_html), DATA_DIR / "wta_elo.csv")

    men_url = f"https://en.wikipedia.org/wiki/{args.year}_US_Open_%E2%80%93_Men%27s_singles"
    print(f"Fetching men's draw: {men_url}", file=sys.stderr)
    men_html = fetch(men_url)
    if not args.skip_raw:
        save(raw_dir / "mens_singles.html", men_html)
    men_draw = parse_draw(men_html)
    men_draw["fetched_at"] = fetched_at
    men_draw["source"] = men_url
    save(DATA_DIR / "mens_draw.json", json.dumps(men_draw, indent=2, ensure_ascii=False))

    women_url = f"https://en.wikipedia.org/wiki/{args.year}_US_Open_%E2%80%93_Women%27s_singles"
    print(f"Fetching women's draw: {women_url}", file=sys.stderr)
    women_html = fetch(women_url)
    if not args.skip_raw:
        save(raw_dir / "womens_singles.html", women_html)
    women_draw = parse_draw(women_html)
    women_draw["fetched_at"] = fetched_at
    women_draw["source"] = women_url
    save(DATA_DIR / "womens_draw.json", json.dumps(women_draw, indent=2, ensure_ascii=False))

    print("Done. Data written to", DATA_DIR, file=sys.stderr)


if __name__ == "__main__":
    main()
