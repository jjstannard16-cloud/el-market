#!/usr/bin/env python3
"""
el_recipes.py - import crafting recipes from the EL wiki and price them
against live bot prices from el_bots.db.

The wiki holds 469 recipes in a ManuInfo template: ingredients and amounts,
skill, level, experience, tool, food. Combined with what bots currently
charge, that gives the two things no EL site shows: what a craft costs to
make right now, and what a level actually costs you.

    python el_recipes.py import         # fetch recipes from the wiki
    python el_recipes.py profit         # what's worth making at today's prices
    python el_recipes.py xp             # cheapest experience per skill
    python el_recipes.py recipe "steel long sword"

Recipes change rarely, so importing once a week is plenty.
"""

import argparse
import re
import sqlite3
import sys
import time
from datetime import datetime, timezone

try:
    import requests
except ImportError:
    sys.exit("Run: pip install requests")

API = "https://el-wiki.holy-eternalland.de/api.php"
DB_PATH = "el_bots.db"
UA = "EL-HQ/0.1 (Eternal Lands community project; contact: stann in-game)"
TEMPLATE = "Template:ManuInfo"
HARVEST_PAGE = "Harvestables"

# The wiki's skill field is hand-typed, so the same skill arrives under
# several spellings and a few pages put a category there instead.
SKILL_ALIASES = {
    "potions": "Potion", "potion": "Potion",
    "alchemy": "Alchemy", "crafting": "Crafting",
    "engineering": "Engineering", "manufacturing": "Manufacturing",
    "manufacture": "Manufacturing", "tailoring": "Tailoring",
    "summoning": "Summoning", "magic": "Magic", "ranging": "Ranging",
    "harvesting": "Harvesting",
    # Not skills at all - someone typed the item category in this field.
    "weapons": "Manufacturing", "weapon": "Manufacturing",
    "armour": "Manufacturing", "armor": "Manufacturing",
    "clothes": "Tailoring",
}
KNOWN_SKILLS = {"Potion", "Alchemy", "Crafting", "Engineering",
                "Manufacturing", "Tailoring", "Summoning", "Magic",
                "Ranging", "Harvesting"}


def canon_skill(raw):
    """Return (skill, was_corrected). Unknown values are kept as-is."""
    if not raw:
        return None, False
    key = raw.strip().lower()
    if key in SKILL_ALIASES:
        fixed = SKILL_ALIASES[key]
        return fixed, fixed.lower() != key
    return raw.strip(), False
BATCH = 40          # titles per API call
PAUSE = 0.4         # seconds between API calls

SCHEMA = """
CREATE TABLE IF NOT EXISTS recipe (
    item            TEXT PRIMARY KEY,
    skill           TEXT,
    level           INTEGER,
    exp             INTEGER,
    tool            TEXT,
    food            INTEGER,
    nexus           TEXT,
    nexus_level     INTEGER,
    knowledge       TEXT,
    product_emu     REAL,
    ingredients_emu REAL,
    stackable       TEXT,
    vendor_pays     REAL,
    imported        TEXT
);

CREATE TABLE IF NOT EXISTS recipe_ingredient (
    item       TEXT NOT NULL,
    ingredient TEXT NOT NULL,
    amount     REAL NOT NULL,
    position   INTEGER,
    PRIMARY KEY (item, ingredient)
);

CREATE TABLE IF NOT EXISTS harvestable (
    name     TEXT PRIMARY KEY,
    level    REAL,
    exp      REAL,
    kind     TEXT,
    tool          TEXT,   -- item you must hold to harvest it at all
    nexus_level   REAL,
    needs_item    TEXT,   -- material consumed by harvesting, if any
    action_points REAL,
    emu           REAL,
    food          REAL,
    notes         TEXT,
    imported TEXT
);

CREATE INDEX IF NOT EXISTS idx_ri_item ON recipe_ingredient(item);
CREATE INDEX IF NOT EXISTS idx_ri_ing  ON recipe_ingredient(ingredient);
"""


# Columns added after the first release. CREATE TABLE IF NOT EXISTS will
# not add them to a table that already exists, so bring old files forward.
LATER_COLUMNS = {
    "harvestable": {"tool": "TEXT", "emu": "REAL", "food": "REAL",
                    "notes": "TEXT", "nexus_level": "REAL",
                    "needs_item": "TEXT", "action_points": "REAL"},
    "recipe": {"knowledge": "TEXT", "vendor_pays": "REAL"},
}


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


