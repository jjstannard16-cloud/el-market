#!/usr/bin/env python3
"""One-off: does the wiki say what each god rank costs?"""
import re, requests, time
API = "https://el-wiki.holy-eternalland.de/api.php"
UA = {"User-Agent": "EL-HQ/0.1 (Eternal Lands community site; stann in-game)"}

def api(**kw):
    kw.setdefault("format", "json"); kw.setdefault("formatversion", 2)
    return requests.get(API, params=kw, headers=UA, timeout=30).json()

print("=== Category:Gods")
body = api(action="query", list="categorymembers",
           cmtitle="Category:Gods", cmlimit=500)
titles = [m["title"] for m in body.get("query", {}).get("categorymembers", [])]
print(f"  {len(titles)}: {titles}")

for title in ["Mortos", "Aluwen"]:
    print(f"\n=== {title}")
    b = api(action="query", prop="revisions", titles=title,
            rvprop="content", rvslots="main", redirects=1)
    for pg in b.get("query", {}).get("pages", []):
        revs = pg.get("revisions") or [{}]
        text = revs[0].get("slots", {}).get("main", {}).get("content") or ""
        if not text:
            print(f"  {pg.get('title')}: missing or empty")
            continue
        print(f"  {pg.get('title')}: {len(text)} chars")
        print("  " + "\n  ".join(text.splitlines()[:60]))
    time.sleep(0.4)

print("\n=== anything about ranks and items")
for term in ["god rank items", "worship rank", "Dirhyan"]:
    b = api(action="query", list="search", srsearch=term, srlimit=6)
    hits = [h["title"] for h in b.get("query", {}).get("search", [])]
    print(f"  {term!r}: {hits}")
    time.sleep(0.4)
