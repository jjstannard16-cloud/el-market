#!/usr/bin/env python3
"""
el_bots.py - Eternal Lands bot market scraper + reporting.

Scrapes https://bots.el-services.net/ (all hosted trade bots), stores current
listings and price history in SQLite, and reports cheapest sellers, best
buyers and arbitrage spreads.

Install:
    pip install requests beautifulsoup4 lxml

Usage:
    python el_bots.py scrape                  # one pass over all bots
    python el_bots.py report cheapest         # cheapest seller for every item
    python el_bots.py report spread           # buy price > sell price (free money)
    python el_bots.py report item "Silver Ore"
    python el_bots.py report history "Silver Ore"
    python el_bots.py report bots             # bots seen, with listing counts

Schedule it (hourly is plenty, and polite):
    0 * * * * cd /path/to/dir && /usr/bin/python3 el_bots.py scrape >> scrape.log 2>&1
"""

import argparse
import re
import sqlite3
import sys
import time
from datetime import datetime, timezone
from urllib.parse import urljoin

try:
    import requests
    from bs4 import BeautifulSoup
except ImportError:
    sys.exit("Missing deps. Run: pip install requests beautifulsoup4 lxml")

BASE_URL = "https://bots.el-services.net/"
DB_PATH = "el_bots.db"

# Be identifiable and polite. Put your own contact / character name here.
USER_AGENT = "EL-Market-Tracker/0.1 (Eternal Lands community project; contact: stann in-game)"
DELAY_SECONDS = 1.0          # pause between bot pages
REQUEST_TIMEOUT = 20

# Pages on the index that aren't bots
NOT_BOTS = {"index", "search", "main", "stats"}

SCHEMA = """
CREATE TABLE IF NOT EXISTS run (
    id          INTEGER PRIMARY KEY,
    started_at  TEXT NOT NULL,
    finished_at TEXT,
    bots_seen   INTEGER DEFAULT 0,
    rows_seen   INTEGER DEFAULT 0,
    errors      INTEGER DEFAULT 0
);

-- The bot index header carries the in-game clock and today's special
-- day, which is the single most useful thing in the game to know and
-- nothing outside the client shows it. One row per in-game day seen.
CREATE TABLE IF NOT EXISTS game_day (
    id         INTEGER PRIMARY KEY,
    day        INTEGER,        -- day of the in-game month
    month      TEXT,
    year       INTEGER,
    special    TEXT,           -- "Ordinary Day", "Day of Magic", ...
    first_seen TEXT NOT NULL,
    last_seen  TEXT NOT NULL,
    UNIQUE (day, month, year, special)
);

CREATE TABLE IF NOT EXISTS bot (
    name       TEXT PRIMARY KEY,
    location   TEXT,
    map_x      INTEGER,
    map_y      INTEGER,
    owner      TEXT,
    note       TEXT,
    online     INTEGER,
    slots      INTEGER,   -- free inventory slots the bot reports
    emu        INTEGER,   -- free carrying capacity the bot reports
    first_seen TEXT,
    last_seen  TEXT
);

CREATE TABLE IF NOT EXISTS item (
    item_id   INTEGER PRIMARY KEY,
    name      TEXT NOT NULL,
    image     TEXT,
    last_seen TEXT
);

-- Current state. One row per (bot, item, side). Upserted every run.
CREATE TABLE IF NOT EXISTS listing (
    bot       TEXT NOT NULL,
    item_id   INTEGER NOT NULL,
    side      TEXT NOT NULL CHECK (side IN ('sell','buy')),
    quantity  INTEGER,
    price     REAL,
    last_seen TEXT NOT NULL,
    PRIMARY KEY (bot, item_id, side)
);

-- Price history. A new row ONLY when the price changes, so this stays small
-- even scraping hourly for years. Quantity churns constantly and is not
-- history-tracked; it lives in `listing` as current state.
CREATE TABLE IF NOT EXISTS price_history (
    id         INTEGER PRIMARY KEY,
    bot        TEXT NOT NULL,
    item_id    INTEGER NOT NULL,
    side       TEXT NOT NULL,
    price      REAL NOT NULL,
    first_seen TEXT NOT NULL,
    last_seen  TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_listing_item ON listing(item_id, side);
CREATE INDEX IF NOT EXISTS idx_hist_item    ON price_history(item_id, side, first_seen);
CREATE INDEX IF NOT EXISTS idx_hist_latest  ON price_history(bot, item_id, side, id);
"""


