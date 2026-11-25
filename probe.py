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

import re

import requests
from bs4 import BeautifulSoup

BASE = "https://holy-eternalland.de/en/eternal-lands-quests/haidir-daily/"
UA = {"User-Agent": "EL-HQ/0.1 (Eternal Lands community site; stann in-game)"}

PAGES = {
    "Summoning Daily": "14-maja-daily-summoning.html",
    "Combat Daily": "4-haidir-daily-fighting-quests.html",
    "Clothes Breaking Daily": "13-daily-breakage-quest-of-clothes.html",
    "Engineering Daily": "9-minel-engenering-daily.html",
    "Harvesting Daily": "6-xaquelina-daily-quest.html",
    "Armor and Weapon Supply Daily":
        "5-darithas-daily-quest-manufacture-items.html",
    "Dung Harvesting Quest": "10-kaleb-dung-daily.html",
    "Mule Daily": "8-tatu-mule-daily.html",
    "Temps R Us Daily": "7-dorel-tempr-us.html",
}

for name, slug in PAGES.items():
    url = BASE + slug
    print("\n" + "=" * 70)
    print(name, "   ", url)
    print("=" * 70)
    try:
        r = requests.get(url, headers=UA, timeout=30)
        r.raise_for_status()
    except Exception as e:
        print("   failed:", e)
        continue
    soup = BeautifulSoup(r.text, "lxml")
    body = (soup.select_one(".com-content-article__body")
            or soup.select_one("[itemprop=articleBody]")
            or soup.select_one(".item-page") or soup)
    tables = body.find_all("table")
    print(f"   {len(r.text)} bytes, {len(tables)} tables in the article")
    for i, t in enumerate(tables):
        rows = t.find_all("tr")
        print(f"   --- table {i}: {len(rows)} rows ---")
        for tr in rows[:40]:
            cells = [" ".join(c.get_text(" ", strip=True).split())
                     for c in tr.find_all(["td", "th"])]
            if any(cells):
                print("      ", cells)
    if not tables:
        text = body.get_text("\n", strip=True)
        print("   no tables; first 2500 characters of the article:")
        print(re.sub(r"\n{3,}", "\n\n", text[:2500]))
