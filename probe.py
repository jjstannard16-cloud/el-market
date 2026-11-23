#!/usr/bin/env python3
"""
probe.py - scratch space for looking at a source before building on it.

This sandbox cannot reach the Eternal Lands sites, so anything that needs
looking at gets written here and run through the Probe workflow. Replace
the body with whatever the current question is.

What has already been checked, so nobody checks it twice:

  Where does a player's guild come from?  Nowhere public, as of
  23 November 2026. Every candidate was tried:

    game.eternal-lands.com/view_user.php   attributes and skills only,
                                           no guild anywhere on the page
    mercator /api/v1/players/online        in the API docs, but 404 - the
                                           route does not exist
    mercator /onlineplayer                 needs a jelb.User login
    eternal-lands.com/page/guild_list.php  navigation chrome, 4.8 KB, no
                                           guilds on it at all
    top.el-db.com                          no guild per player; its only
                                           mention is a menu link
    el.other-life.com/top/guild50.php      the Top Guilds page the
                                           official menu points at. The
                                           site is gone: it redirects to
                                           an empty page

  So guild membership stays hand-made in guild.txt until either the
  logged-in Mercator page turns out to carry it, or the developers
  publish it.
"""

import re
import requests

LINK = r'href=["\']([^"\']+)["\']'
UA = {"User-Agent": "EL-HQ/0.1 (Eternal Lands community site; stann in-game)"}


def grab(url):
    try:
        r = requests.get(url, headers=UA, timeout=30)
    except Exception as e:
        print(f"\n=== {url} -> {e}")
        return ""
    print(f"\n=== {r.url} -> {r.status_code}, {len(r.text)} bytes")
    return r.text


def show(html, n=6, width=230):
    text = " ".join(re.sub(r"<[^>]+>", " ", html).split())
    print(f"  text: {text[:420]}")
    rows = re.findall(r"<tr[^>]*>.*?</tr>", html, re.S | re.I)
    print(f"  {len(rows)} rows; a sample:")
    for row in rows[len(rows) // 3:len(rows) // 3 + n]:
        print("   " + " ".join(row.split())[:width])


if __name__ == "__main__":
    print(__doc__)
