import json
import logging
import queue
import re
import threading
import time
import uuid
from pathlib import Path

from flask import Flask, Response, jsonify, request, send_from_directory
from PIL import Image
from watchdog.events import FileSystemEventHandler
from watchdog.observers import Observer

import config as cfg
import models
import youtube

# ── Constants ────────────────────────────────────────────────────────────────────
ANKICONNECT_URL = "http://localhost:8765"
SCREENSHOTS_DIR = Path.home() / "AnkiFox" / "incoming"
BASE_DIR        = Path(__file__).parent
_QUEUE_FILE     = Path.home() / ".anki-fox" / "offline_queue.json"

MAX_RECENT_CARDS = 20
MAX_ACTIVITY_LOG = 20
MAX_BATCHES = 10
MAX_SSE_CONNECTIONS = 10
POLL_INTERVAL_SECS = 2
QUEUE_RETRY_SECS = 30
QUEUE_TTL_SECS = 86400  # 24 hours
ANKICONNECT_TIMEOUT = 5
ANKICONNECT_RETRIES = 2

# ── Logging ──────────────────────────────────────────────────────────────────────
_REDACT_PATTERNS = (re.compile(r'sk-ant-[a-zA-Z0-9_-]+'), re.compile(r'sk-[a-zA-Z0-9_-]{20,}'), re.compile(r'gsk_[a-zA-Z0-9_-]+'), re.compile(r'AIza[a-zA-Z0-9_-]+'))

def _redact(text: str) -> str:
    for pat in _REDACT_PATTERNS:
        text = pat.sub("[REDACTED]", text)
    return text

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s", datefmt="%H:%M:%S")
log = logging.getLogger("anki-fox")

app = Flask(
    __name__,
    template_folder=str(BASE_DIR / "web" / "templates"),
    static_folder=str(BASE_DIR / "web" / "static"),
)
app.config["SEND_FILE_MAX_AGE_DEFAULT"] = 0

@app.after_request
def add_no_cache(response):
    if "text/html" in response.content_type or "javascript" in response.content_type or "text/css" in response.content_type:
        response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
        response.headers["Pragma"] = "no-cache"
        response.headers["Expires"] = "0"
    return response

# ── SSE broadcast ────────────────────────────────────────────────────────────────
_sse_subscribers: list[queue.Queue] = []
_sse_lock = threading.Lock()

# ── Persistent state file ──────────────────────────────────────────────────────────
_STATE_FILE = cfg.CONFIG_DIR / "state.json"

def _load_state():
    """Load persisted activity log, recent cards, and batches from disk."""
    try:
        if _STATE_FILE.exists():
            with open(_STATE_FILE) as f:
                s = json.load(f)
            return (
                s.get("activity_log", []),
                s.get("recent_cards", []),
                {k: v for k, v in s.get("batches", {}).items()},
            )
    except (json.JSONDecodeError, OSError):
        pass
    return [], [], {}

def _save_state():
    """Persist activity log, recent cards, and batches to disk."""
    try:
        cfg.CONFIG_DIR.mkdir(parents=True, exist_ok=True)
        with open(_STATE_FILE, "w") as f:
            json.dump({
                "activity_log": _activity_log,
                "recent_cards": _recent_cards,
                "batches": _batches,
            }, f)
    except OSError:
        pass

# ── Recent cards (newest-first) ──────────────────────────────────────────────────
_recent_lock  = threading.Lock()

# ── Activity log (newest-first) ──────────────────────────────────────────────────
_activity_lock = threading.Lock()

# ── Undo: batch_id → list of note IDs ─────────────────────────────────────────────
_batches_lock = threading.Lock()

_activity_log, _recent_cards, _batches = _load_state()

# ── Offline queue ─────────────────────────────────────────────────────────────
_queue_lock = threading.Lock()
_queue_processing = threading.Lock()  # ensures only one _process_queue runs at a time
_offline_queue: list[dict] = []  # [{"path": str, "ts": float, "deck": str, "conf": dict}]