def api(s, **params):
    params.setdefault("format", "json")
    params.setdefault("formatversion", 2)
    r = s.get(API, params=params, timeout=30)
    r.raise_for_status()
    return r.json()


# ------------------------------------------------------------ wikitext

def find_template(text, name):
    """Return the inside of {{name ...}}, brace-aware. None if absent."""
    m = re.search(r"\{\{\s*" + name + r"\s*(?=[|}])", text, re.I)
    if not m:
        return None
    i, depth = m.end(), 2
    while i < len(text):
        if text.startswith("{{", i):
            depth += 2; i += 2
        elif text.startswith("}}", i):
            depth -= 2; i += 2
            if depth == 0:
                return text[m.end():i - 2]
        else:
            i += 1
    return None


def split_params(body):
    """Split a template body on top-level pipes, respecting [[ ]] and {{ }}."""
    parts, buf, depth, link = [], [], 0, 0
    i = 0
    while i < len(body):
        two = body[i:i + 2]
        if two == "{{":
            depth += 1; buf.append(two); i += 2; continue
        if two == "}}":
            depth -= 1; buf.append(two); i += 2; continue
        if two == "[[":
            link += 1; buf.append(two); i += 2; continue
        if two == "]]":
            link -= 1; buf.append(two); i += 2; continue
        if body[i] == "|" and depth == 0 and link == 0:
            parts.append("".join(buf)); buf = []; i += 1; continue
        buf.append(body[i]); i += 1
    parts.append("".join(buf))
    return parts


def clean(v):
    """Strip wiki markup down to plain text."""
    v = re.sub(r"\[\[(?:[^\]|]*\|)?([^\]]*)\]\]", r"\1", v)   # [[a|b]] -> b
    v = re.sub(r"\{\{[^}]*\}\}", "", v)
    v = re.sub(r"<[^>]+>", "", v)
    v = v.replace("'''", "").replace("''", "")
    return v.strip()


def number(v):
    """First number in a string, or None. Must contain a digit: a lone
    full stop from prose like 'Food: none.' is not a number."""
    if not v:
        return None
    m = re.search(r"-?(?:\d+(?:\.\d+)?|\.\d+)", v.replace(",", ""))
    if not m:
        return None
    try:
        return float(m.group())
    except ValueError:
        return None


def parse_page(title, text):
    body = find_template(text, "ManuInfo")
    if body is None:
        return None

    fields = {}
    for part in split_params(body):
        if "=" not in part:
            continue
        k, _, v = part.partition("=")
        fields[k.strip().lower()] = clean(v)

    ings = []
    for n in range(1, 21):
        name = fields.get(f"ing{n}")
        if not name:
            continue
        amt = number(fields.get(f"ing{n}amount") or "1") or 1
        ings.append((name, amt, n))
    if not ings:
        return None

    # The free-text section below the template carries the weights.
    def after(label):
        m = re.search(label + r"\s*:\s*([^\n*]+)", text, re.I)
        return clean(m.group(1)) if m else None

    # "General stores pay 7.5 gold coins each" - take the number next to
    # "pay", not the first number anywhere in the sentence.
    vendor = None
    buyer = after("Buyer")
    if buyer:
        m = re.search(r"pays?\s+([\d,.]+)", buyer, re.I)
        vendor = number(m.group(1)) if m else None

    return {
        "item": fields.get("item") or title,
        "skill": fields.get("skill") or None,
        "level": number(fields.get("lvl")),
        "exp": number(fields.get("exp")),
        "tool": fields.get("tool") or None,
        "food": number(fields.get("food")),
        "nexus": fields.get("nexus") or None,
        "nexus_level": number(fields.get("nexuslvl")),
        "knowledge": fields.get("know") or None,
        "product_emu": number(after("Final Product Weight") or ""),
        "ingredients_emu": number(after("Ingredients Weight") or ""),
        "stackable": after("Stackable"),
        "vendor_pays": vendor,
        "ingredients": ings,
    }


