"""Tests for YouTube transcript module, extension, and YouTube-related API endpoints."""

import json
import pytest
from unittest.mock import patch, MagicMock
from dataclasses import dataclass

import youtube
import flask_server
import models


# ── youtube.py unit tests ──────────────────────────────────────────────────────


class TestExtractVideoId:
    """Test video ID extraction from various URL formats."""

    def test_standard_watch_url(self):
        assert youtube.extract_video_id("https://www.youtube.com/watch?v=dQw4w9WgXcQ") == "dQw4w9WgXcQ"

    def test_short_url(self):
        assert youtube.extract_video_id("https://youtu.be/dQw4w9WgXcQ") == "dQw4w9WgXcQ"

    def test_embed_url(self):
        assert youtube.extract_video_id("https://youtube.com/embed/dQw4w9WgXcQ") == "dQw4w9WgXcQ"

    def test_watch_url_with_extra_params(self):
        assert youtube.extract_video_id("https://youtube.com/watch?v=dQw4w9WgXcQ&t=120") == "dQw4w9WgXcQ"

    def test_bare_video_id(self):
        assert youtube.extract_video_id("dQw4w9WgXcQ") == "dQw4w9WgXcQ"

    def test_invalid_url_returns_none(self):
        assert youtube.extract_video_id("not-a-url") is None

    def test_empty_string_returns_none(self):
        assert youtube.extract_video_id("") is None

    def test_whitespace_stripped(self):
        assert youtube.extract_video_id("  dQw4w9WgXcQ  ") == "dQw4w9WgXcQ"

    def test_v_url_format(self):
        assert youtube.extract_video_id("https://youtube.com/v/dQw4w9WgXcQ") == "dQw4w9WgXcQ"

    def test_http_url(self):
        assert youtube.extract_video_id("http://www.youtube.com/watch?v=dQw4w9WgXcQ") == "dQw4w9WgXcQ"

    def test_url_with_playlist_param(self):
        assert youtube.extract_video_id("https://www.youtube.com/watch?v=dQw4w9WgXcQ&list=PLrAXtmErZgOeiKm4sgNOknGvNjby9efdf") == "dQw4w9WgXcQ"

    def test_too_short_id_returns_none(self):
        assert youtube.extract_video_id("abc") is None

    def test_too_long_id_returns_none(self):
        assert youtube.extract_video_id("abcdefghijklm") is None


class TestGetTranscriptChunk:
    """Test transcript chunking around timestamps."""

    @pytest.fixture
    def sample_transcript(self):
        return [
            {"text": "Hello everyone", "start": 0.0, "duration": 3.0},
            {"text": "today we talk about math", "start": 3.0, "duration": 4.0},
            {"text": "first topic is algebra", "start": 10.0, "duration": 5.0},
            {"text": "equations are fun", "start": 15.0, "duration": 3.0},
            {"text": "now let us discuss calculus", "start": 30.0, "duration": 5.0},
            {"text": "derivatives measure change", "start": 60.0, "duration": 4.0},
            {"text": "integrals are the reverse", "start": 64.0, "duration": 4.0},
            {"text": "thanks for watching", "start": 120.0, "duration": 3.0},
        ]

    def test_chunk_at_beginning(self, sample_transcript):
        chunk = youtube.get_transcript_chunk(sample_transcript, 0.0, window=10.0)
        assert "Hello everyone" in chunk
        assert "today we talk about math" in chunk
        assert "first topic is algebra" in chunk

    def test_chunk_at_middle(self, sample_transcript):
        chunk = youtube.get_transcript_chunk(sample_transcript, 62.0, window=10.0)
        assert "derivatives measure change" in chunk
        assert "integrals are the reverse" in chunk
        assert "Hello everyone" not in chunk

    def test_chunk_at_end(self, sample_transcript):
        chunk = youtube.get_transcript_chunk(sample_transcript, 120.0, window=10.0)
        assert "thanks for watching" in chunk
        assert "Hello everyone" not in chunk

    def test_empty_transcript(self):
        chunk = youtube.get_transcript_chunk([], 10.0)
        assert chunk == ""

    def test_default_window_30s(self, sample_transcript):
        chunk = youtube.get_transcript_chunk(sample_transcript, 15.0)
        # Default 30s window: 0 to 45s
        assert "Hello everyone" in chunk
        assert "equations are fun" in chunk
        assert "now let us discuss calculus" in chunk

    def test_no_segments_in_range(self, sample_transcript):
        chunk = youtube.get_transcript_chunk(sample_transcript, 90.0, window=5.0)
        assert chunk == ""

    def test_wide_window_captures_all(self, sample_transcript):
        chunk = youtube.get_transcript_chunk(sample_transcript, 60.0, window=200.0)
        assert "Hello everyone" in chunk
        assert "thanks for watching" in chunk

    def test_segment_at_boundary_included(self, sample_transcript):
        # Segment starts at 30.0, window [29.0, 31.0] should include it
        chunk = youtube.get_transcript_chunk(sample_transcript, 30.0, window=1.0)
        assert "now let us discuss calculus" in chunk

    def test_custom_window_size(self, sample_transcript):
        chunk = youtube.get_transcript_chunk(sample_transcript, 60.0, window=5.0)
        assert "derivatives measure change" in chunk
        # 64s is in range [55, 65]
        assert "integrals are the reverse" in chunk


