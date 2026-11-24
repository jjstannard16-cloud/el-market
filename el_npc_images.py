#!/usr/bin/env python3
"""
el_npc_images.py - keep a local copy of the quest NPC portraits.

The quest guide says who a quest starts with but has no pictures. The
wiki keeps a portrait for nearly all of them, as a plain <Name>.png at
96 pixels square, which is already the size we want.

    python el_npc_images.py            # fetch anything missing
    python el_npc_images.py --check    # say what is missing

The file listing and the matching come from el_creature_images, which
had the same problem first: the whole list is read once and matched on
the name with capitals, spaces, underscores and extension stripped,
rather than guessing at file names.

Two things the quest guide does that the wiki does not:

    "Elle, Valley of the Dwarves"       a place after a comma
    "Bob the Gob, Portland [wandering]" a place and a note

so a name is cut at the first comma or bracket. "The Wraith" is filed
under Wraith, so a leading "The" is tried as well.
"""

import argparse
import json
import os
import re
import sys

try:
    import requests
except ImportError:
    sys.exit("Run: pip install requests")

from el_creature_images import api, every_image, key, slug, UA

IN_JSON = "quests.json"
OUT_DIR = os.path.join("public", "img", "n")
MANIFEST = "npc_images.json"
TIMEOUT = 30
MAX_BYTES = 2_000_000


def bare(npc):
    """'Elle, Valley of the Dwarves' -> 'Elle'."""
    return re.split(r"\s*[,\[(]", npc)[0].strip()


def main():
    ap = argparse.ArgumentParser(description="Mirror the quest NPC portraits")
    ap.add_argument("--json", default=IN_JSON)
    ap.add_argument("--out", default=OUT_DIR)
    ap.add_argument("--manifest", default=MANIFEST)
    ap.add_argument("--check", action="store_true")
    a = ap.parse_args()

    quests = json.load(open(a.json, encoding="utf-8"))["quests"]
    names = sorted({bare(q["npc"]) for q in quests if q.get("npc")})
    os.makedirs(a.out, exist_ok=True)

    old = {}
    if os.path.exists(a.manifest):
        old = json.load(open(a.manifest, encoding="utf-8")).get("npcs", {})

    session = requests.Session()
    session.headers.update(UA)
    files = every_image(session)
    print(f"{len(files)} files on the wiki, {len(names)} NPCs to find")

    have, got, failed, skipped = {}, 0, 0, 0
    for name in names:
        hit = files.get(key(name))
        if not hit:
            # "The Wraith" is filed under Wraith.
            short = re.sub(r"^the\s+", "", name, flags=re.I)
            hit = files.get(key(short)) if short != name else None
        if not hit:
            continue
        was = old.get(name)
        if (was and was.get("from") == hit["name"]
                and os.path.exists(os.path.join(a.out, was["file"]))):
            have[name] = was
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
            ext = (hit["name"].rsplit(".", 1)[-1] or "png").lower()
            ext = "jpg" if ext in ("jpeg", "jpg") else "png"
            fname = f"{slug(name)}.{ext}"
            with open(os.path.join(a.out, fname), "wb") as f:
                f.write(r.content)
            have[name] = {"file": fname, "from": hit["name"]}
            got += 1
        except Exception as e:
            failed += 1
            if failed <= 4:
                print(f"  {name} ({hit['name']}): {e}")

    missing = [n for n in names if n not in have]
    if a.check:
        print(f"{len(have)} already here, {len(missing)} with nothing")
        print("  " + ", ".join(missing))
        return

    json.dump({"_comment": "Quest NPC portraits from the EL wiki, by "
                           "el_npc_images.py. Keyed on the name as the "
                           "quest guide writes it, before any place.",
               "npcs": have},
              open(a.manifest, "w", encoding="utf-8"), indent=1,
              sort_keys=True)

    total = sum(os.path.getsize(os.path.join(a.out, f))
                for f in os.listdir(a.out))
    print(f"\ndownloaded {got}, kept {skipped}, failed {failed}")
    print(f"{len(have)} of {len(names)} NPCs have a portrait; "
          f"{total / 1024:.0f} KB on disk")
    if missing:
        print(f"no picture for: {', '.join(missing)}")


if __name__ == "__main__":
    main()