def _load_queue():
    try:
        if _QUEUE_FILE.exists():
            with open(_QUEUE_FILE) as f:
                return json.load(f)
    except (json.JSONDecodeError, OSError):
        pass
    return []

def _save_queue():
    try:
        _QUEUE_FILE.parent.mkdir(parents=True, exist_ok=True)
        with open(_QUEUE_FILE, "w") as f:
            json.dump(_offline_queue, f)
    except OSError:
        pass

_offline_queue = _load_queue()

def _is_network_error(exc: Exception) -> bool:
    """Return True if the exception looks like a connectivity failure."""
    net_types = [ConnectionError, TimeoutError, OSError]
    # Dynamically add library-specific network error types
    for mod_name, cls_name in [
        ("requests.exceptions", "ConnectionError"),
        ("requests.exceptions", "Timeout"),
        ("httpx", "ConnectError"),
        ("httpx", "ConnectTimeout"),
        ("anthropic", "APIConnectionError"),
        ("anthropic", "APITimeoutError"),
        ("openai", "APIConnectionError"),
        ("openai", "APITimeoutError"),
    ]:
        try:
            import importlib
            m = importlib.import_module(mod_name)
            net_types.append(getattr(m, cls_name))
        except (ImportError, AttributeError):
            pass
    net_types = tuple(net_types)
    # Check the exception itself and any wrapped cause
    for e in (exc, getattr(exc, "__cause__", None)):
        if e is not None and isinstance(e, net_types):
            return True
    msg = str(exc).lower()
    return any(k in msg for k in ("connection", "timeout", "unreachable", "network", "dns", "name resolution"))

def _enqueue_screenshot(path: str, conf: dict):
    """Add a screenshot to the offline queue for later processing."""
    deck = conf.get("deck", "")
    # Snapshot only what's needed to process later (never store API keys)
    entry = {
        "path": path,
        "ts": time.time(),
        "deck": deck,
        "conf": {
            "model": conf.get("model"),
            "custom_prompt": conf.get("custom_prompt", ""),
        },
    }
    with _queue_lock:
        _offline_queue.append(entry)
        _save_queue()
    count = len(_offline_queue)
    _push_event({
        "type": "offline_queued",
        "message": f"Offline — screenshot queued ({count} pending)",
        "queue_count": count,
    })

def _process_queue():
    """Try to process all queued screenshots. Serialized via _queue_processing lock."""
    if not _queue_processing.acquire(blocking=False):
        return  # another _process_queue is already running
    try:
        _process_queue_inner()
    finally:
        _queue_processing.release()

def _process_queue_inner():
    with _queue_lock:
        total = len(_offline_queue)
    if total == 0:
        return

    processed = 0
    total_added = 0
    total_dupes = 0

    while True:
        # Dequeue atomically to avoid TOCTOU race
        with _queue_lock:
            if not _offline_queue:
                break
            entry = _offline_queue.pop(0)
            _save_queue()

        path = entry["path"]
        deck = entry["deck"]
        age = time.time() - entry.get("ts", 0)

        # Skip expired entries
        if age > QUEUE_TTL_SECS:
            log.info("Skipping expired queue entry: %s (%.0fh old)", Path(path).name, age / 3600)
            continue

        # Reconstruct config from current settings (API keys from live config, not queue)
        conf = {**cfg.load(), **entry["conf"]}
        conf["deck_context"] = fetch_deck_cards(deck)

        if not Path(path).exists():
            continue

        try:
            cards = models.generate_cards(path, conf)
            result = _add_cards_to_anki(cards, path, deck)
            batch_id = result["batch_id"]

            added_cards = [c for c in cards if c.get("note_id")]
            with _recent_lock:
                for card in reversed(added_cards):
                    _recent_cards.insert(0, {
                        "front": card["front"], "back": card["back"],
                        "deck": deck, "ts": time.time(),
                        "batch_id": batch_id, "note_id": card["note_id"],
                    })
                del _recent_cards[MAX_RECENT_CARDS:]
                _save_state()

            if added_cards:
                _push_event({
                    "type": "done", "message": "",
                    "cards": added_cards, "batch_id": batch_id,
                })

            processed += 1
            total_added += result["added"]
            total_dupes += result["duplicates"]

        except Exception as e:
            if _is_network_error(e):
                # Re-enqueue at front for retry
                with _queue_lock:
                    _offline_queue.insert(0, entry)
                    _save_queue()
                return
            _push_event({"type": "error", "message": _redact(f"Failed to process queued {Path(path).name}: {e}")})
            with _queue_lock:
                if _offline_queue and _offline_queue[0] is entry:
                    _offline_queue.pop(0)
                    _save_queue()

    # Single summary — this is also the "back online" signal
    if processed > 0:
        msg = f"Back online — processed {processed} queued screenshot{'' if processed == 1 else 's'}, {total_added} card(s) added"
        if total_dupes:
            msg += f" ({total_dupes} skipped as duplicates)"
        _push_event({"type": "queue_clear", "queue_count": 0, "message": msg})

