"""Elo-based match win-probability model.

Uses Tennis Abstract's published Elo ratings (see fetch_data.py): an overall
Elo plus a hard-court-specific Elo ("hElo") derived from each player's
hard-court match history. Since the US Open is played on hard courts, we
blend the two ratings, weighted toward the surface-specific number but
still informed by the larger-sample overall rating (hElo is noisier for
players with a thin hard-court sample).
"""
from __future__ import annotations

HARD_ELO_WEIGHT = 0.7  # weight on surface (hard-court) Elo vs overall Elo


def blended_rating(elo: float, helo: float, weight: float = HARD_ELO_WEIGHT) -> float:
    return weight * helo + (1 - weight) * elo


def win_probability(rating_a: float, rating_b: float) -> float:
    """Standard logistic Elo win probability for player A over player B."""
    return 1.0 / (1.0 + 10 ** ((rating_b - rating_a) / 400.0))


def match_win_probability(player_a: dict, player_b: dict) -> float:
    """player_a / player_b: dicts with 'elo' and 'helo' keys (see name_match.resolve_rating)."""
    ra = blended_rating(player_a["elo"], player_a["helo"])
    rb = blended_rating(player_b["elo"], player_b["helo"])
    return win_probability(ra, rb)
