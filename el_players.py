#!/usr/bin/env python3
"""
el_players.py - player stats from the official Eternal Lands site.

top.el-db.com says who is in the top 100 for each skill but only gives a
rank, and ties share one. The official player page gives real levels. So
this takes the names from the first and the numbers from the second.

    python el_players.py seed              # build the list of players to follow
    python el_players.py scrape            # read every player's page
    python el_players.py top attack        # leaderboard for one skill
    python el_players.py movers            # who levelled recently
    python el_players.py pk                # PK table, with weekly movement
    python el_players.py player stann      # one player

Add your guild to guild.txt, one name per line, and they get followed too.
"""

import argparse
import re
import sqlite3
import sys
import time
from datetime import datetime, timezone, timedelta

try:
    import requests
    from bs4 import BeautifulSoup
except ImportError:
    sys.exit("Run: pip install requests beautifulsoup4 lxml")

TOP_URL = "https://top.el-db.com/365-200.html"
USER_URL = "http://game.eternal-lands.com/view_user.php?user="
DB_PATH = "el_bots.db"
GUILD_FILE = "guild.txt"
UA = "EL-HQ/0.1 (Eternal Lands community project; contact: stann in-game)"
PAUSE = 1.0
TIMEOUT = 25

SCHEMA = """
CREATE TABLE IF NOT EXISTS player (
    name        TEXT PRIMARY KEY,
    overall     INTEGER,
    pk_score    REAL,
    pk_fights   INTEGER,
    pk_won      INTEGER,
    pk_lost     INTEGER,
    achievements TEXT,
    source      TEXT,          -- how we came to follow them
    private     INTEGER,        -- they have hidden their stats
    missing     INTEGER,        -- no such character any more
    private_note TEXT,          -- what their page says instead
    checked     TEXT,           -- when privacy was last re-checked
    first_seen  TEXT,
    last_seen   TEXT,
    last_read   TEXT           -- null until their page has been read
);

-- Current levels. One row per player per skill or attribute.
CREATE TABLE IF NOT EXISTS player_stat (
    name  TEXT NOT NULL,
    kind  TEXT NOT NULL,       -- skill | attribute | cross
    stat  TEXT NOT NULL,
    level INTEGER,
    PRIMARY KEY (name, stat)
);

-- A row only when a level actually changes, so this stays small.
CREATE TABLE IF NOT EXISTS level_change (
    id    INTEGER PRIMARY KEY,
    name  TEXT NOT NULL,
    stat  TEXT NOT NULL,
    was   INTEGER,
    now   INTEGER NOT NULL,
    at    TEXT NOT NULL
);

-- PK figures move constantly, so these get a dated snapshot.
CREATE TABLE IF NOT EXISTS pk_snapshot (
    name   TEXT NOT NULL,
    day    TEXT NOT NULL,
    score  REAL, fights INTEGER, won INTEGER, lost INTEGER,
    PRIMARY KEY (name, day)
);

CREATE INDEX IF NOT EXISTS idx_stat_skill ON player_stat(stat, level);
CREATE INDEX IF NOT EXISTS idx_change_at  ON level_change(at);
"""

SKILLS = ["Overall", "Attack", "Defense", "Magic", "Harvest", "Manufacture",
          "Alchemy", "Potion", "Summoning", "Crafting", "Engineering",
          "Tailoring", "Ranging"]


LATER_COLUMNS = {"player": {"private": "INTEGER", "private_note": "TEXT",
                            "checked": "TEXT", "missing": "INTEGER"}}

PRIVACY_MARK = "privacy mode enabled"


def page_state(text):
    """privacy | gone | stats, from the flattened page text."""
    low = text.lower()
    if PRIVACY_MARK in low:
        return "privacy"
    if len(text.strip()) < 80 and "player stats" in low:
        return "gone"
    return "stats"


def connect(path):
    con = sqlite3.connect(path)
    con.row_factory = sqlite3.Row
    con.executescript(SCHEMA)
    for table, cols in LATER_COLUMNS.items():
        have = {r["name"] for r in con.execute(f"PRAGMA table_info({table})")}
        if not have:
            continue
        for col, kind in cols.items():
            if col not in have:
                con.execute(f"ALTER TABLE {table} ADD COLUMN {col} {kind}")
    con.commit()
    return con


def session():
    s = requests.Session()
    s.headers.update({"User-Agent": UA})
    return s


def today():
    return datetime.now(timezone.utc).date().isoformat()