def _queue_worker():
    """Background thread: periodically retries queued screenshots."""
    while True:
        time.sleep(QUEUE_RETRY_SECS)
        with _queue_lock:
            if not _offline_queue:
                continue
        _process_queue()


# ── YouTube video state ─────────────────────────────────────────────────────
_video_lock = threading.Lock()
_loaded_video: youtube.VideoMeta | None = None
_extension_connected = False
_extension_path = str(Path(__file__).parent / "extension")


def _push_event(data: dict):
    # Persist log-worthy events for replay on reconnect
    etype = data.get("type", "")
    if etype in ("progress", "done", "error", "undo", "card_deleted", "session_start", "session_stop", "offline_queued", "queue_clear"):
        entry = {
            "message": data.get("message", ""),
            "type":    etype,
            "ts":      time.time(),
        }
        if "batch_id" in data:
            entry["batch_id"] = data["batch_id"]
        with _activity_lock:
            _activity_log.insert(0, entry)
            del _activity_log[MAX_ACTIVITY_LOG:]
            _save_state()

    with _sse_lock:
        dead = []
        for q in _sse_subscribers:
            try:
                q.put_nowait(data)
            except queue.Full:
                dead.append(q)
        for q in dead:
            _sse_subscribers.remove(q)


# ── AnkiConnect helper ────────────────────────────────────────────────────────────
def _ankiconnect(action: str, **params):
    import requests
    payload = json.dumps({"action": action, "version": 6, "params": params})
    last_err = None
    for attempt in range(ANKICONNECT_RETRIES + 1):
        try:
            response = requests.post(ANKICONNECT_URL, data=payload, timeout=ANKICONNECT_TIMEOUT)
            result = response.json()
            if result.get("error"):
                raise Exception(f"AnkiConnect error: {result['error']}")
            return result["result"]
        except Exception as e:
            last_err = e
            if attempt < ANKICONNECT_RETRIES and _is_network_error(e):
                time.sleep(1)
                continue
            raise
    raise last_err


def _strip_html_preserve_math(text: str) -> str:
    """Convert Anki's <anki-mathjax> tags to \\( \\) delimiters, then strip remaining HTML."""
    text = re.sub(r'<anki-mathjax block="true">(.*?)</anki-mathjax>', r'\\[\1\\]', text, flags=re.DOTALL)
    text = re.sub(r'<anki-mathjax>(.*?)</anki-mathjax>', r'\\(\1\\)', text, flags=re.DOTALL)
    return re.sub(r"<[^>]+>", "", text).strip()


