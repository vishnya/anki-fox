import json
import time
import pytest
from unittest.mock import MagicMock, patch

import flask_server
from flask_server import ScreenshotHandler


def make_event(path):
    event = MagicMock()
    event.src_path = path
    event.is_directory = False
    return event


class TestNetworkErrorDetection:
    """_is_network_error correctly identifies connectivity failures."""

    def test_connection_error(self):
        import requests
        assert flask_server._is_network_error(requests.exceptions.ConnectionError())

    def test_timeout_error(self):
        import requests
        assert flask_server._is_network_error(requests.exceptions.Timeout())

    def test_os_error(self):
        assert flask_server._is_network_error(OSError("Network is unreachable"))

    def test_wrapped_connection_error(self):
        """An exception whose __cause__ is a ConnectionError should match."""
        import requests
        outer = Exception("API call failed")
        outer.__cause__ = requests.exceptions.ConnectionError()
        assert flask_server._is_network_error(outer)

    def test_message_heuristic(self):
        assert flask_server._is_network_error(Exception("Connection refused"))
        assert flask_server._is_network_error(Exception("DNS name resolution failed"))

    def test_non_network_error(self):
        assert not flask_server._is_network_error(ValueError("invalid JSON"))
        assert not flask_server._is_network_error(Exception("duplicate card"))

    def test_anthropic_api_connection_error(self):
        import anthropic
        exc = anthropic.APIConnectionError(request=MagicMock())
        assert flask_server._is_network_error(exc)

    def test_anthropic_api_timeout_error(self):
        import anthropic
        exc = anthropic.APITimeoutError(request=MagicMock())
        assert flask_server._is_network_error(exc)

    def test_openai_api_connection_error(self):
        import openai
        exc = openai.APIConnectionError(request=MagicMock())
        assert flask_server._is_network_error(exc)

    def test_httpx_connect_error(self):
        import httpx
        exc = httpx.ConnectError("Failed to connect")
        assert flask_server._is_network_error(exc)


class TestScreenshotQueuing:
    """When generate_cards fails with a network error, the screenshot is queued."""

    def test_network_error_queues_screenshot(self, tmp_config, tiny_png):
        handler = ScreenshotHandler()
        event = make_event(tiny_png)
        conf = dict(tmp_config)
        conf["session_active"] = True
        conf["deck"] = "TestDeck"

        import requests
        net_err = requests.exceptions.ConnectionError("no internet")

        pushed = []
        with patch("flask_server.cfg.load", return_value=conf), \
             patch("flask_server.models.generate_cards", side_effect=net_err), \
             patch("flask_server._push_event", side_effect=pushed.append), \
             patch("time.sleep"):
            handler.on_created(event)

        # Should be queued, not errored
        assert len(flask_server._offline_queue) == 1
        assert flask_server._offline_queue[0]["path"] == tiny_png
        assert flask_server._offline_queue[0]["deck"] == "TestDeck"

        # Should have pushed an offline_queued event
        queued_events = [e for e in pushed if e["type"] == "offline_queued"]
        assert len(queued_events) == 1
        assert "1 pending" in queued_events[0]["message"]

    def test_anthropic_sdk_error_queues_screenshot(self, tmp_config, tiny_png):
        """The real error type thrown by the anthropic SDK when offline."""
        import anthropic
        handler = ScreenshotHandler()
        event = make_event(tiny_png)
        conf = dict(tmp_config)
        conf["session_active"] = True
        conf["deck"] = "TestDeck"

        sdk_err = anthropic.APIConnectionError(request=MagicMock())

        pushed = []
        with patch("flask_server.cfg.load", return_value=conf), \
             patch("flask_server.models.generate_cards", side_effect=sdk_err), \
             patch("flask_server._push_event", side_effect=pushed.append), \
             patch("time.sleep"):
            handler.on_created(event)

        assert len(flask_server._offline_queue) == 1
        queued_events = [e for e in pushed if e["type"] == "offline_queued"]
        assert len(queued_events) == 1

    def test_non_network_error_not_queued(self, tmp_config, tiny_png):
        handler = ScreenshotHandler()
        event = make_event(tiny_png)
        conf = dict(tmp_config)
        conf["session_active"] = True
        conf["deck"] = "TestDeck"

        pushed = []
        with patch("flask_server.cfg.load", return_value=conf), \
             patch("flask_server.models.generate_cards", side_effect=ValueError("bad json")), \
             patch("flask_server._push_event", side_effect=pushed.append), \
             patch("time.sleep"):
            handler.on_created(event)

        assert len(flask_server._offline_queue) == 0
        error_events = [e for e in pushed if e["type"] == "error"]
        assert len(error_events) == 1

    def test_multiple_screenshots_queue_in_order(self, tmp_config, tmp_path):
        from PIL import Image

        conf = dict(tmp_config)
        conf["session_active"] = True
        conf["deck"] = "TestDeck"

        import requests
        net_err = requests.exceptions.ConnectionError()

        handler = ScreenshotHandler()
        paths = []
        for i in range(3):
            p = tmp_path / f"shot_{i}.png"
            Image.new("RGB", (100, 100)).save(str(p))
            paths.append(str(p))

        with patch("flask_server.cfg.load", return_value=conf), \
             patch("flask_server.models.generate_cards", side_effect=net_err), \
             patch("flask_server._push_event"), \
             patch("time.sleep"):
            for p in paths:
                handler.on_created(make_event(p))

        assert len(flask_server._offline_queue) == 3
        assert [e["path"] for e in flask_server._offline_queue] == paths


