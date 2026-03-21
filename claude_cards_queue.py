#!/usr/bin/env python3
"""
Queue Anki cards for later sync when AnkiConnect isn't available (e.g., server sessions).

On the server: saves card definitions to ~/.claude-cards-queue.json
On the Mac: claude_cards_sync.py reads the queue and creates the cards via AnkiConnect.

Usage (server):
    python claude_cards_queue.py "concept" "definition" "example" [--type sysdesign|ai]

The queue file is a JSON array of card objects. Each object has:
    concept, definition, example, deck, tags, queued_at
"""

import json
import os
import sys
import argparse
from datetime import datetime

QUEUE_FILE = os.path.expanduser("~/.claude-cards-queue.json")
SYSDESIGN_DECK = "Claude System Design Learnings"
AI_DECK = "Claude AI Learnings"


def load_queue():
    if os.path.exists(QUEUE_FILE):
        with open(QUEUE_FILE) as f:
            return json.load(f)
    return []


def save_queue(queue):
    with open(QUEUE_FILE, "w") as f:
        json.dump(queue, f, indent=2)


def queue_card(concept, definition, example, deck, tags=None):
    queue = load_queue()
    queue.append({
        "concept": concept,
        "definition": definition,
        "example": example,
        "deck": deck,
        "tags": tags or [],
        "queued_at": datetime.now().isoformat(),
    })
    save_queue(queue)
    print(f"Queued: {concept} (will sync to Anki on next Mac session)")


def main():
    parser = argparse.ArgumentParser(description="Queue Anki cards for later sync")
    parser.add_argument("concept", help="The term or concept name")
    parser.add_argument("definition", help="Plain-language definition")
    parser.add_argument("example", help="Real example from our work")
    parser.add_argument("--deck", default=None)
    parser.add_argument("--type", choices=["sysdesign", "ai"], default="sysdesign")
    parser.add_argument("--tags", nargs="*", default=[])

    args = parser.parse_args()
    deck = args.deck or (AI_DECK if args.type == "ai" else SYSDESIGN_DECK)
    tags = args.tags + [f"type:{args.type}"]

    queue_card(args.concept, args.definition, args.example, deck, tags)


if __name__ == "__main__":
    main()
