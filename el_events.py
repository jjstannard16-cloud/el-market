#!/usr/bin/env python3
"""
el_events.py - the things that happen to everyone, from Mercator.

Four open feeds, no key needed:

    /api/pears          who found a Joker or a Pear
    /api/invances       invance broadcasts
    /api/lottery        daily lottery results
    /api/announcements  moderator and server broadcasts

All four carry the game's own broadcast text rather than structured
fields, so the player's name has to be read out of the sentence. Every
pattern used here is written down below; anything that does not match is
stored whole and counted, so a broadcast we cannot read shows up as a
number rather than vanishing.

    python el_events.py              # anything new
    python el_events.py --full       # walk the whole history
    python el_events.py --dump       # print what each feed returns
"""

import argparse
import json
import os
import re
import sqlite3
import sys
import time
from datetime import datetime, timezone

try:
    import requests
except ImportError:
    sys.exit("Run: pip install requests")

BASE = "https://mercator.holy-eternalland.de"
FEEDS = {
    "find":         "/api/pears",
    "invance":      "/api/invances",
    "lottery":      "/api/lottery",
    "announcement": "/api/announcements",
}
DB_PATH = "el_bots.db"
UA = "EL-HQ/0.1 (Eternal Lands community site; contact: stann in-game)"
TIMEOUT = 25
PAGE_SIZE = 100
PAUSE = 0.4
MAX_PAGES = 400

SCHEMA = """
CREATE TABLE IF NOT EXISTS event_log (
    kind      TEXT NOT NULL,     -- find | invance | lottery | announcement
    id        INTEGER NOT NULL,  -- Mercator's id within that feed
    what      TEXT,              -- pear, joker, ... once we can read it
    who       TEXT,              -- the player, where there is one
    amount    INTEGER,
    message   TEXT NOT NULL,     -- the broadcast, as sent
    game_day   INTEGER,
    game_month INTEGER,
    game_year  INTEGER,
    game_time  TEXT,
    at        TEXT,
    PRIMARY KEY (kind, id)
);
CREATE INDEX IF NOT EXISTS ev_at ON event_log (at);
CREATE INDEX IF NOT EXISTS ev_who ON event_log (kind, who);
CREATE INDEX IF NOT EXISTS ev_what ON event_log (kind, what);
"""

# "teeh found 1 Pear." / "Stann found 2 Jokers!"
FOUND = re.compile(
    r"^\s*(?P<who>.+?)\s+found\s+(?P<n>\d+)\s+(?P<what>[A-Za-z][A-Za-z ]*?)s?\s*[.!]*\s*$",
    re.I)
# "The lottery winner is Stann, who won 50000 gc"
WON = re.compile(
    r"(?:winner is|congratulations to|won by)\s+(?P<who>[\w\-\[\]' ]+?)\s*[,.!]",
    re.I)
# The Global Invasion Warning System speaks in a handful of sentences.
# "...they will invade Portland!" / "...spawning inside the Portland Cave!"
GIWS_OVER = re.compile(r"\bthe invasion is over\b", re.I)
GIWS_WARN = re.compile(r"\binvasion warning\b|\bis spawning\b", re.I)
INVADE = re.compile(r"\b(?:they will invade|invasion (?:in|at)|invading)\s+"
                    r"(?P<map>[A-Z][\w' ]{2,30}?)\s*[!.,]", re.I)
INSIDE = re.compile(r"\b(?:inside|in)\s+the\s+(?P<map>[A-Z][\w' ]{2,30}?)\s*[!.,]")

# The announcements feed carries more than invasions. Each of these was
# read off the real broadcasts rather than guessed:
#   JOKER: LadyReni found Joker and got a Potion of Wildness
#   GIWS: mashu has kindly donated 50000 gold coins for the project...
#   GIWS: A Rat was pulled out of an outhouse in Portland! ...
#   A treasure has been found in Desert Pines!
JOKER = re.compile(r"^JOKER:\s*(?P<who>.+?)\s+found\s+Joker"
                   r"(?:\s+and\s+got\s+(?:an?\s+)?(?P<prize>.+?))?\s*[.!]*\s*$",
                   re.I)
DONATED = re.compile(r"^GIWS:\s*(?P<who>.+?)\s+has kindly donated\s+"
                     r"(?P<n>[\d,]+)\s+gold", re.I)
