#!/usr/bin/env python3
"""
Create Anki cards from Claude Code sessions.
Generates bidirectional cards for system design and AI concepts.

Usage:
    python claude_cards.py "concept" "definition" "real example from our work" [--deck "deck name"] [--type sysdesign|ai]

Examples:
    python claude_cards.py \
        "sticky bit" \
        "A Linux permission rule on directories (like /tmp) that prevents users from deleting files they don't own, even if the directory is world-writable" \
        "Walkie's server ran as root and created temp files in /tmp. The claude user couldn't delete them because of the sticky bit. Fixed by eliminating temp files entirely."

    python claude_cards.py \
        "ring buffer" \
        "A fixed-size list that overwrites the oldest entry when full. Useful when you want to keep the last N items without using unlimited memory" \
        "Walkie keeps the last 500 WebSocket events per session in a ring buffer. When a phone reconnects, the server replays only the missed events instead of resending everything."

Cards created (bidirectional):
  1. Concept → Definition + Example  (what does this term mean?)
  2. Scenario → Concept              (what concept solves this problem?)
"""

import json
import sys
import argparse
import requests

ANKICONNECT_URL = "http://localhost:8765"
SYSDESIGN_DECK = "Claude System Design Learnings"
AI_DECK = "Claude AI Learnings"


def ankiconnect(action, **params):
    payload = {"action": action, "version": 6, "params": params}
    resp = requests.post(ANKICONNECT_URL, json=payload, timeout=10)
    result = resp.json()
    if result.get("error"):
        raise Exception(f"AnkiConnect error: {result['error']}")
    return result["result"]


def ensure_deck(deck_name):
    """Create deck if it doesn't exist."""
    decks = ankiconnect("deckNames")
    if deck_name not in decks:
        ankiconnect("createDeck", deck=deck_name)
        print(f"Created deck: {deck_name}")


def create_cards(concept, definition, example, deck, tags=None):
    """Create bidirectional Anki cards for a concept.

    Card 1 (concept → definition): "What is a ring buffer?"
    Card 2 (scenario → concept): Given a real problem, what concept solves it?
    """
    if tags is None:
        tags = []
    tags.append("claude-session")

    ensure_deck(deck)
    created = 0

    # Card 1: Concept → Definition + Example
    front1 = f"<b>What is: {concept}?</b>"
    back1 = (
        f"<b>{definition}</b>"
        f"<br><br>"
        f"<i>Real example:</i> {example}"
    )

    try:
        ankiconnect("addNote", note={
            "deckName": deck,
            "modelName": "Basic",
            "fields": {"Front": front1, "Back": back1},
            "tags": tags,
            "options": {"allowDuplicate": False},
        })
        created += 1
        print(f"  Card 1: What is {concept}?")
    except Exception as e:
        if "duplicate" in str(e).lower():
            print(f"  Card 1: skipped (duplicate)")
        else:
            raise

    # Card 2: Scenario → Concept
    front2 = (
        f"<b>What system design concept is this?</b>"
        f"<br><br>"
        f"{example}"
    )
    back2 = (
        f"<b>{concept}</b>"
        f"<br><br>"
        f"{definition}"
    )

    try:
        ankiconnect("addNote", note={
            "deckName": deck,
            "modelName": "Basic",
            "fields": {"Front": front2, "Back": back2},
            "tags": tags,
            "options": {"allowDuplicate": False},
        })
        created += 1
        print(f"  Card 2: What concept solves this?")
    except Exception as e:
        if "duplicate" in str(e).lower():
            print(f"  Card 2: skipped (duplicate)")
        else:
            raise

    return created


def main():
    parser = argparse.ArgumentParser(description="Create Anki cards from Claude sessions")
    parser.add_argument("concept", help="The term or concept name")
    parser.add_argument("definition", help="Plain-language definition")
    parser.add_argument("example", help="Real example from our work")
    parser.add_argument("--deck", default=None, help=f"Deck name (default: {SYSDESIGN_DECK})")
    parser.add_argument("--type", choices=["sysdesign", "ai"], default="sysdesign",
                        help="Type of concept (determines default deck)")
    parser.add_argument("--tags", nargs="*", default=[], help="Additional tags")

    args = parser.parse_args()

    deck = args.deck or (AI_DECK if args.type == "ai" else SYSDESIGN_DECK)
    tags = args.tags + [f"type:{args.type}"]

    print(f"Creating cards in '{deck}':")
    created = create_cards(args.concept, args.definition, args.example, deck, tags)
    print(f"Done: {created} cards created")


if __name__ == "__main__":
    main()
