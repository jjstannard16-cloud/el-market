#!/usr/bin/env python3
"""
el_questcheck.py - check the quest guide against the wiki.

quests.json comes from a community PDF, which is thorough but is one
person's work and dates from whenever it was last revised. The wiki is
edited by everyone and keeps up. This compares the two and says what is
in one and not the other, so gaps are found rather than assumed away.

    python el_questcheck.py                 # report only
    python el_questcheck.py --json gaps.json

Nothing is written to the site: this only reports. Deciding what to do
about a gap is a judgement call, not something to automate.
"""

import argparse
import json
import os
import re
import sys
import time

try:
    import requests
except ImportError:
    sys.exit("Run: pip install requests")

API = "https://el-wiki.holy-eternalland.de/api.php"
UA = "EL-HQ/0.1 (Eternal Lands community site; contact: stann in-game)"
PAUSE = 0.4
QUESTS_FILE = "quests.json"

# Where the wiki keeps quests. More than one, because it has reorganised
# itself over the years and the old names still hold pages.
CATEGORIES = ["Quests", "Quest", "Daily Quests", "Dailies", "God Quests",
              "Tutorial Quests", "Instance Quests"]

# Pages that live in a quest category without being a quest.
NOT_A_QUEST = re.compile(
    r"^(Category|Template|File|Help|Talk|User|Quests?$|Quest list|"
    r"List of quests|Quest rewards?)\b", re.I)


def session():
    s = requests.Session()
    s.headers.update({"User-Agent": UA})
    return s


def api(s, **params):
    params.setdefault("format", "json")
    params.setdefault("formatversion", 2)
    r = s.get(API, params=params, timeout=30)
    r.raise_for_status()
    return r.json()


def category_members(s, name):
    """Every page in a category, following continuations."""
    out, cont = [], None
    for _ in range(20):
        kw = {"action": "query", "list": "categorymembers",
              "cmtitle": f"Category:{name}", "cmlimit": 500}
        if cont:
            kw["cmcontinue"] = cont
        try:
            body = api(s, **kw)
        except Exception as e:
            print(f"  {name}: {e}")
            return out
        for m in body.get("query", {}).get("categorymembers", []):
            title = m.get("title", "")
            if title and not NOT_A_QUEST.match(title):
                out.append(title)
        cont = body.get("continue", {}).get("cmcontinue")
        if not cont:
            break
        time.sleep(PAUSE)
    return out


def search_quests(s, term, limit=200):
    try:
        body = api(s, action="query", list="search", srsearch=term,
                   srlimit=limit, srnamespace=0)
    except Exception as e:
        print(f"  search {term!r}: {e}")
        return [], 0
    hits = body.get("query", {}).get("search", [])
    total = body.get("query", {}).get("searchinfo", {}).get("totalhits", 0)
    return [h["title"] for h in hits if not NOT_A_QUEST.match(h["title"])], total


def norm(text):
    """
    Compare names the way a reader would: case, punctuation and the words
    'quest' and 'the' are noise. An apostrophe closes a word up rather
    than splitting it, so "Novac's" and "Novacs" are the same name.
    """
    t = str(text or "").lower()
    t = t.replace("’", "").replace("‘", "").replace("'", "")
    t = re.sub(r"[^a-z0-9 ]+", " ", t)
    t = re.sub(r"\b(the|a|an|quest|quests|of)\b", " ", t)
    return " ".join(t.split())


def keys(name):
    """
    Every form a page might be filed under. The god pages are the reason:
    ours is "Attack (Mortos)", and the wiki may call it "Mortos",
    "Attack God", or the whole thing.
    """
    name = str(name or "")
    out = {norm(name)}
    bracket = re.search(r"\((.*?)\)", name)
    if bracket:
        out.add(norm(bracket.group(1)))
        out.add(norm(re.sub(r"\(.*?\)", " ", name)))
    out.discard("")
    return out


HOSTS = ["https://el-wiki.holy-eternalland.de/api.php",
         "https://www.el-wiki.net/api.php"]


def npc_check(s, ours_npcs):
    """
    This wiki has no quest write-ups, but it does keep a Quest NPCs
    category. Every quest starts with someone, so an NPC there that no
    quest of ours starts with is a quest we may be missing.
    """
    listed = {}
    for cat in ("Quest NPCs", "Gods"):
        for t in category_members(s, cat):
            listed.setdefault(norm(t), t)
        time.sleep(PAUSE)
    if not listed:
        print("  the wiki listed no quest NPCs; treat this as not run")
        return
    mine = {norm(n) for n in ours_npcs if n}
    # An NPC may be written "Haidir" by us and "Haidir the Hunter" there.
    unmatched = sorted(t for k, t in listed.items()
                       if not any(k == m or k in m or m in k for m in mine))
    print(f"\n  {len(listed)} quest NPCs and gods on the wiki, "
          f"{len(mine)} distinct starters in our guide")
    print(f"  {len(unmatched)} wiki NPCs no quest of ours starts with:")
    for t in unmatched:
        print(f"     ? {t}")


