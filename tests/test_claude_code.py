"""Tests for the claude-code provider (Claude CLI subscription-based generation)."""
import json
import subprocess
from unittest.mock import MagicMock, patch

import pytest

import models
import flask_server


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
        config = {"model": {"provider": "anthropic", "model_name": "claude-sonnet-4-6"}, "api_keys": {"anthropic": "sk-test"}}
        with patch("models._generate_anthropic") as mock:
            mock.return_value = []
            models.generate_cards("/fake/path.png", config)
            mock.assert_called_once()

    def test_openai_still_routes_correctly(self):
        config = {"model": {"provider": "openai", "model_name": "gpt-4o"}, "api_keys": {"openai": "sk-test"}}
        with patch("models._generate_openai_compat") as mock:
            mock.return_value = []
            models.generate_cards("/fake/path.png", config)
            mock.assert_called_once()


# ── Successful generation ────────────────────────────────────────────────────────

class TestClaudeCodeGeneration:
    """Test _generate_claude_code with mocked subprocess."""

    def _make_cli_output(self, cards):
        """Build mock CLI JSON output wrapping card JSON."""
        cards_json = json.dumps({"cards": cards})
        return json.dumps({"type": "result", "result": cards_json})

    def _config(self, model="claude-sonnet-4-6", **extra):
        return {"model": {"provider": "claude-code", "model_name": model}, "api_keys": {}, **extra}

    def test_parses_single_card(self):
        cards_data = [{"front": "What is X?", "back": "Y", "tags": ["test"], "is_image_card": False}]
        cli_output = self._make_cli_output(cards_data)
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0, stdout=cli_output, stderr="")
            cards = models._generate_claude_code("/img.png", self._config())
        assert len(cards) == 1
        assert cards[0]["front"] == "What is X?"
        assert cards[0]["back"] == "Y"

    def test_parses_multiple_cards(self):
        cards_data = [
            {"front": "Q1", "back": "A1", "tags": [], "is_image_card": False},
            {"front": "Q2", "back": "A2", "tags": ["bio"], "is_image_card": True},
        ]
        cli_output = self._make_cli_output(cards_data)
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0, stdout=cli_output, stderr="")
            cards = models._generate_claude_code("/img.png", self._config())
        assert len(cards) == 2
        assert cards[1]["tags"] == ["bio"]

    def test_no_api_key_needed(self):
        """claude-code should never raise about missing API keys."""
        cli_output = self._make_cli_output([{"front": "Q", "back": "A", "tags": [], "is_image_card": False}])
        config = {"model": {"provider": "claude-code", "model_name": "claude-sonnet-4-6"}, "api_keys": {}}
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0, stdout=cli_output, stderr="")
            cards = models._generate_claude_code("/img.png", config)
        assert len(cards) == 1

    def test_empty_api_keys_dict_ok(self):
        """Even with completely empty api_keys, no error."""
        cli_output = self._make_cli_output([])
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0, stdout=cli_output, stderr="")
            cards = models._generate_claude_code("/img.png", self._config())
        assert cards == []


# ── CLI invocation ───────────────────────────────────────────────────────────────

class TestClaudeCodeCLIArgs:
    """Verify the correct CLI arguments and prompt content."""

    def _config(self, model="claude-sonnet-4-6", **extra):
        return {"model": {"provider": "claude-code", "model_name": model}, "api_keys": {}, **extra}

    def _run_and_capture(self, config, image_path="/path/to/screenshot.png"):
        cli_output = json.dumps({"type": "result", "result": '{"cards": []}'})
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0, stdout=cli_output, stderr="")
            models._generate_claude_code(image_path, config)
        return mock_run.call_args

    def test_prompt_includes_image_path(self):
        call = self._run_and_capture(self._config(), "/my/screenshot.png")
        stdin_text = call.kwargs.get("input", "")
        assert "/my/screenshot.png" in stdin_text

    def test_prompt_includes_card_rules(self):
        call = self._run_and_capture(self._config())
        stdin_text = call.kwargs.get("input", "")
        assert "Anki flashcards" in stdin_text
        assert "RULES:" in stdin_text

    def test_uses_specified_model(self):
        call = self._run_and_capture(self._config(model="claude-haiku-4-5"))
        cmd = call.args[0]
        model_idx = cmd.index("--model")
        assert cmd[model_idx + 1] == "claude-haiku-4-5"

    def test_uses_json_output_format(self):
        call = self._run_and_capture(self._config())
        cmd = call.args[0]
        fmt_idx = cmd.index("--output-format")
        assert cmd[fmt_idx + 1] == "json"

    def test_allows_read_tool(self):
        call = self._run_and_capture(self._config())
        cmd = call.args[0]
        tools_idx = cmd.index("--allowedTools")
        assert cmd[tools_idx + 1] == "Read"

    def test_uses_print_mode(self):
        call = self._run_and_capture(self._config())
        cmd = call.args[0]
        assert "-p" in cmd

    def test_custom_prompt_included(self):
        config = self._config(custom_prompt="Make cards in Spanish")
        call = self._run_and_capture(config)
        stdin_text = call.kwargs.get("input", "")
        assert "Make cards in Spanish" in stdin_text

    def test_deck_context_included(self):
        config = self._config(deck_context=[
            {"front": "What is DNA?", "back": "Genetic material", "tags": ["bio"]},
        ])
        call = self._run_and_capture(config)
        stdin_text = call.kwargs.get("input", "")
        assert "What is DNA?" in stdin_text

    def test_timeout_set(self):
        call = self._run_and_capture(self._config())
        assert call.kwargs.get("timeout") == 120


