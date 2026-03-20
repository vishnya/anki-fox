"""Tests for MathJax formula support in card generation and rendering."""
import json
from unittest.mock import patch, MagicMock

import pytest

import models
import flask_server
import config as cfg_mod


# ── Prompt contains math rules ──────────────────────────────────────────────────

class TestPromptMathRules:
    """Verify the prompt instructs the LLM to use MathJax delimiters."""

    def test_mathjax_section_in_prompt(self):
        prompt = models._build_prompt({"custom_prompt": ""})
        assert "MATH FORMATTING:" in prompt

    def test_inline_delimiter_mentioned(self):
        prompt = models._build_prompt({"custom_prompt": ""})
        assert "\\\\(" in prompt or "\\(" in prompt

    def test_display_delimiter_mentioned(self):
        prompt = models._build_prompt({"custom_prompt": ""})
        assert "\\\\[" in prompt or "\\[" in prompt

    def test_no_dollar_sign_rule(self):
        prompt = models._build_prompt({"custom_prompt": ""})
        assert "Do NOT use dollar-sign" in prompt

    def test_selfcheck_includes_math(self):
        prompt = models._build_prompt({"custom_prompt": ""})
        selfcheck_pos = prompt.index("SELF-CHECK:")
        assert "math cards" in prompt[selfcheck_pos:].lower() or "dollar signs" in prompt[selfcheck_pos:]


# ── Card parsing preserves MathJax ──────────────────────────────────────────────

class TestCardParsingPreservesMath:
    """Verify _parse_cards doesn't mangle MathJax delimiters."""

    def test_inline_math_preserved(self):
        raw = json.dumps({"cards": [{
            "front": "What is the derivative of \\(x^2\\)?",
            "back": "\\(2x\\)",
            "tags": ["calc"],
            "is_image_card": False,
        }]})
        cards = models._parse_cards(raw)
        assert "\\(x^2\\)" in cards[0]["front"]
        assert "\\(2x\\)" in cards[0]["back"]

    def test_display_math_preserved(self):
        raw = json.dumps({"cards": [{
            "front": "What is the quadratic formula?",
            "back": "\\[x = \\frac{-b \\pm \\sqrt{b^2 - 4ac}}{2a}\\]",
            "tags": ["algebra"],
            "is_image_card": False,
        }]})
        cards = models._parse_cards(raw)
        assert "\\frac{-b" in cards[0]["back"]
        assert "\\[" in cards[0]["back"]
        assert "\\]" in cards[0]["back"]

    def test_mixed_math_and_text(self):
        raw = json.dumps({"cards": [{
            "front": "What does \\(\\nabla\\) mean?",
            "back": "The gradient operator \\(\\nabla f\\) points in the direction of steepest ascent.",
            "tags": ["math"],
            "is_image_card": False,
        }]})
        cards = models._parse_cards(raw)
        assert "\\(\\nabla\\)" in cards[0]["front"]
        assert "\\(\\nabla f\\)" in cards[0]["back"]

    def test_backslash_escaping_in_json(self):
        """JSON uses \\\\ for literal backslash — verify round-trip works."""
        raw = '{"cards": [{"front": "What is \\\\(\\\\alpha\\\\)?", "back": "A Greek letter", "tags": [], "is_image_card": false}]}'
        cards = models._parse_cards(raw)
        assert "\\(\\alpha\\)" in cards[0]["front"]

    def test_cards_without_math_unchanged(self):
        raw = json.dumps({"cards": [{
            "front": "What is DNA?",
            "back": "Deoxyribonucleic acid — carries genetic information.",
            "tags": ["bio"],
            "is_image_card": False,
        }]})
        cards = models._parse_cards(raw)
        assert cards[0]["front"] == "What is DNA?"


# ── AnkiConnect receives MathJax delimiters ─────────────────────────────────────

class TestAnkiConnectReceivesMath:
    """Verify cards with MathJax are sent to AnkiConnect correctly."""

    def test_mathjax_in_fields(self, flask_client, tmp_path, tmp_config, mock_ankiconnect):
        """When generate_cards returns MathJax, AnkiConnect gets the delimiters."""
        conf = cfg_mod.load()
        conf["session_active"] = True
        conf["deck"] = "Math"
        conf["api_keys"] = {"anthropic": "sk-test"}
        conf["model"] = {"provider": "anthropic", "model_name": "test"}
        cfg_mod.save(conf)

        math_cards = [{
            "front": "What is the derivative of \\(x^2\\)?",
            "back": "\\(2x\\). The power rule says \\(\\frac{d}{dx} x^n = nx^{n-1}\\).",
            "tags": ["calculus"],
            "is_image_card": False,
        }]

        from PIL import Image
        img_path = str(tmp_path / "math_screenshot.png")
        Image.new("RGB", (200, 200)).save(img_path)

        with patch("models.generate_cards", return_value=math_cards):
            handler = flask_server.ScreenshotHandler()
            event = MagicMock()
            event.is_directory = False
            event.src_path = img_path
            handler.on_created(event)

        # Check what AnkiConnect received
        calls = mock_ankiconnect.call_args_list
        add_note_calls = [c for c in calls if c[0][0] == "addNote"]
        assert len(add_note_calls) >= 1
        note_params = add_note_calls[0][1]
        front_field = note_params["note"]["fields"]["Front"]
        back_field = note_params["note"]["fields"]["Back"]
        assert "\\(x^2\\)" in front_field
        assert "\\(2x\\)" in back_field
        assert "\\frac{d}{dx}" in back_field


