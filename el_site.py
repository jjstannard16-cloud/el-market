#!/usr/bin/env python3
"""
el_site.py - turn el_bots.db into a browsable web page.

Reads the database made by el_bots.py and writes index.html: a searchable
market browser with cheapest sellers, best buyers, and a profit table ranked
by what you can actually make rather than per-unit spread.

Usage:
    python el_site.py                 # writes index.html
    python el_site.py --open          # writes it and opens it in your browser
    python el_site.py --out docs/index.html
"""

import argparse
import json
import os
import sqlite3
import sys
import webbrowser
from datetime import datetime, timezone

DB_PATH = "el_bots.db"
OUT_PATH = "index.html"
IMG_BASE = "https://bots.el-services.net/images/"

# Which landmass each map sits on. Bots report locations like
# "White Stone - Tirnwood Vale", so we match on the part before the dash.
CONTINENTS = {
    "Seridia": [
        "tahraji desert", "desert pines", "kilaran field", "north kilaran",
        "valley of the dwarves", "nordcarn", "tarsengaard", "tarsengaard",
        "portland", "white stone", "whitestone", "morcraven marsh",
        "naralik", "grubani peninsula", "ruins of tirnym", "isla prima",
        # Underground maps, which don't appear on the overworld maps.
        "crystal cavern", "crystal caverns",   # cave inside Desert Pines
    ],
    "Irilion": [
        "idaloran", "melinis", "bethel", "sedicolis", "north redmoon",
        "south redmoon", "palon vertas", "thelinor", "irsis", "zirakinbar",
        "emerald valley", "kusamura", "hurquin", "yarris", "egratia point",
        "imbroglio islands", "willowvine forest", "aeth aelfan",
        "iscarlith", "irinveron", "glacmor", "isle of the forgotten",
        "trassian", "hulda",
    ],
}
MAP_TO_CONTINENT = {m: c for c, maps in CONTINENTS.items() for m in maps}


def split_location(loc):
    """'White Stone - Tirnwood Vale' -> ('White Stone', 'Irilion'|'Seridia'|None)"""
    if not loc:
        return None, None
    base = loc.split(" - ")[0].strip()
    return base, MAP_TO_CONTINENT.get(base.lower())


