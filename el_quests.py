#!/usr/bin/env python3
"""
el_quests.py - turn the community quest guide into structured data.

The guide is a PDF a player maintains, so this reads the text pulled out
of it rather than the PDF itself, and writes quests.json for the site to
render. The result is committed, so the site does not depend on anyone
having the PDF to hand.

    pdftotext -layout choris_quests.pdf quests.txt
    python el_quests.py quests.txt --out quests.json

The guide opens with a table of contents and a cross-reference of what
each quest pays per skill. Both are used: the contents gives every quest
its name and section, and the cross-reference gives the experience, so
nothing here is guessed from the prose.
"""

import argparse
import json
import re
import sys
from collections import OrderedDict

# A contents line: name, a run of dots, then the page.
CONTENTS = re.compile(r"^(\s*)(\S.*?)\s*\.{4,}\s*(\d+)\s*$")

# Page furniture that the extractor leaves behind.
NOISE = re.compile(
    r"^\s*(-\s*\d+\s*-|(Back to the )?Table of Contents\s*(-\s*\d+\s*-)?)\s*$",
    re.I)

# The blocks inside a quest, in the order the guide writes them.
BLOCKS = ["Reward", "Rewards", "Items Needed", "Item Needed", "Steps",
          "Notes", "Note", "Requirements", "Prerequisites"]
BLOCK_RE = re.compile(r"^\s*(" + "|".join(BLOCKS) + r")\s*:?\s*$", re.I)
CANON_BLOCK = {"rewards": "reward", "item needed": "items needed",
               "note": "notes", "prerequisites": "requirements"}

START_NPC = re.compile(r"^\s*Start NPC\s*:\s*(.+?)\s*$", re.I)
PREREQ = re.compile(r"^\s*Prerequisite(?: Quest)?s?\s*:\s*(.+?)\s*$", re.I)
# "Strajer, Portland [217,122]" -> npc, where, x, y. A line can carry a
# second pair ("Naralik Catacombs [105,162], inside at [20,80]"), so the
# first one wins and the rest is kept as part of the place.
NPC_PLACE = re.compile(
    r"^(.*?),\s*(.*?)\s*\[\s*(\d+)\s*,\s*(\d+)\s*\]\s*(.*)$")
STEP = re.compile(r"^\s*(\d+)\.\s+(.*)$")
SUBSTEP = re.compile(r"^\s*([a-z])\.\s+(.*)$")
# "75,000 Attack" or "100 Treasure finders"
REWARD_LINE = re.compile(r"^\s*([\d,]+)\s+(.+?)\s*$")


# The god pages head each entry with the skill on the left and the god on
# the right of the same line: "Attack            (Mortos)".
GOD_HEAD = re.compile(r"^\s*([A-Z][A-Za-z ]{2,20}?)\s{6,}\((\w[\w '-]*)\)\s*$")
GOD_BLOCKS = ["High Priest", "Benefits", "Blessing", "Enemies",
              "Starting rank", "Quests", "Notes"]
GOD_BLOCK_RE = re.compile(r"^\s*(" + "|".join(GOD_BLOCKS) + r")\s*:?\s*$", re.I)


# Review anchors the PDF carries over from its author's comments, stuck
# onto the end of a heading: "Novac's Potion 1[SS1]".
ANCHOR = re.compile(r"\[[A-Za-z]{1,4}\d{1,3}\]\s*$")

NOT_IN_GAME = re.compile(r"^\s*not yet in game\.?\s*$", re.I)


def clean(lines):
    out = []
    for ln in lines:
        ln = ln.replace("\x0c", "").replace("\uf0b7", "\u2022").rstrip()
        ln = ANCHOR.sub("", ln).rstrip()
        if not NOISE.match(ln):
            out.append(ln)
    return out


def read_contents(lines):
    """
    The contents, as an ordered {quest name: section}. A line with no
    indent is a section; an indented one is a quest inside it.
    """
    out, section = OrderedDict(), None
    for ln in lines:
        m = CONTENTS.match(ln)
        if not m:
            # The contents is one unbroken run; the first line that is
            # neither a contents entry nor blank ends it.
            if out and ln.strip() and not NOISE.match(ln):
                break
            continue
        indent, name, _page = m.group(1), m.group(2), m.group(3)
        if len(indent) < 2:
            section = name
        elif section:
            out.setdefault(name, section)
    return out


def read_skill_table(lines, names):
    """
    The cross-reference lists each quest once per skill it pays, with the
    skill name set vertically in the middle of its block rather than on
    every row. There is no reliable way to tell where one block ends and
    the next begins, so the skill is NOT read here: guessing it would put
    "Harvesting Daily pays Attack" on the page, which is worse than
    saying nothing.

    What the table does say plainly is which quests pay a fixed amount
    and which vary with your level, so that is all it is used for.
    """
    varies = set()
    longest = sorted(names, key=len, reverse=True)
    for ln in lines:
        if not ln.strip():
            continue
        hit = next((n for n in longest if n in ln), None)
        if not hit:
            continue
        after = ln[ln.index(hit) + len(hit):].strip()
        if after.split()[:1] == ["Variable"]:
            varies.add(hit)
    return varies


