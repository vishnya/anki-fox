import json
import pytest
from unittest.mock import MagicMock, patch

import flask_server
from flask_server import ScreenshotHandler


def make_event(path):
    event = MagicMock()
    event.src_path = path
    event.is_directory = False
    return event


def add_cards_via_handler(tmp_config, tiny_png, ankiconnect_side_effect, n_cards=2):
    """Helper: trigger ScreenshotHandler and return pushed events."""
    handler = ScreenshotHandler()
    event = make_event(tiny_png)
    conf = dict(tmp_config)
    conf["session_active"] = True
    conf["deck"] = "TestDeck"

    fake_cards = [
        {"front": f"Q{i}", "back": f"A{i}", "tags": [], "is_image_card": False}
        for i in range(n_cards)
    ]

    pushed_events = []
    with patch("flask_server.cfg.load", return_value=conf), \
         patch("flask_server.models.generate_cards", return_value=fake_cards), \
         patch("flask_server._ankiconnect", side_effect=ankiconnect_side_effect), \
         patch("flask_server._push_event", side_effect=lambda e: (pushed_events.append(e), flask_server._push_event.__wrapped__(e)) if False else pushed_events.append(e)), \
         patch("time.sleep"):
        handler.on_created(event)

    return pushed_events


class TestBatchTracking:
    """Cards added via a screenshot get a batch_id."""

    def test_done_event_has_batch_id(self, tmp_config, tiny_png):
        counter = [100000]
        def ac(action, **params):
            if action == "deckNames": return ["TestDeck"]
            if action == "addNote":
                counter[0] += 1
                return counter[0]
            return None

        events = add_cards_via_handler(tmp_config, tiny_png, ac, n_cards=3)
        done = [e for e in events if e.get("type") == "done"]
        assert len(done) == 1
        assert "batch_id" in done[0]
        assert len(done[0]["batch_id"]) == 8  # hex[:8]

    def test_recent_cards_have_batch_id(self, tmp_config, tiny_png):
        counter = [100000]
        def ac(action, **params):
            if action == "deckNames": return ["TestDeck"]
            if action == "addNote":
                counter[0] += 1
                return counter[0]
            return None

        add_cards_via_handler(tmp_config, tiny_png, ac, n_cards=2)
        assert all(c.get("batch_id") for c in flask_server._recent_cards)

    def test_two_batches_get_different_ids(self, tmp_config, tiny_png):
        counter = [100000]
        def ac(action, **params):
            if action == "deckNames": return ["TestDeck"]
            if action == "addNote":
                counter[0] += 1
                return counter[0]
            return None

        events1 = add_cards_via_handler(tmp_config, tiny_png, ac, n_cards=2)
        events2 = add_cards_via_handler(tmp_config, tiny_png, ac, n_cards=2)
        bid1 = [e for e in events1 if e["type"] == "done"][0]["batch_id"]
        bid2 = [e for e in events2 if e["type"] == "done"][0]["batch_id"]
        assert bid1 != bid2

    def test_batch_note_ids_stored(self, tmp_config, tiny_png):
        counter = [100000]
        def ac(action, **params):
            if action == "deckNames": return ["TestDeck"]
            if action == "addNote":
                counter[0] += 1
                return counter[0]
            return None

        events = add_cards_via_handler(tmp_config, tiny_png, ac, n_cards=3)
        bid = [e for e in events if e["type"] == "done"][0]["batch_id"]
        assert bid in flask_server._batches
        assert len(flask_server._batches[bid]) == 3