class TestQueuePersistence:
    """Queue survives save/load cycle."""

    def test_save_and_load_queue(self, tmp_path, monkeypatch):
        monkeypatch.setattr(flask_server, "_QUEUE_FILE", tmp_path / "q.json")
        flask_server._offline_queue.clear()
        flask_server._offline_queue.append({"path": "/tmp/a.png", "ts": time.time(), "deck": "D", "conf": {}})
        flask_server._save_queue()

        loaded = flask_server._load_queue()
        assert len(loaded) == 1
        assert loaded[0]["path"] == "/tmp/a.png"


class TestProcessQueue:
    """_process_queue processes items and clears the queue."""

    def test_processes_queued_item(self, tmp_config, tiny_png, mock_ankiconnect):
        conf = dict(tmp_config)
        conf["deck"] = "TestDeck"
        conf["session_active"] = True

        flask_server._offline_queue.append({
            "path": tiny_png,
            "ts": time.time(),
            "deck": "TestDeck",
            "conf": {
                "model": conf["model"],
                                "custom_prompt": "",
            },
        })

        fake_cards = [{"front": "Q1", "back": "A1", "tags": [], "is_image_card": False}]

        pushed = []
        with patch("flask_server.cfg.load", return_value=conf), \
             patch("flask_server.models.generate_cards", return_value=fake_cards), \
             patch("flask_server._push_event", side_effect=pushed.append):
            flask_server._process_queue()

        assert len(flask_server._offline_queue) == 0
        assert len(flask_server._recent_cards) == 1

        # Should have exactly: 1 done (cards, silent) + 1 queue_clear (summary)
        clear_events = [e for e in pushed if e["type"] == "queue_clear"]
        assert len(clear_events) == 1
        assert "1 card(s) added" in clear_events[0]["message"]
        assert "Back online" in clear_events[0]["message"]

        # No per-item activity entries — only the summary
        done_with_msg = [e for e in pushed if e["type"] == "done" and e.get("message")]
        assert len(done_with_msg) == 0
        # No "Back online — processing..." progress events (deck creation progress is ok)
        queue_progress = [e for e in pushed if e["type"] == "progress" and "queued" in e.get("message", "")]
        assert len(queue_progress) == 0

    def test_skips_deleted_screenshot(self, tmp_config):
        conf = dict(tmp_config)
        flask_server._offline_queue.append({
            "path": "/nonexistent/deleted.png",
            "ts": time.time(),
            "deck": "TestDeck",
            "conf": {"model": conf["model"], "api_keys": conf["api_keys"], "custom_prompt": ""},
        })

        with patch("flask_server.cfg.load", return_value=conf), \
             patch("flask_server._push_event"):
            flask_server._process_queue()

        assert len(flask_server._offline_queue) == 0

    def test_stops_on_still_offline(self, tmp_config, tiny_png):
        """If processing fails with another network error, stop retrying."""
        import requests

        conf = dict(tmp_config)
        flask_server._offline_queue.append({
            "path": tiny_png,
            "ts": time.time(),
            "deck": "TestDeck",
            "conf": {"model": conf["model"], "api_keys": conf["api_keys"], "custom_prompt": ""},
        })

        with patch("flask_server.cfg.load", return_value=conf), \
             patch("flask_server.models.generate_cards",
                   side_effect=requests.exceptions.ConnectionError()), \
             patch("flask_server._push_event"):
            flask_server._process_queue()

        # Item should still be in the queue
        assert len(flask_server._offline_queue) == 1

    def test_non_network_error_skips_item(self, tmp_config, tiny_png):
        """A non-network error (e.g. bad JSON from API) should skip the item, not block the queue."""
        conf = dict(tmp_config)
        flask_server._offline_queue.append({
            "path": tiny_png,
            "ts": time.time(),
            "deck": "TestDeck",
            "conf": {"model": conf["model"], "api_keys": conf["api_keys"], "custom_prompt": ""},
        })

        pushed = []
        with patch("flask_server.cfg.load", return_value=conf), \
             patch("flask_server.models.generate_cards",
                   side_effect=ValueError("invalid JSON from model")), \
             patch("flask_server._push_event", side_effect=pushed.append):
            flask_server._process_queue()

        assert len(flask_server._offline_queue) == 0
        error_events = [e for e in pushed if e["type"] == "error"]
        assert len(error_events) == 1


