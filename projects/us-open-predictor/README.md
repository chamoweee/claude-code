# US Open Winner Predictor (2026, Men's & Women's)

Predicts the winner of every round of the US Open singles draws using an
Elo-rating model and a Monte Carlo bracket simulation, seeded with the real
current draw and results.

## How it works

1. **Ratings** (`src/fetch_data.py`): pulls the current ATP and WTA Elo
   ratings published by [Tennis Abstract](https://tennisabstract.com/reports/atp_elo_ratings.html)
   -- overall Elo plus a hard-court-specific Elo (`hElo`), computed from each
   player's actual match history. Since the US Open is a hard-court event,
   `src/elo_model.py` blends the two ratings 70% hard / 30% overall (the
   overall number smooths out noise for players with a thin hard-court
   sample) and converts the blended rating difference into a win probability
   with the standard logistic Elo formula.
2. **Draw** (`src/fetch_data.py`): parses the live Wikipedia draw page for
   `{year} US Open – Men's/Women's singles`, which is updated round by round
   as matches finish. The page embeds the bracket as structured template
   parameters (`RD1-team01`, `RD1-seed01`, ...), which we parse directly
   rather than scraping rendered text, so seeds and already-decided results
   come through exactly.
3. **Name matching** (`src/name_match.py`): the draw abbreviates players as
   `"{initials} {surname}"` (e.g. `"JM Cerúndolo"`); Elo tables use full
   names (`"Juan Manuel Cerundolo"`). Matched by surname + initials, accent-
   insensitive. Players who fall outside the Elo table's "10+ matches in the
   last 52 weeks" cutoff (mostly deep qualifiers/wildcards) get a flat
   below-average fallback rating -- flagged in each report's Data Notes.
4. **Simulation** (`src/bracket_sim.py`): the real 128-player bracket order
   is fixed; where the real match has already been played, that result is
   used deterministically (looked up by the pair of players, since the
   bracket topology means a given pair can only ever meet in one slot).
   Everything not yet played is simulated via the Elo win probability,
   20,000 times by default, tallying how often each player reaches each
   round.
5. **Report** (`src/predict.py`): writes `predictions/mens_2026.md` and
   `predictions/womens_2026.md` -- a point prediction (favorite + win
   probability) for every currently pending match, a title-contenders table
   with per-round probabilities, and a full 128-player CSV.

## Usage

```bash
pip install -r requirements.txt

# refresh data (re-run any time to pick up new results as the tournament progresses)
python3 src/fetch_data.py --year 2026

# generate predictions
python3 src/predict.py --draw both --sims 20000
```

Outputs land in `predictions/`.

## Limitations

- Elo captures overall/surface strength and recent form, not day-of factors:
  injuries, weather, scheduling, or head-to-head matchup quirks (e.g. a
  lefty who struggles specifically against a certain player's serve).
- Qualifiers/wildcards/lucky losers missing from the Elo table get a rough
  flat fallback rating -- predictions involving them carry more uncertainty
  (see each report's Data Notes section).
- The Wikipedia draw page is community-maintained; if a page hasn't been
  updated yet for a just-finished match, that match will still show as
  "pending" until the next `fetch_data.py` refresh.
- This is a single, fairly simple model (Elo + Monte Carlo), not an
  ensemble -- treat the probabilities as informative estimates, not
  certainties. A 65% favorite still loses more than a third of the time.
