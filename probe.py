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

  view_user.php has no pictures on it at all. The whole page is about
  2,300 bytes and holds not one img tag; the achievements on it are
  plain text separated by two non-breaking spaces. So badge artwork,
  if it exists, has to come from somewhere else.

Asking now: does the wiki have the achievement badges? Looking for a
page about them and for any file whose name resembles one, against the
30 badge names we have actually seen on players.
"""

import json
import re
import time
from difflib import get_close_matches

import requests

API = "https://el-wiki.holy-eternalland.de/api.php"
UA = {"User-Agent": "EL-HQ/0.1 (Eternal Lands community site; stann in-game)"}

# Every badge name seen across the players we have read.
NAMES = ["Tutorial completed", "Vanquisher", "Church donator", "Alchemist",
         "Professor of Potioning", "Crafter", "Armorer", "Big belly",
         "Child of Stars", "Mushroomer", "Herbalist", "Miner",
         "Mother nature hates me", "Lucky finder", "Lucky crafter",
         "Exterminator"]


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


print("--- is there a page about achievements? ---")
body = api(action="query", list="search", srsearch="achievements",
           srlimit=12)
for hit in body.get("query", {}).get("search", []):
    print(f"   {hit['title']}  ({hit.get('wordcount')} words)")

for title in ("Achievements", "Achievement", "Medals"):
    body = api(action="query", prop="revisions", titles=title,
               rvprop="content", rvslots="main", redirects=1)
    pages = body.get("query", {}).get("pages", [])
    if pages and not pages[0].get("missing"):
        text = (pages[0]["revisions"][0]["slots"]["main"]["content"])
        print(f"\n--- page '{title}' exists, {len(text)} bytes ---")
        print(text[:1200])
        files = re.findall(r"\[\[File:([^\]|]+)", text, re.I)
        print(f"   files it uses: {files[:20]}")
        break
else:
    print("\n   no Achievements page under any of those titles")

files = every_image()
print(f"\n{len(files)} files on the wiki")

print("\n--- files whose name mentions an achievement-ish word ---")
for name in sorted(files):
    if re.search(r"achiev|badge|medal|trophy", name, re.I):
        im = files[name]
        print(f"   {name}  {im.get('width')}x{im.get('height')}")

print("\n--- nearest file to each badge name ---")
plain = {}
for name in files:
    stem = re.sub(r"\.(png|jpe?g|gif|webp)$", "", name, flags=re.I)
    plain.setdefault(stem.replace("_", " ").lower(), name)
for badge in NAMES:
    near = get_close_matches(badge.lower(), plain, n=2, cutoff=0.8)
    print(f"   {badge:26} -> "
          + (", ".join(plain[m] for m in near) if near else "nothing close"))
