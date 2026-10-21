#!/usr/bin/env python3
"""
Gridiron Edge data pipeline.

Pulls real, public data instead of hand-researched snapshots:
  - nflverse play-by-play (pass location + air yards + sacks/hits + every
    rush/catch) -> https://github.com/nflverse/nflverse-data
  - nflverse weekly roster + injury reports (names, teams, jersey #, status)
  - ESPN's public (undocumented) standings + scoreboard JSON endpoints
    (records, streaks, home/away splits, the Week 7 schedule + home/away/
    neutral-site flags)

Outputs nfl_data.json, which the site fetches at load instead of embedding
hand-typed PLAYERS/TEAMS arrays. Re-run this script and redeploy
nfl_data.json to refresh the whole site for a new week.
"""
import json
import math
import urllib.request
import gzip
import io
import csv
from collections import defaultdict
from datetime import datetime, timezone

SEASON = 2026
CURRENT_WEEK = 7  # the week we are projecting FOR
PBP_URL = f"https://github.com/nflverse/nflverse-data/releases/download/pbp/play_by_play_{SEASON}.csv.gz"
ROSTER_URL = f"https://github.com/nflverse/nflverse-data/releases/download/rosters/roster_{SEASON}.csv"
INJURIES_URL = f"https://github.com/nflverse/nflverse-data/releases/download/injuries/injuries_{SEASON}.csv"
ESPN_STANDINGS_URL = f"https://site.api.espn.com/apis/v2/sports/football/nfl/standings?season={SEASON}"
ESPN_SCOREBOARD_URL = f"https://site.api.espn.com/apis/site/v2/sports/football/nfl/scoreboard?seasontype=2&week={CURRENT_WEEK}"

TEAM_FIX = {"LA": "LAR"}  # nflverse play-by-play spelling -> site spelling
ESPN_FIX = {"WSH": "WAS", "LAR": "LAR"}  # ESPN spelling -> site spelling

def fix_espn_team(abbr):
    return ESPN_FIX.get(abbr, abbr)

DIVISIONS = {
    "AFC East": ["BUF","MIA","NE","NYJ"], "AFC North": ["BAL","CIN","CLE","PIT"],
    "AFC South": ["HOU","IND","JAX","TEN"], "AFC West": ["DEN","KC","LAC","LV"],
    "NFC East": ["DAL","NYG","PHI","WAS"], "NFC North": ["CHI","DET","GB","MIN"],
    "NFC South": ["ATL","CAR","NO","TB"], "NFC West": ["ARI","LAR","SF","SEA"],
}
TEAM_NAMES = {
    "BUF":"Buffalo Bills","MIA":"Miami Dolphins","NE":"New England Patriots","NYJ":"New York Jets",
    "BAL":"Baltimore Ravens","CIN":"Cincinnati Bengals","CLE":"Cleveland Browns","PIT":"Pittsburgh Steelers",
    "HOU":"Houston Texans","IND":"Indianapolis Colts","JAX":"Jacksonville Jaguars","TEN":"Tennessee Titans",
    "DEN":"Denver Broncos","KC":"Kansas City Chiefs","LAC":"Los Angeles Chargers","LV":"Las Vegas Raiders",
    "DAL":"Dallas Cowboys","NYG":"New York Giants","PHI":"Philadelphia Eagles","WAS":"Washington Commanders",
    "CHI":"Chicago Bears","DET":"Detroit Lions","GB":"Green Bay Packers","MIN":"Minnesota Vikings",
    "ATL":"Atlanta Falcons","CAR":"Carolina Panthers","NO":"New Orleans Saints","TB":"Tampa Bay Buccaneers",
    "ARI":"Arizona Cardinals","LAR":"Los Angeles Rams","SF":"San Francisco 49ers","SEA":"Seattle Seahawks",
}
DIV_OF = {t: d for d, ts in DIVISIONS.items() for t in ts}

def fetch_text(url):
    req = urllib.request.Request(url, headers={"User-Agent": "gridiron-edge-pipeline"})
    with urllib.request.urlopen(req, timeout=60) as resp:
        data = resp.read()
    if url.endswith(".gz"):
        data = gzip.decompress(data)
    return data.decode("utf-8", errors="replace")

def fetch_json(url):
    req = urllib.request.Request(url, headers={"User-Agent": "gridiron-edge-pipeline"})
    with urllib.request.urlopen(req, timeout=60) as resp:
        return json.load(resp)

def read_csv_dicts(text):
    return list(csv.DictReader(io.StringIO(text)))

