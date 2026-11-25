#!/usr/bin/env python3
"""
el_dailies.py - what each daily quest can ask you for.

The community quest guide describes the dailies in one line each -
"Provide a number of furs, skins, and other creature parts for
summoning experience" - because what you are asked for changes every
day and the pay depends on your level. True, and no use at all to
somebody deciding whether today's task is worth doing.

The lists do exist. vinoveritas keeps them at holy-eternalland.de, the
same place as the wiki and Mercator, one page per daily:

    python el_dailies.py             # fetch and write dailies.json
    python el_dailies.py --dump      # print what it read

Five of the nine are tabular and are read here. Four are prose - Lord
Luxin's clothes, Kaleb's dung, Tatu's mule run and Dorel's temp agency
- and are left alone rather than half-parsed into something that looks
like data and is not.

The pay is nearly always "3000xp plus so much per level", so the two
numbers are kept apart: the site can then work out what a given player
gets rather than printing a formula at them.
"""

import argparse
import json
import re
import sys
import time

try:
    import requests
    from bs4 import BeautifulSoup
except ImportError:
    sys.exit("Run: pip install requests beautifulsoup4 lxml")

BASE = "https://holy-eternalland.de/en/eternal-lands-quests/haidir-daily/"
UA = {"User-Agent": "EL-HQ/0.1 (Eternal Lands community site; stann in-game)"}
OUT = "dailies.json"
TIMEOUT = 30
PAUSE = 0.4

# Our quest name -> its page, and which skill the experience is in.
PAGES = {
    "Summoning Daily": ("14-maja-daily-summoning.html", "Summoning"),
    "Combat Daily": ("4-haidir-daily-fighting-quests.html", "Attack/Defense"),
    "Engineering Daily": ("9-minel-engenering-daily.html", "Engineering"),
    "Harvesting Daily": ("6-xaquelina-daily-quest.html", "Harvesting"),
    "Armor and Weapon Supply Daily":
        ("5-darithas-daily-quest-manufacture-items.html", "Attack/Defense"),
}

# A header cell to the field it holds. Matched on the words in it, so
# "Reward XP(to be multiplied by (a d))" and "xp" both land on xpPer.
HEADERS = [
    (r"^npc$", "npc"),
    (r"^(item|harvestable|job|what)", "what"),
    (r"^location|^where|^spawns?$", "where"),
    (r"base\s*xp", "xpBase"),
    (r"xp|experience", "xpPer"),
    (r"^gc$|reward\s*\(gc\)|^gold", "gc"),
    (r"level\s*requirement|^req", "needs"),
]

NUMBER = re.compile(r"(\d[\d,.]*)\s*([km])?", re.I)
# "100 rat tails", "03 Titanium chainmail", "30 Orcs (male, female)"
COUNT_FIRST = re.compile(r"^\s*#?0*(\d+)\s+(.+?)\s*$")
# Maia's page is laid out with spaces rather than a table:
#   100 wolf furs    3000xp SUM +   140xp per SUM level      130gc
MAIA = re.compile(r"""^\s*\#?0*(?P<n>\d+)\s+(?P<what>[A-Za-z][A-Za-z' ]+?)\s{2,}
     (?P<base>[\d,]+)\s*xp\s*\w*\s*\+\s*(?P<per>[\d,]+)\s*xp\s*per
     [^\d]*?(?:\s{2,}|\s)(?P<gc>[\d,]+)\s*gc""", re.X | re.I)


def number(text):
    """The first number in a cell, k and m and commas understood."""
    if not text:
        return None
    m = NUMBER.search(text.replace(" ", ""))
    if not m:
        return None
    n = float(m.group(1).replace(",", ""))
    if (m.group(2) or "").lower() == "k":
        n *= 1_000
    elif (m.group(2) or "").lower() == "m":
        n *= 1_000_000
    return int(n)


def split_count(text):
    """'100 rat tails' -> (100, 'rat tails')."""
    m = COUNT_FIRST.match(text or "")
    return (int(m.group(1)), m.group(2)) if m else (None, (text or "").strip())


