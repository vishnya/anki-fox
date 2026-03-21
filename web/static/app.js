// ── Helpers ───────────────────────────────────────────────────────────────────
function escapeHtmlExceptMath(text) {
  // Escape HTML entities but preserve MathJax \(...\) and \[...\] delimiters
  return text
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}

function typesetMath() {
  if (typeof MathJax !== "undefined" && MathJax.typesetPromise) {
    MathJax.typesetPromise().catch(() => {});
  }
}

// ── Constants ──────────────────────────────────────────────────────────────────
const MODEL_DEFAULTS = {
  "claude-code": {
    label: "Claude (subscription)", apiKeyLabel: "", apiKeyPlaceholder: "", hasKey: false, hasUrl: false,
    models: ["claude-sonnet-4-6", "claude-opus-4-6", "claude-haiku-4-5"],
  },
  anthropic: {
    label: "Claude (API key)", apiKeyLabel: "Anthropic API Key", apiKeyPlaceholder: "sk-ant-...", hasKey: true, hasUrl: false,
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
const offlineBanner   = document.getElementById("offline-banner");
const offlineText     = document.getElementById("offline-text");
const sourceVideoConfig = document.getElementById("source-video-config");
const youtubeUrlInput   = document.getElementById("youtube-url");
const btnLoadVideo      = document.getElementById("btn-load-video");
const videoInfo         = document.getElementById("video-info");
const videoTitle        = document.getElementById("video-title");
const videoMetaEl       = document.getElementById("video-meta");
const extensionBanner   = document.getElementById("extension-banner");
const btnOpenExtFolder  = document.getElementById("btn-open-ext-folder");
const btnCopyExtPath    = document.getElementById("btn-copy-ext-path");
const btnExtSkip        = document.getElementById("btn-ext-skip");
const btnExtDone        = document.getElementById("btn-ext-done");
const extPathDisplay    = document.getElementById("ext-path-display");

// ── State ──────────────────────────────────────────────────────────────────────
let config        = null;
let sessionActive = false;
let ankiReachable = false;
let retryTimer    = null;
let currentSource = "screen";

// ── Source selector ────────────────────────────────────────────────────────────
const SOURCE_LABELS = { screen: "Screen", multi: "Multi", video: "Video" };

function setSource(source) {
  currentSource = source;
  if (source === "video" && sessionActive) {
    sourceVideoConfig.classList.remove("hidden");
    loadVideoStatus();
    checkExtensionStatus();
  } else {
    sourceVideoConfig.classList.add("hidden");
  }
  if (sessionActive) updateSessionUI();
}

function loadSourceForDeck(deck) {
  const deckSources = config?.deck_sources || {};
  const source = deckSources[deck]?.source || "screen";
  setSource(source);
  if (source === "video") {
    youtubeUrlInput.value = deckSources[deck]?.youtube_url || "";
  }
}

async function loadVideoStatus() {
  try {
    const res = await fetch("/api/youtube/status");
    const data = await res.json();
    if (data && data.video_id) {
      showVideoInfo(data);
    } else {
      videoInfo.classList.add("hidden");
    }
  } catch { videoInfo.classList.add("hidden"); }
}

function showVideoInfo(data) {
  videoTitle.textContent = data.title || data.video_id;
  const dur = data.duration ? formatDuration(data.duration) : "";
  const segs = data.segment_count || 0;
  videoMetaEl.textContent = `${segs} segments${dur ? " \u00B7 " + dur : ""}${data.transcript_loaded ? " \u00B7 \u2713 Transcript loaded" : ""}`;
  videoInfo.classList.remove("hidden");
}

function formatDuration(secs) {
  const total = Math.floor(secs);
  const h = Math.floor(total / 3600);
  const m = Math.floor((total % 3600) / 60);
  const s = total % 60;
  if (h) return `${h}:${String(m).padStart(2, "0")}:${String(s).padStart(2, "0")}`;
  return `${m}:${String(s).padStart(2, "0")}`;
}

btnLoadVideo.addEventListener("click", async () => {
  const url = youtubeUrlInput.value.trim();
  if (!url) { showToast("Enter a YouTube URL", true); return; }
  btnLoadVideo.disabled = true;
  btnLoadVideo.textContent = "...";
  try {
    const res = await fetch("/api/youtube/load", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ url }),
    });
    const data = await res.json();
    if (data.error) {
      showToast(data.error, true);
      videoInfo.classList.add("hidden");
    } else {
      showVideoInfo(data);
      // Store URL in deck_sources
      const deck = deckSelect.value;
      if (deck) {
        const deckSources = { ...(config?.deck_sources || {}) };
        deckSources[deck] = { ...(deckSources[deck] || {}), source: "video", youtube_url: url };
        config = { ...config, deck_sources: deckSources };
        saveConfig();
      }
    }
  } catch { showToast("Failed to load video", true); }
  btnLoadVideo.disabled = false;
  btnLoadVideo.textContent = "Load";
});

