"""Tests for multi-screenshot mode: stitching, watchdog integration, and session flow."""
import os
import time
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from PIL import Image

import config as cfg_mod
import flask_server


class TestMultiFinishStitching:
    """Test POST /api/multi/finish stitching behavior."""

    def _make_image(self, tmp_path, name, width, height, color=(255, 0, 0)):
        p = str(tmp_path / name)
        Image.new("RGB", (width, height), color=color).save(p)
        return p

    def test_stitch_two_same_width(self, flask_client, tmp_path):
        p1 = self._make_image(tmp_path, ".multi_0.png", 100, 50)
        p2 = self._make_image(tmp_path, ".multi_1.png", 100, 60)
        resp = flask_client.post("/api/multi/finish", json={"paths": [p1, p2]})
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["ok"] is True
        result = Image.open(data["path"])
        assert result.width == 100
        assert result.height == 110
        result.close()

    def test_stitch_different_widths_uses_max(self, flask_client, tmp_path):
        p1 = self._make_image(tmp_path, ".multi_0.png", 80, 50)
        p2 = self._make_image(tmp_path, ".multi_1.png", 200, 50)
        resp = flask_client.post("/api/multi/finish", json={"paths": [p1, p2]})
        result = Image.open(resp.get_json()["path"])
        assert result.width == 200
        assert result.height == 100
        result.close()

    def test_stitch_three_images(self, flask_client, tmp_path):
        paths = [self._make_image(tmp_path, f".multi_{i}.png", 100, 30) for i in range(3)]
        resp = flask_client.post("/api/multi/finish", json={"paths": paths})
        assert resp.status_code == 200
        result = Image.open(resp.get_json()["path"])
        assert result.height == 90
        result.close()

    def test_stitch_cleans_up_temp_files(self, flask_client, tmp_path):
        paths = [self._make_image(tmp_path, f".multi_{i}.png", 100, 50) for i in range(2)]
        flask_client.post("/api/multi/finish", json={"paths": paths})
        for p in paths:
            assert not Path(p).exists(), f"Temp file {p} should be cleaned up"

    def test_stitch_single_image_works(self, flask_client, tmp_path):
        p = self._make_image(tmp_path, ".multi_0.png", 200, 100)
        resp = flask_client.post("/api/multi/finish", json={"paths": [p]})
        assert resp.status_code == 200
        assert resp.get_json()["ok"] is True

    def test_stitch_empty_paths_returns_400(self, flask_client):
        resp = flask_client.post("/api/multi/finish", json={"paths": []})
        assert resp.status_code == 400

    def test_stitch_missing_file_returns_400(self, flask_client):
        resp = flask_client.post("/api/multi/finish", json={"paths": ["/nonexistent.png"]})
        assert resp.status_code == 400

    def test_stitch_output_lands_in_screenshots_dir(self, flask_client, tmp_path, monkeypatch):
        """Stitched output should go to SCREENSHOTS_DIR, not the temp dir."""
        out_dir = tmp_path / "incoming"
        out_dir.mkdir()
        monkeypatch.setattr(flask_server, "SCREENSHOTS_DIR", out_dir)
        p1 = self._make_image(tmp_path, ".multi_0.png", 100, 50)
        p2 = self._make_image(tmp_path, ".multi_1.png", 100, 50)
        resp = flask_client.post("/api/multi/finish", json={"paths": [p1, p2]})
        result_path = resp.get_json()["path"]
        assert str(out_dir) in result_path
        assert Path(result_path).exists()