class TestFormatTimestamp:
    """Test timestamp formatting."""

    def test_zero(self):
        assert youtube.format_timestamp(0) == "0:00"

    def test_seconds(self):
        assert youtube.format_timestamp(45) == "0:45"

    def test_minutes(self):
        assert youtube.format_timestamp(125) == "2:05"

    def test_hours(self):
        assert youtube.format_timestamp(3661) == "1:01:01"

    def test_float_truncated(self):
        assert youtube.format_timestamp(90.7) == "1:30"

    def test_exactly_one_hour(self):
        assert youtube.format_timestamp(3600) == "1:00:00"

    def test_large_value(self):
        assert youtube.format_timestamp(7384) == "2:03:04"

    def test_single_digit_seconds(self):
        assert youtube.format_timestamp(5) == "0:05"

    def test_sixty_seconds(self):
        assert youtube.format_timestamp(60) == "1:00"


class TestVideoMeta:
    """Test VideoMeta dataclass."""

    def test_to_dict(self):
        meta = youtube.VideoMeta(
            video_id="abc123",
            title="Test Video",
            duration=120.0,
            transcript=[{"text": "hello", "start": 0, "duration": 3}],
        )
        d = meta.to_dict()
        assert d["video_id"] == "abc123"
        assert d["title"] == "Test Video"
        assert d["duration"] == 120.0
        assert d["transcript_loaded"] is True
        assert d["segment_count"] == 1

    def test_to_dict_no_transcript(self):
        meta = youtube.VideoMeta(video_id="abc123", title="Test")
        d = meta.to_dict()
        assert d["transcript_loaded"] is False
        assert d["segment_count"] == 0

    def test_to_dict_multiple_segments(self):
        meta = youtube.VideoMeta(
            video_id="x", title="T",
            transcript=[
                {"text": "a", "start": 0, "duration": 1},
                {"text": "b", "start": 1, "duration": 1},
                {"text": "c", "start": 2, "duration": 1},
            ],
        )
        assert meta.to_dict()["segment_count"] == 3

    def test_default_duration(self):
        meta = youtube.VideoMeta(video_id="x", title="T")
        assert meta.duration == 0.0

    def test_default_transcript(self):
        meta = youtube.VideoMeta(video_id="x", title="T")
        assert meta.transcript == []


class TestFetchTranscript:
    """Test transcript fetching (mocked)."""

    def test_fetch_transcript_success(self):
        @dataclass
        class MockSegment:
            text: str
            start: float
            duration: float

        mock_api = MagicMock()
        mock_api.fetch.return_value = [
            MockSegment(text="Hello", start=0.0, duration=3.0),
            MockSegment(text="World", start=3.0, duration=2.0),
        ]
        with patch("youtube.YouTubeTranscriptApi", return_value=mock_api):
            result = youtube.fetch_transcript("abc123")
        assert len(result) == 2
        assert result[0]["text"] == "Hello"
        assert result[0]["start"] == 0.0
        assert result[0]["duration"] == 3.0
        assert result[1]["start"] == 3.0

    def test_fetch_transcript_not_installed(self):
        with patch.object(youtube, "HAS_TRANSCRIPT_API", False):
            with pytest.raises(ImportError, match="youtube-transcript-api"):
                youtube.fetch_transcript("abc123")

    def test_fetch_transcript_empty(self):
        mock_api = MagicMock()
        mock_api.fetch.return_value = []
        with patch("youtube.YouTubeTranscriptApi", return_value=mock_api):
            result = youtube.fetch_transcript("abc123")
        assert result == []


class TestFetchVideoTitle:
    """Test title fetching (mocked)."""

    def test_title_success(self):
        mock_resp = MagicMock()
        mock_resp.json.return_value = {"title": "My Great Video"}
        mock_resp.raise_for_status = MagicMock()
        import requests as req_mod
        with patch.object(req_mod, "get", return_value=mock_resp):
            title = youtube.fetch_video_title("abc123")
        assert title == "My Great Video"

    def test_title_failure_returns_video_id(self):
        import requests as req_mod
        with patch.object(req_mod, "get", side_effect=Exception("network")):
            title = youtube.fetch_video_title("abc123")
        assert title == "abc123"

    def test_title_missing_key_returns_video_id(self):
        mock_resp = MagicMock()
        mock_resp.json.return_value = {}
        mock_resp.raise_for_status = MagicMock()
        import requests as req_mod
        with patch.object(req_mod, "get", return_value=mock_resp):
            title = youtube.fetch_video_title("abc123")
        assert title == "abc123"