def parse_harvestables(text):
    """
    The Harvestables page is bulleted lists under Plants / Ores / Minerals /
    Other, each line roughly:
        * [[File:Black Rose.png|...]] [[Black Rose]] [lvl 6] [exp 12]
    Levels are sometimes "?" and experience is missing for some sections.
    """
    REAL = {"plants", "ores", "minerals", "other", "flowers", "herbs"}
    out, kind = {}, None
    for line in text.splitlines():
        head = re.match(r"\s*=+\s*([A-Za-z ]+?)\s*=+\s*$", line)
        if head:
            kind = head.group(1).strip()
            continue
        # Hints, Value and Quick List are prose, not harvestables.
        if not kind or kind.lower() not in REAL:
            continue
        if not line.lstrip().startswith("*"):
            continue
        names = [n for n in re.findall(r"\[\[([^\]|]+)", line)
                 if ":" not in n]
        if not names:
            continue
        name = names[-1].strip()          # the item link, after the icon
        lvl = re.search(r"lvl\s*([\d.]+)", line, re.I)
        exp = re.search(r"exp\s*([\d.]+)", line, re.I)
        out[name] = {
            "name": name,
            "level": float(lvl.group(1)) if lvl else None,
            "exp": float(exp.group(1)) if exp else None,
            "kind": kind,
        }
    return out


def harvest_details(s_http, con, names, ts):
    """
    Some materials cannot be gathered at all without a particular item -
    hydrogenium ore wants a sword in hand, for instance. That turns a
    recipe from expensive into unavailable, so it is worth knowing.
    """
    print("reading each harvestable's own page...")
    found = sample = 0
    for i in range(0, len(names), BATCH):
        chunk = names[i:i + BATCH]
        try:
            r = api(s_http, action="query", prop="revisions", rvprop="content",
                    rvslots="main", titles="|".join(chunk))
        except Exception as e:
            print(f"  batch failed: {e}")
            continue
        for page in r["query"]["pages"]:
            title = page["title"]
            try:
                text = page["revisions"][0]["slots"]["main"]["content"]
            except (KeyError, IndexError):
                continue
            try:
                got = read_harvest_page(con, title, text, ts)
            except Exception as e:
                print(f"  {title}: {e}")
                continue
            if got:
                found += 1
                if sample == 0:
                    sample = 1
                    print(f"\n  --- sample: {title} ---")
                    print("  " + text[:700].replace("\n", "\n  "))
                    print("  --- end sample ---\n")
        time.sleep(PAUSE)
    con.commit()
    apply_overrides(con)
    print(f"  {found} of {len(names)} pages had a HarvestInfo template")
    gated = con.execute("""SELECT name, tool, nexus_level FROM harvestable
                           WHERE tool IS NOT NULL AND tool <> ''
                           ORDER BY name""").fetchall()
    print(f"  {len(gated)} need a tool in hand:")
    for r in gated:
        nx = f", nexus {int(r['nexus_level'])}" if r["nexus_level"] else ""
        print(f"    {r['name']:<24} {r['tool']}{nx}")


def read_harvest_page(con, title, text, ts):
    """
    Harvestable pages carry a HarvestInfo template:
        {{HarvestInfo |item= |exp= |lvl= |nexuslvl= |tool= |ing= }}
    The tool field is the one that matters - amber wants a saw, and
    without it the material is not gatherable at all.
    """
    body = find_template(text, "HarvestInfo")
    fields = {}
    if body:
        for part in split_params(body):
            if "=" in part:
                k, _, v = part.partition("=")
                fields[k.strip().lower()] = clean(v)

    ap = re.search(r"You need\s+([\d,]+)\s*\[*\s*Action Points", text, re.I)

    # The template's tool field misses things - hydrogenium wants a sword in
    # your inventory as well as a pickaxe, and the template never says so.
    # Keep any bullet that reads like a requirement, so it can be shown.
    notes = []
    for line in text.splitlines():
        if not line.lstrip().startswith("*"):
            continue
        plain = clean(line.lstrip("* ").strip())
        if not plain or "Action Points" in plain:
            continue
        if re.search(r"\b(need|needs|require|requires|must have|must carry|"
                     r"in your inventory|equipped|in hand)\b", plain, re.I):
            notes.append(plain)
    note_text = " | ".join(notes[:4]) or None

    con.execute("""UPDATE harvestable SET
                       tool  = ?,
                       level = COALESCE(?, level),
                       exp   = COALESCE(?, exp),
                       nexus_level = ?,
                       needs_item  = ?,
                       action_points = ?,
                       notes = ?,
                       imported = ?
                   WHERE name = ?""",
                (fields.get("tool") or None,
                 number(fields.get("lvl") or ""),
                 number(fields.get("exp") or ""),
                 number(fields.get("nexuslvl") or ""),
                 fields.get("ing") or None,
                 number(ap.group(1)) if ap else None,
                 note_text,
                 ts, title))
    return bool(fields)