def to_f(v, default=0.0):
    try:
        if v is None or v == "" or v == "NA":
            return default
        return float(v)
    except (TypeError, ValueError):
        return default

def fix_team(abbr):
    return TEAM_FIX.get(abbr, abbr)

print("Fetching play-by-play ...")
pbp = read_csv_dicts(fetch_text(PBP_URL))
print(f"  {len(pbp)} rows")

print("Fetching roster ...")
roster_rows = read_csv_dicts(fetch_text(ROSTER_URL))
roster = {r["gsis_id"]: r for r in roster_rows if r.get("gsis_id")}
print(f"  {len(roster)} players")

print("Fetching injuries ...")
injury_rows = read_csv_dicts(fetch_text(INJURIES_URL))
# Use the most recent week that actually has a published game-status (Q/D/O)
# designation, not just the most recent week with any row — early in a game
# week, the newest week's rows are often practice-only (no report_status yet),
# which would otherwise wipe every real status back to "Healthy".
weeks_with_status = sorted({int(r["week"]) for r in injury_rows if r.get("week") and r.get("report_status")})
max_inj_week = weeks_with_status[-1] if weeks_with_status else 0
latest_injuries = {}
for r in injury_rows:
    if r.get("week") and int(r["week"]) == max_inj_week and r.get("report_status"):
        latest_injuries[r["gsis_id"]] = r["report_status"]
print(f"  latest injury report with designations: week {max_inj_week}, {len(latest_injuries)} flagged players")

print("Fetching ESPN standings ...")
standings = fetch_json(ESPN_STANDINGS_URL)
print("Fetching ESPN Week", CURRENT_WEEK, "scoreboard ...")
scoreboard = fetch_json(ESPN_SCOREBOARD_URL)

# ---------------------------------------------------------------------------
# Team records / streaks / home-away splits from ESPN standings
# ---------------------------------------------------------------------------
team_stats = {}
for conf in standings["children"]:
    for entry in conf["standings"]["entries"]:
        abbr = fix_espn_team(entry["team"]["abbreviation"])
        stats = {s["name"]: s for s in entry["stats"]}
        wins = int(to_f(stats.get("wins", {}).get("value")))
        losses = int(to_f(stats.get("losses", {}).get("value")))
        ties = int(to_f(stats.get("ties", {}).get("value")))
        record = f"{wins}-{losses}" + (f"-{ties}" if ties else "")
        streak_raw = stats.get("streak", {}).get("displayValue", "")
        streak = f"Won {streak_raw[1:]} straight" if streak_raw.startswith("W") and streak_raw[1:] != "1" \
            else "Won 1 straight" if streak_raw == "W1" \
            else f"Lost {streak_raw[1:]} straight" if streak_raw.startswith("L") and streak_raw[1:] != "1" \
            else "Lost 1 straight" if streak_raw == "L1" else streak_raw
        home = stats.get("Home", {}).get("displayValue")
        away = stats.get("Road", {}).get("displayValue")
        team_stats[abbr] = {
            "record": record, "wins": wins, "losses": losses, "ties": ties,
            "streak": streak, "homeRecord": home, "awayRecord": away,
        }

# division placement
for div, abbrs in DIVISIONS.items():
    ranked = sorted(abbrs, key=lambda a: (
        -(team_stats[a]["wins"] + team_stats[a]["ties"]*0.5),
        team_stats[a]["losses"]
    ))
    for i, a in enumerate(ranked):
        ord_ = {1:"1st",2:"2nd",3:"3rd",4:"4th"}[i+1]
        team_stats[a]["placeText"] = f"{ord_} in {div}"

# ---------------------------------------------------------------------------
# Week 7 schedule: opponent + home/away/neutral from ESPN scoreboard
# ---------------------------------------------------------------------------
scheduled = set()
for event in scoreboard["events"]:
    comp = event["competitions"][0]
    neutral = bool(comp.get("neutralSite"))
    competitors = comp["competitors"]
    home = next(c for c in competitors if c["homeAway"] == "home")
    away = next(c for c in competitors if c["homeAway"] == "away")
    h, a = fix_espn_team(home["team"]["abbreviation"]), fix_espn_team(away["team"]["abbreviation"])
    scheduled.add(h); scheduled.add(a)
    team_stats.setdefault(h, {})["nextOpp"] = a
    team_stats.setdefault(h, {})["homeGame"] = "neutral" if neutral else True
    team_stats.setdefault(a, {})["nextOpp"] = h
    team_stats.setdefault(a, {})["homeGame"] = "neutral" if neutral else False