def now_iso():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def fold_duplicates(con):
    """
    The same character can arrive twice under different capitals - once
    from the rankings as "pinkroses" and once from guild.txt as
    "PinkRoses" - and then counts twice everywhere on the site. The row
    that has actually been read wins; if both have, the newest does.
    """
    groups = con.execute("""SELECT LOWER(name) k, COUNT(*) n FROM player
                            GROUP BY LOWER(name) HAVING n > 1""").fetchall()
    merged = 0
    for key, _ in groups:
        rows = con.execute("""SELECT name, last_read, private, overall
                              FROM player WHERE LOWER(name) = ?""",
                           (key,)).fetchall()
        rows.sort(key=lambda r: (r["last_read"] is not None,
                                 r["overall"] is not None,
                                 r["last_read"] or "", r["name"]),
                  reverse=True)
        keep, drop = rows[0]["name"], [r["name"] for r in rows[1:]]
        for name in drop:
            # Stats follow the name, so move any the keeper lacks.
            con.execute("""INSERT OR IGNORE INTO player_stat
                           (name, kind, stat, level)
                           SELECT ?, kind, stat, level FROM player_stat
                           WHERE name = ?""", (keep, name))
            con.execute("DELETE FROM player_stat WHERE name = ?", (name,))
            con.execute("DELETE FROM player WHERE name = ?", (name,))
            merged += 1
    if merged:
        con.commit()
        print(f"  folded {merged} duplicate name{'s' if merged > 1 else ''} "
              f"that differed only by capitals")
    return merged


# ------------------------------------------------------------- guilds

# "[www] Warlords" opens a roster; the names follow, one per line.
GUILD_HEAD = re.compile(r"^\s*\[\s*(?P<tag>[^\]]{1,12})\s*\]\s*(?P<name>.*)$")
# A guild picks the colour its tag is drawn in, and the game shows it
# in that colour above a player's head. "[wWw] Warlords #c9a227" sets
# one; without it the tag takes the page's own colour.
GUILD_COLOUR = re.compile(r"\s+(#[0-9a-fA-F]{3,8})\s*$")


def read_guilds(path):
    """
    {tag: {name, members}} out of guild.txt. A file in the older shape,
    a bare list of names with no bracket line, is read as one unnamed
    guild so nothing is lost by upgrading.
    """
    try:
        with open(path, encoding="utf-8") as f:
            lines = f.read().splitlines()
    except FileNotFoundError:
        return {}

    out, tag = {}, None
    loose = []
    for line in lines:
        text = line.strip()
        if not text or text.startswith("#"):
            continue
        head = GUILD_HEAD.match(text)
        if head:
            tag = head.group("tag").strip()
            name = head.group("name").strip()
            colour = None
            hit = GUILD_COLOUR.search(name)
            if hit:
                colour = hit.group(1)
                name = name[:hit.start()].strip()
            out.setdefault(tag, {"name": name or tag, "members": [],
                                 "colour": colour})
            continue
        # A roster usually arrives pasted out of the game, so it can be
        # one name a line, or several separated by commas or spaces. A
        # character name has no spaces in it, so splitting is safe.
        names = [n.strip(" ,;\t") for n in re.split(r"[,\s;]+", text)]
        (out[tag]["members"] if tag else loose).extend(n for n in names if n)
    if loose:
        out.setdefault("?", {"name": "Guild", "members": []})
        out["?"]["members"] += loose
    for g in out.values():                     # a name listed twice is one
        g["members"] = list(dict.fromkeys(g["members"]))
    return out


# ------------------------------------------------------------ seeding

def do_seed(args):
    """Collect names from the top-players page and from guild.txt."""
    con = connect(args.db)
    s = session()
    ts = now_iso()
    names = {}

    print(f"reading {TOP_URL} ...")
    try:
        r = s.get(TOP_URL, timeout=TIMEOUT)
        r.raise_for_status()
        for m in re.finditer(r"view_user\.php\?user=([^\"'&<>\s]+)", r.text):
            n = requests.utils.unquote(m.group(1)).strip()
            if n:
                names.setdefault(n, "top200")
    except Exception as e:
        print(f"  could not read it: {e}")

    print(f"  {len(names)} names from the rankings")

    rosters = read_guilds(GUILD_FILE)
    if rosters:
        for tag, g in rosters.items():
            for n in g["members"]:
                names[n] = "guild"
            print(f"  {len(g['members'])} in {g['name']} [{tag}]")
    else:
        print(f"  no {GUILD_FILE} (make one to follow a guild)")

    # Match an existing row's spelling rather than making a second one.
    known = {r[0].lower(): r[0] for r in con.execute("SELECT name FROM player")}
    names = {known.get(n.lower(), n): src for n, src in names.items()}

    added = 0
    for n, src in names.items():
        cur = con.execute("""INSERT INTO player (name, source, first_seen,
                             last_seen) VALUES (?,?,?,?)
                             ON CONFLICT(name) DO UPDATE SET
                             last_seen=excluded.last_seen""",
                          (n, src, ts, ts))
        added += 1 if cur.rowcount and cur.lastrowid else 0
    con.commit()
    fold_duplicates(con)
    total = con.execute("SELECT COUNT(*) FROM player").fetchone()[0]
    print(f"\n{total} players on the list")


