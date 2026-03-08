// ── Constants ──────────────────────────────────────────────────────────────────
const MODEL_DEFAULTS = {
  anthropic: {
    label: "Claude", apiKeyLabel: "Anthropic API Key", apiKeyPlaceholder: "sk-ant-...", hasKey: true, hasUrl: false,
    models: ["claude-sonnet-4-6", "claude-opus-4-6", "claude-haiku-4-5", "claude-sonnet-4-5"],
  },
  openai: {
    label: "GPT", apiKeyLabel: "OpenAI API Key", apiKeyPlaceholder: "sk-...", hasKey: true, hasUrl: false,
    models: ["gpt-4o", "gpt-4o-mini", "o3-mini", "gpt-4-turbo"],
  },
  groq: {
    label: "Groq", apiKeyLabel: "Groq API Key", apiKeyPlaceholder: "gsk_...", hasKey: true, hasUrl: false,
    models: ["llama-3.3-70b-versatile", "mixtral-8x7b-32768"],
  },
  gemini: {
    label: "Gemini", apiKeyLabel: "Gemini API Key", apiKeyPlaceholder: "AIza...", hasKey: true, hasUrl: false,
    models: ["gemini-2.5-flash", "gemini-2.5-pro", "gemini-2.0-flash", "gemini-1.5-pro"],
  },
  custom: {
    label: "Custom", apiKeyLabel: "", apiKeyPlaceholder: "", hasKey: false, hasUrl: true,
    models: [],
  },
};

// ── DOM refs ───────────────────────────────────────────────────────────────────
const deckSelect      = document.getElementById("deck");
const deckRow         = document.getElementById("deck-row");
const btnNewDeck      = document.getElementById("btn-new-deck");
const btnRetryDecks   = document.getElementById("btn-retry-decks");
const deckNewRow      = document.getElementById("deck-new-row");
const deckNewInput    = document.getElementById("deck-new-input");
const btnCancelDeck   = document.getElementById("btn-cancel-deck");
const providerSelect    = document.getElementById("provider");
const modelNameInput    = document.getElementById("model-name");
const modelListEl       = document.getElementById("model-list");
const modelCustomField  = document.getElementById("field-model-custom");
const modelCustomInput  = document.getElementById("model-name-custom");
const modelSelectField  = document.getElementById("field-model-select");
const modelSummaryText  = document.getElementById("model-summary-text");
const apiKeyField       = document.getElementById("field-api-key");
const apiKeyInput       = document.getElementById("api-key");
const apiKeyLabel       = document.getElementById("api-key-label");
const baseUrlField      = document.getElementById("field-base-url");
const baseUrlInput      = document.getElementById("base-url");
const promptInput     = document.getElementById("custom-prompt");
const promptSaved     = document.getElementById("prompt-saved");
const promptSavedDeck = document.getElementById("prompt-saved-deck");
const btnClearPrompt  = document.getElementById("btn-clear-prompt");
const startBtn        = document.getElementById("btn-start");
const stopBtn         = document.getElementById("btn-stop");
const statusBanner    = document.getElementById("status-banner");
const statusText      = document.getElementById("status-text");
const cardsList       = document.getElementById("cards-list");
const activityLog     = document.getElementById("activity-log");
const toast           = document.getElementById("toast");

// ── State ──────────────────────────────────────────────────────────────────────
let config        = null;
let sessionActive = false;
let ankiReachable = false;
let retryTimer    = null;

// ── Init ───────────────────────────────────────────────────────────────────────
async function init() {
  await loadConfig();
  await loadDecks();
  connectSSE();
}

async function loadConfig() {
  const res  = await fetch("/api/config");
  config     = await res.json();
  sessionActive = config.session_active;

  const provider = config.model?.provider || "anthropic";
  providerSelect.value = provider;
  baseUrlInput.value   = config.model?.base_url   || "";
  promptInput.value    = config.custom_prompt || "";
  apiKeyInput.value    = config.api_keys?.[provider] || "";

  await updateProviderUI(provider, false);
  setModelValue(config.model?.model_name || "");
  updatePromptSavedIndicator(config.deck);
  updateSessionUI();
}

