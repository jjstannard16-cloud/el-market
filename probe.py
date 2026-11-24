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

Asking now: two holes in the instance pages.

  Nineteen creatures have no drops at all in creatures.json, Castellan
  among them, and a player says Castellan is the best dropper in the
  game. So either its page lays drops out in a shape read_creature does
  not read, or the drops live somewhere else entirely.

  Instance membership is built from each creature page's own Locations
  table, which gives only 6 to 11 creatures per instance. That smells
  short. Looking for a page per instance that lists what is inside.
"""

import re
import time

import requests

API = "https://el-wiki.holy-eternalland.de/api.php"
UA = {"User-Agent": "EL-HQ/0.1 (Eternal Lands community site; stann in-game)"}


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


print("===== Instances, the whole page =====")
print(page_text("Instances"))

for name in ("Leonard", "Invdrag", "Nasparliu", "Mare Bulangiu"):
    print(f"\n===== {name} =====")
    print(page_text(name))
    time.sleep(0.3)