def import_harvestables(s_http, con, ts):
    print("reading the harvestables page...")
    try:
        text = api(s_http, action="parse", page=HARVEST_PAGE,
                   prop="wikitext")["parse"]["wikitext"]
    except Exception as e:
        print(f"  could not read it: {e}")
        return 0
    found = parse_harvestables(text)
    for h in found.values():
        con.execute("""INSERT INTO harvestable (name, level, exp, kind, imported)
            VALUES (?,?,?,?,?)
            ON CONFLICT(name) DO UPDATE SET level=excluded.level,
                exp=excluded.exp, kind=excluded.kind,
                imported=excluded.imported""",
            (h["name"], h["level"], h["exp"], h["kind"], ts))
    con.commit()
    kinds = {}
    for h in found.values():
        kinds[h["kind"] or "?"] = kinds.get(h["kind"] or "?", 0) + 1
    print(f"  {len(found)} harvestables  "
          + ", ".join(f"{k} {v}" for k, v in sorted(kinds.items())))
    harvest_details(s_http, con, sorted(found), ts)
    return len(found)


OVERRIDES_FILE = "overrides.json"


def apply_overrides(con):
    """
    Anything the wiki gets wrong or leaves out, recorded by someone who
    actually plays. Create overrides.json next to this script:

        {"harvestable": {
            "Hydrogenium Ore": {"tool": "Pickaxe and Steel Two Edged Sword"}
        }}
    """
    import json
    import os
    if not os.path.exists(OVERRIDES_FILE):
        return
    try:
        with open(OVERRIDES_FILE, encoding="utf-8") as f:
            data = json.load(f)
    except Exception as e:
        print(f"  could not read {OVERRIDES_FILE}: {e}")
        return
    n = 0
    for name, changes in (data.get("harvestable") or {}).items():
        allowed = {"tool", "level", "nexus_level", "needs_item",
                   "action_points", "notes"}
        cols = {k: v for k, v in changes.items() if k in allowed}
        if not cols:
            continue
        sets = ", ".join(f"{k}=?" for k in cols)
        cur = con.execute(f"UPDATE harvestable SET {sets} WHERE name=?",
                          (*cols.values(), name))
        if cur.rowcount:
            n += 1
        else:
            print(f"  override for unknown harvestable: {name}")
    con.commit()
    if n:
        print(f"  applied {n} override{'s' if n != 1 else ''} "
              f"from {OVERRIDES_FILE}")


# ------------------------------------------------------------ import

