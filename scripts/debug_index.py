#!/usr/bin/env python3
from pathlib import Path
import sys, re

SCROLLS_DIR = Path("lore-scrolls")
OK_EXT = {".md", ".markdown", ".txt"}

total = 0
picked = 0
skipped_ext = 0
skipped_size = 0
skipped_name = 0

# Customize if your indexer expects certain series:
SERIES_RE = re.compile(r"^(TOBY_[A-Z]+|ARC|LG|QL|RAG|Toby|Epoch\d+|.*)$")

for p in SCROLLS_DIR.rglob("*"):
    if not p.is_file(): 
        continue
    total += 1
    ext = p.suffix.lower()
    if ext not in OK_EXT:
        skipped_ext += 1
        continue
    if p.stat().st_size == 0:
        skipped_size += 1
        continue
    name = p.name
    if not SERIES_RE.match(name):
        skipped_name += 1
        # print(f"[SKIP:NAME] {p}")   # uncomment to see
        continue
    picked += 1
    print(f"[PICK] {p}")

print(f"\nTotal seen: {total}")
print(f"Picked: {picked}")
print(f"Skipped by ext: {skipped_ext}")
print(f"Skipped by size: {skipped_size}")
print(f"Skipped by name: {skipped_name}")
