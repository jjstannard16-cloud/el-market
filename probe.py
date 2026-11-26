#!/usr/bin/env python3
"""
probe.py - scratch space for questions the sandbox cannot ask.

Nothing here runs on a schedule. The sandbox has no route to any
Eternal Lands host, so anything that needs one is written here and run
through .github/workflows/probe.yml by hand.

Answers found so far, recorded so nobody goes looking twice:

  Guild membership is not published anywhere. view_user.php and
  online_players.htm carry no guild; Mercator's /api/v1/players/online
  is a 404 and its /onlineplayer needs a login and shows no tags even
  signed in; guild_list.php is an empty navigation shell; top.el-db.com
  only links a menu; el.other-life.com's Top Guilds is gone. guild.txt
  stays hand-kept.

  The #ach counters are not on view_user.php. The badges there are a
  bucketed version of the same numbers, which is what we read instead.

  How many a recipe makes is the ManuInfo template's "resamount". The
  template says so itself. No resamount means one. el_recipes.py reads it.

  Creature pictures are not named to one rule - Creature Yeti.png,
  Badaran.png, Legionnaire_Troll.PNG, Monster_phantomwarrior.png - so
  el_creature_images.py reads the whole file list and matches on the
  name with capitals, spaces, underscores and extension stripped. That
  found 98 of 108. The remaining ten have no artwork anywhere.

  view_user.php has no pictures on it at all - about 2,300 bytes and
  not one img tag.

  Achievement badges are on the wiki's Achievements page, one heading
  each with the files under it giving the tiers in order. el_badges.py
  reads it. The wiki and the game disagree on two spellings.

  Quest NPC portraits are a plain <Name>.png on the wiki at 96 pixels,
  found the same way as the creatures. 55 of the 61 NPCs have one.

  Drops were being read from the section headed exactly "Drops", and
  from cells carrying no layout. 94 creature pages suit that and 14 do
  not: Castellan keeps its best drops under "Instance Drops", a Shy Rat
  styles the item cell as well as the icon cell, a Badaran uses a list
  instead of a table. el_creatures.py now reads the word "drop" in any
  heading, strips a cell's attributes, and reads bullets where there is
  no table.

  There are no per-instance pages. One Instances page carries all six,
  with the five waves of each, the counts, the a/d range to get in, the
  wait between visits and the time limit, in level order - which is not
  the order the nicknames suggest. el_instances.py reads it.

Asking now: nothing. The run below re-reads the creature pages with the
drop fixes and prints what changed, creature by creature, so the fix
can be checked against the old numbers before it lands.
"""

import sqlite3

import requests

BASE = "https://mercator.holy-eternalland.de"
UA = {"User-Agent": "EL-HQ/0.1 (Eternal Lands community site; stann in-game)"}

# Our recipes come from the wiki. Mercator keeps its own set, read from
# somewhere else, so the two disagreeing is the cheapest accuracy check
# there is: one of them is wrong and the row says which to go and look
# at. 462 of ours against 414 of theirs.
theirs = requests.get(f"{BASE}/api/v1/recipes", headers=UA,
                      timeout=60).json()["recipes"]
by_name = {}
for r in theirs:
    by_name.setdefault(r["itemName"].lower(), r)

con = sqlite3.connect("el_bots.db")
con.row_factory = sqlite3.Row
ours = {r["item"].lower(): dict(r) for r in con.execute("SELECT * FROM recipe")}
parts = {}
for r in con.execute("SELECT * FROM recipe_ingredient"):
    parts.setdefault(r["item"].lower(), {})[r["ingredient"].lower()] = \
        int(r["amount"])

both = sorted(set(ours) & set(by_name))
print(f"{len(ours)} ours, {len(by_name)} theirs, {len(both)} in both")
print(f"only ours: {len(set(ours) - set(by_name))}")
print(f"only theirs: {sorted(set(by_name) - set(ours))[:20]}")

def same(a, b):
    return (a or 0) == (b or 0)

off = {"level": [], "exp": [], "food": [], "makes": [], "skill": [],
       "knowledge": [], "ingredients": []}
for name in both:
    us, them = ours[name], by_name[name]
    if not same(us["level"], them.get("skillLevel")):
        off["level"].append(f"{us['item']}: {us['level']} vs {them.get('skillLevel')}")
    exp_theirs = sum((them.get("exps") or {}).values())
    if not same(us["exp"], exp_theirs):
        off["exp"].append(f"{us['item']}: {us['exp']} vs {exp_theirs}")
    if not same(us["food"], them.get("food")):
        off["food"].append(f"{us['item']}: {us['food']} vs {them.get('food')}")
    if not same(us["makes"], them.get("outputQuantity")):
        off["makes"].append(f"{us['item']}: {us['makes']} vs {them.get('outputQuantity')}")
    if (us["skill"] or "").lower() != (them.get("skillName") or "").lower():
        off["skill"].append(f"{us['item']}: {us['skill']} vs {them.get('skillName')}")
    ours_in = parts.get(name, {})
    theirs_in = {i["itemName"].lower(): i["quantity"]
                 for i in them.get("ingredients") or []}
    if ours_in != theirs_in:
        miss = set(theirs_in) - set(ours_in)
        extra = set(ours_in) - set(theirs_in)
        diff = {k: (ours_in[k], theirs_in[k]) for k in set(ours_in) & set(theirs_in)
                if ours_in[k] != theirs_in[k]}
        off["ingredients"].append(
            f"{us['item']}: " + ", ".join(filter(None, [
                f"we lack {sorted(miss)}" if miss else "",
                f"we have extra {sorted(extra)}" if extra else "",
                f"amounts {diff}" if diff else ""])))

for key, rows in off.items():
    print(f"\n--- {key}: {len(rows)} disagree ---")
    for line in rows[:25]:
        print("   " + line)