class TestDuplicateFiltering:
    """Duplicate cards (no note_id) should not appear in recent cards."""

    def test_duplicates_excluded_from_recent_cards(self, tmp_config, tiny_png):
        """When AnkiConnect rejects a duplicate, it should not appear in recent cards."""
        handler = ScreenshotHandler()
        event = make_event(tiny_png)
        conf = dict(tmp_config)
        conf["session_active"] = True
        conf["deck"] = "TestDeck"

        fake_cards = [
            {"front": "Q1", "back": "A1", "tags": [], "is_image_card": False},
            {"front": "Q2", "back": "A2", "tags": [], "is_image_card": False},
            {"front": "Q3", "back": "A3", "tags": [], "is_image_card": False},
        ]

        call_count = 0
        def ankiconnect_side_effect(action, **params):
            nonlocal call_count
            if action == "deckNames":
                return ["TestDeck"]
            if action == "addNote":
                call_count += 1
                if call_count == 2:
                    raise Exception("cannot create note because it is a duplicate")
                return 10000 + call_count
            return None

        pushed = []
        with patch("flask_server.cfg.load", return_value=conf), \
             patch("flask_server.models.generate_cards", return_value=fake_cards), \
             patch("flask_server._ankiconnect", side_effect=ankiconnect_side_effect), \
             patch("flask_server._push_event", side_effect=pushed.append), \
             patch("time.sleep"):
            handler.on_created(event)

        # Only 2 cards should be in recent (the duplicate was skipped)
        assert len(flask_server._recent_cards) == 2
        assert all(c["note_id"] is not None for c in flask_server._recent_cards)

        # The done event should only contain the 2 added cards
        done_events = [e for e in pushed if e["type"] == "done"]
        assert len(done_events) == 1
        assert len(done_events[0]["cards"]) == 2

    def test_duplicates_excluded_from_queue_processing(self, tmp_config, tiny_png, mock_ankiconnect):
        """Duplicates during queue processing should also be excluded from recent cards."""
        conf = dict(tmp_config)
        conf["deck"] = "TestDeck"

        flask_server._offline_queue.append({
            "path": tiny_png, "ts": time.time(), "deck": "TestDeck",
            "conf": {"model": conf["model"], "api_keys": conf["api_keys"], "custom_prompt": ""},
        })

        fake_cards = [
            {"front": "Q1", "back": "A1", "tags": [], "is_image_card": False},
            {"front": "Q2", "back": "A2", "tags": [], "is_image_card": False},
        ]

        call_count = 0
        def ankiconnect_side_effect(action, **params):
            nonlocal call_count
            if action == "deckNames":
                return ["TestDeck"]
            if action == "addNote":
                call_count += 1
                if call_count == 1:
                    raise Exception("cannot create note because it is a duplicate")
                return 99999
            return None

        pushed = []
        with patch("flask_server.cfg.load", return_value=conf), \
             patch("flask_server.models.generate_cards", return_value=fake_cards), \
             patch("flask_server._ankiconnect", side_effect=ankiconnect_side_effect), \
             patch("flask_server._push_event", side_effect=pushed.append):
            flask_server._process_queue()

        assert len(flask_server._recent_cards) == 1
        assert flask_server._recent_cards[0]["note_id"] == 99999

        clear_events = [e for e in pushed if e["type"] == "queue_clear"]
        assert "skipped as duplicates" in clear_events[0]["message"]


class TestOfflineQueueRoute:
    """GET /api/offline-queue returns queue status."""

    def test_empty_queue(self, flask_client):
        resp = flask_client.get("/api/offline-queue")
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["count"] == 0
        assert data["items"] == []

    def test_queue_with_items(self, flask_client):
        flask_server._offline_queue.append({
            "path": "/tmp/a.png", "ts": time.time(), "deck": "Bio",
            "conf": {},
        })
        resp = flask_client.get("/api/offline-queue")
        data = resp.get_json()
        assert data["count"] == 1
        assert data["items"][0]["deck"] == "Bio"


