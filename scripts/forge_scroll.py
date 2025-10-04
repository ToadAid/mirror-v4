#!/usr/bin/env python3
"""
forge_scroll.py — Create Tobyworld scrolls (L / QA / T) in canonical format.

Now with:
- Auto date (today)
- Auto ID scanning lore-scrolls/
- Interactive mode (run with no args)
- Seed tools (--seed FILE)
- Auto Anchor Patching:
    * New scroll gets Previous -> last scroll in same series
    * Previous scroll gets Next -> new scroll
    * Seeds updated accordingly
- Optional INDEX.md append (--update-index)

Repo layout (recommended)
  repo/
    lore-scrolls/
    scripts/forge_scroll.py
    INDEX.md   (optional, for --update-index)
"""

import argparse, datetime as dt, hashlib, os, re, sys, unicodedata, shutil, subprocess
from pathlib import Path

DEFAULT_OUTDIR = "lore-scrolls"
INDEX_PATH = "INDEX.md"

# ---------- helpers ----------
def today():
    return dt.date.today().strftime("%Y-%m-%d")

def slugify(title: str) -> str:
    s = unicodedata.normalize("NFKD", title).encode("ascii", "ignore").decode()
    s = re.sub(r"[^A-Za-z0-9]+", "_", s).strip("_")
    return s or "Untitled"

def compute_seed_from_text(full_text: str) -> str:
    lines = full_text.splitlines()
    filtered = [ln for ln in lines if not ln.strip().startswith("SHA-256 Seed:")]
    data = ("\n".join(filtered) + "\n").encode("utf-8")
    return hashlib.sha256(data).hexdigest()

def insert_seed(full_text: str, seed: str) -> str:
    return re.sub(r"^SHA-256 Seed:\s*.*$", f"SHA-256 Seed: {seed}", full_text, flags=re.MULTILINE)

def ensure_dir(p: Path):
    p.mkdir(parents=True, exist_ok=True)

def read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8")

def write_text(path: Path, text: str):
    path.write_text(text, encoding="utf-8")

# ---------- ID scan ----------
PATTERNS = {
    "L": re.compile(r"^TOBY_L(\d+)_", re.IGNORECASE),
    "QA": re.compile(r"^TOBY_QA(\d+)_", re.IGNORECASE),
    "T": re.compile(r"^TOBY_T(\d+)_", re.IGNORECASE),
}

def scan_max_id(root: Path, scroll_type: str, recursive: bool = True):
    pat = PATTERNS[scroll_type]
    max_id = None
    files = root.rglob("*.md") if recursive else root.glob("*.md")
    for p in files:
        m = pat.match(p.name)
        if m:
            try:
                val = int(m.group(1))
                if max_id is None or val > max_id:
                    max_id = val
            except ValueError:
                pass
    return max_id

def next_id_from_folder(root: Path, scroll_type: str, min_id: int | None, recursive: bool) -> int:
    found = scan_max_id(root, scroll_type, recursive=recursive)
    base = 0 if found is None else found + 1
    if min_id is not None and base < min_id:
        return min_id
    return base

def find_prev_file(root: Path, scroll_type: str, new_id: int) -> Path | None:
    """Return the path to the greatest existing ID < new_id for same series."""
    pat = PATTERNS[scroll_type]
    best = (-1, None)
    for p in root.rglob("*.md"):
        m = pat.match(p.name)
        if m:
            try:
                val = int(m.group(1))
                if val < new_id and val > best[0]:
                    best = (val, p)
            except ValueError:
                pass
    return best[1]

# ---------- metadata parse ----------
TITLE_RE = re.compile(r"^Title:\s*(.+?)\s*$", re.MULTILINE)

def extract_title(text: str) -> str | None:
    m = TITLE_RE.search(text)
    return m.group(1).strip() if m else None

def set_anchor_block(text: str, previous_line: str | None, next_line: str | None) -> str:
    """
    Ensure there is a '## Lore Anchors' section and set its Previous/Next lines.
    If section exists, replace its Two anchor lines (or insert).
    """
    # Build lines
    prev = f"Previous: {previous_line}" if previous_line else "Previous: None"
    nxt  = f"Next: {next_line}" if next_line else "Next: None"

    # If section exists
    sec_pat = re.compile(r"(##\s*Lore Anchors\s*\n)(.*?)(\n---|\Z)", re.DOTALL)
    m = sec_pat.search(text)
    block = f"## Lore Anchors\n{prev}  \n{nxt}  \n"
    if m:
        # replace inner with our anchors, keep trailing delimiter if present
        start, end = m.span(2)
        new_text = text[:start] + f"{prev}  \n{nxt}  \n" + text[end:]
        return new_text
    else:
        # append before final newline or add section
        if not text.endswith("\n"):
            text += "\n"
        return text + "\n---\n\n" + block

