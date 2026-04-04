# Worklog

Recent session handoff notes. Read on session start, append before committing.
Keep only the last 10 entries. Each entry: date, device, what was done.

---

### 2026-04-04 | Mac
- Added 4 missing ch3 cards: BLEU/ROUGE/F1 worked example, lexical metrics limitation, AI judge capabilities, Chatbot Arena/Elo
- Quality audit of 64 ch3 cards: fixed 10 dense text blocks (added line breaks + bold terms), 2 jargon issues (tokenization, embeddings)
- Exported ch3 cards to ~/Desktop/chip_ai_engineering_ch3.zip (65 cards, 5 images)

### 2026-03-26 | Mac
- Fixed video timestamp bug: cards showed video duration (end) instead of current playback position
- Chrome extension now POSTs currentTime to server every 2s (was waiting for a message never sent)
- Server reads `_extension_timestamp` during card generation instead of unused config field
- 385 tests passing, pushed to GitHub
- NOTE: must reload extension in chrome://extensions after this update

### 2026-03-21 | Mac
- Added claude-code provider (subscription-based): shells out to `claude` CLI, no API key needed
- Production hardening: path traversal fix, config input validation, API key redaction in logs, AnkiConnect retry, queue TTL (24h), TOCTOU race fix, /health endpoint, structured logging, named constants
- Deleted deprecated anki_watcher.py, pinned dependencies
- Improved activity messages for empty/cancelled screenshots
- 339 tests passing (33 claude-code + 18 production), pushed to GitHub
- Fixed #4: init.lua crashed on other machines due to hardcoded pancake_hotkey.lua path; now loads optional extras.lua instead
- Added local server URL (http://localhost:5789) to README

### 2026-03-20 | Mac
- Fixed multi-screenshot mode: screencapture rejects dot-prefixed filenames, renamed .multi_ to multi_; fixed race condition and key interference in Hammerspoon
- Replaced watchdog FSEvents observer with polling thread (FSEvents unreliable under launchd after restart cycles)
- Added MathJax formula support: prompt rules for \(...\) delimiters, variable definitions required, _strip_html_preserve_math() for deck context round-trip, MathJax 3 CDN in web UI
- Added computation card rules: front must give all inputs, back shows formula + names broader concept
- Removed "Saved for" indicator from prompt field
- Claude-code subscription provider attempted but reverted (launchd integration issues) — notes saved for future session
- Updated /anki slash command, anki_watcher.md memory
- Exported Chip_AI_Engineering deck as zip with images for quiz game
- 306 tests passing (24 mathjax, 16 multi-screenshot, 2 prompt), pushed to GitHub

### 2026-03-17 | Mac
- Added 8 UX check tests to test_ui.py using shared ~/code/ux_checks/ library
- Tests: horizontal scroll, font readability, button uniformity, form field width, clickable not obscured, key elements in viewport, text overflow, section spacing
- All 18 UI tests passing

### 2026-03-15 | Mac
- Added YouTube video study mode: load video, fetch transcript, chunk by timestamp
- Three capture modes: screen (default), multi-screenshot stitching, video
- Chrome extension for exact YouTube playback position capture
- Video-sourced cards get yt-HHMMSS timestamp tags and YouTube badges in recent list
- Source mode cycling via hotkey (Opt+Shift+M) and API
- Per-deck source configuration persistence in config
- Comprehensive test suite: 246 tests passing
- Pushed to GitHub via subtree