async function loadDecks() {
  try {
    const res   = await fetch("/api/decks");
    const decks = await res.json();
    if (Array.isArray(decks)) {
      deckSelect.innerHTML = '<option value="">— choose deck —</option>';
      decks.forEach(d => {
        const opt = document.createElement("option");
        opt.value = d;
        opt.textContent = d;
        deckSelect.appendChild(opt);
      });
      // If saved deck isn't in Anki yet (e.g. typed manually), add it
      if (config?.deck) {
        if (![...deckSelect.options].some(o => o.value === config.deck)) {
          const opt = document.createElement("option");
          opt.value = config.deck;
          opt.textContent = config.deck;
          deckSelect.appendChild(opt);
        }
        deckSelect.value = config.deck;
      }
      setAnkiReachable(true);
    } else {
      setAnkiReachable(false);
    }
  } catch {
    setAnkiReachable(false);
  }
}

function setAnkiReachable(reachable) {
  ankiReachable = reachable;
  if (reachable) {
    btnNewDeck.classList.remove("hidden");
    btnRetryDecks.classList.add("hidden");
    if (retryTimer) { clearInterval(retryTimer); retryTimer = null; }
  } else {
    deckSelect.innerHTML = '<option value="">Anki not reachable — is it open?</option>';
    btnNewDeck.classList.add("hidden");
    btnRetryDecks.classList.remove("hidden");
    if (!retryTimer) {
      retryTimer = setInterval(loadDecks, 5000);
    }
  }
}

btnRetryDecks.addEventListener("click", loadDecks);

// ── Autosave ───────────────────────────────────────────────────────────────────
async function saveConfig() {
  const provider = providerSelect.value;
  const deck     = deckSelect.value;
  const prompt   = promptInput.value.trim();

  // Build updated deck_prompts: set or delete the current deck's entry
  const deckPrompts = { ...(config?.deck_prompts || {}) };
  if (deck) {
    if (prompt) deckPrompts[deck] = prompt;
    else        delete deckPrompts[deck];
  }

  const body = {
    deck,
    model: {
      provider,
      model_name: getModelName(),
      base_url:   provider === "custom" ? baseUrlInput.value.trim() : null,
    },
    api_keys:      { ...(config?.api_keys || {}), [provider]: apiKeyInput.value.trim() },
    custom_prompt: prompt,
    deck_prompts:  deckPrompts,
  };
  await fetch("/api/config", { method: "POST", body: JSON.stringify(body), headers: { "Content-Type": "application/json" } });
  config = { ...config, ...body };
  updateModelSummary();
}

[apiKeyInput, baseUrlInput, modelCustomInput].forEach(el => {
  el.addEventListener("blur", saveConfig);
});

modelNameInput.addEventListener("change", saveConfig);
modelNameInput.addEventListener("blur", () => {
  setTimeout(() => {
    modelListEl.classList.remove("open");
    // Snap to a valid model — if typed value isn't in the list, revert to closest match or first
    const typed = modelNameInput.value.trim().toLowerCase();
    const match = _allModels.find(m => m.toLowerCase() === typed)
               || _allModels.find(m => m.toLowerCase().includes(typed));
    modelNameInput.value = match || _allModels[0] || "";
    updateModelSummary();
    saveConfig();
  }, 150);
});

// Prompt gets its own blur handler so it can update the saved indicator
promptInput.addEventListener("blur", async () => {
  await saveConfig();
  updatePromptSavedIndicator(deckSelect.value);
});

// ── Provider UI ────────────────────────────────────────────────────────────────
function getModelName() {
  const provider = providerSelect.value;
  if (provider === "custom") return modelCustomInput.value.trim();
  return modelNameInput.value.trim();
}

function setModelValue(name) {
  const provider = providerSelect.value;
  if (provider === "custom") {
    modelCustomInput.value = name;
  } else {
    modelNameInput.value = name;
  }
  updateModelSummary();
}

function updateModelSummary() {
  const meta = MODEL_DEFAULTS[providerSelect.value] || MODEL_DEFAULTS.anthropic;
  modelSummaryText.textContent = `${meta.label} ${getModelName()}`;
}