def article(soup):
    return (soup.select_one(".com-content-article__body")
            or soup.select_one("[itemprop=articleBody]")
            or soup.select_one(".item-page") or soup)


def field_of(header):
    low = " ".join(header.lower().split())
    for pattern, field in HEADERS:
        if re.search(pattern, low):
            return field
    return None


def read_table(table):
    """
    One wikitable-ish table into rows, going by its own header.

    Nothing is read by column position: these five pages were written
    by different people in different years and no two put the columns
    in the same order.
    """
    rows = table.find_all("tr")
    if len(rows) < 2:
        return []
    head = [c.get_text(" ", strip=True) for c in rows[0].find_all(["th", "td"])]
    fields = [field_of(h) for h in head]
    if "what" not in fields:
        return []
    out = []
    for tr in rows[1:]:
        cells = [" ".join(c.get_text(" ", strip=True).split())
                 for c in tr.find_all(["td", "th"])]
        if not any(cells):
            continue
        one = {}
        for field, cell in zip(fields, cells):
            if not field or not cell:
                continue
            # A second "where" column (Haidir lists the NPC's tavern and
            # the creature's spawns) is kept as the spawn note.
            if field in one and field == "where":
                one["spawns"] = cell
                continue
            one[field] = cell
        if not one.get("what"):
            continue
        n, what = split_count(one["what"])
        one["n"], one["what"] = n, what
        for key in ("xpBase", "xpPer", "gc"):
            if key in one:
                one[key] = number(one[key])
        out.append(one)
    return out


def read_maia(text):
    """Maia's list, which is lines of text lined up with spaces."""
    out = []
    for line in text.splitlines():
        m = MAIA.match(line)
        if not m:
            continue
        out.append({"n": int(m.group("n")),
                    "what": m.group("what").strip(),
                    "xpBase": number(m.group("base")),
                    "xpPer": number(m.group("per")),
                    "gc": number(m.group("gc"))})
    return out


def main():
    ap = argparse.ArgumentParser(description="What each daily asks for")
    ap.add_argument("--out", default=OUT)
    ap.add_argument("--dump", action="store_true")
    a = ap.parse_args()

    s = requests.Session()
    s.headers.update(UA)
    found, failed = {}, []
    for quest, (slug, skill) in PAGES.items():
        url = BASE + slug
        try:
            r = s.get(url, timeout=TIMEOUT)
            r.raise_for_status()
        except Exception as e:
            failed.append(f"{quest}: {e}")
            continue
        body = article(BeautifulSoup(r.text, "lxml"))
        rows = []
        for table in body.find_all("table"):
            rows += read_table(table)
        if not rows:
            rows = read_maia(body.get_text("\n", strip=True))
        if rows:
            found[quest] = {"skill": skill, "source": url, "asks": rows}
        else:
            failed.append(f"{quest}: nothing parsed from {url}")
        time.sleep(PAUSE)

    if not found:
        sys.exit("No daily could be read at all - the pages have moved")

    json.dump({"_comment": "What each daily quest can ask for, from the "
                           "quest pages at holy-eternalland.de, by "
                           "el_dailies.py. Keyed on the quest name as "
                           "quests.json writes it.",
               "dailies": found},
              open(a.out, "w", encoding="utf-8"), indent=1, ensure_ascii=False)

    print(f"{len(found)} dailies read")
    for quest, one in found.items():
        priced = sum(1 for r in one["asks"] if r.get("xpPer"))
        print(f"   {quest:32} {len(one['asks']):3} tasks, "
              f"{priced} with experience, {one['skill']}")
        if a.dump:
            for r in one["asks"]:
                print(f"      {str(r.get('n') or ''):>4} {r['what'][:34]:34} "
                      f"xp {str(r.get('xpBase') or '-'):>5}"
                      f"+{str(r.get('xpPer') or '-'):>5}/lvl  "
                      f"gc {str(r.get('gc') or '-'):>6}  "
                      f"{(r.get('where') or '')[:40]}")
    for line in failed:
        print("  could not read", line)


if __name__ == "__main__":
    main()