# ── HTML stripping preserves MathJax ────────────────────────────────────────────

class TestStripHtmlPreservesMath:
    """Test _strip_html_preserve_math converts Anki's internal tags correctly."""

    def test_inline_mathjax_tag_to_delimiter(self):
        html = 'The answer is <anki-mathjax>x^2</anki-mathjax> obviously.'
        result = flask_server._strip_html_preserve_math(html)
        assert result == 'The answer is \\(x^2\\) obviously.'

    def test_block_mathjax_tag_to_delimiter(self):
        html = '<anki-mathjax block="true">E = mc^2</anki-mathjax>'
        result = flask_server._strip_html_preserve_math(html)
        assert result == '\\[E = mc^2\\]'

    def test_mixed_mathjax_and_html(self):
        html = '<b>Bold</b> text with <anki-mathjax>\\frac{1}{2}</anki-mathjax> math'
        result = flask_server._strip_html_preserve_math(html)
        assert result == 'Bold text with \\(\\frac{1}{2}\\) math'

    def test_multiple_mathjax_tags(self):
        html = '<anki-mathjax>a</anki-mathjax> and <anki-mathjax>b</anki-mathjax>'
        result = flask_server._strip_html_preserve_math(html)
        assert result == '\\(a\\) and \\(b\\)'

    def test_no_mathjax_tags(self):
        html = '<b>Bold</b> <i>italic</i> plain'
        result = flask_server._strip_html_preserve_math(html)
        assert result == 'Bold italic plain'

    def test_plain_text_unchanged(self):
        text = 'No HTML at all'
        result = flask_server._strip_html_preserve_math(text)
        assert result == 'No HTML at all'

    def test_existing_delimiters_preserved(self):
        """Text that already has \\( \\) delimiters (not Anki tags) should pass through."""
        text = 'The formula is \\(x^2 + y^2\\) here'
        result = flask_server._strip_html_preserve_math(text)
        assert '\\(x^2 + y^2\\)' in result

    def test_mathjax_with_complex_latex(self):
        html = '<anki-mathjax>\\int_0^\\infty e^{-x^2} dx = \\frac{\\sqrt{\\pi}}{2}</anki-mathjax>'
        result = flask_server._strip_html_preserve_math(html)
        assert '\\(\\int_0^\\infty' in result
        assert '\\frac{\\sqrt{\\pi}}{2}\\)' in result


# ── Deck context round-trip ─────────────────────────────────────────────────────

class TestDeckContextMathRoundTrip:
    """Verify math survives the deck context pipeline: Anki → fetch → prompt."""

    def test_math_cards_in_deck_context(self, flask_client, tmp_config, mock_ankiconnect):
        """Cards with MathJax tags in Anki should appear with delimiters in the prompt."""
        # Simulate AnkiConnect returning cards with Anki's internal MathJax tags
        def side_effect(action, **params):
            if action == "findNotes":
                return [1, 2]
            if action == "notesInfo":
                return [
                    {
                        "fields": {
                            "Front": {"value": "What is <anki-mathjax>\\alpha</anki-mathjax>?"},
                            "Back": {"value": "<b>Greek letter</b> <anki-mathjax>\\alpha \\approx 0.05</anki-mathjax>"},
                        },
                        "tags": ["stats"],
                    },
                    {
                        "fields": {
                            "Front": {"value": "Plain question"},
                            "Back": {"value": "Plain answer"},
                        },
                        "tags": [],
                    },
                ]
            return None

        with patch("flask_server._ankiconnect", side_effect=side_effect):
            cards = flask_server.fetch_deck_cards("TestDeck")

        assert len(cards) == 2
        # Math card should have delimiters, not HTML tags
        assert "\\(\\alpha\\)" in cards[0]["front"]
        assert "<anki-mathjax>" not in cards[0]["front"]
        assert "\\(\\alpha \\approx 0.05\\)" in cards[0]["back"]
        assert "<b>" not in cards[0]["back"]
        # Plain card unchanged
        assert cards[1]["front"] == "Plain question"
        assert cards[1]["back"] == "Plain answer"


# ── Web UI includes MathJax ─────────────────────────────────────────────────────

class TestWebUIMathJax:
    """Verify the web UI loads MathJax for formula rendering."""

    def test_mathjax_script_in_html(self, flask_client):
        resp = flask_client.get("/")
        assert b"mathjax" in resp.data.lower()
        assert b"tex-mml-chtml.js" in resp.data

    def test_mathjax_config_in_html(self, flask_client):
        resp = flask_client.get("/")
        assert b"inlineMath" in resp.data

    def test_typeset_in_js(self, flask_client):
        resp = flask_client.get("/static/app.js")
        assert b"typesetMath" in resp.data
        assert b"MathJax.typesetPromise" in resp.data

    def test_escape_html_except_math_in_js(self, flask_client):
        resp = flask_client.get("/static/app.js")
        assert b"escapeHtmlExceptMath" in resp.data
