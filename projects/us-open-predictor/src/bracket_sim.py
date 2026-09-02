"""Monte Carlo bracket simulator.

Given the 128-player initial draw order (fixed, from the actual US Open
bracket) plus whichever matches have already been decided in reality, this
simulates the rest of the tournament many times using the Elo win-probability
model, and tabulates how often each player reaches each round.

Already-decided matches are applied deterministically (looked up by the
*pair* of players involved, since the bracket's slot topology is fixed and a
given pair can only ever meet in the one slot reality put them in).
"""
from __future__ import annotations

import random
from collections import defaultdict

from elo_model import match_win_probability

ROUND_PLAYED = ["First round", "Second round", "Third round", "Fourth round", "Quarterfinals", "Semifinals", "Final"]
ROUND_REACHED = ["Second round", "Third round", "Fourth round", "Quarterfinals", "Semifinals", "Final", "Champion"]


def build_initial_bracket(draw_json: dict) -> tuple[list[dict], dict]:
    """Returns (bracket_order, known_results).

    bracket_order: list of 128 {'name', 'seed'} dicts in actual draw slot order.
    known_results: {frozenset({a, b}): winner_name} for every match already
    decided in the real tournament (any round).
    """
    by_section = defaultdict(list)
    for m in draw_json["section_matches"]:
        if m["round"] == "First round":
            by_section[m["section"]].append(m)

    bracket_order = []
    for section in sorted(by_section):
        for m in by_section[section]:
            bracket_order.append({"name": m["p1"], "seed": m["p1_seed"]})
            bracket_order.append({"name": m["p2"], "seed": m["p2_seed"]})

    known_results = {}
    for m in draw_json["section_matches"] + draw_json["final_matches"]:
        if m["winner"] and m["p1"] and m["p2"]:
            known_results[frozenset({m["p1"], m["p2"]})] = m["winner"]

    return bracket_order, known_results


def simulate(
    bracket_order: list[str],
    known_results: dict,
    ratings: dict,
    n_sims: int = 20000,
    seed: int = 42,
) -> dict:
    """Returns {player_name: {round_reached_label: probability}}."""
    rng = random.Random(seed)
    reach_counts = {name: defaultdict(int) for name in bracket_order}

    for _ in range(n_sims):
        current = list(bracket_order)
        for round_label, reached_label in zip(ROUND_PLAYED, ROUND_REACHED):
            winners = []
            for i in range(0, len(current), 2):
                a, b = current[i], current[i + 1]
                key = frozenset({a, b})
                if key in known_results:
                    w = known_results[key]
                else:
                    pa, pb = ratings[a], ratings[b]
                    p_a_wins = match_win_probability(pa, pb)
                    w = a if rng.random() < p_a_wins else b
                winners.append(w)
                reach_counts[w][reached_label] += 1
            current = winners

    result = {}
    for name in bracket_order:
        result[name] = {label: reach_counts[name][label] / n_sims for label in ROUND_REACHED}
    return result


def predict_next_round_matches(draw_json: dict, ratings: dict) -> list[dict]:
    """For every match in the current (first undecided) round, return the
    Elo-favored winner and win probability -- a direct point prediction,
    independent of the full Monte Carlo simulation."""
    predictions = []
    for m in draw_json["section_matches"] + draw_json["final_matches"]:
        if m["winner"] or not m["p1"] or not m["p2"]:
            continue
        pa, pb = ratings[m["p1"]], ratings[m["p2"]]
        p_a = match_win_probability(pa, pb)
        favored, prob = (m["p1"], p_a) if p_a >= 0.5 else (m["p2"], 1 - p_a)
        predictions.append(
            {
                "round": m["round"],
                "section": m["section"],
                "p1": m["p1"],
                "p1_seed": m["p1_seed"],
                "p2": m["p2"],
                "p2_seed": m["p2_seed"],
                "predicted_winner": favored,
                "win_probability": prob,
            }
        )
    return predictions