PULLED = re.compile(r"^GIWS:\s*An?\s+(?P<mob>[\w' ]+?)\s+was pulled out of .*?\bin\s+"
                    r"(?P<map>[\w' ]+?)\s*[!.]", re.I)
TREASURE = re.compile(r"^A treasure has been found(?:\s+in\s+(?P<map>[\w' ]+?))?\s*[!.]*\s*$",
                      re.I)
# "radu: There is a new treasure..." - a named person broadcasting.
# Since October the game has prefixed them, so both shapes are read:
#   CherUT: The moon is turning red, MM invasion in ~5 minutes
#   #Message from CherUT: The moon is turning red, MM invasion in ~5 min
# The prefixed ones were being filed as an unattributed "message",
# which dropped the moderator's name and the invasion with it.
SPEAKER = re.compile(r"^(?:#Message from\s+)?(?P<who>[A-Za-z][\w\-]{1,19})"
                     r":\s+\S")

# The Global Invasion Warning System runs the scheduled invasions - the
# caves, the two dragons - and they come round like clockwork. The ones
# players turn up for are the ones a moderator runs by hand, announced
# in their own words with no template at all:
#
#   Wizzy: C2 invasion in 15mins, no caps!
#   Acelon: Invasion is coming. Safe maps are: VotD, Nordcarn, Bethel...
#   Thyralax: second wave is arriving in bethel now!
#   Wizzy: There are 47 invaded monsters left.
#
# The last of those is the only count anybody gets while an invasion is
# running, so it is pulled out with its number.
INVADERS_LEFT = re.compile(
    r"\bthere\s+(?:are|is)\s+(?P<n>[\d,]+)\s+invaded\s+monsters?\s+left",
    re.I)
# A moderator's working vocabulary. This was once a narrow pattern
# built around the word "invasion", on the assumption that "wave" on
# its own would catch a moderator talking about something else. Read
# against all 6,668 broadcasts it had filed as ordinary chatter, that
# assumption was wrong: every one of the 125 that said "wave" was an
# invasion, and so were the ones saying uncap, reload, mobs, bosses
# or spawned. A moderator broadcasts to the whole game, and when they
# use these words they are placing monsters.
#
# "cap" is the one exception, because a PK contest sets an a/d limit
# the same way an invasion does ("no alts, a/d < 40"), so it is only
# read with its number beside it.
MOD_INVASION = re.compile(
    # Typed in a hurry and often misspelt - "invsion", "invaision" -
    # so the word is matched loosely rather than exactly.
    r"\binv[a-z]{0,3}sion\b|\binvaded\b|\binvaders\b"
    r"|\bwaves?\b|\buncap|\breload|\bmobs?\b|\bmonsters?\b"
    r"|\bspawn|\bbosse?s?\b"
    r"|\bcap(?:ped|s)?\s*(?:at\s+)?\d|\d\s*(?:a\s*/\s*d\s*)?caps?\b"
    # The game's own idiom for one starting, used on its own as often
    # as not: "red moon whatsit irin shortly".
    r"|\bred moon\b|\bmoon is turning red\b", re.I)

# "Game Date: 14-07-0089 Game time: 0:08"
GAMETIME = re.compile(
    r"(?P<d>\d{1,2})-(?P<m>\d{1,2})-(?P<y>\d{2,4}).*?(?P<t>\d{1,2}:\d{2})",
    re.S)


def session():
    s = requests.Session()
    s.headers.update({"User-Agent": UA, "Accept": "application/json"})
    return s


def get_json(s, url, **params):
    r = s.get(url, params=params or None, timeout=TIMEOUT)
    r.raise_for_status()
    return r.json()


def pick(d, *names):
    low = {str(k).lower(): v for k, v in d.items()}
    for n in names:
        v = low.get(n.lower())
        if v not in (None, ""):
            return v
    return None


