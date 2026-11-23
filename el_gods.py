#!/usr/bin/env python3
"""
el_gods.py - what each rank of worship costs, from the wiki.

The community quest guide covers the gods but never says which items a
rank wants, how many, or whether they go in your inventory or storage.
The wiki does, in a table on each god's page, so this reads it and
writes gods.json for the site to show alongside the guide's write-up.

    python el_gods.py                 # fetch and write gods.json
    python el_gods.py --dump Mortos   # print one page's table

Only the gods that can actually be worshipped have a rank table; the
lore gods out of the Almanac have none, and are skipped.
"""

import argparse
import json
import re
import sys
import time
from collections import OrderedDict

try:
    import requests
except ImportError:
    sys.exit("Run: pip install requests")

API = "https://el-wiki.holy-eternalland.de/api.php"
UA = "EL-HQ/0.1 (Eternal Lands community site; contact: stann in-game)"
OUT = "gods.json"
PAUSE = 0.4
TIMEOUT = 30

# Pages in Category:Gods that are not a god.
NOT_A_GOD = {"gods", "priest npcs"}

TABLE = re.compile(r"\{\|.*?\|\}", re.S)
FILE_LINK = re.compile(r"\[\[File:[^\]]*\]\]", re.I)
WIKI_LINK = re.compile(r"\[\[([^\]|]+)(?:\|([^\]]+))?\]\]")
EXT_LINK = re.compile(r"\[(?:https?://\S+)\s+([^\]]*)\]")
HTML = re.compile(r"<[^>]+>")
# A cell can carry attributes before its content: |style="..." | 300
CELL_ATTRS = re.compile(r'^[^|]*\b(?:style|scope|align|colspan|rowspan)\s*=[^|]*\|')


def session():
    s = requests.Session()
    s.headers.update({"User-Agent": UA})
    return s


def api(s, **params):
    params.setdefault("format", "json")
    params.setdefault("formatversion", 2)
    r = s.get(API, params=params, timeout=TIMEOUT)
    r.raise_for_status()
    return r.json()


def page_text(s, title):
    body = api(s, action="query", prop="revisions", titles=title,
               rvprop="content", rvslots="main", redirects=1)
    for pg in body.get("query", {}).get("pages", []):
        revs = pg.get("revisions") or [{}]
        return (revs[0].get("slots", {}).get("main", {}).get("content")
                or revs[0].get("content") or "")
    return ""


def clean_cell(text):
    """Wikitext down to the words a reader wants."""
    text = FILE_LINK.sub(" ", text)
    text = WIKI_LINK.sub(lambda m: (m.group(2) or m.group(1)), text)
    text = EXT_LINK.sub(lambda m: m.group(1), text)
    text = HTML.sub(" ", text)
    text = text.replace("'''", "").replace("''", "")
    # An empty link, [[]], is how the wiki marks a value nobody knows.
    text = re.sub(r"\[\[\s*\]\]", " ", text)
    text = re.sub(r"[\[\]]+", " ", text)
    return " ".join(text.split()).strip(" |?").strip()


def split_cells(line):
    """
    One table line into its cells. Cells are divided by || on a single
    line, and a cell may carry style attributes before a final pipe.
    """
    out = []
    for part in re.split(r"\|\||!!", line):
        part = part.lstrip("|!").strip()
        part = CELL_ATTRS.sub("", part).strip()
        out.append(clean_cell(part))
    return out


