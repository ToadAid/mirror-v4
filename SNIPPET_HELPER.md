# 📜 Snippet Helper · Mirror V4

The **Snippet Helper** keeps your `lore-scrolls/` directory in sync with lightweight `.snippets/` files. These are used by Mirror V4’s retrievers to quickly access clean text instead of parsing full scrolls.

This helper is optional — you can run it once, run it in the background, or ignore it. The choice is yours.

---

## 1. Prerequisites

- Python 3.9+ (with `venv`)
- Linux or macOS (Windows users can run under WSL2)
- Optional: `inotify-tools` (for automatic refresh)

---

## 2. Setup

Clone the repo and create a virtual environment:

```bash
git clone https://github.com/ToadAid/mirror-v4.git
cd mirror-v4

python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

---

## 3. Run once (manual refresh)

To build `.snippets/` from `lore-scrolls/`:

```bash
./scripts/refresh_snippets.sh
```

This runs `make_snippets.py` and writes cleaned text files to:

```
lore-scrolls/.snippets/
```

---

## 4. Run continuously (auto-refresh)

If you want the snippets to update automatically when you edit scrolls:

1. Install watcher tools:
   ```bash
   sudo apt install inotify-tools    # Debian/Ubuntu
   brew install inotify-tools        # macOS with Homebrew
   ```

2. Start the watcher:
   ```bash
   ./scripts/watch_snippets.sh
   ```

Now every time you edit a scroll in `lore-scrolls/`, the snippets regenerate automatically.

---

## 5. Advanced Options

You can control which scroll families are included using environment variables:

```bash
INCLUDE_QA=1 INCLUDE_L=0 ./scripts/refresh_snippets.sh
```

(values: `1` = include, `0` = skip)

Default families:
- `QA` → Question/Answer scrolls  
- `L` → Lore scrolls  
- `C` → Commentary  
- `LG` → Lore Guardian  
- `T` → Teaching scrolls  

---

## 6. Where Snippets Live

- Original scrolls: `lore-scrolls/QA/TOBY_QA001.md`  
- Snippets: `lore-scrolls/.snippets/QA/QA001.txt`

The `.snippets/` folder is auto-created and can be safely deleted or regenerated at any time.

---

## 7. Optional: Run as a Service

For long-running environments, you can run the watcher in background:

```bash
nohup ./scripts/watch_snippets.sh > snippet.log 2>&1 &
```

Or configure a `systemd` service if you want it to start on boot.

---

✅ That’s it!  
You now have a **lightweight snippet layer** for `lore-scrolls`, making Mirror V4 retrieval faster and smoother.