def do_import(args):
    con = connect(args.db)
    s = session()

    print("listing pages that use the recipe template...")
    titles, cont = [], {}
    while True:
        r = api(s, action="query", list="embeddedin", eititle=TEMPLATE,
                eilimit=500, einamespace=0, **cont)
        titles += [p["title"] for p in r["query"]["embeddedin"]]
        if "continue" not in r:
            break
        cont = r["continue"]
        time.sleep(PAUSE)
    print(f"  {len(titles)} pages")

    ts = datetime.now(timezone.utc).isoformat(timespec="seconds")
    import_harvestables(s, con, ts)
    print()
    ok = skipped = 0
    failed = []
    fixed_skills = {}

    for i in range(0, len(titles), BATCH):
        chunk = titles[i:i + BATCH]
        r = api(s, action="query", prop="revisions", rvprop="content",
                rvslots="main", titles="|".join(chunk))
        for page in r["query"]["pages"]:
            title = page["title"]
            try:
                text = page["revisions"][0]["slots"]["main"]["content"]
            except (KeyError, IndexError):
                failed.append(title); continue
            rec = parse_page(title, text)
            if not rec:
                skipped += 1; continue
            rec["skill"], corrected = canon_skill(rec["skill"])
            if corrected:
                fixed_skills[rec["skill"]] = fixed_skills.get(rec["skill"], 0) + 1

            con.execute("""
                INSERT INTO recipe (item, skill, level, exp, tool, food, nexus,
                    nexus_level, knowledge, product_emu, ingredients_emu,
                    stackable, vendor_pays, imported)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                ON CONFLICT(item) DO UPDATE SET
                    skill=excluded.skill, level=excluded.level,
                    exp=excluded.exp, tool=excluded.tool, food=excluded.food,
                    nexus=excluded.nexus, nexus_level=excluded.nexus_level,
                    knowledge=excluded.knowledge,
                    product_emu=excluded.product_emu,
                    ingredients_emu=excluded.ingredients_emu,
                    stackable=excluded.stackable,
                    vendor_pays=excluded.vendor_pays, imported=excluded.imported
            """, (rec["item"], rec["skill"], rec["level"], rec["exp"],
                  rec["tool"], rec["food"], rec["nexus"], rec["nexus_level"],
                  rec["knowledge"], rec["product_emu"], rec["ingredients_emu"],
                  rec["stackable"], rec["vendor_pays"], ts))

            con.execute("DELETE FROM recipe_ingredient WHERE item=?",
                        (rec["item"],))
            for name, amt, pos in rec["ingredients"]:
                con.execute("""INSERT OR REPLACE INTO recipe_ingredient
                    (item, ingredient, amount, position) VALUES (?,?,?,?)""",
                    (rec["item"], name, amt, pos))
            ok += 1
        con.commit()
        print(f"  {min(i + BATCH, len(titles)):>4}/{len(titles)}  "
              f"{ok} recipes")
        time.sleep(PAUSE)

    stored = con.execute("SELECT COUNT(*) FROM recipe").fetchone()[0]
    print(f"\nimported {ok} recipes, skipped {skipped} pages with no "
          f"ingredients")
    if ok > stored:
        print(f"note: {ok - stored} pages share an item name with another "
              f"page, so only the last of each was kept")
    if fixed_skills:
        print("tidied skill names: "
              + ", ".join(f"{k} +{v}" for k, v in sorted(fixed_skills.items())))
    odd = con.execute("""SELECT skill, COUNT(*) n FROM recipe
                         WHERE skill IS NOT NULL GROUP BY skill""").fetchall()
    strange = [r for r in odd if r["skill"] not in KNOWN_SKILLS]
    if strange:
        print("skill field not recognised on: "
              + ", ".join(f"{r['skill']} ({r['n']})" for r in strange)
              + "  - worth fixing on the wiki itself")
    if failed:
        print(f"could not read: {', '.join(failed[:10])}")

    by_skill = con.execute("""SELECT IFNULL(skill,'?') s, COUNT(*) n
                              FROM recipe GROUP BY s ORDER BY n DESC""")
    print()
    for r in by_skill:
        print(f"  {r['s']:<18}{r['n']:>4}")


# ------------------------------------------------------------ pricing

def price_table(con):
    """Cheapest live sell price per item name, lowercased for matching."""
    rows = con.execute("""
        SELECT LOWER(i.name) n, MIN(l.price) p
        FROM listing l JOIN item i ON i.item_id = l.item_id
        WHERE l.side='sell' AND IFNULL(l.quantity,0) <> 0
        GROUP BY n
    """).fetchall()
    sell = {r["n"]: r["p"] for r in rows}
    rows = con.execute("""
        SELECT LOWER(i.name) n, MAX(l.price) p
        FROM listing l JOIN item i ON i.item_id = l.item_id
        WHERE l.side='buy' AND IFNULL(l.quantity,0) <> 0
        GROUP BY n
    """).fetchall()
    buy = {r["n"]: r["p"] for r in rows}
    return sell, buy


def harvest_set(con):
    return {r["name"].lower() for r in con.execute("SELECT name FROM harvestable")}


def cost_of(con, item, sell, buy, harvested=None, gathered_worth="value"):
    """
    Cost of one craft.

    An ingredient you gather is not free. If a bot would pay you for it,
    using one costs you that sale - so by default a gathered ingredient is
    valued at the best price a bot pays. That is the number that tells you
    whether crafting beats just selling the materials.

    gathered_worth: "value" (what bots pay), "free" (time only), or
    "none" (gathered ingredients disqualify the recipe).
    Returns (cost, missing, gathered).
    """
    harvested = harvested or set()
    total, missing, gathered = 0.0, [], []
    for r in con.execute("""SELECT ingredient, amount FROM recipe_ingredient
                            WHERE item=?""", (item,)):
        key = r["ingredient"].lower()
        p = sell.get(key)
        if p is not None:
            total += p * r["amount"]
            continue
        if key in harvested and gathered_worth != "none":
            gathered.append(r["ingredient"])
            if gathered_worth == "value":
                total += (buy.get(key) or 0.0) * r["amount"]
            continue
        missing.append(r["ingredient"])
    return total, missing, gathered