let _allModels = [];

async function populateModelDropdown(provider) {
  const meta = MODEL_DEFAULTS[provider] || MODEL_DEFAULTS.anthropic;

  // Try fetching live models from the provider API
  let models = meta.models;  // fallback
  try {
    const res = await fetch(`/api/models/${provider}`);
    const live = await res.json();
    if (Array.isArray(live) && live.length > 0) models = live;
  } catch { /* use fallback */ }

  _allModels = models;
  _renderModelList(models);
}

function _renderModelList(models) {
  modelListEl.innerHTML = "";
  models.forEach(m => {
    const li = document.createElement("li");
    li.textContent = m;
    li.addEventListener("mousedown", (e) => {
      e.preventDefault();  // keep focus on input
      modelNameInput.value = m;
      modelListEl.classList.remove("open");
      updateModelSummary();
      saveConfig();
    });
    modelListEl.appendChild(li);
  });
}

modelNameInput.addEventListener("focus", () => {
  _renderModelList(_allModels);
  modelListEl.classList.add("open");
});

modelNameInput.addEventListener("input", () => {
  const q = modelNameInput.value.toLowerCase();
  const filtered = _allModels.filter(m => m.toLowerCase().includes(q));
  _renderModelList(filtered);
  modelListEl.classList.add("open");
});

async function updateProviderUI(provider, resetName) {
  const meta = MODEL_DEFAULTS[provider] || MODEL_DEFAULTS.anthropic;

  // Model dropdown vs free text
  if (provider === "custom") {
    modelSelectField.classList.add("hidden");
    modelCustomField.classList.remove("hidden");
    if (resetName) modelCustomInput.value = "minicpm-v";
  } else {
    modelSelectField.classList.remove("hidden");
    modelCustomField.classList.add("hidden");
    await populateModelDropdown(provider);
    if (resetName) modelNameInput.value = _allModels[0] || "";
  }

  if (resetName) {
    apiKeyInput.value = config?.api_keys?.[provider] || "";
  }

  if (meta.hasKey) {
    apiKeyField.classList.remove("hidden");
    apiKeyLabel.textContent = meta.apiKeyLabel;
    // Derive placeholder from saved key prefix, fall back to hardcoded hint
    const savedKey = config?.api_keys?.[provider] || "";
    apiKeyInput.placeholder = savedKey
      ? savedKey.slice(0, 4) + "..."
      : meta.apiKeyPlaceholder;
  } else {
    apiKeyField.classList.add("hidden");
  }

  if (meta.hasUrl) {
    baseUrlField.classList.remove("hidden");
  } else {
    baseUrlField.classList.add("hidden");
  }

  updateModelSummary();
}

providerSelect.addEventListener("change", async () => {
  await updateProviderUI(providerSelect.value, true);
  saveConfig();
});

// ── New deck ───────────────────────────────────────────────────────────────────
btnNewDeck.addEventListener("click", () => {
  deckRow.classList.add("hidden");
  deckNewRow.classList.remove("hidden");
  deckNewInput.focus();
});

function confirmNewDeck() {
  const name = deckNewInput.value.trim();
  if (name) {
    if (![...deckSelect.options].some(o => o.value === name)) {
      const opt = document.createElement("option");
      opt.value = name;
      opt.textContent = name;
      deckSelect.appendChild(opt);
    }
    deckSelect.value = name;
    saveConfig();
  }
  deckNewInput.value = "";
  deckRow.classList.remove("hidden");
  deckNewRow.classList.add("hidden");
}

deckNewInput.addEventListener("keydown", (e) => {
  if (e.key === "Enter")  { e.preventDefault(); confirmNewDeck(); }
  if (e.key === "Escape") {
    deckNewInput.value = "";
    deckRow.classList.remove("hidden");
    deckNewRow.classList.add("hidden");
  }
});

// blur fires before the cancel button click — small delay lets the click win
deckNewInput.addEventListener("blur", () => setTimeout(confirmNewDeck, 150));

