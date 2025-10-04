function secondsToHMS(sec) {
  sec = Math.max(0, Math.floor(sec || 0));
  const h = Math.floor(sec / 3600);
  const m = Math.floor((sec % 3600) / 60);
  const s = sec % 60;
  return `${h}h ${m}m ${s}s`;
}

function dot(cls){ return `<span class="dot ${cls}"></span>` }

function setStatusPill(ok, text) {
  const pill = document.getElementById('status-pill');
  if (!pill) return;
  pill.textContent = text || (ok ? "Healthy" : "Degraded");
  pill.classList.remove('warn','bad','ok');
  pill.classList.add(ok ? 'ok' : 'warn');
}

async function fetchJSON(url, signal) {
  const r = await fetch(url, { cache: "no-store", signal });
  if (!r.ok) throw new Error(await r.text());
  return r.json();
}

function renderRequests(reqs) {
  const kv = document.getElementById('reqs');
  if (!kv) return;
  kv.innerHTML = "";
  Object.entries(reqs || {}).forEach(([k, v]) => {
    kv.insertAdjacentHTML('beforeend', `<span>${k}</span><b>${v}</b>`);
  });
}

function renderSafeguards(s) {
  const kv = document.getElementById('safeguards');
  if (!kv) return;
  kv.innerHTML = "";
  if (!s) return;
  const states = [s.temporal?.state, s.symbol?.state, s.conversation?.state]
    .filter(Boolean).join('/');
  kv.insertAdjacentHTML('beforeend', `<span>Circuit Breakers</span><b>${states || '—'}</b>`);
  if (s.privacy_filter) kv.insertAdjacentHTML('beforeend', `<span>Privacy Filter</span><b>${s.privacy_filter}</b>`);
  if (s.confidence_validator) kv.insertAdjacentHTML('beforeend', `<span>Confidence Validator</span><b>${s.confidence_validator}</b>`);
}

function renderEnv(e) {
  const el = document.getElementById('env');
  if (!el || !e) return;
  el.textContent =
    `SCROLLS_DIR=${e.SCROLLS_DIR} · MODEL=${e.LLM_MODEL} · ` +
    `TEMPORAL=${e.TEMPORAL_CONTEXT} · SYMBOLS=${e.SYMBOL_RESONANCE} · CONV=${e.CONVERSATION_WEAVE}`;
}

function moduleRow(name, healthy, desc) {
  const cls = healthy === true ? "ok" : (healthy === false ? "bad" : "warn");
  return `
  <div class="module">
    <h4>${name}</h4>
    <div class="desc">${desc || ""}</div>
    <div class="status">${dot(cls)} <span>${
      healthy === true ? "Healthy" : (healthy === false ? "Failed" : "Degraded/Unknown")
    }</span></div>
  </div>`;
}

function setFlowHealth(id, state) {
  const g = document.getElementById(`node-${id}`);
  if (!g) return;
  const rect = g.querySelector('rect');
  if (!rect) return;
  rect.classList.remove('ok','warn','bad');
  rect.classList.add(state);
}

function updateFlowFromStatus(status) {
  const ok = 'ok', warn = 'warn', bad = 'bad';
  setFlowHealth('Guard', ok);
  setFlowHealth('Guide', ok);
  setFlowHealth('Retriever', (status.scrolls_loaded ?? 0) > 0 ? ok : bad);
  setFlowHealth('Synthesis', ok);
  setFlowHealth('Memory', ok);
  setFlowHealth('Resonance', ok);
  setFlowHealth('Lucidity', ok);
  setFlowHealth('Ledger', (status.ledger && (status.ledger.count || status.ledger.entries)) ? ok : warn);
  setFlowHealth('Learning', ok);
}

/* -------- Singleton poller (no overlap) -------- */
let __mv4_timer = null;
let __mv4_inflight = false;
let __mv4_controller = null;
const POLL_MS = 6000;

