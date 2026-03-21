"""Tests for production-readiness fixes: security, reliability, observability."""
import time
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

import flask_server
import config as cfg_mod


# ── Health check ─────────────────────────────────────────────────────────────────

class TestHealthCheck:

    def test_healthy(self, flask_client, tmp_config, mock_ankiconnect):
        resp = flask_client.get("/health")
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["status"] == "ok"
        assert data["checks"]["server"] is True
        assert data["checks"]["config"] is True

    def test_degraded_when_anki_down(self, flask_client, tmp_config):
        with patch("flask_server._ankiconnect", side_effect=Exception("refused")):
            resp = flask_client.get("/health")
        assert resp.status_code == 503
        data = resp.get_json()
        assert data["status"] == "degraded"
        assert data["checks"]["anki"] is False


# ── Path traversal protection ────────────────────────────────────────────────────

class TestPathTraversal:

    def test_rejects_path_outside_screenshots_dir(self, flask_client, tmp_path, monkeypatch):
        from PIL import Image
        monkeypatch.setattr(flask_server, "SCREENSHOTS_DIR", tmp_path / "safe")
        (tmp_path / "safe").mkdir()
        # Create file outside the safe dir
        evil_path = str(tmp_path / "evil.png")
        Image.new("RGB", (100, 100)).save(evil_path)
        resp = flask_client.post("/api/multi/finish", json={"paths": [evil_path]})
        assert resp.status_code == 400
        assert "outside" in resp.get_json()["error"].lower()

    def test_accepts_path_inside_screenshots_dir(self, flask_client, tmp_path, monkeypatch):
        from PIL import Image
        monkeypatch.setattr(flask_server, "SCREENSHOTS_DIR", tmp_path)
        p = str(tmp_path / "multi_0.png")
        Image.new("RGB", (100, 100)).save(p)
        resp = flask_client.post("/api/multi/finish", json={"paths": [p]})
        assert resp.status_code == 200


# ── Config validation ────────────────────────────────────────────────────────────

class TestConfigValidation:

    def test_rejects_non_dict_body(self, flask_client):
        resp = flask_client.post("/api/config", data="[]", content_type="application/json")
        assert resp.status_code == 400

    def test_rejects_wrong_type_for_deck(self, flask_client):
        resp = flask_client.post("/api/config", json={"deck": 123})
        assert resp.status_code == 400
        assert "str" in resp.get_json()["error"]

    def test_rejects_wrong_type_for_model(self, flask_client):
        resp = flask_client.post("/api/config", json={"model": "not-a-dict"})
        assert resp.status_code == 400

    def test_accepts_valid_config(self, flask_client):
        resp = flask_client.post("/api/config", json={"deck": "TestDeck", "model": {"provider": "anthropic"}})
        assert resp.status_code == 200

    def test_ignores_unknown_keys(self, flask_client):
        resp = flask_client.post("/api/config", json={"unknown_evil_key": "value"})
        assert resp.status_code == 200
        conf = flask_client.get("/api/config").get_json()
        assert "unknown_evil_key" not in conf


# ── Queue TTL ────────────────────────────────────────────────────────────────────

