#!/usr/bin/env python3
"""
el_online.py - who is in the game, read once an hour.

The official page at game.eternal-lands.com/online_players.htm lists
everyone online and refreshes every thirty seconds. Reading it hourly
gives three things nothing else here can: how busy the game is through
the day, who is on most often, and a steady supply of players nobody
would have found from the top-200 rankings.

    python el_online.py              # one reading
    python el_online.py --dry-run    # read it, store nothing

A row per player per reading would be two million rows a year, so it is
not stored that way. Each reading stores one count, and each player a
running tally - which answers the same questions and stays small.
"""

import argparse
import os
import re
import sqlite3
import sys
from datetime import datetime, timezone

try:
    import requests
except ImportError:
    sys.exit("Run: pip install requests")

URL = "http://game.eternal-lands.com/online_players.htm"
DB_PATH = "el_bots.db"
UA = "EL-HQ/0.1 (Eternal Lands community site; contact: stann in-game)"
TIMEOUT = 25

# The page has two lists, one after the other, each under its own
# heading: "There are 230 Players Online:" then "There are 126 Bots
# Online:". Both are made of the same kind of link, so the headings are
# the only thing separating a player from a bot.
NAME = re.compile(r"view_user\.php\?user=([^\"'&<>\s]+)")
SECTION = re.compile(r"There are\s+(\d+)\s+(Players|Bots)\s+Online", re.I)
RECORD = re.compile(r"Most users ever online was\s+(\d+)\s+on\s+([^<\n]+)",
                    re.I)

SCHEMA = """
-- One row per reading: how many were on, and when.
CREATE TABLE IF NOT EXISTS online_count (
    at    TEXT PRIMARY KEY,
    n     INTEGER NOT NULL,
    hour  INTEGER,            -- UTC hour, for the busiest-hour question
    dow   INTEGER             -- 0 = Monday
);

-- One row per player, however many times we see them.
CREATE TABLE IF NOT EXISTS online_player (
    name       TEXT PRIMARY KEY,
    readings   INTEGER NOT NULL DEFAULT 0,
    first_seen TEXT NOT NULL,
    last_seen  TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS op_readings ON online_player (readings DESC);

-- The same page lists the bots. Kept apart, because a bot is not a
-- player and must never be followed as one.
CREATE TABLE IF NOT EXISTS online_bot (
    name       TEXT PRIMARY KEY,
    readings   INTEGER NOT NULL DEFAULT 0,
    first_seen TEXT NOT NULL,
    last_seen  TEXT NOT NULL
);
"""

LATER_COLUMNS = {"bots": "INTEGER"}


def read_page(session):
    """
    (players, bots, said, record). Each heading claims a number, and
    those are kept so a page that changes shape is noticed rather than
    quietly miscounted.
    """
    r = session.get(URL, timeout=TIMEOUT)
    r.raise_for_status()
    html = r.text

    marks = [(m.start(), m.group(2).lower(), int(m.group(1)))
             for m in SECTION.finditer(html)]
    found, said = {"players": [], "bots": []}, {}
    for i, (start, what, claimed) in enumerate(marks):
        end = marks[i + 1][0] if i + 1 < len(marks) else len(html)
        key = "players" if what.startswith("player") else "bots"
        said[key] = claimed
        found[key] = [n for n in dict.fromkeys(
            requests.utils.unquote(m.group(1)).strip()
            for m in NAME.finditer(html[start:end])) if n]

    rec = RECORD.search(html)
    record = {"n": int(rec.group(1)), "when": rec.group(2).strip()} if rec \
        else None
    return found["players"], found["bots"], said, record


def ensure(con):
    con.executescript(SCHEMA)
    have = {r[1] for r in con.execute("PRAGMA table_info(online_count)")}
    for col, kind in LATER_COLUMNS.items():
        if col not in have:
            con.execute(f"ALTER TABLE online_count ADD COLUMN {col} {kind}")
    con.commit()


