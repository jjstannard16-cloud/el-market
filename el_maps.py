#!/usr/bin/env python3
"""
el_maps.py - what is on each map, and what each map leads to.

The wiki keeps a page per map and they are laid out the same way, so
one reader does all 91 of them:

    {{FoCW Header|Mynadar, Valley of the Dwarves|VotD}}
    === Map overview ===        prose, and the 512-pixel map picture
    === NPCs and Stores ===     * [[File:X.png|25px]] [[Name]] - job - [x,y]
    === Harvestables ===        * [[Name]] - '''[x,y]''', [x,y] 00:20
    === Creatures ===           * [[File:X 25px.png]] [[Name]] [x,y]
    === Specials ===            firepits and the like, with coordinates
    === Internal Maps ===       the caves and buildings you can go into
    === Exits to ===            a table per means: By Land, By Boat

    python el_maps.py            # fetch and write maps.json
    python el_maps.py --dump     # print what it read
    python el_maps.py --one "Valley of the Dwarves"

Two things worth knowing about the harvestables. A spot in bold is the
one the wiki thinks is best, so that is kept as the pick rather than
flattened in with the rest. And a good many lines end in something
like 00:20, which the pages never explain; it is stored as written and
called what the wiki calls it rather than guessed at.

The exits are the useful part. Every exit names the map it leads to
and the tile you leave from, so the 91 pages together make a graph:
which maps touch, how to get between two of them, and how far across
each one you have to walk on the way.
"""

import argparse
import json
import re
import sys
import time

try:
    import requests
except ImportError:
    sys.exit("Run: pip install requests")

API = "https://el-wiki.holy-eternalland.de/api.php"
UA = {"User-Agent": "EL-HQ/0.1 (Eternal Lands community site; stann in-game)"}
OUT = "maps.json"
TIMEOUT = 30
PAUSE = 0.25
LANDS = {"Seridia maps": "Seridia", "Irilion maps": "Irilion"}

SECTION = re.compile(r"^(=+)\s*(.+?)\s*=+\s*$", re.M)
# [[Target|Label]] or [[Target]]
LINK = re.compile(r"\[\[(?!File:|:?Category:)([^\]|#]+)(?:\|([^\]]*))?\]\]")
FILE = re.compile(r"\[\[File:([^\]|]+)[^\]]*\]\]", re.I)
# '''[84,39]''' is the wiki's pick; [14,28] is another of the same thing.
SPOT = re.compile(r"(''')?\[\s*(\d{1,4})\s*,\s*(\d{1,4})\s*\]")
CLOCK = re.compile(r"(?<![\d:])(\d{1,2}:\d{2})(?![\d:])")
HEADER = re.compile(r"\{\{\s*FoCW Header\s*\|([^|}]*)(?:\|([^|}]*))?", re.I)
# The 512-pixel drawing of the map itself, as against a photograph of
# somewhere on it.
MAPPIC = re.compile(r"\[\[File:(map_[^\]|]+?\.(?:png|jpe?g))", re.I)
TABLE = re.compile(r"\{\|.*?\|\}", re.S)
PK = re.compile(r"\(\s*PK\s*\)", re.I)


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
        if pg.get("missing"):
            return None
        revs = pg.get("revisions") or [{}]
        return (revs[0].get("slots", {}).get("main", {}).get("content")
                or revs[0].get("content") or "")
    return None


def sections(text):
    """Each heading with what sits under it, down to the next heading."""
    marks = [(m.start(), m.end(), m.group(2)) for m in SECTION.finditer(text)]
    out = [("", text[:marks[0][0]] if marks else text)]
    for i, (start, end, title) in enumerate(marks):
        stop = marks[i + 1][0] if i + 1 < len(marks) else len(text)
        out.append((title, text[end:stop]))
    return out


def section_named(parts, *words):
    """The first section whose heading mentions one of these words."""
    for title, body in parts:
        low = title.lower()
        if any(w in low for w in words):
            return body
    return ""