btnCancelDeck.addEventListener("click", () => {
  deckNewInput.value = "";
  deckRow.classList.remove("hidden");
  deckNewRow.classList.add("hidden");
});

deckSelect.addEventListener("change", async () => {
  const oldDeck   = config?.deck || "";
  const newDeck   = deckSelect.value;
  const oldPrompt = promptInput.value.trim();

  // Persist the leaving deck's prompt in memory before switching
  const deckPrompts = { ...(config?.deck_prompts || {}) };
  if (oldDeck) {
    if (oldPrompt) deckPrompts[oldDeck] = oldPrompt;
    else           delete deckPrompts[oldDeck];
  }
  config = { ...config, deck: newDeck, deck_prompts: deckPrompts };

  // Load the new deck's saved prompt (or clear if none)
  promptInput.value = deckPrompts[newDeck] || "";
  updatePromptSavedIndicator(newDeck);

  await saveConfig();
});

// ── Prompt saved indicator ──────────────────────────────────────────────────────
function updatePromptSavedIndicator(deck) {
  const hasSaved = !!(deck && config?.deck_prompts?.[deck]);
  if (hasSaved) {
    promptSavedDeck.textContent = deck;
    promptSaved.classList.remove("hidden");
  } else {
    promptSaved.classList.add("hidden");
  }
}

btnClearPrompt.addEventListener("click", () => {
  promptInput.value = "";
  promptSaved.classList.add("hidden");
  saveConfig();
  promptInput.focus();
});

// ── Session UI ─────────────────────────────────────────────────────────────────
function updateSessionUI() {
  if (sessionActive) {
    startBtn.classList.add("hidden");
    stopBtn.classList.remove("hidden");
    statusBanner.className = "status-banner active";
    statusBanner.classList.remove("hidden");
    statusBanner.querySelector(".status-dot").classList.add("pulse");
    statusText.textContent = `Session active — press ⌥⇧A to screenshot (deck: ${config?.deck || "?"})`;
    setFormDisabled(true);
  } else {
    startBtn.classList.remove("hidden");
    stopBtn.classList.add("hidden");
    statusBanner.classList.add("hidden");
    setFormDisabled(false);
  }
}

function setFormDisabled(disabled) {
  [deckSelect, providerSelect, modelNameInput, modelCustomInput, apiKeyInput, baseUrlInput, promptInput, btnNewDeck]
    .forEach(el => { el.disabled = disabled; });
}

// ── Save & Start ───────────────────────────────────────────────────────────────
startBtn.addEventListener("click", async () => {
  const provider = providerSelect.value;
  const deck     = deckSelect.value;

  if (!deck) { showToast("Choose a deck first"); return; }

  const meta = MODEL_DEFAULTS[provider] || MODEL_DEFAULTS.anthropic;
  if (meta.hasKey && !apiKeyInput.value.trim()) {
    showToast("Enter an API key first", true);
    document.getElementById("model-details").open = true;
    setTimeout(() => apiKeyInput.focus(), 50);
    return;
  }

  const body = {
    deck,
    model: {
      provider,
      model_name: getModelName(),
      base_url:   provider === "custom" ? baseUrlInput.value.trim() : null,
    },
    api_keys:      { ...(config?.api_keys || {}), [provider]: apiKeyInput.value.trim() },
    custom_prompt: promptInput.value.trim(),
  };

  await fetch("/api/config", { method: "POST", body: JSON.stringify(body), headers: { "Content-Type": "application/json" } });
  const res  = await fetch("/api/session/start", { method: "POST" });
  const data = await res.json();

  if (data.ok) {
    config = { ...config, ...body, session_active: true };
    sessionActive = true;
    activityLog.innerHTML = "";
    activityLog.classList.add("hidden");
    updateSessionUI();
  }
});

stopBtn.addEventListener("click", async () => {
  await fetch("/api/session/stop", { method: "POST" });
  sessionActive = false;
  config = { ...config, session_active: false };
  updateSessionUI();
});

async function undoBatch(batchId, btn) {
  btn.disabled = true;
  try {
    const r = await fetch("/api/undo", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ batch_id: batchId }),
    });
    const data = await r.json();
    if (!r.ok) logActivity(data.error || "Undo failed", "error");
  } catch {
    logActivity("Undo failed — is Anki running?", "error");
    btn.disabled = false;
  }
}

