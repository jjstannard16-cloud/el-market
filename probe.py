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

import json
import re
import time

import requests

API = "https://el-wiki.holy-eternalland.de/api.php"
UA = {"User-Agent": "EL-HQ/0.1 (Eternal Lands community site; stann in-game)"}

NO_DROPS = ["Castellan", "Bulangiu", "Badaran", "Frozen Dragon", "Leonard",
            "Sslessar", "Bricker", "Small dragon", "Tank Rabbit", "Shy Rat",
            "Nenorocit"]
INSTANCES = ["Noob Instance", "Advanced Instance", "Pr0 Farm Instance",
             "Almost Pr0 Instance", "Pr0 Instance", "WTF???111?! Instance"]

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


print("=" * 70)
print("PART 1 - pages whose title mentions instance")
print("=" * 70)
body = api(action="query", list="search", srsearch="instance",
           srlimit=50, srwhat="title")
for hit in body.get("query", {}).get("search", []):
    print(f"   {hit['title']}")

print("\n--- Category:Instances and friends ---")
for cat in ("Instances", "Instance", "Instance creatures", "Invance",
            "Invances", "Instance maps"):
    body = api(action="query", list="categorymembers",
               cmtitle=f"Category:{cat}", cmlimit=500)
    members = [m["title"] for m in
               body.get("query", {}).get("categorymembers", [])]
    print(f"   Category:{cat}: {len(members)}"
          + ("  " + ", ".join(members) if members else ""))

print("\n" + "=" * 70)
print("PART 2 - the instance pages themselves, in full")
print("=" * 70)
for title in INSTANCES + ["Instances", "Instance"]:
    text = page_text(title)
    print(f"\n----- {title} -----")
    if text is None:
        print("   no such page")
        continue
    print(f"   {len(text)} bytes, headings: "
          + ", ".join(HEADING.findall(text)))
    print(text[:4000])
    time.sleep(0.3)

print("\n" + "=" * 70)
print("PART 3 - the creatures with no drops, in full")
print("=" * 70)
for name in NO_DROPS:
    text = page_text(name)
    print(f"\n----- {name} -----")
    if text is None:
        print("   no such page")
        continue
    print(f"   {len(text)} bytes, headings: "
          + ", ".join(HEADING.findall(text)))
    print(text[:2500])
    time.sleep(0.3)

print("\n" + "=" * 70)
print("PART 4 - every heading used on a creature page, counted")
print("=" * 70)
creatures = [c["name"] for c in
             json.load(open("creatures.json"))["creatures"]]
seen = {}
for name in creatures:
    text = page_text(name)
    if not text:
        continue
    for h in HEADING.findall(text):
        seen.setdefault(h.strip(), []).append(name)
    time.sleep(0.2)
for h, who in sorted(seen.items(), key=lambda kv: -len(kv[1])):
    sample = "" if len(who) > 20 else "  " + ", ".join(who)
    print(f"   {len(who):4}  {h}{sample}")
