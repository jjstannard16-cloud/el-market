#!/usr/bin/env python3
"""
el_creatures.py - what lives in the game, and what it drops.

Fighting is where the money is, so this is the other half of the market
data: every creature's stats, where it is found, what it drops normally
and what it drops rarely. The site joins the drops to what bots pay for
them, which is the part no other source has.

Three kinds of page on the wiki, all of them read here:

    Creature statistics      one table of stats for every creature
    <Creature>               locations, normal drops, instances
    Rare Drops of <Creature> the rare drops, as players confirm them

    python el_creatures.py              # fetch and write creatures.json
    python el_creatures.py --one Feros  # print one creature and stop

Anything the wiki does not say is left empty rather than guessed, and
the counts at the end say how much was found.
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

# The wikitable reader already written for the god rank tables.
from el_gods import api, clean_cell, parse_one, session, TABLE

OUT = "creatures.json"
PAUSE = 0.35
STATS_PAGE = "Creature statistics"

# Categories that say what kind of thing a creature is.
KINDS = {
    "Animals": "animal",
    "Monsters": "monster",
    "Other Creatures": "other",
    "Instance creatures": "instance",
    "Invance creatures": "invance",
    "Invasion creatures": "invasion",
}

# "Attack/Defense: || <font color="red">105/90</font>"
STAT_ROW = re.compile(r"^\s*\|\s*([A-Za-z /]+?)\s*:\s*\|\|\s*(.+?)\s*$")
SECTION = re.compile(r"^=+\s*(.+?)\s*=+\s*$", re.M)
# A table cell, which is a line opening with a single pipe. The closing
# "|}" and the row divider "|-" are not cells and must not be read as one.
CELL = re.compile(r"^\s*\|(?![-}])\s*(.+?)\s*$", re.M)
# "* [[File:X.png|25px]] 4 [[Invisibility Potion|Invisibility Potions]]"
BULLET = re.compile(r"^\*\s*(.+?)\s*$", re.M)
# "0-35 Gold coins", "4 Invisibility Potions", "150,000-340,213 Gold
# Coins", "~200k-835k Gold Coins". The wiki writes big numbers however
# it likes and a Castellan's whole worth hangs on reading them.
AMOUNT = re.compile(r"""^\s*~?\s*
     ((?:\d[\d,.]*\s*[km]?|\?+)
      (?:\s*(?:-|to|\u2013)\s*~?\s*(?:\d[\d,.]*\s*[km]?|\?+))?)
     \s+(.+?)\s*$""", re.X | re.I)
# A table cell may carry its layout before the content it holds:
#   | style="width: 95%;" | 1 [[Bones]]
# The attributes are not the drop. Reading them as one lost every drop
# on every page that styles the item cell as well as the icon cell.
CELL_ATTRS = re.compile(r"""^\s*
     [A-Za-z-]+\s*=\s*"[^"]*"
     (?:\s+[A-Za-z-]+\s*=\s*"[^"]*")*
     \s*\|(?!\|)""", re.X)
# Any heading that mentions drops is a drops section. 94 creature pages
# call it "Drops" and the rest do not: "Invasion Drops", "Instance
# Drops", "Normal drops", "Additional drops", "Possible Special Drops".
# Matching the word rather than the heading is what finds Castellan's.
DROPS = re.compile(r"drop", re.I)
# A heading or a table header saying these means a drop you cannot
# count on. "Normal" outranks them, because Castellan's instance table
# is headed "Normal Drops" inside a section headed "Instance Drops".
RARE_WORDS = ("rare", "other", "additional", "special", "unusual",
              "chance", "possible")


def page_text(s, title):
    body = api(s, action="query", prop="revisions", titles=title,
               rvprop="content", rvslots="main", redirects=1)
    for pg in body.get("query", {}).get("pages", []):
        if pg.get("missing"):
            return None
        revs = pg.get("revisions") or [{}]
        return (revs[0].get("slots", {}).get("main", {}).get("content")
                or revs[0].get("content") or "")
    return None


def members(s, category):
    out, cont = [], None
    for _ in range(10):
        kw = {"action": "query", "list": "categorymembers",
              "cmtitle": f"Category:{category}", "cmlimit": 500}
        if cont:
            kw["cmcontinue"] = cont
        body = api(s, **kw)
        out += [m["title"] for m in
                body.get("query", {}).get("categorymembers", [])]
        cont = body.get("continue", {}).get("cmcontinue")
        if not cont:
            break
        time.sleep(PAUSE)
    return out


def section_of(wikitext, name):
    """The wikitext under a heading, up to the next heading of any level."""
    heads = [(m.start(), m.end(), m.group(1)) for m in SECTION.finditer(wikitext)]
    for i, (start, end, title) in enumerate(heads):
        if title.strip().lower() == name.lower():
            stop = heads[i + 1][0] if i + 1 < len(heads) else len(wikitext)
            return wikitext[end:stop]
    return ""


def cell_text(raw):
    """One table cell, without the layout it carries."""
    return clean_cell(CELL_ATTRS.sub("", raw))


def drop_sections(wikitext):
    """Every section whose heading mentions drops, with that heading."""
    heads = [(m.start(), m.end(), m.group(1))
             for m in SECTION.finditer(wikitext)]
    for i, (start, end, title) in enumerate(heads):
        if DROPS.search(title):
            stop = heads[i + 1][0] if i + 1 < len(heads) else len(wikitext)
            yield title.strip(), wikitext[end:stop]


def is_rare(heading, header):
    """
    Whether a table holds drops you cannot count on.

    The heading is believed before the table under it, because Invdrag
    heads a table "Normal Drops" under "Possible Special Drops" and
    says in words above it that only one of the eight will drop.
    Counting all eight as normal made the kill look eight times richer
    than it is. A heading that says neither leaves it to the table, and
    a plain "Drops" with nothing said either way means the ordinary
    ones.
    """
    for text in (heading, header or ""):
        low = text.lower()
        if "normal" in low:
            return False
        if any(w in low for w in RARE_WORDS):
            return True
    return False


def where_of(heading, header):
    """
    Which fight these drops are for. A Castellan killed in an instance
    carries ~200k-835k gold; the same Castellan in an invasion carries
    150,000-340,213, and its page keeps the two apart.
    """
    low = f"{heading} {header}".lower()
    if "instance" in low:
        return "instance"
    if "invasion" in low or "invance" in low:
        return "invasion"
    return None


NOTE = re.compile(r"\s*\(([^)]*)\)")
# A cell that opens with question marks: "?? [[Gold Coins]]" is the
# wiki saying nobody has written the number down. clean_cell rubs the
# marks off, so the raw line is what has to be asked.
FIRST_Q = re.compile(r'^\s*(?:[A-Za-z-]+\s*=\s*"[^"]*"\s*\|)?\s*\?+(\s|$)')


def tidy_item(what):
    """
    An item name, and anything the wiki said about it in brackets.

    "1 Human Removal Stone (20% chance)" names an item no bot has ever
    heard of; the stone itself they have. The note is worth keeping and
    showing, but not inside the name.
    """
    note = " ".join(n.strip() for n in NOTE.findall(what)).strip(" ?")
    what = " ".join(NOTE.sub(" ", what).split())
    return what, (note or None)


def read_drop(raw, clean):
    """
    One drop line into what it is, how many, and anything said about it
    in brackets.

    An amount the wiki has not recorded is kept as a question mark
    rather than left empty, because an empty amount means one and a
    Meltean does not drop one gold coin.
    """
    what, note = tidy_item(clean)
    n, what = split_amount(what)
    if n is None and FIRST_Q.match(raw):
        n = "?"
    if not what:
        return None
    one = {"n": n, "item": what}
    if note:
        one["note"] = note
    return one


def split_amount(text):
    """'0-35 Gold coins' -> ('0-35', 'Gold coins')."""
    m = AMOUNT.match(text)
    if m:
        return m.group(1).replace(" ", ""), m.group(2)
    return None, text


def read_master(s):
    """
    The one page with every creature's stats. It holds a table per kind
    of creature, each with its own columns, so they are read together
    and keyed on the creature's name.
    """
    body = page_text(s, STATS_PAGE) or ""
    out = {}
    for m in TABLE.finditer(body):
        for row in parse_one(m.group()[2:-2]):
            keys = {k.lower(): v for k, v in row.items()}
            name = keys.get("creature") or ""
            if not name:
                continue
            out[name.lower()] = {
                "name": name,
                "attack": keys.get("attack"),
                "defense": keys.get("defense"),
                "material": keys.get("material points"),
                "respawn": keys.get("respawn time"),
                "hostile": keys.get("hostile"),
            }
    return out


def read_creature(s, title):
    body = page_text(s, title)
    if body is None:
        return None

    stats = OrderedDict()
    for line in body.splitlines():
        m = STAT_ROW.match(line)
        if m:
            stats[m.group(1).strip()] = clean_cell(m.group(2))

    # Locations and instances sit in small tables under their heading.
    places, instances = [], []
    for m in TABLE.finditer(section_of(body, "Locations")):
        chunk = m.group()
        header = re.search(r"^\s*!\s*(?:colspan=\"\d+\"\s*\|)?\s*(.+?)\s*$",
                           chunk, re.M)
        label = clean_cell(header.group(1)) if header else ""
        cells = [cell_text(c) for c in CELL.findall(chunk)]
        cells = [c for c in cells if c and c != "}"]
        if label.lower().startswith("instance"):
            instances += cells
        else:
            places += [{"where": c, "region": label} for c in cells]

    # A drops section holds a table per kind - "Normal Drops" and "Rare
    # Drops" - and only the header tells them apart. A rare drop listed
    # as a normal one would be badly misleading, so the header is read
    # rather than assumed. Some pages use no table at all and write the
    # drops as a bulleted list, which is read when there is no table.
    drops, rare_here = [], []
    for heading, text in drop_sections(body):
        tables = list(TABLE.finditer(text))
        for m in tables:
            chunk = m.group()
            header = re.search(
                r"^\s*!\s*(?:colspan=\"\d+\"\s*\|)?\s*(.+?)\s*$", chunk, re.M)
            label = cell_text(header.group(1)) if header else ""
            into = rare_here if is_rare(heading, label) else drops
            where = where_of(heading, label)
            for cell in CELL.findall(chunk):
                clean = cell_text(cell)
                if not clean or clean == "}":
                    continue
                one = read_drop(cell, clean)
                if one:
                    if where:
                        one["where"] = where
                    into.append(one)
        if not tables:
            into = rare_here if is_rare(heading, "") else drops
            where = where_of(heading, "")
            for one in bullet_drops(text):
                if where:
                    one["where"] = where
                into.append(one)

    return {"stats": stats, "places": places, "instances": instances,
            "drops": drops, "rareOnPage": rare_here}


def bullet_drops(text):
    """
    Drops written as a list rather than a table, which is how a Badaran
    says it carries 50k-150k gold. Only the top level is read: a bullet
    ending in a colon introduces alternatives - "One of the following
    Day Stones:" - and counting all seven as dropping would make the
    kill look worth several times what it is.
    """
    out = []
    for line in text.splitlines():
        if not line.startswith("*") or line.startswith("**"):
            continue
        clean = clean_cell(line.lstrip("* "))
        if not clean or clean.endswith(":") or len(clean) > 60:
            continue
        one = read_drop(line.lstrip("* "), clean)
        if not one or one["item"].lower() in ("none", "nothing", "unknown",
                                              "n/a"):
            continue
        # An item name is a few words. Anything longer is the wiki
        # explaining itself - "Gold coins he gets from creature kills"
        # - and is not a drop a bot can price.
        if len(one["item"].split()) > 6:
            continue
        out.append(one)
    return out


def read_rare(s, creature):
    """
    The rare drops page, which is a bulleted list with a signature under
    each line. Only the lines naming an item are kept.
    """
    for title in (f"Rare Drops of {creature}s", f"Rare Drops of {creature}"):
        body = page_text(s, title)
        if body is None:
            continue
        out = []
        for m in BULLET.finditer(body):
            line = m.group(1)
            if line.lstrip().startswith("--") or "User:" in line:
                continue
            clean = clean_cell(line)
            if not clean or len(clean) > 60:
                continue
            if re.search(r"copy the drop line|confirm a drop|signature",
                         clean, re.I):
                continue
            one = read_drop(line, clean)
            if not one or one["item"].lower().startswith(("new drops",
                                                          "to ")):
                continue
            if len(one["item"].split()) > 6:
                continue
            out.append(one)
        return out, title
    return [], None


def main():
    ap = argparse.ArgumentParser(description="Creatures, stats and drops")
    ap.add_argument("--out", default=OUT)
    ap.add_argument("--one", help="print one creature and stop")
    a = ap.parse_args()

    s = session()
    if a.one:
        print(json.dumps({"page": read_creature(s, a.one),
                          "rare": read_rare(s, a.one)[0]},
                         indent=2, ensure_ascii=False))
        return

    master = read_master(s)
    print(f"{len(master)} creatures in {STATS_PAGE}")

    kind_of, names = {}, []
    for cat, kind in KINDS.items():
        for title in members(s, cat):
            if title.startswith("Category:") or title in KINDS:
                continue
            kind_of.setdefault(title, []).append(kind)
            if title not in names:
                names.append(title)
        time.sleep(PAUSE)
    # A creature in the stats table but in no category is still real.
    for key, row in master.items():
        if row["name"] not in names:
            names.append(row["name"])
    print(f"{len(names)} creature pages to read")

    out, no_page, with_drops, with_rare = [], [], 0, 0
    for title in sorted(names):
        try:
            page = read_creature(s, title)
        except Exception as e:
            print(f"  {title}: {e}")
            page = None
        if page is None:
            no_page.append(title)
            page = {"stats": {}, "places": [], "instances": [],
                    "drops": [], "rareOnPage": []}
        rare, _ = read_rare(s, title)
        # A creature page can list its rare drops itself; both sources
        # are kept, without listing the same item twice.
        # "10k Gold Coins" and "10k gold coins" are one drop written
        # twice, so the two sources are matched without regard to case.
        def same(r):
            return (str(r.get("n") or "").lower(), r["item"].lower())
        seen = {same(r) for r in rare}
        for r in page.get("rareOnPage", []):
            if same(r) not in seen:
                seen.add(same(r))
                rare.append(r)
        # The creature's own page is the reliable source: its statistics
        # box is a plain key-and-value list. The master table's columns
        # do not line up for the monsters - it had the Blue Dragon with
        # 179 health when its page says 9,000 - so that is used only to
        # fill a gap, and only where it agrees in shape.
        base = master.get(title.lower(), {})
        stats = page["stats"]
        ad = (stats.get("Attack/Defense") or "").split("/")
        attack = ad[0].strip() if ad and ad[0].strip() else base.get("attack")
        defense = (ad[1].strip() if len(ad) > 1 and ad[1].strip()
                   else base.get("defense"))
        health = stats.get("Health Points") or base.get("material")
        # A respawn is a time, so the master table's value is taken only
        # when it says so. It had the Blue Dragon respawning in "179".
        respawn = stats.get("Respawn Time")
        if not respawn and re.search(r"sec|min|hour",
                                     str(base.get("respawn") or ""), re.I):
            respawn = base.get("respawn")
        hostile = base.get("hostile")
        if hostile not in ("Yes", "No"):
            hostile = None
        out.append({
            "name": title,
            "kinds": kind_of.get(title, []),
            "attack": attack,
            "defense": defense,
            "material": health,
            "respawn": respawn,
            "hostile": hostile,
            "stats": page["stats"],
            "places": page["places"],
            "instances": page["instances"],
            "drops": page["drops"],
            "rare": rare,
        })
        with_drops += 1 if page["drops"] else 0
        with_rare += 1 if rare else 0
        time.sleep(PAUSE)

    with open(a.out, "w", encoding="utf-8") as f:
        json.dump({"_comment": "Creature stats and drops from the EL wiki, "
                               "by el_creatures.py.",
                   "creatures": out}, f, indent=1, ensure_ascii=False)
    print(f"\n{len(out)} creatures -> {a.out}")
    print(f"  {with_drops} with normal drops, {with_rare} with rare drops")
    if no_page:
        print(f"  {len(no_page)} with no page of their own: "
              + ", ".join(no_page))


if __name__ == "__main__":
    main()