class TestLoadVideo:
    """Test the full load_video flow."""

    def test_invalid_url_raises(self):
        with pytest.raises(ValueError, match="Could not extract video ID"):
            youtube.load_video("not-a-url")

    def test_load_video_success(self):
        @dataclass
        class MockSegment:
            text: str
            start: float
            duration: float

        mock_api = MagicMock()
        mock_api.fetch.return_value = [
            MockSegment(text="Hello", start=0.0, duration=3.0),
            MockSegment(text="World", start=3.0, duration=2.0),
        ]
        with patch("youtube.YouTubeTranscriptApi", return_value=mock_api), \
             patch("youtube.fetch_video_title", return_value="Test Title"):
            video = youtube.load_video("https://youtube.com/watch?v=dQw4w9WgXcQ")
        assert video.video_id == "dQw4w9WgXcQ"
        assert video.title == "Test Title"
        assert video.duration == 5.0
        assert len(video.transcript) == 2

    def test_load_video_empty_transcript(self):
        mock_api = MagicMock()
        mock_api.fetch.return_value = []
        with patch("youtube.YouTubeTranscriptApi", return_value=mock_api), \
             patch("youtube.fetch_video_title", return_value="No Subs"):
            video = youtube.load_video("https://youtube.com/watch?v=dQw4w9WgXcQ")
        assert video.duration == 0.0
        assert len(video.transcript) == 0

    def test_load_video_computes_duration_from_last_segment(self):
        @dataclass
        class MockSegment:
            text: str
            start: float
            duration: float

        mock_api = MagicMock()
        mock_api.fetch.return_value = [
            MockSegment(text="One", start=0.0, duration=10.0),
            MockSegment(text="Two", start=100.0, duration=5.0),
        ]
        with patch("youtube.YouTubeTranscriptApi", return_value=mock_api), \
             patch("youtube.fetch_video_title", return_value="T"):
            video = youtube.load_video("dQw4w9WgXcQ")
        assert video.duration == 105.0


# ── Flask API endpoint tests ──────────────────────────────────────────────────


class TestYouTubeLoadEndpoint:
    """Test POST /api/youtube/load."""

    def test_load_success(self, flask_client):
        @dataclass
        class MockSegment:
            text: str
            start: float
            duration: float

        mock_api = MagicMock()
        mock_api.fetch.return_value = [
            MockSegment(text="Hello", start=0.0, duration=3.0),
        ]
        with patch("youtube.YouTubeTranscriptApi", return_value=mock_api), \
             patch("youtube.fetch_video_title", return_value="My Video"):
            resp = flask_client.post("/api/youtube/load", json={"url": "https://youtube.com/watch?v=dQw4w9WgXcQ"})
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["video_id"] == "dQw4w9WgXcQ"
        assert data["title"] == "My Video"
        assert data["transcript_loaded"] is True
        assert data["segment_count"] == 1

    def test_load_no_url(self, flask_client):
        resp = flask_client.post("/api/youtube/load", json={"url": ""})
        assert resp.status_code == 400

    def test_load_missing_url_key(self, flask_client):
        resp = flask_client.post("/api/youtube/load", json={})
        assert resp.status_code == 400

    def test_load_invalid_url(self, flask_client):
        resp = flask_client.post("/api/youtube/load", json={"url": "not-a-url"})
        assert resp.status_code == 400
        assert "error" in resp.get_json()

    def test_load_transcript_failure(self, flask_client):
        with patch("youtube.load_video", side_effect=Exception("No transcript")):
            resp = flask_client.post("/api/youtube/load", json={"url": "https://youtube.com/watch?v=abc12345678"})
        assert resp.status_code == 400
        assert "error" in resp.get_json()

    def test_load_replaces_previous_video(self, flask_client):
        """Loading a new video replaces the previous one."""
        @dataclass
        class MockSegment:
            text: str
            start: float
            duration: float

        mock_api = MagicMock()
        mock_api.fetch.return_value = [MockSegment(text="First", start=0.0, duration=1.0)]
        with patch("youtube.YouTubeTranscriptApi", return_value=mock_api), \
             patch("youtube.fetch_video_title", return_value="Video 1"):
            flask_client.post("/api/youtube/load", json={"url": "https://youtube.com/watch?v=aaaaaaaaaaa"})

        mock_api.fetch.return_value = [MockSegment(text="Second", start=0.0, duration=1.0)]
        with patch("youtube.YouTubeTranscriptApi", return_value=mock_api), \
             patch("youtube.fetch_video_title", return_value="Video 2"):
            flask_client.post("/api/youtube/load", json={"url": "https://youtube.com/watch?v=bbbbbbbbbbb"})

        status = flask_client.get("/api/youtube/status").get_json()
        assert status["video_id"] == "bbbbbbbbbbb"
        assert status["title"] == "Video 2"


class TestYouTubeStatusEndpoint:
    """Test GET /api/youtube/status."""

    def test_status_no_video(self, flask_client):
        flask_server._loaded_video = None
        resp = flask_client.get("/api/youtube/status")
        assert resp.status_code == 200
        assert resp.get_json() is None

    def test_status_with_video(self, flask_client):
        flask_server._loaded_video = youtube.VideoMeta(
            video_id="abc123", title="Test", duration=60.0,
            transcript=[{"text": "hi", "start": 0, "duration": 2}],
        )
        resp = flask_client.get("/api/youtube/status")
        data = resp.get_json()
        assert data["video_id"] == "abc123"
        assert data["transcript_loaded"] is True
        assert data["duration"] == 60.0

    def test_status_returns_all_fields(self, flask_client):
        flask_server._loaded_video = youtube.VideoMeta(
            video_id="xyz789", title="Full Test", duration=300.0,
            transcript=[
                {"text": "a", "start": 0, "duration": 1},
                {"text": "b", "start": 1, "duration": 1},
            ],
        )
        data = flask_client.get("/api/youtube/status").get_json()
        assert set(data.keys()) == {"video_id", "title", "duration", "transcript_loaded", "segment_count"}