# ── Error handling ───────────────────────────────────────────────────────────────

class TestClaudeCodeErrors:
    """Test error conditions for the claude-code provider."""

    def _config(self):
        return {"model": {"provider": "claude-code", "model_name": "claude-sonnet-4-6"}, "api_keys": {}}

    def test_cli_not_installed(self):
        with patch("subprocess.run", side_effect=FileNotFoundError):
            with pytest.raises(ValueError, match="Claude Code not found"):
                models._generate_claude_code("/img.png", self._config())

    def test_cli_timeout(self):
        with patch("subprocess.run", side_effect=subprocess.TimeoutExpired(cmd="claude", timeout=120)):
            with pytest.raises(ValueError, match="timed out"):
                models._generate_claude_code("/img.png", self._config())

    def test_cli_nonzero_exit(self):
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=1, stdout="", stderr="authentication failed")
            with pytest.raises(ValueError, match="Claude Code error.*authentication failed"):
                models._generate_claude_code("/img.png", self._config())

    def test_cli_returns_invalid_json(self):
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0, stdout="not json at all", stderr="")
            with pytest.raises(ValueError, match="invalid JSON"):
                models._generate_claude_code("/img.png", self._config())

    def test_cli_returns_empty_result(self):
        output = json.dumps({"type": "result", "result": ""})
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0, stdout=output, stderr="")
            with pytest.raises(ValueError, match="empty result"):
                models._generate_claude_code("/img.png", self._config())

    def test_cli_returns_missing_result_key(self):
        output = json.dumps({"type": "result"})
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0, stdout=output, stderr="")
            with pytest.raises(ValueError, match="empty result"):
                models._generate_claude_code("/img.png", self._config())

    def test_cli_stderr_truncated_in_error(self):
        """Long stderr should be truncated to 300 chars."""
        long_err = "x" * 500
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=1, stdout="", stderr=long_err)
            with pytest.raises(ValueError) as exc_info:
                models._generate_claude_code("/img.png", self._config())
            assert len(str(exc_info.value)) < 400


# ── Connectivity check ───────────────────────────────────────────────────────────

class TestClaudeCodeConnectivity:
    """Test /api/connectivity for the claude-code provider."""

    def test_online_when_cli_found(self, flask_client, tmp_config):
        import config as cfg_mod
        conf = cfg_mod.load()
        conf["model"] = {"provider": "claude-code", "model_name": "claude-sonnet-4-6"}
        cfg_mod.save(conf)
        with patch("shutil.which", return_value="/usr/local/bin/claude"):
            resp = flask_client.get("/api/connectivity")
        assert resp.get_json()["online"] is True

    def test_offline_when_cli_missing(self, flask_client, tmp_config):
        import config as cfg_mod
        conf = cfg_mod.load()
        conf["model"] = {"provider": "claude-code", "model_name": "claude-sonnet-4-6"}
        cfg_mod.save(conf)
        with patch("shutil.which", return_value=None):
            resp = flask_client.get("/api/connectivity")
        assert resp.get_json()["online"] is False


# ── UI config ────────────────────────────────────────────────────────────────────

class TestClaudeCodeUI:
    """Verify the web UI includes the claude-code provider option."""

    def test_dropdown_has_claude_code_option(self, flask_client):
        resp = flask_client.get("/")
        assert b'value="claude-code"' in resp.data

    def test_dropdown_label(self, flask_client):
        resp = flask_client.get("/")
        assert b"Claude (subscription)" in resp.data

    def test_app_js_has_model_defaults(self, flask_client):
        resp = flask_client.get("/static/app.js")
        assert b'"claude-code"' in resp.data
        assert b"hasKey: false" in resp.data


# ── Integration with watchdog ────────────────────────────────────────────────────

class TestClaudeCodeWatchdogIntegration:
    """Verify watchdog triggers claude-code generation correctly."""

    def test_watchdog_uses_claude_code_provider(self, flask_client, tmp_path, mock_ankiconnect):
        """When config has claude-code provider, watchdog should use it."""
        import config as cfg_mod
        from PIL import Image
        from unittest.mock import MagicMock as MM

        conf = cfg_mod.load()
        conf["session_active"] = True
        conf["deck"] = "TestDeck"
        conf["model"] = {"provider": "claude-code", "model_name": "claude-sonnet-4-6"}
        cfg_mod.save(conf)

        img_path = str(tmp_path / "screenshot_test.png")
        Image.new("RGB", (200, 200)).save(img_path)

        handler = flask_server.ScreenshotHandler()
        event = MM()
        event.is_directory = False
        event.src_path = img_path

        with patch("models.generate_cards", return_value=[]) as mock_gen:
            handler.on_created(event)
            mock_gen.assert_called_once()
            call_config = mock_gen.call_args[0][1]
            assert call_config["model"]["provider"] == "claude-code"
