#!/usr/bin/env python3
"""One-off: where is the live list of online players?"""
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

# Find the menu link rather than guessing the filename.
menu = grab("https://www.eternal-lands.com/page/guild_list.php")
for m in re.finditer(r'<a[^>]+href=["\']([^"\']+)["\'][^>]*>\s*([^<]{3,30})\s*</a>',
                     menu, re.I):
    if re.search(r"online", m.group(2), re.I):
        print(f"  menu says: {m.group(2).strip()!r} -> {m.group(1)}")

for url in ("https://www.eternal-lands.com/page/online.php",
            "https://www.eternal-lands.com/page/players.php",
            "http://game.eternal-lands.com/online.php",
            "https://top.el-db.com/online.html",
            "https://el-db.com/online"):
    h = grab(url)
    if h and len(h) > 500:
        text = " ".join(re.sub(r"<[^>]+>", " ", h).split())
        print(f"  text: {text[:300]}")
        print(f"  rows: {len(re.findall(r'<tr', h, re.I))}, "
              f"user links: {len(re.findall(r'view_user', h))}")