# ------------------------------------------------------------ parsing

# EL's stats are a fixed set, so match them by name. Flattened page text
# has no reliable delimiters, and a loose pattern happily reads the
# section heading as part of the label ("Skills Overall: 163/163").
ATTRIBUTES = ["Physique", "Coordination", "Reasoning", "Will", "Instinct",
              "Vitality"]
CROSS = ["Might", "Matter", "Toughness", "Charm", "Reaction", "Rationality",
         "Dexterity", "Ethereality", "Perception"]
SKILL_NAMES = ["Overall", "Attack", "Defense", "Defence", "Magic", "Harvest",
               "Harvesting", "Manufacture", "Manufacturing", "Alchemy",
               "Potion", "Summoning", "Crafting", "Engineering", "Tailoring",
               "Ranging"]
STAT_KIND = {**{n: "attribute" for n in ATTRIBUTES},
             **{n: "cross" for n in CROSS},
             **{n: "skill" for n in SKILL_NAMES}}
STAT_RE = re.compile(r"\b(" + "|".join(sorted(STAT_KIND, key=len, reverse=True))
                     + r")\s*:\s*(\d+)\s*/\s*(\d+)")
ANY_STAT_RE = re.compile(r"([A-Za-z][A-Za-z '\-]{1,22}?)\s*:\s*\d+\s*/\s*\d+")


# The page separates one achievement from the next with two non-breaking
# spaces. Flattening the page to text turns those into ordinary spaces
# and the names run together, so they are taken off the raw html first.
ACH_SPLIT = re.compile(r"(?:&nbsp;|\u00a0|\s){2,}")


def read_achievements(html):
    """["Herbalist (III)", "Miner (III)", ...] off the raw page."""
    i = html.find("Achievements")
    if i < 0:
        return []
    tail = re.sub(r"<[^>]+>", "", html[i + len("Achievements"):])
    out = []
    for part in ACH_SPLIT.split(tail):
        name = part.strip(" :\u00a0")
        # A real achievement is a short phrase, optionally with a tier.
        if name and len(name) <= 48 and re.match(r"^[A-Za-z][\w' ()-]*$", name):
            out.append(name)
    return out


def parse_player(html):
    """
    Pull every known stat, the PK figures and the achievements off a
    player page. Returns None if the page is not a player page at all.

    The second number of each pair is the base level; the first drops
    when the player is hurt or drunk.
    """
    text = re.sub(r"\s+", " ",
                  BeautifulSoup(html, "lxml").get_text(" ", strip=True))
    if "Skills" not in text and "Main Attributes" not in text:
        return None

    out = {"stats": {}, "pk": {}, "achievements": None, "overall": None,
           "unknown": []}

    for m in STAT_RE.finditer(text):
        stat = m.group(1)
        out["stats"][stat] = {"kind": STAT_KIND[stat], "level": int(m.group(3))}
        if stat == "Overall":
            out["overall"] = int(m.group(3))

    # Anything shaped like a stat that we do not recognise - a new skill,
    # say - so it shows up rather than being silently dropped.
    for m in ANY_STAT_RE.finditer(text):
        label = m.group(1).strip().split()[-1]
        if label not in STAT_KIND:
            out["unknown"].append(label)

    for m in re.finditer(r"PK\s+(Score|Fights|Won|Lost)\s*:\s*([\d.]+)",
                         text, re.I):
        out["pk"][m.group(1).lower()] = float(m.group(2))

    got = read_achievements(html)
    if got:
        # Stored with a separator the names cannot contain, so they can
        # be taken apart again without guessing where one ends.
        out["achievements"] = " | ".join(got)[:900]

    return out if out["stats"] else None


