#!/usr/bin/env python3
"""
el_badges.py - keep a local copy of the achievement badges.

A player page lists achievements as plain words: "Herbalist (III)",
"Big belly". The page they come from has no artwork at all - the whole
of view_user.php is about 2,300 bytes and holds not one img tag - but
the wiki's Achievements page has a picture for every one of them.

    python el_badges.py            # fetch anything missing
    python el_badges.py --check    # say what is missing, download nothing

That page is laid out one achievement to a heading, with its badge
underneath:

    == Herbalist ==
    * [[File:Award harvest1.png]] Obtained by harvesting 10,000 ...
    * [[File:Award harvest2.png]] Obtained by harvesting 100,000 ...

so the headings give the names and the files under each give the tiers
in order, which is what the (I), (II) and (III) on a player page mean.
Nothing is guessed from the badge names themselves: Herbalist's badges
are called harvest1 to harvest3 and no amount of guessing would have
found them.

The wiki's spelling and the game's differ here and there - the wiki
says "Child of stars" and "Professor of potions" where the game says
"Child of Stars" and "Professor of Potioning" - so the manifest is
keyed on the name with its capitals and punctuation removed, and the
run prints anything it could not place.
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
PAGE = "Achievements"
OUT_DIR = os.path.join("public", "img", "a")
MANIFEST = "badges.json"
BOX = (72, 72)
PAUSE = 0.25
TIMEOUT = 30
MAX_BYTES = 2_000_000

HEADING = re.compile(r"^=+\s*(.+?)\s*=+\s*$", re.M)
FILE = re.compile(r"\[\[File:([^\]|]+)", re.I)


def key(text):
    return re.sub(r"[^a-z0-9]", "", text.lower())


def slug(name):
    """'Award harvest3.png' -> 'award-harvest3'. The extension is put
    back by the caller, so it does not end up in the middle."""
    name = re.sub(r"\.(png|jpe?g|gif|webp)$", "", name, flags=re.I)
    return re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-") or "x"


def api(session, **params):
    params.setdefault("format", "json")
    params.setdefault("formatversion", 2)
    r = session.get(API, params=params, timeout=TIMEOUT)
    r.raise_for_status()
    return r.json()


def page_text(session, title):
    body = api(session, action="query", prop="revisions", titles=title,
               rvprop="content", rvslots="main", redirects=1)
    pages = body.get("query", {}).get("pages", [])
    if not pages or pages[0].get("missing"):
        return ""
    revs = pages[0].get("revisions") or [{}]
    return (revs[0].get("slots", {}).get("main", {}).get("content")
            or revs[0].get("content") or "")


def sections(text):
    """Each heading with the files that appear under it, in page order."""
    marks = [(m.start(), m.end(), m.group(1)) for m in HEADING.finditer(text)]
    out = []
    for i, (start, end, title) in enumerate(marks):
        stop = marks[i + 1][0] if i + 1 < len(marks) else len(text)
        files = [f.strip() for f in FILE.findall(text[end:stop])]
        if files:
            out.append((title, files))
    return out


def file_urls(session, names):
    found = {}
    for i in range(0, len(names), 40):
        chunk = names[i:i + 40]
        body = api(session, action="query", prop="imageinfo",
                   iiprop="url|size|mime",
                   titles="|".join(f"File:{n}" for n in chunk))
        for pg in body.get("query", {}).get("pages", []):
            if pg.get("missing"):
                continue
            for info in pg.get("imageinfo", []):
                found[pg["title"][len("File:"):]] = info
        time.sleep(PAUSE)
    return found


def shrink(raw):
    """Keep a small badge exactly as it is; shrink a large one. PNG
    throughout, because these have transparent corners."""
    im = Image.open(io.BytesIO(raw))
    if im.width <= BOX[0] and im.height <= BOX[1]:
        return raw
    im = im.convert("RGBA")
    im.thumbnail(BOX, Image.LANCZOS)
    buf = io.BytesIO()
    im.save(buf, "PNG", optimize=True)
    return buf.getvalue()


def main():
    ap = argparse.ArgumentParser(description="Mirror the achievement badges")
    ap.add_argument("--out", default=OUT_DIR)
    ap.add_argument("--manifest", default=MANIFEST)
    ap.add_argument("--check", action="store_true")
    a = ap.parse_args()

    os.makedirs(a.out, exist_ok=True)
    session = requests.Session()
    session.headers.update(UA)

    text = page_text(session, PAGE)
    if not text:
        sys.exit(f"The wiki has no {PAGE} page")
    found = sections(text)
    print(f"{len(found)} achievements with a badge on the {PAGE} page")

    wanted = sorted({f for _, files in found for f in files})
    urls = file_urls(session, wanted)
    print(f"{len(wanted)} badge files named, {len(urls)} of them exist")
    if a.check:
        for name, files in found:
            gone = [f for f in files if f not in urls]
            if gone:
                print(f"  {name}: missing {gone}")
        return

    have, got, failed = {}, 0, 0
    for name, files in found:
        tiers = []
        for one in files:
            info = urls.get(one)
            if not info:
                continue
            out_name = f"{slug(one)}.png"
            path = os.path.join(a.out, out_name)
            if not os.path.exists(path):
                try:
                    r = session.get(info["url"], timeout=TIMEOUT)
                    r.raise_for_status()
                    if not r.content or len(r.content) > MAX_BYTES:
                        failed += 1
                        continue
                    with open(path, "wb") as f:
                        f.write(shrink(r.content))
                    got += 1
                except Exception as e:
                    failed += 1
                    if failed <= 4:
                        print(f"  {one}: {e}")
                time.sleep(PAUSE)
            tiers.append(out_name)
        if tiers:
            have[key(name)] = {"name": name, "tiers": tiers}

    json.dump({"_comment": "Achievement badges from the EL wiki, by "
                           "el_badges.py. Keyed on the name with capitals "
                           "and punctuation removed, because the wiki and "
                           "the game spell some of them differently.",
               "badges": have},
              open(a.manifest, "w", encoding="utf-8"), indent=1,
              sort_keys=True)

    total = sum(os.path.getsize(os.path.join(a.out, f))
                for f in os.listdir(a.out))
    tiered = sum(1 for v in have.values() if len(v["tiers"]) > 1)
    print(f"\ndownloaded {got}, failed {failed}")
    print(f"{len(have)} achievements have a badge ({tiered} of them tiered); "
          f"{total / 1024:.0f} KB on disk")
    print("names, as the wiki spells them:")
    for v in sorted(have.values(), key=lambda x: x["name"]):
        print(f"   {v['name']:30} {len(v['tiers'])} tier(s)")


if __name__ == "__main__":
    main()
