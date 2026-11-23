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

# <a href="...view_user.php?user=Stann">Stann</a>
NAME = re.compile(r"view_user\.php\?user=([^\"'&<>\s]+)")
HEADER = re.compile(r"There are\s+(\d+)\s+Players Online", re.I)

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
"""


def read_page(session):
    r = session.get(URL, timeout=TIMEOUT)
    r.raise_for_status()
    html = r.text
    # The page says how many it means; if our count differs, the page
    # changed shape and we would rather know than quietly undercount.
    said = HEADER.search(html)
    names = list(dict.fromkeys(
        requests.utils.unquote(m.group(1)).strip()
        for m in NAME.finditer(html)))
    names = [n for n in names if n]
    return names, (int(said.group(1)) if said else None)


def ensure(con):
    con.executescript(SCHEMA)
    con.commit()


def store(con, names, ts):
    when = datetime.fromisoformat(ts)
    con.execute("""INSERT OR REPLACE INTO online_count (at, n, hour, dow)
                   VALUES (?, ?, ?, ?)""",
                (ts, len(names), when.hour, when.weekday()))
    con.executemany("""
        INSERT INTO online_player (name, readings, first_seen, last_seen)
        VALUES (?, 1, ?, ?)
        ON CONFLICT (name) DO UPDATE SET
            readings = readings + 1,
            last_seen = excluded.last_seen""",
        [(n, ts, ts) for n in names])
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
    fresh = [n for n in names if n.lower() not in known]
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
    print(f"  {n} readings so far, {distinct} different players seen; "
          f"{lo} to {hi} online, {avg:.0f} on average")
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
        names, said = read_page(s)
    except Exception as e:
        print(f"  could not read who is online: {e}")
        return

    note = ""
    if said is not None and said != len(names):
        note = f" (the page says {said}, we read {len(names)})"
    print(f"[{ts}] {len(names)} players online{note}")

    if a.dry_run:
        print("  " + ", ".join(names[:12]) + (" ..." if len(names) > 12 else ""))
        return
    if not names:
        print("  nothing to store")
        return
    if not os.path.exists(a.db):
        sys.exit(f"No database at {a.db}. Run el_bots.py first.")

    con = sqlite3.connect(a.db)
    con.row_factory = sqlite3.Row
    ensure(con)
    store(con, names, ts)
    fresh = follow_new(con, names, ts)
    if fresh:
        print(f"  {fresh} player{'s' if fresh > 1 else ''} we had not seen "
              f"before, now followed")
    report(con)
    con.close()


if __name__ == "__main__":
    main()
