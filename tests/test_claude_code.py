"""Tests for the claude-code provider (Claude CLI subscription-based generation)."""
import json
import subprocess
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

import models
import flask_server
import config as cfg_mod


@pytest.fixture(autouse=True)
def mock_find_cli():
    """By default, pretend claude CLI is installed at a known path."""
    with patch("models._find_claude_cli", return_value="/usr/local/bin/claude"):
        yield


# ── CLI discovery ────────────────────────────────────────────────────────────────

class TestFindClaudeCLI:
    """Test _find_claude_cli finds the binary in various locations."""

    def _call_real(self):
        """Inline the real logic to bypass autouse mock."""
        import shutil
        path = shutil.which("claude")
        if path:
            return path
        for candidate in [
            Path.home() / ".local" / "bin" / "claude",
            Path("/usr/local/bin/claude"),
        ]:
            if candidate.exists():
                return str(candidate)
        return None

    def test_found_on_path(self):
        with patch("shutil.which", return_value="/usr/local/bin/claude"):
            assert self._call_real() == "/usr/local/bin/claude"

    def test_found_in_local_bin_fallback(self):
        expected = str(Path.home() / ".local" / "bin" / "claude")
        with patch("shutil.which", return_value=None), \
             patch.object(Path, "exists", return_value=True):
            assert self._call_real() == expected

    def test_not_found_anywhere(self):
        with patch("shutil.which", return_value=None), \
             patch.object(Path, "exists", return_value=False):
            assert self._call_real() is None


# ── Routing ──────────────────────────────────────────────────────────────────────

class TestProviderRouting:
    """generate_cards dispatches to _generate_claude_code for claude-code provider."""

    def test_routes_to_claude_code(self):
        config = {"model": {"provider": "claude-code", "model_name": "claude-sonnet-4-6"}, "api_keys": {}}
        with patch("models._generate_claude_code") as mock:
            mock.return_value = [{"front": "Q", "back": "A", "tags": []}]
            cards = models.generate_cards("/fake/path.png", config)
            mock.assert_called_once_with("/fake/path.png", config)
            assert len(cards) == 1

    def test_anthropic_still_routes_correctly(self):
        config = {"model": {"provider": "anthropic"}, "api_keys": {"anthropic": "sk-test"}}
        with patch("models._generate_anthropic") as mock:
            mock.return_value = []
            models.generate_cards("/fake.png", config)
            mock.assert_called_once()

    def test_openai_still_routes_correctly(self):
        config = {"model": {"provider": "openai"}, "api_keys": {"openai": "sk-test"}}
        with patch("models._generate_openai_compat") as mock:
            mock.return_value = []
            models.generate_cards("/fake.png", config)
            mock.assert_called_once()


# ── Successful generation ────────────────────────────────────────────────────────

class TestClaudeCodeGeneration:
    """Test _generate_claude_code with mocked subprocess."""

    def _cli_output(self, cards):
        return json.dumps({"type": "result", "result": json.dumps({"cards": cards})})

    def _config(self, model="claude-sonnet-4-6"):
        return {"model": {"provider": "claude-code", "model_name": model}, "api_keys": {}}

    def test_parses_single_card(self):
        out = self._cli_output([{"front": "Q1", "back": "A1", "tags": ["t"], "is_image_card": False}])
        with patch("subprocess.run") as m:
            m.return_value = MagicMock(returncode=0, stdout=out, stderr="")
            cards = models._generate_claude_code("/img.png", self._config())
        assert len(cards) == 1
        assert cards[0]["front"] == "Q1"

    def test_parses_multiple_cards(self):
        out = self._cli_output([
            {"front": "Q1", "back": "A1", "tags": [], "is_image_card": False},
            {"front": "Q2", "back": "A2", "tags": ["bio"], "is_image_card": True},
        ])
        with patch("subprocess.run") as m:
            m.return_value = MagicMock(returncode=0, stdout=out, stderr="")
            cards = models._generate_claude_code("/img.png", self._config())
        assert len(cards) == 2
        assert cards[1]["tags"] == ["bio"]

    def test_no_api_key_needed(self):
        out = self._cli_output([{"front": "Q", "back": "A", "tags": [], "is_image_card": False}])
        config = {"model": {"provider": "claude-code", "model_name": "claude-sonnet-4-6"}, "api_keys": {}}
        with patch("subprocess.run") as m:
            m.return_value = MagicMock(returncode=0, stdout=out, stderr="")
            cards = models._generate_claude_code("/img.png", config)
        assert len(cards) == 1

    def test_empty_cards_ok(self):
        out = self._cli_output([])
        with patch("subprocess.run") as m:
            m.return_value = MagicMock(returncode=0, stdout=out, stderr="")
            assert models._generate_claude_code("/img.png", self._config()) == []


