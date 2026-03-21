#!/usr/bin/env python3
"""
Sync queued Anki cards from server sessions.

Reads the queue from the remote server (via SSH), creates cards locally
via AnkiConnect, then clears the remote queue.

Usage:
    python claude_cards_sync.py                    # sync from server
    python claude_cards_sync.py --local            # sync local queue only
    python claude_cards_sync.py --server claude@5.161.182.15  # specify server
"""

import json
import os
import subprocess
import sys
import argparse

# Reuse card creation logic from claude_cards.py
from claude_cards import create_cards

REMOTE_USER = "claude"
REMOTE_HOST = "5.161.182.15"
REMOTE_QUEUE = "~/.claude-cards-queue.json"
LOCAL_QUEUE = os.path.expanduser("~/.claude-cards-queue.json")


def sync_remote(server):
    """Fetch queue from server, create cards, clear remote queue."""
    print(f"Syncing cards from {server}...")

    # Read remote queue
    try:
        result = subprocess.run(
            ["ssh", server, f"cat {REMOTE_QUEUE} 2>/dev/null || echo '[]'"],
            capture_output=True, text=True, timeout=15
        )
        queue = json.loads(result.stdout.strip())
    except Exception as e:
        print(f"Failed to read remote queue: {e}")
        return 0

    if not queue:
        print("No queued cards on server.")
        return 0

    print(f"Found {len(queue)} queued cards.")
    total = 0

    for item in queue:
        print(f"\n  Creating: {item['concept']}")
        try:
            created = create_cards(
                item["concept"],
                item["definition"],
                item["example"],
                item["deck"],
                item.get("tags", [])
            )
            total += created
        except Exception as e:
            print(f"    Error: {e}")

    # Clear remote queue
    try:
        subprocess.run(
            ["ssh", server, f"echo '[]' > {REMOTE_QUEUE}"],
            timeout=10
        )
        print(f"\nCleared remote queue.")
    except Exception as e:
        print(f"Warning: couldn't clear remote queue: {e}")

    return total


def sync_local():
    """Process local queue (if any)."""
    if not os.path.exists(LOCAL_QUEUE):
        return 0

    with open(LOCAL_QUEUE) as f:
        queue = json.load(f)

    if not queue:
        return 0

    print(f"Found {len(queue)} locally queued cards.")
    total = 0

    for item in queue:
        print(f"\n  Creating: {item['concept']}")
        try:
            created = create_cards(
                item["concept"],
                item["definition"],
                item["example"],
                item["deck"],
                item.get("tags", [])
            )
            total += created
        except Exception as e:
            print(f"    Error: {e}")

    # Clear local queue
    with open(LOCAL_QUEUE, "w") as f:
        json.dump([], f)

    return total


def main():
    parser = argparse.ArgumentParser(description="Sync queued Anki cards")
    parser.add_argument("--local", action="store_true", help="Sync local queue only")
    parser.add_argument("--server", default=f"{REMOTE_USER}@{REMOTE_HOST}")
    args = parser.parse_args()

    total = 0

    # Always sync local queue
    total += sync_local()

    # Sync remote unless --local
    if not args.local:
        total += sync_remote(args.server)

    print(f"\nTotal: {total} cards created")


if __name__ == "__main__":
    main()