class TestYouTubeClearEndpoint:
    """Test POST /api/youtube/clear."""

    def test_clear(self, flask_client):
        flask_server._loaded_video = youtube.VideoMeta(video_id="abc", title="T")
        resp = flask_client.post("/api/youtube/clear")
        assert resp.status_code == 200
        assert flask_server._loaded_video is None

    def test_clear_when_already_none(self, flask_client):
        flask_server._loaded_video = None
        resp = flask_client.post("/api/youtube/clear")
        assert resp.status_code == 200
        assert flask_server._loaded_video is None

    def test_clear_then_status_returns_none(self, flask_client):
        flask_server._loaded_video = youtube.VideoMeta(video_id="abc", title="T")
        flask_client.post("/api/youtube/clear")
        data = flask_client.get("/api/youtube/status").get_json()
        assert data is None


# ── Extension endpoint tests ─────────────────────────────────────────────────


class TestExtensionHello:
    """Test POST /api/extension/hello."""

    def test_hello_marks_connected(self, flask_client):
        flask_server._extension_connected = False
        resp = flask_client.post("/api/extension/hello")
        assert resp.status_code == 200
        assert resp.get_json()["ok"] is True
        assert flask_server._extension_connected is True

    def test_hello_idempotent(self, flask_client):
        flask_server._extension_connected = True
        resp = flask_client.post("/api/extension/hello")
        assert resp.status_code == 200
        assert flask_server._extension_connected is True


class TestExtensionStatus:
    """Test GET /api/extension/status."""

    def test_status_not_connected(self, flask_client):
        flask_server._extension_connected = False
        resp = flask_client.get("/api/extension/status")
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["connected"] is False
        assert "path" in data

    def test_status_connected(self, flask_client):
        flask_server._extension_connected = True
        resp = flask_client.get("/api/extension/status")
        data = resp.get_json()
        assert data["connected"] is True

    def test_status_returns_extension_path(self, flask_client):
        resp = flask_client.get("/api/extension/status")
        data = resp.get_json()
        assert "extension" in data["path"]


# ── Config deck_sources tests ─────────────────────────────────────────────────


class TestDeckSources:
    """Test deck_sources config persistence."""

    def test_save_deck_sources(self, flask_client):
        flask_client.post("/api/config", json={
            "deck_sources": {"Bio": {"source": "video", "youtube_url": "https://youtube.com/watch?v=abc123"}},
        })
        conf = flask_client.get("/api/config").get_json()
        assert conf["deck_sources"]["Bio"]["source"] == "video"
        assert conf["deck_sources"]["Bio"]["youtube_url"] == "https://youtube.com/watch?v=abc123"

    def test_empty_deck_sources_default(self, flask_client):
        conf = flask_client.get("/api/config").get_json()
        assert conf["deck_sources"] == {}

    def test_switch_source_back_to_screen(self, flask_client):
        flask_client.post("/api/config", json={
            "deck_sources": {"Bio": {"source": "video"}},
        })
        flask_client.post("/api/config", json={
            "deck_sources": {},
        })
        conf = flask_client.get("/api/config").get_json()
        assert conf["deck_sources"] == {}

    def test_multiple_decks_different_sources(self, flask_client):
        flask_client.post("/api/config", json={
            "deck_sources": {
                "Bio": {"source": "video", "youtube_url": "https://youtube.com/watch?v=aaa"},
                "Math": {"source": "screen"},
            },
        })
        conf = flask_client.get("/api/config").get_json()
        assert conf["deck_sources"]["Bio"]["source"] == "video"
        assert conf["deck_sources"]["Math"]["source"] == "screen"

    def test_deck_sources_preserved_on_other_config_update(self, flask_client):
        flask_client.post("/api/config", json={
            "deck_sources": {"Bio": {"source": "video"}},
        })
        flask_client.post("/api/config", json={
            "deck": "Chemistry",
        })
        conf = flask_client.get("/api/config").get_json()
        assert conf["deck_sources"]["Bio"]["source"] == "video"


# ── models.py transcript context tests ────────────────────────────────────────