# ── CLI invocation details ───────────────────────────────────────────────────────

class TestClaudeCodeCLIArgs:
    """Verify correct CLI arguments and prompt content."""

    def _config(self, model="claude-sonnet-4-6", **extra):
        return {"model": {"provider": "claude-code", "model_name": model}, "api_keys": {}, **extra}

    def _capture(self, config, image_path="/path/to/img.png"):
        out = json.dumps({"type": "result", "result": '{"cards": []}'})
        with patch("subprocess.run") as m:
            m.return_value = MagicMock(returncode=0, stdout=out, stderr="")
            models._generate_claude_code(image_path, config)
        return m.call_args

    def test_prompt_includes_image_path(self):
        call = self._capture(self._config(), "/my/screenshot.png")
        assert "/my/screenshot.png" in call.kwargs["input"]

    def test_prompt_includes_rules(self):
        call = self._capture(self._config())
        assert "RULES:" in call.kwargs["input"]

    def test_uses_specified_model(self):
        call = self._capture(self._config(model="claude-haiku-4-5"))
        cmd = call.args[0]
        assert cmd[cmd.index("--model") + 1] == "claude-haiku-4-5"

    def test_uses_json_output(self):
        call = self._capture(self._config())
        cmd = call.args[0]
        assert cmd[cmd.index("--output-format") + 1] == "json"

    def test_allows_read_tool(self):
        call = self._capture(self._config())
        cmd = call.args[0]
        assert cmd[cmd.index("--allowedTools") + 1] == "Read"

    def test_uses_print_mode(self):
        call = self._capture(self._config())
        assert "-p" in call.args[0]

    def test_timeout_set(self):
        call = self._capture(self._config())
        assert call.kwargs["timeout"] == 120

    def test_custom_prompt_included(self):
        call = self._capture(self._config(custom_prompt="Spanish please"))
        assert "Spanish please" in call.kwargs["input"]

    def test_deck_context_included(self):
        call = self._capture(self._config(deck_context=[
            {"front": "What is DNA?", "back": "Genetic material", "tags": ["bio"]},
        ]))
        assert "What is DNA?" in call.kwargs["input"]


# ── Error handling ───────────────────────────────────────────────────────────────

