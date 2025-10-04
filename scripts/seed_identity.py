# scripts/seed_identity.py
import os, sqlite3, uuid, sys
DB = os.getenv("LEDGER_DB", "mirror-v4.db")
prov = sys.argv[1]          # 'x' or 'telegram'
external_id = sys.argv[2]   # e.g. twitter handle w/o @, or telegram numeric id
handle = sys.argv[3] if len(sys.argv) > 3 else external_id

con = sqlite3.connect(DB); con.row_factory = sqlite3.Row
cur = con.cursor()

# ensure traveler
traveler_id = str(uuid.uuid4())
cur.execute("INSERT OR IGNORE INTO travelers(id) VALUES (?)", (traveler_id,))

# identity (provider,external_id unique)
cur.execute("""
  INSERT OR IGNORE INTO identities(id, traveler_id, provider, external_id, handle, verified)
  VALUES (?, ?, ?, ?, ?, 1)
""", (str(uuid.uuid4()), traveler_id, prov, external_id, handle))

# profile row
cur.execute("""
  INSERT OR IGNORE INTO profiles(traveler_id, tone, language_pref, interactions, lucidity_avg)
  VALUES (?, '', '', 0, 0.0)
""", (traveler_id,))

con.commit()
print("✅ seeded:", {"traveler_id": traveler_id, "provider": prov, "external_id": external_id, "handle": handle})