def fetch_deck_cards(deck: str, limit: int = 30) -> list[dict]:
    """Fetch the most recent cards from a deck for LLM context. Never raises."""
    try:
        note_ids = _ankiconnect("findNotes", query=f'"deck:{deck}"')
        if not note_ids:
            return []
        # Take the most recent cards (findNotes returns creation order)
        selected = note_ids[-limit:]
        notes = _ankiconnect("notesInfo", notes=selected)
        cards = []
        for n in notes:
            front = n.get("fields", {}).get("Front", {}).get("value", "")
            back = n.get("fields", {}).get("Back", {}).get("value", "")
            # Convert Anki's internal MathJax tags back to delimiters, then strip HTML
            front = _strip_html_preserve_math(front)
            back = _strip_html_preserve_math(back)
            if front:
                cards.append({
                    "front": front,
                    "back": back[:200],
                    "tags": n.get("tags", []),
                })
        return cards
    except Exception:
        return []


# ── Watchdog ──────────────────────────────────────────────────────────────────────
class ScreenshotHandler(FileSystemEventHandler):
    def on_created(self, event):
        if event.is_directory or not event.src_path.endswith(".png"):
            return
        # Skip multi-screenshot temp files and dot-prefixed files
        fname = Path(event.src_path).name
        if fname.startswith(".") or fname.startswith("multi_"):
            return
        path = event.src_path
        time.sleep(0.5)  # let screencapture finish writing

        # Validate screenshot — tiny images are cancelled selections
        try:
            with Image.open(path) as img:
                w, h = img.size
            if w < 50 or h < 50:
                _push_event({"type": "error", "message": f"Cancelled selection ({w}x{h}). Skipping."})
                return
        except Exception:
            pass  # if we can't read it, let later code handle the error

        conf = cfg.load()
        if not conf.get("session_active"):
            return

        deck = conf.get("deck", "").strip()
        if not deck:
            _push_event({"type": "error", "message": "No deck set — open localhost:5789 to configure."})
            return

        filename = Path(path).name
        _push_event({"type": "progress", "message": f"Processing {filename}..."})

        conf["deck_context"] = fetch_deck_cards(deck)

        # Video source: attach transcript context
        source = conf.get("deck_sources", {}).get(deck, {}).get("source", "screen")
        timestamp = None
        if source == "video":
            with _video_lock:
                video = _loaded_video
            if video and video.transcript:
                ts = conf.get("deck_sources", {}).get(deck, {}).get("timestamp")
                if ts is not None:
                    timestamp = float(ts)
                else:
                    # Use end of transcript as fallback (latest point)
                    timestamp = video.duration
                chunk = youtube.get_transcript_chunk(video.transcript, timestamp)
                if chunk:
                    conf["transcript_context"] = chunk
                    conf["timestamp"] = timestamp
                    conf["video_title"] = video.title
                    conf["video_id"] = video.video_id

        try:
            cards = models.generate_cards(path, conf)
            if not cards:
                _push_event({"type": "done", "message": "No cards generated — screenshot may not contain study-worthy content.", "cards": [], "batch_id": None})
                return
            _push_event({"type": "progress", "message": f"{len(cards)} card(s) generated, adding to Anki..."})

            # Add timestamp tag to video-sourced cards
            if timestamp is not None:
                ts_tag = f"yt-{youtube.format_timestamp(timestamp).replace(':', '')}"
                for card in cards:
                    card.setdefault("tags", []).append(ts_tag)

            result = _add_cards_to_anki(cards, path, deck)
            batch_id = result["batch_id"]

            added_cards = [c for c in cards if c.get("note_id")]
            with _recent_lock:
                for card in reversed(added_cards):
                    entry = {
                        "front":    card["front"],
                        "back":     card["back"],
                        "deck":     deck,
                        "ts":       time.time(),
                        "batch_id": batch_id,
                        "note_id":  card["note_id"],
                    }
                    if timestamp is not None:
                        entry["yt_timestamp"] = timestamp
                        entry["video_id"] = conf.get("video_id", "")
                    _recent_cards.insert(0, entry)
                del _recent_cards[MAX_RECENT_CARDS:]
                _save_state()

            msg = f"Added {result['added']} card(s) to '{deck}'"
            if result["duplicates"]:
                msg += f" ({result['duplicates']} duplicate(s) skipped)"

            _push_event({
                "type":     "done",
                "message":  msg,
                "cards":    added_cards,
                "batch_id": batch_id,
            })
        except Exception as e:
            if _is_network_error(e):
                _enqueue_screenshot(path, conf)
            else:
                _push_event({"type": "error", "message": str(e)})