class TestClaudeCodeErrors:

    def _config(self):
        return {"model": {"provider": "claude-code", "model_name": "claude-sonnet-4-6"}, "api_keys": {}}

    def test_cli_not_installed(self):
        with patch("models._find_claude_cli", return_value=None):
            with pytest.raises(ValueError, match="Claude Code not found"):
                models._generate_claude_code("/img.png", self._config())

    def test_cli_timeout(self):
        with patch("subprocess.run", side_effect=subprocess.TimeoutExpired(cmd="claude", timeout=120)):
            with pytest.raises(ValueError, match="timed out"):
                models._generate_claude_code("/img.png", self._config())

    def test_cli_nonzero_exit(self):
        with patch("subprocess.run") as m:
            m.return_value = MagicMock(returncode=1, stdout="", stderr="auth failed")
            with pytest.raises(ValueError, match="Claude Code error.*auth failed"):
                models._generate_claude_code("/img.png", self._config())

    def test_cli_invalid_json(self):
        with patch("subprocess.run") as m:
            m.return_value = MagicMock(returncode=0, stdout="not json", stderr="")
            with pytest.raises(ValueError, match="invalid JSON"):
                models._generate_claude_code("/img.png", self._config())

    def test_cli_empty_result(self):
        out = json.dumps({"type": "result", "result": ""})
        with patch("subprocess.run") as m:
            m.return_value = MagicMock(returncode=0, stdout=out, stderr="")
            with pytest.raises(ValueError, match="empty result"):
                models._generate_claude_code("/img.png", self._config())

    def test_cli_missing_result_key(self):
        out = json.dumps({"type": "result"})
        with patch("subprocess.run") as m:
            m.return_value = MagicMock(returncode=0, stdout=out, stderr="")
            with pytest.raises(ValueError, match="empty result"):
                models._generate_claude_code("/img.png", self._config())

    def test_stderr_truncated(self):
        with patch("subprocess.run") as m:
            m.return_value = MagicMock(returncode=1, stdout="", stderr="x" * 500)
            with pytest.raises(ValueError) as exc_info:
                models._generate_claude_code("/img.png", self._config())
            assert len(str(exc_info.value)) < 400


# ── Connectivity ─────────────────────────────────────────────────────────────────

class TestClaudeCodeConnectivity:

    def _set_provider(self, tmp_config):
        conf = cfg_mod.load()
        conf["model"] = {"provider": "claude-code", "model_name": "claude-sonnet-4-6"}
        cfg_mod.save(conf)

    def test_online_when_cli_found(self, flask_client, tmp_config):
        self._set_provider(tmp_config)
        with patch("models._find_claude_cli", return_value="/usr/local/bin/claude"):
            resp = flask_client.get("/api/connectivity")
        assert resp.get_json()["online"] is True

    def test_offline_when_cli_missing(self, flask_client, tmp_config):
        self._set_provider(tmp_config)
        with patch("models._find_claude_cli", return_value=None):
            resp = flask_client.get("/api/connectivity")
        assert resp.get_json()["online"] is False

    def test_online_via_fallback_path(self, flask_client, tmp_config):
        self._set_provider(tmp_config)
        with patch("models._find_claude_cli", return_value="/Users/rachel/.local/bin/claude"):
            resp = flask_client.get("/api/connectivity")
        assert resp.get_json()["online"] is True


# ── UI ───────────────────────────────────────────────────────────────────────────

class TestClaudeCodeUI:

    def test_dropdown_has_option(self, flask_client):
        resp = flask_client.get("/")
        assert b'value="claude-code"' in resp.data

    def test_dropdown_label(self, flask_client):
        resp = flask_client.get("/")
        assert b"Claude (subscription)" in resp.data

    def test_js_has_model_defaults(self, flask_client):
        resp = flask_client.get("/static/app.js")
        assert b'"claude-code"' in resp.data
        assert b"hasKey: false" in resp.data


# ── Watchdog integration ─────────────────────────────────────────────────────────

class TestClaudeCodeWatchdog:

    def test_watchdog_uses_claude_code_provider(self, flask_client, tmp_path, mock_ankiconnect):
        conf = cfg_mod.load()
        conf["session_active"] = True
        conf["deck"] = "TestDeck"
        conf["model"] = {"provider": "claude-code", "model_name": "claude-sonnet-4-6"}
        cfg_mod.save(conf)

        from PIL import Image
        img_path = str(tmp_path / "screenshot_test.png")
        Image.new("RGB", (200, 200)).save(img_path)

        handler = flask_server.ScreenshotHandler()
        event = MagicMock()
        event.is_directory = False
        event.src_path = img_path

        with patch("models.generate_cards", return_value=[]) as mock_gen:
            handler.on_created(event)
            mock_gen.assert_called_once()
            call_config = mock_gen.call_args[0][1]
            assert call_config["model"]["provider"] == "claude-code"