def do_debug(args):
    """Show what one player's page actually looks like to the parser."""
    s = session()
    url = USER_URL + requests.utils.quote(args.name)
    print(f"fetching {url}\n")
    r = s.get(url, timeout=TIMEOUT)
    print(f"  status {r.status_code}, {len(r.text)} bytes, "
          f"type {r.headers.get('content-type')}\n")
    text = re.sub(r"\s+", " ",
                  BeautifulSoup(r.text, "lxml").get_text(" ", strip=True))
    print("--- page as text (first 1200 chars) ---")
    print(text[:1200])
    print("--- end ---\n")
    p = parse_player(r.text)
    if not p:
        print("PARSER FOUND NOTHING. Paste the block above into the chat.")
        print("\n--- raw html (first 900 chars) ---")
        print(r.text[:900])
        return
    print(f"parsed {len(p['stats'])} stats, overall {p['overall']}, "
          f"pk {p['pk']}")
    for k, v in list(p["stats"].items())[:8]:
        print(f"   {k:<16}{v['level']:>5}  {v['kind']}")


def store_player(con, name, p, ts, day):
    changes = 0
    for stat, v in p["stats"].items():
        row = con.execute("""SELECT level FROM player_stat
                             WHERE name=? AND stat=?""", (name, stat)).fetchone()
        was = row["level"] if row else None
        if was != v["level"]:
            if was is not None:
                con.execute("""INSERT INTO level_change (name, stat, was, now, at)
                               VALUES (?,?,?,?,?)""", (name, stat, was,
                                                       v["level"], ts))
                changes += 1
            con.execute("""INSERT INTO player_stat (name, kind, stat, level)
                           VALUES (?,?,?,?)
                           ON CONFLICT(name, stat) DO UPDATE SET
                           level=excluded.level, kind=excluded.kind""",
                        (name, v["kind"], stat, v["level"]))

    pk = p["pk"]
    con.execute("""UPDATE player SET overall=?, pk_score=?, pk_fights=?,
                   pk_won=?, pk_lost=?, achievements=?, last_read=?,
                   last_seen=? WHERE name=?""",
                (p["overall"], pk.get("score"), pk.get("fights"),
                 pk.get("won"), pk.get("lost"), p["achievements"], ts, ts,
                 name))
    if pk:
        con.execute("""INSERT INTO pk_snapshot (name, day, score, fights,
                       won, lost) VALUES (?,?,?,?,?,?)
                       ON CONFLICT(name, day) DO UPDATE SET
                       score=excluded.score, fights=excluded.fights,
                       won=excluded.won, lost=excluded.lost""",
                    (name, day, pk.get("score"), pk.get("fights"),
                     pk.get("won"), pk.get("lost")))
    return changes


