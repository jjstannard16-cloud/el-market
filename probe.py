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

  A creature's own picture, where it has one, is File:Creature <Name>.png
  under a "Creature" heading. Plain File:<Name>.png does not exist. Of
  Yeti, Feros, Red Dragon and Rabbit, only Yeti had one, so coverage is
  the open question and this measures it.

Asking now: how many of our creatures have a picture at all, and under
which name? Two shapes are in use - "Creature <Name>.png" for the full
portrait and "<Name> 25px.png" for the little ones on index pages - so
this asks the wiki for every file of either shape and reports what is
matched, what is missed, and how big the files are.
"""

import json
import re
import time
from collections import Counter

import requests

API = "https://el-wiki.holy-eternalland.de/api.php"
UA = {"User-Agent": "EL-HQ/0.1 (Eternal Lands community site; stann in-game)"}


def api(**params):
    params.setdefault("format", "json")
    params.setdefault("formatversion", 2)
    r = requests.get(API, params=params, headers=UA, timeout=30)
    r.raise_for_status()
    return r.json()


def all_images(prefix):
    """Every file whose name starts with prefix, with size and url."""
    out, cont = {}, None
    for _ in range(40):
        kw = {"action": "query", "list": "allimages", "aiprefix": prefix,
              "ailimit": 500, "aiprop": "url|size|mime"}
        if cont:
            kw["aicontinue"] = cont
        body = api(**kw)
        for im in body.get("query", {}).get("allimages", []):
            out[im["name"]] = im
        cont = body.get("continue", {}).get("aicontinue")
        if not cont:
            break
        time.sleep(0.3)
    return out


names = [c["name"] for c in json.load(open("creatures.json"))["creatures"]]
print(f"{len(names)} creatures to find a picture for")

portraits = all_images("Creature ")
print(f"\n{len(portraits)} files named 'Creature ...'")
sizes = Counter((im.get("width"), im.get("height"))
                for im in portraits.values())
print("their sizes:", sizes.most_common(8))

# The little ones are not under a shared prefix, so ask per creature in
# one batch of titles rather than listing the whole wiki.
small = {}
for i in range(0, len(names), 40):
    chunk = names[i:i + 40]
    titles = "|".join(f"File:{n} 25px.png" for n in chunk)
    body = api(action="query", titles=titles, prop="imageinfo",
               iiprop="url|size|mime")
    for pg in body.get("query", {}).get("pages", []):
        if not pg.get("missing"):
            for info in pg.get("imageinfo", []):
                small[pg["title"][5:]] = info
    time.sleep(0.3)
print(f"{len(small)} files named '<Name> 25px.png'")


def key(s):
    return re.sub(r"[^a-z0-9]", "", s.lower())


by_key = {key(n): n for n in portraits}
small_key = {key(n): n for n in small}

have_big, have_small, have_none = [], [], []
for n in names:
    if key("Creature " + n + ".png") in by_key:
        have_big.append(n)
    elif key(n + " 25px.png") in small_key:
        have_small.append(n)
    else:
        have_none.append(n)

print(f"\n{len(have_big)} have a portrait, {len(have_small)} only a small "
      f"one, {len(have_none)} have neither")
print("\nportraits, with size:")
for n in have_big[:12]:
    im = portraits[by_key[key('Creature ' + n + '.png')]]
    print(f"   {n[:28]:30} {im.get('width')}x{im.get('height')} "
          f"{im.get('size')} bytes {im.get('mime')}")
print("\nonly a small one:", ", ".join(have_small[:18]))
print("\nneither:", ", ".join(have_none[:30]))

# Are the unmatched ones named differently rather than absent?
print("\nfiles named 'Creature ...' that matched no creature of ours:")
unused = [n for k, n in by_key.items()
          if not any(key("Creature " + c + ".png") == k for c in names)]
print("   " + ", ".join(sorted(unused)[:30]))
print(f"   ({len(unused)} in all)")
