"""Match abbreviated draw names ("A Zverev", "JM Cerúndolo") to the full
player names used in the Tennis Abstract Elo tables ("Alexander Zverev").

Wikipedia draw templates always format a player as "{initials} {surname...}"
-- a single space separates the abbreviated given name(s) from the full
(possibly multi-word) surname. We exploit that: the number of words in the
draw surname tells us how many trailing words of a candidate Elo full name
to treat as the surname, then we check the remaining leading words' initials
match.
"""
from __future__ import annotations

import csv
import unicodedata
from pathlib import Path


def fold(s: str) -> str:
    s = unicodedata.normalize("NFKD", s)
    s = "".join(c for c in s if not unicodedata.combining(c))
    return s.lower().strip()


def load_elo_table(path: Path) -> list[dict]:
    with open(path, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


class NameMatcher:
    def __init__(self, elo_rows: list[dict]):
        self.rows = elo_rows
        # precompute folded word lists
        self._words = [fold(r["player"]).split() for r in elo_rows]

    def match(self, draw_name: str) -> dict | None:
        if not draw_name or " " not in draw_name:
            return self._match_single_word(draw_name)
        initials, surname = draw_name.split(" ", 1)
        initials_f = fold(initials).replace("-", "")
        surname_words = fold(surname).replace("-", " ").split()
        k = len(surname_words)

        best = None
        for row, words in zip(self.rows, self._words):
            words_flat = [w.replace("-", " ") for w in words]
            words_expanded = " ".join(words_flat).split()
            if len(words_expanded) <= k:
                continue
            candidate_surname = words_expanded[-k:]
            candidate_given = words_expanded[:-k]
            if candidate_surname != surname_words:
                continue
            cand_initials = "".join(w[0] for w in candidate_given)
            if cand_initials == initials_f or cand_initials.startswith(initials_f) or initials_f.startswith(cand_initials):
                return row
            best = best or row  # surname matched but initials imperfect; keep as weak fallback
        return best

    def _match_single_word(self, name: str) -> dict | None:
        if not name:
            return None
        target = fold(name)
        for row, words in zip(self.rows, self._words):
            if words and words[-1] == target:
                return row
        return None


FALLBACK_ELO = 1480.0  # rough estimate for players absent from the Elo table
                        # (qualifiers/lucky losers/wildcards outside the top ~550
                        # by recent match count) -- treated as below-average tour level


def resolve_rating(matcher: NameMatcher, draw_name: str) -> dict:
    row = matcher.match(draw_name)
    if row is None:
        return {
            "name": draw_name,
            "matched_name": None,
            "elo": FALLBACK_ELO,
            "helo": FALLBACK_ELO,
            "is_fallback": True,
        }
    helo = row.get("helo") or row.get("elo") or FALLBACK_ELO
    elo = row.get("elo") or FALLBACK_ELO
    return {
        "name": draw_name,
        "matched_name": row["player"],
        "elo": float(elo),
        "helo": float(helo),
        "is_fallback": False,
    }
