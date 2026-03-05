#!/usr/bin/env bash
set -e

cat << 'BANNER'
      /\_/\
     ( o.o )
      = ^ =
  === anki-fox setup ===
BANNER
echo ""

# ── Homebrew ──────────────────────────────────────────────────────────────────
if ! command -v brew &>/dev/null; then
  echo "Installing Homebrew..."
  /bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"
else
  echo "✓ Homebrew"
fi

# ── Hammerspoon ───────────────────────────────────────────────────────────────
if [ ! -d "/Applications/Hammerspoon.app" ]; then
  echo "Installing Hammerspoon..."
  brew install --cask hammerspoon
else
  echo "✓ Hammerspoon"
fi

# ── Clone repo ────────────────────────────────────────────────────────────────
REPO_DIR="$HOME/anki-fox"
PROJECT="$REPO_DIR"

if [ ! -d "$REPO_DIR/.git" ]; then
  echo "Cloning repo to $REPO_DIR..."
  git clone https://github.com/vishnya/anki-fox "$REPO_DIR"
else
  echo "✓ Repo already present at $REPO_DIR"
fi

# ── uv + Python dependencies ─────────────────────────────────────────────────
if ! command -v uv &>/dev/null; then
  echo "Installing uv..."
  curl -LsSf https://astral.sh/uv/install.sh | sh
  export PATH="$HOME/.local/bin:$PATH"
fi
echo "✓ uv"

VENV_DIR="$REPO_DIR/.venv"
echo "Installing Python dependencies..."
uv venv "$VENV_DIR" --quiet 2>/dev/null || true
uv pip install --quiet -r "$REPO_DIR/requirements.txt" --python "$VENV_DIR/bin/python"
echo "✓ Python dependencies (in $VENV_DIR)"

# ── Symlinks ──────────────────────────────────────────────────────────────────
mkdir -p "$HOME/.hammerspoon"
ln -sf "$PROJECT/hammerspoon/init.lua" "$HOME/.hammerspoon/init.lua"
mkdir -p "$HOME/.anki-fox"
ln -sf "$PROJECT/CONTEXT.md" "$HOME/.anki-fox/CONTEXT.md"
echo "✓ Symlinks"

# ── Claude /anki skill ────────────────────────────────────────────────────────
if [ -d "$HOME/.claude/commands" ]; then
  cp "$PROJECT/claude/anki.md" "$HOME/.claude/commands/anki.md"
  echo "✓ Claude /anki skill"
fi

# ── .zshrc ────────────────────────────────────────────────────────────────────
if ! grep -q "anki-fox/anki.zsh" "$HOME/.zshrc" 2>/dev/null; then
  printf '\n# Anki watcher\nsource %s/anki.zsh\n' "$PROJECT" >> "$HOME/.zshrc"
fi
echo "✓ Shell function"

# ── launchd agent ─────────────────────────────────────────────────────────────
PYTHON_PATH="$REPO_DIR/.venv/bin/python"
PLIST_DEST="$HOME/Library/LaunchAgents/com.anki-fox.plist"

mkdir -p "$HOME/Library/LaunchAgents"
sed \
  -e "s|__PYTHON__|${PYTHON_PATH}|g" \
  -e "s|__PROJECT__|${PROJECT}|g" \
  "$PROJECT/launchd/com.anki-fox.plist" > "$PLIST_DEST"

# Unload if already loaded (e.g. re-running install), then reload
launchctl unload "$PLIST_DEST" 2>/dev/null || true
launchctl load   "$PLIST_DEST"
echo "✓ launchd agent (auto-starts on login)"

# ── AnkiConnect ───────────────────────────────────────────────────────────────
echo ""
echo "Opening Anki to install the AnkiConnect add-on..."
open -a Anki 2>/dev/null || echo "(Anki not found — install it from https://apps.ankiweb.net first)"
echo ""
echo "  In Anki:  Tools > Add-ons > Get Add-ons"
echo "  Code:     2055492159"
echo "  Click OK, then restart Anki."
echo ""
read -rp "Press Enter once AnkiConnect is installed and Anki has restarted... "

# ── Hammerspoon first launch ──────────────────────────────────────────────────
echo ""
echo "Opening Hammerspoon..."
echo ""
echo "  Hammerspoon is a macOS automation tool that powers the ⌥⇧A hotkey."
echo "  It needs two permissions to work:"
echo ""
echo "  1. ACCESSIBILITY (for the hotkey)"
echo "     When the Hammerspoon Preferences window appears:"
echo "     → Click 'Enable Accessibility'"
echo "     → macOS will open System Settings > Privacy & Security > Accessibility"
echo "     → Toggle Hammerspoon ON"
echo ""
echo "  2. SCREEN RECORDING (for screenshots)"
echo "     When the 'Hammerspoon would like to record this computer's screen' dialog appears:"
echo "     → Click 'Open System Settings'"
echo "     → System Settings > Privacy & Security > Screen Recording"
echo "     → Toggle Hammerspoon ON"
echo ""
echo "  (You may need to quit and reopen Hammerspoon after granting permissions.)"
echo ""
open -a Hammerspoon
read -rp "Press Enter once you've granted both permissions... "

echo ""
cat << 'BANNER'
      /\_/\
     ( o.o )
      = ^ =
    === Done! ===
BANNER
echo ""
echo "  1. Press ⌥⇧A  → opens http://localhost:5789 in your browser"
echo "  2. Choose deck, add your API key, click Start Session"
echo "  3. Press ⌥⇧A  → crosshair to screenshot → cards appear in Anki"
echo ""
echo "Server logs: tail -f /tmp/anki-fox.log"
echo "Uninstall:   bash $REPO_DIR/uninstall.sh"
