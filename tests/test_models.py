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

    def _judge(self, cards, criterion, api_key):
        """Ask a second LLM whether the cards meet the given criterion.
        Returns 'yes' or 'no'."""
        import anthropic

        formatted = "\n---\n".join(
            f"Card {i+1}:\n  Front: {c['front']}\n  Back: {c['back']}"
            for i, c in enumerate(cards)
        )
        client = anthropic.Anthropic(api_key=api_key)
        resp = client.messages.create(
            model="claude-haiku-4-5",
            max_tokens=50,
            messages=[{
                "role": "user",
                "content": (
                    f"You are judging flashcard output. The user's instruction was:\n"
                    f"\"{criterion}\"\n\n"
                    f"Here are the cards produced:\n{formatted}\n\n"
                    f"Do the cards follow the user's instruction? "
                    f"Reply with ONLY 'yes' or 'no'."
                ),
            }],
        )
        return resp.content[0].text.strip().lower()

    @pytest.mark.integration
    def test_rhyme_prompt_followed(self, text_png, api_key):
        """A casual 'rhyme everything' prompt — the kind a real user types —
        should produce cards whose backs actually rhyme."""
        prompt = "Rhyme everything you see here"
        cards = self._generate(text_png, api_key, prompt)
        assert len(cards) >= 1

        verdict = self._judge(cards, prompt, api_key)
        assert verdict.startswith("yes"), (
            f"Judge said '{verdict}' for prompt '{prompt}'. "
            f"Cards: {[(c['front'], c['back']) for c in cards]}"
        )

    @pytest.mark.integration
    def test_no_rhyme_prompt_not_rhyming(self, text_png, api_key):
        """Without a rhyming prompt, the judge should say cards do NOT rhyme.
        This proves the judge actually discriminates."""
        cards = self._generate(text_png, api_key, "")
        assert len(cards) >= 1

        verdict = self._judge(cards, "Rhyme everything you see here", api_key)
        assert verdict.startswith("no"), (
            f"Expected 'no' for plain cards, got '{verdict}'. "
            f"Cards: {[(c['front'], c['back']) for c in cards]}"
        )