class TestBuildPromptWithTranscript:
    """Test _build_prompt with transcript context injection."""

    def test_no_transcript_returns_base(self):
        prompt = models._build_prompt({"custom_prompt": ""})
        assert "TRANSCRIPT CONTEXT" not in prompt

    def test_transcript_appears_before_rules(self):
        prompt = models._build_prompt({
            "custom_prompt": "",
            "transcript_context": "mitochondria are the powerhouse of the cell",
            "timestamp": 42.0,
        })
        assert "TRANSCRIPT CONTEXT" in prompt
        rules_pos = prompt.index("RULES:")
        transcript_pos = prompt.index("TRANSCRIPT CONTEXT")
        assert transcript_pos < rules_pos

    def test_transcript_includes_timestamp(self):
        prompt = models._build_prompt({
            "custom_prompt": "",
            "transcript_context": "hello world",
            "timestamp": 125.0,
        })
        assert "2:05" in prompt

    def test_transcript_includes_video_title(self):
        prompt = models._build_prompt({
            "custom_prompt": "",
            "transcript_context": "hello world",
            "video_title": "My Great Lecture",
        })
        assert "My Great Lecture" in prompt

    def test_transcript_with_custom_prompt_both_present(self):
        prompt = models._build_prompt({
            "custom_prompt": "Focus on biology",
            "transcript_context": "cells divide by mitosis",
            "timestamp": 60.0,
        })
        assert "TRANSCRIPT CONTEXT" in prompt
        assert "Focus on biology" in prompt
        assert "cells divide by mitosis" in prompt

    def test_transcript_guidance_text(self):
        prompt = models._build_prompt({
            "custom_prompt": "",
            "transcript_context": "some text",
        })
        assert "Use this transcript alongside the screenshot" in prompt

    def test_empty_transcript_ignored(self):
        prompt = models._build_prompt({
            "custom_prompt": "",
            "transcript_context": "   ",
        })
        assert "TRANSCRIPT CONTEXT" not in prompt

    def test_transcript_with_deck_context(self):
        prompt = models._build_prompt({
            "custom_prompt": "",
            "transcript_context": "neural networks learn via backpropagation",
            "timestamp": 300.0,
            "deck_context": [
                {"front": "What is a neuron?", "back": "A computation unit", "tags": ["ml"]},
            ],
        })
        assert "TRANSCRIPT CONTEXT" in prompt
        assert "EXISTING CARDS" in prompt
        assert "neural networks" in prompt

    def test_transcript_no_timestamp(self):
        """Transcript without timestamp should still work."""
        prompt = models._build_prompt({
            "custom_prompt": "",
            "transcript_context": "some lecture content here",
        })
        assert "TRANSCRIPT CONTEXT" in prompt
        assert "some lecture content here" in prompt
        # No timestamp should mean no "(around timestamp ...)" in header
        assert "around timestamp" not in prompt

    def test_transcript_with_zero_timestamp(self):
        prompt = models._build_prompt({
            "custom_prompt": "",
            "transcript_context": "intro content",
            "timestamp": 0.0,
        })
        assert "around timestamp 0:00" in prompt

    def test_transcript_ordering_with_all_contexts(self):
        """Verify ordering: deck context, transcript, custom prompt all before RULES."""
        prompt = models._build_prompt({
            "custom_prompt": "Focus on details",
            "transcript_context": "lecture audio text",
            "timestamp": 10.0,
            "deck_context": [
                {"front": "Q1?", "back": "A1", "tags": []},
            ],
        })
        rules_pos = prompt.index("RULES:")
        transcript_pos = prompt.index("TRANSCRIPT CONTEXT")
        deck_pos = prompt.index("EXISTING CARDS")
        custom_pos = prompt.index("Focus on details")
        # All should be before RULES
        assert deck_pos < rules_pos
        assert transcript_pos < rules_pos
        assert custom_pos < rules_pos


# ── Screenshot handler with video source tests ────────────────────────────────