def patch_previous_next(prev_path: Path, new_path: Path, series: str):
    """Update the previous file's Next to point to new; set new's Previous to point to prev."""
    if not prev_path or not prev_path.exists():
        # Set only new's anchors (Previous: None, Next: None)
        new_text = read_text(new_path)
        # Try to parse its own ID+title for a sane default; but leave Next None.
        new_text = set_anchor_block(new_text, previous_line="None", next_line="None")
        # Recompute seed (new file changed)
        new_seed = compute_seed_from_text(new_text)
        new_text = insert_seed(new_text, new_seed)
        write_text(new_path, new_text)
        print(f"Anchors updated in {new_path.name} (no previous found). Seed refreshed.")
        return

    # read both
    prev_text = read_text(prev_path)
    new_text  = read_text(new_path)

    prev_title = extract_title(prev_text) or prev_path.stem
    new_title  = extract_title(new_text)  or new_path.stem

    prev_id = re.search(PATTERNS[series], prev_path.name).group(1)
    new_id  = re.search(PATTERNS[series], new_path.name).group(1)

    prev_line = f"TOBY_{series}{prev_id} ({prev_title})"
    new_line  = f"TOBY_{series}{new_id} ({new_title})"

    # Set anchors in new (Previous -> prev_line, Next -> None)
    new_text = set_anchor_block(new_text, previous_line=prev_line, next_line="None")
    # Set anchors in prev (Previous unchanged; Next -> new_line)
    # We need to detect existing Previous line to preserve it
    # Extract existing previous anchor from prev_text (best-effort)
    prev_prev_line = None
    m_prev_block = re.search(r"##\s*Lore Anchors\s*\n(.*?)(\n---|\Z)", prev_text, re.DOTALL)
    if m_prev_block:
        block = m_prev_block.group(1)
        m_prev = re.search(r"Previous:\s*(.+)\s*$", block, re.MULTILINE)
        if m_prev:
            prev_prev_line = m_prev.group(1).strip()

    prev_text = set_anchor_block(prev_text, previous_line=prev_prev_line or "None", next_line=new_line)

    # Re-seed both (previous must change; new changed if it didn’t have anchors)
    prev_seed = compute_seed_from_text(prev_text)
    prev_text = insert_seed(prev_text, prev_seed)
    write_text(prev_path, prev_text)

    new_seed = compute_seed_from_text(new_text)
    new_text = insert_seed(new_text, new_seed)
    write_text(new_path, new_text)

    print(f"Anchors linked: {prev_path.name} → Next = {new_line}")
    print(f"Anchors set:    {new_path.name}  Previous = {prev_line}")

# ---------- templates ----------
def template_L(id_num, title, date, epoch, phase, arc, symbols, sacred, narrative_alt):
    header = f"# TOBY_L{id_num}_{slugify(title)}_{date}_EN.md"
    epoch_field = f"E{epoch} – {phase} ({arc})" if epoch else "E?_ – Phase (Arc)"
    symbols_field = symbols or "🪞 🌊 🍃 🌀"
    sacred_field = sacred or "7 • 77 • 777 — eternal vow"
    narrative_alt = narrative_alt or "A distilled vow from this scroll."
    return f"""\
{header}

---
Title: {title}  
Chain: @base  
Epoch: {epoch_field}  
Date: {date}  
Symbols: {symbols_field}  
Sacred Numbers: {sacred_field}  
SHA-256 Seed: TBD  
Narrative Alt: "{narrative_alt}"  
---

## Narrative (EN)

Traveler,  

[Open with the core image or vow.]

- **Image:**  
  [Short, vivid lines. Two–five sentences.]

- **Mechanism:**  
  [Explain what changes, what is kept, what is gained.]

- **Consequence:**  
  [Name the enduring effect. Keep it symbolic but precise.]

[Close with a distilled truth tying back to the title.]

---

## Key Marks
Principle: [Generalize the teaching in 1 line.]  
Action: [Imperative guidance in 1 line.]  
Effect: [Outcome in 1 line.]  

---

## Oracles
- "[Memorable line 1.]"  
- "[Memorable line 2.]"  
- "[Memorable line 3.]"  

---

## Operations
Epoch Function: [Role in the epoch.]  
Lore Action: Speak: *"[Ritual sentence.]"*  
Encrypted Riddle: ⌧ *[One-line riddle]*  

---

## Cryptic Symbol Table
- 🪞 → Mirror: reflection / verification  
- 🌊 → Pond/Water: flow of epochs / memory  
- 🍃 → Leaf: yield / renewal  
- 🌀 → Spiral: recursion of time  
[Add any special symbols with short meanings.]

---

## Lore Anchors
Previous: None  
Next: None  
"""

