import json
import queue
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

ANKICONNECT_URL = "http://localhost:8765"
SCREENSHOTS_DIR = Path.home() / "AnkiFox" / "incoming"
BASE_DIR        = Path(__file__).parent

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

# ── Recent cards (kept in memory, newest-first) ──────────────────────────────────
_recent_cards: list[dict] = []
_recent_lock  = threading.Lock()

# ── Activity log (kept in memory, newest-first) ──────────────────────────────────
_activity_log: list[dict] = []  # {"message": str, "type": str, "ts": float}
_activity_lock = threading.Lock()

# ── Undo: batch_id → list of note IDs ─────────────────────────────────────────────
_batches: dict[str, list[int]] = {}  # keeps last 10 batches
_batches_lock = threading.Lock()


def _push_event(data: dict):
    # Persist log-worthy events for replay on reconnect
    etype = data.get("type", "")
    if etype in ("progress", "done", "error", "undo"):
        with _activity_lock:
            _activity_log.insert(0, {
                "message": data.get("message", ""),
                "type":    etype,
                "ts":      time.time(),
            })
            del _activity_log[20:]  # keep last 20

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
    payload  = json.dumps({"action": action, "version": 6, "params": params})
    response = requests.post(ANKICONNECT_URL, data=payload, timeout=5)
    result   = response.json()
    if result.get("error"):
        raise Exception(f"AnkiConnect error: {result['error']}")
    return result["result"]


# ── Watchdog ──────────────────────────────────────────────────────────────────────
class ScreenshotHandler(FileSystemEventHandler):
    def on_created(self, event):
        if event.is_directory or not event.src_path.endswith(".png"):
            return
        path = event.src_path
        time.sleep(0.5)  # let screencapture finish writing

        # Validate screenshot — tiny images are usually cancelled selections
        try:
            with Image.open(path) as img:
                w, h = img.size
            if w < 50 or h < 50:
                _push_event({"type": "error", "message": f"Screenshot too small ({w}x{h}) — looks like a cancelled selection. Skipping."})
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

        try:
            cards = models.generate_cards(path, conf)
            _push_event({"type": "progress", "message": f"{len(cards)} card(s) generated, adding to Anki..."})

            result = _add_cards_to_anki(cards, path, deck)
            batch_id = result["batch_id"]

            with _recent_lock:
                for card in reversed(cards):
                    _recent_cards.insert(0, {
                        "front":    card["front"],
                        "back":     card["back"],
                        "deck":     deck,
                        "ts":       time.time(),
                        "batch_id": batch_id,
                    })
                del _recent_cards[10:]  # keep last 10

            msg = f"Added {result['added']} card(s) to '{deck}'"
            if result["duplicates"]:
                msg += f" ({result['duplicates']} duplicate(s) skipped)"

            _push_event({
                "type":     "done",
                "message":  msg,
                "cards":    cards,
                "batch_id": batch_id,
            })
        except Exception as e:
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
            added += 1
        except Exception as e:
            if "duplicate" not in str(e).lower():
                raise
            duplicates += 1

    batch_id = uuid.uuid4().hex[:8]
    with _batches_lock:
        _batches[batch_id] = note_ids
        # Keep only last 10 batches
        while len(_batches) > 10:
            oldest = next(iter(_batches))
            del _batches[oldest]

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
    for key in ("deck", "model", "api_keys", "custom_prompt", "deck_prompts"):
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
        _push_event({"type": "undo", "message": f"Undid {len(ids)} card(s)", "batch_id": batch_id})
        return jsonify({"ok": True, "deleted": len(ids)})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/session", methods=["GET"])
def api_session():
    conf = cfg.load()
    return jsonify({"active": conf.get("session_active", False), "deck": conf.get("deck", "")})


@app.route("/api/session/start", methods=["POST"])
def api_session_start():
    conf = cfg.load()
    conf["session_active"] = True
    cfg.save(conf)
    _push_event({"type": "session_start", "deck": conf.get("deck", "")})
    return jsonify({"ok": True, "deck": conf.get("deck", "")})


@app.route("/api/session/stop", methods=["POST"])
def api_session_stop():
    conf = cfg.load()
    conf["session_active"] = False
    cfg.save(conf)
    _push_event({"type": "session_stop"})
    return jsonify({"ok": True})


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
            if snapshot or log_snapshot:
                yield f"data: {json.dumps({'type': 'recent', 'cards': snapshot, 'undoable_batches': undoable, 'activity_log': log_snapshot})}\n\n"
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
def _start_watchdog():
    SCREENSHOTS_DIR.mkdir(parents=True, exist_ok=True)
    observer = Observer()
    observer.schedule(ScreenshotHandler(), str(SCREENSHOTS_DIR), recursive=False)
    observer.start()
    return observer


if __name__ == "__main__":
    observer = _start_watchdog()
    try:
        app.run(host="127.0.0.1", port=5789, threaded=True, use_reloader=False)
    finally:
        observer.stop()
        observer.join()
