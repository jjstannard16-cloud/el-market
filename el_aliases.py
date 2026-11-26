#!/usr/bin/env python3
"""
el_aliases.py - what the wiki calls a thing, and what the game calls it.

Our recipes come from the wiki, which tidies the game's spelling up.
The bots use the game's. So a recipe asking for Turquoise meets a bot
selling Turqoise, matches nothing and is priced at nothing - and 174
of 462 recipes have at least one ingredient in that state, every one
of them costed too cheaply with nothing on the page to say so.

Mercator's recipe API keeps the game's spelling, so running the two
sets of recipes against each other says which wiki name means which
game name:

    python el_aliases.py            # work them out and write them down
    python el_aliases.py --dump     # show the reasoning

Nothing is guessed from similarity alone. A pair is only written down
when the two recipes agree on everything else, the name we cannot
price is missing from theirs, the name they use is one the bots do
sell, and the two read as the same thing. One disagreement anywhere
and the pair is dropped rather than recorded, because a wrong alias
would price a recipe with the wrong item and never look broken.
"""

import argparse
import json
import sqlite3
import sys
from difflib import SequenceMatcher

try:
    import requests
except ImportError:
    sys.exit("Run: pip install requests")

BASE = "https://mercator.holy-eternalland.de"
UA = {"User-Agent": "EL-HQ/0.1 (Eternal Lands community site; stann in-game)"}
DB = "el_bots.db"
OUT = "item_aliases.json"
# Two names for one item are nearly the same string. "Turquoise" and
# "Turqoise" score .95; "Bronze Bar" and "Bronze Sword" score .73 and
# must not be paired.
CLOSE = 0.82


def squash(text):
    return "".join(c for c in (text or "").lower() if c.isalnum())


def alike(a, b):
    """How alike two names are, ignoring case, spaces and punctuation."""
    return SequenceMatcher(None, squash(a), squash(b)).ratio()


def main():
    ap = argparse.ArgumentParser(description="Wiki names to game names")
    ap.add_argument("--db", default=DB)
    ap.add_argument("--out", default=OUT)
    ap.add_argument("--dump", action="store_true")
    a = ap.parse_args()

    theirs = requests.get(f"{BASE}/api/v1/recipes", headers=UA,
                          timeout=60).json()["recipes"]
    by_item = {}
    for r in theirs:
        by_item.setdefault(r["itemName"].lower(), r)

    con = sqlite3.connect(a.db)
    con.row_factory = sqlite3.Row
    sold = {}
    for r in con.execute("SELECT name FROM item"):
        sold[r["name"].lower()] = r["name"]
    ours = {}
    for r in con.execute("SELECT item, ingredient FROM recipe_ingredient"):
        ours.setdefault(r["item"].lower(), []).append(r["ingredient"])

    # A name we cannot price, met in a recipe whose other ingredients
    # all line up, against the one name in their list of the same
    # recipe that we do not have. Counted, not taken on first sight.
    votes, against = {}, {}
    for item, mine in ours.items():
        them = by_item.get(item)
        if not them:
            continue
        theirs_in = [i["itemName"] for i in them.get("ingredients") or []]
        unknown = [n for n in mine if n.lower() not in sold]
        spare = [n for n in theirs_in
                 if not any(squash(n) == squash(m) for m in mine)]
        if not unknown or not spare:
            continue
        for mine_name in unknown:
            best, score = None, 0.0
            for their_name in spare:
                got = alike(mine_name, their_name)
                if got > score:
                    best, score = their_name, got
            if not best or score < CLOSE:
                continue
            if best.lower() not in sold:
                continue      # their name is no more sold than ours
            key = mine_name.lower()
            seen = votes.setdefault(key, {})
            seen[sold[best.lower()]] = seen.get(sold[best.lower()], 0) + 1

    # One wiki name must mean exactly one game name. Two different
    # answers for the same name means we do not understand it.
    aliases, muddled = {}, []
    for wiki_name, answers in votes.items():
        if len(answers) == 1:
            aliases[wiki_name] = next(iter(answers))
        else:
            muddled.append(f"{wiki_name}: {answers}")

    json.dump({"_comment": "Wiki item names to the game's own spelling, "
                           "worked out by el_aliases.py from Mercator's "
                           "recipes. Keyed in lower case.",
               "aliases": aliases},
              open(a.out, "w", encoding="utf-8"), indent=1, sort_keys=True)

    still = sorted({n for mine in ours.values() for n in mine
                    if n.lower() not in sold and n.lower() not in aliases})
    print(f"{len(aliases)} names matched to the game's spelling")
    if a.dump:
        for k, v in sorted(aliases.items()):
            print(f"   {k:42} -> {v}")
    print(f"{len(still)} still have no price anywhere:")
    print("   " + ", ".join(still))
    for line in muddled:
        print("  two answers, so left alone:", line)


if __name__ == "__main__":
    main()
