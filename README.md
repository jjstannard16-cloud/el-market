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
| `el_bots.db` | SQLite database — current listings plus price history |
| `public/index.html` | The page itself, rebuilt on every scrape |
| `.github/workflows/scrape.yml` | Runs the scrape hourly |

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
