#!/usr/bin/env python3
"""One-off: the Top Guilds page, and whether any source names members."""
import re, requests
LINK = r'href=["\']([^"\']+)["\']'
UA = {"User-Agent": "EL-HQ/0.1 (Eternal Lands community site; stann in-game)"}

def grab(url):
    try:
        r = requests.get(url, headers=UA, timeout=30)
    except Exception as e:
        print(f"\n=== {url} -> {e}")
        return ""
    print(f"\n=== {r.url} -> {r.status_code}, {len(r.text)} bytes")
    return r.text

def show(html, n=6, width=230):
    text = " ".join(re.sub(r"<[^>]+>", " ", html).split())
    print(f"  text: {text[:420]}")
    rows = re.findall(r"<tr[^>]*>.*?</tr>", html, re.S | re.I)
    print(f"  {len(rows)} rows; a sample:")
    for row in rows[max(0, len(rows)//3):max(0, len(rows)//3) + n]:
        print("   " + " ".join(row.split())[:width])

html = grab("http://el.other-life.com/top/guild50.php")
show(html)
links = list(dict.fromkeys(re.findall(LINK, html, re.I)))
print(f"  links: {links[:12]}")

# Anything that looks like one guild's own page.
cand = [l for l in links if re.search(r"guild|tag=|member", l, re.I)]
if cand:
    t = cand[0] if cand[0].startswith("http") else \
        "http://el.other-life.com/top/" + cand[0].lstrip("/")
    show(grab(t))

# Does other-life list players with their guild?
for u in ("http://el.other-life.com/top/", "http://el.other-life.com/"):
    h = grab(u)
    if h:
        found = list(dict.fromkeys(re.findall(LINK, h, re.I)))[:14]
        print(f"  links: {found}")