def read_god(name, body, contents):
    """
    A god page: who the high priest is, what worshipping gives you, what
    the blessing costs, and which gods it rules out.
    """
    blocks, current = OrderedDict(), "intro"
    for ln in body:
        m = GOD_BLOCK_RE.match(ln)
        if m:
            current = m.group(1).strip().lower()
            blocks.setdefault(current, [])
            continue
        blocks.setdefault(current, []).append(ln)

    # The high priest's name and place sit on the two lines after the
    # heading, before any block of its own.
    head = tidy(blocks.get("intro", [])) + tidy(blocks.get("high priest", []))
    if head and all(NOT_IN_GAME.match(h) for h in head):
        return {"name": name, "section": "God Quests", "kind": "god",
                "npc": None, "where": None, "at": None, "status": "not in game",
                "intro": [], "reward": [], "items": [], "steps": [],
                "notes": [], "requirements": [], "varies": False}
    npc = where = None
    coords = None
    for ln in head:
        place = NPC_PLACE.match(ln.strip())
        if place:
            npc_part = place.group(1).strip()
            npc = npc_part or npc
            where = place.group(2).strip()
            coords = [int(place.group(3)), int(place.group(4))]
            rest = place.group(5).strip().lstrip(",").strip()
            if rest:
                where = f"{where}, {rest}"
            break
    if npc is None and head:
        npc = head[0].strip()

    bullets = lambda k: [b.strip().lstrip("\u2022").strip()
                         for b in tidy(blocks.get(k, [])) if b.strip()]
    return {
        "name": name,
        "section": "God Quests",
        "kind": "god",
        "npc": npc, "where": where, "at": coords,
        "intro": paragraphs(tidy(blocks.get("quests", []))),
        "reward": [{"amount": None, "what": b} for b in bullets("benefits")],
        "items": [],
        "steps": [],
        "notes": ([("Blessing: " + p) for p in
                   paragraphs(tidy(blocks.get("blessing", [])))]
                  + [("Starting rank: " + p) for p in
                     paragraphs(tidy(blocks.get("starting rank", [])))]),
        "requirements": bullets("enemies"),
        "varies": False,
    }


def split_blocks(body):
    """The quest body into its named blocks, keeping the opening text."""
    blocks, current = OrderedDict(), "intro"
    for ln in body:
        m = BLOCK_RE.match(ln)
        if m:
            key = m.group(1).strip().lower()
            current = CANON_BLOCK.get(key, key)
            blocks.setdefault(current, [])
            continue
        blocks.setdefault(current, []).append(ln)
    return blocks


def tidy(lines):
    """Trim blank runs off both ends."""
    out = list(lines)
    while out and not out[0].strip():
        out.pop(0)
    while out and not out[-1].strip():
        out.pop()
    return out


def parse_steps(lines):
    """
    Numbered steps, each possibly with lettered sub-steps, with wrapped
    lines folded back into whatever they were wrapped from.
    """
    steps, cur, sub = [], None, None
    for ln in lines:
        m = STEP.match(ln)
        if m:
            cur = {"n": int(m.group(1)), "text": m.group(2).strip(), "sub": []}
            steps.append(cur)
            sub = None
            continue
        s = SUBSTEP.match(ln)
        if s and cur is not None:
            sub = {"n": s.group(1), "text": s.group(2).strip()}
            cur["sub"].append(sub)
            continue
        text = ln.strip()
        if not text:
            continue
        if sub is not None:
            sub["text"] += " " + text
        elif cur is not None:
            cur["text"] += " " + text
        else:                       # prose before the first numbered step
            steps.append({"n": None, "text": text, "sub": []})
    return steps


# "4,200 Attack              2,200 Defense" - the guide sets long reward
# lists in two columns, and a run of spaces is the only thing dividing them.
TWO_COLUMN = re.compile(r"\s{4,}")


def parse_rewards(lines):
    out = []
    for ln in tidy(lines):
        if not ln.strip():
            continue
        parts = [p.strip() for p in TWO_COLUMN.split(ln.strip()) if p.strip()]
        # Only treat it as two columns when both halves look like rewards;
        # otherwise it is a sentence that happens to be padded.
        if len(parts) < 2 or not all(REWARD_LINE.match(p) for p in parts):
            parts = [ln.strip()]
        for text in parts:
            m = REWARD_LINE.match(text)
            if m:
                out.append({"amount": m.group(1), "what": m.group(2)})
            else:
                out.append({"amount": None, "what": text})
    return out


def parse_items(lines):
    out = []
    for ln in tidy(lines):
        text = ln.strip()
        if text:
            out.append(text)
    return out


def paragraphs(lines):
    """Wrapped lines folded into paragraphs."""
    out, cur = [], []
    for ln in lines:
        if ln.strip():
            cur.append(ln.strip())
        elif cur:
            out.append(" ".join(cur))
            cur = []
    if cur:
        out.append(" ".join(cur))
    return out


