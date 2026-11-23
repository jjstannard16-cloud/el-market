#!/usr/bin/env python3
"""
el_mercator.py - the in-game calendar, from the Mercator service.

The bot site's header carries a game date, but it has been showing the
same reading for days, so it cannot be used. Mercator (holy-eternalland.de)
publishes the live clock and, better, a complete log of every special day
going back years - including who summoned it, which the bot site has no
notion of.

Two sources, both open, neither needing a key:

    /_elday/clock-data      what day it is right now
    /api/specialdays        every special day on record, newest first

    python el_mercator.py                 # today, plus any new history
    python el_mercator.py --full          # walk the whole history
    python el_mercator.py --dump          # print what the endpoints return

Rows are keyed on Mercator's own id, so running this twice is harmless.
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
CLOCK_URL = f"{BASE}/_elday/clock-data"
DAYS_URL = f"{BASE}/api/specialdays"
DB_PATH = "el_bots.db"
UA = "EL-HQ/0.1 (Eternal Lands community site; contact: stann in-game)"
TIMEOUT = 25
PAGE_SIZE = 100
PAUSE = 0.4
MAX_PAGES = 400          # ~40,000 rows, well past the current total

SCHEMA = """
CREATE TABLE IF NOT EXISTS special_day_log (
    id          INTEGER PRIMARY KEY,   -- Mercator's own id
    name        TEXT NOT NULL,
    description TEXT,
    donated_by  TEXT,                  -- 'natural', or the player who paid
    game_day    INTEGER,
    game_month  INTEGER,
    game_year   INTEGER,
    game_time   TEXT,
    at          TEXT                   -- real-world ISO timestamp
);
CREATE INDEX IF NOT EXISTS sd_at ON special_day_log (at);
CREATE INDEX IF NOT EXISTS sd_name ON special_day_log (name);
CREATE INDEX IF NOT EXISTS sd_by ON special_day_log (donated_by);
"""

# game_day predates this script and was fed from the bot site. Rows now
# carry where they came from, so the site can prefer the live source.
GAME_DAY_COLUMNS = {"source": "TEXT"}


def session():
    s = requests.Session()
    s.headers.update({"User-Agent": UA, "Accept": "application/json"})
    return s


def get_json(s, url, **params):
    r = s.get(url, params=params or None, timeout=TIMEOUT)
    r.raise_for_status()
    return r.json()


# ---------------------------------------------------------------- parsing

def pick(d, *names):
    """Mercator's keys are CamelCase in one endpoint and lower in another."""
    lowered = {str(k).lower(): v for k, v in d.items()}
    for n in names:
        if n.lower() in lowered:
            v = lowered[n.lower()]
            if v not in (None, ""):
                return v
    return None


def number(v):
    """An int from 14, '14', or '0089'. None from anything else."""
    if isinstance(v, bool):
        return None
    if isinstance(v, int):
        return v
    m = re.search(r"\d+", str(v or ""))
    return int(m.group()) if m else None


def split_day(text):
    """
    'Leonard's day, when Leonard is considerably stronger ...'
    -> ("Leonard's day", "when Leonard is considerably stronger ...")

    The name is always the part before the first comma; everything after
    is prose. A day with no comma is all name.
    """
    text = (text or "").strip()
    if "," not in text:
        return text, None
    name, rest = text.split(",", 1)
    return name.strip(), rest.strip() or None


def split_gamedate(text):
    """
    '14-07-0089, game time 6:00' -> (14, 7, 89, '6:00')
    Anything that does not look like a date comes back empty.
    """
    text = str(text or "")
    m = re.search(r"\b(\d{1,2})-(\d{1,2})-(\d{2,4})\b", text)
    day = month = year = None
    if m:
        day, month, year = (int(g) for g in m.groups())
    t = re.search(r"(\d{1,2}:\d{2})", text)
    return day, month, year, (t.group(1) if t else None)


