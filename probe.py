#!/usr/bin/env python3
"""One-off: is the invasions export reachable, and what is in it?"""
import json, re, requests
UA = {"User-Agent": "EL-HQ/0.1 (Eternal Lands community site; stann in-game)"}

for url, params in (
    ("https://mercator.holy-eternalland.de/analytics/export/invasions",
     {"format": "json", "limit": 5}),
    ("https://mercator.holy-eternalland.de/api/invasions", {"limit": 5}),
    ("https://mercator.holy-eternalland.de/analytics/export/invasions",
     {"format": "csv", "limit": 5}),
):
    try:
        r = requests.get(url, params=params, headers=UA, timeout=40)
        print(f"\n=== {r.url}\n  {r.status_code}, {len(r.text)} bytes, "
              f"{r.headers.get('content-type')}")
        if r.status_code == 200:
            body = r.text[:1500]
            try:
                j = r.json()
                print("  " + json.dumps(j)[:1200])
            except Exception:
                print("  " + " ".join(body.split())[:800])
    except Exception as e:
        print(f"\n=== {url} -> {e}")