MODES = {
    # mode     -> how a gathered ingredient is valued
    "buy":     "none",    # must be buyable from a bot
    "value":   "value",   # valued at what a bot would pay you for it
    "free":    "free",    # costs you nothing but time
}


def costed(con, mode="value"):
    sell, buy = price_table(con)
    worth = MODES[mode]
    harvested = harvest_set(con) if worth != "none" else set()
    out = []
    for rec in con.execute("SELECT * FROM recipe"):
        cost, missing, gathered = cost_of(con, rec["item"], sell, buy,
                                          harvested, worth)
        if missing:
            continue
        revenue = buy.get(rec["item"].lower())
        vendor = rec["vendor_pays"]
        if revenue is not None:
            best, where = revenue, "bot"
        elif vendor is not None:
            best, where = vendor, "vendor"
        else:
            best, where = 0.0, "nobody"
        out.append({
            "item": rec["item"], "skill": rec["skill"] or "?",
            "level": rec["level"], "exp": rec["exp"] or 0,
            "cost": cost, "sells_for": best, "where": where,
            "profit": best - cost, "gathered": gathered,
            "margin": (best - cost) / cost * 100 if cost > 0 else None,
        })
    return out


def fmt(v):
    if v is None:
        return "-"
    return f"{v:,.0f}" if abs(v) >= 1000 else f"{v:,.2f}".rstrip("0").rstrip(".")


def do_profit(args):
    con = connect(args.db)
    all_rows = costed(con, args.mode)
    rows = [r for r in all_rows if r["profit"] > 0]
    key = (lambda r: -(r["margin"] or -1e9)) if args.by == "margin" \
        else (lambda r: -r["profit"])
    rows.sort(key=key)
    if not rows:
        sys.exit("Nothing is profitable to craft at current prices.")
    blurb = {
        "buy":   "every ingredient bought from a bot",
        "value": "gathered ingredients valued at what bots pay for them",
        "free":  "gathered ingredients cost nothing but your time",
    }[args.mode]
    print(f"mode: {args.mode}  ({blurb})")
    print()
    print(f"{'ITEM':<32}{'SKILL':<14}{'LVL':>4}{'COST':>11}{'SELLS':>11}"
          f"{'PROFIT':>10}{'MARGIN':>8}  TO")
    for r in rows[:args.limit]:
        star = " *" if r["gathered"] else ""
        name = (r["item"] + star)[:31]
        lvl = int(r["level"]) if r["level"] is not None else "-"
        margin = "free" if r["margin"] is None else f"{r['margin']:.0f}%"
        print(f"{name:<32}{r['skill'][:13]:<14}{lvl:>4}"
              f"{fmt(r['cost']):>11}{fmt(r['sells_for']):>11}"
              f"{fmt(r['profit']):>10}{margin:>8}  {r['where']}")
    total = con.execute("SELECT COUNT(*) FROM recipe").fetchone()[0]
    print(f"\n{len(rows)} profitable of {len(all_rows)} priceable, "
          f"{total} recipes known")
    if args.mode != "buy":
        print("* uses ingredients you gather yourself")


def do_xp(args):
    """Cheapest experience. Negative cost means you profit while levelling."""
    con = connect(args.db)
    rows = [r for r in costed(con, args.mode) if r["exp"] > 0]
    for r in rows:
        r["per_xp"] = (r["cost"] - r["sells_for"]) / r["exp"]
    rows.sort(key=lambda r: r["per_xp"])
    by_skill = {}
    for r in rows:
        by_skill.setdefault(r["skill"], []).append(r)
    for skill in sorted(by_skill):
        print(f"\n{skill}")
        print(f"  {'ITEM':<32}{'LVL':>4}{'EXP':>7}{'GC PER XP':>12}")
        for r in by_skill[skill][:args.limit]:
            tag = "  (profit)" if r["per_xp"] < 0 else ""
            tag += " *" if r["gathered"] else ""
            print(f"  {r['item'][:31]:<32}"
                  f"{(int(r['level']) if r['level'] is not None else '-'):>4}"
                  f"{int(r['exp']):>7}{r['per_xp']:>12,.2f}{tag}")