def plain(text):
    """Wiki markup out, words left."""
    text = FILE.sub(" ", text)
    text = LINK.sub(lambda m: (m.group(2) or m.group(1)).strip(), text)
    text = re.sub(r"<!--.*?-->", " ", text, flags=re.S)
    text = re.sub(r"<[^>]+>", " ", text)
    text = text.replace("'''", "").replace("''", "")
    return " ".join(text.split())


def spots(text):
    """Every [x,y] on the line, with the wiki's own pick marked."""
    out = []
    for bold, x, y in SPOT.findall(text):
        out.append({"x": int(x), "y": int(y), "pick": bool(bold)})
    return out


def bullets(body):
    """The bullet lines of a section, comments and blanks dropped."""
    for line in body.splitlines():
        line = line.strip()
        if not line.startswith("*") or line.startswith("<!--"):
            continue
        line = re.sub(r"<!--.*?-->", "", line)
        if line.strip("* "):
            yield line.lstrip("* ").strip()


def thing(line):
    """
    One bullet into what it is, where it is and what was said about it.

    The name is the first real link on the line, which is the same
    whether the line writes the picture first, as the creature lists
    do, or the name first, as a few of the older pages do.
    """
    m = LINK.search(line)
    if not m:
        return None
    name = (m.group(1) or "").strip()
    label = (m.group(2) or "").strip()
    # The rest of the line with the name taken out, so "Storage - [43,124]"
    # keeps the word Storage and loses the repetition.
    rest = plain(line[m.end():]).strip(" -–:,")
    at = spots(line)
    clock = CLOCK.search(plain(line))
    one = {"name": label or name, "page": name}
    if at:
        one["at"] = at
    if rest:
        one["what"] = rest[:160]
    if clock:
        one["clock"] = clock.group(1)
    if PK.search(line):
        one["pk"] = True
    return one


def read_exits(body):
    """
    The exits table, which is one table per means of travel. The header
    cell names it - By Land, By Boat - and each row is an icon and the
    map it leads to with the tile you leave from.
    """
    out = []
    for table in TABLE.findall(body):
        head = re.search(r"^\s*!.*?\|\s*(?:By\s+)?([A-Za-z ]+?)\s*$",
                         table, re.M)
        how = (head.group(1).strip() if head else "") or "Land"
        for row in re.split(r"^\|-\s*$", table, flags=re.M)[1:]:
            one = thing(" ".join(
                line.lstrip("| ").strip()
                for line in row.splitlines() if line.startswith("|")))
            if one:
                one["how"] = how
                out.append(one)
    # A page or two writes its exits as bullets instead of a table.
    if not out:
        for line in bullets(body):
            one = thing(line)
            if one:
                one["how"] = "Land"
                out.append(one)
    return out


def read_map(s, title, land):
    text = page_text(s, title)
    if not text:
        return None
    parts = sections(text)
    top = parts[0][1]
    head = HEADER.search(text)
    overview = section_named(parts, "overview")
    pic = MAPPIC.search(overview) or MAPPIC.search(text)
    # The first picture that is not the map drawing is a photograph of
    # the place, which the page uses as its thumbnail.
    photo = None
    for f in FILE.findall(top + overview):
        if not f.lower().startswith("map_"):
            photo = f
            break

    one = {
        "name": title,
        "land": land,
        "full": (head.group(1).strip() if head and head.group(1) else None),
        "short": (head.group(2).strip() if head and head.group(2) else None),
        "about": plain(re.sub(r"\[\[File:[^\]]*\]\]", "", overview))[:900],
        "pic": pic.group(1) if pic else None,
        "photo": photo,
        "npcs": [], "harvest": [], "creatures": [], "specials": [],
        "inside": [], "exits": read_exits(section_named(parts, "exits")),
    }
    for key, words in (("npcs", ("npc", "stores")),
                       ("harvest", ("harvestable",)),
                       ("creatures", ("creature",)),
                       ("specials", ("special",)),
                       ("inside", ("internal",))):
        for line in bullets(section_named(parts, *words)):
            got = thing(line)
            if got:
                one[key].append(got)
    # The header's second field is whatever the page's author put
    # there: an acronym on one page (VotD), the map it sits inside on
    # another (Abandoned Temple says "Valley of the Dwarves"), and a
    # tagline on a third (White Stone says "Home of Raven"). It is
    # sorted out by the caller, which knows every map's name.
    one["hint"] = one.pop("short")
    # The same exit is sometimes listed twice, once with the tile and
    # once without.
    seen, keep = set(), []
    for x in sorted(one["exits"], key=lambda e: not e.get("at")):
        key = (x["name"], x["how"])
        if key in seen:
            continue
        seen.add(key)
        keep.append(x)
    one["exits"] = keep
    return one


