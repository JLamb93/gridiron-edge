#!/usr/bin/env python3
"""
Grades a past week's Top-10 algorithm picks against real final stats, and
records (already-known) editor picks for that week, into picks_history.json.

Usage:
  python3 grade_week.py <week> <before.json> <after.json> [--editor editor_week.json]

<before.json>  a snapshot of nfl_data.json taken BEFORE that week's games
               (git history has these — see README)
<after.json>   the current nfl_data.json, which now has that week's real
               results in each player's log

This reimplements the site's own ranking math (mean/stdev/normalCdf/
computeProp/isLeaderboardWorthy in index.html) so "what the Top 10 said"
is reproduced exactly, then checks each pick's actual result for that week.
"""
import json
import math
import sys
import argparse

STATUS_FACTOR = {"Healthy": 1, "Probable": 0.98, "Questionable": 0.93, "Out": 0}
POS_RANK_KEY = {"QB": "pass", "RB": "rush", "WR": "rec", "TE": "rec"}

def mean(xs):
    return sum(xs) / len(xs) if xs else 0

def stdev(xs):
    m = mean(xs)
    v = mean([(x - m) ** 2 for x in xs])
    s = math.sqrt(v)
    return s or (m * 0.18) or 1

def normal_cdf(z):
    t = 1 / (1 + 0.2316419 * abs(z))
    d = 0.3989423 * math.exp(-z * z / 2)
    p = d * t * (0.3193815 + t * (-0.3565638 + t * (1.781478 + t * (-1.821256 + t * 1.330274))))
    if z > 0:
        p = 1 - p
    return p

def compute_prop(player, prop):
    season_avg = player["season"][prop["key"]]
    log = player.get("log") or []
    if log:
        vals = [g[prop["key"]] for g in log if prop["key"] in g]
        last3 = vals[-3:]
        last_game = vals[-1]
        baseline = mean(last3) * 0.5 + season_avg * 0.3 + last_game * 0.2
        sd_base = stdev(vals) * 0.9
    else:
        baseline = season_avg
        sd_base = season_avg * 0.22
    rank_key = POS_RANK_KEY[player["pos"]]
    opp_rank = (player.get("oppRank") or {}).get(rank_key) or 16
    matchup_pull = ((opp_rank - 16.5) / 16.5) * 0.12
    matchup_adj = baseline * matchup_pull
    availability = STATUS_FACTOR[player["status"]]
    projected = (baseline + matchup_adj) * availability
    sd = max(sd_base, season_avg * 0.1, 0.6)
    z = (projected - prop["line"]) / sd
    p_over = max(0.03, min(0.97, normal_cdf(z)))
    return projected, p_over

def is_leaderboard_worthy(prop):
    return prop["line"] >= 8 if prop["unit"] == "yds" else prop["line"] >= 1.5

def top_10_props(data):
    ranked = []
    for player in data["players"]:
        if player.get("bye") or player.get("status") == "Out":
            continue
        for prop in player.get("props") or []:
            if not is_leaderboard_worthy(prop):
                continue
            projected, p_over = compute_prop(player, prop)
            pick = "over" if p_over >= 0.5 else "under"
            pct = p_over if pick == "over" else 1 - p_over
            ranked.append({
                "playerId": player["id"], "playerName": player["name"], "team": player["team"],
                "propKey": prop["key"], "propLabel": prop["label"], "unit": prop["unit"],
                "line": prop["line"], "pick": pick, "pct": round(pct, 4), "projected": round(projected, 1),
            })
    ranked.sort(key=lambda r: -r["pct"])
    return ranked[:10]

def actual_value_for_week(after_data, player_id, prop_key, week):
    for p in after_data["players"]:
        if p["id"] == player_id:
            for g in p.get("log") or []:
                if g.get("wk") == week and prop_key in g:
                    return g[prop_key]
            return None
    return None

def grade(picks, after_data, week):
    graded = []
    hits = 0
    for pick in picks:
        actual = actual_value_for_week(after_data, pick["playerId"], pick["propKey"], week)
        if actual is None:
            result = "no-data"
        elif actual == pick["line"]:
            result = "push"
        elif (pick["pick"] == "over") == (actual > pick["line"]):
            result = "hit"
        else:
            result = "miss"
        if result == "hit":
            hits += 1
        graded.append({**pick, "actual": actual, "result": result})
    gradeable = [g for g in graded if g["result"] in ("hit", "miss")]
    accuracy = round(hits / len(gradeable) * 100, 1) if gradeable else None
    return graded, accuracy

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("week", type=int)
    ap.add_argument("before")
    ap.add_argument("after")
    ap.add_argument("--editor", help="JSON file: {\"picks\": [{playerId/playerName, team, propLabel, pick, line, result}]}")
    ap.add_argument("--out", default="picks_history.json")
    args = ap.parse_args()

    before = json.load(open(args.before))
    after = json.load(open(args.after))

    algo_picks = top_10_props(before)
    algo_graded, algo_accuracy = grade(algo_picks, after, args.week)

    editor_entry = None
    if args.editor:
        editor_raw = json.load(open(args.editor))
        editor_hits = sum(1 for p in editor_raw["picks"] if p.get("result") == "hit")
        editor_total = sum(1 for p in editor_raw["picks"] if p.get("result") in ("hit", "miss"))
        editor_entry = {
            "picks": editor_raw["picks"],
            "accuracy": round(editor_hits / editor_total * 100, 1) if editor_total else None,
            "source": editor_raw.get("source", "manual"),
        }

    try:
        history = json.load(open(args.out))
    except FileNotFoundError:
        history = {"weeks": []}

    history["weeks"] = [w for w in history["weeks"] if w["week"] != args.week]
    entry = {
        "week": args.week,
        "algorithm": {"picks": algo_graded, "accuracy": algo_accuracy},
    }
    if editor_entry:
        entry["editor"] = editor_entry
    history["weeks"].append(entry)
    history["weeks"].sort(key=lambda w: w["week"])

    json.dump(history, open(args.out, "w"), indent=1)
    print(f"Week {args.week}: algorithm {sum(1 for g in algo_graded if g['result']=='hit')}/{len(algo_graded)} "
          f"({algo_accuracy}%)" + (f", editor {editor_entry['accuracy']}%" if editor_entry else ""))
    for g in algo_graded:
        print(f"  [{g['result']:>7}] {g['playerName']} {g['propLabel']} {g['pick']} {g['line']} -> actual {g['actual']}")

if __name__ == "__main__":
    main()