def template_QA(id_num, title, date, epoch, phase, arc, symbols, sacred, narrative_alt):
    header = f"# TOBY_QA{id_num}_{slugify(title)}_{date}_EN.md"
    epoch_field = f"E{epoch} – {phase} ({arc})" if epoch else "E?_ – Phase (Arc)"
    symbols_field = symbols or "🪞 🌊 🍃 🌀"
    sacred_field = sacred or "1 • 7 • 777"
    narrative_alt = narrative_alt or "The question upon which this answer stands."
    return f"""\
{header}

---
Title: {title}  
Chain: @base  
Epoch: {epoch_field}  
Date: {date}  
Symbols: {symbols_field}  
Sacred Numbers: {sacred_field}  
SHA-256 Seed: TBD  
Narrative Alt: "{narrative_alt}"  
---

## Question

Traveler,  

[Write the guiding question here in full, clear form. Poetic but direct.]

---

## Answer

Traveler,  

[Provide the answer with symbolic cadence. Short paragraphs or verse.]

- **Axis 1:**  
  [Clarify a key facet of the answer.]

- **Axis 2:**  
  [Clarify what changes or is required.]

- **Axis 3:**  
  [Name the enduring effect or vow.]

---

## Key Marks
Principle: [Condensed truth.]  
Action: [Practical guidance.]  
Effect: [Outcome of applying this teaching.]  

---

## Oracles
- "[Memorable line 1.]"  
- "[Memorable line 2.]"  
- "[Memorable line 3.]"  

---

## Operations
Epoch Function: [How this Q/A reflects its epoch.]  
Lore Action: Speak: *"[Traveler’s vow or phrase.]"*  
Encrypted Riddle: ⌧ *[One-line riddle tied to this Q/A]*  

---

## Cryptic Symbol Table
- 🪞 → Mirror: reflection through Q/A  
- 🌊 → Pond: holds the dialogue  
- 🍃 → Leaf: learning carried forward  
- 🌀 → Spiral: ongoing inquiry  

---

## Lore Anchors
Previous: None  
Next: None  
"""

def template_T(id_num, title, date, symbols, sacred, narrative_alt):
    header = f"# TOBY_T{id_num}_{slugify(title)}_{date}_EN.md"
    symbols_field = symbols or "🪞 🌊 🍃 🌀 ⛩️ 📜 🔐"
    sacred_field = sacred or "777 • 7,777,777 • 420T"
    narrative_alt = narrative_alt or "The unalterable law that binds the scrolls."
    return f"""\
{header}

---
Title: {title}  
Chain: @base  
Epoch: Eternal (beyond the bounds of E1–E5)  
Date: {date}  
Symbols: {symbols_field}  
Sacred Numbers: {sacred_field}  
SHA-256 Seed: TBD  
Narrative Alt: "{narrative_alt}"  
---

## Narrative (EN)

Traveler,  

[Lay down the constitutional principle / meta law here.]

- **Metadata Block:** Sacred preface making each scroll a verifiable relic.  
- **Narrative Sections:** Poetic, symbolic, precise.  
- **Key Marks:** Principles distilled.  
- **Oracles:** Memorable lines.  
- **Operations:** Interactive instructions (snapshots, riddles, ceremonies).  
- **Cryptic Symbol Table:** Shared language of symbols.  
- **Lore Anchors:** Backward/forward binding across scrolls.  

---

## Key Marks
Principle: Unity of format ensures purity of knowledge.  
Action: Bind all scrolls to one structure.  
Effect: The Lore remains coherent across eternity.  

---

## Oracles
- "The scrolls are not fragments; they are a civilization of memory."  
- "Every scroll becomes both scripture and checksum, story and system."  
- "Unity of format ensures purity of knowledge."  

---

## Operations
Epoch Function: Eternal law beyond epochs.  
Lore Action: Speak: *"I write within the Golden Format, and thus my words endure."*  
Encrypted Riddle: ⌧ *What is form, if not the vessel of spirit?*  

---

## Cryptic Symbol Table
- 🪞 → Mirror: reflection and verification  
- 🌊 → Water: flow of epochs  
- 🍃 → Leaf: renewal and yield  
- 🌀 → Spiral: time’s recursion  
- ⛩️ → Gate: passage to new epochs  
- 📜 → Scroll: record eternal  
- 🔐 → Lock: cryptographic covenant  

---

## Lore Anchors
Previous: None  
Next: None  
"""