def _add_cards_to_anki(cards: list[dict], image_path: str, deck: str) -> dict:
    """Returns {"added": int, "duplicates": int}."""
    existing = _ankiconnect("deckNames")
    if deck not in existing:
        _ankiconnect("createDeck", deck=deck)
        _push_event({"type": "progress", "message": f"Created new deck '{deck}'"})

    added = 0
    duplicates = 0
    note_ids = []

    # If any card is flagged as an image card, attach the image to ALL cards
    has_image = any(c.get("is_image_card") for c in cards)
    if has_image:
        fname = Path(image_path).name
        b64   = models.encode_image(image_path)
        _ankiconnect("storeMediaFile", filename=fname, data=b64)

    for card in cards:
        back = card["back"]
        if has_image:
            back += f'<br><img src="{fname}">'

        note = {
            "deckName":  deck,
            "modelName": "Basic",
            "fields":    {"Front": card["front"], "Back": back},
            "tags":      card.get("tags", []),
            "options":   {"allowDuplicate": False},
        }
        try:
            note_id = _ankiconnect("addNote", note=note)
            if note_id:
                note_ids.append(note_id)
                card["note_id"] = note_id
            added += 1
        except Exception as e:
            if "duplicate" not in str(e).lower():
                raise
            duplicates += 1

    batch_id = uuid.uuid4().hex[:8]
    with _batches_lock:
        _batches[batch_id] = note_ids
        # Keep only last 10 batches
        while len(_batches) > MAX_BATCHES:
            oldest = next(iter(_batches))
            del _batches[oldest]
        _save_state()

    return {"added": added, "duplicates": duplicates, "batch_id": batch_id}


# ── Routes ────────────────────────────────────────────────────────────────────────
@app.route("/")
def index():
    return send_from_directory(str(BASE_DIR / "web" / "templates"), "index.html")


@app.route("/api/decks")
def api_decks():
    try:
        decks = _ankiconnect("deckNames")
        return jsonify(sorted(decks))
    except Exception as e:
        return jsonify({"error": str(e)}), 503


@app.route("/api/config", methods=["GET"])
def api_config_get():
    return jsonify(cfg.load())


@app.route("/api/config", methods=["POST"])
def api_config_post():
    data = request.get_json(force=True)
    conf = cfg.load()
    for key in ("deck", "model", "api_keys", "custom_prompt", "deck_prompts", "deck_sources", "skip_delete_confirm"):
        if key in data:
            conf[key] = data[key]
    cfg.save(conf)
    return jsonify({"ok": True})