def do_scrape(args):
    con = connect(args.db)
    where = ("" if args.include_private else
             "WHERE IFNULL(private,0) = 0 AND IFNULL(missing,0) = 0")
    names = [r["name"] for r in con.execute(
        f"SELECT name FROM player {where} ORDER BY name COLLATE NOCASE")]
    skip = con.execute("""SELECT
            SUM(CASE WHEN private=1 THEN 1 ELSE 0 END) p,
            SUM(CASE WHEN missing=1 THEN 1 ELSE 0 END) m
            FROM player""").fetchone()
    if not args.include_private and (skip["p"] or skip["m"]):
        print(f"skipping {skip['p'] or 0} with privacy mode on and "
              f"{skip['m'] or 0} that no longer exist "
              f"(--include-private to re-check)")
    if not names:
        sys.exit("No players yet. Run: python el_players.py seed")
    if args.limit:
        names = names[:args.limit]

    s = session()
    ts, day = now_iso(), today()
    ok = failed = private = gone = changes = 0
    unknown_seen = set()
    duds = []

    print(f"reading {len(names)} player pages, a second apart "
          f"(about {len(names) // 60 + 1} minutes)...")
    for i, name in enumerate(names, 1):
        try:
            r = s.get(USER_URL + requests.utils.quote(name), timeout=TIMEOUT)
            r.raise_for_status()
            flat = re.sub(r"\s+", " ", BeautifulSoup(
                r.text, "lxml").get_text(" ", strip=True))
            state = page_state(flat)
            p = parse_player(r.text) if state == "stats" else None

            if state == "privacy":
                # Their choice. Record it, keep the achievements the page
                # still shows, and stop asking every day.
                ach = None
                i = flat.lower().find("achievements")
                if i >= 0:
                    ach = flat[i + len("achievements"):].strip(" :")[:600]
                con.execute("""UPDATE player SET private=1, missing=0,
                               private_note=?, achievements=COALESCE(?,
                               achievements), checked=?, last_seen=?
                               WHERE name=?""",
                            ("Privacy mode enabled", ach, ts, ts, name))
                private += 1
            elif state == "gone" or not p:
                con.execute("""UPDATE player SET missing=1, checked=?
                               WHERE name=?""", (ts, name))
                gone += 1
                if len(duds) < 3:
                    duds.append((name, r.status_code, len(r.text), flat[:120]))
            else:
                con.execute("""UPDATE player SET private=0, missing=0,
                               checked=? WHERE name=?""", (ts, name))
                changes += store_player(con, name, p, ts, day)
                ok += 1
                for u in p.get("unknown", []):
                    if u not in unknown_seen:
                        unknown_seen.add(u)
                        print(f"  unrecognised stat on {name}: {u!r}")
        except Exception as e:
            failed += 1
            if failed <= 5:
                print(f"  {name}: {e}")
        if i % 50 == 0:
            con.commit()
            print(f"  {i}/{len(names)}")
        time.sleep(args.delay)
    con.commit()

    print(f"\nread {ok}, {private} have privacy mode on, "
          f"{gone} no longer exist, {failed} failed, "
          f"{changes} levels changed")
    if duds:
        print("\nnot recognised, worth a look:")
        for name, code, size, snippet in duds[:3]:
            print(f"  {name} (HTTP {code}, {size}b): {snippet or '(empty)'}")
    if changes:
        for r in con.execute("""SELECT name, stat, was, now FROM level_change
                                WHERE at=? ORDER BY name LIMIT 25""", (ts,)):
            print(f"  {r['name']:<20} {r['stat']:<14} "
                  f"{r['was']} -> {r['now']}")


# ------------------------------------------------------------ reports

def do_top(args):
    con = connect(args.db)
    stat = args.skill.strip().title()
    rows = con.execute("""SELECT p.name, s.level, p.overall
                          FROM player_stat s JOIN player p ON p.name=s.name
                          WHERE LOWER(s.stat)=LOWER(?)
                          ORDER BY s.level DESC, p.name COLLATE NOCASE
                          LIMIT ?""", (stat, args.limit)).fetchall()
    if not rows:
        known = [r["stat"] for r in con.execute(
            "SELECT DISTINCT stat FROM player_stat ORDER BY stat")]
        sys.exit(f"No data for '{args.skill}'. Known: {', '.join(known)}")
    print(f"{'#':>4}  {'PLAYER':<22}{stat.upper():>8}{'OVERALL':>9}")
    rank, last, shown = 0, None, 0
    for r in rows:
        shown += 1
        if r["level"] != last:
            rank, last = shown, r["level"]
        print(f"{rank:>4}  {r['name']:<22}{r['level']:>8}"
              f"{(r['overall'] or '-'):>9}")


def do_movers(args):
    con = connect(args.db)
    since = (datetime.now(timezone.utc)
             - timedelta(days=args.days)).isoformat(timespec="seconds")
    rows = con.execute("""SELECT name, stat, was, now, at FROM level_change
                          WHERE at >= ? ORDER BY at DESC, name""",
                       (since,)).fetchall()
    if not rows:
        sys.exit(f"No levels gained in the last {args.days} days "
                 f"(or not enough snapshots yet).")
    print(f"levels gained in the last {args.days} days\n")
    for r in rows[:args.limit]:
        gained = r["now"] - (r["was"] or 0)
        plus = f"+{gained}" if gained > 1 else ""
        print(f"  {r['at'][:10]}  {r['name']:<20} {r['stat']:<14}"
              f"{r['now']:>5}  {plus}")
    print(f"\n{len(rows)} level-ups")


