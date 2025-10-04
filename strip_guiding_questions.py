#!/usr/bin/env python3
"""
strip_guiding_questions.py

Recursively strip any "Guiding Question" lines from markdown scrolls so the LLM
can append its own guiding question dynamically.

Adds logging to guiding_cleanup.log for every run.
"""

import sys
from pathlib import Path
import re
import argparse
import shutil
from datetime import datetime

PATTERNS = [
    re.compile(r'^\s*\*\*Guiding Question:\*\*.*$'),
    re.compile(r'^\s*Guiding Question:.*$'),
    re.compile(r'^\s*\*\*Guiding Question：\*\*.*$'),
    re.compile(r'^\s*Guiding Question：.*$'),
]

def should_process(path: Path, exts):
    return path.is_file() and path.suffix.lower() in exts

def strip_gq_from_text(text: str):
    lines = text.splitlines()
    kept = []
    removed = 0
    for line in lines:
        if any(p.match(line) for p in PATTERNS):
            removed += 1
            continue
        kept.append(line)

    # Collapse accidental double blank lines left behind
    collapsed = []
    prev_blank = False
    for line in kept:
        is_blank = (line.strip() == "")
        if is_blank and prev_blank:
            continue
        collapsed.append(line)
        prev_blank = is_blank

    new_text = "\n".join(collapsed)
    return new_text, removed

def main():
    parser = argparse.ArgumentParser(description="Strip 'Guiding Question' lines from scrolls.")
    parser.add_argument("--path", type=str, required=True, help="Root folder to scan (recursively).")
    parser.add_argument("--ext", nargs="+", default=[".md"], help="File extensions to process.")
    parser.add_argument("--inplace", action="store_true", help="Write changes to files (otherwise dry-run).")
    parser.add_argument("--backup", action="store_true", help="Create .bak backups when --inplace is used.")
    args = parser.parse_args()

    root = Path(args.path)
    if not root.exists():
        print(f"[ERROR] Path not found: {root}", file=sys.stderr)
        sys.exit(2)

    files = [p for p in root.rglob("*") if should_process(p, set([e.lower() for e in args.ext]))]
    if not files:
        print("[INFO] No files found matching extensions:", ", ".join(args.ext))
        sys.exit(0)

    total_removed = 0
    changed_files = 0
    examined = 0

    # Open log file
    log_path = Path("guiding_cleanup.log")
    with log_path.open("a", encoding="utf-8") as log:
        log.write(f"\n=== Run at {datetime.now().isoformat()} ===\n")

        for f in files:
            examined += 1
            original = f.read_text(encoding="utf-8", errors="ignore")
            updated, removed = strip_gq_from_text(original)
            if removed > 0:
                changed_files += 1
                total_removed += removed
                if args.inplace:
                    if args.backup:
                        backup_path = f.with_suffix(f.suffix + ".bak")
                        shutil.copy2(f, backup_path)
                    f.write_text(updated, encoding="utf-8")
                msg = f"[{'WRITE' if args.inplace else 'DRY-RUN'}] {f}  (-{removed} guiding line{'s' if removed!=1 else ''})"
                print(msg)
                log.write(msg + "\n")

        summary = (
            f"\n--- Summary ---\n"
            f"Examined files : {examined}\n"
            f"Changed files  : {changed_files}\n"
            f"Lines removed  : {total_removed}\n"
            f"Mode           : {'IN-PLACE' if args.inplace else 'DRY RUN'}\n"
        )
        if args.inplace and args.backup:
            summary += "Backups        : .bak files written next to modified files\n"

        print(summary)
        log.write(summary + "\n")

if __name__ == "__main__":
    main()
