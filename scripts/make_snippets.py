#!/usr/bin/env python3
"""
Builds distilled snippets from lore-scrolls into lore-scrolls/.snippets/**.txt

- QA: extracts ## Question + ## Answer
- L (Lore): cleans body (no YAML/title/IDs)
- C (Commentary): extracts ## Commentary/Comments/Meditation (fallback to body)
- LG (Ledger): extracts ## Ledger/Entry/Record (fallback)
- T (Teaching): extracts ## Teaching/Tenet/Sutra/Principles (fallback)
- Other families: cleaned body fallback

Keeps lightweight footer: "tags: [...] | arcs: [...]" (toggle with env).
Never leaks filenames or TOBY_* IDs in content.
"""

import os, re, json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC  = ROOT / "lore-scrolls"
DST  = SRC / ".snippets"

# Enable/disable families via env (default ON for known sets)
def on(x): return str(os.getenv(x, "1")).lower() in ("1","true","yes","on")
INCLUDE = {
    "QA": on("INCLUDE_QA"),
    "L":  on("INCLUDE_L"),
    "C":  on("INCLUDE_C"),
    "LG": on("INCLUDE_LG"),
    "T":  on("INCLUDE_T"),
    "OTHER": str(os.getenv("INCLUDE_OTHER","0")).lower() in ("1","true","yes","on"),
}

KEEP_TAGS = on("KEEP_TAGS")
KEEP_ARCS = on("KEEP_ARCS")

for sub in ("QA","L","C","LG","T","OTHER"):
    (DST / sub).mkdir(parents=True, exist_ok=True)

# Regex helpers
YAML_FENCE = re.compile(r'(?s)^---\n(.*?)\n---\n')
H2_ANY     = re.compile(r'(?im)^\s*##\s+[^\n]+\s*$')
H2_Q       = re.compile(r'(?im)^\s*##\s*Question\s*$', re.M)
H2_A       = re.compile(r'(?im)^\s*##\s*Answer\s*$',   re.M)
YOU_ASKED  = re.compile(r'(?is)^\s*you\s+asked:.*?\n+')
META_LINE  = re.compile(r'^\s*(Title|Tags|Arcs?|Chain|Epoch|Date|Symbols|Sacred Numbers|Narrative Alt|SHA-256 Seed)\s*:', re.I)
TOBY_ID    = re.compile(r'\bTOBY_[A-Z]+[0-9_:\- ]+(?:\.md)?\b', re.I)

# Family→preferred section labels (in priority order)
SECTIONS = {
    "C":  ["Commentary", "Comments", "Meditation"],
    "LG": ["Ledger", "Entry", "Record"],
    "T":  ["Teaching", "Tenet", "Sutra", "Principles"],
}

def strip_ids(s:str) -> str:
    return TOBY_ID.sub('', s or '').strip()

def parse_yaml_drop(md: str):
    """
    Return (body_wo_yaml, tags_text, arcs_text).
    Tags/Arcs come from YAML header if present; body is YAML-stripped.
    """
    tags = arcs = ""
    m = YAML_FENCE.search(md)
    if m:
        yaml = m.group(1)
        t = re.search(r'(?im)^\s*Tags\s*:\s*(.+)$', yaml)
        a = re.search(r'(?im)^\s*Arcs?\s*:\s*(.+)$', yaml)
        tags = (t.group(1).strip() if t else "")
        arcs = (a.group(1).strip() if a else "")
        md = md[m.end():]
    return md, tags, arcs

def clean_body(md: str):
    md, tags, arcs = parse_yaml_drop(md)
    md = YOU_ASKED.sub('', md).strip()
    body_lines = []
    for ln in md.splitlines():
        if ln.lstrip().startswith("# "):  # top-level md title
            continue
        if META_LINE.match(ln):
            continue
        body_lines.append(ln)
    body = "\n".join(body_lines).strip()
    return body, tags, arcs

def extract_section(text: str, markers):
    """Return the first found section body for given H2 markers; else None."""
    for label in markers:
        rx = re.compile(fr'(?im)^\s*##\s*{re.escape(label)}\s*$', re.M)
        m = rx.search(text)
        if m:
            tail = text[m.end():]
            n = H2_ANY.search(tail)
            return tail[:(n.start() if n else None)].strip()
    return None

def write_snippet(path: Path, q: str, a: str, tags: str, arcs: str):
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        if q:
            f.write(f"Q: {q.strip()}\n\n")
        f.write(a.strip())
        footer = []
        if KEEP_TAGS and tags: footer.append(f"tags: {tags}")
        if KEEP_ARCS and arcs: footer.append(f"arcs: {arcs}")
        f.write(("\n\n" + " | ".join(footer) + "\n") if footer else "\n")

def process_QA(p: Path):
    raw = p.read_text(encoding="utf-8", errors="ignore")
    body, tags, arcs = clean_body(raw)
    q = extract_section(body, ["Question"]) or ""
    a = extract_section(body, ["Answer"]) or body
    q = strip_ids(q); a = strip_ids(a)
    write_snippet(DST/"QA"/(p.stem + ".txt"), q, a, tags, arcs)

def process_family(p: Path, fam: str):
    raw = p.read_text(encoding="utf-8", errors="ignore")
    body, tags, arcs = clean_body(raw)
    sec = extract_section(body, SECTIONS.get(fam, []))
    a = strip_ids(sec or body)
    write_snippet(DST/fam/(p.stem + ".txt"), "", a, tags, arcs)

def process_other(p: Path):
    raw = p.read_text(encoding="utf-8", errors="ignore")
    body, tags, arcs = clean_body(raw)
    a = strip_ids(body)
    write_snippet(DST/"OTHER"/(p.stem + ".txt"), "", a, tags, arcs)

def main():
    count = 0
    if INCLUDE["QA"]:
        for p in sorted(SRC.glob("TOBY_QA*.md")): process_QA(p); count += 1
    if INCLUDE["L"]:
        for p in sorted(SRC.glob("TOBY_L*.md")):  process_family(p, "L");  count += 1
    if INCLUDE["C"]:
        for p in sorted(SRC.glob("TOBY_C*.md")):  process_family(p, "C");  count += 1
    if INCLUDE["LG"]:
        for p in sorted(SRC.glob("TOBY_LG*.md")): process_family(p, "LG"); count += 1
    if INCLUDE["T"]:
        for p in sorted(SRC.glob("TOBY_T*.md")):  process_family(p, "T");  count += 1
    if INCLUDE["OTHER"]:
        for p in sorted(SRC.glob("TOBY_*.md")):
            if any(p.name.startswith(f"TOBY_{k}") for k in ("QA","L","C","LG","T")): continue
            process_other(p); count += 1
    print(f"Built/updated {count} snippets under {DST}")

if __name__ == "__main__":
    main()
