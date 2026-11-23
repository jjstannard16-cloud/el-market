#!/usr/bin/env python3
"""One-off: what is on a player page beyond skills? Counters, or badges?"""
import re, requests
UA = {"User-Agent": "EL-HQ/0.1 (Eternal Lands community site; stann in-game)"}

for who in ("stann", "Burn"):
    r = requests.get("http://game.eternal-lands.com/view_user.php",
                     params={"user": who}, headers=UA, timeout=25)
    html = r.text
    print(f"\n===== {who}: {r.status_code}, {len(html)} bytes")
    text = " ".join(re.sub(r"<[^>]+>", " ", html).split())
    print(text)
    for word in ("Instances", "kills", "missions", "Haidir", "harvested",
                 "Lucky", "Rostogol", "achiev"):
        if re.search(word, html, re.I):
            print(f"  >>> mentions {word!r}")
