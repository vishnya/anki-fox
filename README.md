<div align="center">

```
┌───────────┐
│   |\_/|   │
│  /     \  │
│ /_.o o,_\ │
│    \@/    │
└───────────┘
```

</div>

# anki-fox

Take a screenshot of anything — a textbook, slide, diagram — and get Anki flashcards automatically. Works with Claude, GPT-4o, Gemini, Groq, or any local model.

## Requirements

- macOS
- [Anki](https://apps.ankiweb.net) installed
- An API key for your chosen provider (or a local model via Ollama/LM Studio)

Everything else (Hammerspoon, AnkiConnect, Python dependencies, background server) is handled by the install script.

## Install

```bash
curl -fsSL https://raw.githubusercontent.com/vishnya/anki-fox/main/install.sh | bash
```

The script:
- Installs [Hammerspoon](https://www.hammerspoon.org) (via Homebrew) — a macOS automation tool that powers the global hotkeys
- Installs [uv](https://github.com/astral-sh/uv) (if needed) and creates a `.venv` with Python dependencies from `requirements.txt`
- Opens Anki and walks you through adding the AnkiConnect add-on (code: `2055492159`)
- Sets up a launchd agent so the server starts automatically on login

### Hammerspoon permissions

Hammerspoon needs two macOS permissions to function. The install script will prompt you, but if you need to grant them manually:

1. **Accessibility** (required for the hotkey to work)
   - System Settings > Privacy & Security > Accessibility > toggle **Hammerspoon** ON
2. **Screen Recording** (required for screenshots)
   - System Settings > Privacy & Security > Screen Recording > toggle **Hammerspoon** ON

If hotkeys don't work after granting permissions, quit Hammerspoon (click the menu bar icon > Quit) and reopen it.

## Usage

| Hotkey | Action |
|--------|--------|
| `⌥⇧A` | Session active: takes screenshot. No session: opens config page. |
| `⌥⇧⌘A` | Stop session and reopen config page (switch decks/subjects). |

**Workflow:**
1. Press `⌥⇧A` — browser opens to `http://localhost:5789`
2. Choose a deck, pick your model, add your API key, click **Start Session**
3. Press `⌥⇧A` — drag to select any region of your screen
4. Cards appear in Anki within ~10 seconds
5. Watch progress in the **Activity Log** and cards in the **Recent Cards** panel

## Model support

Configure everything in the web UI — no decisions needed at install time. The **Model name** field (next to the Provider dropdown) controls the exact model; change it any time and it autosaves.

| Provider | Default model | Other models | API key |
|----------|--------------|--------------|---------|
| Anthropic *(default)* | `claude-sonnet-4-6` | `claude-opus-4-6` | [console.anthropic.com](https://console.anthropic.com) |
| OpenAI | `gpt-4o` | `gpt-4-turbo`, `gpt-4o-mini` | [platform.openai.com/api-keys](https://platform.openai.com/api-keys) |
| Groq | `llama-3.3-70b-versatile` | `llama-3.2-90b-vision-preview` | [console.groq.com](https://console.groq.com) |
| Gemini | `gemini-2.0-flash` | `gemini-1.5-pro`, `gemini-2.0-pro` | [aistudio.google.com](https://aistudio.google.com) |
| Custom endpoint | `minicpm-v` | `qwen2.5-vl`, `llava:13b`, `llama3.2-vision` | none required |

### Custom endpoint

Use this for any server that speaks the OpenAI API format — local or remote. No API key field is shown; the server handles auth however it chooses.

**Ollama (local, free)**
```bash
brew install ollama
ollama pull minicpm-v   # recommended — or: qwen2.5-vl, llava:13b, llama3.2-vision
```
- Base URL: `http://localhost:11434/v1`
- Model name: `minicpm-v` (match exactly what `ollama list` shows)
- JSON output is forced via `response_format` so even models that tend to add commentary will produce valid cards

**LM Studio (local, free)**
1. Download from [lmstudio.ai](https://lmstudio.ai) and load a vision model
2. Start the local server (default port 1234)
- Base URL: `http://localhost:1234/v1`
- Model name: the model identifier shown in LM Studio's server tab

**Remote / self-hosted (vLLM, llama.cpp, Together AI, etc.)**
- Base URL: your server's address, e.g. `http://192.168.1.10:8000/v1`
- Model name: whatever identifier your server expects

> Vision support varies by model. Whichever model you choose must accept image inputs — check before using.

## Config

Settings (deck, model, API key, custom prompt) are saved to `~/.anki-fox/config.json` with `chmod 600` and autosaved on blur — no explicit save step needed. The last-used deck is remembered and pre-selected on next visit. If `$ANTHROPIC_API_KEY` is set in your environment, it pre-fills on first run.

## Server logs

```bash
tail -f /tmp/anki-fox.log
```

## Claude `/anki` skill

If you use [Claude Code](https://claude.ai/code), there's a `/anki` slash command that loads full project context. The install script adds it automatically.

## How it works

```
⌥⇧A keypress (Hammerspoon)
  → GET /api/session → session active?
  → yes: screencapture -i → saves PNG to ~/AnkiFox/incoming/
  → no:  opens http://localhost:5789 in browser

flask_server.py (launchd background process, port 5789)
  → serves web UI at /
  → watchdog thread detects new PNG in incoming/
  → calls models.py → Claude/GPT/Groq/Gemini/Ollama generates cards
  → AnkiConnect HTTP API (localhost:8765) adds cards to Anki
  → SSE stream pushes progress to browser
```

## Uninstall

```bash
bash ~/anki-fox/uninstall.sh
```

Stops and removes the launchd agent, removes symlinks and the shell function. Prompts before deleting the repo.

## Files

```
flask_server.py       # Flask app: API endpoints + watchdog thread
config.py             # Read/write ~/.anki-fox/config.json
models.py             # Provider abstraction: Anthropic / OpenAI / Groq / Gemini / custom
requirements.txt      # Python dependencies (installed into .venv by install.sh)
anki.zsh              # anki() shell function (sourced by ~/.zshrc)
hammerspoon/
  init.lua            # Hotkey: checks session via GET /api/session
web/
  templates/
    index.html        # Config + session UI
  static/
    style.css         # Dark theme
    app.js            # Deck fetch, config save, session control, SSE cards
launchd/
  com.anki-fox.plist   # launchd template (install.sh fills in paths)
tests/                # pytest suite
claude/
  anki.md             # /anki Claude Code skill
CONTEXT.md            # Living architecture doc, updated each Claude session
install.sh            # One-step installer
uninstall.sh          # Removes everything install.sh added
```
