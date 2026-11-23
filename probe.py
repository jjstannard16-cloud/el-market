#!/usr/bin/env python3
"""One-off: why does the online page have more links than it claims?"""
import re, requests
UA = {"User-Agent": "EL-HQ/0.1 (Eternal Lands community site; stann in-game)"}
html = requests.get("http://game.eternal-lands.com/online_players.htm",
                    headers=UA, timeout=30).text
print(f"{len(html)} bytes")
for m in re.finditer(r"There are\s+(\d+)\s+([^<:]+)", html, re.I):
    print(f"  header: {m.group(0).strip()!r} at offset {m.start()}")
links = [(m.start(), m.group(1)) for m in
         re.finditer(r"view_user\.php\?user=([^\"'&<>\s]+)", html)]
print(f"  {len(links)} links, {len(set(n for _, n in links))} distinct")
print(f"  first at {links[0][0]}, last at {links[-1][0]}")

# Anything between the links that is not another link marks a new block.
print("\n--- text that is not a player link, through the body:")
body = html[html.lower().find("<body"):]
plain = re.sub(r'<a [^>]*view_user[^>]*>[^<]*</a>', "", body)
plain = " ".join(re.sub(r"<[^>]+>", " ", plain).split())
print(f"  {plain[:700]}")

# Where exactly does the second block start?
chunks = re.split(r"(There are\s+\d+[^<:]*:?)", html, flags=re.I)
print(f"\n--- {len(chunks)} chunks split on 'There are N ...'")
for i, c in enumerate(chunks):
    n = len(re.findall(r"view_user", c))
    head = " ".join(re.sub(r"<[^>]+>", " ", c).split())[:90]
    print(f"  [{i}] {n:>4} links  {head!r}")
