# RAG Link — Jade Chest Arc

## Trigger Keywords
Map these keywords so they trigger all linked scrolls:
- `jade chest`
- `ceremony of the jade chest`
- `7777777 grains`
- `7,777,777 grains`
- `$PATIENCE grains`
- `unclaimed jade chest`
- `guard vault`

---

## Linked Scrolls
1. **TOBY_QA319** — Ceremony of the Jade Chest (origin + purpose)  
2. **TOBY_QA319B** — Meaning of the 7,777,777 grains of $PATIENCE  
3. **TOBY_QA319C** — Fate of unclaimed Jade Chests (Guard Vault lore)  

---

## Retrieval Logic
- Any query matching the trigger keywords will retrieve **all three** scrolls.  
- Responses will be **ordered** in narrative flow:  
  **319 → 319B → 319C**  
- Merged before generation so the bot answers in **one unified scroll**, not separate fragments.

---

## Expected Answer Chain
1. **Ceremony** — Introduce the ritual and its symbolic role.  
2. **Grain meaning** — Explain the 7,777,777 $PATIENCE grains.  
3. **Unclaimed fate** — Describe what happens to unclaimed chests and the Guard Vault.