class TestQueueTTL:

    def test_expired_entries_skipped(self, flask_client, tmp_config, tmp_path, mock_ankiconnect):
        from PIL import Image
        conf = cfg_mod.load()
        conf["session_active"] = True
        conf["deck"] = "TestDeck"
        conf["api_keys"] = {"anthropic": "sk-test"}
        conf["model"] = {"provider": "anthropic", "model_name": "test"}
        cfg_mod.save(conf)

        img_path = str(tmp_path / "old_screenshot.png")
        Image.new("RGB", (200, 200)).save(img_path)

        # Add entry with timestamp from 48 hours ago (expired)
        flask_server._offline_queue.append({
            "path": img_path,
            "ts": time.time() - 172800,
            "deck": "TestDeck",
            "conf": {"model": conf["model"], "custom_prompt": ""},
        })

        with patch("flask_server.cfg.load", return_value=conf), \
             patch("flask_server.models.generate_cards") as mock_gen:
            flask_server._process_queue()
            mock_gen.assert_not_called()  # expired, should not process

    def test_fresh_entries_processed(self, flask_client, tmp_config, tmp_path, mock_ankiconnect):
        from PIL import Image
        conf = cfg_mod.load()
        conf["session_active"] = True
        conf["deck"] = "TestDeck"
        conf["api_keys"] = {"anthropic": "sk-test"}
        conf["model"] = {"provider": "anthropic", "model_name": "test"}
        cfg_mod.save(conf)

        img_path = str(tmp_path / "fresh_screenshot.png")
        Image.new("RGB", (200, 200)).save(img_path)

        flask_server._offline_queue.append({
            "path": img_path,
            "ts": time.time(),
            "deck": "TestDeck",
            "conf": {"model": conf["model"], "custom_prompt": ""},
        })

        fake_cards = [{"front": "Q", "back": "A", "tags": [], "is_image_card": False}]
        with patch("flask_server.cfg.load", return_value=conf), \
             patch("flask_server.models.generate_cards", return_value=fake_cards), \
             patch("flask_server._push_event"):
            flask_server._process_queue()

        assert len(flask_server._offline_queue) == 0


# ── Redaction ────────────────────────────────────────────────────────────────────

class TestRedaction:

    def test_redacts_anthropic_key(self):
        text = "Error with key sk-ant-api03-abc123def456"
        assert "[REDACTED]" in flask_server._redact(text)
        assert "sk-ant" not in flask_server._redact(text)

    def test_redacts_openai_key(self):
        text = "Auth failed: sk-proj-abc123def456ghi789jkl0"
        assert "[REDACTED]" in flask_server._redact(text)

    def test_redacts_groq_key(self):
        text = "Bad key: gsk_abc123def456ghi789jkl0"
        assert "[REDACTED]" in flask_server._redact(text)

    def test_preserves_non_secret_text(self):
        text = "Normal error message without secrets"
        assert flask_server._redact(text) == text


# ── AnkiConnect retry ────────────────────────────────────────────────────────────

class TestAnkiConnectRetry:

    def test_retries_on_network_error(self, flask_client):
        import requests
        call_count = [0]
        def side_effect(*args, **kwargs):
            call_count[0] += 1
            if call_count[0] <= 2:
                raise requests.ConnectionError("refused")
            mock_resp = MagicMock()
            mock_resp.json.return_value = {"result": ["Deck1"], "error": None}
            return mock_resp

        with patch("requests.post", side_effect=side_effect):
            result = flask_server._ankiconnect("deckNames")
        assert result == ["Deck1"]
        assert call_count[0] == 3  # 2 failures + 1 success

    def test_no_retry_on_ankiconnect_error(self, flask_client):
        """AnkiConnect application errors should not be retried."""
        mock_resp = MagicMock()
        mock_resp.json.return_value = {"result": None, "error": "deck not found"}
        with patch("requests.post", return_value=mock_resp):
            with pytest.raises(Exception, match="deck not found"):
                flask_server._ankiconnect("deckNames")


# ── No API keys in queue ─────────────────────────────────────────────────────────

class TestQueueNoSecrets:

    def test_enqueue_does_not_store_api_keys(self, flask_client, tmp_config):
        conf = cfg_mod.load()
        conf["api_keys"] = {"anthropic": "sk-ant-secret-key"}
        conf["deck"] = "TestDeck"
        conf["model"] = {"provider": "anthropic"}

        with patch("flask_server._push_event"):
            flask_server._enqueue_screenshot("/fake/path.png", conf)

        entry = flask_server._offline_queue[-1]
        assert "api_keys" not in entry["conf"]
        assert "sk-ant" not in str(entry)
        flask_server._offline_queue.pop()