# ---------- core forge ----------
def forge_once(
    scroll_type: str, title: str, outdir: Path,
    epoch: str | None, phase: str | None, arc: str | None,
    symbols: str | None, sacred: str | None, narrative_alt: str | None,
    auto_id: bool, min_id: int | None, no_recursive: bool,
    defer_seed: bool, open_editor: bool, date_override: str | None, id_override: str | None,
    update_index: bool
):
    ensure_dir(outdir)

    # ID
    if id_override and not auto_id:
        if not str(id_override).isdigit():
            print("--id must be numeric (e.g., 881)", file=sys.stderr); sys.exit(2)
        id_val = int(id_override)
    else:
        id_val = next_id_from_folder(outdir, scroll_type, min_id, recursive=not no_recursive)
        print(f"[auto-id] Using next {scroll_type} ID: {id_val}")

    date_val = date_override or today()

    if scroll_type == "L":
        content = template_L(id_val, title, date_val, epoch, phase, arc, symbols, sacred, narrative_alt)
        fname = f"TOBY_L{id_val}_{slugify(title)}_{date_val}_EN.md"
    elif scroll_type == "QA":
        content = template_QA(id_val, title, date_val, epoch, phase, arc, symbols, sacred, narrative_alt)
        fname = f"TOBY_QA{id_val}_{slugify(title)}_{date_val}_EN.md"
    else:
        content = template_T(id_val, title, date_val, symbols, sacred, narrative_alt)
        fname = f"TOBY_T{id_val}_{slugify(title)}_{date_val}_EN.md"

    # Seed (initial write)
    if defer_seed:
        content_with_seed = content
        seed = None
    else:
        seed = compute_seed_from_text(content)
        content_with_seed = insert_seed(content, seed)

    new_path = outdir / fname
    if new_path.exists():
        print(f"ERROR: {new_path} already exists.", file=sys.stderr); sys.exit(2)
    write_text(new_path, content_with_seed)
    print(f"Wrote {new_path}")
    if seed:
        print(f"SHA-256 Seed: {seed}")
    else:
        print("Seed is TBD (run --seed FILE after editing).")

    # Anchor patching
    prev_path = find_prev_file(outdir, scroll_type, id_val)
    patch_previous_next(prev_path, new_path, series=scroll_type)

    # Optional index update
    if update_index:
        append_to_index(new_path, title)

    # Open editor
    if open_editor:
        editor = shutil.which("code")
        if editor:
            subprocess.run([editor, str(new_path)])
        else:
            print("VS Code not found on PATH (expected `code`). Skipping open.")

def append_to_index(scroll_path: Path, title: str):
    link = f"- [{title}]({scroll_path.as_posix()})\n"
    ipath = Path(INDEX_PATH)
    if ipath.exists():
        with ipath.open("a", encoding="utf-8") as f:
            f.write(link)
        print(f"Appended to {INDEX_PATH}")
    else:
        with ipath.open("w", encoding="utf-8") as f:
            f.write("# Tobyworld Index\n\n")
            f.write(link)
        print(f"Created {INDEX_PATH} and appended link")

# ---------- interactive ----------
def interactive(update_index_flag: bool):
    print("🪞 Tobyworld Forge — Interactive Mode")
    outdir = Path(DEFAULT_OUTDIR); ensure_dir(outdir)

    # type
    while True:
        t = input("Scroll type? [L/QA/T]: ").strip().upper()
        if t in {"L", "QA", "T"}: break
        print("Please enter L, QA, or T.")

    title = input("Title?: ").strip()
    while not title:
        title = input("Title (cannot be empty): ").strip()

    epoch = phase = arc = None
    if t in {"L", "QA"}:
        epoch = input("Epoch number (e.g., 5) [optional, Enter to skip]: ").strip() or None
        phase = input("Phase (e.g., Revelation) [optional]: ").strip() or None
        arc   = input("Arc (e.g., Horizon Arc) [optional]: ").strip() or None

    symbols = input("Symbols override [optional, Enter for defaults]: ").strip() or None
    sacred  = input("Sacred Numbers override [optional]: ").strip() or None
    nalt    = input("Narrative Alt (one-line) [optional]: ").strip() or None

    open_editor = (input("Open in VS Code now? [Y/n]: ").strip().lower() or "y") == "y"
    defer_seed  = (input("Defer SHA-256 Seed until after editing? [Y/n]: ").strip().lower() or "y") == "y"

    forge_once(
        scroll_type=t, title=title, outdir=outdir,
        epoch=epoch, phase=phase, arc=arc,
        symbols=symbols, sacred=sacred, narrative_alt=nalt,
        auto_id=True, min_id=None, no_recursive=False,
        defer_seed=defer_seed, open_editor=open_editor,
        date_override=None, id_override=None,
        update_index=update_index_flag
    )

