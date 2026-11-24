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

Asking now: is there a picture for a quest's NPC? The quest guide names
61 of them. Looking for a category or page listing NPCs, and for any
file resembling each name, the same way the creatures were found.
"""

import json
import re
import time
from difflib import get_close_matches

import requests

API = "https://el-wiki.holy-eternalland.de/api.php"
UA = {"User-Agent": "EL-HQ/0.1 (Eternal Lands community site; stann in-game)"}


def api(**params):
    params.setdefault("format", "json")
    params.setdefault("formatversion", 2)
    r = requests.get(API, params=params, headers=UA, timeout=30)
    r.raise_for_status()
    return r.json()


def every_image():
    out, cont = {}, None
    for _ in range(200):
        kw = {"action": "query", "list": "allimages", "ailimit": 500,
              "aiprop": "url|size", "aisort": "name"}
        if cont:
            kw["aicontinue"] = cont
        body = api(**kw)
        for im in body.get("query", {}).get("allimages", []):
            out[im["name"]] = im
        cont = body.get("continue", {}).get("aicontinue")
        if not cont:
            break
        time.sleep(0.25)
    return out


# "Elle, Valley of the Dwarves" and "Bob the Gob, Portland [wandering]"
# carry a place; the name is what comes before the comma or bracket.
def bare(npc):
    return re.split(r"\s*[,\[(]", npc)[0].strip()


def key(text):
    return re.sub(r"[^a-z0-9]", "", text.lower())


quests = json.load(open("quests.json"))["quests"]
npcs = sorted({bare(q["npc"]) for q in quests if q.get("npc")})
print(f"{len(npcs)} distinct NPCs named by the quest guide")

print("\n--- categories whose name mentions NPC ---")
body = api(action="query", list="allcategories", acprefix="", aclimit=500)
cats = [c["category"] for c in body.get("query", {}).get("allcategories", [])]
print("   " + ", ".join(c for c in cats if re.search(r"npc|character|people",
                                                     c, re.I)) or "   none")

for cat in ("NPCs", "NPC", "Characters", "Priest NPCs"):
    body = api(action="query", list="categorymembers",
               cmtitle=f"Category:{cat}", cmlimit=500)
    members = [m["title"] for m in
               body.get("query", {}).get("categorymembers", [])]
    if members:
        print(f"\n--- Category:{cat} has {len(members)} members ---")
        print("   " + ", ".join(members[:30]))

files = every_image()
print(f"\n{len(files)} files on the wiki")

plain = {}
for name in files:
    stem = re.sub(r"\.(png|jpe?g|gif|webp)$", "", name, flags=re.I)
    plain.setdefault(key(stem), name)

hit, miss = [], []
for npc in npcs:
    k = key(npc)
    found = None
    for prefix in ("npc", "", "character", "quest"):
        if prefix + k in plain:
            found = plain[prefix + k]
            break
    (hit if found else miss).append((npc, found))

print(f"\n{len(hit)} NPCs have a file, {len(miss)} do not")
for npc, f in hit[:20]:
    im = files[f]
    print(f"   {npc:22} {f}  {im.get('width')}x{im.get('height')} "
          f"{im.get('size')}b")

print("\n--- nearest file to each miss ---")
for npc, _ in miss[:25]:
    near = get_close_matches(key(npc), plain, n=2, cutoff=0.78)
    print(f"   {npc:22} -> "
          + (", ".join(plain[m] for m in near) if near else "nothing close"))

print("\n--- files whose name mentions npc or quest ---")
for name in sorted(files):
    if re.search(r"\bnpc|quest", name, re.I):
        print(f"   {name}")
