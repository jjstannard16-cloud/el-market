#!/usr/bin/env python3
"""
el_instances.py - what is behind each instance door, wave by wave.

Every creature page says which instances that creature turns up in, and
inverting those gave a list of six instances with six to eleven
creatures each. That list was both short and in the wrong order: the
Second Swamp (100-120 a/d) comes before the Second Mountain (120-140),
and guessing from the nicknames put them the other way round.

The wiki's Instances page has the real thing - five waves per instance,
the count for each creature, the attack/defense range that lets you in,
the wait between visits and the time limit - and it has them in order,
because the page is laid out by level.

    python el_instances.py            # fetch and write instances.json
    python el_instances.py --dump     # print what it read, nothing else

Three things the page does that a reader has to know about:

    40 [[Feros]] or 30 [[Desert Chimeran]]   one wave, either creature
    25 or 30 [[Meltean]]                     one creature, 25 to 30
    1-2 [[Mare Bulangiu]]                    the same, written properly

so a bare number before an "or" is the low end of a count, not a wave
option with its creature left out.

The names the page uses for the instances are not the names players
use: the Swamp instance is the noob instance, the Dungeon is the
WTF???111?!. The creature pages use the player names, so both are kept
and PLAYER_NAME joins them.
"""

import argparse
import json
import os
import re
import sys

try:
    import requests
except ImportError:
    sys.exit("Run: pip install requests")

from el_gods import api, clean_cell, session

PAGE = "Instances"
OUT = "instances.json"
CREATURES = "creatures.json"

# The wiki's section name, and what players call the same instance -
# which is what every creature page links to it as.
PLAYER_NAME = {
    "swamp": "Noob Instance",
    "mountain": "Advanced Instance",
    "second swamp": "Almost Pr0 Instance",
    "second mountain": "Pr0 Farm Instance",
    "ice": "Pr0 Instance",
    "dungeon": "WTF???111?! Instance",
}

# "Second Mountain instance 120-140 a/d, 160 hours"
# "Ice instance 120+ a/d, 150 hours"
# "Dungeon instance 110+ a/d, 96 hours"
HEADING = re.compile(r"""^(?P<name>.+?)\s+instance
     (?:\s+(?P<from>\d+)\s*(?:-\s*(?P<to>\d+)|(?P<plus>\+))?\s*a/d)?
     (?:\s*,\s*(?P<wait>\d+)\s*hours?)?\s*$""", re.I | re.X)
SECTION = re.compile(r"^(=+)\s*(.+?)\s*=+\s*$", re.M)
# "Also known as ''Instance for pr0s that want to farm'' instance,
#  short name, ''pr0 farm instance''" - the last quoted phrase is the
# one players actually say.
NICK = re.compile(r"''(.+?)''")
# A bare count standing in front of an "or": "25 or 30 Meltean".
JUST_A_NUMBER = re.compile(r"^\d+$")
COUNT = re.compile(r"^\s*(\d+(?:\s*-\s*\d+)?)\s+(.+?)\s*$")


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
    """Every heading with the lines under it, down to the next heading."""
    marks = [(m.start(), m.end(), len(m.group(1)), m.group(2))
             for m in SECTION.finditer(text)]
    for i, (start, end, depth, title) in enumerate(marks):
        stop = marks[i + 1][0] if i + 1 < len(marks) else len(text)
        yield title, text[end:stop]


def read_wave(line):
    """
    One wave line into the creatures it can hold.

    "40 [[Feros]] or 30 [[Desert Chimeran]]" is a choice of two; the
    game picks one when the instance starts. "25 or 30 [[Meltean]]" is
    one creature whose number varies, and the 25 must not be read as a
    second option with no creature.
    """
    parts = [p.strip() for p in re.split(r"\s+or\s+", clean_cell(line))]
    out, waiting = [], []
    for part in parts:
        if JUST_A_NUMBER.match(part):
            waiting.append(part)
            continue
        m = COUNT.match(part)
        count, who = (m.group(1), m.group(2)) if m else (None, part)
        if waiting:
            # "25 or 30 Meltean" -> 25-30 Meltean
            low = min(waiting + ([count] if count else []), key=int)
            high = max(waiting + ([count] if count else []), key=int)
            count = low if low == high else f"{low}-{high}"
            waiting = []
        who = who.strip(" .,")
        if who:
            out.append({"count": count, "creature": who})
    return out