def do_recipe(args):
    con = connect(args.db)
    rec = con.execute("SELECT * FROM recipe WHERE item LIKE ?",
                      (f"%{args.query}%",)).fetchone()
    if not rec:
        sys.exit(f"No recipe matching '{args.query}'")
    sell, buy = price_table(con)
    harvested = harvest_set(con)
    gathered_cost = 0.0
    print(f"\n{rec['item']}")
    print(f"  {rec['skill']} level {int(rec['level'] or 0)}, "
          f"{int(rec['exp'] or 0)} exp"
          + (f", needs {rec['tool']}" if rec['tool'] else "")
          + (f", {int(rec['food'])} food" if rec['food'] else ""))
    if rec["nexus"]:
        print(f"  nexus: {rec['nexus']} {int(rec['nexus_level'] or 0)}")
    print()
    total = 0.0
    for r in con.execute("""SELECT ingredient, amount FROM recipe_ingredient
                            WHERE item=? ORDER BY position""", (rec["item"],)):
        key = r["ingredient"].lower()
        p = sell.get(key)
        line = f"  {int(r['amount'])} x {r['ingredient']:<28}"
        if p is None:
            h = con.execute("""SELECT level, tool FROM harvestable
                               WHERE LOWER(name)=?""", (key,)).fetchone()
            if h:
                lv = f" lvl {int(h['level'])}" if h["level"] else ""
                if h["tool"]:
                    lv += f", needs {h['tool']}"
                worth = buy.get(key)
                if worth:
                    gathered_cost += worth * r["amount"]
                    total += worth * r["amount"]
                    print(line + f"  gather{lv}, worth {fmt(worth)} each"
                                 f"{fmt(worth * r['amount']):>9}")
                else:
                    print(line + f"  gather{lv}, nobody buys it")
            else:
                print(line + "   no bot sells it")
        else:
            total += p * r["amount"]
            print(line + f"{fmt(p):>10} each{fmt(p * r['amount']):>12}")
    print(f"  {'':<32}{'cost':>15}{fmt(total):>12}")
    got = buy.get(rec["item"].lower())
    if got is not None:
        print(f"  {'':<32}{'bots pay':>15}{fmt(got):>12}")
        print(f"  {'':<32}{'profit':>15}{fmt(got - total):>12}")
    elif rec["vendor_pays"]:
        print(f"  {'':<32}{'vendor pays':>15}{fmt(rec['vendor_pays']):>12}")
        print(f"  {'':<32}{'profit':>15}"
              f"{fmt(rec['vendor_pays'] - total):>12}")
    if rec["exp"]:
        net = total - (got if got is not None else (rec["vendor_pays"] or 0))
        print(f"  {'':<32}{'per xp':>15}{net / rec['exp']:>12,.2f}")


def main():
    p = argparse.ArgumentParser(description="EL recipes and craft pricing")
    p.add_argument("--db", default=DB_PATH)
    sub = p.add_subparsers(dest="cmd", required=True)

    i = sub.add_parser("import", help="fetch recipes from the wiki")
    i.set_defaults(func=do_import)

    pr = sub.add_parser("profit", help="what's worth making right now")
    pr.add_argument("--limit", type=int, default=40)
    pr.add_argument("--mode", choices=["buy", "value", "free"],
                    default="value",
                    help="buy: bought ingredients only. value: gathered ones "
                         "valued at what bots pay (default). free: gathered "
                         "ones cost nothing")
    pr.add_argument("--by", choices=["profit", "margin"], default="profit")
    pr.set_defaults(func=do_profit)

    x = sub.add_parser("xp", help="cheapest experience per skill")
    x.add_argument("--limit", type=int, default=6)
    x.add_argument("--mode", choices=["buy", "value", "free"], default="value")
    x.set_defaults(func=do_xp)

    rc = sub.add_parser("recipe", help="one recipe, costed")
    rc.add_argument("query")
    rc.set_defaults(func=do_recipe)

    a = p.parse_args()
    a.func(a)


if __name__ == "__main__":
    main()