def parse_one(body):
    """One table body into a list of {column: value}."""
    rows, current = [], []
    for raw in body.splitlines():
        line = raw.rstrip()
        if line.startswith("|-"):
            if current:
                rows.append(current)
            current = []
            continue
        if line.startswith("!") or line.startswith("|"):
            current.append((line.startswith("!"), split_cells(line)))
    if current:
        rows.append(current)

    flat = []
    for row in rows:
        cells, all_head = [], True
        for is_head, parts in row:
            cells += parts
            if not is_head:
                all_head = False
        cells = [c for c in cells if c != ""]
        if cells:
            flat.append((all_head, cells))
    if not flat:
        return []

    headers = flat[0][1] if flat[0][0] else []
    out = []

    for all_head, cells in flat[1:]:
        if not headers:
            headers = cells
            continue
        row = OrderedDict((h, "") for h in headers)
        if len(cells) < len(headers):
            # A row can leave a cell out entirely: the gods that are not
            # in the game yet have no items and nowhere to put them. The
            # first and last columns are never in doubt, so fill from
            # both ends and leave the hole in the middle, rather than
            # shifting every value one column to the left.
            row[headers[0]] = cells[0]
            for i, value in enumerate(reversed(cells[1:])):
                row[headers[len(headers) - 1 - i]] = value
        else:
            for i, value in enumerate(cells):
                key = headers[i] if i < len(headers) else f"column {i + 1}"
                row[key] = value
        out.append(row)
    return out


def parse_table(wikitext):
    """
    The rank table. A god page opens with a one-cell box holding the
    contents list, so taking the first table on the page gets that
    instead - the right one is the one whose columns mention ranks.
    """
    best = []
    for m in TABLE.finditer(wikitext):
        rows = parse_one(m.group()[2:-2])
        if not rows:
            continue
        cols = " ".join(rows[0].keys()).lower()
        if "rank" in cols or "item" in cols:
            return rows
        if len(rows) > len(best):
            best = rows
    return best


def god_names(s):
    body = api(s, action="query", list="categorymembers",
               cmtitle="Category:Gods", cmlimit=500)
    return [m["title"] for m in body.get("query", {}).get("categorymembers", [])
            if m["title"].lower() not in NOT_A_GOD]


def read_god(s, name):
    text = page_text(s, name)
    if not text:
        return None
    ranks = parse_table(text)
    if not ranks:
        return None
    # "== Mortos - Attack God ==" gives the skill it serves.
    head = re.search(r"==\s*" + re.escape(name) + r"\s*-\s*(.+?)\s*==", text)
    priest = re.search(r"===\s*High priest\s*===\s*(.+?)(?:\n=|\Z)",
                       text, re.S | re.I)
    where = re.search(r"===\s*Location\s*===\s*(.+?)(?:\n=|\Z)",
                      text, re.S | re.I)
    return {
        "god": name,
        "title": head.group(1).strip() if head else None,
        "priest": clean_cell(priest.group(1)) if priest else None,
        "where": clean_cell(where.group(1)) if where else None,
        "ranks": ranks,
        "columns": list(ranks[0].keys()) if ranks else [],
    }


def main():
    ap = argparse.ArgumentParser(description="What each rank of worship costs")
    ap.add_argument("--out", default=OUT)
    ap.add_argument("--dump", help="print one god's table and stop")
    a = ap.parse_args()

    s = session()
    if a.dump:
        g = read_god(s, a.dump)
        print(json.dumps(g, indent=2, ensure_ascii=False) if g
              else f"{a.dump}: no rank table")
        return

    names = god_names(s)
    print(f"{len(names)} pages in Category:Gods")
    gods, skipped = [], []
    for name in names:
        try:
            g = read_god(s, name)
        except Exception as e:
            print(f"  {name}: {e}")
            g = None
        if g:
            gods.append(g)
            print(f"  {g['god']} ({g['title']}): {len(g['ranks'])} ranks, "
                  f"columns {g['columns']}")
        else:
            skipped.append(name)
        time.sleep(PAUSE)

    with open(a.out, "w", encoding="utf-8") as f:
        json.dump({"_comment": "Rank tables from the EL wiki, by el_gods.py.",
                   "gods": gods}, f, indent=1, ensure_ascii=False)
    print(f"\n{len(gods)} gods with a rank table -> {a.out}")
    if skipped:
        print(f"  {len(skipped)} with none, which is right for the lore "
              f"gods: {', '.join(skipped)}")


if __name__ == "__main__":
    main()