def read_instance(title, body):
    m = HEADING.match(title)
    if not m:
        return None
    name = m.group("name").strip()
    one = {
        "name": name,
        "player": PLAYER_NAME.get(name.lower()),
        "adFrom": int(m.group("from")) if m.group("from") else None,
        "adTo": int(m.group("to")) if m.group("to") else None,
        "adPlus": bool(m.group("plus")),
        "wait": int(m.group("wait")) if m.group("wait") else None,
        "nick": None, "short": None, "minutes": None, "people": None,
        "notes": [], "waves": [],
    }

    lines = body.splitlines()
    in_waves = False
    for line in lines:
        bare = line.strip()
        if bare.startswith("**"):
            if in_waves:
                got = read_wave(bare.lstrip("* "))
                if got:
                    one["waves"].append(got)
            continue
        if not bare.startswith("*"):
            continue
        in_waves = False
        text = clean_cell(bare.lstrip("* "))
        low = text.lower()
        if low.startswith("waves are"):
            in_waves = True
        elif low.startswith("also known as"):
            quoted = NICK.findall(bare)
            if quoted:
                one["nick"] = quoted[-1].replace(" instance", "").strip()
        elif low.startswith("short name"):
            one["short"] = text.split(":", 1)[-1].strip()
        elif low.startswith("time"):
            got = re.search(r"(\d+)", text)
            if got:
                one["minutes"] = int(got.group(1))
        elif low.startswith("guide"):
            pass
        else:
            people = re.search(r"requires\s+(\d+)\s+(?:people|players)", low)
            if people:
                one["people"] = int(people.group(1))
            entered = re.search(r"from\s+(\d+)\s*a/d", low)
            if entered and one["adFrom"] is None:
                one["adFrom"] = int(entered.group(1))
                one["adPlus"] = True
            # Anything left is a note worth keeping, unless it only
            # repeats a fact already shown in its own right.
            said = people or entered or low.startswith("can be entered")
            if len(text) > 8 and not said:
                one["notes"].append(text)
    return one if one["waves"] else None


def main():
    ap = argparse.ArgumentParser(description="What is in each instance")
    ap.add_argument("--out", default=OUT)
    ap.add_argument("--dump", action="store_true")
    a = ap.parse_args()

    s = session()
    text = page_text(s, PAGE)
    if not text:
        sys.exit(f"The wiki has no {PAGE} page")

    found = []
    for title, body in sections(text):
        one = read_instance(title, body)
        if one:
            found.append(one)
    if not found:
        sys.exit("No instance has any waves - the page has been rewritten")

    # Every creature named in a wave should be one we hold stats for,
    # or the instance cannot say what a kill is worth. Spelling drifts
    # ("Cocaral" for Cocalar in a file name), so this is checked and
    # reported rather than assumed.
    known = {}
    if os.path.exists(CREATURES):
        known = {c["name"].lower(): c["name"] for c in
                 json.load(open(CREATURES, encoding="utf-8"))["creatures"]}
    unknown = []
    for one in found:
        for wave in one["waves"]:
            for opt in wave:
                real = known.get(opt["creature"].lower())
                if real:
                    opt["creature"] = real
                elif known:
                    unknown.append(f"{one['name']}: {opt['creature']}")

    json.dump({"_comment": "What is in each instance, from the EL wiki's "
                           "Instances page, by el_instances.py. In the "
                           "page's own order, which is by level.",
               "instances": found},
              open(a.out, "w", encoding="utf-8"), indent=1)

    print(f"{len(found)} instances from the {PAGE} page")
    for one in found:
        waves = sum(len(w) for w in one["waves"])
        ad = (f"{one['adFrom']}{'+' if one['adPlus'] else ''}"
              f"{'-' + str(one['adTo']) if one['adTo'] else ''}"
              if one["adFrom"] else "?")
        print(f"   {one['name']:16} {str(one['player']):22} {ad:9} "
              f"{len(one['waves'])} waves, {waves} creatures"
              + (f", {one['people']} people" if one["people"] else ""))
        if a.dump:
            for i, wave in enumerate(one["waves"], 1):
                shown = " or ".join(f"{o['count'] or '?'} {o['creature']}"
                                    for o in wave)
                print(f"      wave {i}: {shown}")
    if unknown:
        print(f"\nnot in creatures.json: {', '.join(unknown)}")


if __name__ == "__main__":
    main()
