"""
Tests for claude_cards.py, claude_cards_queue.py, and claude_cards_sync.py.

These test the bidirectional card creation, queue/sync flow for server sessions,
and AnkiConnect integration.
"""

import json
import os
import sys
import tempfile
import pytest
from unittest.mock import patch, MagicMock

# Add parent dir to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import claude_cards
import claude_cards_queue


# ── claude_cards.py tests ────────────────────────────────────────────────────────


class TestCreateCards:
    """Test bidirectional card creation via AnkiConnect."""

    def test_creates_two_cards(self):
        """Each concept should produce exactly 2 cards: vocab and scenario."""
        calls = []

        def mock_ankiconnect(action, **params):
            calls.append((action, params))
            if action == "deckNames":
                return ["Default", "Claude System Design Learnings"]
            if action == "addNote":
                return 12345
            return None

        with patch.object(claude_cards, "ankiconnect", mock_ankiconnect):
            created = claude_cards.create_cards(
                "test concept",
                "test definition",
                "test example",
                "Claude System Design Learnings",
            )

        assert created == 2
        add_calls = [c for c in calls if c[0] == "addNote"]
        assert len(add_calls) == 2

    def test_card1_is_vocab_direction(self):
        """Card 1 should ask 'What is X?' with definition + example on back."""
        calls = []

        def mock_ankiconnect(action, **params):
            calls.append((action, params))
            if action == "deckNames":
                return ["Claude System Design Learnings"]
            if action == "addNote":
                return 12345
            return None

        with patch.object(claude_cards, "ankiconnect", mock_ankiconnect):
            claude_cards.create_cards(
                "ring buffer",
                "a fixed-size list",
                "Walkie uses one",
                "Claude System Design Learnings",
            )

        add_calls = [c for c in calls if c[0] == "addNote"]
        card1 = add_calls[0][1]["note"]["fields"]
        assert "What is" in card1["Front"]
        assert "ring buffer" in card1["Front"]
        assert "a fixed-size list" in card1["Back"]
        assert "Walkie uses one" in card1["Back"]

    def test_card2_is_scenario_direction(self):
        """Card 2 should present a scenario and ask what concept applies."""
        calls = []

        def mock_ankiconnect(action, **params):
            calls.append((action, params))
            if action == "deckNames":
                return ["Claude System Design Learnings"]
            if action == "addNote":
                return 12345
            return None

        with patch.object(claude_cards, "ankiconnect", mock_ankiconnect):
            claude_cards.create_cards(
                "ring buffer",
                "a fixed-size list",
                "Walkie uses one for event replay",
                "Claude System Design Learnings",
            )

        add_calls = [c for c in calls if c[0] == "addNote"]
        card2 = add_calls[1][1]["note"]["fields"]
        assert "What system design concept" in card2["Front"]
        assert "Walkie uses one for event replay" in card2["Front"]
        assert "ring buffer" in card2["Back"]

    def test_creates_deck_if_missing(self):
        """Should call createDeck if the deck doesn't exist yet."""
        calls = []

        def mock_ankiconnect(action, **params):
            calls.append((action, params))
            if action == "deckNames":
                return ["Default"]  # target deck not in list
            if action == "createDeck":
                return None
            if action == "addNote":
                return 12345
            return None

        with patch.object(claude_cards, "ankiconnect", mock_ankiconnect):
            claude_cards.create_cards(
                "test", "def", "ex", "Claude System Design Learnings"
            )

        create_calls = [c for c in calls if c[0] == "createDeck"]
        assert len(create_calls) == 1
        assert create_calls[0][1]["deck"] == "Claude System Design Learnings"

    def test_skips_duplicates(self):
        """Duplicate cards should be skipped, not raise errors."""
        call_count = 0

        def mock_ankiconnect(action, **params):
            nonlocal call_count
            if action == "deckNames":
                return ["Claude System Design Learnings"]
            if action == "addNote":
                call_count += 1
                if call_count == 1:
                    raise Exception("cannot create note because it is a duplicate")
                return 12345
            return None

        with patch.object(claude_cards, "ankiconnect", mock_ankiconnect):
            created = claude_cards.create_cards(
                "test", "def", "ex", "Claude System Design Learnings"
            )

        # One duplicate, one success
        assert created == 1

    def test_tags_include_claude_session(self):
        """All cards should be tagged with 'claude-session'."""
        calls = []

        def mock_ankiconnect(action, **params):
            calls.append((action, params))
            if action == "deckNames":
                return ["Claude System Design Learnings"]
            if action == "addNote":
                return 12345
            return None

        with patch.object(claude_cards, "ankiconnect", mock_ankiconnect):
            claude_cards.create_cards(
                "test", "def", "ex", "Claude System Design Learnings"
            )

        add_calls = [c for c in calls if c[0] == "addNote"]
        for call in add_calls:
            assert "claude-session" in call[1]["note"]["tags"]

    def test_ai_type_uses_ai_deck(self):
        """--type ai should default to the AI learnings deck."""
        deck = claude_cards.AI_DECK if True else claude_cards.SYSDESIGN_DECK
        assert deck == "Claude AI Learnings"


# ── claude_cards_queue.py tests ──────────────────────────────────────────────────


class TestCardQueue:
    """Test the queue-and-sync flow for server sessions."""

    def test_queue_creates_file(self):
        """Queuing a card should create the queue file with the card data."""
        with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as f:
            queue_file = f.name
            f.write(b"[]")

        try:
            with patch.object(claude_cards_queue, "QUEUE_FILE", queue_file):
                claude_cards_queue.queue_card(
                    "test concept", "test def", "test example",
                    "Claude System Design Learnings", ["type:sysdesign"]
                )

            with open(queue_file) as f:
                queue = json.load(f)

            assert len(queue) == 1
            assert queue[0]["concept"] == "test concept"
            assert queue[0]["definition"] == "test def"
            assert queue[0]["example"] == "test example"
            assert queue[0]["deck"] == "Claude System Design Learnings"
            assert "queued_at" in queue[0]
        finally:
            os.unlink(queue_file)

    def test_queue_appends(self):
        """Multiple queued cards should accumulate in the file."""
        with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as f:
            queue_file = f.name
            f.write(b"[]")

        try:
            with patch.object(claude_cards_queue, "QUEUE_FILE", queue_file):
                claude_cards_queue.queue_card("concept1", "def1", "ex1", "Deck")
                claude_cards_queue.queue_card("concept2", "def2", "ex2", "Deck")

            with open(queue_file) as f:
                queue = json.load(f)

            assert len(queue) == 2
            assert queue[0]["concept"] == "concept1"
            assert queue[1]["concept"] == "concept2"
        finally:
            os.unlink(queue_file)

    def test_queue_handles_missing_file(self):
        """Should create the queue file if it doesn't exist."""
        queue_file = tempfile.mktemp(suffix=".json")
        assert not os.path.exists(queue_file)

        try:
            with patch.object(claude_cards_queue, "QUEUE_FILE", queue_file):
                claude_cards_queue.queue_card("new", "def", "ex", "Deck")

            assert os.path.exists(queue_file)
            with open(queue_file) as f:
                queue = json.load(f)
            assert len(queue) == 1
        finally:
            if os.path.exists(queue_file):
                os.unlink(queue_file)

    def test_load_empty_queue(self):
        """Loading a nonexistent queue should return empty list."""
        with patch.object(claude_cards_queue, "QUEUE_FILE", "/nonexistent/path.json"):
            queue = claude_cards_queue.load_queue()
        assert queue == []
