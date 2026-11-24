#!/usr/bin/env python3
"""
el_creature_images.py - keep a local copy of the creature artwork.

The item icons are mirrored by el_images.py. Creatures had no picture at
all, so this finds one on the wiki for as many as it can, shrinks it and
writes it into public/img/c/ alongside a manifest the page reads.

    python el_creature_images.py              # fetch anything missing
    python el_creature_images.py --check      # say what is missing
    python el_creature_images.py --one Yeti   # try one creature, loudly

The wiki does not name these to one rule, so four shapes are tried in
turn and the first that exists wins:

    Creature <Name>.png     the portrait, what most of them have
    Creature <Name>.jpg     the same thing photographed instead
    Creature_<Name>.jpg     run together, as Creature_DesertChimeran.jpg
    <Name> 25px.png         the thumbnail off the index pages

The portraits are big - a Cyclops is 800x650 and over half a megabyte -
and the page shows them small, so each is shrunk to fit a box and saved
as JPEG. The 25px thumbnails are already tiny and are kept as they are.

Nothing is downloaded twice: a creature already in the manifest with its
file on disk is skipped, so a weekly run costs almost nothing.
"""

import argparse
import io
import json
import os
import re
import sys
import time

try:
    import requests
    from PIL import Image
except ImportError:
    sys.exit("Run: pip install requests pillow")

API = "https://el-wiki.holy-eternalland.de/api.php"
UA = {"User-Agent": "EL-HQ/0.1 (Eternal Lands community site; stann in-game)"}
IN_JSON = "creatures.json"
OUT_DIR = os.path.join("public", "img", "c")
MANIFEST = "creature_images.json"
BOX = (240, 240)
PAUSE = 0.3
TIMEOUT = 30
MAX_BYTES = 8_000_000
JPEG_QUALITY = 82


def slug(name):
    """A safe file name. Nothing here can escape the folder."""
    return re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-") or "x"


def candidates(name):
    """The names the wiki might be keeping this creature's picture under."""
    run = name.replace(" ", "")
    return [f"Creature {name}.png", f"Creature {name}.jpg",
            f"Creature_{run}.jpg", f"Creature_{run}.png",
            f"{name} 25px.png"]


def api(session, **params):
    params.setdefault("format", "json")
    params.setdefault("formatversion", 2)
    r = session.get(API, params=params, timeout=TIMEOUT)
    r.raise_for_status()
    return r.json()


def find_files(session, titles):
    """Ask for many file names at once; return the ones that exist."""
    found = {}
    for i in range(0, len(titles), 40):
        chunk = titles[i:i + 40]
        body = api(session, action="query", prop="imageinfo",
                   iiprop="url|size|mime",
                   titles="|".join(f"File:{t}" for t in chunk))
        for pg in body.get("query", {}).get("pages", []):
            if pg.get("missing"):
                continue
            for info in pg.get("imageinfo", []):
                found[pg["title"][len("File:"):]] = info
        time.sleep(PAUSE)
    return found


def shrink(raw, keep_as_is):
    """
    Fit the picture in a box and hand back JPEG bytes. A thumbnail that
    is already small is returned untouched, since re-encoding a 25 pixel
    image only makes it worse.
    """
    if keep_as_is:
        return raw, "png"
    im = Image.open(io.BytesIO(raw))
    if im.width <= BOX[0] and im.height <= BOX[1]:
        return raw, "png" if im.format == "PNG" else "jpg"
    # A transparent picture needs something behind it before it is JPEG.
    if im.mode in ("RGBA", "LA", "P"):
        im = im.convert("RGBA")
        flat = Image.new("RGB", im.size, (23, 32, 25))
        flat.paste(im, mask=im.split()[-1])
        im = flat
    else:
        im = im.convert("RGB")
    im.thumbnail(BOX, Image.LANCZOS)
    buf = io.BytesIO()
    im.save(buf, "JPEG", quality=JPEG_QUALITY, optimize=True)
    return buf.getvalue(), "jpg"


def main():
    ap = argparse.ArgumentParser(description="Mirror the creature artwork")
    ap.add_argument("--json", default=IN_JSON)
    ap.add_argument("--out", default=OUT_DIR)
    ap.add_argument("--manifest", default=MANIFEST)
    ap.add_argument("--check", action="store_true",
                    help="report what is missing without downloading")
    ap.add_argument("--one", help="try a single creature and say everything")
    a = ap.parse_args()

    names = [c["name"] for c in
             json.load(open(a.json, encoding="utf-8"))["creatures"]]
    if a.one:
        names = [a.one]
    os.makedirs(a.out, exist_ok=True)

    have = {}
    if os.path.exists(a.manifest):
        have = json.load(open(a.manifest, encoding="utf-8")).get("images", {})
    # A manifest entry whose file has gone is not an entry.
    have = {k: v for k, v in have.items()
            if os.path.exists(os.path.join(a.out, v["file"]))}

    todo = [n for n in names if n not in have] if not a.one else names
    print(f"{len(names)} creatures, {len(names) - len(todo)} already have a "
          f"picture, {len(todo)} to look for")
    if a.check or not todo:
        if not a.check:
            json.dump({"_comment": "Creature artwork mirrored from the EL "
                                   "wiki by el_creature_images.py.",
                       "images": have},
                      open(a.manifest, "w", encoding="utf-8"), indent=1,
                      sort_keys=True)
        return

    session = requests.Session()
    session.headers.update(UA)

    # One lookup for every name we might want, rather than one per try.
    wanted, owner = [], {}
    for n in todo:
        for c in candidates(n):
            wanted.append(c)
            owner.setdefault(c, n)
    print(f"asking the wiki about {len(wanted)} possible file names")
    found = find_files(session, wanted)
    print(f"{len(found)} of them exist")

    got = failed = 0
    for n in todo:
        pick = next((c for c in candidates(n) if c in found), None)
        if a.one:
            print(f"  candidates for {n}:")
            for c in candidates(n):
                print(f"    {'HIT ' if c in found else '    '}{c}")
        if not pick:
            continue
        info = found[pick]
        try:
            r = session.get(info["url"], timeout=TIMEOUT)
            r.raise_for_status()
            if not r.content or len(r.content) > MAX_BYTES:
                failed += 1
                continue
            if not r.headers.get("content-type", "").startswith("image/"):
                failed += 1
                continue
            data, kind = shrink(r.content, keep_as_is=pick.endswith("25px.png"))
            fname = f"{slug(n)}.{kind}"
            with open(os.path.join(a.out, fname), "wb") as f:
                f.write(data)
            have[n] = {"file": fname, "from": pick,
                       "small": pick.endswith("25px.png")}
            got += 1
        except Exception as e:
            failed += 1
            if failed <= 4:
                print(f"  {n} ({pick}): {e}")
        time.sleep(PAUSE)

    json.dump({"_comment": "Creature artwork mirrored from the EL wiki by "
                           "el_creature_images.py.",
               "images": have},
              open(a.manifest, "w", encoding="utf-8"), indent=1,
              sort_keys=True)

    big = sum(1 for v in have.values() if not v["small"])
    total = sum(os.path.getsize(os.path.join(a.out, f))
                for f in os.listdir(a.out))
    missing = [n for n in names if n not in have]
    print(f"\ndownloaded {got}, failed {failed}")
    print(f"{len(have)} creatures have a picture ({big} a portrait, "
          f"{len(have) - big} a thumbnail); {total / 1024:.0f} KB on disk")
    if missing:
        print(f"{len(missing)} still have none: {', '.join(missing[:12])}")


if __name__ == "__main__":
    main()