def parse_record(rec):
    """One row of /api/specialdays into our own shape."""
    name, desc = split_day(pick(rec, "specialday", "special_day", "name"))
    if not name:
        return None
    day, month, year, clock = split_gamedate(
        pick(rec, "gamedate", "game_date", "gameDate"))
    by = (pick(rec, "donatedby", "donated_by", "donatedBy") or "").strip()
    return {
        "id": number(pick(rec, "id")),
        "name": name,
        "description": desc,
        "donated_by": by or None,
        "game_day": day, "game_month": month, "game_year": year,
        "game_time": clock,
        "at": pick(rec, "spdaydate", "created_at", "at", "date"),
    }


# ----------------------------------------------------------------- store

def ensure(con):
    con.executescript(SCHEMA)
    have = {r[1] for r in con.execute("PRAGMA table_info(game_day)")}
    if have:                                   # table exists already
        for col, kind in GAME_DAY_COLUMNS.items():
            if col not in have:
                con.execute(f"ALTER TABLE game_day ADD COLUMN {col} {kind}")
    else:
        con.execute("""CREATE TABLE game_day (
            id INTEGER PRIMARY KEY, day INTEGER, month TEXT, year INTEGER,
            special TEXT, first_seen TEXT NOT NULL, last_seen TEXT NOT NULL,
            source TEXT, UNIQUE (day, month, year, special))""")
    con.commit()


def store_history(con, rows):
    """Returns how many were new."""
    before = con.execute("SELECT COUNT(*) FROM special_day_log").fetchone()[0]
    con.executemany("""
        INSERT INTO special_day_log
            (id, name, description, donated_by,
             game_day, game_month, game_year, game_time, at)
        VALUES (:id, :name, :description, :donated_by,
                :game_day, :game_month, :game_year, :game_time, :at)
        ON CONFLICT (id) DO UPDATE SET
            name = excluded.name,
            description = excluded.description,
            donated_by = excluded.donated_by,
            game_day = excluded.game_day,
            game_month = excluded.game_month,
            game_year = excluded.game_year,
            game_time = excluded.game_time,
            at = excluded.at""",
        [r for r in rows if r and r["id"] is not None])
    con.commit()
    after = con.execute("SELECT COUNT(*) FROM special_day_log").fetchone()[0]
    return after - before


def store_today(con, info, ts):
    """Keep game_day fed, so the rest of the site needs no changes."""
    if not info or not info.get("special"):
        return None
    con.execute("""
        INSERT INTO game_day (day, month, year, special,
                              first_seen, last_seen, source)
        VALUES (?, ?, ?, ?, ?, ?, 'mercator')
        ON CONFLICT (day, month, year, special)
          DO UPDATE SET last_seen = excluded.last_seen,
                        source = 'mercator'""",
        (info.get("day"), info.get("month"), info.get("year"),
         info["special"], ts, ts))
    con.commit()
    return info["special"]


# ------------------------------------------------------------------ work

def read_clock(s):
    """
    clock-data wraps everything in 'eldata' and splits the time into
    hour and minute. The month is a number, and no source we can check
    publishes the month names, so the date stays numeric rather than
    invented.
    """
    raw = get_json(s, CLOCK_URL)
    d = raw
    for wrapper in ("eldata", "data"):
        if isinstance(raw.get(wrapper), dict):
            d = raw[wrapper]
            break
    name, desc = split_day(pick(d, "GameDayName", "dayname", "specialday"))
    if not name:
        return None, raw
    hour = number(pick(d, "GameHour", "hour"))
    minute = number(pick(d, "GameMinute", "minute"))
    clock = (f"{hour}:{minute:02d}" if hour is not None and minute is not None
             else pick(d, "GameTime", "time", "clock"))
    month = number(pick(d, "GameMonth", "month"))
    return {
        "day": number(pick(d, "GameDay", "day")),
        "month": f"{month:02d}" if month else None,
        "year": number(pick(d, "GameYear", "year")),
        "special": name,
        "description": desc or pick(d, "GameDayDescription", "description"),
        "clock": clock,
        "warning": pick(d, "GIWS_Text"),
        "monsters": number(pick(d, "GIWS_Monsters")),
    }, raw


