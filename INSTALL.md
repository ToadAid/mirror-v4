# INSTALL.md — Setting up Mirror v4 🪞🌊🍃

Mirror v4 is designed to run fully local, with scrolls as its heart and a local LLM as its voice.  
This guide covers setup for **Linux**, **macOS**, and **Windows (Docker / WSL)**.

---

## 1. Requirements

- **Python 3.11+**  
- **LM Studio** (https://lmstudio.ai)  
- **Meta LLaMA 3B Instruct** (downloaded inside LM Studio)  
- **Git + Docker** (optional, for containerized deployment)

---

## 2. Running LM Studio

1. Install LM Studio.  
2. Open **Models** tab → download **Meta LLaMA-3B Instruct**.  
   - 7B or 8B models also work if you have GPU RAM.  
3. Go to **Server** tab → start **Local Inference Server**.  
   - Example URL: `http://127.0.0.1:1234/v1`  
4. Copy the endpoint into your `.env` as:
   ```
   LOCAL_MODEL_URL=http://127.0.0.1:1234/v1
   ```

---

## 3. Clone and Install

```bash
git clone https://github.com/ToadAid/mirror-v4.git
cd mirror-v4
python3 -m venv .venv && source .venv/bin/activate
pip install -U pip
pip install -r requirements.txt
cp .env.example .env
```

Edit `.env`:
```
SCROLLS_DIR=./lore-scrolls
LEDGER_DB=./ledger/mirror.db
HARMONY_THRESHOLD=0.80
LOCAL_MODEL_URL=http://127.0.0.1:1234/v1
```

---

## 4. Run

```bash
python -m tobyworld_v4.api.server
```

Mirror v4 runs at: `[http://localhost](http://127.0.0.1/web/index.html)`  
Health: [http://localhost:8080/web/health.html](http://127.0.0.1:8080/web/health.html)
Check: `curl http://localhost:8080/heartbeat`

---

## 5. Windows Users

### Option A — Docker Desktop
1. Install [Docker Desktop](https://www.docker.com/products/docker-desktop/).  
2. Run Mirror:
   ```bash
   docker run --rm -p 8080:8080 ^
     -e SCROLLS_DIR=/app/lore-scrolls ^
     -e LEDGER_DB=/app/ledger/mirror.db ^
     -e LOCAL_MODEL_URL=http://host.docker.internal:1234/v1 ^
     -v %cd%/lore-scrolls:/app/lore-scrolls ^
     -v %cd%/ledger:/app/ledger ^
     ghcr.io/toadaid/mirror:v4.0.0
   ```

### Option B — WSL2 (Ubuntu)
1. Install [WSL2 + Ubuntu](https://learn.microsoft.com/en-us/windows/wsl/install).  
2. Install Python + Docker inside WSL2.  
3. Follow Linux instructions above.

---

## 6. GPU Acceleration (Optional)

- **CUDA/cuDNN** → install NVIDIA drivers.  
- LM Studio will detect GPU if supported.  
- For CPU-only, LLaMA-3B Instruct still works, but responses will be slower.

---

## 7. First Scroll Import

Place scrolls in `lore-scrolls/`:
```
lore-scrolls/
  TOBY_L110_SolasAndTheWatcher.md
  TOBY_QA284_ProofOfTime.md
```

Reindex:
```bash
curl -X POST "http://localhost:8080/reindex?pattern=*.md&background=true"
```

---

## 8. Verify

Run:
```bash
curl -X POST http://localhost:8080/ask   -H "Content-Type: application/json"   -d '{"user":"guest","question":"Traveler, what is the lesson of Rune 3?"}'
```

You should see a Mirror answer with **answer + meta** fields.

---

## 9. Notes

- Linux/macOS: recommended for stable dev.  
- Windows: use Docker Desktop or WSL2 for best results.  
- LM Studio must be running **before** you start the Mirror.  
- Scrolls are your wisdom archive — without them the Mirror is empty glass. 🪞