// ── SSE ────────────────────────────────────────────────────────────────────────
let _eventSource = null;

function connectSSE() {
  if (_eventSource) { _eventSource.close(); _eventSource = null; }
  const es = new EventSource("/api/events");
  _eventSource = es;

  es.onmessage = (e) => {
    const event = JSON.parse(e.data);

    if (event.type === "ping")    return;
    if (event.type === "recent")  { renderCards(event.cards, event.undoable_batches); renderActivityLog(event.activity_log); return; }
    if (event.type === "session_start") {
      sessionActive = true;
      // Reload config so we pick up the new deck/model from whoever started the session
      fetch("/api/config").then(r => r.json()).then(c => { config = c; updateSessionUI(); });
      return;
    }
    if (event.type === "session_stop") {
      sessionActive = false;
      if (config) config.session_active = false;
      updateSessionUI();
      return;
    }
    if (event.type === "done")    { logActivity(event.message, "done"); if (event.cards?.length) prependCards(event.cards, event.batch_id); return; }
    if (event.type === "undo")   { logActivity(event.message, "done"); removeBatch(event.batch_id); return; }
    if (event.type === "error")   { logActivity(event.message, "error"); return; }
    if (event.type === "progress") { logActivity(event.message, "progress"); }
  };
}

// ── Recent cards ───────────────────────────────────────────────────────────────
function renderCards(cards, undoableBatches) {
  cardsList.innerHTML = "";
  if (!cards || !cards.length) {
    cardsList.innerHTML = '<li class="empty-state">No cards yet this session</li>';
    return;
  }
  const undoSet = new Set(undoableBatches || []);
  // Group by batch_id, preserving order (newest first)
  const seen = new Set();
  for (const c of cards) {
    const bid = c.batch_id;
    if (bid && !seen.has(bid)) {
      seen.add(bid);
      const batchCards = cards.filter(x => x.batch_id === bid);
      const header = document.createElement("li");
      header.className = "batch-header";
      header.dataset.batchId = bid;
      const label = document.createElement("span");
      label.className = "batch-label";
      label.textContent = `${batchCards.length} card(s) added`;
      if (undoSet.has(bid)) {
        const btn = document.createElement("button");
        btn.className = "btn-undo";
        btn.textContent = "Undo";
        btn.addEventListener("click", () => undoBatch(bid, btn));
        header.appendChild(label);
        header.appendChild(btn);
      } else {
        header.appendChild(label);
      }
      cardsList.appendChild(header);
      batchCards.forEach(bc => cardsList.appendChild(buildCardLi(bc)));
    } else if (!bid) {
      cardsList.appendChild(buildCardLi(c));
    }
  }
}

function prependCards(cards, batchId) {
  if (cardsList.querySelector(".empty-state")) cardsList.innerHTML = "";
  const deck = config?.deck || "";
  // Insert batch header with undo button
  if (batchId) {
    const header = document.createElement("li");
    header.className = "batch-header";
    header.dataset.batchId = batchId;
    const label = document.createElement("span");
    label.className = "batch-label";
    label.textContent = `${cards.length} card(s) added`;
    const btn = document.createElement("button");
    btn.className = "btn-undo";
    btn.textContent = "Undo";
    btn.addEventListener("click", () => undoBatch(batchId, btn));
    header.appendChild(label);
    header.appendChild(btn);
    cardsList.prepend(header);
  }
  // Insert cards in reverse so first card ends up on top (just below header)
  for (let i = cards.length - 1; i >= 0; i--) {
    const c = cards[i];
    const li = buildCardLi({ front: c.front, back: c.back, deck, ts: Date.now() / 1000, batch_id: batchId });
    // Insert after the batch header if present
    const header = batchId && cardsList.querySelector(`.batch-header[data-batch-id="${batchId}"]`);
    if (header && header.nextSibling) {
      cardsList.insertBefore(li, header.nextSibling);
    } else if (header) {
      cardsList.appendChild(li);
    } else {
      cardsList.prepend(li);
    }
  }
  while (cardsList.children.length > 30) cardsList.removeChild(cardsList.lastChild);
}

