#!/usr/bin/env python3
"""
el_images.py - keep a local copy of the item artwork.

The page showed around 550 item icons loaded straight from
bots.el-services.net, which meant every visitor cost them bandwidth.
This downloads each one once into public/img/ so the site serves its own.

    python el_images.py            # fetch anything missing
    python el_images.py --check    # say what is missing, download nothing

Only images for items already in the database are fetched, one at a time
with a pause, and an image already on disk is never fetched again.
"""

import argparse
import os
import sqlite3
import sys
import time

try:
    import requests
except ImportError:
    sys.exit("Run: pip install requests")

DB_PATH = "el_bots.db"
OUT_DIR = os.path.join("public", "img")
BASE = "https://bots.el-services.net/images/"
UA = "EL-HQ/0.1 (Eternal Lands community project; contact: stann in-game)"
PAUSE = 0.3
TIMEOUT = 20
MAX_BYTES = 2_000_000


def wanted(db_path):
    if not os.path.exists(db_path):
        sys.exit(f"No database at {db_path}")
    con = sqlite3.connect(db_path)
    names = [r[0] for r in con.execute(
        "SELECT DISTINCT image FROM item WHERE image IS NOT NULL")]
    con.close()
    # Only plain file names, so nothing can write outside the folder.
    return sorted(n for n in names
                  if n and "/" not in n and "\\" not in n and ".." not in n)


def main():
    ap = argparse.ArgumentParser(description="Mirror the item artwork")
    ap.add_argument("--db", default=DB_PATH)
    ap.add_argument("--out", default=OUT_DIR)
    ap.add_argument("--check", action="store_true",
                    help="report what is missing without downloading")
    ap.add_argument("--delay", type=float, default=PAUSE)
    a = ap.parse_args()

    names = wanted(a.db)
    os.makedirs(a.out, exist_ok=True)
    have = set(os.listdir(a.out))
    missing = [n for n in names if n not in have]

    print(f"{len(names)} images referenced, {len(names) - len(missing)} "
          f"already in {a.out}, {len(missing)} missing")
    if a.check or not missing:
        return

    s = requests.Session()
    s.headers.update({"User-Agent": UA})
    got = failed = 0
    for i, name in enumerate(missing, 1):
        try:
            r = s.get(BASE + name, timeout=TIMEOUT)
            r.raise_for_status()
            if not r.content or len(r.content) > MAX_BYTES:
                failed += 1
                continue
            if not r.headers.get("content-type", "").startswith("image/"):
                failed += 1
                continue
            with open(os.path.join(a.out, name), "wb") as f:
                f.write(r.content)
            got += 1
        except Exception as e:
            failed += 1
            if failed <= 3:
                print(f"  {name}: {e}")
        if i % 100 == 0:
            print(f"  {i}/{len(missing)}")
        time.sleep(a.delay)

    total = sum(os.path.getsize(os.path.join(a.out, f))
                for f in os.listdir(a.out))
    print(f"\ndownloaded {got}, failed {failed}; "
          f"{total / 1024:.0f} KB on disk")


if __name__ == "__main__":
    main()
