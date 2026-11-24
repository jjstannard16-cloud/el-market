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

Asking now: how many does a recipe make? The wiki's ManuInfo template
gives ingredients and amounts but el_recipes.py never captured a yield,
so arrows - mixed fifty at a time - have their batch cost compared with
the price of a single arrow. This dumps the template's own definition
and a few known batch recipes to find the field that says so.
"""

import json
import re
import sys

import requests

API = "https://el-wiki.holy-eternalland.de/api.php"
UA = {"User-Agent": "EL-HQ/0.1 (Eternal Lands community site; stann in-game)"}

PAGES = ["Template:ManuInfo", "Magic arrows", "Fire arrows", "Ice arrows",
         "Thread", "Iron Bar", "Ring of Power", "Steel Bar"]


def page_text(title):
    r = requests.get(API, params={
        "action": "query", "prop": "revisions", "titles": title,
        "rvprop": "content", "rvslots": "main", "format": "json",
        "formatversion": 2, "redirects": 1}, headers=UA, timeout=30)
    r.raise_for_status()
    pages = r.json().get("query", {}).get("pages", [])
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
    if title.startswith("Template:"):
        # The template's own source names every parameter it accepts.
        names = sorted(set(re.findall(r"\{\{\{\s*([A-Za-z0-9_]+)", text)))
        print("parameters the template accepts:")
        print("   " + ", ".join(names))
        print("\n--- first 2500 bytes ---")
        print(text[:2500])
        continue
    # On a recipe page, show the template call and anything numeric that
    # looks like it says how many you get.
    m = re.search(r"\{\{\s*ManuInfo(.*?)\n\}\}", text, re.S | re.I)
    print("--- ManuInfo call ---")
    print(m.group(1).strip() if m else "(no ManuInfo found)")
    for line in text.splitlines():
        if re.search(r"\b(yield|makes|produces|batch|at a time|quantity|"
                     r"amount made|per mix|each mix)\b", line, re.I):
            print(f"  >>> {line.strip()[:160]}")
