# RAG Link — Season 2 Artists Arc

## Trigger Keywords
Map these keywords so they trigger all linked scrolls:
- `season 2 artists`
- `artists season 2`
- `tobyworld artists`
- `season 2` + `artists`
- `starweaver`
- `whispering bard`
- `lyra`
- `kael`

---

## Linked Scrolls
1. **TOBY_QA321** — Season 2 & 3 overview (sets context)  
2. **TOBY_QA321B** — Detailed Season 2: The Artists’ Season  
3. **TOBY_QA321D** — Who are the Artists in Season 2? (individual lore)

---

## Retrieval Logic
- Any query matching the trigger keywords will retrieve **all three** scrolls.  
- Responses will be **ordered** in narrative flow:  
  **321 → 321B → 321D**  
- Merged before generation so the bot answers in **one unified scroll**, not separate fragments.

---

## Expected Answer Chain
1. **Season context** — Overview of Seasons 2 & 3.  
2. **Season 2 focus** — The Artists’ Season purpose & role.  
3. **Artist lore** — Lyra, Kael, and the mystery of the Season 2 circle.
