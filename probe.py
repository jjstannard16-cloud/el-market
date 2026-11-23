#!/usr/bin/env python3
"""One-off: the official online-players page."""
import re, requests, time
UA = {"User-Agent": "EL-HQ/0.1 (Eternal Lands community site; stann in-game)"}
URL = "http://game.eternal-lands.com/online_players.htm"

r = requests.get(URL, headers=UA, timeout=30)
html = r.text
print(f"{r.url} -> {r.status_code}, {len(html)} bytes, "
      f"type {r.headers.get('content-type')}")
text = " ".join(re.sub(r"<[^>]+>", " ", html).split())
print(f"\ntext ({len(text)} chars):\n  {text[:900]}")
print(f"\nview_user links: {len(re.findall(r'view_user', html))}")
print(f"rows: {len(re.findall(r'<tr', html, re.I))}")
print(f"mentions guild: {bool(re.search(r'guild', html, re.I))}")
print("\nfirst 1200 bytes of raw html:")
print(html[:1200])

# Does it move? Two reads a minute apart say whether it is live.
time.sleep(45)
again = requests.get(URL, headers=UA, timeout=30).text
t2 = " ".join(re.sub(r"<[^>]+>", " ", again).split())
print(f"\n45 seconds later: {len(again)} bytes, identical: {again == html}")
print(f"  {t2[:300]}")