// ── Extension setup banner ─────────────────────────────────────────────────────
let _extensionSkipped = false;
let _extensionPath = "";

async function checkExtensionStatus() {
  if (_extensionSkipped) return;
  try {
    const res = await fetch("/api/extension/status");
    const data = await res.json();
    _extensionPath = data.path || "";
    if (extPathDisplay) extPathDisplay.textContent = _extensionPath;
    if (data.connected) {
      extensionBanner.classList.add("hidden");
    } else if (currentSource === "video") {
      extensionBanner.classList.remove("hidden");
    }
  } catch { /* ignore */ }
}

btnOpenExtFolder.addEventListener("click", async () => {
  try {
    await fetch("/api/extension/reveal", { method: "POST" });
    showToast("Folder opened in Finder");
  } catch {
    showToast("Could not open folder", true);
  }
});

btnCopyExtPath.addEventListener("click", () => {
  navigator.clipboard.writeText(_extensionPath).then(
    () => showToast("Path copied"),
    () => showToast("Copy failed", true),
  );
});

btnExtSkip.addEventListener("click", () => {
  _extensionSkipped = true;
  extensionBanner.classList.add("hidden");
});

btnExtDone.addEventListener("click", async () => {
  try {
    await fetch("/api/extension/hello", { method: "POST" });
    extensionBanner.classList.add("hidden");
    showToast("Extension connected");
  } catch {
    showToast("Could not verify extension", true);
  }
});

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
  _skipDeleteConfirm   = !!config.skip_delete_confirm;

  await updateProviderUI(provider, false);
  setModelValue(config.model?.model_name || "");
  updatePromptSavedIndicator(config.deck);
  loadSourceForDeck(config.deck || "");
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
    deck_sources:  config?.deck_sources || {},
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
  loadSourceForDeck(newDeck);

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
    let statusMsg = `Session active — \u2325\u21E7A to screenshot (deck: ${config?.deck || "?"})`;
    if (currentSource === "multi") statusMsg = `Session active — \u2325\u21E7A to multi-capture (deck: ${config?.deck || "?"})`;
    if (currentSource === "video") statusMsg = `Session active — \u2325\u21E7A to capture moment (deck: ${config?.deck || "?"})`;
    statusText.textContent = statusMsg;
    if (currentSource === "video") {
      sourceVideoConfig.classList.remove("hidden");
    } else {
      sourceVideoConfig.classList.add("hidden");
    }
    setFormDisabled(true);
    startConnectivityPolling();
  } else {
    startBtn.classList.remove("hidden");
    stopBtn.classList.add("hidden");
    statusBanner.classList.add("hidden");
    sourceVideoConfig.classList.add("hidden");
    setFormDisabled(false);
    stopConnectivityPolling();
  }
}

function setFormDisabled(disabled) {
  [deckSelect, providerSelect, modelNameInput, modelCustomInput, apiKeyInput, baseUrlInput, promptInput, btnNewDeck]
    .forEach(el => { el.disabled = disabled; });
  // Source pills, YouTube URL, and load button stay enabled during session
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
    updateSessionUI();
  }
});

stopBtn.addEventListener("click", async () => {
  await fetch("/api/session/stop", { method: "POST" });
  sessionActive = false;
  config = { ...config, session_active: false };
  updateSessionUI();
});

// ── Delete confirmation ────────────────────────────────────────────────────
let _skipDeleteConfirm = false;

function confirmDelete(message) {
  if (_skipDeleteConfirm) return Promise.resolve(true);
  return new Promise(resolve => {
    const overlay = document.createElement("div");
    overlay.className = "confirm-overlay";
    const box = document.createElement("div");
    box.className = "confirm-box";
    const msg = document.createElement("p");
    msg.textContent = message;
    const checkLabel = document.createElement("label");
    checkLabel.className = "confirm-check";
    const check = document.createElement("input");
    check.type = "checkbox";
    checkLabel.appendChild(check);
    checkLabel.appendChild(document.createTextNode(" Don't ask again"));
    const btns = document.createElement("div");
    btns.className = "confirm-btns";
    const cancelBtn = document.createElement("button");
    cancelBtn.className = "confirm-cancel";
    cancelBtn.textContent = "Cancel";
    const deleteBtn = document.createElement("button");
    deleteBtn.className = "confirm-delete";
    deleteBtn.textContent = "Delete";
    btns.appendChild(cancelBtn);
    btns.appendChild(deleteBtn);
    box.appendChild(msg);
    box.appendChild(checkLabel);
    box.appendChild(btns);
    overlay.appendChild(box);
    document.body.appendChild(overlay);
    cancelBtn.addEventListener("click", () => { overlay.remove(); resolve(false); });
    deleteBtn.addEventListener("click", () => {
      if (check.checked) {
        _skipDeleteConfirm = true;
        fetch("/api/config", { method: "POST", body: JSON.stringify({ skip_delete_confirm: true }), headers: { "Content-Type": "application/json" } });
      }
      overlay.remove();
      resolve(true);
    });
    overlay.addEventListener("click", (e) => { if (e.target === overlay) { overlay.remove(); resolve(false); } });
  });
}