def parse(text):
    raw = text.replace("\r", "").split("\n")
    lines = clean(raw)
    contents = read_contents(lines)
    if not contents:
        sys.exit("No table of contents found - is this the quest guide?")
    names = list(contents)

    # The write-ups start at the first section heading standing on its own
    # line. Everything before that is contents and cross-reference tables.
    sections_in_order = list(OrderedDict.fromkeys(contents.values()))
    heads = {}
    for i, ln in enumerate(lines):
        t = ln.strip()
        if t in sections_in_order and t not in heads and i > len(names):
            heads[t] = i
    if not heads:
        sys.exit("Found the contents but none of its sections in the body.")
    body_start = min(heads.values())
    varies = read_skill_table(lines[:body_start], names)

    # Inside the body a section heading switches section and a quest name
    # starts a quest. God pages are headed differently and handled apart.
    head_at = {i: sec for sec, i in heads.items()}
    exact = set(names)
    marks, section_of = [], {}
    current = None
    for i in range(body_start, len(lines)):
        if i in head_at:
            current = head_at[i]
            continue
        t = lines[i].strip()
        if t in exact:
            marks.append((i, t))
            section_of[i] = current
        elif current == "God Quests":
            g = GOD_HEAD.match(lines[i])
            if g:
                name = f"{g.group(1).strip()} ({g.group(2).strip()})"
                marks.append((i, name))
                section_of[i] = current
    quests = OrderedDict()
    for k, (i, name) in enumerate(marks):
        end = marks[k + 1][0] if k + 1 < len(marks) else len(lines)
        if name in quests:                 # a repeat heading, keep the first
            continue
        body = lines[i + 1:end]
        if section_of.get(i) == "God Quests":
            quests[name] = read_god(name, body, contents)
            continue
        npc = where = None
        coords = None
        needs_first = []
        # The guide puts "Prerequisite Quest: ..." above the start NPC on
        # the quests that have one, so both are looked for.
        while body:
            pre = PREREQ.match(body[0])
            if not pre:
                break
            needs_first.append(pre.group(1).strip())
            body = body[1:]
        if body and START_NPC.match(body[0]):
            raw_npc = START_NPC.match(body[0]).group(1)
            body = body[1:]
            place = NPC_PLACE.match(raw_npc)
            if place:
                npc, where = place.group(1).strip(), place.group(2).strip()
                coords = [int(place.group(3)), int(place.group(4))]
                rest = place.group(5).strip().lstrip(",").strip()
                if rest:
                    where = f"{where}, {rest}"
            else:
                npc = raw_npc.strip()
        blocks = split_blocks(body)
        q = {
            "name": name,
            "section": section_of.get(i) or contents.get(name),
            "npc": npc, "where": where, "at": coords,
            "intro": paragraphs(tidy(blocks.get("intro", []))),
            "reward": parse_rewards(blocks.get("reward", [])),
            "items": parse_items(blocks.get("items needed", [])),
            "steps": parse_steps(tidy(blocks.get("steps", []))),
            "notes": paragraphs(tidy(blocks.get("notes", []))),
            "noteLines": tidy(blocks.get("notes", [])),
            "requirements": needs_first
                            + paragraphs(tidy(blocks.get("requirements", []))),
            "varies": name in varies,
        }
        quests[name] = q
    return quests, contents


def main():
    ap = argparse.ArgumentParser(description="Parse the quest guide")
    ap.add_argument("source", help="text pulled out of the quest PDF")
    ap.add_argument("--out", default="quests.json")
    a = ap.parse_args()

    with open(a.source, encoding="utf-8", errors="replace") as f:
        quests, contents = parse(f.read())

    missing = [n for n in contents if n not in quests]
    thin = [n for n, q in quests.items()
            if not q["steps"] and not q["intro"] and not q["notes"]]

    sections = OrderedDict()
    for q in quests.values():
        sections.setdefault(q["section"], []).append(q["name"])

    with open(a.out, "w", encoding="utf-8") as f:
        json.dump({"_comment": "Built by el_quests.py from the community "
                               "quest guide. Edit the guide, not this file.",
                   "sections": list(sections),
                   "quests": list(quests.values())}, f,
                  indent=1, ensure_ascii=False)

    print(f"{len(quests)} quests in {len(sections)} sections -> {a.out}")
    for sec, names in sections.items():
        print(f"  {len(names):>3}  {sec}")
    withnpc = sum(1 for q in quests.values() if q["npc"])
    withstep = sum(1 for q in quests.values() if q["steps"])
    withpay = sum(1 for q in quests.values() if q["reward"])
    varies = sum(1 for q in quests.values() if q.get("varies"))
    print(f"  {withnpc} have a start NPC, {withstep} have steps, "
          f"{withpay} list a reward, {varies} pay by your level")
    if missing:
        print(f"  {len(missing)} in the contents with no write-up: "
              + ", ".join(missing[:5]) + (" ..." if len(missing) > 5 else ""))
    if thin:
        print(f"  {len(thin)} with nothing but a heading: "
              + ", ".join(thin[:5]) + (" ..." if len(thin) > 5 else ""))


if __name__ == "__main__":
    main()