class TestScreenshotHandlerVideoSource:
    """Test ScreenshotHandler.on_created with video source mode."""

    def test_video_source_adds_transcript_context(self, flask_client, tiny_png, mock_ankiconnect):
        """When source=video and video loaded, transcript context is passed to generate_cards."""
        import config as cfg

        # Set up config with video source
        conf = cfg.load()
        conf["session_active"] = True
        conf["deck"] = "TestDeck"
        conf["deck_sources"] = {"TestDeck": {"source": "video"}}
        conf["api_keys"] = {"anthropic": "sk-test"}
        cfg.save(conf)

        # Load a video — transcript segments near end so they're in range of duration fallback
        flask_server._loaded_video = youtube.VideoMeta(
            video_id="test123",
            title="Test Lecture",
            duration=120.0,
            transcript=[
                {"text": "this is about biology", "start": 95.0, "duration": 5.0},
                {"text": "cells are the building blocks of life", "start": 100.0, "duration": 5.0},
            ],
        )

        cards = [{"front": "What are cells?", "back": "Building blocks of life", "tags": ["bio"], "is_image_card": False}]

        with patch("models.generate_cards", return_value=cards) as mock_gen, \
             patch("time.sleep"):
            handler = flask_server.ScreenshotHandler()
            event = MagicMock()
            event.is_directory = False
            event.src_path = tiny_png
            handler.on_created(event)

            # Verify generate_cards was called with transcript context
            assert mock_gen.called
            call_conf = mock_gen.call_args[0][1]
            assert "transcript_context" in call_conf
            assert "biology" in call_conf["transcript_context"]
            assert call_conf["video_id"] == "test123"
            assert call_conf["video_title"] == "Test Lecture"
            assert call_conf["timestamp"] == 120.0  # fallback to duration

    def test_screen_source_no_transcript(self, flask_client, tiny_png, mock_ankiconnect):
        """When source=screen, no transcript context is passed."""
        import config as cfg

        conf = cfg.load()
        conf["session_active"] = True
        conf["deck"] = "TestDeck"
        conf["deck_sources"] = {}  # screen is default
        conf["api_keys"] = {"anthropic": "sk-test"}
        cfg.save(conf)

        cards = [{"front": "Q?", "back": "A", "tags": [], "is_image_card": False}]

        with patch("models.generate_cards", return_value=cards) as mock_gen, \
             patch("time.sleep"):
            handler = flask_server.ScreenshotHandler()
            event = MagicMock()
            event.is_directory = False
            event.src_path = tiny_png
            handler.on_created(event)

            assert mock_gen.called
            call_conf = mock_gen.call_args[0][1]
            assert "transcript_context" not in call_conf

    def test_video_source_no_video_loaded(self, flask_client, tiny_png, mock_ankiconnect):
        """When source=video but no video loaded, no transcript context."""
        import config as cfg

        conf = cfg.load()
        conf["session_active"] = True
        conf["deck"] = "TestDeck"
        conf["deck_sources"] = {"TestDeck": {"source": "video"}}
        conf["api_keys"] = {"anthropic": "sk-test"}
        cfg.save(conf)

        flask_server._loaded_video = None

        cards = [{"front": "Q?", "back": "A", "tags": [], "is_image_card": False}]

        with patch("models.generate_cards", return_value=cards) as mock_gen, \
             patch("time.sleep"):
            handler = flask_server.ScreenshotHandler()
            event = MagicMock()
            event.is_directory = False
            event.src_path = tiny_png
            handler.on_created(event)

            assert mock_gen.called
            call_conf = mock_gen.call_args[0][1]
            assert "transcript_context" not in call_conf

    def test_video_source_empty_transcript(self, flask_client, tiny_png, mock_ankiconnect):
        """When source=video but transcript is empty, no transcript context."""
        import config as cfg

        conf = cfg.load()
        conf["session_active"] = True
        conf["deck"] = "TestDeck"
        conf["deck_sources"] = {"TestDeck": {"source": "video"}}
        conf["api_keys"] = {"anthropic": "sk-test"}
        cfg.save(conf)

        flask_server._loaded_video = youtube.VideoMeta(
            video_id="test123", title="Empty", duration=0, transcript=[],
        )

        cards = [{"front": "Q?", "back": "A", "tags": [], "is_image_card": False}]

        with patch("models.generate_cards", return_value=cards) as mock_gen, \
             patch("time.sleep"):
            handler = flask_server.ScreenshotHandler()
            event = MagicMock()
            event.is_directory = False
            event.src_path = tiny_png
            handler.on_created(event)

            assert mock_gen.called
            call_conf = mock_gen.call_args[0][1]
            assert "transcript_context" not in call_conf

    def test_video_source_adds_timestamp_tag(self, flask_client, tiny_png, mock_ankiconnect):
        """Cards from video source get yt-timestamp tags."""
        import config as cfg

        conf = cfg.load()
        conf["session_active"] = True
        conf["deck"] = "TestDeck"
        conf["deck_sources"] = {"TestDeck": {"source": "video"}}
        conf["api_keys"] = {"anthropic": "sk-test"}
        cfg.save(conf)

        flask_server._loaded_video = youtube.VideoMeta(
            video_id="test123", title="T", duration=65.0,
            transcript=[{"text": "content here", "start": 40.0, "duration": 5.0}],
        )

        cards = [{"front": "Q?", "back": "A", "tags": ["topic"], "is_image_card": False}]

        with patch("models.generate_cards", return_value=cards), \
             patch("time.sleep"):
            handler = flask_server.ScreenshotHandler()
            event = MagicMock()
            event.is_directory = False
            event.src_path = tiny_png
            handler.on_created(event)

            # Check the cards had a yt tag added
            assert any(t.startswith("yt-") for t in cards[0]["tags"])

    def test_video_source_stores_yt_timestamp_in_recent(self, flask_client, tiny_png, mock_ankiconnect):
        """Recent cards from video source include yt_timestamp and video_id."""
        import config as cfg

        conf = cfg.load()
        conf["session_active"] = True
        conf["deck"] = "TestDeck"
        conf["deck_sources"] = {"TestDeck": {"source": "video"}}
        conf["api_keys"] = {"anthropic": "sk-test"}
        cfg.save(conf)

        flask_server._loaded_video = youtube.VideoMeta(
            video_id="vid456", title="T", duration=100.0,
            transcript=[{"text": "content", "start": 75.0, "duration": 5.0}],
        )

        cards = [{"front": "Q?", "back": "A", "tags": [], "is_image_card": False}]

        with patch("models.generate_cards", return_value=cards), \
             patch("time.sleep"):
            handler = flask_server.ScreenshotHandler()
            event = MagicMock()
            event.is_directory = False
            event.src_path = tiny_png
            handler.on_created(event)

        assert len(flask_server._recent_cards) > 0
        card = flask_server._recent_cards[0]
        assert "yt_timestamp" in card
        assert card["video_id"] == "vid456"


# ── HTML UI element tests ─────────────────────────────────────────────────────


class TestSourceSelectorHTML:
    """Verify the HTML page contains source selector elements."""

    def test_contains_status_banner(self, flask_client):
        html = flask_client.get("/").data.decode()
        assert 'id="status-banner"' in html
        assert 'id="status-text"' in html

    def test_contains_youtube_url_input(self, flask_client):
        html = flask_client.get("/").data.decode()
        assert 'id="youtube-url"' in html
        assert 'id="btn-load-video"' in html

    def test_contains_video_info(self, flask_client):
        html = flask_client.get("/").data.decode()
        assert 'id="video-info"' in html
        assert 'id="video-title"' in html

    def test_video_config_hidden_by_default(self, flask_client):
        html = flask_client.get("/").data.decode()
        assert 'class="video-config-panel hidden"' in html

    def test_contains_extension_banner(self, flask_client):
        html = flask_client.get("/").data.decode()
        assert 'id="extension-banner"' in html
        assert "Chrome extension needed" in html

    def test_extension_banner_hidden_by_default(self, flask_client):
        html = flask_client.get("/").data.decode()
        assert 'class="extension-banner hidden"' in html

    def test_contains_extension_setup_steps(self, flask_client):
        html = flask_client.get("/").data.decode()
        assert "chrome://extensions" in html
        assert "Developer mode" in html
        assert "Load unpacked" in html

    def test_contains_extension_action_buttons(self, flask_client):
        html = flask_client.get("/").data.decode()
        assert 'id="btn-copy-ext-path"' in html
        assert 'id="btn-ext-skip"' in html
        assert 'id="btn-ext-done"' in html

    def test_extension_explains_why_needed(self, flask_client):
        html = flask_client.get("/").data.decode()
        assert "exact playback position" in html or "exact timestamps" in html