async function undoBatch(batchId, btn) {
  const ok = await confirmDelete("Delete this batch of cards from Anki?");
  if (!ok) return;
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
    if (event.type === "recent")  { renderCards(event.cards); renderActivityLog(event.activity_log); _queueCount = event.queue_count || 0; updateOfflineBanner(); return; }
    if (event.type === "session_start") {
      sessionActive = true;
      if (event.message) logActivity(event.message, "done");
      // Reload config so we pick up the new deck/model from whoever started the session
      fetch("/api/config").then(r => r.json()).then(c => { config = c; updateSessionUI(); });
      return;
    }
    if (event.type === "session_stop") {
      sessionActive = false;
      if (config) config.session_active = false;
      if (event.message) logActivity(event.message, "progress");
      updateSessionUI();
      return;
    }
    if (event.type === "done")    { if (event.message) logActivity(event.message, "done"); if (event.cards?.length) prependCards(event.cards, event.batch_id); return; }
    if (event.type === "undo")   { logActivity(event.message, "done"); removeBatch(event.batch_id); return; }
    if (event.type === "card_deleted") { logActivity("Deleted card from Anki", "done"); removeCard(event.note_id); return; }
    if (event.type === "offline_queued") { _isOffline = true; logActivity(event.message, "offline"); updateOfflineBanner(event.queue_count); return; }
    if (event.type === "queue_update") { updateOfflineBanner(event.queue_count); return; }
    if (event.type === "queue_clear")  { _isOffline = false; logActivity(event.message, "done"); updateOfflineBanner(0); return; }
    if (event.type === "source_changed") { setSource(event.source); return; }
    if (event.type === "error")   { logActivity(event.message, "error"); return; }
    if (event.type === "progress") { logActivity(event.message, "progress"); }
  };
}

// ── Recent cards ───────────────────────────────────────────────────────────────
function renderCards(cards) {
  cardsList.innerHTML = "";
  if (!cards || !cards.length) {
    cardsList.innerHTML = '<li class="empty-state">No cards yet</li>';
    return;
  }
  cards.forEach(c => cardsList.appendChild(buildCardLi(c)));
  typesetMath();
}

function prependCards(cards, batchId) {
  if (cardsList.querySelector(".empty-state")) cardsList.innerHTML = "";
  const deck = config?.deck || "";
  for (let i = cards.length - 1; i >= 0; i--) {
    const c = cards[i];
    cardsList.prepend(buildCardLi({
      front: c.front, back: c.back, deck, note_id: c.note_id,
      ts: Date.now() / 1000, batch_id: batchId,
    }));
  }
  while (cardsList.children.length > 20) cardsList.removeChild(cardsList.lastChild);
  typesetMath();
}

function removeBatch(batchId) {
  if (!batchId) return;
  cardsList.querySelectorAll(`[data-batch-id="${batchId}"]`).forEach(el => el.remove());
  if (!cardsList.children.length) {
    cardsList.innerHTML = '<li class="empty-state">No cards yet</li>';
  }
  // Disable the undo button in the activity log
  const undoBtn = activityLog.querySelector(`.log-undo-btn[data-batch-id="${batchId}"]`);
  if (undoBtn) { undoBtn.disabled = true; undoBtn.textContent = "undone"; }
}

function removeCard(noteId) {
  if (!noteId) return;
  const el = cardsList.querySelector(`[data-note-id="${noteId}"]`);
  if (el) el.remove();
  if (!cardsList.children.length) {
    cardsList.innerHTML = '<li class="empty-state">No cards yet</li>';
  }
}

async function deleteCard(noteId, li) {
  const ok = await confirmDelete("Delete this card from Anki?");
  if (!ok) return;
  try {
    const r = await fetch("/api/delete-card", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ note_id: noteId }),
    });
    if (!r.ok) {
      const data = await r.json();
      logActivity(data.error || "Delete failed", "error");
    }
  } catch {
    logActivity("Delete failed — is Anki running?", "error");
  }
}

