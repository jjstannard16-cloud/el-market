#!/usr/bin/env python3
"""One-off: does the wiki list every achievement by name?"""
import re, requests, time
API = "https://el-wiki.holy-eternalland.de/api.php"
UA = {"User-Agent": "EL-HQ/0.1 (Eternal Lands community site; stann in-game)"}

def api(**kw):
    kw.setdefault("format", "json"); kw.setdefault("formatversion", 2)
    return requests.get(API, params=kw, headers=UA, timeout=30).json()

b = api(action="query", prop="revisions", titles="Achievements",
        rvprop="content", rvslots="main", redirects=1)
for pg in b.get("query", {}).get("pages", []):
    rv = (pg.get("revisions") or [{}])[0]
    t = rv.get("slots", {}).get("main", {}).get("content") or ""
    print(f"{pg.get('title')}: {len(t)} chars, "
          f"{len(re.findall(r'^==', t, re.M))} headings, "
          f"{len(re.findall(r'^\|-', t, re.M))} table rows")
    print("\n".join(t.splitlines()[:60]))
