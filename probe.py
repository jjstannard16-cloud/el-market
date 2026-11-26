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
import re

import requests

API = "https://el-wiki.holy-eternalland.de/api.php"
UA = {"User-Agent": "EL-HQ/0.1 (Eternal Lands community site; stann in-game)"}
HEADING = re.compile(r"^=+\s*(.+?)\s*=+\s*$", re.M)


def api(**params):
    params.setdefault("format", "json")
    params.setdefault("formatversion", 2)
    r = requests.get(API, params=params, headers=UA, timeout=30)
    r.raise_for_status()
    return r.json()


def page_text(title):
    body = api(action="query", prop="revisions", titles=title,
               rvprop="content", rvslots="main", redirects=1)
    for pg in body.get("query", {}).get("pages", []):
        if pg.get("missing"):
            return None
        revs = pg.get("revisions") or [{}]
        return (revs[0].get("slots", {}).get("main", {}).get("content")
                or revs[0].get("content") or "")
    return None


# Maps our reader found no harvestables on. Some are temples and sewers
# with none to find; the rest are laid out in a way we do not read.
for name in ("Desert Pines", "Magic School", "Gargoyles Cave",
             "Nordcarn", "Portland"):
    text = page_text(name) or ""
    print("=" * 70)
    print(name, "  headings:", " | ".join(HEADING.findall(text)))
    for m in re.finditer(r"^=+\s*(.*[Hh]arvest.*?)\s*=+\s*$", text, re.M):
        print(text[m.start():m.start() + 700])
