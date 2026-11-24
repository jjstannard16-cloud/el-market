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

Asking now: do the achievement badges have pictures? read_achievements
strips every tag before reading the names, so if the badges are images
their addresses are being thrown away unseen. This prints the raw HTML
of that part of the page to find out what is actually in there.
"""

import re

import requests

UA = {"User-Agent": "EL-HQ/0.1 (Eternal Lands community site; stann in-game)"}
URL = "http://game.eternal-lands.com/view_user.php"

for who in ("stann", "Burn"):
    r = requests.get(URL, params={"user": who}, headers=UA, timeout=25)
    html = r.text
    print(f"\n{'=' * 70}\n===== {who}: {r.status_code}, {len(html)} bytes")

    i = html.find("Achievements")
    if i < 0:
        print("  no Achievements section")
        continue

    chunk = html[i:i + 4000]
    print("--- raw HTML from 'Achievements', first 2600 characters ---")
    print(chunk[:2600])

    print("\n--- every tag found in that chunk, counted ---")
    tags = re.findall(r"<\s*([a-zA-Z][a-zA-Z0-9]*)", chunk)
    seen = {}
    for t in tags:
        seen[t.lower()] = seen.get(t.lower(), 0) + 1
    print("   " + ", ".join(f"{k}x{v}" for k, v in sorted(seen.items())))

    print("\n--- image sources anywhere on the page ---")
    for m in re.finditer(r"<img[^>]*>", html, re.I):
        print("   " + m.group()[:200])

    print("\n--- anything that looks like a title or alt attribute ---")
    for m in re.finditer(r'(?:title|alt)\s*=\s*"([^"]{2,60})"', chunk, re.I):
        print(f"   {m.group(1)}")
