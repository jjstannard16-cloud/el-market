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
  template says so itself: "Note: The recipe produces {{{resamount}}}
  {{{item}}} at once". No resamount means one. el_recipes.py reads it.

Asking now: where is a creature's picture? Item artwork comes from
bots.el-services.net and is mirrored by el_images.py, but creatures have
none at all. Their wiki pages carry [[File:...]] links - for the
creature itself, but also for every drop - so this prints each one with
the heading it sits under, to find which is the creature's own, and
checks what the API gives back for the real file.
"""

import re

import requests

API = "https://el-wiki.holy-eternalland.de/api.php"
UA = {"User-Agent": "EL-HQ/0.1 (Eternal Lands community site; stann in-game)"}

PAGES = ["Yeti", "Feros", "Red Dragon", "Rabbit", "Nasty Giant"]
FILE = re.compile(r"\[\[File:([^\]|]+)[^\]]*\]\]", re.I)
HEAD = re.compile(r"^=+\s*(.+?)\s*=+\s*$", re.M)


def api(**params):
    params.setdefault("format", "json")
    params.setdefault("formatversion", 2)
    r = requests.get(API, params=params, headers=UA, timeout=30)
    r.raise_for_status()
    return r.json()


def page_text(title):
    body = api(action="query", prop="revisions", titles=title,
               rvprop="content", rvslots="main", redirects=1)
    pages = body.get("query", {}).get("pages", [])
    if not pages or pages[0].get("missing"):
        return None
    revs = pages[0].get("revisions") or [{}]
    return (revs[0].get("slots", {}).get("main", {}).get("content")
            or revs[0].get("content") or "")


for title in PAGES:
    text = page_text(title)
    print(f"\n{'=' * 70}\n===== {title}: "
          f"{'missing' if text is None else str(len(text)) + ' bytes'}")
    if not text:
        continue
    heads = [(m.start(), m.group(1)) for m in HEAD.finditer(text)]
    for m in FILE.finditer(text):
        under = ""
        for pos, name in heads:
            if pos < m.start():
                under = name
        print(f"  @{m.start():>5} under {under or '(top of page)':24} "
              f"{m.group(1).strip()}")
    print("  --- first 300 bytes of the page ---")
    print("  " + text[:300].replace("\n", "\n  "))

# What does the API hand back for a file, and how big is it?
print(f"\n{'=' * 70}\n===== imageinfo")
names = ["File:Yeti.png", "File:Yeti.jpg", "File:Yeti.gif"]
body = api(action="query", titles="|".join(names), prop="imageinfo",
           iiprop="url|size|mime")
for pg in body.get("query", {}).get("pages", []):
    if pg.get("missing"):
        print(f"  {pg.get('title')}: missing")
        continue
    for info in pg.get("imageinfo", []):
        print(f"  {pg['title']}: {info.get('width')}x{info.get('height')} "
              f"{info.get('mime')} {info.get('url')}")

# And is there a tidier way to ask - every image used on one page?
print(f"\n{'=' * 70}\n===== images used on the Yeti page, in page order")
body = api(action="query", titles="Yeti", prop="images", imlimit=50)
for pg in body.get("query", {}).get("pages", []):
    for im in pg.get("images", []) or []:
        print("  " + im.get("title", ""))
