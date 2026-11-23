#!/usr/bin/env python3
"""One-off: the official guild list, and whether it names members."""
import re, requests
UA = {"User-Agent": "EL-HQ/0.1 (Eternal Lands community site; stann in-game)"}

def grab(url, **kw):
    r = requests.get(url, headers=UA, timeout=30, params=kw or None)
    print(f"\n=== {r.url} -> {r.status_code}, {len(r.text)} bytes")
    return r.text

html = grab("https://www.eternal-lands.com/page/guild_list.php")
text = " ".join(re.sub(r"<[^>]+>", " ", html).split())
print(f"  text: {text[:500]}")
rows = re.findall(r"<tr[^>]*>.*?</tr>", html, re.S | re.I)
print(f"  {len(rows)} table rows; a few from the middle:")
for row in rows[len(rows)//2:len(rows)//2 + 4]:
    print("   " + " ".join(row.split())[:260])
links = list(dict.fromkeys(re.findall(r'href=["\']([^"\']+)["\']', html, re.I)))
guildish = [l for l in links if re.search(r"guild", l, re.I)]
print(f"  {len(guildish)} guild links, first few: {guildish[:6]}")

# Whatever a single guild's page looks like decides everything.
if guildish:
    target = guildish[0]
    if not target.startswith("http"):
        target = "https://www.eternal-lands.com/page/" + target.lstrip("/")
    g = grab(target)
    gt = " ".join(re.sub(r"<[^>]+>", " ", g).split())
    print(f"  text: {gt[:600]}")
    grows = re.findall(r"<tr[^>]*>.*?</tr>", g, re.S | re.I)
    print(f"  {len(grows)} rows; a few:")
    for row in grows[:6]:
        print("   " + " ".join(row.split())[:240])

grab("https://www.eternal-lands.com/page/players_online.php")