def do_pk(args):
    con = connect(args.db)
    since = (datetime.now(timezone.utc)
             - timedelta(days=args.days)).date().isoformat()
    rows = con.execute("""
        SELECT p.name, p.pk_score, p.pk_fights, p.pk_won, p.pk_lost,
               (SELECT fights FROM pk_snapshot x
                 WHERE x.name=p.name AND x.day<=? ORDER BY x.day DESC
                 LIMIT 1) AS then_fights,
               (SELECT won FROM pk_snapshot x
                 WHERE x.name=p.name AND x.day<=? ORDER BY x.day DESC
                 LIMIT 1) AS then_won
        FROM player p
        WHERE IFNULL(p.pk_fights,0) > 0
        ORDER BY p.pk_score DESC LIMIT ?""",
        (since, since, args.limit)).fetchall()
    if not rows:
        sys.exit("No PK data yet. Run a scrape first.")
    print(f"{'PLAYER':<22}{'SCORE':>10}{'FIGHTS':>8}{'WON':>6}{'LOST':>6}"
          f"{'RATE':>7}{'RECENT':>9}")
    for r in rows:
        rate = (r["pk_won"] / r["pk_fights"] * 100) if r["pk_fights"] else 0
        recent = ""
        if r["then_fights"] is not None:
            d = (r["pk_fights"] or 0) - r["then_fights"]
            if d:
                recent = f"+{d}"
        print(f"{r['name']:<22}{r['pk_score']:>10.2f}{r['pk_fights']:>8}"
              f"{r['pk_won']:>6}{r['pk_lost']:>6}{rate:>6.0f}%{recent:>9}")


def do_player(args):
    con = connect(args.db)
    p = con.execute("SELECT * FROM player WHERE LOWER(name)=LOWER(?)",
                    (args.name,)).fetchone()
    if not p:
        sys.exit(f"Not following '{args.name}'. Add them to {GUILD_FILE} "
                 f"and run seed.")
    print(f"\n{p['name']}" + (f"   overall {p['overall']}"
                              if p["overall"] else ""))
    if p["private"]:
        sys.exit("  this player has their stats hidden")
    if p["last_read"] is None:
        sys.exit("  not read yet - run: python el_players.py scrape")
    for kind, label in (("skill", "Skills"), ("attribute", "Attributes"),
                        ("cross", "Cross attributes")):
        rows = con.execute("""SELECT stat, level FROM player_stat
                              WHERE name=? AND kind=?
                              ORDER BY level DESC""", (p["name"], kind))
        rows = list(rows)
        if not rows:
            continue
        print(f"\n  {label}")
        for r in rows:
            print(f"    {r['stat']:<16}{r['level']:>5}")
    if p["pk_fights"]:
        print(f"\n  PK   score {p['pk_score']:.2f}, {p['pk_fights']} fights, "
              f"{p['pk_won']} won, {p['pk_lost']} lost")
    hist = list(con.execute("""SELECT stat, was, now, at FROM level_change
                               WHERE name=? ORDER BY at DESC LIMIT 10""",
                            (p["name"],)))
    if hist:
        print("\n  Recent levels")
        for h in hist:
            print(f"    {h['at'][:10]}  {h['stat']:<14}{h['was']} -> {h['now']}")
    if p["achievements"]:
        print(f"\n  Achievements\n    {p['achievements']}")


def main():
    ap = argparse.ArgumentParser(description="EL player stats")
    ap.add_argument("--db", default=DB_PATH)
    sub = ap.add_subparsers(dest="cmd", required=True)

    s1 = sub.add_parser("seed", help="build the list of players to follow")
    s1.set_defaults(func=do_seed)

    s2 = sub.add_parser("scrape", help="read every followed player's page")
    s2.add_argument("--limit", type=int, default=0)
    s2.add_argument("--delay", type=float, default=PAUSE)
    s2.add_argument("--include-private", action="store_true",
                    help="also re-check players who have hidden their stats")
    s2.set_defaults(func=do_scrape)

    s3 = sub.add_parser("top", help="leaderboard for one skill")
    s3.add_argument("skill")
    s3.add_argument("--limit", type=int, default=25)
    s3.set_defaults(func=do_top)

    s4 = sub.add_parser("movers", help="who levelled recently")
    s4.add_argument("--days", type=int, default=7)
    s4.add_argument("--limit", type=int, default=40)
    s4.set_defaults(func=do_movers)

    s5 = sub.add_parser("pk", help="PK table")
    s5.add_argument("--days", type=int, default=7)
    s5.add_argument("--limit", type=int, default=25)
    s5.set_defaults(func=do_pk)

    s7 = sub.add_parser("debug", help="show one page as the parser sees it")
    s7.add_argument("name")
    s7.set_defaults(func=do_debug)

    s6 = sub.add_parser("player", help="one player")
    s6.add_argument("name")
    s6.set_defaults(func=do_player)

    a = ap.parse_args()
    a.func(a)


if __name__ == "__main__":
    main()