def load(db_path):
    if not os.path.exists(db_path):
        sys.exit(f"No database at {db_path}. Run: python el_bots.py scrape")

    con = sqlite3.connect(db_path)
    con.row_factory = sqlite3.Row

    unknown_maps = set()

    # Capacity columns arrived later. A database written by an older scraper
    # does not have them, and this reader must not fail on that or alter it.
    bot_cols = {r["name"] for r in con.execute("PRAGMA table_info(bot)")}
    slots = "b.slots" if "slots" in bot_cols else "NULL"
    emu = "b.emu" if "emu" in bot_cols else "NULL"

    bots = [dict(r) for r in con.execute(f"""
        SELECT b.name, b.location, b.map_x, b.map_y, b.owner,
               {slots} AS slots, {emu} AS emu, b.last_seen,
               (SELECT COUNT(*) FROM listing l
                 WHERE l.bot=b.name AND l.side='sell') AS sells,
               (SELECT COUNT(*) FROM listing l
                 WHERE l.bot=b.name AND l.side='buy')  AS buys
        FROM bot b ORDER BY b.name COLLATE NOCASE
    """)]

    for b in bots:
        b["map"], b["continent"] = split_location(b["location"])
        if b["map"] and not b["continent"]:
            unknown_maps.add(b["map"])

    rows = con.execute(f"""
        SELECT i.item_id, i.name AS item, i.image,
               l.side, l.price, l.quantity, l.bot,
               b.location, b.map_x, b.map_y,
               {slots} AS slots, {emu} AS emu
        FROM listing l
        JOIN item i ON i.item_id = l.item_id
        LEFT JOIN bot b ON b.name = l.bot
        ORDER BY i.name COLLATE NOCASE, l.price
    """).fetchall()

    items = {}
    for r in rows:
        it = items.setdefault(r["item_id"], {
            "id": r["item_id"], "name": r["item"], "img": r["image"],
            "sell": [], "buy": [],
        })
        loc = r["location"] or ""
        mp, cont = split_location(loc)
        if mp and not cont:
            unknown_maps.add(mp)
        if r["map_x"] is not None:
            loc = f"{loc} [{r['map_x']},{r['map_y']}]"
        it[r["side"]].append({
            "bot": r["bot"], "loc": loc.strip(), "map": mp, "cont": cont,
            "qty": r["quantity"] or 0, "price": r["price"],
            "slots": r["slots"], "emu": r["emu"],
        })

    # Recipes are optional: the tables only exist once el_recipes.py has run.
    tables = {r["name"] for r in
              con.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    recipes, harvestables = [], {}
    if {"recipe", "recipe_ingredient"} <= tables:
        ings = {}
        for r in con.execute("""SELECT item, ingredient, amount
                                FROM recipe_ingredient ORDER BY position"""):
            ings.setdefault(r["item"], []).append(
                {"n": r["ingredient"], "a": r["amount"]})
        for r in con.execute("SELECT * FROM recipe"):
            recipes.append({
                "item": r["item"], "skill": r["skill"] or "?",
                "level": r["level"], "exp": r["exp"] or 0,
                "tool": r["tool"], "food": r["food"],
                "vendor": r["vendor_pays"],
                "ings": ings.get(r["item"], []),
            })
    if "harvestable" in tables:
        hcols = {r["name"] for r in con.execute("PRAGMA table_info(harvestable)")}
        extra = ", ".join(c if c in hcols else f"NULL AS {c}"
                          for c in ("tool", "nexus_level"))
        for r in con.execute(f"SELECT name, level, {extra} FROM harvestable"):
            harvestables[r["name"].lower()] = {
                "lvl": r["level"], "tool": r["tool"],
                "nexus": r["nexus_level"],
            }

    # Players are optional too: only present once el_players.py has run.
    players, skills, movers = [], [], []
    if "player" in tables:
        stats = {}
        if "player_stat" in tables:
            for r in con.execute("""SELECT name, kind, stat, level
                                    FROM player_stat"""):
                stats.setdefault(r["name"], {})[r["stat"]] = {
                    "k": r["kind"], "v": r["level"]}
                if r["kind"] == "skill" and r["stat"] not in skills:
                    skills.append(r["stat"])
        pcols = {r["name"] for r in con.execute("PRAGMA table_info(player)")}
        priv = "private" if "private" in pcols else "NULL"
        miss = "missing" if "missing" in pcols else "NULL"
        # A week of PK figures, to show movement.
        week = {}
        if "pk_snapshot" in tables:
            for r in con.execute("""SELECT name, fights, won FROM pk_snapshot
                                    WHERE day <= date('now', '-7 day')
                                    GROUP BY name HAVING day = MAX(day)"""):
                week[r["name"]] = {"f": r["fights"], "w": r["won"]}
        for r in con.execute(f"""SELECT name, overall, pk_score, pk_fights,
                                 pk_won, pk_lost, achievements, source,
                                 {priv} AS private, {miss} AS missing,
                                 last_read FROM player"""):
            if r["missing"]:
                continue
            w = week.get(r["name"], {})
            players.append({
                "name": r["name"], "overall": r["overall"],
                "private": bool(r["private"]),
                "pk": None if not r["pk_fights"] else {
                    "score": r["pk_score"], "f": r["pk_fights"],
                    "w": r["pk_won"], "l": r["pk_lost"],
                    "wasF": w.get("f"), "wasW": w.get("w"),
                },
                "ach": r["achievements"],
                "stats": stats.get(r["name"], {}),
            })
        if "level_change" in tables:
            for r in con.execute("""SELECT name, stat, was, now, at
                                    FROM level_change
                                    ORDER BY at DESC, name LIMIT 300"""):
                movers.append({"name": r["name"], "stat": r["stat"],
                               "was": r["was"], "now": r["now"],
                               "at": r["at"][:10]})

    # price history, for a sparkline / "changed recently" flag later
    hist_count = con.execute("SELECT COUNT(*) FROM price_history").fetchone()[0]
    runs = con.execute("""SELECT COUNT(*) FROM run
                          WHERE finished_at IS NOT NULL""").fetchone()[0]
    last = con.execute("""SELECT MAX(last_seen) FROM listing""").fetchone()[0]

    con.close()

    for it in items.values():
        it["sell"].sort(key=lambda x: x["price"])
        it["buy"].sort(key=lambda x: -x["price"])

    return {
        "items": sorted(items.values(), key=lambda x: x["name"].lower()),
        "bots": bots,
        "recipes": sorted(recipes, key=lambda r: r["item"].lower()),
        "players": sorted(players, key=lambda p: p["name"].lower()),
        "skills": skills,
        "movers": movers,
        "harvestables": harvestables,
        "meta": {
            "generated": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "lastScrape": last,
            "runs": runs,
            "botCount": len(bots),
            "itemCount": len(items),
            "listingCount": sum(len(i["sell"]) + len(i["buy"])
                                for i in items.values()),
            "historyRows": hist_count,
            "imgBase": IMG_BASE,
            "unknownMaps": sorted(unknown_maps),
            "recipeCount": len(recipes),
            "playerCount": sum(1 for p in players if not p["private"]),
            "privateCount": sum(1 for p in players if p["private"]),
        },
    }


HTML = r"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>EL Market</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Fraunces:opsz,wght@9..144,400;9..144,600;9..144,700&family=Archivo:wght@400;500;600&display=swap" rel="stylesheet">
<style>
  :root {
    --ground:  #0d1210;
    --panel:   #151c17;
    --raised:  #1b241d;
    --line:    #273227;
    --line-2:  #35422f;
    --ink:     #e6dfcb;
    --muted:   #8d8a76;
    --brass:   #d0a63c;
    --brass-d: #6b5420;
    --patina:  #6fa79b;
    --patina-d:#2c4a45;
    --rust:    #b4603f;
    --display: "Fraunces", Georgia, serif;
    --ui: "Archivo", system-ui, -apple-system, "Segoe UI", sans-serif;
  }
  * { box-sizing: border-box; }
  html { -webkit-text-size-adjust: 100%; }
  body {
    margin: 0; background: var(--ground); color: var(--ink);
    font: 400 15px/1.5 var(--ui);
  }
  .wrap { max-width: 1240px; margin: 0 auto; padding: 0 22px; }
  .num, th.num { font-variant-numeric: tabular-nums; }

  /* masthead ------------------------------------------------------- */
  .mast { border-bottom: 1px solid var(--line); }
  .mast .wrap {
    display: flex; align-items: flex-end; justify-content: space-between;
    gap: 24px; flex-wrap: wrap; padding-top: 26px; padding-bottom: 18px;
  }
  .mark { font-family: var(--display); font-size: 34px; font-weight: 600;
          line-height: 1; letter-spacing: -.015em; color: var(--ink); }
  .mark em { font-style: normal; color: var(--brass); }
  .ledger { display: flex; gap: 26px; }
  .ledger div { text-align: right; }
  .ledger .n { font-family: var(--display); font-size: 19px; font-weight: 600;
               line-height: 1.1; font-variant-numeric: tabular-nums; }
  .ledger .k { font-size: 12px; color: var(--muted); }

  /* the floor ------------------------------------------------------ */
  .floor { border-bottom: 1px solid var(--line); background: var(--panel); }
  .floor .wrap { padding-top: 18px; padding-bottom: 20px; }
  .floor h2 { font-family: var(--display); font-weight: 400; font-size: 16px;
              margin: 0 0 12px; color: var(--muted); }
  .deals { display: grid; grid-template-columns: repeat(3, 1fr); gap: 12px; }
  .deal {
    display: flex; gap: 12px; align-items: flex-start; text-align: left;
    background: var(--raised); border: 1px solid var(--line);
    border-left: 3px solid var(--brass); border-radius: 3px;
    padding: 13px 15px; cursor: pointer; color: inherit; font: inherit;
    width: 100%;
  }
  .deal:hover { border-color: var(--line-2); border-left-color: var(--brass); }
  .deal img { width: 30px; height: 30px; object-fit: contain; flex: none;
              image-rendering: pixelated; margin-top: 2px; }
  .deal > span { display: block; min-width: 0; }
  .deal .amt { display: block; font-family: var(--display); font-size: 22px;
               font-weight: 600; color: var(--brass); line-height: 1.1;
               font-variant-numeric: tabular-nums; }
  .deal .what { display: block; font-size: 13.5px; margin-top: 2px; }
  .deal .route { display: block; font-size: 12px; color: var(--muted);
                 margin-top: 3px; }
  .nodeals { color: var(--muted); font-size: 14px; padding: 2px 0 4px; }

  /* controls ------------------------------------------------------- */
  .bar { border-bottom: 1px solid var(--line); }
  .bar .wrap { display: flex; align-items: center; gap: 18px;
               flex-wrap: wrap; padding-top: 0; }
  nav { display: flex; }
  nav button {
    background: none; border: 0; border-bottom: 2px solid transparent;
    color: var(--muted); padding: 13px 0; margin-right: 22px; cursor: pointer;
    font: 500 14.5px var(--ui);
  }
  nav button:hover { color: var(--ink); }
  nav button.on { color: var(--brass); border-bottom-color: var(--brass); }
  .spacer { flex: 1; }
  input[type=search] {
    width: 260px; padding: 7px 11px; border-radius: 3px;
    border: 1px solid var(--line-2); background: var(--ground);
    color: var(--ink); font: 400 14px var(--ui);
  }
  input[type=search]::placeholder { color: #6a6a5c; }
  .walk { display: none; gap: 7px; align-items: center; color: var(--muted);
          font-size: 13.5px; cursor: pointer; user-select: none; }
  .walk input { accent-color: var(--brass); }
  .modes { display: none; align-items: center; gap: 0; font-size: 13px; }
  .modes .lbl { color: var(--muted); margin-right: 10px; }
  .modes button {
    background: none; border: 1px solid var(--line-2); border-right: 0;
    color: var(--muted); padding: 5px 11px; cursor: pointer;
    font: 400 12.5px var(--ui);
  }
  .modes button:first-of-type { border-radius: 3px 0 0 3px; }
  .modes button:last-of-type { border-right: 1px solid var(--line-2);
                               border-radius: 0 3px 3px 0; }
  .modes button:hover { color: var(--ink); }
  .modes button.on { color: var(--ground); background: var(--brass);
                     border-color: var(--brass); }
  .gathered { color: var(--patina); }
  .pick { display: none; padding: 5px 9px; border-radius: 3px;
          border: 1px solid var(--line-2); background: var(--ground);
          color: var(--ink); font: 400 13px var(--ui); }
  .caveat { color: var(--muted); font-size: 12.5px; margin: -2px 0 12px; }
  .hidden-row td { color: var(--muted); }
  .rank { color: var(--muted); font-variant-numeric: tabular-nums; }
  .chips { display: flex; flex-wrap: wrap; gap: 6px; margin-top: 4px; }
  .chip { font-size: 11.5px; border: 1px solid var(--line-2);
          border-radius: 10px; padding: 1px 8px; color: var(--muted); }
  .gate { font-size: 11.5px; color: var(--rust); border: 1px solid #4e2e26;
          border-radius: 10px; padding: 1px 7px; white-space: nowrap; }
  .ing { display: grid; grid-template-columns: 2.4rem 1fr auto auto;
         gap: 4px 14px; align-items: baseline; font-size: 13.5px;
         max-width: 620px; }
  .ing .amt { color: var(--muted); text-align: right; }
  .ing .each, .ing .sub { text-align: right; font-variant-numeric: tabular-nums; }
  .ing .rule { grid-column: 1 / -1; border-top: 1px solid var(--line-2);
               margin: 5px 0 1px; }

  /* tables --------------------------------------------------------- */
  main .wrap { padding-top: 16px; padding-bottom: 56px; }
  .meta-line { color: var(--muted); font-size: 13px; margin-bottom: 10px; }
  .scroller { overflow-x: auto; }
  table { width: 100%; border-collapse: collapse; font-size: 14px; }
  th {
    text-align: left; padding: 7px 11px; color: var(--muted);
    font-weight: 500; font-size: 13px; border-bottom: 1px solid var(--line-2);
    position: sticky; top: 0; background: var(--ground); cursor: pointer;
    white-space: nowrap;
  }
  th:hover { color: var(--ink); }
  th.num, td.num { text-align: right; }
  td { padding: 7px 11px; border-bottom: 1px solid var(--line);
       vertical-align: top; }
  tr.item { cursor: pointer; }
  tr.item:hover > td { background: var(--panel); }
  tr.item.open > td { background: var(--panel); }
  .nm { display: flex; align-items: center; gap: 10px; }
  .nm img { width: 20px; height: 20px; object-fit: contain; flex: none;
            image-rendering: pixelated; }
  .sm { color: var(--muted); font-size: 12.5px; }
  .brass { color: var(--brass); }
  .patina { color: var(--patina); }
  a.lnk { color: var(--ink); text-decoration: none;
          border-bottom: 1px solid var(--line-2); cursor: pointer; }
  a.lnk:hover { color: var(--brass); border-bottom-color: var(--brass); }

  .trip { font-size: 12px; white-space: nowrap; }
  .t-map  { color: var(--patina); }
  .t-cont { color: var(--ink); }
  .t-sea  { color: var(--rust); }

  /* expanded item -------------------------------------------------- */
  .detail > td { background: var(--panel); padding: 0;
                 border-bottom: 1px solid var(--line-2); }
  .dwrap { padding: 16px 14px 20px; }
  .verdict { font-size: 14px; margin-bottom: 16px; }
  .verdict b { font-weight: 600; }

  .axis { margin: 0 6px 20px; }
  .track { position: relative; height: 3px; background: var(--line);
           border-radius: 2px; }
  .overlap { position: absolute; top: 0; height: 3px; background: var(--patina-d); }
  .pin { position: absolute; width: 2px; border-radius: 1px;
         transform: translateX(-1px); }
  .pin.s { top: -7px; height: 17px; background: var(--brass); }
  .pin.b { top: -7px; height: 17px; background: var(--patina); }
  .ends { display: flex; justify-content: space-between; margin-top: 12px;
          font-size: 12px; color: var(--muted); font-variant-numeric: tabular-nums; }
  .legend { font-size: 12px; color: var(--muted); margin-top: 7px; }
  .swatch { display: inline-block; width: 2px; height: 10px;
            vertical-align: -1px; margin-right: 5px; }

  .cols { display: flex; gap: 36px; align-items: flex-start; flex-wrap: wrap; }
  .cols > div { flex: 1 1 320px; min-width: 0; }
  .cols h3 { font-family: var(--display); font-weight: 400; font-size: 15px;
             margin: 0 0 7px; color: var(--ink); }
  .cols h3 span { color: var(--muted); font-size: 13px; font-family: var(--ui); }
  .cols table { font-size: 13.5px; }
  .cols td { padding: 4px 12px 4px 0; border-bottom: 1px solid var(--line); }

  /* bot page ------------------------------------------------------- */
  .bothead { display: flex; align-items: baseline; gap: 16px; flex-wrap: wrap;
             margin: 2px 0 22px; }
  .bothead h2 { font-family: var(--display); font-weight: 600; font-size: 26px;
                margin: 0; }
  .bothead .where { color: var(--muted); font-size: 13.5px; }
  .back { background: none; border: 1px solid var(--line-2); color: var(--muted);
          padding: 5px 11px; border-radius: 3px; cursor: pointer;
          font: 400 13px var(--ui); }
  .back:hover { color: var(--ink); border-color: var(--muted); }

  .empty { padding: 56px 0; text-align: center; color: var(--muted); }
  footer { border-top: 1px solid var(--line); }
  footer .wrap { padding-top: 16px; padding-bottom: 40px;
                 color: var(--muted); font-size: 12.5px; line-height: 1.8; }
  code { font-family: ui-monospace, Menlo, Consolas, monospace;
         background: var(--panel); padding: 1px 5px; border-radius: 2px;
         font-size: 12px; color: var(--ink); }
  a { color: var(--brass); }
  :focus-visible { outline: 2px solid var(--brass); outline-offset: 2px; }
  @media (prefers-reduced-motion: reduce) { * { transition: none !important; } }
  @media (max-width: 860px) {
    .deals { grid-template-columns: 1fr; }
    .mast .wrap { padding-bottom: 14px; }
    .ledger { gap: 18px; }
    input[type=search] { width: 100%; }
    .hide-sm { display: none; }
  }
</style>
</head>
<body>

<div class="mast"><div class="wrap">
  <div class="mark">Eternal Lands <em>Market</em></div>
  <div class="ledger" id="ledger"></div>
</div></div>

<div class="floor"><div class="wrap">
  <h2>On the floor right now</h2>
  <div id="deals"></div>
</div></div>

<div class="bar"><div class="wrap">
  <nav>
    <button class="on" data-tab="market">Market</button>
    <button data-tab="profit">Profit</button>
    <button data-tab="craft">Craft</button>
    <button data-tab="players">Players</button>
    <button data-tab="bots">Bots</button>
  </nav>
  <div class="spacer"></div>
  <label class="walk" id="walkwrap">
    <input type="checkbox" id="walk"> Hide boat trips</label>
  <span class="modes" id="viewwrap">
    <button data-pview="skills" class="on">Skills</button>
    <button data-pview="pk">PK</button>
    <button data-pview="movers">Level-ups</button>
  </span>
  <select id="skillpick" class="pick"></select>
  <span class="modes" id="modewrap">
    <span class="lbl">Gathered materials</span>
    <button data-mode="value" class="on">worth what bots pay</button>
    <button data-mode="free">free</button>
    <button data-mode="buy">bought, not gathered</button>
  </span>
  <input type="search" id="q" placeholder="Item, bot or map" autofocus>
</div></div>

<main><div class="wrap">
  <div class="meta-line" id="count"></div>
  <div id="view"></div>
</div></main>

<footer><div class="wrap" id="foot"></div></footer>

<script>
const DATA = __DATA__;
const m = DATA.meta;
let tab = "market", sortKey = null, sortDir = 1, focusBot = null;
let walkableOnly = false;
const openIds = new Set();
const AUTO_OPEN_UPTO = 5;

const UNLIMITED = -1;
const cap = q => q === UNLIMITED ? Infinity : q;
const qty = q => q === UNLIMITED ? "no limit" : q.toLocaleString("en-GB");
const fmt = n => n == null ? "–" : n === Infinity ? "∞"
  : (Math.abs(n) >= 1000 ? Math.round(n).toLocaleString("en-GB")
                         : (+n.toFixed(2)).toLocaleString("en-GB"));
const esc = s => String(s).replace(/[&<>"]/g,
  c => ({ "&":"&amp;", "<":"&lt;", ">":"&gt;", '"':"&quot;" }[c]));

/* derived figures ---------------------------------------------------- */
for (const it of DATA.items) {
  const s = it.sell.filter(x => x.qty !== 0)[0] || null;
  const b = it.buy.filter(x => x.qty !== 0)[0] || null;
  it.best = { sell: s, buy: b };
  if (s && b && b.price > s.price) {
    it.unit = b.price - s.price;
    it.units = Math.min(cap(s.qty), cap(b.qty));
    it.total = it.units === Infinity ? Infinity : it.unit * it.units;
    it.trip = s.map && s.map === b.map ? "map"
            : s.cont && b.cont ? (s.cont === b.cont ? "cont" : "sea")
            : "unknown";
  } else { it.unit = it.units = it.total = 0; it.trip = null; }
}
const TRIP = {
  map:     { label: "same map",  cls: "t-map"  },
  cont:    { label: "a walk",    cls: "t-cont" },
  sea:     { label: "by boat",   cls: "t-sea"  },
  unknown: { label: "unknown",   cls: "sm"     },
};

const BOTS = {};
for (const b of DATA.bots) BOTS[b.name] = { info: b, sell: [], buy: [] };
for (const it of DATA.items)
  for (const side of ["sell", "buy"])
    for (const l of it[side])
      (BOTS[l.bot] ||= { info: { name: l.bot }, sell: [], buy: [] })[side]
        .push({ item: it, qty: l.qty, price: l.price });

const botLink = n => `<a class="lnk" data-bot="${esc(n)}">${esc(n)}</a>`;

/* crafting ------------------------------------------------------------
   An ingredient you gather is not free: if a bot buys it, using one costs
   you that sale. "value" prices gathered materials at what bots pay,
   which is the number that says whether crafting beats selling the raw
   materials. "free" ignores that, "buy" refuses to gather at all.        */
let craftMode = "value";
let pview = "skills", pskill = null, focusPlayer = null;
const PRICE = {};
for (const it of DATA.items) {
  const k = it.name.toLowerCase();
  PRICE[k] = {
    sell: (it.sell.filter(x => x.qty !== 0)[0] || {}).price ?? null,
    sellBot: (it.sell.filter(x => x.qty !== 0)[0] || {}).bot ?? null,
    buy: (it.buy.filter(x => x.qty !== 0)[0] || {}).price ?? null,
    buyBot: (it.buy.filter(x => x.qty !== 0)[0] || {}).bot ?? null,
  };
}
const HARVEST = DATA.harvestables || {};

function cost(r, mode) {
  let total = 0;
  const lines = [], missing = [], tools = [];
  let anyGathered = false, gate = 0;
  for (const g of r.ings) {
    const k = g.n.toLowerCase();
    const p = PRICE[k] || {};
    if (p.sell != null) {
      total += p.sell * g.a;
      lines.push({ ...g, each: p.sell, from: p.sellBot, how: "buy" });
    } else if (k in HARVEST && mode !== "buy") {
      anyGathered = true;
      const worth = mode === "value" ? (p.buy || 0) : 0;
      total += worth * g.a;
      const h = HARVEST[k] || {};
      lines.push({ ...g, each: worth, how: "gather",
                   lvl: h.lvl, tool: h.tool, nexus: h.nexus });
      if (h.nexus) gate = Math.max(gate, h.nexus);
      if (h.tool && !tools.includes(h.tool)) tools.push(h.tool);
    } else {
      missing.push(g.n);
      lines.push({ ...g, each: null, how: "none" });
    }
  }
  const p = PRICE[r.item.toLowerCase()] || {};
  let sells = p.buy, where = "bot", who = p.buyBot;
  if (sells == null && r.vendor != null) { sells = r.vendor; where = "vendor"; who = null; }
  if (sells == null) { sells = 0; where = "nobody"; }
  const profit = sells - total;
  return {
    cost: total, lines, missing, gathered: anyGathered,
    gate, tools, sells, where, who, profit,
    margin: total > 0 ? profit / total * 100 : null,
    perXp: r.exp > 0 ? -profit / r.exp : null,
  };
}
const icon = it => it.img
  ? `<img src="${m.imgBase}${it.img}" loading="lazy" alt="">` : `<img alt="">`;

/* masthead ----------------------------------------------------------- */
document.getElementById("ledger").innerHTML = [
  [m.botCount, "bots"], [m.itemCount, "items"], [m.listingCount, "offers"],
  ...(m.playerCount ? [[m.playerCount, "players"]] : []),
  [m.lastScrape ? new Date(m.lastScrape).toLocaleTimeString("en-GB",
     { hour: "2-digit", minute: "2-digit" }) : "–", "last read"],
].map(([n, k]) => `<div><div class="n">${
  typeof n === "number" ? n.toLocaleString("en-GB") : n
}</div><div class="k">${k}</div></div>`).join("");

document.getElementById("foot").innerHTML =
  `Built from ${m.runs} scrape${m.runs === 1 ? "" : "s"} of
   bots.el-services.net, ${m.historyRows.toLocaleString("en-GB")} price points
   recorded. Refresh with <code>python el_bots.py scrape</code> then
   <code>python el_site.py</code>.` +
  (m.unknownMaps.length
    ? `<br>Maps not yet placed on a continent: ${esc(m.unknownMaps.join(", "))}.`
    : "") +
  `<br>Item art is loaded from bots.el-services.net. Host your own copies
   before putting this online.`;

/* the floor ---------------------------------------------------------- */
(function floor() {
  const top = DATA.items
    .filter(it => it.total > 0 && it.trip !== "sea")
    .sort((a, b) => (b.total === Infinity ? 1e15 : b.total)
                  - (a.total === Infinity ? 1e15 : a.total))
    .slice(0, 3);
  const el = document.getElementById("deals");
  if (!top.length) {
    el.className = "nodeals";
    el.textContent =
      "No gaps worth walking for in this reading. Scrape again later.";
    return;
  }
  el.className = "deals";
  el.innerHTML = top.map(it => `
    <button class="deal" data-item="${esc(it.name)}">
      ${icon(it)}
      <span>
        <span class="amt">${fmt(it.total)}</span>
        <span class="what">${esc(it.name)}</span>
        <span class="route">${esc(it.best.sell.map || "?")} → ${
          esc(it.best.buy.map || "?")} &middot; ${
          it.units === Infinity ? "no limit" : qty(it.units)} to move</span>
      </span>
    </button>`).join("");
  el.querySelectorAll(".deal").forEach(btn => btn.onclick = () => {
    document.getElementById("q").value = btn.dataset.item;
    setTab("profit");
  });
})();

/* navigation --------------------------------------------------------- */
function setTab(t) {
  tab = t; sortKey = null; focusBot = null; focusPlayer = null;
  document.querySelectorAll("nav button").forEach(b =>
    b.classList.toggle("on", b.dataset.tab === t));
  render();
}
document.querySelectorAll("nav button").forEach(btn =>
  btn.onclick = () => { document.getElementById("q").value = ""; setTab(btn.dataset.tab); });
document.getElementById("q").oninput = () => {
  focusBot = null; focusPlayer = null; render();
};
document.getElementById("walk").onchange = e => {
  walkableOnly = e.target.checked; render();
};
document.querySelectorAll(".modes button").forEach(b => b.onclick = () => {
  document.querySelectorAll(".modes button").forEach(x =>
    x.classList.remove("on"));
  b.classList.add("on"); craftMode = b.dataset.mode; render();
});

function openBot(name) {
  focusBot = name; tab = "bots"; sortKey = null;
  document.querySelectorAll("nav button").forEach(b =>
    b.classList.toggle("on", b.dataset.tab === "bots"));
  window.scrollTo({ top: 0 });
  render();
}
const wireBotLinks = () =>
  document.querySelectorAll("a.lnk[data-bot]").forEach(a =>
    a.onclick = e => { e.stopPropagation(); openBot(a.dataset.bot); });

/* price spread ------------------------------------------------------- */
function axis(it) {
  const all = [...it.sell, ...it.buy].map(l => l.price);
  if (all.length < 2) return "";
  const lo = Math.min(...all), hi = Math.max(...all);
  if (hi === lo) return "";
  const log = hi / Math.max(lo, 0.01) > 40;
  const at = p => {
    const f = log ? (Math.log(p) - Math.log(lo)) / (Math.log(hi) - Math.log(lo))
                  : (p - lo) / (hi - lo);
    return (f * 100).toFixed(2);
  };
  const s = it.best.sell, b = it.best.buy;
  const gap = s && b && b.price > s.price
    ? `<div class="overlap" style="left:${at(s.price)}%;width:${
        at(b.price) - at(s.price)}%"></div>` : "";
  const pins = side => it[side].map(l =>
    `<div class="pin ${side[0]}" style="left:${at(l.price)}%" title="${
      esc(l.bot)} ${fmt(l.price)}"></div>`).join("");
  return `<div class="axis">
    <div class="track">${gap}${pins("sell")}${pins("buy")}</div>
    <div class="ends"><span>${fmt(lo)}</span><span>${fmt(hi)}</span></div>
    <div class="legend">
      <span class="swatch" style="background:var(--brass)"></span>on sale
      &nbsp;&nbsp;<span class="swatch" style="background:var(--patina)"></span>wanted
      ${log ? "&nbsp;&nbsp;log scale" : ""}</div>
  </div>`;
}

function detailRow(it, span) {
  const col = (rows, title, cls) => `
    <div><h3>${title} <span>${rows.length}</span></h3>
    ${rows.length ? `<table>${rows.map(l => `<tr>
      <td class="num ${cls}">${fmt(l.price)}</td>
      <td class="num sm">${qty(l.qty)}</td>
      <td>${botLink(l.bot)}</td>
      <td class="sm">${esc(l.loc)}</td></tr>`).join("")}</table>`
      : `<div class="sm">Nobody.</div>`}</div>`;
  const s = it.best.sell, b = it.best.buy;
  let verdict;
  if (s && b) {
    const d = b.price - s.price;
    verdict = d > 0
      ? `Buy at <b class="brass">${fmt(s.price)}</b> from ${botLink(s.bot)},
         sell at <b class="patina">${fmt(b.price)}</b> to ${botLink(b.bot)}
         — <b>${fmt(d)}</b> a unit${it.units === Infinity
           ? ", and the buyer takes any amount."
           : `, <b>${fmt(it.total)}</b> across ${qty(it.units)}.`}`
      : `Cheapest is <b class="brass">${fmt(s.price)}</b>, best buyer pays
         <b class="patina">${fmt(b.price)}</b>. No money in it.`;
    if (d > 0 && b.emu === 0)
      verdict += ` <span class="t-sea">${esc(b.bot)} has no EMU free,
        so it may not be able to take any.</span>`;
  } else if (s) { verdict = "On sale, nobody buying."; }
  else if (b)   { verdict = "Wanted, nobody selling."; }
  else          { verdict = "Nothing live."; }
  return `<tr class="detail"><td colspan="${span}"><div class="dwrap">
    <div class="verdict">${verdict}</div>
    ${axis(it)}
    <div class="cols">
      ${col(it.sell, "On sale", "brass")}
      ${col(it.buy, "Wanted", "patina")}
    </div></div></td></tr>`;
}

const isOpen = (it, n, q) => openIds.has(it.id) || (q && n <= AUTO_OPEN_UPTO);

/* rendering ---------------------------------------------------------- */
function head(cols) {
  return "<thead><tr>" + cols.map(c =>
    `<th class="${c.num ? "num " : ""}${c.hide ? "hide-sm" : ""}" data-k="${
      c.k || ""}">${c.t}${sortKey === c.k && c.k
        ? (sortDir > 0 ? " ▲" : " ▼") : ""}</th>`).join("")
    + "</tr></thead>";
}
function sortRows(rows, def) {
  const k = sortKey || def, dir = sortKey ? sortDir : 1;
  return rows.sort((a, b) => {
    const x = typeof k === "function" ? k(a) : a[k];
    const y = typeof k === "function" ? k(b) : b[k];
    if (typeof x === "string" || typeof y === "string")
      return dir * String(x ?? "").localeCompare(String(y ?? ""));
    return dir * ((x ?? -Infinity) < (y ?? -Infinity) ? 1 : -1);
  });
}
function wireSort() {
  document.querySelectorAll("th[data-k]").forEach(th => {
    if (!th.dataset.k) return;
    th.onclick = () => {
      const k = th.dataset.k;
      if (sortKey === k) sortDir *= -1; else { sortKey = k; sortDir = 1; }
      render();
    };
  });
}
function wireRows() {
  document.querySelectorAll("tr.item").forEach(tr => tr.onclick = () => {
    const id = +tr.dataset.id;
    openIds.has(id) ? openIds.delete(id) : openIds.add(id);
    render();
  });
}
function matches(it, q) {
  if (!q) return true;
  if (it.name.toLowerCase().includes(q)) return true;
  return [...it.sell, ...it.buy].some(l =>
    l.bot.toLowerCase().includes(q) || (l.loc || "").toLowerCase().includes(q));
}

function render() {
  const q = document.getElementById("q").value.trim().toLowerCase();
  const view = document.getElementById("view");
  const count = document.getElementById("count");
  document.getElementById("walkwrap").style.display =
    tab === "profit" ? "flex" : "none";
  document.getElementById("modewrap").style.display =
    tab === "craft" ? "flex" : "none";
  document.getElementById("viewwrap").style.display =
    tab === "players" && !focusPlayer ? "flex" : "none";
  document.getElementById("skillpick").style.display =
    tab === "players" && !focusPlayer && pview === "skills"
      ? "inline-block" : "none";

  if (tab === "bots" && focusBot) return renderBot(view, count);
  if (tab === "bots")   return renderBotList(view, count, q);
  if (tab === "craft")  return renderCraft(view, count, q);
  if (tab === "players") return renderPlayers(view, count, q);

  let items = DATA.items.filter(it => matches(it, q));
  if (tab === "profit") {
    items = items.filter(it => it.total > 0);
    if (walkableOnly) items = items.filter(it => it.trip !== "sea");
  }
  if (!items.length) {
    count.textContent = "";
    view.innerHTML = `<div class="empty">${q
      ? "Nothing matches that."
      : "No trades in profit right now."}</div>`;
    return;
  }
  return tab === "profit" ? renderProfit(view, count, items, q)
                          : renderMarket(view, count, items, q);
}

function renderMarket(view, count, items, q) {
  items = sortRows(items, "name");
  count.textContent = `${items.length} item${items.length === 1 ? "" : "s"}`;
  view.innerHTML = `<div class="scroller"><table>${head([
    { t: "Item", k: "name" },
    { t: "Cheapest", k: it => it.best.sell?.price, num: 1 },
    { t: "Seller" },
    { t: "Stock", k: it => cap(it.best.sell?.qty ?? 0), num: 1, hide: 1 },
    { t: "Best buyer", k: it => it.best.buy?.price, num: 1 },
    { t: "Buyer" },
    { t: "Offers", k: it => it.sell.length + it.buy.length, num: 1, hide: 1 },
  ])}<tbody>${items.map(it => {
    const s = it.best.sell, b = it.best.buy;
    const who = l => l ? `${botLink(l.bot)}<br><span class="sm">${
      esc(l.map || "")}</span>` : "–";
    return `<tr class="item ${isOpen(it, items.length, q) ? "open" : ""}"
        data-id="${it.id}">
      <td><div class="nm">${icon(it)}<span>${esc(it.name)}</span></div></td>
      <td class="num brass">${s ? fmt(s.price) : "–"}</td>
      <td>${who(s)}</td>
      <td class="num sm hide-sm">${s ? qty(s.qty) : "–"}</td>
      <td class="num patina">${b ? fmt(b.price) : "–"}</td>
      <td>${who(b)}</td>
      <td class="num sm hide-sm">${it.sell.length + it.buy.length}</td></tr>
      ${isOpen(it, items.length, q) ? detailRow(it, 7) : ""}`;
  }).join("")}</tbody></table></div>`;
  wireRows(); wireSort(); wireBotLinks();
}

function renderProfit(view, count, items, q) {
  items = sortRows(items, "total");
  count.textContent = `${items.length} trade${items.length === 1 ? "" : "s"} in profit`
    + (walkableOnly ? ", boat trips hidden" : "");
  view.innerHTML = `<div class="scroller"><table>${head([
    { t: "Item", k: "name" },
    { t: "Buy", k: it => it.best.sell.price, num: 1 },
    { t: "From" },
    { t: "Sell", k: it => it.best.buy.price, num: 1 },
    { t: "To" },
    { t: "Margin", k: "unit", num: 1, hide: 1 },
    { t: "Units", k: "units", num: 1, hide: 1 },
    { t: "Gold", k: "total", num: 1 },
    { t: "Trip", k: "trip" },
  ])}<tbody>${items.map(it => `
    <tr class="item ${isOpen(it, items.length, q) ? "open" : ""}"
        data-id="${it.id}">
      <td><div class="nm">${icon(it)}<span>${esc(it.name)}</span></div></td>
      <td class="num brass">${fmt(it.best.sell.price)}</td>
      <td>${botLink(it.best.sell.bot)}<br><span class="sm">${
        esc(it.best.sell.map || "")}</span></td>
      <td class="num patina">${fmt(it.best.buy.price)}</td>
      <td>${botLink(it.best.buy.bot)}<br><span class="sm">${
        esc(it.best.buy.map || "")}</span></td>
      <td class="num sm hide-sm">${fmt(it.unit)}</td>
      <td class="num sm hide-sm">${it.units === Infinity ? "no limit"
        : it.units.toLocaleString("en-GB")}</td>
      <td class="num brass"><b>${fmt(it.total)}</b></td>
      <td><span class="trip ${TRIP[it.trip].cls}">${TRIP[it.trip].label}</span></td>
    </tr>${isOpen(it, items.length, q) ? detailRow(it, 9) : ""}`).join("")}
    </tbody></table></div>`;
  wireRows(); wireSort(); wireBotLinks();
}

/* players -------------------------------------------------------------
   About a third of players have privacy mode on, so every table here is
   of players with public stats rather than of the game. Say so.         */
const PLAYERS = DATA.players || [];
const PUBLIC = PLAYERS.filter(p => !p.private);
const SKILLS = (DATA.skills || []).slice().sort((a, b) =>
  a === "Overall" ? -1 : b === "Overall" ? 1 : a.localeCompare(b));
if (!pskill) pskill = SKILLS.includes("Overall") ? "Overall" : SKILLS[0];

const pickEl = document.getElementById("skillpick");
if (pickEl && SKILLS.length) {
  pickEl.innerHTML = SKILLS.map(s =>
    `<option value="${esc(s)}">${esc(s)}</option>`).join("");
  pickEl.value = pskill;
  pickEl.onchange = () => { pskill = pickEl.value; render(); };
}
document.querySelectorAll("#viewwrap button").forEach(b => b.onclick = () => {
  document.querySelectorAll("#viewwrap button").forEach(x =>
    x.classList.remove("on"));
  b.classList.add("on"); pview = b.dataset.pview; focusPlayer = null; render();
});
const playerLink = n =>
  `<a class="lnk" data-player="${esc(n)}">${esc(n)}</a>`;
const wirePlayerLinks = () =>
  document.querySelectorAll("a.lnk[data-player]").forEach(a =>
    a.onclick = e => {
      e.stopPropagation(); focusPlayer = a.dataset.player;
      tab = "players"; window.scrollTo({ top: 0 }); render();
    });

const caveat = `<div class="caveat">${
  DATA.meta.playerCount} players with public stats. ${
  DATA.meta.privateCount} have privacy mode on, so they are not shown
  here \u2014 any of them could be top of this table.</div>`;

function renderPlayers(view, count, q) {
  if (!PLAYERS.length) {
    count.textContent = "";
    view.innerHTML = `<div class="empty">No player data yet.<br>
      <span class="sm">Run <code>python el_players.py seed</code> then
      <code>scrape</code>, and rebuild.</span></div>`;
    return;
  }
  if (focusPlayer) return renderOnePlayer(view, count);
  if (pview === "pk") return renderPk(view, count, q);
  if (pview === "movers") return renderMovers(view, count, q);

  const rows = PUBLIC
    .filter(p => p.stats[pskill] != null)
    .filter(p => !q || p.name.toLowerCase().includes(q))
    .map(p => ({ p, lvl: p.stats[pskill].v }))
    .sort((a, b) => b.lvl - a.lvl || a.p.name.localeCompare(b.p.name));
  if (!rows.length) {
    count.textContent = "";
    view.innerHTML = `<div class="empty">Nothing matches that.</div>`;
    return;
  }
  count.textContent = `${rows.length} players ranked by ${pskill}`;
  let rank = 0, last = null;
  view.innerHTML = caveat + `<div class="scroller"><table>
    <thead><tr><th class="num">#</th><th>Player</th>
    <th class="num">${esc(pskill)}</th><th class="num hide-sm">Overall</th>
    <th class="hide-sm">Best at</th></tr></thead><tbody>
    ${rows.map(({ p, lvl }, i) => {
      if (lvl !== last) { rank = i + 1; last = lvl; }
      const best = Object.entries(p.stats)
        .filter(([s, v]) => v.k === "skill" && s !== "Overall")
        .sort((a, b) => b[1].v - a[1].v)[0];
      return `<tr>
        <td class="num rank">${rank}</td>
        <td>${playerLink(p.name)}</td>
        <td class="num brass">${lvl}</td>
        <td class="num sm hide-sm">${p.overall ?? "\u2013"}</td>
        <td class="sm hide-sm">${best ? esc(best[0]) + " " + best[1].v : ""}</td>
      </tr>`;
    }).join("")}</tbody></table></div>`;
  wirePlayerLinks();
}

function renderPk(view, count, q) {
  const rows = PUBLIC.filter(p => p.pk && p.pk.f > 0)
    .filter(p => !q || p.name.toLowerCase().includes(q))
    .sort((a, b) => b.pk.score - a.pk.score);
  if (!rows.length) {
    count.textContent = "";
    view.innerHTML = `<div class="empty">No PK data yet.</div>`;
    return;
  }
  const anyMovement = rows.some(p => p.pk.wasF != null);
  count.textContent = `${rows.length} players with PK history`;
  view.innerHTML = caveat + `<div class="scroller"><table>
    <thead><tr><th class="num">#</th><th>Player</th><th class="num">Score</th>
    <th class="num">Fights</th><th class="num hide-sm">Won</th>
    <th class="num hide-sm">Lost</th><th class="num">Win rate</th>
    <th class="num">This week</th></tr></thead><tbody>
    ${rows.map((p, i) => {
      const k = p.pk, rate = k.f ? k.w / k.f * 100 : 0;
      const df = k.wasF != null ? k.f - k.wasF : null;
      const dw = k.wasW != null ? k.w - k.wasW : null;
      return `<tr>
        <td class="num rank">${i + 1}</td>
        <td>${playerLink(p.name)}</td>
        <td class="num brass">${k.score.toFixed(2)}</td>
        <td class="num">${k.f.toLocaleString("en-GB")}</td>
        <td class="num sm hide-sm">${k.w.toLocaleString("en-GB")}</td>
        <td class="num sm hide-sm">${k.l.toLocaleString("en-GB")}</td>
        <td class="num ${rate >= 80 ? "patina" : rate < 50 ? "t-sea" : ""}">${
          rate.toFixed(0)}%</td>
        <td class="num ${df ? "patina" : "sm"}">${
          df == null ? "\u2013" : df === 0 ? "\u2013"
          : `+${df} fight${df === 1 ? "" : "s"}${dw ? `, ${dw} won` : ""}`}</td>
      </tr>`;
    }).join("")}</tbody></table></div>`
    + (anyMovement ? "" : `<div class="caveat" style="margin-top:14px">
       Weekly movement appears once there are readings from two different
       days.</div>`);
  wirePlayerLinks();
}

function renderMovers(view, count, q) {
  const rows = (DATA.movers || [])
    .filter(m => !q || m.name.toLowerCase().includes(q)
                    || m.stat.toLowerCase().includes(q));
  if (!rows.length) {
    count.textContent = "";
    view.innerHTML = `<div class="empty">No level-ups recorded yet.<br>
      <span class="sm">The first appear once players have been read on two
      different days.</span></div>`;
    return;
  }
  count.textContent = `${rows.length} level-ups`;
  view.innerHTML = caveat + `<div class="scroller"><table>
    <thead><tr><th>When</th><th>Player</th><th>Skill</th>
    <th class="num">Level</th><th class="num hide-sm">Gained</th>
    </tr></thead><tbody>
    ${rows.map(m => `<tr>
      <td class="sm">${esc(m.at)}</td>
      <td>${playerLink(m.name)}</td>
      <td>${esc(m.stat)}</td>
      <td class="num brass">${m.now}</td>
      <td class="num sm hide-sm">${m.was != null
        ? "+" + (m.now - m.was) : "\u2013"}</td></tr>`).join("")}
    </tbody></table></div>`;
  wirePlayerLinks();
}

function renderOnePlayer(view, count) {
  const p = PLAYERS.find(x => x.name === focusPlayer);
  count.textContent = "";
  if (!p) { view.innerHTML = `<div class="empty">Not followed.</div>`; return; }

  const group = kind => Object.entries(p.stats)
    .filter(([, v]) => v.k === kind)
    .sort((a, b) => b[1].v - a[1].v);

  const rankIn = skill => {
    const better = PUBLIC.filter(x => x.stats[skill]
      && x.stats[skill].v > p.stats[skill].v).length;
    return better + 1;
  };

  const table = (rows, title, ranked) => !rows.length ? "" : `
    <div><h3>${title}</h3><table>${rows.map(([stat, v]) => `<tr>
      <td>${esc(stat)}</td><td class="num brass">${v.v}</td>
      ${ranked ? `<td class="num sm">#${rankIn(stat)}</td>` : ""}
    </tr>`).join("")}</table></div>`;

  const mine = (DATA.movers || []).filter(m => m.name === p.name).slice(0, 12);

  view.innerHTML = `
    <div class="bothead">
      <button class="back">All players</button>
      <h2>${esc(p.name)}</h2>
      <span class="where">${p.overall ? "overall " + p.overall : ""}${
        p.private ? " \u00b7 privacy mode on" : ""}</span>
    </div>
    ${p.private ? `<div class="caveat">This player has hidden their stats.
      Only their achievements are public.</div>` : ""}
    <div class="cols">
      ${table(group("skill"), "Skills", true)}
      <div>
        ${table(group("attribute"), "Attributes", false)
          .replace("<div>", "").replace(/<\/div>$/, "")}
        ${p.pk ? `<h3 style="margin-top:18px">PK</h3><table>
          <tr><td>Score</td><td class="num brass">${p.pk.score.toFixed(2)}</td></tr>
          <tr><td>Fights</td><td class="num">${p.pk.f}</td></tr>
          <tr><td>Won</td><td class="num patina">${p.pk.w}</td></tr>
          <tr><td>Lost</td><td class="num">${p.pk.l}</td></tr>
          <tr><td>Win rate</td><td class="num">${
            (p.pk.w / p.pk.f * 100).toFixed(0)}%</td></tr></table>` : ""}
      </div>
      ${table(group("cross"), "Cross attributes", false)}
    </div>
    ${mine.length ? `<h3 style="margin-top:24px">Recent levels</h3>
      <table style="max-width:420px">${mine.map(m => `<tr>
        <td class="sm">${esc(m.at)}</td><td>${esc(m.stat)}</td>
        <td class="num brass">${m.now}</td></tr>`).join("")}</table>` : ""}
    ${p.ach ? `<h3 style="margin-top:24px">Achievements</h3>
      <div class="chips">${p.ach.split(/\s{2,}/).filter(Boolean)
        .map(a => `<span class="chip">${esc(a.trim())}</span>`).join("")}</div>`
      : ""}`;
  view.querySelector(".back").onclick = () => { focusPlayer = null; render(); };
}

function renderCraft(view, count, q) {
  if (!DATA.recipes || !DATA.recipes.length) {
    count.textContent = "";
    view.innerHTML = `<div class="empty">No recipes imported yet.<br>
      <span class="sm">Run <code>python el_recipes.py import</code>
      and rebuild.</span></div>`;
    return;
  }
  let rows = DATA.recipes
    .filter(r => !q || r.item.toLowerCase().includes(q)
              || (r.skill || "").toLowerCase().includes(q)
              || r.ings.some(g => g.n.toLowerCase().includes(q)))
    .map(r => ({ r, c: cost(r, craftMode) }))
    .filter(x => !x.c.missing.length);

  if (!rows.length) {
    count.textContent = "";
    view.innerHTML = `<div class="empty">${q ? "Nothing matches that."
      : "Nothing can be priced yet."}</div>`;
    return;
  }

  const k = sortKey, dir = sortKey ? sortDir : 1;
  const get = {
    item: x => x.r.item, skill: x => x.r.skill, level: x => x.r.level,
    cost: x => x.c.cost, sells: x => x.c.sells, profit: x => x.c.profit,
    margin: x => x.c.margin, exp: x => x.r.exp, perXp: x => x.c.perXp,
  }[k] || (x => x.c.profit);
  rows.sort((a, b) => {
    const x = get(a), y = get(b);
    if (typeof x === "string" || typeof y === "string")
      return dir * String(x ?? "").localeCompare(String(y ?? ""));
    return dir * ((x ?? -Infinity) < (y ?? -Infinity) ? 1 : -1);
  });

  const inProfit = rows.filter(x => x.c.profit > 0).length;
  count.textContent = `${rows.length} recipes priceable, ${inProfit} in profit`
    + ` \u00b7 ${DATA.meta.recipeCount} known`;

  view.innerHTML = `<div class="scroller"><table>${head([
    { t: "Item", k: "item" }, { t: "Skill", k: "skill" },
    { t: "Lvl", k: "level", num: 1, hide: 1 },
    { t: "Cost", k: "cost", num: 1 },
    { t: "Sells for", k: "sells", num: 1 },
    { t: "Profit", k: "profit", num: 1 },
    { t: "Margin", k: "margin", num: 1, hide: 1 },
    { t: "Exp", k: "exp", num: 1, hide: 1 },
    { t: "Gold per xp", k: "perXp", num: 1 },
  ])}<tbody>${rows.map(({ r, c }, i) => `
    <tr class="item ${openIds.has("c" + i) ? "open" : ""}" data-craft="${i}">
      <td><div class="nm"><span>${esc(r.item)}${c.gathered
        ? ` <span class="gathered" title="uses gathered materials">\u2726</span>`
        : ""}${c.gate ? ` <span class="gate" title="needs nexus ${
        c.gate} to gather the materials">nexus ${c.gate}</span>` : ""
        }</span></div></td>
      <td class="sm">${esc(r.skill)}</td>
      <td class="num sm hide-sm">${r.level ?? "\u2013"}</td>
      <td class="num">${fmt(c.cost)}</td>
      <td class="num patina">${fmt(c.sells)}${c.where === "vendor"
        ? ` <span class="sm">shop</span>` : ""}</td>
      <td class="num ${c.profit > 0 ? "brass" : "sm"}">${fmt(c.profit)}</td>
      <td class="num sm hide-sm">${c.margin == null ? "\u2013"
        : c.margin.toFixed(0) + "%"}</td>
      <td class="num sm hide-sm">${r.exp ? r.exp.toLocaleString("en-GB") : "\u2013"}</td>
      <td class="num ${c.perXp != null && c.perXp < 0 ? "patina" : ""}">${
        c.perXp == null ? "\u2013" : c.perXp.toFixed(2)}</td>
    </tr>${openIds.has("c" + i) ? craftDetail(r, c) : ""}`).join("")}
    </tbody></table></div>`;

  document.querySelectorAll("tr[data-craft]").forEach(tr => tr.onclick = () => {
    const id = "c" + tr.dataset.craft;
    openIds.has(id) ? openIds.delete(id) : openIds.add(id);
    render();
  });
  wireSort(); wireBotLinks();
}

function craftDetail(r, c) {
  const rows = c.lines.map(l => {
    let desc, each;
    if (l.how === "buy") {
      desc = `${esc(l.n)} <span class="sm">from ${botLink(l.from)}</span>`;
      each = fmt(l.each);
    } else if (l.how === "gather") {
      const needs = [
        l.lvl ? "level " + Math.round(l.lvl) : null,
        l.tool || null,
        l.nexus ? "nexus " + Math.round(l.nexus) : null,
      ].filter(Boolean).join(", ");
      desc = `${esc(l.n)} <span class="gathered">gather${
        needs ? " \u2014 " + esc(needs) : ""}</span>`;
      each = l.each ? fmt(l.each) : "\u2013";
    } else {
      desc = `${esc(l.n)} <span class="sm">nobody sells it, you cannot gather it</span>`;
      each = "\u2013";
    }
    return `<div class="amt">${l.a}\u00d7</div><div>${desc}</div>
      <div class="each sm">${each}</div>
      <div class="sub">${l.each != null ? fmt(l.each * l.a) : "\u2013"}</div>`;
  }).join("");
  const sold = c.where === "bot" && c.who ? ` to ${botLink(c.who)}`
    : c.where === "vendor" ? " to a shop" : "";
  return `<tr class="detail"><td colspan="9"><div class="dwrap">
    <div class="ing">
      ${rows}
      <div class="rule"></div>
      <div></div><div class="sm">cost to make one</div>
      <div></div><div class="sub">${fmt(c.cost)}</div>
      <div></div><div class="sm">sells for${sold}</div>
      <div></div><div class="sub patina">${fmt(c.sells)}</div>
      <div></div><div>profit</div>
      <div></div><div class="sub ${c.profit > 0 ? "brass" : ""}">${fmt(c.profit)}</div>
      ${r.exp ? `<div></div><div class="sm">${r.exp.toLocaleString("en-GB")}
        experience, so ${c.perXp < 0 ? "you earn" : "it costs"}
        ${fmt(Math.abs(c.perXp))} a point</div><div></div><div></div>` : ""}
    </div>
    ${r.tool ? `<div class="sm" style="margin-top:12px">Needs ${esc(r.tool)}${
      r.food ? `, ${Math.round(r.food)} food` : ""}</div>` : ""}
  </div></td></tr>`;
}

function renderBotList(view, count, q) {
  let rows = DATA.bots.filter(b => !q ||
    b.name.toLowerCase().includes(q) ||
    (b.location || "").toLowerCase().includes(q) ||
    (b.owner || "").toLowerCase().includes(q));
  rows = sortRows(rows, "name");
  count.textContent = `${rows.length} bot${rows.length === 1 ? "" : "s"}`;
  view.innerHTML = `<div class="scroller"><table>${head([
    { t: "Bot", k: "name" }, { t: "Where", k: "location" },
    { t: "Land", k: "continent", hide: 1 }, { t: "Owner", k: "owner", hide: 1 },
    { t: "On sale", k: "sells", num: 1 }, { t: "Wanted", k: "buys", num: 1 },
    { t: "Slots", k: "slots", num: 1, hide: 1 },
    { t: "EMU free", k: "emu", num: 1, hide: 1 },
  ])}<tbody>${rows.map(b => `<tr>
    <td>${botLink(b.name)}</td>
    <td class="sm">${esc(b.location || "–")}${b.map_x != null
      ? ` [${b.map_x},${b.map_y}]` : ""}</td>
    <td class="sm hide-sm">${esc(b.continent || "–")}</td>
    <td class="sm hide-sm">${esc(b.owner || "–")}</td>
    <td class="num">${b.sells}</td>
    <td class="num">${b.buys}</td>
    <td class="num sm hide-sm">${b.slots ?? "\u2013"}</td>
    <td class="num hide-sm ${b.emu === 0 ? "t-sea" : "sm"}">${
      b.emu == null ? "\u2013" : b.emu.toLocaleString("en-GB")}</td></tr>`
    ).join("")}</tbody></table></div>`;
  wireSort(); wireBotLinks();
}

function renderBot(view, count) {
  const B = BOTS[focusBot], i = B.info;
  const where = (i.location || "unknown spot") +
    (i.map_x != null ? ` [${i.map_x},${i.map_y}]` : "");
  const room = i.emu == null ? ""
    : `, ${i.slots} slot${i.slots === 1 ? "" : "s"} and
       ${i.emu.toLocaleString("en-GB")} EMU free`;
  const col = (rows, title, cls, other) => `
    <div><h3>${title} <span>${rows.length}</span></h3>
    ${rows.length ? `<div class="scroller"><table><thead><tr>
      <th>Item</th><th class="num">Price</th><th class="num">Qty</th>
      <th class="num">Elsewhere</th></tr></thead><tbody>
      ${rows.slice().sort((a, b2) =>
          b2.price * Math.min(cap(b2.qty), 1e6)
        - a.price * Math.min(cap(a.qty), 1e6)).map(r => {
        const alt = r.item.best[other];
        const beats = alt && alt.bot !== focusBot &&
          (cls === "brass" ? alt.price > r.price : alt.price < r.price);
        return `<tr>
          <td><div class="nm">${icon(r.item)}<span>${esc(r.item.name)}</span></div></td>
          <td class="num ${cls}">${fmt(r.price)}</td>
          <td class="num sm">${qty(r.qty)}</td>
          <td class="num ${beats ? "patina" : "sm"}">${
            alt && alt.bot !== focusBot
              ? fmt(alt.price) + " " + botLink(alt.bot) : "–"}</td></tr>`;
      }).join("")}</tbody></table></div>`
      : `<div class="sm">Nothing.</div>`}</div>`;
  view.innerHTML = `
    <div class="bothead">
      <button class="back">All bots</button>
      <h2>${esc(focusBot)}</h2>
      <span class="where">${esc(where)}${
        i.owner ? `, run by ${esc(i.owner)}` : ""}${room}</span>
    </div>
    <div class="cols">
      ${col(B.sell, "On sale", "brass", "buy")}
      ${col(B.buy, "Wanted", "patina", "sell")}
    </div>`;
  count.textContent = "";
  view.querySelector(".back").onclick = () => { focusBot = null; render(); };
  wireBotLinks();
}

render();
</script>
</body>
</html>
"""


def main():
    p = argparse.ArgumentParser(description="Build the EL Market page")
    p.add_argument("--db", default=DB_PATH)
    p.add_argument("--out", default=OUT_PATH)
    p.add_argument("--open", action="store_true", help="open it when done")
    a = p.parse_args()

    data = load(a.db)
    html = HTML.replace("__DATA__", json.dumps(data, separators=(",", ":")))

    out_dir = os.path.dirname(os.path.abspath(a.out))
    os.makedirs(out_dir, exist_ok=True)
    with open(a.out, "w", encoding="utf-8") as f:
        f.write(html)

    m = data["meta"]
    print(f"wrote {a.out} ({os.path.getsize(a.out)/1024:.0f} KB)")
    print(f"  {m['botCount']} bots, {m['itemCount']} items, "
          f"{m['listingCount']} offers, {m['runs']} scrapes so far")
    if m["unknownMaps"]:
        print("  maps not placed on a continent: "
              + ", ".join(m["unknownMaps"]))

    if a.open:
        webbrowser.open("file://" + os.path.abspath(a.out))


if __name__ == "__main__":
    main()