# ── Extension file tests ─────────────────────────────────────────────────────


class TestExtensionFiles:
    """Verify the Chrome extension files exist and are valid."""

    def test_manifest_exists(self):
        from pathlib import Path
        manifest = Path(__file__).parent.parent / "extension" / "manifest.json"
        assert manifest.exists()

    def test_manifest_valid_json(self):
        from pathlib import Path
        manifest = Path(__file__).parent.parent / "extension" / "manifest.json"
        data = json.loads(manifest.read_text())
        assert data["manifest_version"] == 3
        assert "anki-fox" in data["name"].lower()

    def test_manifest_has_content_scripts(self):
        from pathlib import Path
        manifest = Path(__file__).parent.parent / "extension" / "manifest.json"
        data = json.loads(manifest.read_text())
        assert len(data["content_scripts"]) > 0
        assert "*://*.youtube.com/*" in data["content_scripts"][0]["matches"]

    def test_manifest_externally_connectable(self):
        from pathlib import Path
        manifest = Path(__file__).parent.parent / "extension" / "manifest.json"
        data = json.loads(manifest.read_text())
        origins = data["externally_connectable"]["origins"]
        assert any("localhost:5789" in o for o in origins)

    def test_content_js_exists(self):
        from pathlib import Path
        content = Path(__file__).parent.parent / "extension" / "content.js"
        assert content.exists()

    def test_content_js_handles_messages(self):
        from pathlib import Path
        content = Path(__file__).parent.parent / "extension" / "content.js"
        js = content.read_text()
        assert "onMessageExternal" in js
        assert "anki-fox-get-timestamp" in js
        assert "currentTime" in js


# ── Integration: Load → Status → Clear lifecycle ─────────────────────────────


class TestYouTubeLifecycle:
    """Integration test for the full YouTube load/status/clear lifecycle."""

    def test_load_status_clear_lifecycle(self, flask_client):
        @dataclass
        class MockSegment:
            text: str
            start: float
            duration: float

        # Initially no video
        assert flask_client.get("/api/youtube/status").get_json() is None

        # Load a video
        mock_api = MagicMock()
        mock_api.fetch.return_value = [
            MockSegment(text="Hello", start=0.0, duration=3.0),
            MockSegment(text="World", start=3.0, duration=2.0),
        ]
        with patch("youtube.YouTubeTranscriptApi", return_value=mock_api), \
             patch("youtube.fetch_video_title", return_value="Lifecycle Test"):
            resp = flask_client.post("/api/youtube/load", json={"url": "https://youtube.com/watch?v=dQw4w9WgXcQ"})
        assert resp.status_code == 200

        # Status should show loaded video
        status = flask_client.get("/api/youtube/status").get_json()
        assert status["video_id"] == "dQw4w9WgXcQ"
        assert status["title"] == "Lifecycle Test"
        assert status["transcript_loaded"] is True
        assert status["segment_count"] == 2

        # Clear
        flask_client.post("/api/youtube/clear")
        assert flask_client.get("/api/youtube/status").get_json() is None

    def test_extension_hello_then_status(self, flask_client):
        flask_server._extension_connected = False
        assert flask_client.get("/api/extension/status").get_json()["connected"] is False
        flask_client.post("/api/extension/hello")
        assert flask_client.get("/api/extension/status").get_json()["connected"] is True


# ── Source cycling tests ──────────────────────────────────────────────────────


class TestSourceCycle:
    """Test POST /api/source/cycle."""

    def test_cycle_screen_to_multi(self, flask_client):
        flask_client.post("/api/config", json={"deck": "Bio", "deck_sources": {}})
        resp = flask_client.post("/api/source/cycle")
        assert resp.status_code == 200
        assert resp.get_json()["source"] == "multi"

    def test_cycle_multi_to_video(self, flask_client):
        flask_client.post("/api/config", json={
            "deck": "Bio",
            "deck_sources": {"Bio": {"source": "multi"}},
        })
        resp = flask_client.post("/api/source/cycle")
        assert resp.get_json()["source"] == "video"

    def test_cycle_video_to_screen(self, flask_client):
        flask_client.post("/api/config", json={
            "deck": "Bio",
            "deck_sources": {"Bio": {"source": "video"}},
        })
        resp = flask_client.post("/api/source/cycle")
        assert resp.get_json()["source"] == "screen"

    def test_cycle_full_loop(self, flask_client):
        flask_client.post("/api/config", json={"deck": "Bio", "deck_sources": {}})
        sources = []
        for _ in range(4):
            resp = flask_client.post("/api/source/cycle")
            sources.append(resp.get_json()["source"])
        assert sources == ["multi", "video", "screen", "multi"]

    def test_cycle_no_deck_returns_error(self, flask_client):
        flask_client.post("/api/config", json={"deck": ""})
        resp = flask_client.post("/api/source/cycle")
        assert resp.status_code == 400

    def test_cycle_persists_to_config(self, flask_client):
        flask_client.post("/api/config", json={"deck": "Bio", "deck_sources": {}})
        flask_client.post("/api/source/cycle")
        conf = flask_client.get("/api/config").get_json()
        assert conf["deck_sources"]["Bio"]["source"] == "multi"

    def test_cycle_back_to_screen_removes_from_deck_sources(self, flask_client):
        flask_client.post("/api/config", json={
            "deck": "Bio",
            "deck_sources": {"Bio": {"source": "video"}},
        })
        flask_client.post("/api/source/cycle")  # video → screen
        conf = flask_client.get("/api/config").get_json()
        assert "Bio" not in conf["deck_sources"]


