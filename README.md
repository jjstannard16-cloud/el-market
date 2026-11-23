# EL Market

Price tracking for [Eternal Lands](http://www.eternal-lands.com) trade bots.

Every hour this reads all the bots hosted at
[bots.el-services.net](https://bots.el-services.net/), records what each one is
buying and selling, and rebuilds a page showing where things are cheapest, who
pays most, and which trades are worth the walk.

The point is history. The bot pages tell you today's price; nothing tells you
last week's. This does, once it has been running a while.

## What's here

| File | What it does |
| --- | --- |
| `el_bots.py` | Reads every bot page and stores the results in `el_bots.db` |
| `el_site.py` | Turns that database into `public/index.html` |
| `el_recipes.py` | Imports crafting recipes and harvestables from the EL wiki |
| `el_players.py` | Reads player levels and PK figures from the official site |
| `guild.txt` | Extra players to follow, beyond the top 200 |
| `overrides.json` | Corrections to wiki data, from people who actually play |
| `el_bots.db` | SQLite database — current listings plus price history |
| `public/index.html` | The page itself, rebuilt on every scrape |
| `.github/workflows/scrape.yml` | Runs the scrape hourly |
| `.github/workflows/recipes.yml` | Refreshes recipes from the wiki weekly |
| `.github/workflows/players.yml` | Reads player stats daily |

## Running it yourself

```bash
pip install requests beautifulsoup4 lxml

python el_bots.py scrape          # read every bot
python el_site.py --open          # build the page and open it
```

Other things the scraper can tell you from the command line:

```bash
python el_bots.py report cheapest          # cheapest seller for every item
python el_bots.py report spread            # trades currently in profit
python el_bots.py report item "silver ore" # one item, every bot
python el_bots.py report bots              # every bot, with free capacity
```

Recipes come from the wiki separately:

```bash
python el_recipes.py import                # 469 recipes, 67 harvestables
python el_recipes.py profit                # what is worth making right now
python el_recipes.py xp                    # cheapest experience per skill
python el_recipes.py recipe "steel bar"    # one recipe, fully costed
```

## Players

```bash
python el_players.py seed            # who to follow: top 200 plus guild.txt
python el_players.py scrape          # read their pages
python el_players.py top tailoring   # leaderboard with real levels
python el_players.py movers          # who levelled recently
python el_players.py pk              # PK table with weekly movement
```

top.el-db.com gives a rank per skill and ties share one, so thirty players
can all show as "1". The official player page gives actual levels, so that
is where the numbers come from.

**About a third of players have privacy mode on.** Their stats are hidden,
which is their choice: they are recorded as private, skipped on later
reads, and re-checked weekly in case they change their mind. Any
leaderboard here is therefore of players with public stats, not of the
game, and should say so wherever it is shown.

## What a craft actually costs

An ingredient you gather is not free. If a bot pays 1,100 for an ore, using
one in a craft costs you that sale. So by default gathered materials are
valued at what bots pay for them, which is the number that tells you whether
crafting beats selling the raw materials. `--mode free` ignores that and
`--mode buy` refuses to count gathered materials at all.

Some materials cannot be gathered without a tool, a nexus level, or both.
Those are shown against the recipe, because a 2,000% margin means little if
it needs nexus 6.

The wiki is the source for all of this, and it has gaps. `overrides.json`
is where corrections go, and they win over whatever the wiki says.

## How the data is stored

`listing` holds current state, one row per bot, item and side. `price_history`
only gains a row when a price actually changes, so the database stays small
even after years of hourly readings. Quantity is not history-tracked — it moves
with every trade and nobody queries it.

Quantities of `-1` mean the bot printed "NO LIMIT".

## Being a good neighbour

The scraper waits a second between bot pages and identifies itself in its
user agent. Please keep both if you fork this.

Item artwork is currently loaded from bots.el-services.net. If this becomes
widely used, those images should be mirrored rather than hotlinked.

Not affiliated with Eternal Lands or with EL Services.
