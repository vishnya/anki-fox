#!/usr/bin/env bash
set -e

cat << 'BANNER'
  ┌───────────┐
  │   |\_/|   │
  │  /     \  │
  │ /_.x x,_\ │
  │    \@/    │
  └───────────┘
  === anki-fox uninstall ===
BANNER
echo ""

REPO_DIR="$HOME/anki-fox"
PLIST="$HOME/Library/LaunchAgents/com.anki-fox.plist"

# launchd agent
if [ -f "$PLIST" ]; then
  launchctl unload "$PLIST" 2>/dev/null || true
  rm -f "$PLIST"
  echo "✓ launchd agent removed"
fi

# Symlinks
rm -f "$HOME/anki_watcher.py"    # legacy symlink, may not exist
rm -f "$HOME/.hammerspoon/init.lua"
rm -rf "$HOME/.anki-fox"
echo "✓ Symlinks removed"

# Shell function
if grep -q "anki-fox/anki.zsh" "$HOME/.zshrc" 2>/dev/null; then
  sed -i '' '/# Anki watcher/d' "$HOME/.zshrc"
  sed -i '' '/anki-fox\/anki.zsh/d' "$HOME/.zshrc"
  echo "✓ Shell function removed from ~/.zshrc"
fi

# Claude skill
rm -f "$HOME/.claude/commands/anki.md"
echo "✓ Claude /anki skill removed"

# Hammerspoon
if [ -d "/Applications/Hammerspoon.app" ]; then
  read -rp "Uninstall Hammerspoon? [y/N] " hs_confirm
  if [[ "$hs_confirm" =~ ^[Yy]$ ]]; then
    osascript -e 'quit app "Hammerspoon"' 2>/dev/null || true
    brew uninstall --cask hammerspoon 2>/dev/null || rm -rf /Applications/Hammerspoon.app
    echo "✓ Hammerspoon uninstalled"
  else
    echo "  Hammerspoon kept"
  fi
fi

# Repo (includes .venv with Python deps)
if [ -d "$REPO_DIR" ]; then
  read -rp "Delete repo at $REPO_DIR? [y/N] " confirm
  if [[ "$confirm" =~ ^[Yy]$ ]]; then
    rm -rf "$REPO_DIR"
    echo "✓ Repo deleted"
  else
    echo "  Repo kept at $REPO_DIR"
  fi
fi

echo ""
echo "=== Done. ==="