class TestConnectivityEndpoint:
    """GET /api/connectivity checks provider reachability and triggers queue drain."""

    def test_online_returns_true(self, flask_client):
        import requests as req
        with patch.object(req, "head"):
            resp = flask_client.get("/api/connectivity")
        data = resp.get_json()
        assert data["online"] is True
        assert data["queue_count"] == 0

    def test_offline_returns_false(self, flask_client):
        import requests as req
        with patch.object(req, "head", side_effect=req.exceptions.ConnectionError()):
            resp = flask_client.get("/api/connectivity")
        data = resp.get_json()
        assert data["online"] is False

    def test_online_with_queue_triggers_processing(self, flask_client, tmp_config, tiny_png):
        """When connectivity returns and queue has items, processing is triggered."""
        import requests as req
        conf = dict(tmp_config)
        flask_server._offline_queue.append({
            "path": tiny_png, "ts": time.time(), "deck": "TestDeck",
            "conf": {"model": conf["model"], "api_keys": conf["api_keys"], "custom_prompt": ""},
        })

        threads_started = []
        original_thread = flask_server.threading.Thread
        class MockThread:
            def __init__(self, target=None, daemon=None):
                threads_started.append(target)
            def start(self):
                pass

        with patch.object(req, "head"), \
             patch.object(flask_server.threading, "Thread", MockThread):
            resp = flask_client.get("/api/connectivity")

        data = resp.get_json()
        assert data["online"] is True
        assert data["queue_count"] == 1
        assert len(threads_started) == 1
        assert threads_started[0] == flask_server._process_queue

    def test_offline_does_not_trigger_processing(self, flask_client, tmp_config, tiny_png):
        import requests as req
        flask_server._offline_queue.append({
            "path": tiny_png, "ts": time.time(), "deck": "TestDeck",
            "conf": {"model": {}, "custom_prompt": ""},
        })

        threads_started = []
        original_thread = flask_server.threading.Thread
        class MockThread:
            def __init__(self, target=None, daemon=None):
                threads_started.append(target)
            def start(self):
                pass

        with patch.object(req, "head", side_effect=req.exceptions.ConnectionError()), \
             patch.object(flask_server.threading, "Thread", MockThread):
            flask_client.get("/api/connectivity")

        assert len(threads_started) == 0