def parse_message(kind, text):
    """
    (what, who, amount) out of a broadcast, or (None, None, None) when
    the sentence is not one we know. Never guesses a name.
    """
    text = " ".join(str(text or "").split())
    if not text:
        return None, None, None
    m = FOUND.match(text)
    if m:
        return (m.group("what").strip().lower(),
                m.group("who").strip(), int(m.group("n")))
    if kind == "lottery":
        w = WON.search(text)
        if w:
            return "lottery", w.group("who").strip(), None
    if kind == "announcement":
        # Most of this feed is the invasion warning system, where there
        # is no player, so "who" carries the place instead. The joker and
        # donation broadcasts do name a player, and those use "who" for
        # the player as everywhere else.
        j = JOKER.match(text)
        if j:
            return "joker", j.group("who").strip(), 1
        d = DONATED.match(text)
        if d:
            return "donation", d.group("who").strip(), \
                   int(d.group("n").replace(",", ""))
        t = TREASURE.match(text)
        if t:
            return "treasure", (t.group("map") or "").strip() or None, None
        p = PULLED.match(text)
        if p:
            return "pulled", p.group("map").strip(), None
        if GIWS_OVER.search(text):
            return "invasion over", None, None
        if GIWS_WARN.search(text) or "invasion advanced warning" in text.lower():
            # A second-wave warning names two places: where the monsters
            # are and where they are heading. "A second wave is spawning
            # inside the Portland Cave ... in 6 minutes they will invade
            # Portland!" Where they are is the invasion; where they are
            # heading is a threat. Taking the threat made the cave and
            # the town look like two different invasions.
            m = INSIDE.search(text) or INVADE.search(text)
            return "invasion", (m.group("map").strip() if m else None), None
        sp = SPEAKER.match(text)
        if sp and not text.startswith("GIWS"):
            who = sp.group("who")
            left = INVADERS_LEFT.search(text)
            if left:
                return "invaders left", who, \
                       int(left.group("n").replace(",", ""))
            if MOD_INVASION.search(text):
                return "mod invasion", who, None
            return "message", who, None
    return None, None, None


def parse_record(kind, rec):
    msg = pick(rec, "modmessages", "message", "text", "announcement",
               "broadcast", "msg")
    if msg is None:
        # Keep something, so a feed whose field we have not seen before
        # is visible rather than silently empty.
        msg = json.dumps(rec, ensure_ascii=False)[:500]
    what, who, amount = parse_message(kind, msg)
    g = GAMETIME.search(str(pick(rec, "gametime", "gamedate", "game_time")
                             or ""))
    rid = pick(rec, "id")
    try:
        rid = int(rid)
    except (TypeError, ValueError):
        return None
    return {
        "kind": kind, "id": rid, "what": what, "who": who, "amount": amount,
        "message": " ".join(str(msg).split()),
        "game_day": int(g.group("d")) if g else None,
        "game_month": int(g.group("m")) if g else None,
        "game_year": int(g.group("y")) if g else None,
        "game_time": g.group("t") if g else None,
        "at": pick(rec, "time", "date", "at", "created_at", "spdaydate"),
    }


def ensure(con):
    con.executescript(SCHEMA)
    con.commit()


def store(con, rows):
    before = con.execute("SELECT COUNT(*) FROM event_log").fetchone()[0]
    con.executemany("""
        INSERT INTO event_log (kind, id, what, who, amount, message,
                               game_day, game_month, game_year, game_time, at)
        VALUES (:kind, :id, :what, :who, :amount, :message,
                :game_day, :game_month, :game_year, :game_time, :at)
        ON CONFLICT (kind, id) DO UPDATE SET
            what = excluded.what, who = excluded.who,
            amount = excluded.amount, message = excluded.message,
            game_day = excluded.game_day, game_month = excluded.game_month,
            game_year = excluded.game_year, game_time = excluded.game_time,
            at = excluded.at""", [r for r in rows if r])
    con.commit()
    return con.execute("SELECT COUNT(*) FROM event_log").fetchone()[0] - before


def fetch_page(s, kind, path, page, limit):
    """
    The paginated feed, or the bulk export when the feed is down.
    /api/invances and /api/lottery have both been answering 500, so the
    export is tried once before giving up on a feed.
    """
    try:
        return get_json(s, BASE + path, page=page, limit=limit), False
    except Exception as paged:
        if page > 1:
            raise
        name = path.rsplit("/", 1)[-1]
        try:
            body = get_json(s, f"{BASE}/analytics/export/{name}",
                            format="json", limit=100000)
            print(f"  {kind}: the paged feed is down ({paged}); "
                  f"used the bulk export instead")
            return body, True
        except Exception:
            raise paged