def store(con, names, bots, ts):
    when = datetime.fromisoformat(ts)
    con.execute("""INSERT OR REPLACE INTO online_count
                   (at, n, bots, hour, dow) VALUES (?, ?, ?, ?, ?)""",
                (ts, len(names), len(bots), when.hour, when.weekday()))
    for table, rows in (("online_player", names), ("online_bot", bots)):
        con.executemany(f"""
            INSERT INTO {table} (name, readings, first_seen, last_seen)
            VALUES (?, 1, ?, ?)
            ON CONFLICT (name) DO UPDATE SET
                readings = readings + 1,
                last_seen = excluded.last_seen""",
            [(n, ts, ts) for n in rows])
    con.commit()


def follow_new(con, names, ts):
    """
    Anyone on this page is a real, active character, which is a better
    reason to follow someone than appearing in a ranking. Names are
    matched without case so nobody gains a second row.
    """
    if "player" not in {r[0] for r in con.execute(
            "SELECT name FROM sqlite_master WHERE type='table'")}:
        return 0
    known = {r[0].lower() for r in con.execute("SELECT name FROM player")}
    # A bot must never be followed as a player, including any that an
    # earlier version of this script already added.
    bots = {r[0].lower() for r in con.execute("SELECT name FROM online_bot")}
    wrong = [r[0] for r in con.execute(
        "SELECT name FROM player WHERE source = 'online'")
        if r[0].lower() in bots]
    if wrong:
        con.executemany("DELETE FROM player WHERE name = ?",
                        [(n,) for n in wrong])
        con.executemany("DELETE FROM player_stat WHERE name = ?",
                        [(n,) for n in wrong])
        print(f"  dropped {len(wrong)} bots that had been followed as players")
    fresh = [n for n in names if n.lower() not in known and
             n.lower() not in bots]
    con.executemany("""INSERT OR IGNORE INTO player
                       (name, source, first_seen, last_seen)
                       VALUES (?, 'online', ?, ?)""",
                    [(n, ts, ts) for n in fresh])
    con.commit()
    return len(fresh)


def report(con):
    n, = con.execute("SELECT COUNT(*) FROM online_count").fetchone()
    if n < 2:
        return
    distinct, = con.execute("SELECT COUNT(*) FROM online_player").fetchone()
    lo, hi, avg = con.execute(
        "SELECT MIN(n), MAX(n), AVG(n) FROM online_count").fetchone()
    nbots, = con.execute("SELECT COUNT(*) FROM online_bot").fetchone()
    print(f"  {n} readings so far, {distinct} different players and "
          f"{nbots} bots seen; {lo} to {hi} players online, "
          f"{avg:.0f} on average")
    top = con.execute("""SELECT name, readings FROM online_player
                         ORDER BY readings DESC, name LIMIT 5""").fetchall()
    if top and top[0][1] > 1:
        print("  on most often: "
              + ", ".join(f"{r[0]} ({r[1]})" for r in top))


def main():
    ap = argparse.ArgumentParser(description="Read who is online")
    ap.add_argument("--db", default=DB_PATH)
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()

    s = requests.Session()
    s.headers.update({"User-Agent": UA})
    ts = datetime.now(timezone.utc).isoformat(timespec="seconds")

    try:
        names, bots, said, record = read_page(s)
    except Exception as e:
        print(f"  could not read who is online: {e}")
        return

    for key, got in (("players", names), ("bots", bots)):
        claimed = said.get(key)
        if claimed is not None and claimed != len(got):
            print(f"  careful: the page claims {claimed} {key} and we read "
                  f"{len(got)}")
    print(f"[{ts}] {len(names)} players and {len(bots)} bots online"
          + (f"; the record is {record['n']} on {record['when']}"
             if record else ""))

    if a.dry_run:
        print("  players: " + ", ".join(names[:10])
              + (" ..." if len(names) > 10 else ""))
        print("  bots:    " + ", ".join(bots[:10])
              + (" ..." if len(bots) > 10 else ""))
        return
    if not names:
        print("  nothing to store")
        return
    if not os.path.exists(a.db):
        sys.exit(f"No database at {a.db}. Run el_bots.py first.")

    con = sqlite3.connect(a.db)
    con.row_factory = sqlite3.Row
    ensure(con)
    store(con, names, bots, ts)
    fresh = follow_new(con, names, ts)
    if fresh:
        print(f"  {fresh} player{'s' if fresh > 1 else ''} we had not seen "
              f"before, now followed")
    report(con)
    con.close()


if __name__ == "__main__":
    main()
