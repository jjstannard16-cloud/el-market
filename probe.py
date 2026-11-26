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

import json

import requests

BASE = "https://mercator.holy-eternalland.de"
UA = {"User-Agent": "EL-HQ/0.1 (Eternal Lands community site; stann in-game)"}


def get(path, **kw):
    r = requests.get(BASE + path, headers=UA, timeout=40, **kw)
    r.raise_for_status()
    return r.json()


print("===== /api/analytics/summary, in full =====")
print(json.dumps(get("/api/analytics/summary"), indent=1)[:6000])

print("\n===== /api/marketsearch - a second set of bot prices? =====")
body = get("/api/marketsearch", params={"q": "leather", "per_page": 10})
print(json.dumps(body, indent=1)[:2500])

print("\n===== /api/v1/recipes - how many, and what shape =====")
body = get("/api/v1/recipes")
print("keys:", list(body))
print("total:", body.get("total"))
rs = body.get("recipes") or []
print(json.dumps(rs[0], indent=1)[:900] if rs else "none")
multi = {}
for r in rs:
    multi.setdefault(r.get("itemName"), []).append(r.get("id"))
many = {k: v for k, v in multi.items() if len(v) > 1}
print(f"{len(rs)} recipes for {len(multi)} items; "
      f"{len(many)} items have more than one")
print("   e.g.", list(many)[:8])

print("\n===== /api/v1/recipes/calculate =====")
print(json.dumps(get("/api/v1/recipes/calculate",
                     params={"item": "Steel Long Sword", "amount": 1,
                             "recursive": "true"}), indent=1)[:2500])