def now_iso():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def connect(path=DB_PATH):
    con = sqlite3.connect(path)
    con.row_factory = sqlite3.Row
    con.executescript(SCHEMA)
    # Older databases predate the capacity columns; add them in place so an
    # existing el_bots.db keeps its history instead of needing a rebuild.
    have = {r["name"] for r in con.execute("PRAGMA table_info(bot)")}
    for col in ("slots", "emu"):
        if col not in have:
            con.execute(f"ALTER TABLE bot ADD COLUMN {col} INTEGER")
    con.commit()
    return con


def session():
    s = requests.Session()
    s.headers.update({"User-Agent": USER_AGENT})
    return s


# ---------------------------------------------------------------- parsing

def parse_number(text):
    """'9,650.00' -> 9650.0 ; '250' -> 250.0 ; junk -> None"""
    if text is None:
        return None
    cleaned = re.sub(r"[^\d.]", "", text.replace(",", ""))
    if not cleaned or cleaned == ".":
        return None
    try:
        return float(cleaned)
    except ValueError:
        return None


MONTHS_RE = r"([A-Za-z]+)"


def parse_game_header(html):
    """
    The index header reads like:
        Game Time 4:55
        6th day in the month of Akbar, the year 0051
        Ordinary Day
    Returns {day, month, year, special, clock} with whatever it could find.
    """
    text = re.sub(r"\s+", " ",
                  BeautifulSoup(html, "lxml").get_text(" ", strip=True))
    out = {"day": None, "month": None, "year": None, "special": None,
           "clock": None}

    m = re.search(r"(\d{1,2})(?:st|nd|rd|th)?\s+day\s+in\s+the\s+month\s+"
                  r"of\s+" + MONTHS_RE + r"\s*,?\s*(?:the\s+)?year\s+"
                  r"(\d+)", text, re.I)
    if m:
        out["day"] = int(m.group(1))
        out["month"] = m.group(2)
        out["year"] = int(m.group(3))

    m = re.search(r"Game Time\s+(\d{1,2}:\d{2})", text, re.I)
    if m:
        out["clock"] = m.group(1)

    # The day name sits just after the date. Take the words between the
    # year and whatever follows, rather than guessing from a fixed list,
    # so a day we have never seen is still captured.
    m = re.search(r"year\s+\d+\s*,?\s*([A-Z][A-Za-z'\- ]{2,40}?)\s*"
                  r"(?:Please select|Item Name|Search|$)", text)
    if m:
        cand = m.group(1).strip(" .,")
        if 2 < len(cand) < 42:
            out["special"] = cand
    return out


def store_game_day(con, info, ts):
    if not info or not info.get("special"):
        return None
    con.execute("""
        INSERT INTO game_day (day, month, year, special, first_seen, last_seen)
        VALUES (?,?,?,?,?,?)
        ON CONFLICT(day, month, year, special) DO UPDATE SET
            last_seen = excluded.last_seen
    """, (info["day"], info["month"], info["year"], info["special"], ts, ts))
    con.commit()
    return info["special"]


def find_bot_links(html):
    """Return [(bot_name, url, online_bool)] from the index page."""
    soup = BeautifulSoup(html, "lxml")
    found = {}
    for a in soup.find_all("a", href=True):
        href = a["href"].strip()
        m = re.fullmatch(r"\.?/?([A-Za-z0-9_\-]+)\.php", href)
        if not m:
            continue
        name = m.group(1)
        if name.lower() in NOT_BOTS:
            continue
        # The index puts a coloured dot image immediately before each link.
        online = True
        prev_img = a.find_previous("img")
        if prev_img and prev_img.get("src"):
            online = "green" in prev_img["src"].lower()
        found[name] = (name, urljoin(BASE_URL, href), online)
    return list(found.values())


