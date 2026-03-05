// ── Constants ──────────────────────────────────────────────────────────────────
const MODEL_DEFAULTS = {
  anthropic: {
    label: "Claude", apiKeyLabel: "Anthropic API Key", hasKey: true, hasUrl: false,
    models: ["claude-sonnet-4-6", "claude-opus-4-6", "claude-haiku-4-5", "claude-sonnet-4-5"],
  },
  openai: {
    label: "GPT", apiKeyLabel: "OpenAI API Key", hasKey: true, hasUrl: false,
    models: ["gpt-4o", "gpt-4o-mini", "o3-mini", "gpt-4-turbo"],
  },
  groq: {
    label: "Groq", apiKeyLabel: "Groq API Key", hasKey: true, hasUrl: false,
    models: ["llama-3.3-70b-versatile", "mixtral-8x7b-32768"],
  },
  gemini: {
    label: "Gemini", apiKeyLabel: "Gemini API Key", hasKey: true, hasUrl: false,
    models: ["gemini-2.0-flash", "gemini-2.0-pro", "gemini-1.5-pro", "gemini-2.5-pro-exp"],
  },
  custom: {
    label: "Custom", apiKeyLabel: "", hasKey: false, hasUrl: true,
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
const modelNameSelect   = document.getElementById("model-name");
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
  await Promise.all([loadConfig(), loadDecks()]);
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

  updateProviderUI(provider, false);
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
  if (sessionActive) return;
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

modelNameSelect.addEventListener("change", saveConfig);

// Prompt gets its own blur handler so it can update the saved indicator
promptInput.addEventListener("blur", async () => {
  await saveConfig();
  updatePromptSavedIndicator(deckSelect.value);
});

// ── Provider UI ────────────────────────────────────────────────────────────────
function getModelName() {
  const provider = providerSelect.value;
  if (provider === "custom") return modelCustomInput.value.trim();
  return modelNameSelect.value;
}

function setModelValue(name) {
  const provider = providerSelect.value;
  if (provider === "custom") {
    modelCustomInput.value = name;
  } else {
    // If saved model is in the list, select it; otherwise pick first
    if ([...modelNameSelect.options].some(o => o.value === name)) {
      modelNameSelect.value = name;
    }
  }
  updateModelSummary();
}

function updateModelSummary() {
  const meta = MODEL_DEFAULTS[providerSelect.value] || MODEL_DEFAULTS.anthropic;
  modelSummaryText.textContent = `${meta.label} ${getModelName()}`;
}

function populateModelDropdown(provider) {
  const meta = MODEL_DEFAULTS[provider] || MODEL_DEFAULTS.anthropic;
  modelNameSelect.innerHTML = "";
  meta.models.forEach(m => {
    const opt = document.createElement("option");
    opt.value = m;
    opt.textContent = m;
    modelNameSelect.appendChild(opt);
  });
}

function updateProviderUI(provider, resetName) {
  const meta = MODEL_DEFAULTS[provider] || MODEL_DEFAULTS.anthropic;

  // Model dropdown vs free text
  if (provider === "custom") {
    modelSelectField.classList.add("hidden");
    modelCustomField.classList.remove("hidden");
    if (resetName) modelCustomInput.value = "minicpm-v";
  } else {
    modelSelectField.classList.remove("hidden");
    modelCustomField.classList.add("hidden");
    populateModelDropdown(provider);
    if (resetName) modelNameSelect.value = meta.models[0];
  }

  if (resetName) {
    apiKeyInput.value = config?.api_keys?.[provider] || "";
  }

  if (meta.hasKey) {
    apiKeyField.classList.remove("hidden");
    apiKeyLabel.textContent = meta.apiKeyLabel;
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

providerSelect.addEventListener("change", () => {
  updateProviderUI(providerSelect.value, true);
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
  [deckSelect, providerSelect, modelNameSelect, modelCustomInput, apiKeyInput, baseUrlInput, promptInput, btnNewDeck]
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
    apiKeyInput.focus();
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

// ── SSE ────────────────────────────────────────────────────────────────────────
function connectSSE() {
  const es = new EventSource("/api/events");

  es.onmessage = (e) => {
    const event = JSON.parse(e.data);

    if (event.type === "ping")    return;
    if (event.type === "recent")  { renderCards(event.cards); return; }
    if (event.type === "done")    { logActivity(event.message, "done"); showToast(event.message); if (event.cards?.length) prependCards(event.cards); return; }
    if (event.type === "error")   { logActivity(event.message, "error"); showToast("Error: " + event.message, true); return; }
    if (event.type === "progress") { logActivity(event.message, "progress"); showToast(event.message); }
  };
}

// ── Recent cards ───────────────────────────────────────────────────────────────
function renderCards(cards) {
  cardsList.innerHTML = "";
  if (!cards.length) {
    cardsList.innerHTML = '<li class="empty-state">No cards yet this session</li>';
    return;
  }
  cards.forEach(c => cardsList.appendChild(buildCardLi(c)));
}

function prependCards(cards) {
  if (cardsList.querySelector(".empty-state")) cardsList.innerHTML = "";
  const deck = config?.deck || "";
  cards.forEach(c => {
    cardsList.prepend(buildCardLi({ front: c.front, back: c.back, deck, ts: Date.now() / 1000 }));
  });
  while (cardsList.children.length > 10) cardsList.removeChild(cardsList.lastChild);
}

function buildCardLi(c) {
  const li = document.createElement("li");

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

// ── Boot ───────────────────────────────────────────────────────────────────────
init();