class TestOfflineToOnlineIntegration:
    """Full integration: screenshot while offline -> queued -> comes back online -> processed."""

    def test_screenshot_offline_then_online(self, tmp_config, tiny_png, mock_ankiconnect):
        """Simulate: take screenshot offline (SDK error), then process queue when online."""
        import anthropic

        handler = ScreenshotHandler()
        event = make_event(tiny_png)
        conf = dict(tmp_config)
        conf["session_active"] = True
        conf["deck"] = "TestDeck"

        # Phase 1: offline — SDK throws APIConnectionError
        sdk_err = anthropic.APIConnectionError(request=MagicMock())
        pushed = []
        with patch("flask_server.cfg.load", return_value=conf), \
             patch("flask_server.models.generate_cards", side_effect=sdk_err), \
             patch("flask_server._push_event", side_effect=pushed.append), \
             patch("time.sleep"):
            handler.on_created(event)

        # Screenshot should be queued
        assert len(flask_server._offline_queue) == 1
        assert len(flask_server._recent_cards) == 0
        assert any(e["type"] == "offline_queued" for e in pushed)

        # Phase 2: back online — generate_cards succeeds
        fake_cards = [
            {"front": "Q1", "back": "A1", "tags": [], "is_image_card": False},
            {"front": "Q2", "back": "A2", "tags": [], "is_image_card": False},
        ]
        pushed.clear()
        with patch("flask_server.cfg.load", return_value=conf), \
             patch("flask_server.models.generate_cards", return_value=fake_cards), \
             patch("flask_server._push_event", side_effect=pushed.append):
            flask_server._process_queue()

        # Queue should be empty, cards should be created
        assert len(flask_server._offline_queue) == 0
        assert len(flask_server._recent_cards) == 2
        assert any(e["type"] == "done" for e in pushed)
        assert any(e["type"] == "queue_clear" for e in pushed)

    def test_multiple_screenshots_offline_then_online(self, tmp_config, tmp_path, mock_ankiconnect):
        """Three screenshots queued offline, all processed when online with consolidated activity."""
        import anthropic
        from PIL import Image

        handler = ScreenshotHandler()
        conf = dict(tmp_config)
        conf["session_active"] = True
        conf["deck"] = "TestDeck"

        sdk_err = anthropic.APIConnectionError(request=MagicMock())
        paths = []
        for i in range(3):
            p = tmp_path / f"shot_{i}.png"
            Image.new("RGB", (100, 100)).save(str(p))
            paths.append(str(p))

        # Phase 1: all three fail offline
        with patch("flask_server.cfg.load", return_value=conf), \
             patch("flask_server.models.generate_cards", side_effect=sdk_err), \
             patch("flask_server._push_event"), \
             patch("time.sleep"):
            for p in paths:
                handler.on_created(make_event(p))

        assert len(flask_server._offline_queue) == 3

        # Phase 2: online — each generates 1 card
        fake_cards = [{"front": "Q", "back": "A", "tags": [], "is_image_card": False}]
        pushed = []
        with patch("flask_server.cfg.load", return_value=conf), \
             patch("flask_server.models.generate_cards", return_value=fake_cards), \
             patch("flask_server._push_event", side_effect=pushed.append):
            flask_server._process_queue()

        assert len(flask_server._offline_queue) == 0
        assert len(flask_server._recent_cards) == 3

        # 3 silent done events (cards for UI) + 1 progress + 1 queue_clear summary
        done_events = [e for e in pushed if e["type"] == "done"]
        assert len(done_events) == 3
        assert all(e["message"] == "" for e in done_events)

        clear_events = [e for e in pushed if e["type"] == "queue_clear"]
        assert len(clear_events) == 1
        assert "3 queued screenshots" in clear_events[0]["message"]
        assert "3 card(s) added" in clear_events[0]["message"]

    def test_still_offline_during_retry_keeps_queue(self, tmp_config, tiny_png):
        """If the queue worker retries but we're still offline, queue stays intact."""
        import anthropic

        handler = ScreenshotHandler()
        conf = dict(tmp_config)
        conf["session_active"] = True
        conf["deck"] = "TestDeck"

        sdk_err = anthropic.APIConnectionError(request=MagicMock())

        # Queue one screenshot
        with patch("flask_server.cfg.load", return_value=conf), \
             patch("flask_server.models.generate_cards", side_effect=sdk_err), \
             patch("flask_server._push_event"), \
             patch("time.sleep"):
            handler.on_created(make_event(tiny_png))

        assert len(flask_server._offline_queue) == 1

        # Retry — still offline
        with patch("flask_server.cfg.load", return_value=conf), \
             patch("flask_server.models.generate_cards", side_effect=sdk_err), \
             patch("flask_server._push_event"):
            flask_server._process_queue()

        # Queue unchanged
        assert len(flask_server._offline_queue) == 1
        assert len(flask_server._recent_cards) == 0

    def test_connectivity_endpoint_drains_queue(self, flask_client, tmp_config, tiny_png, mock_ankiconnect):
        """Full E2E: screenshot queued offline, /api/connectivity triggers processing."""
        import anthropic
        import requests as req

        handler = ScreenshotHandler()
        conf = dict(tmp_config)
        conf["session_active"] = True
        conf["deck"] = "TestDeck"

        # Phase 1: take screenshot while offline
        sdk_err = anthropic.APIConnectionError(request=MagicMock())
        with patch("flask_server.cfg.load", return_value=conf), \
             patch("flask_server.models.generate_cards", side_effect=sdk_err), \
             patch("flask_server._push_event"), \
             patch("time.sleep"):
            handler.on_created(make_event(tiny_png))

        assert len(flask_server._offline_queue) == 1

        # Phase 2: connectivity check comes back online — run _process_queue synchronously
        fake_cards = [{"front": "Q1", "back": "A1", "tags": [], "is_image_card": False}]

        # Capture the thread target so we can run it synchronously
        captured_target = []
        class SyncThread:
            def __init__(self, target=None, daemon=None):
                captured_target.append(target)
            def start(self):
                pass

        with patch.object(req, "head"), \
             patch.object(flask_server.threading, "Thread", SyncThread):
            resp = flask_client.get("/api/connectivity")
            assert resp.get_json()["online"] is True

        # Now run the captured process_queue synchronously with online mocks
        assert len(captured_target) == 1
        with patch("flask_server.cfg.load", return_value=conf), \
             patch("flask_server.models.generate_cards", return_value=fake_cards), \
             patch("flask_server._push_event"):
            captured_target[0]()

        # Queue drained, cards created
        assert len(flask_server._offline_queue) == 0
        assert len(flask_server._recent_cards) == 1
