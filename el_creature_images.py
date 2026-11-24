#!/usr/bin/env python3
"""
el_creature_images.py - keep a local copy of the creature artwork.

The item icons are mirrored by el_images.py. Creatures had no picture at
all, so this finds one on the wiki for as many as it can, shrinks it and
writes it into public/img/c/ alongside a manifest the page reads.

    python el_creature_images.py              # fetch anything missing
    python el_creature_images.py --check      # say what is missing
    python el_creature_images.py --one Yeti   # try one creature, loudly

Guessing file names did not work. The wiki has no single habit: a Yeti
is Creature Yeti.png, a Badaran is just Badaran.png, a Legionnaire Troll
is Legionnaire_Troll.PNG with the extension shouting, a Phantom Warrior
is Monster_phantomwarrior.png, and most of the rest are only the little
<Name> 25px.png off the index pages. Four guesses found 86 of 108 and
the misses were all spelling, not absence.

So nothing is guessed now. The whole file list - about 1,600 names - is
read once and matched on the name with its capitals, spaces, underscores
and extension taken off, which makes every one of those shapes the same
string. Matching is exact after that, so Small dragon does not catch
Small_Dragon_Scale.png.

A creature named like "Imp (fire damage)" is an invasion's version of an
ordinary Imp and has no page or picture of its own, so it falls back to
the plain Imp's and the manifest records that it did, because a picture
that is really of something else should say so.

The portraits are big - a Cyclops is 800x650 and over half a megabyte -
and the page shows them small, so each is shrunk to fit a box and saved
as JPEG. The 25px thumbnails are already tiny and are kept as they are.
A picture already on disk from the same file is never fetched twice.
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
PAUSE = 0.25
TIMEOUT = 30
MAX_BYTES = 8_000_000
JPEG_QUALITY = 82

EXT = re.compile(r"\.(png|jpe?g|gif|webp)$", re.I)
BRACKET = re.compile(r"\s*\(.*?\)\s*$")


def key(text):
    """Everything the wiki is inconsistent about, removed."""
    return re.sub(r"[^a-z0-9]", "", text.lower())


def slug(name):
    """A safe file name. Nothing here can escape the folder."""
    return re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-") or "x"


def api(session, **params):
    params.setdefault("format", "json")
    params.setdefault("formatversion", 2)
    r = session.get(API, params=params, timeout=TIMEOUT)
    r.raise_for_status()
    return r.json()


def every_image(session):
    """Every file on the wiki, keyed by its name with the noise removed."""
    out, cont = {}, None
    for _ in range(200):
        kw = {"action": "query", "list": "allimages", "ailimit": 500,
              "aiprop": "url|size", "aisort": "name"}
        if cont:
            kw["aicontinue"] = cont
        body = api(session, **kw)
        for im in body.get("query", {}).get("allimages", []):
            out.setdefault(key(EXT.sub("", im["name"])), im)
        cont = body.get("continue", {}).get("aicontinue")
        if not cont:
            break
        time.sleep(PAUSE)
    return out


def pick(files, name):
    """
    The best picture for one creature, or None.

    A portrait beats a thumbnail, and the creature's own beats the one
    belonging to the creature it is a variant of. Returns the file, how
    small it is, and whose picture it really is.
    """
    base = BRACKET.sub("", name).strip()
    for who in ([name] if base == name else [name, base]):
        k = key(who)
        for prefix, small in (("creature", False), ("monster", False),
                              ("", False), ("", True)):
            hit = files.get(prefix + k + ("25px" if small else ""))
            if hit:
                return hit, small, (None if who == name else who)
    return None, False, None


def shrink(raw, keep_as_is):
    """
    Fit the picture in a box and hand back the bytes to write. A
    thumbnail that is already small is returned untouched, since
    re-encoding a 25 pixel image only makes it worse.
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

    old = {}
    if os.path.exists(a.manifest):
        old = json.load(open(a.manifest, encoding="utf-8")).get("images", {})

    session = requests.Session()
    session.headers.update(UA)
    files = every_image(session)
    print(f"{len(files)} files on the wiki")

    have, got, failed, skipped = {}, 0, 0, 0
    for n in names:
        hit, small, stand_in = pick(files, n)
        if a.one:
            print(f"  {n}: {hit['name'] if hit else 'nothing matches'}"
                  f"{f' (really {stand_in})' if stand_in else ''}")
        if not hit:
            continue
        was = old.get(n)
        # Already mirrored from this very file, and still on disk.
        if (was and was.get("from") == hit["name"]
                and os.path.exists(os.path.join(a.out, was["file"]))):
            have[n] = was
            skipped += 1
            continue
        if a.check:
            continue
        try:
            r = session.get(hit["url"], timeout=TIMEOUT)
            r.raise_for_status()
            if not r.content or len(r.content) > MAX_BYTES:
                failed += 1
                continue
            if not r.headers.get("content-type", "").startswith("image/"):
                failed += 1
                continue
            data, kind = shrink(r.content, keep_as_is=small)
            fname = f"{slug(n)}.{kind}"
            with open(os.path.join(a.out, fname), "wb") as f:
                f.write(data)
            have[n] = {"file": fname, "from": hit["name"], "small": small}
            if stand_in:
                have[n]["of"] = stand_in
            got += 1
        except Exception as e:
            failed += 1
            if failed <= 4:
                print(f"  {n} ({hit['name']}): {e}")
        time.sleep(PAUSE)

    if a.check:
        missing = [n for n in names if n not in have and not pick(files, n)[0]]
        print(f"{len(have)} already mirrored, "
              f"{len(names) - len(have) - len(missing)} to fetch, "
              f"{len(missing)} with nothing on the wiki")
        return

    json.dump({"_comment": "Creature artwork mirrored from the EL wiki by "
                           "el_creature_images.py.",
               "images": have},
              open(a.manifest, "w", encoding="utf-8"), indent=1,
              sort_keys=True)

    big = sum(1 for v in have.values() if not v["small"])
    stood = sum(1 for v in have.values() if v.get("of"))
    total = sum(os.path.getsize(os.path.join(a.out, f))
                for f in os.listdir(a.out))
    missing = [n for n in names if n not in have]
    print(f"\ndownloaded {got}, kept {skipped}, failed {failed}")
    print(f"{len(have)} of {len(names)} creatures have a picture "
          f"({big} a portrait, {len(have) - big} a thumbnail, "
          f"{stood} borrowed from the creature they are a variant of); "
          f"{total / 1024:.0f} KB on disk")
    if missing:
        print(f"{len(missing)} have none at all: {', '.join(missing)}")


if __name__ == "__main__":
    main()
