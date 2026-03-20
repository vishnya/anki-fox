import os
import pytest
from PIL import Image, ImageDraw, ImageFont

import models


class TestBuildPrompt:
    """Verify _build_prompt places user instructions prominently."""

    def test_no_custom_prompt_returns_base(self):
        prompt = models._build_prompt({"custom_prompt": ""})
        assert prompt == models.PROMPT_TEMPLATE

    def test_custom_prompt_appears_before_rules(self):
        prompt = models._build_prompt({"custom_prompt": "Rhyme everything"})
        rules_pos = prompt.index("RULES:")
        user_pos = prompt.index("Rhyme everything")
        assert user_pos < rules_pos, "User instruction should appear before RULES"

    def test_custom_prompt_in_header_block(self):
        prompt = models._build_prompt({"custom_prompt": "Focus on cells"})
        assert "IMPORTANT — USER INSTRUCTION (this overrides any conflicting rules below):" in prompt
        assert "Focus on cells" in prompt

    def test_custom_prompt_reinforced_in_selfcheck(self):
        prompt = models._build_prompt({"custom_prompt": "Use rhymes"})
        # Should appear twice: once in header, once in self-check
        assert prompt.count("Use rhymes") == 2
        selfcheck_pos = prompt.index("SELF-CHECK:")
        second_occurrence = prompt.index("Use rhymes", prompt.index("Use rhymes") + 1)
        assert second_occurrence > selfcheck_pos, "Should be reinforced after SELF-CHECK"

    def test_whitespace_only_prompt_returns_base(self):
        prompt = models._build_prompt({"custom_prompt": "   \n  "})
        assert prompt == models.PROMPT_TEMPLATE

    def test_computation_rules_in_prompt(self):
        prompt = models._build_prompt({"custom_prompt": ""})
        assert "computation" in prompt.lower()
        assert "EVERY number needed" in prompt
        assert "broader concept" in prompt

    def test_computation_selfcheck_in_prompt(self):
        prompt = models._build_prompt({"custom_prompt": ""})
        selfcheck_pos = prompt.index("SELF-CHECK:")
        comp_check = "computation cards"
        assert comp_check in prompt[selfcheck_pos:]


class TestPromptAdherence:
    """Integration tests: verify the full pipeline (screenshot → prompt → cards)
    actually follows the user's custom prompt. Uses a second LLM call as judge."""

    @pytest.fixture
    def text_png(self, tmp_path):
        """Create a screenshot with readable text content."""
        img = Image.new("RGB", (600, 200), color=(255, 255, 255))
        draw = ImageDraw.Draw(img)
        draw.text((20, 20), "Mitochondria are the powerhouse of the cell.\n"
                            "They produce ATP through oxidative phosphorylation.\n"
                            "The inner membrane has many folds called cristae.",
                  fill=(0, 0, 0))
        path = tmp_path / "textbook_screenshot.png"
        img.save(str(path))
        return str(path)

    @pytest.fixture
    def api_key(self):
        key = os.environ.get("ANTHROPIC_API_KEY", "")
        if not key:
            pytest.skip("ANTHROPIC_API_KEY not set")
        return key

    def _generate(self, image_path, api_key, custom_prompt):
        """Run the real generate_cards pipeline with the given custom prompt."""
        config = {
            "model": {"provider": "anthropic", "model_name": "claude-haiku-4-5"},
            "api_keys": {"anthropic": api_key},
            "custom_prompt": custom_prompt,
        }
        return models.generate_cards(image_path, config)

    @pytest.mark.integration
    def test_spanish_prompt_followed(self, text_png, api_key):
        """Custom prompt asking for Spanish backs — easy to verify deterministically."""
        prompt = "Write all card backs in Spanish"
        cards = self._generate(text_png, api_key, prompt)
        assert len(cards) >= 1

        # Deterministic check: at least half the cards should contain common Spanish words
        spanish_markers = ("la", "el", "de", "las", "los", "es", "en", "del", "una", "son", "por", "que", "se")
        spanish_count = sum(
            1 for c in cards
            if any(f" {w} " in f" {c['back'].lower()} " for w in spanish_markers)
        )
        assert spanish_count >= len(cards) // 2, (
            f"Expected Spanish backs, but only {spanish_count}/{len(cards)} look Spanish. "
            f"Cards: {[(c['front'], c['back']) for c in cards]}"
        )

    @pytest.mark.integration
    def test_no_spanish_prompt_not_spanish(self, text_png, api_key):
        """Without a Spanish prompt, cards should be in English.
        This proves the check actually discriminates."""
        cards = self._generate(text_png, api_key, "")
        assert len(cards) >= 1

        spanish_markers = ("la", "el", "de", "las", "los", "es", "en", "del", "una", "son", "por", "que", "se")
        spanish_count = sum(
            1 for c in cards
            if any(f" {w} " in f" {c['back'].lower()} " for w in spanish_markers)
        )
        # English cards shouldn't have many Spanish markers
        assert spanish_count < len(cards) // 2, (
            f"Expected English backs, but {spanish_count}/{len(cards)} look Spanish. "
            f"Cards: {[(c['front'], c['back']) for c in cards]}"
        )