@app.route("/api/models/<provider>")
def api_models(provider):
    """Fetch available models from the provider's API. Returns top 10 most relevant."""
    import requests as req

    MAX_MODELS = 10
    conf = cfg.load()
    api_key = conf.get("api_keys", {}).get(provider, "")
    if not api_key:
        return jsonify([])

    try:
        if provider == "anthropic":
            r = req.get(
                "https://api.anthropic.com/v1/models",
                headers={"x-api-key": api_key, "anthropic-version": "2023-06-01"},
                timeout=5,
            )
            r.raise_for_status()
            # Only claude models, sorted newest first
            models = sorted(
                [m["id"] for m in r.json().get("data", []) if m["id"].startswith("claude-")],
                reverse=True,
            )[:MAX_MODELS]

        elif provider == "openai":
            r = req.get(
                "https://api.openai.com/v1/models",
                headers={"Authorization": f"Bearer {api_key}"},
                timeout=5,
            )
            r.raise_for_status()
            all_models = r.json().get("data", [])
            # Filter to chat models, skip embeddings/tts/dall-e/whisper/search etc.
            skip = ("embed", "tts", "dall-e", "whisper", "davinci", "babbage",
                    "moderation", "search", "similarity", "instruct")
            chat_models = [
                m for m in all_models
                if not any(k in m["id"] for k in skip)
                and any(k in m["id"] for k in ("gpt-", "o1", "o3", "o4", "chatgpt"))
            ]
            # Sort by creation date (newest first)
            chat_models.sort(key=lambda m: m.get("created", 0), reverse=True)
            models = [m["id"] for m in chat_models][:MAX_MODELS]

        elif provider == "groq":
            r = req.get(
                "https://api.groq.com/openai/v1/models",
                headers={"Authorization": f"Bearer {api_key}"},
                timeout=5,
            )
            r.raise_for_status()
            all_models = r.json().get("data", [])
            all_models.sort(key=lambda m: m.get("created", 0), reverse=True)
            models = [m["id"] for m in all_models][:MAX_MODELS]

        elif provider == "gemini":
            r = req.get(
                f"https://generativelanguage.googleapis.com/v1beta/models?key={api_key}",
                timeout=5,
            )
            r.raise_for_status()
            # Only gemini models that support generateContent, skip robotics/tts/etc
            skip_gemini = ("robotics", "tts", "image-preview", "customtools",
                           "embedding", "aqa", "bisheng")
            gemini_models = [
                m["name"].removeprefix("models/")
                for m in r.json().get("models", [])
                if "generateContent" in m.get("supportedGenerationMethods", [])
                and m["name"].startswith("models/gemini-")
                and not any(k in m["name"] for k in skip_gemini)
            ]
            # Sort reverse alpha (newest version numbers first)
            models = sorted(gemini_models, reverse=True)[:MAX_MODELS]

        else:
            return jsonify([])

        return jsonify(models)

    except Exception:
        return jsonify([])


@app.route("/api/undo", methods=["POST"])
def api_undo():
    data = request.get_json(force=True) if request.data else {}
    batch_id = data.get("batch_id", "")
    if not batch_id:
        return jsonify({"error": "No batch_id provided"}), 400
    with _batches_lock:
        ids = _batches.pop(batch_id, None)
    if not ids:
        return jsonify({"error": "Batch not found or already undone"}), 400
    try:
        _ankiconnect("deleteNotes", notes=ids)
        with _recent_lock:
            _recent_cards[:] = [c for c in _recent_cards if c.get("batch_id") != batch_id]
            _save_state()
        _push_event({"type": "undo", "message": f"Undid {len(ids)} card(s)", "batch_id": batch_id})
        return jsonify({"ok": True, "deleted": len(ids)})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/delete-card", methods=["POST"])
def api_delete_card():
    data = request.get_json(force=True) if request.data else {}
    note_id = data.get("note_id")
    if not note_id:
        return jsonify({"error": "No note_id provided"}), 400
    try:
        _ankiconnect("deleteNotes", notes=[note_id])
        with _recent_lock:
            _recent_cards[:] = [c for c in _recent_cards if c.get("note_id") != note_id]
        # Also remove from batch tracking
        with _batches_lock:
            for bid, ids in _batches.items():
                if note_id in ids:
                    ids.remove(note_id)
                    break
            _save_state()
        _push_event({"type": "card_deleted", "note_id": note_id, "message": "Deleted card from Anki"})
        return jsonify({"ok": True})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/session", methods=["GET"])
def api_session():
    conf = cfg.load()
    deck = conf.get("deck", "")
    source = conf.get("deck_sources", {}).get(deck, {}).get("source", "screen")
    return jsonify({"active": conf.get("session_active", False), "deck": deck, "source": source})


@app.route("/api/session/start", methods=["POST"])
def api_session_start():
    conf = cfg.load()
    conf["session_active"] = True
    cfg.save(conf)
    deck = conf.get("deck", "")
    model = conf.get("model", {})
    provider = model.get("provider", "")
    model_name = model.get("model_name", "")
    prompt = conf.get("custom_prompt", "").strip()
    msg = f"Session started — {deck}"
    if provider and model_name:
        msg += f" ({provider}/{model_name})"
    if prompt:
        # Show first ~60 chars of prompt
        short = prompt[:60] + ("..." if len(prompt) > 60 else "")
        msg += f' — "{short}"'
    _push_event({"type": "session_start", "deck": deck, "message": msg})
    return jsonify({"ok": True, "deck": deck})