for abbr in TEAM_NAMES:
    if abbr not in scheduled:
        team_stats.setdefault(abbr, {})["nextOpp"] = None
        team_stats[abbr]["homeGame"] = None
        team_stats[abbr]["bye"] = True

# ---------------------------------------------------------------------------
# Defense: real sacks / QB hits / yards allowed, from play-by-play
# ---------------------------------------------------------------------------
def_games = defaultdict(set)
def_sacks = defaultdict(int)
def_hits = defaultdict(int)
def_pass_att = defaultdict(int)
def_pass_yds = defaultdict(float)
def_rush_yds = defaultdict(float)

for r in pbp:
    defteam = fix_team(r.get("defteam") or "")
    if not defteam or not r.get("week"):
        continue
    week = int(r["week"])
    def_games[defteam].add(week)
    if r.get("sack") == "1": def_sacks[defteam] += 1
    if r.get("qb_hit") == "1": def_hits[defteam] += 1
    if r.get("pass") == "1":
        def_pass_att[defteam] += 1
        def_pass_yds[defteam] += to_f(r.get("yards_gained"))
    if r.get("rush") == "1":
        def_rush_yds[defteam] += to_f(r.get("yards_gained"))

def_rank_input = {}
for abbr in TEAM_NAMES:
    g = max(len(def_games[abbr]), 1)
    pass_ypg = def_pass_yds[abbr] / g
    rush_ypg = def_rush_yds[abbr] / g
    pressure_rate = round((def_sacks[abbr] + def_hits[abbr]) / max(def_pass_att[abbr], 1) * 100, 1)
    def_rank_input[abbr] = {
        "sacks": def_sacks[abbr], "pressureRate": pressure_rate,
        "passYdsAllowed": round(pass_ypg, 1), "rushYdsAllowed": round(rush_ypg, 1),
    }
pass_rank_order = sorted(TEAM_NAMES, key=lambda a: def_rank_input[a]["passYdsAllowed"])
rush_rank_order = sorted(TEAM_NAMES, key=lambda a: def_rank_input[a]["rushYdsAllowed"])
for i, a in enumerate(pass_rank_order): def_rank_input[a]["passRank"] = i+1
for i, a in enumerate(rush_rank_order): def_rank_input[a]["rushRank"] = i+1

# ---------------------------------------------------------------------------
# Passers: directional split, depth split, season + weekly stat lines
# ---------------------------------------------------------------------------
STATUS_MAP = {"Questionable": "Questionable", "Doubtful": "Questionable", "Out": "Out"}

def depth_bucket(ay):
    if ay is None: return None
    if ay < 10: return "short"
    if ay < 20: return "intermediate"
    return "deep"

passer_rows = defaultdict(list)
rusher_rows = defaultdict(list)
receiver_rows = defaultdict(list)

for r in pbp:
    week = r.get("week")
    if not week: continue
    week = int(week)
    if r.get("passer_id"): passer_rows[r["passer_id"]].append(r)
    if r.get("rusher_id"): rusher_rows[r["rusher_id"]].append(r)
    if r.get("receiver_id"): receiver_rows[r["receiver_id"]].append(r)

def season_week_agg(rows, week_fn):
    by_week = defaultdict(list)
    for r in rows:
        by_week[int(r["week"])].append(r)
    weeks = sorted(by_week)
    log = [week_fn(w, by_week[w]) for w in weeks]
    return log

def build_passer(gsis_id, rows):
    thrown = [r for r in rows if r.get("pass_location")]
    n = len(thrown)
    if n < 15:
        return None
    left = sum(1 for r in thrown if r["pass_location"] == "left")
    mid = sum(1 for r in thrown if r["pass_location"] == "middle")
    right = sum(1 for r in thrown if r["pass_location"] == "right")
    directional = {
        "left": round(left/n*100, 1), "middle": round(mid/n*100, 1), "right": round(right/n*100, 1),
    }
    depthed = [r for r in thrown if r.get("air_yards") not in (None, "")]
    buckets = {"short":0, "intermediate":0, "deep":0}
    for r in depthed:
        b = depth_bucket(to_f(r["air_yards"]))
        if b: buckets[b] += 1
    dn = sum(buckets.values()) or 1
    depth = {k: round(v/dn*100, 1) for k, v in buckets.items()}

    def wk(w, wrows):
        comp = sum(1 for r in wrows if r.get("complete_pass") == "1")
        yds = sum(to_f(r.get("passing_yards")) for r in wrows)
        td = sum(1 for r in wrows if r.get("pass_touchdown") == "1")
        opp = fix_team(wrows[0].get("defteam") or "")
        return {"wk": w, "opp": opp, "passYd": round(yds), "passTd": td, "cmp": comp}
    log = season_week_agg(rows, wk)
    games = len(log)
    season = {
        "passYd": round(sum(g["passYd"] for g in log)/games, 1),
        "passTd": round(sum(g["passTd"] for g in log)/games, 2),
        "cmp": round(sum(g["cmp"] for g in log)/games, 1),
    }
    return {"log": log, "season": season, "ngs": {"directional": directional, "depth": depth}, "games": games}