class TestUndoEndpoint:
    """POST /api/undo deletes a batch of notes."""

    def _setup_batch(self, tmp_config, tiny_png):
        counter = [100000]
        def ac(action, **params):
            if action == "deckNames": return ["TestDeck"]
            if action == "addNote":
                counter[0] += 1
                return counter[0]
            return None

        events = add_cards_via_handler(tmp_config, tiny_png, ac, n_cards=2)
        bid = [e for e in events if e["type"] == "done"][0]["batch_id"]
        return bid

    def test_undo_deletes_notes(self, flask_client, tmp_config, tiny_png, mock_ankiconnect):
        # Add cards through the handler
        flask_client.post("/api/config", json={"deck": "TestDeck"})
        flask_client.post("/api/session/start")

        fake_cards = [
            {"front": "Q1", "back": "A1", "tags": [], "is_image_card": False},
            {"front": "Q2", "back": "A2", "tags": [], "is_image_card": False},
        ]
        handler = ScreenshotHandler()
        event = make_event(tiny_png)
        with patch("flask_server.models.generate_cards", return_value=fake_cards), \
             patch("time.sleep"):
            handler.on_created(event)

        # Get the batch_id
        assert len(flask_server._batches) == 1
        bid = list(flask_server._batches.keys())[0]

        # Undo
        resp = flask_client.post("/api/undo", json={"batch_id": bid})
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["ok"] is True
        assert data["deleted"] == 2

        # Verify batch removed
        assert bid not in flask_server._batches
        # Verify deleteNotes was called
        delete_calls = [
            c for c in mock_ankiconnect.call_args_list if c[0][0] == "deleteNotes"
        ]
        assert len(delete_calls) == 1

    def test_undo_removes_from_recent_cards(self, flask_client, tmp_config, tiny_png, mock_ankiconnect):
        flask_client.post("/api/config", json={"deck": "TestDeck"})
        flask_client.post("/api/session/start")

        fake_cards = [
            {"front": "Q1", "back": "A1", "tags": [], "is_image_card": False},
        ]
        handler = ScreenshotHandler()
        event = make_event(tiny_png)
        with patch("flask_server.models.generate_cards", return_value=fake_cards), \
             patch("time.sleep"):
            handler.on_created(event)

        assert len(flask_server._recent_cards) == 1
        bid = list(flask_server._batches.keys())[0]

        flask_client.post("/api/undo", json={"batch_id": bid})
        assert len(flask_server._recent_cards) == 0

    def test_undo_no_batch_id_returns_400(self, flask_client):
        resp = flask_client.post("/api/undo", json={})
        assert resp.status_code == 400

    def test_undo_unknown_batch_returns_400(self, flask_client):
        resp = flask_client.post("/api/undo", json={"batch_id": "nonexistent"})
        assert resp.status_code == 400

    def test_undo_same_batch_twice_returns_400(self, flask_client, tmp_config, tiny_png, mock_ankiconnect):
        flask_client.post("/api/config", json={"deck": "TestDeck"})
        flask_client.post("/api/session/start")

        fake_cards = [{"front": "Q", "back": "A", "tags": [], "is_image_card": False}]
        handler = ScreenshotHandler()
        event = make_event(tiny_png)
        with patch("flask_server.models.generate_cards", return_value=fake_cards), \
             patch("time.sleep"):
            handler.on_created(event)

        bid = list(flask_server._batches.keys())[0]
        resp1 = flask_client.post("/api/undo", json={"batch_id": bid})
        assert resp1.status_code == 200
        resp2 = flask_client.post("/api/undo", json={"batch_id": bid})
        assert resp2.status_code == 400