def walk(s, con, kind, path, full):
    known = {r[0] for r in con.execute(
        "SELECT id FROM event_log WHERE kind = ?", (kind,))}
    seen = added = 0
    for page in range(1, MAX_PAGES + 1):
        try:
            body, bulk = fetch_page(s, kind, path, page, PAGE_SIZE)
        except Exception as e:
            print(f"  {kind}: unavailable: {e}")
            return 0
        items = body.get("items") if isinstance(body, dict) else body
        if items is None and isinstance(body, dict):
            # An export may wrap its rows under another name.
            items = next((v for v in body.values() if isinstance(v, list)), None)
        if not items:
            break
        rows = [parse_record(kind, r) for r in items]
        rows = [r for r in rows if r]
        added += store(con, rows)
        seen += len(rows)
        if page == 1 and isinstance(body, dict) and body.get("total"):
            print(f"  {kind}: Mercator holds {body['total']}")
        ids = {r["id"] for r in rows}
        if bulk:
            break                      # the export returns everything at once
        if not full and known and ids <= known:
            break
        known |= ids
        time.sleep(PAUSE)
    unread = con.execute("""SELECT COUNT(*) FROM event_log
                            WHERE kind = ? AND who IS NULL""",
                         (kind,)).fetchone()[0]
    print(f"  {kind}: read {seen}, {added} new, {unread} whose wording "
          f"we cannot read")
    return added


def reparse(con):
    """
    Re-read the stored broadcasts with the current patterns. The text is
    already here, so this costs nothing and means a new pattern does not
    need a fresh download of 35,000 rows.
    """
    rows = con.execute("""SELECT kind, id, message, what, who, amount
                          FROM event_log""").fetchall()
    writes = []
    for kind, rid, msg, what, who, amount in rows:
        got = parse_message(kind, msg)
        if got != (what, who, amount):
            writes.append((*got, kind, rid))
    con.executemany("""UPDATE event_log SET what = ?, who = ?, amount = ?
                       WHERE kind = ? AND id = ?""", writes)
    con.commit()
    changed = len(writes)
    print(f"  re-read {len(rows)} broadcasts, {changed} changed")


def report(con):
    rows = con.execute("""SELECT what, COUNT(*) c FROM event_log
                          WHERE what IS NOT NULL
                          GROUP BY what ORDER BY c DESC""").fetchall()
    if rows:
        print("  kinds: " + ", ".join(f"{r[0]} {r[1]}" for r in rows))
    inv = con.execute("""SELECT who, COUNT(*) c FROM event_log
                         WHERE what = 'invasion' AND who IS NOT NULL
                         GROUP BY LOWER(who) ORDER BY c DESC LIMIT 6""")
    best = list(inv)
    if best:
        print("  invaded most: " + ", ".join(f"{r[0]} ({r[1]})" for r in best))
    top = con.execute("""SELECT who, SUM(IFNULL(amount,1)) n FROM event_log
                         WHERE what IN ('pear','joker') AND who IS NOT NULL
                         GROUP BY LOWER(who) ORDER BY n DESC LIMIT 5""")
    best = list(top)
    if best:
        print("  best finders: "
              + ", ".join(f"{r[0]} ({r[1]})" for r in best))


def main():
    ap = argparse.ArgumentParser(description="Pull the event feeds")
    ap.add_argument("--db", default=DB_PATH)
    ap.add_argument("--full", action="store_true")
    ap.add_argument("--dump", action="store_true",
                    help="print what each feed returns and stop")
    ap.add_argument("--reparse", action="store_true",
                    help="re-read stored broadcasts with the current patterns")
    a = ap.parse_args()

    s = session()
    if a.dump:
        for kind, path in FEEDS.items():
            print(f"--- {kind}: {BASE + path}")
            try:
                body = get_json(s, BASE + path, limit=3)
                print(json.dumps(body, indent=2)[:1800])
            except Exception as e:
                print(f"  failed: {e}")
            print()
        return

    if not os.path.exists(a.db):
        sys.exit(f"No database at {a.db}. Run el_bots.py first.")
    con = sqlite3.connect(a.db)
    ensure(con)
    ts = datetime.now(timezone.utc).isoformat(timespec="seconds")
    print(f"[{ts}] reading the event feeds...")
    for kind, path in FEEDS.items():
        walk(s, con, kind, path, a.full)
    if a.reparse:
        reparse(con)
    unread = con.execute("""SELECT COUNT(*) FROM event_log
                            WHERE what IS NULL""").fetchone()[0]
    total = con.execute("SELECT COUNT(*) FROM event_log").fetchone()[0]
    print(f"  {total - unread} of {total} broadcasts read, {unread} not")
    report(con)
    con.close()


if __name__ == "__main__":
    main()
