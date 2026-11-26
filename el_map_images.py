#!/usr/bin/env python3
"""
el_map_images.py - keep a local copy of the map drawings.

Each map page carries a drawing of the map itself, named like
map_whitestone_0512px.png, and el_maps.py records which one. This
fetches them and shrinks them to something a page can load.

    python el_map_images.py           # fetch anything missing
    python el_map_images.py --check   # say what is missing

The file names come out of maps.json rather than being guessed, so
unlike the creatures there is nothing to match: the page named the
file. What is needed here is the fetching, the shrinking and a record
of what came from where.

Two sizes, as with the creatures: one to look at on a map's own page,
and a small one for a list of 91 of them.
"""

import argparse
import io
import json
import os
import sys
import time

try:
    import requests
    from PIL import Image
except ImportError:
    sys.exit("Run: pip install requests pillow")

from el_creature_images import api, slug, UA

IN_JSON = "maps.json"
OUT_DIR = os.path.join("public", "img", "m")
MANIFEST = "map_images.json"
BOX = (768, 768)
BOX_SMALL = (160, 160)
SIZE_VERSION = 1
PAUSE = 0.25
TIMEOUT = 40
MAX_BYTES = 12_000_000
JPEG_QUALITY = 82


def norm(name):
    """
    A file name as MediaWiki keeps it.

    A page writes map_whitestone_0512px.png; the wiki files it under
    "Map whitestone 0512px.png", with the underscores turned to spaces
    and the first letter capitalised. Asking with one spelling and
    looking the answer up under the other found nothing at all.
    """
    name = name.replace("_", " ").strip()
    return name[:1].upper() + name[1:]


def urls_for(session, names):
    """Where each named file actually lives."""
    found = {}
    for i in range(0, len(names), 40):
        chunk = names[i:i + 40]
        body = api(session, action="query", prop="imageinfo",
                   iiprop="url|size|mime",
                   titles="|".join(f"File:{norm(n)}" for n in chunk))
        for pg in body.get("query", {}).get("pages", []):
            if pg.get("missing"):
                continue
            for info in pg.get("imageinfo", []):
                found[norm(pg["title"][len("File:"):])] = info
        time.sleep(PAUSE)
    return found


def fit(raw, box):
    im = Image.open(io.BytesIO(raw))
    if im.mode in ("RGBA", "LA", "P"):
        im = im.convert("RGBA")
        flat = Image.new("RGB", im.size, (23, 32, 25))
        flat.paste(im, mask=im.split()[-1])
        im = flat
    else:
        im = im.convert("RGB")
    im.thumbnail(box, Image.LANCZOS)
    buf = io.BytesIO()
    im.save(buf, "JPEG", quality=JPEG_QUALITY, optimize=True)
    return buf.getvalue()


def main():
    ap = argparse.ArgumentParser(description="Mirror the map drawings")
    ap.add_argument("--json", default=IN_JSON)
    ap.add_argument("--out", default=OUT_DIR)
    ap.add_argument("--manifest", default=MANIFEST)
    ap.add_argument("--check", action="store_true")
    a = ap.parse_args()

    maps = json.load(open(a.json, encoding="utf-8"))["maps"]
    want = {m["name"]: m["pic"] for m in maps if m.get("pic")}
    os.makedirs(a.out, exist_ok=True)

    old = {}
    if os.path.exists(a.manifest):
        old = json.load(open(a.manifest, encoding="utf-8")).get("maps", {})

    session = requests.Session()
    session.headers.update(UA)
    urls = urls_for(session, sorted(set(want.values())))
    print(f"{len(want)} maps name a drawing, {len(urls)} of those exist")

    have, got, failed, skipped = {}, 0, 0, 0
    for name, filename in want.items():
        info = urls.get(norm(filename))
        if not info:
            continue
        was = old.get(name)
        if (was and was.get("from") == filename
                and was.get("v") == SIZE_VERSION
                and os.path.exists(os.path.join(a.out, was["file"]))):
            have[name] = was
            skipped += 1
            continue
        if a.check:
            continue
        try:
            r = session.get(info["url"], timeout=TIMEOUT)
            r.raise_for_status()
            if not r.content or len(r.content) > MAX_BYTES:
                failed += 1
                continue
            big, small = fit(r.content, BOX), fit(r.content, BOX_SMALL)
            fname, tname = f"{slug(name)}.jpg", f"{slug(name)}-sm.jpg"
            with open(os.path.join(a.out, fname), "wb") as f:
                f.write(big)
            with open(os.path.join(a.out, tname), "wb") as f:
                f.write(small)
            have[name] = {"file": fname, "thumb": tname, "from": filename,
                          "v": SIZE_VERSION}
            got += 1
        except Exception as e:
            failed += 1
            if failed <= 4:
                print(f"  {name} ({filename}): {e}")
        time.sleep(PAUSE)

    if a.check:
        print(f"{len(have)} already here, {len(want) - len(have)} to fetch")
        return

    json.dump({"_comment": "Map drawings mirrored from the EL wiki by "
                           "el_map_images.py.", "maps": have},
              open(a.manifest, "w", encoding="utf-8"), indent=1,
              sort_keys=True)
    total = sum(os.path.getsize(os.path.join(a.out, f))
                for f in os.listdir(a.out))
    print(f"downloaded {got}, kept {skipped}, failed {failed}; "
          f"{len(have)} maps have a drawing, {total / 1024:.0f} KB on disk")


if __name__ == "__main__":
    main()