class TestSessionSourceField:
    """Test that /api/session returns the current source."""

    def test_default_source_is_screen(self, flask_client):
        flask_client.post("/api/config", json={"deck": "Bio"})
        resp = flask_client.get("/api/session")
        assert resp.get_json()["source"] == "screen"

    def test_source_reflects_config(self, flask_client):
        flask_client.post("/api/config", json={
            "deck": "Bio",
            "deck_sources": {"Bio": {"source": "multi"}},
        })
        resp = flask_client.get("/api/session")
        assert resp.get_json()["source"] == "multi"

    def test_source_reflects_video(self, flask_client):
        flask_client.post("/api/config", json={
            "deck": "Bio",
            "deck_sources": {"Bio": {"source": "video"}},
        })
        resp = flask_client.get("/api/session")
        assert resp.get_json()["source"] == "video"


class TestMultiFinishEndpoint:
    """Test POST /api/multi/finish."""

    @pytest.fixture(autouse=True)
    def _allow_tmp_path(self, tmp_path, monkeypatch):
        monkeypatch.setattr(flask_server, "SCREENSHOTS_DIR", tmp_path)

    def test_stitch_two_images(self, flask_client, tmp_path):
        from PIL import Image
        from pathlib import Path
        paths = []
        for i in range(2):
            p = str(tmp_path / f".multi_{i}.png")
            Image.new("RGB", (100, 50 + i * 10), color=(255, 0, 0)).save(p)
            paths.append(p)

        resp = flask_client.post("/api/multi/finish", json={"paths": paths})
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["ok"] is True
        assert Path(data["path"]).exists()
        # Verify stitched dimensions
        result = Image.open(data["path"])
        assert result.width == 100
        assert result.height == 110  # 50 + 60
        result.close()
        # Verify temp files cleaned up
        for p in paths:
            assert not Path(p).exists()

    def test_stitch_single_image(self, flask_client, tmp_path):
        from PIL import Image
        p = str(tmp_path / ".multi_0.png")
        Image.new("RGB", (200, 100)).save(p)
        resp = flask_client.post("/api/multi/finish", json={"paths": [p]})
        assert resp.status_code == 200
        assert resp.get_json()["ok"] is True

    def test_stitch_no_paths_returns_error(self, flask_client):
        resp = flask_client.post("/api/multi/finish", json={"paths": []})
        assert resp.status_code == 400

    def test_stitch_missing_file_returns_error(self, flask_client):
        resp = flask_client.post("/api/multi/finish", json={"paths": ["/nonexistent.png"]})
        assert resp.status_code == 400

    def test_stitch_different_widths(self, flask_client, tmp_path):
        """Images with different widths: result width should be max."""
        from PIL import Image
        p1 = str(tmp_path / ".multi_0.png")
        p2 = str(tmp_path / ".multi_1.png")
        Image.new("RGB", (100, 50)).save(p1)
        Image.new("RGB", (200, 50)).save(p2)
        resp = flask_client.post("/api/multi/finish", json={"paths": [p1, p2]})
        result = Image.open(resp.get_json()["path"])
        assert result.width == 200
        assert result.height == 100
        result.close()


class TestWatchdogSkipsDotFiles:
    """Test that the watchdog handler skips dot-prefixed files."""

    def test_dot_prefixed_file_ignored(self, flask_client, tmp_path, mock_ankiconnect):
        """Dot-prefixed PNG files should not be processed."""
        import config as cfg_mod
        from PIL import Image
        from unittest.mock import MagicMock

        conf = cfg_mod.load()
        conf["session_active"] = True
        conf["deck"] = "TestDeck"
        conf["api_keys"] = {"anthropic": "sk-test"}
        cfg_mod.save(conf)

        # Create a dot-prefixed file
        dot_path = str(tmp_path / ".multi_0.png")
        Image.new("RGB", (100, 100)).save(dot_path)

        handler = flask_server.ScreenshotHandler()
        event = MagicMock()
        event.is_directory = False
        event.src_path = dot_path

        with patch("models.generate_cards") as mock_gen:
            handler.on_created(event)
            mock_gen.assert_not_called()


class TestSourceCycleEndpointMulti:
    """Verify multi source can be set via the cycle endpoint."""

    def test_cycle_to_multi(self, flask_client):
        flask_client.post("/api/config", json={"deck": "Bio", "deck_sources": {}})
        resp = flask_client.post("/api/source/cycle")
        assert resp.get_json()["source"] == "multi"