def build_rush_rec(gsis_id, rush_rows_, rec_rows_, pos):
    def wk_rush(w, wrows):
        return {"wk": w, "rushYd": round(sum(to_f(r.get("rushing_yards")) for r in wrows))}
    def wk_rec(w, wrows):
        rec = sum(1 for r in wrows if r.get("complete_pass") == "1")
        yds = sum(to_f(r.get("receiving_yards")) for r in wrows)
        td = sum(1 for r in wrows if r.get("pass_touchdown") == "1" and r.get("complete_pass") == "1")
        return {"wk": w, "rec": rec, "recYd": round(yds), "recTd": td}
    # Gate by position + volume up front so a WR's one jet-sweep carry (or a
    # blocking TE's single garbage-time target) never becomes a displayed stat.
    include_rush = pos == "RB" and len(rush_rows_) >= 3
    include_rec = pos in ("RB", "WR", "TE") and len(rec_rows_) >= 3
    rush_log = season_week_agg(rush_rows_, wk_rush) if include_rush else []
    rec_log = season_week_agg(rec_rows_, wk_rec) if include_rec else []
    by_week = {}
    opp_by_week = {}
    for r in (rush_rows_ if include_rush else []):
        w = int(r["week"]); opp_by_week[w] = fix_team(r.get("defteam") or "")
    for r in rec_rows_:
        w = int(r["week"]); opp_by_week[w] = fix_team(r.get("defteam") or "")
    for g in rush_log: by_week[g["wk"]] = {"wk": g["wk"], "rushYd": g["rushYd"]}
    for g in rec_log:
        by_week.setdefault(g["wk"], {"wk": g["wk"]})
        by_week[g["wk"]].update({"rec": g["rec"], "recYd": g["recYd"], "recTd": g["recTd"]})
    weeks = sorted(by_week)
    log = []
    for w in weeks:
        row = {"wk": w, "opp": opp_by_week.get(w, "")}
        row.update(by_week[w])
        log.append(row)
    games = len(log)
    if games == 0:
        return None
    totals = defaultdict(float)
    for g in log:
        for k in ("rushYd","rec","recYd","recTd"):
            totals[k] += g.get(k, 0)
    season = {}
    rush_yd_avg = totals["rushYd"]/games
    rec_avg = totals["rec"]/games
    rec_yd_avg = totals["recYd"]/games
    rec_td_avg = totals["recTd"]/games
    if include_rush: season["rushYd"] = round(rush_yd_avg, 1)
    if include_rec:
        season["rec"] = round(rec_avg, 2)
        season["recYd"] = round(rec_yd_avg, 1)
        season["recTd"] = round(rec_td_avg, 2)
    return {"log": log, "season": season, "games": games}

players = []
used_ids = set()

def status_for(gsis_id):
    raw = latest_injuries.get(gsis_id)
    return STATUS_MAP.get(raw, "Healthy")

def slug(name, team):
    base = "".join(ch for ch in name.lower() if ch.isalnum())
    return f"{base}{team.lower()}"

def opp_rank_for(pos, opp_abbr):
    d = def_rank_input.get(opp_abbr)
    if not d: return {}
    if pos == "QB": return {"pass": d["passRank"]}
    if pos == "RB": return {"rush": d["rushRank"]}
    return {"rec": d["passRank"]}

# --- QBs: top passer per team by attempts ---
passer_attempts = defaultdict(int)
for gid, rows in passer_rows.items():
    passer_attempts[gid] = len(rows)
by_team_passers = defaultdict(list)
for gid, rows in passer_rows.items():
    info = roster.get(gid)
    if not info: continue
    team = fix_team(info["team"])
    by_team_passers[team].append(gid)