function removeBatch(batchId) {
  if (!batchId) return;
  cardsList.querySelectorAll(`[data-batch-id="${batchId}"]`).forEach(el => el.remove());
  if (!cardsList.children.length) {
    cardsList.innerHTML = '<li class="empty-state">No cards yet this session</li>';
  }
}

function buildCardLi(c) {
  const li = document.createElement("li");
  if (c.batch_id) li.dataset.batchId = c.batch_id;

  // Dim cards older than an hour
  if (Date.now() / 1000 - c.ts > 3600) li.classList.add("card-old");

  // Row 1: question + timestamp
  const top = document.createElement("div");
  top.className = "card-top";

  const front = document.createElement("span");
  front.className   = "card-front";
  front.textContent = c.front;

  const ts = document.createElement("span");
  ts.className   = "card-ts";
  ts.textContent = reltime(c.ts);

  top.appendChild(front);
  top.appendChild(ts);
  li.appendChild(top);

  // Row 2: back preview + deck badge
  if (c.back || c.deck) {
    const meta = document.createElement("div");
    meta.className = "card-meta";

    if (c.back) {
      const back = document.createElement("span");
      back.className   = "card-back";
      back.textContent = c.back.split("\n")[0];
      meta.appendChild(back);
    }

    if (c.deck) {
      const deckEl = document.createElement("span");
      deckEl.className   = "card-deck";
      deckEl.textContent = c.deck;
      meta.appendChild(deckEl);
    }

    li.appendChild(meta);
  }

  return li;
}

function reltime(ts) {
  const secs = Math.floor(Date.now() / 1000 - ts);
  if (secs < 60)   return "just now";
  if (secs < 3600) return `${Math.floor(secs / 60)} min ago`;
  return `${Math.floor(secs / 3600)} hr ago`;
}

// ── Activity log ───────────────────────────────────────────────────────────
function renderActivityLog(entries) {
  if (!entries || !entries.length) return;
  activityLog.classList.remove("hidden");
  activityLog.innerHTML = "";
  // entries are newest-first from server
  for (const entry of entries) {
    const li = document.createElement("li");
    li.className = `log-${entry.type}`;
    const d = new Date(entry.ts * 1000);
    const ts = d.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", second: "2-digit" });
    const tsSpan = document.createElement("span");
    tsSpan.className = "log-ts";
    tsSpan.textContent = ts;
    const msgSpan = document.createElement("span");
    msgSpan.className = "log-msg";
    msgSpan.textContent = entry.message;
    li.appendChild(tsSpan);
    li.appendChild(msgSpan);
    activityLog.appendChild(li);
  }
}

function logActivity(message, type = "progress") {
  activityLog.classList.remove("hidden");
  const li = document.createElement("li");
  li.className = `log-${type}`;
  const ts = new Date().toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", second: "2-digit" });
  const tsSpan = document.createElement("span");
  tsSpan.className = "log-ts";
  tsSpan.textContent = ts;
  const msgSpan = document.createElement("span");
  msgSpan.className = "log-msg";
  msgSpan.textContent = message;
  li.appendChild(tsSpan);
  li.appendChild(msgSpan);
  activityLog.prepend(li);
  while (activityLog.children.length > 20) activityLog.removeChild(activityLog.lastChild);
}

// ── Toast ──────────────────────────────────────────────────────────────────────
let toastTimer = null;
function showToast(msg, isError = false) {
  toast.textContent = msg;
  toast.style.borderColor = isError ? "var(--red)" : "var(--border)";
  toast.classList.add("show");
  if (toastTimer) clearTimeout(toastTimer);
  toastTimer = setTimeout(() => toast.classList.remove("show"), 3000);
}

// ── Cleanup ─────────────────────────────────────────────────────────────────────
window.addEventListener("beforeunload", () => {
  if (_eventSource) { _eventSource.close(); _eventSource = null; }
});

// ── Boot ───────────────────────────────────────────────────────────────────────
init();