def walk_history(s, con, full):
    """Newest first, stopping at the first page we have seen all of."""
    known = {r[0] for r in con.execute("SELECT id FROM special_day_log")}
    seen_total = added = 0
    for page in range(1, MAX_PAGES + 1):
        try:
            body = get_json(s, DAYS_URL, page=page, limit=PAGE_SIZE)
        except Exception as e:
            print(f"  page {page}: {e}")
            break
        items = body.get("items") if isinstance(body, dict) else body
        if not items:
            break
        rows = [parse_record(r) for r in items]
        rows = [r for r in rows if r]
        added += store_history(con, rows)
        seen_total += len(rows)
        ids = {r["id"] for r in rows}
        if page == 1 and isinstance(body, dict) and body.get("total"):
            print(f"  Mercator holds {body['total']} special days")
        if not full and known and ids <= known:
            break                               # caught up with what we have
        known |= ids
        time.sleep(PAUSE)
    return seen_total, added


def report(con):
    n, = con.execute("SELECT COUNT(*) FROM special_day_log").fetchone()
    if not n:
        return
    span = con.execute("SELECT MIN(at), MAX(at) FROM special_day_log").fetchone()
    print(f"  {n} special days on record, {str(span[0])[:10]} to "
          f"{str(span[1])[:10]}")
    nat, = con.execute("""SELECT COUNT(*) FROM special_day_log
                          WHERE LOWER(IFNULL(donated_by,'')) = 'natural'
                       """).fetchone()
    print(f"  {nat} came round naturally, {n - nat} were summoned by players")
    top = con.execute("""SELECT donated_by, COUNT(*) c FROM special_day_log
                         WHERE LOWER(IFNULL(donated_by,'')) NOT IN ('natural','')
                         GROUP BY LOWER(donated_by)
                         ORDER BY c DESC LIMIT 5""").fetchall()
    if top:
        print("  most generous: "
              + ", ".join(f"{r[0]} ({r[1]})" for r in top))


def main():
    ap = argparse.ArgumentParser(description="Pull the in-game calendar")
    ap.add_argument("--db", default=DB_PATH)
    ap.add_argument("--full", action="store_true",
                    help="walk the whole history, not just what is new")
    ap.add_argument("--dump", action="store_true",
                    help="print what the endpoints return and stop")
    a = ap.parse_args()

    s = session()
    ts = datetime.now(timezone.utc).isoformat(timespec="seconds")

    if a.dump:
        for label, url, params in (("clock", CLOCK_URL, {}),
                                   ("days", DAYS_URL, {"limit": 2})):
            print(f"--- {label}: {url}")
            try:
                print(json.dumps(get_json(s, url, **params), indent=2)[:2500])
            except Exception as e:
                print(f"  failed: {e}")
        return

    if not os.path.exists(a.db):
        sys.exit(f"No database at {a.db}. Run el_bots.py first.")
    con = sqlite3.connect(a.db)
    ensure(con)

    print(f"[{ts}] reading the in-game clock...")
    try:
        today, _ = read_clock(s)
    except Exception as e:
        today = None
        print(f"  clock unavailable: {e}")
    if today:
        store_today(con, today, ts)
        when = (f"{today['day']}-{today['month']}-"
                f"{str(today['year'] or 0).zfill(4)}")
        print(f"  in game: {when}"
              f"{', ' + today['clock'] if today['clock'] else ''}"
              f" — {today['special']}")

    print("reading the special day log...")
    seen, added = walk_history(s, con, a.full)
    print(f"  read {seen}, {added} new")
    report(con)
    con.close()


if __name__ == "__main__":
    main()