for team, gids in by_team_passers.items():
    top = max(gids, key=lambda g: passer_attempts[g])
    info = roster[top]
    built = build_passer(top, passer_rows[top])
    if not built: continue
    ts = team_stats.get(team, {})
    bye = ts.get("bye", False)
    opp = ts.get("nextOpp")
    pid = slug(info["full_name"], team)
    used_ids.add(pid)
    props = [] if bye else [
        {"key": "passYd", "label": "Passing Yards", "unit": "yds", "line": round(built["season"]["passYd"]*2)/2, "estimated": True},
        {"key": "passTd", "label": "Passing TDs", "unit": "td", "line": round(built["season"]["passTd"]*2)/2, "estimated": True},
        {"key": "cmp", "label": "Completions", "unit": "cmp", "line": round(built["season"]["cmp"]*2)/2, "estimated": True},
    ]
    players.append({
        "id": pid, "name": info["full_name"], "team": team, "pos": "QB",
        "num": info.get("jersey_number") or "—", "status": status_for(top),
        "bye": bye, "opp": "BYE" if bye else opp,
        "oppRank": {} if bye else opp_rank_for("QB", opp),
        "news": f"Season averages and directional splits computed from real play-by-play through Week {CURRENT_WEEK-1}.",
        "log": built["log"], "season": built["season"], "ngs": built["ngs"], "props": props,
    })

# --- RB/WR/TE: top skill players per team by usage ---
SKILL_CAPS = {"RB": 2, "WR": 3, "TE": 1}
by_team_pos_candidates = defaultdict(lambda: defaultdict(dict))  # team -> pos -> gid -> volume
all_skill_ids = set(rusher_rows) | set(receiver_rows)
for gid in all_skill_ids:
    info = roster.get(gid)
    if not info: continue
    pos = info.get("position")
    if pos not in SKILL_CAPS: continue
    team = fix_team(info["team"])
    rr = rusher_rows.get(gid, [])
    cr = receiver_rows.get(gid, [])
    volume = len(rr) + len(cr)
    if volume < 8: continue
    by_team_pos_candidates[team][pos][gid] = volume

for team, posmap in by_team_pos_candidates.items():
    for pos, cap in SKILL_CAPS.items():
        gids = sorted(posmap.get(pos, {}), key=lambda g: -posmap[pos][g])[:cap]
        for gid in gids:
            info = roster[gid]
            built = build_rush_rec(gid, rusher_rows.get(gid, []), receiver_rows.get(gid, []), pos)
            if not built: continue
            ts = team_stats.get(team, {})
            bye = ts.get("bye", False)
            opp = ts.get("nextOpp")
            pid = slug(info["full_name"], team)
            if pid in used_ids: continue
            used_ids.add(pid)
            props = []
            if not bye:
                for key, label, unit in [("rushYd","Rushing Yards","yds"), ("rec","Receptions","rec"),
                                          ("recYd","Receiving Yards","yds"), ("recTd","Receiving TDs","td")]:
                    if key in built["season"]:
                        props.append({"key": key, "label": label, "unit": unit,
                                      "line": round(built["season"][key]*2)/2, "estimated": True})
            players.append({
                "id": pid, "name": info["full_name"], "team": team, "pos": pos,
                "num": info.get("jersey_number") or "—", "status": status_for(gid),
                "bye": bye, "opp": "BYE" if bye else opp,
                "oppRank": {} if bye else opp_rank_for(pos, opp),
                "news": f"Season line computed from real play-by-play through Week {CURRENT_WEEK-1}.",
                "log": built["log"], "season": built["season"], "props": props,
            })

# ---------------------------------------------------------------------------
# Assemble TEAMS
# ---------------------------------------------------------------------------
teams = []
for abbr, name in TEAM_NAMES.items():
    ts = team_stats.get(abbr, {})
    d = def_rank_input[abbr]
    teams.append({
        "abbr": abbr, "name": name, "conf": "AFC" if abbr in sum([DIVISIONS[k] for k in DIVISIONS if k.startswith("AFC")], []) else "NFC",
        "div": DIV_OF[abbr].split(" ")[1],
        "record": ts.get("record", "0-0"), "homeRecord": ts.get("homeRecord"), "awayRecord": ts.get("awayRecord"),
        "placeText": ts.get("placeText"), "streak": ts.get("streak", ""),
        "bye": bool(ts.get("bye", False)), "nextOpp": ts.get("nextOpp"), "homeGame": ts.get("homeGame"),
        "defense": d,
    })

out = {
    "meta": {"season": SEASON, "throughWeek": CURRENT_WEEK-1, "projectingWeek": CURRENT_WEEK,
             "generatedAt": datetime.now(timezone.utc).isoformat(),
             "generatedBy": "nflverse play-by-play + rosters + injuries, ESPN standings/scoreboard"},
    "teams": teams,
    "players": players,
}
with open("nfl_data.json", "w") as f:
    json.dump(out, f, indent=1)
print(f"Wrote nfl_data.json — {len(teams)} teams, {len(players)} players")