def parse_bot_page(name, html):
    """
    Return dict with meta + listings.
    Listings: [{side, item_id, item_name, image, quantity, price}]
    Parsed defensively - the page is old-school PHP table markup, so we walk
    rows in document order and switch side when we hit a section header.
    """
    soup = BeautifulSoup(html, "lxml")
    text = soup.get_text("\n", strip=True)

    meta = {"name": name, "location": None, "map_x": None, "map_y": None,
            "owner": None, "note": None, "slots": None, "emu": None}

    # Footer reads like "10 Slots & 9626 EMU Available". Capacity, not cash:
    # the bot pages never show how much gold a bot is holding.
    cap = re.search(r"([\d,]+)\s*Slots?\s*&\s*([\d,]+)\s*EMU", text, re.I)
    if cap:
        meta["slots"] = int(cap.group(1).replace(",", ""))
        meta["emu"] = int(cap.group(2).replace(",", ""))

    m = re.search(r"([A-Za-z][A-Za-z '\-]+?)\s*\[\s*(\d+)\s*,\s*(\d+)\s*\]", text)
    if m:
        meta["location"] = m.group(1).strip()
        meta["map_x"] = int(m.group(2))
        meta["map_y"] = int(m.group(3))

    m = re.search(r"My Owner is\s+(\S+)", text)
    if m:
        meta["owner"] = m.group(1).strip()

    listings = []
    side = None

    for tr in soup.find_all("tr"):
        row_text = tr.get_text(" ", strip=True)
        low = row_text.lower()

        # Section headers
        if "i'm selling" in low or "im selling" in low or low.startswith("selling"):
            side = "sell"
            continue
        if "i'm buying" in low or "im buying" in low or low.startswith("buying"):
            side = "buy"
            continue
        if side is None:
            continue

        cells = tr.find_all(["td", "th"])
        if len(cells) < 3:
            continue

        img = None
        texts = []
        for c in cells:
            im = c.find("img")
            if im and im.get("src") and img is None:
                img = im["src"].split("/")[-1]
            t = c.get_text(" ", strip=True)
            if t:
                texts.append(t)

        # Expect: item_id, name, quantity, price  (image cell contributes no text)
        if len(texts) < 4:
            continue
        if not re.fullmatch(r"\d+", texts[0]):
            continue   # header row ("Item id") or a stray row

        item_id = int(texts[0])
        item_name = texts[1]
        price = parse_number(texts[-1])

        # Quantity is usually a number, but a bot with unlimited demand shows
        # "NO LIMIT". Store that as -1 so it reads as "available, uncapped"
        # rather than disappearing as a null.
        qty_text = texts[-2]
        if re.search(r"no\s*limit|unlimited", qty_text, re.I):
            quantity = -1.0
        else:
            quantity = parse_number(qty_text)

        if price is None or not item_name:
            continue

        listings.append({
            "side": side,
            "item_id": item_id,
            "item_name": item_name,
            "image": img,
            "quantity": int(quantity) if quantity is not None else None,
            "price": price,
        })

    return meta, listings


# ---------------------------------------------------------------- storage

def store(con, meta, listings, online, ts):
    cur = con.cursor()

    cur.execute("""
        INSERT INTO bot (name, location, map_x, map_y, owner, note, online,
                         slots, emu, first_seen, last_seen)
        VALUES (?,?,?,?,?,?,?,?,?,?,?)
        ON CONFLICT(name) DO UPDATE SET
            location=excluded.location, map_x=excluded.map_x,
            map_y=excluded.map_y, owner=excluded.owner,
            online=excluded.online, slots=excluded.slots, emu=excluded.emu,
            last_seen=excluded.last_seen
    """, (meta["name"], meta["location"], meta["map_x"], meta["map_y"],
          meta["owner"], meta["note"], int(online), meta["slots"],
          meta["emu"], ts, ts))

    for l in listings:
        cur.execute("""
            INSERT INTO item (item_id, name, image, last_seen) VALUES (?,?,?,?)
            ON CONFLICT(item_id) DO UPDATE SET
                name=excluded.name,
                image=COALESCE(excluded.image, item.image),
                last_seen=excluded.last_seen
        """, (l["item_id"], l["item_name"], l["image"], ts))

        cur.execute("""
            INSERT INTO listing (bot, item_id, side, quantity, price, last_seen)
            VALUES (?,?,?,?,?,?)
            ON CONFLICT(bot, item_id, side) DO UPDATE SET
                quantity=excluded.quantity, price=excluded.price,
                last_seen=excluded.last_seen
        """, (meta["name"], l["item_id"], l["side"], l["quantity"],
              l["price"], ts))

        # Price history: extend the open row if unchanged, else start a new one.
        row = cur.execute("""
            SELECT id, price FROM price_history
            WHERE bot=? AND item_id=? AND side=?
            ORDER BY id DESC LIMIT 1
        """, (meta["name"], l["item_id"], l["side"])).fetchone()

        if row and abs(row["price"] - l["price"]) < 1e-9:
            cur.execute("UPDATE price_history SET last_seen=? WHERE id=?",
                        (ts, row["id"]))
        else:
            cur.execute("""
                INSERT INTO price_history (bot, item_id, side, price,
                                           first_seen, last_seen)
                VALUES (?,?,?,?,?,?)
            """, (meta["name"], l["item_id"], l["side"], l["price"], ts, ts))

    con.commit()


# ---------------------------------------------------------------- scrape

