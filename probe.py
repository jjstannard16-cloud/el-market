#!/usr/bin/env python3
"""One-off: how are creature drops written on the wiki?"""
import re, requests, time
API = "https://el-wiki.holy-eternalland.de/api.php"
UA = {"User-Agent": "EL-HQ/0.1 (Eternal Lands community site; stann in-game)"}

def api(**kw):
    kw.setdefault("format", "json"); kw.setdefault("formatversion", 2)
    return requests.get(API, params=kw, headers=UA, timeout=30).json()

def text(title):
    b = api(action="query", prop="revisions", titles=title,
            rvprop="content", rvslots="main", redirects=1)
    for pg in b.get("query", {}).get("pages", []):
        rv = (pg.get("revisions") or [{}])[0]
        return pg.get("title"), (rv.get("slots", {}).get("main", {})
                                 .get("content") or "")
    return title, ""

for t in ["Feros", "Rare Drops of Feros", "Instance", "Invance"]:
    title, body = text(t)
    print(f"\n===== {title}: {len(body)} chars")
    print("\n".join(body.splitlines()[:55]))
    time.sleep(0.4)

print("\n===== how many creature pages")
for cat in ["Creatures", "Monsters", "Instance creatures",
            "Invance creatures", "Invasion creatures", "Rare drops"]:
    b = api(action="query", list="categorymembers",
            cmtitle=f"Category:{cat}", cmlimit=500)
    ms = [m["title"] for m in b.get("query", {}).get("categorymembers", [])]
    print(f"   {cat}: {len(ms)} -> {ms[:8]}")
    time.sleep(0.3)
