import sys
from pathlib import Path

# Add project root so tests can import flask_server, config, models
sys.path.insert(0, str(Path(__file__).parent.parent))

import pytest
from unittest.mock import patch
from PIL import Image

import flask_server
import config as cfg_module


@pytest.fixture(autouse=True)
def clear_flask_state(tmp_path, monkeypatch):
    """Clear shared global state before and after each test."""
    # Point state/queue files to tmp so tests don't pollute real state
    monkeypatch.setattr(flask_server, "_STATE_FILE", tmp_path / "state.json")
    monkeypatch.setattr(flask_server, "_QUEUE_FILE", tmp_path / "offline_queue.json")
    flask_server._recent_cards.clear()
    flask_server._activity_log.clear()
    flask_server._batches.clear()
    flask_server._offline_queue.clear()
    flask_server._loaded_video = None
    flask_server._extension_connected = False
    yield
    flask_server._recent_cards.clear()
    flask_server._activity_log.clear()
    flask_server._batches.clear()
    flask_server._offline_queue.clear()
    flask_server._loaded_video = None
    flask_server._extension_connected = False


@pytest.fixture
def tmp_config(tmp_path, monkeypatch):
    config_dir = tmp_path / ".anki-fox"
    config_file = config_dir / "config.json"
    monkeypatch.setattr(cfg_module, "CONFIG_DIR", config_dir)
    monkeypatch.setattr(cfg_module, "CONFIG_FILE", config_file)
    return cfg_module._deep_copy(cfg_module.DEFAULT_CONFIG)


@pytest.fixture
def flask_client(tmp_config):
    flask_server.app.config["TESTING"] = True
    with flask_server.app.test_client() as client:
        yield client


@pytest.fixture
def tiny_png(tmp_path):
    img = Image.new("RGB", (100, 100), color=(255, 255, 255))
    path = tmp_path / "test_screenshot.png"
    img.save(str(path))
    return str(path)


@pytest.fixture
def mock_ankiconnect():
    _note_counter = [100000]

    def side_effect(action, **params):
        if action == "deckNames":
            return ["Deck1", "Deck2"]
        if action == "addNote":
            _note_counter[0] += 1
            return _note_counter[0]
        if action == "createDeck":
            return None
        if action == "storeMediaFile":
            return None
        if action == "deleteNotes":
            return None
        if action == "findNotes":
            return []
        if action == "notesInfo":
            return []
        return None

    with patch("flask_server._ankiconnect", side_effect=side_effect) as mock:
        yield mock
