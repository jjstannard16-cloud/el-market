#!/usr/bin/env python3
"""One-off: what does the wiki hold on instances, invances and drops?"""
import re, requests, time
API = "https://el-wiki.holy-eternalland.de/api.php"
UA = {"User-Agent": "EL-HQ/0.1 (Eternal Lands community site; stann in-game)"}

def api(**kw):
    kw.setdefault("format", "json"); kw.setdefault("formatversion", 2)
    return requests.get(API, params=kw, headers=UA, timeout=30).json()

print("=== categories mentioning instance, invance, creature, drop, monster")
cont, seen = None, 0
for _ in range(40):
    kw = {"action": "query", "list": "allcategories", "aclimit": 500}
    if cont: kw["acfrom"] = cont
    b = api(**kw)
    cats = b.get("query", {}).get("allcategories", [])
    seen += len(cats)
    for c in cats:
        n = c if isinstance(c, str) else c.get("category", "")
        if re.search(r"instance|invance|creature|drop|monster|mob", str(n), re.I):
            print(f"   * {n}")
    cont = b.get("continue", {}).get("accontinue")
    if not cont: break
    time.sleep(0.3)
print(f"   ({seen} categories in all)")

print("\n=== searches")
for term in ["instance", "invance", "WTF instance", "drops", "Feros"]:
    b = api(action="query", list="search", srsearch=term, srlimit=8, srnamespace=0)
    hits = [h["title"] for h in b.get("query", {}).get("search", [])]
    total = b.get("query", {}).get("searchinfo", {}).get("totalhits", 0)
    print(f"   {term!r}: {total} hits -> {hits}")
    time.sleep(0.3)

print("\n=== a creature page, to see if drops are listed")
for title in ["Feros", "Yeti", "Cyclops"]:
    b = api(action="query", prop="revisions", titles=title,
            rvprop="content", rvslots="main", redirects=1)
    for pg in b.get("query", {}).get("pages", []):
        rv = (pg.get("revisions") or [{}])[0]
        t = rv.get("slots", {}).get("main", {}).get("content") or ""
        print(f"   {pg.get('title')}: {len(t)} chars"
              + (f", mentions drop: {bool(re.search(r'drop', t, re.I))}" if t else " (missing)"))
        if t:
            print("     " + "\n     ".join(t.splitlines()[:25]))
            break
    time.sleep(0.3)
