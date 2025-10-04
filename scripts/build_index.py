#!/usr/bin/env python3
"""
build_index.py — Regenerate INDEX.md by scanning lore-scrolls/.

Rules:
- Group by series: L, QA, T
- Sort by numeric ID, newest-first (largest ID first)
- SPECIAL: L000 (ID==0) is always listed LAST in the L section
- Include dates by default
- Detect duplicate IDs; keep the most recently modified file and warn

Usage:
  ./scripts/build_index.py
"""

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SCROLLS_DIR = ROOT / "lore-scrolls"
INDEX_PATH = ROOT / "INDEX.md"

# Filename patterns
PAT_L  = re.compile(r"^TOBY_L(\d+)_.*_(\d{4}-\d{2}-\d{2})_EN\.md$", re.IGNORECASE)
PAT_QA = re.compile(r"^TOBY_QA(\d+)_.*_(\d{4}-\d{2}-\d{2})_EN\.md$", re.IGNORECASE)
PAT_T  = re.compile(r"^TOBY_T(\d+)_.*_(\d{4}-\d{2}-\d{2})_EN\.md$", re.IGNORECASE)

# Title line inside the file
TITLE_RE = re.compile(r"^Title:\s*(.+?)\s*$", re.MULTILINE)

def extract_title(path: Path) -> str:
    try:
        text = path.read_text(encoding="utf-8")
        m = TITLE_RE.search(text)
        if m:
            return m.group(1).strip()
    except Exception:
        pass
    # fallback: derive from filename
    stem = path.stem
    # remove prefix like TOBY_L881_
    stem = re.sub(r"^TOBY_(?:QA|L|T)\d+_", "", stem)
    # remove suffix _YYYY-MM-DD_EN
    stem = re.sub(r"_(\d{4}-\d{2}-\d{2})_EN$", "", stem)
    return stem.replace("_", " ").strip()

def find_scrolls():
    """Return list of (series, id, date, path, mtime)."""
    out = []
    for p in SCROLLS_DIR.rglob("*.md"):
        name = p.name
        for series, pat in (("L", PAT_L), ("QA", PAT_QA), ("T", PAT_T)):
            m = pat.match(name)
            if m:
                sid = int(m.group(1))
                date = m.group(2)
                try:
                    mtime = p.stat().st_mtime
                except Exception:
                    mtime = 0.0
                out.append((series, sid, date, p, mtime))
                break
    return out

def dedupe_by_id(items, series_label):
    """
    items: list of (id, date, title, relpath, mtime)
    If duplicate IDs appear, keep the one with most recent mtime.
    Return (deduped_items, warnings)
    """
    by_id = {}
    dups = {}
    for (sid, date, title, rel, mtime) in items:
        if sid not in by_id:
            by_id[sid] = (sid, date, title, rel, mtime)
        else:
            # duplicate
            prev = by_id[sid]
            better = (sid, date, title, rel, mtime) if mtime >= prev[4] else prev
            worse  = prev if better is (sid, date, title, rel, mtime) else (sid, date, title, rel, mtime)
            by_id[sid] = better
            dups.setdefault(sid, []).append(worse)
    warnings = []
    for sid, losers in dups.items():
        keep = by_id[sid]
        losers_list = ", ".join([l[3] for l in losers])
        warnings.append(f"⚠️ Duplicate {series_label}{sid:03d}: kept {keep[3]}, skipped {losers_list}")
    # return as list
    return list(by_id.values()), warnings

def build_index():
    scrolls = find_scrolls()
    if not scrolls:
        INDEX_PATH.write_text("# Tobyworld Scrolls Index\n\n*(No scrolls found in lore-scrolls/)*\n", encoding="utf-8")
        print("Wrote INDEX.md (no scrolls found)")
        return

    # group by series and enrich with title + relative path
    groups = {"L": [], "QA": [], "T": []}
    for series, sid, date, path, mtime in scrolls:
        title = extract_title(path)
        rel = path.relative_to(ROOT).as_posix()
        groups[series].append((sid, date, title, rel, mtime))

    # de-duplicate by ID (keep most recently modified)
    warnings = []
    for k in groups:
        groups[k], w = dedupe_by_id(groups[k], series_label=(k + "_"))
        warnings.extend(w)

    # sort newest-first (largest ID first)
    for k in groups:
        groups[k].sort(key=lambda x: x[0], reverse=True)

    # SPECIAL RULE: L000 should always appear at the bottom of L section
    l_list = groups["L"]
    l_zero = [item for item in l_list if item[0] == 0]
    l_rest = [item for item in l_list if item[0] != 0]
    groups["L"] = l_rest + l_zero  # zero-ID(s) forced to end

    def section(header, items, prefix):
        if not items:
            return f"## {header}\n*(none)*\n\n"
        lines = [f"## {header}"]
        for sid, date, title, rel, _mtime in items:
            idlabel = f"TOBY_{prefix}{sid:03d}"
            lines.append(f"- [{idlabel} — {title}]({rel}) — {date}")
        return "\n".join(lines) + "\n\n"

    parts = [
        "# Tobyworld Scrolls Index",
        "",
        section("L Scrolls",  groups["L"],  "L"),
        section("QA Scrolls", groups["QA"], "QA"),
        section("T Scrolls",  groups["T"],  "T"),
    ]
    INDEX_PATH.write_text("\n".join(parts).strip() + "\n", encoding="utf-8")
    print(f"Wrote {INDEX_PATH.relative_to(ROOT)}")
    if warnings:
        print("\n".join(warnings))

def main():
    if not SCROLLS_DIR.exists():
        print(f"ERROR: {SCROLLS_DIR} not found", file=sys.stderr)
        sys.exit(2)
    build_index()

if __name__ == "__main__":
    main()