@app.route("/api/session/stop", methods=["POST"])
def api_session_stop():
    conf = cfg.load()
    conf["session_active"] = False
    cfg.save(conf)
    _push_event({"type": "session_stop", "message": "Session stopped"})
    return jsonify({"ok": True})


@app.route("/api/connectivity")
def api_connectivity():
    """Quick check: can we reach the configured AI provider?"""
    import requests as req
    conf = cfg.load()
    provider = conf.get("model", {}).get("provider", "anthropic")
    urls = {
        "anthropic": "https://api.anthropic.com",
        "openai":    "https://api.openai.com",
        "groq":      "https://api.groq.com",
        "gemini":    "https://generativelanguage.googleapis.com",
    }
    if provider == "claude-code":
        from models import _find_claude_cli
        online = _find_claude_cli() is not None
        with _queue_lock:
            qc = len(_offline_queue)
        return jsonify({"online": online, "queue_count": qc})
    url = urls.get(provider)
    if not url:
        return jsonify({"online": True, "queue_count": len(_offline_queue)})
    try:
        req.head(url, timeout=3)
        online = True
    except Exception:
        online = False
    # If we just came back online and there are queued items, kick off processing
    if online and _offline_queue:
        threading.Thread(target=_process_queue, daemon=True).start()
    with _queue_lock:
        qc = len(_offline_queue)
    return jsonify({"online": online, "queue_count": qc})


@app.route("/api/youtube/load", methods=["POST"])
def api_youtube_load():
    """Load a YouTube video's transcript and metadata."""
    global _loaded_video
    data = request.get_json(force=True)
    url = data.get("url", "").strip()
    if not url:
        return jsonify({"error": "No URL provided"}), 400
    try:
        video = youtube.load_video(url)
        with _video_lock:
            _loaded_video = video
        return jsonify(video.to_dict())
    except Exception as e:
        return jsonify({"error": str(e)}), 400


@app.route("/api/youtube/status")
def api_youtube_status():
    """Return currently loaded video info or null."""
    with _video_lock:
        if _loaded_video:
            return jsonify(_loaded_video.to_dict())
    return jsonify(None)


@app.route("/api/youtube/clear", methods=["POST"])
def api_youtube_clear():
    """Clear the loaded video."""
    global _loaded_video
    with _video_lock:
        _loaded_video = None
    return jsonify({"ok": True})


@app.route("/api/extension/hello", methods=["POST"])
def api_extension_hello():
    """Extension registration ping — marks extension as connected."""
    global _extension_connected
    _extension_connected = True
    return jsonify({"ok": True})


@app.route("/api/extension/status")
def api_extension_status():
    """Return extension connection status and install path."""
    return jsonify({
        "connected": _extension_connected,
        "path": _extension_path,
    })


@app.route("/api/source/cycle", methods=["POST"])
def api_source_cycle():
    """Cycle through sources: screen → multi → video → screen."""
    conf = cfg.load()
    deck = conf.get("deck", "")
    if not deck:
        return jsonify({"error": "No deck set"}), 400
    sources = ["screen", "multi", "video"]
    current = conf.get("deck_sources", {}).get(deck, {}).get("source", "screen")
    idx = sources.index(current) if current in sources else 0
    new_source = sources[(idx + 1) % len(sources)]
    deck_sources = conf.get("deck_sources", {})
    if new_source == "screen":
        deck_sources.pop(deck, None)
    else:
        deck_sources[deck] = {**deck_sources.get(deck, {}), "source": new_source}
    conf["deck_sources"] = deck_sources
    cfg.save(conf)
    _push_event({"type": "source_changed", "source": new_source, "deck": deck})
    return jsonify({"ok": True, "source": new_source})