def discover(s):
    """
    Find out how this wiki files its quests, rather than assuming. Prints
    every category whose name mentions quests, what a few known quest
    names turn up, and how big the wiki is.
    """
    print("categories mentioning quests, dailies or gods:")
    cont, seen = None, 0
    for _ in range(40):
        kw = {"action": "query", "list": "allcategories", "aclimit": 500}
        if cont:
            kw["acfrom"] = cont
        body = api(s, **kw)
        cats = body.get("query", {}).get("allcategories", [])
        seen += len(cats)
        for c in cats:
            name = c if isinstance(c, str) else c.get("category", "")
            if re.search(r"quest|daily|dailies|god|tutorial", str(name), re.I):
                print(f"   * {name}")
        cont = body.get("continue", {}).get("accontinue")
        if not cont:
            break
        time.sleep(PAUSE)
    print(f"   ({seen} categories in all)")

    print("\nsearching for quests we already have:")
    for probe in ["All Oiled Up", "Haidir", "Treasure of Nordcarn",
                  "Mortos", "Beginner Tutorial"]:
        hits, total = search_quests(s, probe, limit=5)
        print(f"   {probe!r}: {total} hits -> {hits[:5]}")
        time.sleep(PAUSE)

    print("\nwhat categories one known quest page sits in:")
    for title in ["All Oiled Up", "Treasure of Nordcarn"]:
        try:
            body = api(s, action="query", titles=title, prop="categories",
                       cllimit=50)
            for pg in body.get("query", {}).get("pages", []):
                cats = [c["title"] for c in pg.get("categories", [])]
                print(f"   {pg.get('title')!r}: "
                      + (", ".join(cats) if cats else
                         ("missing" if pg.get("missing") else "no categories")))
        except Exception as e:
            print(f"   {title}: {e}")
        time.sleep(PAUSE)


def main():
    ap = argparse.ArgumentParser(description="Check quests.json vs the wiki")
    ap.add_argument("--quests", default=QUESTS_FILE)
    ap.add_argument("--json", help="write the gaps to this file as well")
    ap.add_argument("--discover", action="store_true",
                    help="report how the wiki files its quests, then stop")
    a = ap.parse_args()

    if a.discover:
        for host in HOSTS:
            globals()["API"] = host
            print(f"\n===== {host}")
            try:
                discover(session())
            except Exception as e:
                print(f"  unreachable: {e}")
        return

    if not os.path.exists(a.quests):
        sys.exit(f"No {a.quests}. Run el_quests.py first.")
    with open(a.quests, encoding="utf-8") as f:
        ours = [q["name"] for q in json.load(f).get("quests", [])]
    ours_norm = {}
    for n in ours:
        for k in keys(n):
            ours_norm.setdefault(k, n)
    print(f"{len(ours)} quests in {a.quests}")

    s = session()
    theirs = {}
    for cat in CATEGORIES:
        found = category_members(s, cat)
        if found:
            print(f"  wiki category {cat!r}: {len(found)} pages")
        for t in found:
            theirs.setdefault(norm(t), t)
        time.sleep(PAUSE)

    # Categories alone miss anything uncategorised, so search as well.
    for term in ["quest", "daily quest", "incategory:Quests"]:
        hits, total = search_quests(s, term)
        if hits:
            print(f"  wiki search {term!r}: {len(hits)} of {total} hits")
        for t in hits:
            theirs.setdefault(norm(t), t)
        time.sleep(PAUSE)

    npc_check(s, [q.get("npc") for q in
                  json.load(open(a.quests, encoding="utf-8"))["quests"]])

    if not theirs:
        print("\nThe wiki has no quest write-ups to compare against, so the "
              "guide stands on its own. The NPC list above is the check.")
        return

    # A wiki page counts as covered if any of our names matches any of
    # the forms it could be filed under.
    missing = sorted({t for t in theirs.values()
                      if not (keys(t) & set(ours_norm))})
    theirs_keys = set()
    for t in theirs.values():
        theirs_keys |= keys(t)
    extra = sorted({n for n in ours if not (keys(n) & theirs_keys)})

    print(f"\n{len(theirs)} distinct quest pages on the wiki")
    print(f"{len(missing)} on the wiki but not in our guide:")
    for t in missing:
        print(f"   + {t}")
    print(f"\n{len(extra)} in our guide but not found on the wiki:")
    for t in extra:
        print(f"   - {t}")

    if a.json:
        with open(a.json, "w", encoding="utf-8") as f:
            json.dump({"ours": sorted(ours), "wiki": sorted(theirs.values()),
                       "missing_from_ours": missing,
                       "not_on_wiki": extra}, f, indent=1, ensure_ascii=False)
        print(f"\nwrote {a.json}")


if __name__ == "__main__":
    main()