def scrape(args):
    con = connect(args.db)
    s = session()
    ts = now_iso()

    cur = con.cursor()
    cur.execute("INSERT INTO run (started_at) VALUES (?)", (ts,))
    run_id = cur.lastrowid
    con.commit()

    print(f"[{ts}] fetching index...")
    try:
        r = s.get(BASE_URL, timeout=REQUEST_TIMEOUT)
        r.raise_for_status()
    except Exception as e:
        sys.exit(f"Could not fetch index: {e}")

    day = store_game_day(con, parse_game_header(r.text), ts)
    if day:
        info = parse_game_header(r.text)
        print(f"  in game: {info['day']} {info['month']} {info['year']}"
              f"{', ' + info['clock'] if info['clock'] else ''} \u2014 {day}")
    else:
        print("  could not read the in-game date from the index header")

    bots = find_bot_links(r.text)
    if args.limit:
        bots = bots[: args.limit]
    print(f"found {len(bots)} bots")

    rows_total = 0
    errors = 0

    for i, (name, url, online) in enumerate(bots, 1):
        try:
            resp = s.get(url, timeout=REQUEST_TIMEOUT)
            resp.raise_for_status()
            meta, listings = parse_bot_page(name, resp.text)
            store(con, meta, listings, online, ts)
            rows_total += len(listings)
            loc = meta["location"] or "?"
            print(f"  [{i:3}/{len(bots)}] {name:<20} {loc:<18} "
                  f"{len(listings):3} listings")
        except Exception as e:
            errors += 1
            print(f"  [{i:3}/{len(bots)}] {name:<20} ERROR: {e}")
        time.sleep(args.delay)

    con.execute("""UPDATE run SET finished_at=?, bots_seen=?, rows_seen=?,
                   errors=? WHERE id=?""",
                (now_iso(), len(bots), rows_total, errors, run_id))
    con.commit()
    print(f"\ndone: {len(bots)} bots, {rows_total} listings, {errors} errors")


# ---------------------------------------------------------------- reports

def fmt_gc(v):
    return f"{v:,.2f}".rstrip("0").rstrip(".")


def fmt_qty(q):
    if q is None:
        return "-"
    return "no limit" if q < 0 else f"{q:,}"


