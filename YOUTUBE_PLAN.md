# YouTube "Study as you watch" — Implementation Plan

## Concept
Add YouTube video support to anki-fox. User watches a video, presses ⌥⇧A at key moments, and gets cards generated from **both** the screenshot and the transcript context around that timestamp.

## Unified Source Model

### Three capture modes, one hotkey
Instead of bolting YouTube on as a separate feature, introduce a **Source** concept that unifies all capture modes:

| Source | Trigger | What happens on ⌥⇧A |
|--------|---------|---------------------|
| **Screen** | Default | Single screenshot → cards (today's behavior) |
| **Multi** | User selects | Each press adds a region, stitched into one image → cards |
| **Video** | User selects + pastes URL | Screenshot + transcript chunk around current timestamp → cards |

### UI: Collapsible source selector
- Add a `<details>` row (same pattern as Model settings): `Source: Screen ▸`
- Collapsed by default — screenshot-only users never see it
- Opens to reveal three pill-shaped buttons: `Screen | Multi | Video`
- **Screen** is the default, pre-selected
- **Video** pill reveals a YouTube URL input + transcript status:
  ```
  ┌──────────────────────────────────────────┐
  │ [thumb]  Video Title                     │
  │          12 chapters · 24:30             │
  │          ✓ Transcript loaded             │
  └──────────────────────────────────────────┘
  ```
- Source selection is saved **per-deck** in config (like deck_prompts)

### Status banner adapts to source
```
Screen:  "Session active — press ⌥⇧A to capture"
Multi:   "Session active — press ⌥⇧A to start stitching"
Video:   "Session active — press ⌥⇧A to capture moment — watching [title]"
```

### Cards show their lineage
- Screenshot cards → no badge (default)
- Stitched cards → small ⊞ icon
- YouTube cards → `▶ 3:42` timestamp badge (clickable, opens YouTube at that time)

## Chrome Extension (for exact timestamps)

### Why
The extension reads `document.querySelector('video').currentTime` from the active YouTube tab, giving exact timestamps without OCR or inference.

### Architecture
~30 lines of code:
```
~/.anki-fox/extension/
├── manifest.json        (externally_connectable to localhost:5789)
├── content.js           (injected on youtube.com, responds with videoId + currentTime)
└── background.js        (optional, for badge/icon)
```

The anki-fox web UI communicates with the extension via `chrome.runtime.sendMessage` (externally_connectable). When the user presses ⌥⇧A:
1. Hammerspoon takes screenshot as usual
2. Flask server asks extension for current YouTube state via the web UI relay
3. Server fetches transcript chunk around that timestamp
4. LLM gets: screenshot + transcript context + timestamp → generates cards

### Installation
Extension files installed to `~/.anki-fox/extension/` by install.sh. One-time setup banner in web UI on first launch (when extension not detected):
```
YouTube capture available
1. Open chrome://extensions
2. Enable "Developer mode" (top right)
3. Click "Load unpacked"
4. Select ~/.anki-fox/extension
[Copy path]              [Skip] [I did it]
```
Once extension pings `/api/extension-hello`, banner disappears forever. Extension is a **pure enhancement** — everything works without it (just no timestamp enrichment).

### Fallback without extension
If no extension: user can still paste a YouTube URL, transcript is fetched, but timestamp is inferred by OCR from the screenshot's progress bar (best-effort) or omitted entirely. Cards still get transcript context from the full video.

## Backend Changes

### New dependencies
- `youtube-transcript-api` — fetch auto-generated transcripts
- No yt-dlp needed (transcripts only, no video download)

### New/modified endpoints
| Method | Path | Description |
|--------|------|-------------|
| POST | `/api/youtube/load` | Accepts URL, fetches title + transcript + chapters, returns metadata |
| GET | `/api/youtube/status` | Returns loaded video info (or null) |
| POST | `/api/extension-hello` | Extension registration ping |
| GET | `/api/extension/timestamp` | Web UI asks extension for current playback state |

### Modified: `models.generate_cards()`
Accept optional `transcript_context` and `timestamp` params. When present, the prompt includes:
```
TRANSCRIPT CONTEXT (around timestamp 3:42):
[Speaker]: "...the key insight about eigenvalues is that they tell you
the scaling factor along the eigenvector direction..."

Use this transcript alongside the screenshot to generate accurate cards.
Include the timestamp in tags for reference.
```

### Config changes
```json
{
  "deck_sources": {
    "3Blue1Brown": { "source": "video", "youtube_url": "..." },
    "Anatomy": { "source": "screen" }
  }
}
```

## Implementation Order

### Phase 1: Source selector UI (no new functionality)
- Add collapsible Source row with Screen/Multi/Video pills
- Screen is default, Multi wires up to existing stitch mode
- Video pill shows URL input (non-functional placeholder)
- Per-deck source memory in config
- Status banner text adapts

### Phase 2: Transcript backend
- `/api/youtube/load` endpoint — fetch transcript via youtube-transcript-api
- Transcript chunking (group by ~30s windows)
- Chapter detection from YouTube API
- Video metadata (title, duration, thumbnail)

### Phase 3: Chrome extension
- Extension files in `~/.anki-fox/extension/`
- content.js on youtube.com pages
- externally_connectable to localhost:5789
- Setup banner in web UI
- install.sh copies extension files

### Phase 4: Wiring it together
- Modify watchdog/capture flow: when source=video, query extension for timestamp
- Pass transcript chunk + screenshot to generate_cards
- Timestamp badge on generated cards (clickable YouTube link)
- Transcript preview card in UI showing loaded video info

### Phase 5: Polish
- Graceful fallback when extension not installed
- Offline queue support for video captures
- Tests for new endpoints and transcript parsing
- Update CONTEXT.md and README
