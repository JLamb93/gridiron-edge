# Gridiron Edge data pipeline

Replaces hand-researched stats with real public data:

- **nflverse play-by-play** (`nflverse/nflverse-data`, `pbp` release) — every
  pass's field location and air yards, every sack/QB hit, every rush and
  catch. This is what makes the QB passing-tendency field and team defense
  stats real instead of modeled.
- **nflverse rosters + injuries** — current team/position/jersey number and
  the latest weekly injury report status.
- **ESPN's public standings + scoreboard JSON endpoints** — win/loss
  records, streaks, home/away splits, and the week's schedule (including
  neutral-site games).

## Running it

```
cd data-pipeline
pip3 install pandas   # only needed once
python3 build_data.py
cp nfl_data.json ../nfl_data.json
```

Then commit and push `nfl_data.json` (from the repo root, next to
`index.html`) — GitHub Pages serves it as a static file and the site
`fetch()`s it at load. No other files need to change week to week.

## To project a different week

Edit `CURRENT_WEEK` at the top of `build_data.py` (it pulls the schedule for
that week and treats every prior week as "played").

## Known limitations

- No sportsbook odds anywhere in this pipeline — every prop line is the
  player's own season pace, flagged `estimated` on the site.
- Blitz rate isn't in public play-by-play; `pressureRate` (sacks + QB hits
  per dropback) is used instead, everywhere a blitz rate would have gone.
- A passer needs 15+ pass attempts with location data, and a skill player
  needs 3+ rushes or 3+ targets, to get a season/prop line for that stat —
  below that the sample is too small to be meaningful.
