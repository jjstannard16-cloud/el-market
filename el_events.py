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


def walk(s, con, kind, path, full):
    known = {r[0] for r in con.execute(
        "SELECT id FROM event_log WHERE kind = ?", (kind,))}
    url = BASE + path
    seen = added = 0
    for page in range(1, MAX_PAGES + 1):
        try:
            body = get_json(s, url, page=page, limit=PAGE_SIZE)
        except Exception as e:
            print(f"  {kind}: page {page}: {e}")
            break
        items = body.get("items") if isinstance(body, dict) else body
        if not items:
            break
        rows = [parse_record(kind, r) for r in items]
        rows = [r for r in rows if r]
        added += store(con, rows)
        seen += len(rows)
        if page == 1 and isinstance(body, dict) and body.get("total"):
            print(f"  {kind}: Mercator holds {body['total']}")
        ids = {r["id"] for r in rows}
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


def report(con):
    rows = con.execute("""SELECT what, COUNT(*) c FROM event_log
                          WHERE kind = 'find' AND what IS NOT NULL
                          GROUP BY what ORDER BY c DESC""").fetchall()
    if rows:
        print("  finds: " + ", ".join(f"{r[0]} {r[1]}" for r in rows))
    top = con.execute("""SELECT who, SUM(IFNULL(amount,1)) n FROM event_log
                         WHERE kind = 'find' AND who IS NOT NULL
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
    report(con)
    con.close()


if __name__ == "__main__":
    main()