class TestWatchdogIgnoresMultiTempFiles:
    """Watchdog must ignore dot-prefixed .multi_ temp files."""

    def test_dot_multi_file_skipped(self, flask_client, tmp_path, mock_ankiconnect):
        conf = cfg_mod.load()
        conf["session_active"] = True
        conf["deck"] = "TestDeck"
        conf["api_keys"] = {"anthropic": "sk-test"}
        cfg_mod.save(conf)

        dot_path = str(tmp_path / ".multi_20260320_120000_0.png")
        Image.new("RGB", (100, 100)).save(dot_path)

        handler = flask_server.ScreenshotHandler()
        event = MagicMock()
        event.is_directory = False
        event.src_path = dot_path

        with patch("models.generate_cards") as mock_gen:
            handler.on_created(event)
            mock_gen.assert_not_called()

    def test_regular_png_still_processed(self, flask_client, tmp_path, mock_ankiconnect):
        conf = cfg_mod.load()
        conf["session_active"] = True
        conf["deck"] = "TestDeck"
        conf["api_keys"] = {"anthropic": "sk-test"}
        conf["model"] = {"provider": "anthropic", "model_name": "test", "base_url": None}
        cfg_mod.save(conf)

        regular_path = str(tmp_path / "screenshot_20260320_120000.png")
        Image.new("RGB", (100, 100)).save(regular_path)

        handler = flask_server.ScreenshotHandler()
        event = MagicMock()
        event.is_directory = False
        event.src_path = regular_path

        with patch("models.generate_cards", return_value=[]) as mock_gen:
            handler.on_created(event)
            mock_gen.assert_called_once()


class TestMultiStitchThenWatchdog:
    """Integration: stitch creates a regular file that the watchdog processes."""

    def test_stitched_file_triggers_card_generation(self, flask_client, tmp_path, monkeypatch, mock_ankiconnect):
        """After stitching, the output file should be a regular (non-dot) PNG
        that the watchdog would process."""
        out_dir = tmp_path / "incoming"
        out_dir.mkdir()
        monkeypatch.setattr(flask_server, "SCREENSHOTS_DIR", out_dir)

        conf = cfg_mod.load()
        conf["session_active"] = True
        conf["deck"] = "TestDeck"
        conf["api_keys"] = {"anthropic": "sk-test"}
        conf["model"] = {"provider": "anthropic", "model_name": "test", "base_url": None}
        cfg_mod.save(conf)

        p1 = str(tmp_path / ".multi_0.png")
        p2 = str(tmp_path / ".multi_1.png")
        Image.new("RGB", (100, 50)).save(p1)
        Image.new("RGB", (100, 50)).save(p2)

        resp = flask_client.post("/api/multi/finish", json={"paths": [p1, p2]})
        result_path = resp.get_json()["path"]

        # The stitched file should NOT be dot-prefixed
        assert not Path(result_path).name.startswith(".")

        # Simulate watchdog picking it up
        handler = flask_server.ScreenshotHandler()
        event = MagicMock()
        event.is_directory = False
        event.src_path = result_path

        with patch("models.generate_cards", return_value=[]) as mock_gen:
            handler.on_created(event)
            mock_gen.assert_called_once()


class TestMultiSourceSession:
    """Session endpoint returns correct source mode for multi."""

    def test_session_returns_multi_source(self, flask_client):
        flask_client.post("/api/config", json={
            "deck": "Bio",
            "deck_sources": {"Bio": {"source": "multi"}},
        })
        resp = flask_client.get("/api/session")
        assert resp.get_json()["source"] == "multi"

    def test_session_defaults_to_screen(self, flask_client):
        flask_client.post("/api/config", json={"deck": "Bio", "deck_sources": {}})
        resp = flask_client.get("/api/session")
        assert resp.get_json()["source"] == "screen"

    def test_cycle_reaches_multi(self, flask_client):
        flask_client.post("/api/config", json={"deck": "Bio", "deck_sources": {}})
        resp = flask_client.post("/api/source/cycle")
        assert resp.get_json()["source"] == "multi"

    def test_cycle_past_multi_to_video(self, flask_client):
        flask_client.post("/api/config", json={
            "deck": "Bio",
            "deck_sources": {"Bio": {"source": "multi"}},
        })
        resp = flask_client.post("/api/source/cycle")
        assert resp.get_json()["source"] == "video"

    def test_full_cycle_back_to_screen(self, flask_client):
        flask_client.post("/api/config", json={"deck": "Bio", "deck_sources": {}})
        sources = []
        for _ in range(3):
            resp = flask_client.post("/api/source/cycle")
            sources.append(resp.get_json()["source"])
        assert sources == ["multi", "video", "screen"]
