"""YouTube transcript fetching and chunking for anki-fox."""

import re
from dataclasses import dataclass, field

try:
    from youtube_transcript_api import YouTubeTranscriptApi
    HAS_TRANSCRIPT_API = True
except ImportError:
    HAS_TRANSCRIPT_API = False


@dataclass
class VideoMeta:
    video_id: str
    title: str
    duration: float = 0.0
    transcript: list[dict] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "video_id": self.video_id,
            "title": self.title,
            "duration": self.duration,
            "transcript_loaded": len(self.transcript) > 0,
            "segment_count": len(self.transcript),
        }


def extract_video_id(url: str) -> str | None:
    """Extract a YouTube video ID from various URL formats."""
    patterns = [
        r"(?:youtube\.com/watch\?v=|youtu\.be/|youtube\.com/embed/|youtube\.com/v/)([a-zA-Z0-9_-]{11})",
        r"^([a-zA-Z0-9_-]{11})$",
    ]
    for pat in patterns:
        m = re.search(pat, url.strip())
        if m:
            return m.group(1)
    return None


def fetch_transcript(video_id: str) -> list[dict]:
    """Fetch transcript segments for a video. Each segment: {text, start, duration}."""
    if not HAS_TRANSCRIPT_API:
        raise ImportError("youtube-transcript-api is not installed. Run: pip install youtube-transcript-api")
    ytt_api = YouTubeTranscriptApi()
    transcript = ytt_api.fetch(video_id)
    return [
        {"text": seg.text, "start": seg.start, "duration": seg.duration}
        for seg in transcript
    ]


def fetch_video_title(video_id: str) -> str:
    """Best-effort title fetch from YouTube's oembed endpoint."""
    try:
        import requests
        r = requests.get(
            f"https://www.youtube.com/oembed?url=https://www.youtube.com/watch?v={video_id}&format=json",
            timeout=5,
        )
        r.raise_for_status()
        return r.json().get("title", video_id)
    except Exception:
        return video_id


def get_transcript_chunk(transcript: list[dict], timestamp: float, window: float = 30.0) -> str:
    """Get transcript text around a timestamp (+/- window seconds)."""
    start = max(0.0, timestamp - window)
    end = timestamp + window
    segments = [
        seg for seg in transcript
        if seg["start"] + seg.get("duration", 0) >= start and seg["start"] <= end
    ]
    return " ".join(seg["text"] for seg in segments)


def format_timestamp(seconds: float) -> str:
    """Format seconds into H:MM:SS or M:SS."""
    total = int(seconds)
    h, remainder = divmod(total, 3600)
    m, s = divmod(remainder, 60)
    if h:
        return f"{h}:{m:02d}:{s:02d}"
    return f"{m}:{s:02d}"


def load_video(url: str) -> VideoMeta:
    """Load video metadata and transcript from a YouTube URL."""
    video_id = extract_video_id(url)
    if not video_id:
        raise ValueError(f"Could not extract video ID from: {url}")

    title = fetch_video_title(video_id)
    transcript = fetch_transcript(video_id)

    duration = 0.0
    if transcript:
        last = transcript[-1]
        duration = last["start"] + last.get("duration", 0)

    return VideoMeta(
        video_id=video_id,
        title=title,
        duration=duration,
        transcript=transcript,
    )
