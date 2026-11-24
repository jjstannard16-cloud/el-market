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

  A creature's picture is File:Creature <Name>.png, or the same as .jpg,
  or Creature_<NameRunTogether>.jpg, or the small <Name> 25px.png.
  Trying all four found 86 of 108.

Asking now: why the other 22? They look like three different problems -
variant spawns named "Black Bear (mana burn)" whose base creature has a
picture, names whose capitals differ from the wiki's, and invasion
bosses that may have no art at all. Rather than guess at more name
shapes, this pulls every file name on the wiki and reports the closest
thing to each creature we could not place.
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


creatures = json.load(open("creatures.json"))["creatures"]
have = json.load(open("creature_images.json"))["images"]
missing = [c["name"] for c in creatures if c["name"] not in have]

files = every_image()
print(f"{len(files)} files on the wiki in all")
print(f"{len(missing)} creatures still without a picture\n")

# Strip an extension and the decoration our names do not share.
plain = {}
for name in files:
    stem = re.sub(r"\.(png|jpe?g|gif|webp)$", "", name, flags=re.I)
    stem = re.sub(r"^Creature[ _]", "", stem)
    stem = re.sub(r"[ _]25px$", "", stem)
    plain.setdefault(stem.replace("_", " ").lower(), name)

for name in missing:
    base = re.sub(r"\s*\(.*?\)\s*$", "", name).strip()
    note = ""
    if base != name:
        note = (f"   [variant of {base}: "
                f"{'base HAS art' if base in have else 'base has none'}]")
    near = get_close_matches(name.lower(), plain, n=3, cutoff=0.72)
    near += [m for m in get_close_matches(base.lower(), plain, n=3,
                                          cutoff=0.72) if m not in near]
    print(f"{name}{note}")
    if near:
        for m in near[:4]:
            print(f"     could be {plain[m]}")
    else:
        print("     nothing on the wiki looks like it")

# Do the bracket variants really share the base creature's page?
print("\n--- do variants redirect to the base creature? ---")
for name in missing:
    base = re.sub(r"\s*\(.*?\)\s*$", "", name).strip()
    if base == name:
        continue
    body = api(action="query", titles=name, redirects=1)
    q = body.get("query", {})
    red = q.get("redirects") or []
    pages = q.get("pages") or [{}]
    print(f"  {name}: "
          f"{'page missing' if pages[0].get('missing') else 'page exists'}"
          f"{' -> ' + red[0]['to'] if red else ''}")
    time.sleep(0.25)
