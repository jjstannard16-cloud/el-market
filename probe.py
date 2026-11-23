#!/usr/bin/env python3
"""One-off: where can we get a player's guild without a hand-made list?"""
import json, re, sys, requests
UA = {"User-Agent": "EL-HQ/0.1 (Eternal Lands community site; stann in-game)"}

print("=== 1. the official player page")
for who in ("stann", "Burn"):
    try:
        r = requests.get("http://game.eternal-lands.com/view_user.php",
                         params={"user": who}, headers=UA, timeout=25)
        print(f"  {who}: {r.status_code}, {len(r.text)} bytes")
        text = re.sub(r"<[^>]+>", " ", r.text)
        text = " ".join(text.split())
        print(f"    {text[:400]}")
        if re.search(r"guild", r.text, re.I):
            for m in re.finditer(r".{80}guild.{120}", r.text, re.I | re.S):
                print(f"    GUILD CONTEXT: {' '.join(m.group().split())[:200]}")
    except Exception as e:
        print(f"  {who}: {e}")

print("\n=== 2. Mercator online players")
for url in ("https://mercator.holy-eternalland.de/api/v1/players/online",
            "https://mercator.holy-eternalland.de/onlineplayer"):
    try:
        r = requests.get(url, headers={**UA, "Accept": "application/json"},
                         timeout=25)
        print(f"  {url} -> {r.status_code}, {len(r.text)} bytes")
        if "json" in r.headers.get("content-type", ""):
            body = r.json()
            print("    " + json.dumps(body)[:900])
        else:
            text = " ".join(re.sub(r"<[^>]+>", " ", r.text).split())
            print(f"    (html) {text[:500]}")
    except Exception as e:
        print(f"  {url}: {e}")

print("\n=== 3. the top-players page, which we already read")
try:
    r = requests.get("https://top.el-db.com/365-200.html", headers=UA, timeout=25)
    text = " ".join(re.sub(r"<[^>]+>", " ", r.text).split())
    print(f"  {r.status_code}, {len(r.text)} bytes")
    print(f"  {text[:400]}")
    print(f"  mentions guild: {bool(re.search(r'guild', r.text, re.I))}")
except Exception as e:
    print(f"  {e}")