def report(args):
    con = connect(args.db)
    what = args.what

    if what == "bots":
        rows = con.execute("""
            SELECT b.name, b.location, b.owner, b.online, b.slots, b.emu,
                   (SELECT COUNT(*) FROM listing l
                     WHERE l.bot=b.name AND l.side='sell') AS sells,
                   (SELECT COUNT(*) FROM listing l
                     WHERE l.bot=b.name AND l.side='buy')  AS buys,
                   b.last_seen
            FROM bot b ORDER BY b.name
        """).fetchall()
        print(f"{'BOT':<22}{'LOCATION':<18}{'OWNER':<16}"
              f"{'SELL':>5}{'BUY':>5}{'SLOTS':>7}{'EMU':>9}")
        for r in rows:
            print(f"{r['name']:<22}{(r['location'] or '?'):<18}"
                  f"{(r['owner'] or '?'):<16}{r['sells']:>5}{r['buys']:>5}"
                  f"{(r['slots'] if r['slots'] is not None else '-'):>7}"
                  f"{(f'{r["emu"]:,}' if r['emu'] is not None else '-'):>9}")
        print(f"\n{len(rows)} bots in database")

    elif what == "cheapest":
        rows = con.execute("""
            SELECT i.name AS item, l.price, l.bot, l.quantity, b.location
            FROM listing l
            JOIN item i ON i.item_id = l.item_id
            LEFT JOIN bot b ON b.name = l.bot
            WHERE l.side='sell' AND IFNULL(l.quantity,0) <> 0
              AND l.price = (SELECT MIN(price) FROM listing l2
                             WHERE l2.item_id=l.item_id AND l2.side='sell'
                               AND IFNULL(l2.quantity,0) <> 0)
            GROUP BY l.item_id
            ORDER BY i.name
        """).fetchall()
        print(f"{'ITEM':<34}{'PRICE':>12}  {'BOT':<20}{'QTY':>7}  LOCATION")
        for r in rows:
            print(f"{r['item'][:33]:<34}{fmt_gc(r['price']):>12}  "
                  f"{r['bot']:<20}{fmt_qty(r['quantity']):>9}  "
                  f"{r['location'] or ''}")
        print(f"\n{len(rows)} items currently for sale")

    elif what == "spread":
        # Someone buys higher than someone else sells -> instant profit.
        rows = con.execute("""
            SELECT i.name AS item,
                   MIN(s.price) AS buy_at,
                   MAX(bb.price) AS sell_at,
                   (SELECT bot FROM listing x WHERE x.item_id=i.item_id
                      AND x.side='sell' AND IFNULL(x.quantity,0)<>0
                    ORDER BY x.price ASC LIMIT 1)  AS from_bot,
                   (SELECT bot FROM listing y WHERE y.item_id=i.item_id
                      AND y.side='buy'  AND IFNULL(y.quantity,0)<>0
                    ORDER BY y.price DESC LIMIT 1) AS to_bot
            FROM item i
            JOIN listing s  ON s.item_id=i.item_id  AND s.side='sell'
                            AND IFNULL(s.quantity,0)<>0
            JOIN listing bb ON bb.item_id=i.item_id AND bb.side='buy'
                            AND IFNULL(bb.quantity,0)<>0
            GROUP BY i.item_id
            HAVING sell_at > buy_at
            ORDER BY (sell_at - buy_at) DESC
        """).fetchall()
        print(f"{'ITEM':<30}{'BUY AT':>11}{'SELL AT':>11}{'PROFIT':>11}  "
              f"{'FROM':<16}{'TO':<16}")
        for r in rows:
            profit = r["sell_at"] - r["buy_at"]
            print(f"{r['item'][:29]:<30}{fmt_gc(r['buy_at']):>11}"
                  f"{fmt_gc(r['sell_at']):>11}{fmt_gc(profit):>11}  "
                  f"{r['from_bot']:<16}{r['to_bot']:<16}")
        if not rows:
            print("(none right now - run a few scrapes and check again)")
        else:
            print(f"\n{len(rows)} profitable spreads")

    elif what == "item":
        if not args.query:
            sys.exit('Usage: report item "Silver Ore"')
        rows = con.execute("""
            SELECT i.name AS item, l.side, l.price, l.quantity, l.bot,
                   b.location, b.map_x, b.map_y
            FROM listing l
            JOIN item i ON i.item_id=l.item_id
            LEFT JOIN bot b ON b.name=l.bot
            WHERE i.name LIKE ?
            ORDER BY l.side DESC, l.price ASC
        """, (f"%{args.query}%",)).fetchall()
        if not rows:
            sys.exit(f"No item matching '{args.query}'")
        print(f"{'SIDE':<6}{'PRICE':>12}{'QTY':>8}  {'BOT':<20}LOCATION")
        for r in rows:
            loc = r["location"] or ""
            if r["map_x"] is not None:
                loc += f" [{r['map_x']},{r['map_y']}]"
            print(f"{r['side']:<6}{fmt_gc(r['price']):>12}"
                  f"{fmt_qty(r['quantity']):>10}  {r['bot']:<20}{loc}")

    elif what == "history":
        if not args.query:
            sys.exit('Usage: report history "Silver Ore"')
        rows = con.execute("""
            SELECT i.name AS item, h.side, h.price, h.bot,
                   h.first_seen, h.last_seen
            FROM price_history h
            JOIN item i ON i.item_id=h.item_id
            WHERE i.name LIKE ?
            ORDER BY h.first_seen DESC
            LIMIT 100
        """, (f"%{args.query}%",)).fetchall()
        if not rows:
            sys.exit(f"No history for '{args.query}' yet")
        print(f"{'FROM':<22}{'TO':<22}{'SIDE':<6}{'PRICE':>12}  BOT")
        for r in rows:
            print(f"{r['first_seen']:<22}{r['last_seen']:<22}{r['side']:<6}"
                  f"{fmt_gc(r['price']):>12}  {r['bot']}")

    else:
        sys.exit(f"Unknown report: {what}")


# ---------------------------------------------------------------- cli

def main():
    p = argparse.ArgumentParser(description="Eternal Lands bot market scraper")
    p.add_argument("--db", default=DB_PATH, help="SQLite file (default el_bots.db)")
    sub = p.add_subparsers(dest="cmd", required=True)

    sp = sub.add_parser("scrape", help="fetch all bots once")
    sp.add_argument("--delay", type=float, default=DELAY_SECONDS,
                    help="seconds between bot pages (default 1.0)")
    sp.add_argument("--limit", type=int, default=0,
                    help="only scrape the first N bots (for testing)")
    sp.set_defaults(func=scrape)

    rp = sub.add_parser("report", help="query the database")
    rp.add_argument("what", choices=["cheapest", "spread", "item",
                                     "history", "bots"])
    rp.add_argument("query", nargs="?", help="item name for item/history")
    rp.set_defaults(func=report)

    args = p.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
