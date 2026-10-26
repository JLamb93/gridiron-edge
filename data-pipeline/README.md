# Gridiron Edge data pipeline

Replaces hand-researched stats with real public data:

- **nflverse play-by-play** (`nflverse/nflverse-data`, `pbp` release) — every
  pass's field location and air yards, every sack/QB hit, every rush and
  catch. This is what makes the QB passing-tendency field and team defense
  stats real instead of modeled.
- **nflverse rosters + injuries** — current team/position/jersey number and
  the latest weekly injury report status (falls back to the last week that
  actually had Q/D/O designations, so an early-week practice-only report
  doesn't wipe everyone back to "Healthy").
- **ESPN's public standings + scoreboard JSON endpoints** — win/loss
  records, streaks, home/away splits. Each team's "next game" is resolved
  individually from how far its own play-by-play goes, so mid-week (a team
  that already played Thursday rolls over to next week; one that hasn't
  played yet, e.g. tonight's Monday game, still shows that game).

Pure standard library — no `pip install` needed.

## Running it

```
cd data-pipeline
python3 build_data.py
cp nfl_data.json ../nfl_data.json
```

Then commit and push `nfl_data.json` (from the repo root, next to
`index.html`) — GitHub Pages serves it as a static file and the site
`fetch()`s it at load. No other files need to change week to week.

## Editor's Picks

Edit `../editor_picks.json` (repo root) directly:

```json
{
  "source": "One line of context — a parlay's odds, a theme, whatever",
  "updatedAt": "2026-10-26T12:00:00Z",
  "picks": [
    {"playerName": "Drake Maye", "team": "NE", "propLabel": "Passing Yards", "pick": "over", "line": 200}
  ]
}
```

`playerName`/`team` are optional (omit both for a game-level prop like a
total). Leave `result` off until the week is graded — `grade_week.py` can
fill it in for picks that match a tracked player/stat, or set it by hand for
anything it can't (a combined stat, a team total, a player outside the
roster). Commit and push the file; the site picks it up on next load.

## Track Record — grading a finished week

Once a week's games are complete, grade the algorithm's Top 10 (reproduced
exactly from a pre-game `nfl_data.json` snapshot) against real results, and
record editor picks alongside it:

```
cd data-pipeline
python3 grade_week.py <week> <before.json> <after.json> --editor editor_week.json
cp picks_history.json ../picks_history.json
```

- `<before.json>`: a copy of `nfl_data.json` from before that week's games
  (e.g. `git show <commit>:nfl_data.json > before.json` — find the commit
  from `git log -- nfl_data.json`).
- `<after.json>`: the current `nfl_data.json`, now that the week is final.
- `--editor`: optional, a JSON file shaped like `editor_picks.json` but with
  a `result` ("hit"/"miss"/"push") already set per pick — however you know
  the outcome (the sportsbook's own grading, a manual check, etc.).

This reimplements the site's own ranking math in Python, so "what the Top 10
said" is reproduced exactly rather than approximated. A pick whose game
hadn't been played yet when graded comes back `no-data` ("pending") rather
than counting against accuracy.

## Known limitations

- No sportsbook odds anywhere in this pipeline — every prop line is the
  player's own season pace, flagged `estimated` on the site.
- Blitz rate isn't in public play-by-play; `pressureRate` (sacks + QB hits
  per dropback) is used instead, everywhere a blitz rate would have gone.
- A passer needs 15+ pass attempts with location data, and a skill player
  needs 3+ rushes or 3+ targets, to get a season/prop line for that stat —
  below that the sample is too small to be meaningful.
- The roster is the top 2 RBs / top 3 WRs / top 1 TE by volume, per team,
  each week — a player who drops out of that top tier (even if they still
  played) won't have a grade-able prop the next time the pipeline runs.