function buildCardLi(c) {
  const li = document.createElement("li");
  if (c.batch_id) li.dataset.batchId = c.batch_id;
  if (c.note_id) li.dataset.noteId = c.note_id;

  // Dim cards older than an hour
  if (Date.now() / 1000 - c.ts > 3600) li.classList.add("card-old");

  // Row 1: question + delete button + timestamp
  const top = document.createElement("div");
  top.className = "card-top";

  const front = document.createElement("span");
  front.className   = "card-front";
  front.innerHTML = escapeHtmlExceptMath(c.front);

  if (c.note_id) {
    const del = document.createElement("button");
    del.className = "btn-delete-card";
    del.innerHTML = '<svg width="12" height="13" viewBox="0 0 12 13" fill="none" stroke="currentColor" stroke-width="1.3" stroke-linecap="round"><path d="M1.5 3.5h9M4.5 3.5V2a.5.5 0 0 1 .5-.5h2a.5.5 0 0 1 .5.5v1.5M2.5 3.5l.5 8a.5.5 0 0 0 .5.5h5a.5.5 0 0 0 .5-.5l.5-8"/></svg>';
    del.title = "Delete this card from Anki";
    del.addEventListener("click", (e) => { e.stopPropagation(); deleteCard(c.note_id, li); });
    top.appendChild(front);
    top.appendChild(del);
  } else {
    top.appendChild(front);
  }

  const ts = document.createElement("span");
  ts.className   = "card-ts";
  ts.textContent = reltime(c.ts);
  top.appendChild(ts);
  li.appendChild(top);

  // Row 2: back preview + deck badge
  if (c.back || c.deck) {
    const meta = document.createElement("div");
    meta.className = "card-meta";

    if (c.back) {
      const back = document.createElement("span");
      back.className   = "card-back";
      back.innerHTML = escapeHtmlExceptMath(c.back.split("\n")[0]);
      meta.appendChild(back);
    }

    if (c.yt_timestamp !== undefined && c.video_id) {
      const badge = document.createElement("a");
      badge.className = "yt-badge";
      badge.textContent = "\u25B6 " + formatDuration(c.yt_timestamp);
      badge.href = `https://youtube.com/watch?v=${c.video_id}&t=${Math.floor(c.yt_timestamp)}`;
      badge.target = "_blank";
      badge.rel = "noopener";
      badge.title = "Open in YouTube at this timestamp";
      meta.appendChild(badge);
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
  activityLog.innerHTML = "";
  // entries are newest-first from server
  const typeMap = { session_start: "done", session_stop: "progress", card_deleted: "done", offline_queued: "offline", queue_clear: "done" };
  for (const entry of entries) {
    const li = document.createElement("li");
    li.className = `log-${typeMap[entry.type] || entry.type}`;
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
  if (activityLog.querySelector(".empty-state")) activityLog.innerHTML = "";
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

// ── Offline detection ──────────────────────────────────────────────────────────
let _isOffline = false;
let _queueCount = 0;
let _connectivityTimer = null;

function updateOfflineBanner(count) {
  if (count !== undefined) _queueCount = count;
  if (_isOffline && _queueCount > 0) {
    offlineText.textContent = `Offline — ${_queueCount} screenshot${_queueCount === 1 ? "" : "s"} queued, will process when back online`;
    offlineBanner.classList.remove("hidden");
  } else if (_isOffline) {
    offlineText.textContent = "Offline — screenshots will be queued until you reconnect";
    offlineBanner.classList.remove("hidden");
  } else {
    offlineBanner.classList.add("hidden");
  }
}

async function checkConnectivity() {
  // navigator.onLine is instant but only detects cable/wifi disconnect, not API reachability
  if (!navigator.onLine) {
    setOffline(true);
    return;
  }
  try {
    const res = await fetch("/api/connectivity");
    const data = await res.json();
    _queueCount = data.queue_count ?? _queueCount;
    setOffline(!data.online);
  } catch {
    // Can't even reach our own server — not an internet issue, skip
  }
}

function setOffline(offline) {
  if (offline === _isOffline) return;
  _isOffline = offline;
  updateOfflineBanner();
}

// Check connectivity on browser online/offline events and periodically during session
window.addEventListener("online",  () => checkConnectivity());
window.addEventListener("offline", () => setOffline(true));

function startConnectivityPolling() {
  stopConnectivityPolling();
  checkConnectivity();
  _connectivityTimer = setInterval(checkConnectivity, 30000);
}

function stopConnectivityPolling() {
  if (_connectivityTimer) { clearInterval(_connectivityTimer); _connectivityTimer = null; }
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
