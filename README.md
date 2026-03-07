<h1 align="center">anki-fox</h1>

<p align="center">
  <picture>
    <source media="(prefers-color-scheme: dark)" srcset="fox-cards-all-dark.png" />
    <source media="(prefers-color-scheme: light)" srcset="fox-cards-all-light.png" />
    <img alt="anki-fox logo" src="fox-cards-all-light.png" width="100%" />
  </picture>
</p>

**Screenshot anything. Get Anki flashcards in seconds.**

Point it at a textbook page, lecture slide, diagram, or article — press a hotkey, drag to select what you want to learn, and flashcards appear in Anki automatically. No copy-pasting, no typing.

Works with Anthropic, OpenAI, Google, Groq, or a free local model (no internet required).

---

## Quickstart

1. Install [Anki](https://apps.ankiweb.net) if you haven't already
2. Get an API key from your favorite AI provider (Anthropic, OpenAI, Google, or Groq — free tiers available)
3. Run the installer:
   ```bash
   curl -fsSL https://raw.githubusercontent.com/vishnya/anki-fox/main/install.sh | bash
   ```
4. Follow the prompts — it walks you through everything, including the one-time Anki setup
5. Press `⌥⇧A` (Option + Shift + A), paste your API key, pick a deck, click **Start Session**
6. Press `⌥⇧A` again and drag over anything on your screen — cards appear in Anki in seconds

---

## What you need

- A Mac
- [Anki](https://apps.ankiweb.net) (free, download and install it first)
- An API key from one of the supported AI providers — or a free local model (see below)

The installer handles everything else automatically.

---

## Install

Open Terminal and paste this:

```bash
curl -fsSL https://raw.githubusercontent.com/vishnya/anki-fox/main/install.sh | bash
```

The installer will:
- Install the tools it needs (Homebrew, Hammerspoon, Python)
- Walk you through a one-time Anki setup (just copy-paste an add-on code)
- Start a background service that runs automatically on login

**One thing you'll need to do manually:** grant two permissions to Hammerspoon when macOS asks — Accessibility and Screen Recording. Both are in System Settings > Privacy & Security. Without these, the hotkey and screenshots won't work.

If hotkeys stop working after granting permissions, click the Hammerspoon icon in your menu bar and choose Quit, then reopen it.

---

## How to use it

| Hotkey | What it does |
|--------|--------------|
| `⌥⇧A` (Option + Shift + A) | Opens setup if no session is running. Takes a screenshot if one is. |
| `⌥⇧⌘A` (Option + Shift + Cmd + A) | Stops the current session and reopens setup. |

**Step by step:**

1. Press `⌥⇧A` — your browser opens to the anki-fox setup page
2. Choose which Anki deck to add cards to
3. Pick an AI model and paste your API key
4. Click **Start Session**
5. Press `⌥⇧A` again, then drag to select any part of your screen
6. Cards show up in Anki in about 10 seconds

You can watch progress live in the **Activity Log** on the setup page.

---

## Which AI model should I use?

The setup page has a dropdown — you can switch models any time and it saves automatically.

| Provider | Cost | Where to get a key |
|----------|------|--------------------|
| Anthropic (Claude) — *default* | Paid, ~$0.01–0.05 per screenshot | [console.anthropic.com](https://console.anthropic.com) |
| OpenAI (GPT-4o) | Paid, similar pricing | [platform.openai.com/api-keys](https://platform.openai.com/api-keys) |
| Google (Gemini) | Free tier available | [aistudio.google.com](https://aistudio.google.com) |
| Groq | Free tier available | [console.groq.com](https://console.groq.com) |
| Local model (Ollama) | Free, runs on your Mac | No key needed — see below |

### Free option: run a local model with Ollama

No internet connection or API key required. Quality is lower than cloud models, but it's completely free.

```bash
brew install ollama
ollama pull minicpm-v
```

Then in the setup page, choose **Custom endpoint** and set:
- Base URL: `http://localhost:11434/v1`
- Model name: `minicpm-v`

---

## Where are my settings stored?

In `~/.anki-fox/config.json`. The file is private (readable only by you). Settings save automatically — there's no Save button.

If you have `$ANTHROPIC_API_KEY` set in your terminal environment, it will pre-fill on first run.

---

## Troubleshooting

View the server log:
```bash
tail -f /tmp/anki-fox.log
```

---

## Uninstall

```bash
bash ~/anki-fox/uninstall.sh
```

This removes everything the installer added and prompts before deleting the repo folder.
