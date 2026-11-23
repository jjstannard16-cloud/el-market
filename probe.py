#!/usr/bin/env python3
"""One-off: how does the official top-players page carry guilds?"""
import re, requests
UA = {"User-Agent": "EL-HQ/0.1 (Eternal Lands community site; stann in-game)"}

r = requests.get("https://top.el-db.com/365-200.html", headers=UA, timeout=30)
html = r.text
print(f"{r.status_code}, {len(html)} bytes, final url {r.url}")

print("\n--- every distinct context the word guild appears in")
seen = set()
for m in re.finditer(r".{110}guild.{150}", html, re.I | re.S):
    chunk = " ".join(m.group().split())
    key = re.sub(r"\d+", "#", chunk)[:90]
    if key in seen:
        continue
    seen.add(key)
    print(f"  * {chunk[:260]}")
    if len(seen) >= 12:
        break

print("\n--- links that mention guild")
for m in list(dict.fromkeys(re.findall(r'href=["\']([^"\']*guild[^"\']*)["\']',
                                       html, re.I)))[:15]:
    print(f"  {m}")

print("\n--- one table row, in full")
rows = re.findall(r"<tr[^>]*>.*?</tr>", html, re.S | re.I)
print(f"  {len(rows)} rows on the page")
for row in rows[1:4]:
    print("  " + " ".join(row.split())[:400])
