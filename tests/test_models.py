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
        assert "IMPORTANT — USER INSTRUCTION (follow this exactly):" in prompt
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


class TestRhymeAdherence:
    """Lightweight integration test: verify the model follows a rhyming prompt."""

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
    def rhyme_config(self):
        return {
            "model": {"provider": "anthropic", "model_name": "claude-haiku-4-5"},
            "api_keys": {"anthropic": ""},
            "custom_prompt": "Write the back of every card as a rhyming couplet.",
        }

    @pytest.mark.integration
    def test_rhyming_prompt_produces_rhymes(self, text_png, rhyme_config):
        """Generate cards with a rhyming instruction, then use a second LLM
        call to judge whether the backs actually rhyme."""
        import anthropic

        api_key = os.environ.get("ANTHROPIC_API_KEY", "")
        if not api_key:
            pytest.skip("ANTHROPIC_API_KEY not set")
        rhyme_config["api_keys"]["anthropic"] = api_key

        cards = models.generate_cards(text_png, rhyme_config)
        assert len(cards) >= 1, "Should generate at least one card"

        # Ask a second model to judge rhyming
        backs = "\n---\n".join(
            f"Card {i+1} back:\n{c['back']}" for i, c in enumerate(cards)
        )
        client = anthropic.Anthropic(api_key=api_key)
        judge = client.messages.create(
            model="claude-haiku-4-5",
            max_tokens=200,
            messages=[{
                "role": "user",
                "content": (
                    "You are a rhyme judge. The user asked for flashcard backs "
                    "written as rhyming couplets. Below are the card backs produced. "
                    "Does at least one card back contain a rhyming couplet "
                    "(two lines whose ending words rhyme)?\n\n"
                    f"{backs}\n\n"
                    "Reply with ONLY 'yes' or 'no'."
                ),
            }],
        )
        verdict = judge.content[0].text.strip().lower()
        assert verdict.startswith("yes"), (
            f"Rhyme judge said '{verdict}'. "
            f"Card backs: {[c['back'] for c in cards]}"
        )

    @pytest.mark.integration
    def test_no_rhyme_prompt_does_not_rhyme(self, text_png):
        """Generate cards WITHOUT a rhyming instruction and verify the judge
        says they do NOT rhyme — confirms the judge isn't just saying yes."""
        import anthropic

        api_key = os.environ.get("ANTHROPIC_API_KEY", "")
        if not api_key:
            pytest.skip("ANTHROPIC_API_KEY not set")

        plain_config = {
            "model": {"provider": "anthropic", "model_name": "claude-haiku-4-5"},
            "api_keys": {"anthropic": api_key},
            "custom_prompt": "",
        }
        cards = models.generate_cards(text_png, plain_config)
        assert len(cards) >= 1

        backs = "\n---\n".join(
            f"Card {i+1} back:\n{c['back']}" for i, c in enumerate(cards)
        )
        client = anthropic.Anthropic(api_key=api_key)
        judge = client.messages.create(
            model="claude-haiku-4-5",
            max_tokens=200,
            messages=[{
                "role": "user",
                "content": (
                    "You are a rhyme judge. The user asked for flashcard backs "
                    "written as rhyming couplets. Below are the card backs produced. "
                    "Does at least one card back contain a rhyming couplet "
                    "(two lines whose ending words rhyme)?\n\n"
                    f"{backs}\n\n"
                    "Reply with ONLY 'yes' or 'no'."
                ),
            }],
        )
        verdict = judge.content[0].text.strip().lower()
        assert verdict.startswith("no"), (
            f"Expected judge to say 'no' for plain cards, but got '{verdict}'. "
            f"Card backs: {[c['back'] for c in cards]}"
        )