async function refresh() {
  if (__mv4_inflight) return;
  __mv4_inflight = true;
  if (__mv4_controller) { try { __mv4_controller.abort(); } catch(_){} }
  __mv4_controller = new AbortController();

  try {
    const status = await fetchJSON('/status', __mv4_controller.signal);
    let safeguards = status.safeguards;
    try {
      if (!safeguards) safeguards = await fetchJSON('/safeguards/status', __mv4_controller.signal);
    } catch (_) {}

    // Header stats
    const up = document.getElementById('uptime');
    if (up) up.textContent = secondsToHMS(status.uptime_sec || 0);
    const sc = document.getElementById('scrolls');
    if (sc) sc.textContent = status.scrolls_loaded ?? '—';
    const llm = document.getElementById('llm');
    if (llm) llm.textContent = (status.env?.LLM_BASE_URL ? 'ON' : 'OFF');
    const model = document.getElementById('model');
    if (model) model.textContent = status.env?.LLM_MODEL || '—';

    renderRequests(status.requests || {});
    renderSafeguards(safeguards);
    renderEnv(status.env || {});

    // Modules grid
    const mods = [];
    const led = status.ledger || {};
    const learn = status.learning || {};
    mods.push(moduleRow("Guard", true, "Circuit breakers & privacy filters"));
    mods.push(moduleRow("Guide", true, "Intent, hint, and curiosity prompt"));
    mods.push(moduleRow("Retriever", (status.scrolls_loaded ?? 0) > 0, "Indexed scrolls and notes"));
    mods.push(moduleRow("Synthesis", true, "Weaving draft from top-K evidence"));
    mods.push(moduleRow("Memory", true, "Identity-aware profile + notes"));
    mods.push(moduleRow("Resonance", true, `Harmony threshold = ${status.env?.HARMONY_THRESHOLD ?? "—"}`));
    mods.push(moduleRow("Lucidity", true, "Meta clarity & cadence shaping"));
    mods.push(moduleRow("Ledger", !!(led.count || led.entries), `entries: ${led.count ?? led.entries ?? 0}`));
    mods.push(moduleRow("Learning", Array.isArray(learn) ? learn.length >= 0 : true, "Self-refine queue"));
    if (status.env?.TEMPORAL_CONTEXT) mods.push(moduleRow("Temporal Context", true, "Epoch/Rune enrichment"));
    if (status.env?.SYMBOL_RESONANCE) mods.push(moduleRow("Symbol Resonance", true, "Symbol frequency & motifs"));
    if (status.env?.CONVERSATION_WEAVE) mods.push(moduleRow("Conversation Weaver", true, "Thread continuity"));
    const modsEl = document.getElementById('modules');
    if (modsEl) modsEl.innerHTML = mods.join("");

    updateFlowFromStatus(status);

    // Cadence renderer hook (no extra fetch)
    if (window.__mv4_onStatusData) window.__mv4_onStatusData(status);

    // Status pill logic
    let ok = true;
    if ((status.scrolls_loaded ?? 0) <= 0) ok = false;
    const c = status.cadence || {};
    if ((c.answers || 0) > 0) {
      if ((c.traveler_pct ?? 100) < 99) ok = false;
      if ((c.guiding_pct  ?? 100) < 99) ok = false;
      if ((c.symbols_pct  ?? 100) < 99) ok = false;
    }
    setStatusPill(ok);
  } catch (e) {
    console.error(e);
    setStatusPill(false, "Failed");
    const mods = document.getElementById('modules');
    if (mods) mods.innerHTML = `<div class="muted">Failed to load /status. Is the server running?</div>`;
  } finally {
    __mv4_inflight = false;
  }
}

document.addEventListener('visibilitychange', () => {
  if (document.hidden) {
    if (__mv4_timer) { clearInterval(__mv4_timer); __mv4_timer = null; }
    if (__mv4_controller) { try { __mv4_controller.abort(); } catch(_){} }
  } else {
    refresh();
    if (!__mv4_timer) __mv4_timer = setInterval(refresh, POLL_MS);
  }
});

document.addEventListener('DOMContentLoaded', () => {
  if (__mv4_timer) { clearInterval(__mv4_timer); __mv4_timer = null; }
  refresh();
  __mv4_timer = setInterval(refresh, POLL_MS);
});

window.addEventListener('beforeunload', () => {
  if (__mv4_timer) { clearInterval(__mv4_timer); __mv4_timer = null; }
  if (__mv4_controller) { try { __mv4_controller.abort(); } catch(_){} }
});