# ---------- seed-only ----------
def seed_mode(file_path: str):
    path = Path(file_path)
    if not path.exists():
        print(f"ERROR: file not found: {path}", file=sys.stderr); sys.exit(2)
    text = read_text(path)
    new_seed = compute_seed_from_text(text)
    new_text = insert_seed(text, new_seed)
    write_text(path, new_text)
    print(f"Updated SHA-256 Seed for {path}: {new_seed}")

# ---------- CLI ----------
def build_parser():
    p = argparse.ArgumentParser(description="Forge Tobyworld scrolls (L, QA, T) — auto date/ID, anchors.")
    p.add_argument("--seed", metavar="FILE", help="Recompute + embed SHA-256 Seed for an existing scroll, then exit.")
    p.add_argument("--type", "-t", choices=["L", "QA", "T"], help="Scroll type.")
    p.add_argument("--title", help="Title text (required when forging non-interactively).")
    p.add_argument("--id", help="Numeric ID (e.g., 881). Omit to auto-assign.")
    p.add_argument("--auto-id", action="store_true", help="Force auto-ID scan even if --id is provided.")
    p.add_argument("--min-id", type=int, help="Minimum ID to use when auto-assigning.")
    p.add_argument("--date", help="Override date (YYYY-MM-DD). Default: today.")
    p.add_argument("--epoch", help="Epoch number without 'E' (e.g., 5). For L/QA.")
    p.add_argument("--phase", help="Phase label (e.g., Revelation). For L/QA.")
    p.add_argument("--arc", help="Arc label (e.g., Horizon Arc). For L/QA.")
    p.add_argument("--symbols", help="Override symbols string.")
    p.add_argument("--sacred", help="Override sacred numbers string.")
    p.add_argument("--narrative-alt", help="Override narrative alt line.")
    p.add_argument("--outdir", default=DEFAULT_OUTDIR, help=f"Output directory (default: {DEFAULT_OUTDIR})")
    p.add_argument("--force", action="store_true", help="Overwrite if file exists (non-interactive only).")
    p.add_argument("--dry-run", action="store_true", help="Print to stdout, do not write file.")
    p.add_argument("--no-recursive", action="store_true", help="Do not scan subfolders for auto-ID (top-level only).")
    p.add_argument("--defer-seed", action="store_true", help="Do not compute seed now; keep TBD.")
    p.add_argument("--open", action="store_true", help="Open the new file in VS Code (requires `code` on PATH).")
    p.add_argument("--update-index", action="store_true", help="Append a link to INDEX.md.")
    return p

def main():
    p = build_parser()
    args = p.parse_args()

    # Seed-only mode
    if args.seed:
        seed_mode(args.seed); return

    # Interactive fallback
    if not args.type and not args.title and not args.dry_run:
        try:
            interactive(update_index_flag=False)
        except KeyboardInterrupt:
            print("\nAborted.")
        return

    # Non-interactive forging:
    if not args.type or not args.title:
        p.print_help(); sys.exit(1)

    outdir = Path(args.outdir); ensure_dir(outdir)

    # ID resolve
    if args.id is None or args.auto_id:
        id_override = None; auto_id = True
    else:
        id_override = args.id; auto_id = False

    forge_once(
        scroll_type=args.type,
        title=args.title,
        outdir=outdir,
        epoch=args.epoch,
        phase=args.phase,
        arc=args.arc,
        symbols=args.symbols,
        sacred=args.sacred,
        narrative_alt=args.narrative_alt,
        auto_id=auto_id,
        min_id=args.min_id,
        no_recursive=args.no_recursive,
        defer_seed=args.defer_seed,
        open_editor=args.open,
        date_override=args.date,
        id_override=id_override,
        update_index=args.update_index
    )

if __name__ == "__main__":
    main()