class TestActivityLogPersistence:
    """Activity log entries are stored server-side."""

    def test_progress_events_stored(self, tmp_config, tiny_png):
        counter = [100000]
        def ac(action, **params):
            if action == "deckNames": return ["TestDeck"]
            if action == "addNote":
                counter[0] += 1
                return counter[0]
            return None

        handler = ScreenshotHandler()
        event = make_event(tiny_png)
        conf = dict(tmp_config)
        conf["session_active"] = True
        conf["deck"] = "TestDeck"
        fake_cards = [
            {"front": "Q1", "back": "A1", "tags": [], "is_image_card": False},
        ]
        # Don't mock _push_event so it actually stores to _activity_log
        with patch("flask_server.cfg.load", return_value=conf), \
             patch("flask_server.models.generate_cards", return_value=fake_cards), \
             patch("flask_server._ankiconnect", side_effect=ac), \
             patch("time.sleep"):
            handler.on_created(event)

        assert len(flask_server._activity_log) >= 2
        types = [e["type"] for e in flask_server._activity_log]
        assert "done" in types
        assert "progress" in types

    def test_activity_log_capped_at_20(self):
        # Manually push 25 events
        for i in range(25):
            flask_server._push_event({"type": "progress", "message": f"msg {i}"})
        assert len(flask_server._activity_log) == 20

    def test_activity_log_newest_first(self):
        flask_server._push_event({"type": "progress", "message": "first"})
        flask_server._push_event({"type": "progress", "message": "second"})
        assert flask_server._activity_log[0]["message"] == "second"
        assert flask_server._activity_log[1]["message"] == "first"

    def test_ping_not_stored(self):
        flask_server._push_event({"type": "ping"})
        assert len(flask_server._activity_log) == 0


class TestDeleteCard:
    """POST /api/delete-card deletes a single note."""

    def test_delete_single_card(self, flask_client, tmp_config, tiny_png, mock_ankiconnect):
        flask_client.post("/api/config", json={"deck": "TestDeck"})
        flask_client.post("/api/session/start")

        fake_cards = [
            {"front": "Q1", "back": "A1", "tags": [], "is_image_card": False},
            {"front": "Q2", "back": "A2", "tags": [], "is_image_card": False},
        ]
        handler = ScreenshotHandler()
        event = make_event(tiny_png)
        with patch("flask_server.models.generate_cards", return_value=fake_cards), \
             patch("time.sleep"):
            handler.on_created(event)

        assert len(flask_server._recent_cards) == 2
        note_id = flask_server._recent_cards[0].get("note_id")
        assert note_id is not None

        resp = flask_client.post("/api/delete-card", json={"note_id": note_id})
        assert resp.status_code == 200
        assert resp.get_json()["ok"] is True
        assert len(flask_server._recent_cards) == 1

    def test_delete_card_removes_from_batch(self, flask_client, tmp_config, tiny_png, mock_ankiconnect):
        flask_client.post("/api/config", json={"deck": "TestDeck"})
        flask_client.post("/api/session/start")

        fake_cards = [
            {"front": "Q1", "back": "A1", "tags": [], "is_image_card": False},
        ]
        handler = ScreenshotHandler()
        event = make_event(tiny_png)
        with patch("flask_server.models.generate_cards", return_value=fake_cards), \
             patch("time.sleep"):
            handler.on_created(event)

        bid = list(flask_server._batches.keys())[0]
        note_id = flask_server._recent_cards[0]["note_id"]

        flask_client.post("/api/delete-card", json={"note_id": note_id})
        assert note_id not in flask_server._batches[bid]

    def test_delete_card_no_note_id_returns_400(self, flask_client):
        resp = flask_client.post("/api/delete-card", json={})
        assert resp.status_code == 400


class TestSessionSSEBroadcast:
    """Session start/stop push SSE events."""

    def test_session_start_pushes_event(self, flask_client):
        flask_client.post("/api/config", json={"deck": "MyDeck"})
        flask_client.post("/api/session/start")
        types = [e["type"] for e in flask_server._activity_log]
        assert "session_start" in types

    def test_session_stop_pushes_event(self, flask_client):
        flask_client.post("/api/session/start")
        flask_client.post("/api/session/stop")
        types = [e["type"] for e in flask_server._activity_log]
        assert "session_stop" in types


class TestNoCacheHeaders:
    """Static files get no-cache headers."""

    def test_html_no_cache(self, flask_client):
        resp = flask_client.get("/")
        assert resp.headers.get("Cache-Control") == "no-cache, no-store, must-revalidate"

    def test_js_no_cache(self, flask_client):
        resp = flask_client.get("/static/app.js")
        assert "no-cache" in resp.headers.get("Cache-Control", "")