def main():
    ap = argparse.ArgumentParser(description="What is on each map")
    ap.add_argument("--out", default=OUT)
    ap.add_argument("--dump", action="store_true")
    ap.add_argument("--one")
    a = ap.parse_args()

    s = requests.Session()
    s.headers.update(UA)

    wanted = []
    if a.one:
        wanted = [(a.one, "Seridia")]
    else:
        for cat, land in LANDS.items():
            body = api(s, action="query", list="categorymembers",
                       cmtitle=f"Category:{cat}", cmlimit=500)
            for m in body.get("query", {}).get("categorymembers", []):
                wanted.append((m["title"], land))
    print(f"{len(wanted)} map pages")

    # The continent overview pages are in the category but are not maps.
    wanted = [(t, land) for t, land in wanted if t not in LANDS.values()]

    maps, thin = [], []
    for title, land in wanted:
        one = read_map(s, title, land)
        if not one:
            thin.append(f"{title}: no page")
            continue
        maps.append(one)
        if not any(one[k] for k in ("npcs", "harvest", "creatures", "exits")):
            thin.append(f"{title}: nothing read")
        time.sleep(PAUSE)

    # Now every map's name is known, the header hint can be read: a
    # map's name means this one sits inside that one, something short
    # is what players call it, and the rest is a tagline nobody needs.
    names = {m["name"].lower() for m in maps}
    for m in maps:
        hint, m["short"], m["inside_of"] = m.pop("hint"), None, None
        if not hint:
            continue
        if hint.lower() in names and hint.lower() != m["name"].lower():
            m["inside_of"] = hint
        elif len(hint) <= 6 and " " not in hint:
            m["short"] = hint

    json.dump({"_comment": "What is on each map and what it leads to, from "
                           "the EL wiki's map pages, by el_maps.py.",
               "maps": maps},
              open(a.out, "w", encoding="utf-8"), indent=1,
              ensure_ascii=False)

    tally = lambda k: sum(len(m[k]) for m in maps)
    print(f"{len(maps)} maps: {tally('npcs')} NPCs, "
          f"{tally('harvest')} harvestable spots, {tally('creatures')} "
          f"creature sightings, {tally('exits')} exits, "
          f"{sum(1 for m in maps if m['pic'])} with a map picture, "
          f"{sum(1 for m in maps if m['inside_of'])} inside another map")
    if a.dump:
        for m in maps:
            print(f"\n--- {m['name']} ({m['land']}) "
                  f"{m['short'] or ''} pic={m['pic']}")
            for k in ("npcs", "harvest", "creatures", "specials", "inside"):
                for x in m[k][:4]:
                    where = ", ".join(f"[{p['x']},{p['y']}]"
                                      for p in x.get("at", []))
                    print(f"   {k[:4]:5} {x['name'][:28]:28} {where[:44]:44}"
                          f" {x.get('clock') or ''}")
            for x in m["exits"]:
                print(f"   exit  {x['how']:6} {x['name'][:28]:28} "
                      + ", ".join(f"[{p['x']},{p['y']}]"
                                  for p in x.get("at", [])))
    if thin:
        print(f"\n{len(thin)} pages gave little or nothing:")
        for line in thin:
            print("   " + line)


if __name__ == "__main__":
    main()