@app.route("/api/multi/finish", methods=["POST"])
def api_multi_finish():
    """Stitch multiple temp screenshots into one and drop into incoming."""
    data = request.get_json(force=True)
    paths = data.get("paths", [])
    if not paths:
        return jsonify({"error": "No paths provided"}), 400

    # Validate all paths exist and are within the screenshots directory
    images = []
    for p in paths:
        resolved = Path(p).resolve()
        if not resolved.is_relative_to(SCREENSHOTS_DIR.resolve()):
            return jsonify({"error": f"Path outside screenshots directory: {p}"}), 400
        if not resolved.exists():
            return jsonify({"error": f"File not found: {p}"}), 400
        images.append(Image.open(p))

    # Stitch vertically
    total_w = max(im.width for im in images)
    total_h = sum(im.height for im in images)
    result = Image.new("RGB", (total_w, total_h), (255, 255, 255))
    y = 0
    for im in images:
        result.paste(im, (0, y))
        y += im.height
    for im in images:
        im.close()

    import os
    ts = time.strftime("%Y%m%d_%H%M%S")
    dest = str(SCREENSHOTS_DIR / f"screenshot_{ts}.png")
    result.save(dest)

    # Clean up temp files
    for p in paths:
        try:
            os.remove(p)
        except OSError:
            pass

    return jsonify({"ok": True, "path": dest})


@app.route("/api/offline-queue")
def api_offline_queue():
    with _queue_lock:
        return jsonify({"count": len(_offline_queue), "items": [
            {"path": e["path"], "ts": e["ts"], "deck": e["deck"]} for e in _offline_queue
        ]})


@app.route("/api/events")
def api_events():
    q = queue.Queue(maxsize=100)
    with _sse_lock:
        _sse_subscribers.append(q)

    def stream():
        try:
            # Send recent cards + activity log immediately on connect
            with _recent_lock:
                snapshot = list(_recent_cards)
            with _batches_lock:
                undoable = list(_batches.keys())
            with _activity_lock:
                log_snapshot = list(_activity_log)
            with _queue_lock:
                queue_count = len(_offline_queue)
            yield f"data: {json.dumps({'type': 'recent', 'cards': snapshot, 'undoable_batches': undoable, 'activity_log': log_snapshot, 'queue_count': queue_count})}\n\n"
            # Stream live events
            while True:
                try:
                    event = q.get(timeout=15)
                    yield f"data: {json.dumps(event)}\n\n"
                except queue.Empty:
                    yield 'data: {"type":"ping"}\n\n'
        finally:
            with _sse_lock:
                try:
                    _sse_subscribers.remove(q)
                except ValueError:
                    pass

    return Response(
        stream(),
        mimetype="text/event-stream",
        headers={
            "Cache-Control":    "no-cache",
            "X-Accel-Buffering": "no",
            "Connection":        "keep-alive",
        },
    )


# ── Startup ───────────────────────────────────────────────────────────────────────
_seen_files: set[str] = set()

def _poll_screenshots():
    """Poll for new screenshots — FSEvents is unreliable under launchd."""
    global _seen_files
    handler = ScreenshotHandler()
    _seen_files = {p.name for p in SCREENSHOTS_DIR.glob("*.png")}
    while True:
        try:
            time.sleep(2)
            current = {p.name for p in SCREENSHOTS_DIR.glob("*.png")}
            new_files = current - _seen_files
            _seen_files = current
            for fname in sorted(new_files):
                fpath = str(SCREENSHOTS_DIR / fname)
                from watchdog.events import FileCreatedEvent
                handler.on_created(FileCreatedEvent(fpath))
        except Exception as e:
            print(f"Poll error: {e}", flush=True)


def _start_watchdog():
    SCREENSHOTS_DIR.mkdir(parents=True, exist_ok=True)
    t = threading.Thread(target=_poll_screenshots, daemon=True)
    t.start()
    # Start offline queue worker
    q = threading.Thread(target=_queue_worker, daemon=True)
    q.start()


if __name__ == "__main__":
    _start_watchdog()
    app.run(host="127.0.0.1", port=5789, threaded=True, use_reloader=False)
