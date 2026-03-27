// anki-fox YouTube Timestamp Extension
// Posts current playback position to the anki-fox server every 2 seconds.

const ANKI_FOX_URL = "http://localhost:5789/api/extension/timestamp";
const POLL_MS = 2000;

function postTimestamp() {
  const video = document.querySelector("video");
  if (!video) return;

  const params = new URLSearchParams(window.location.search);
  const videoId = params.get("v") || "";
  if (!videoId) return;

  fetch(ANKI_FOX_URL, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      videoId: videoId,
      currentTime: video.currentTime,
      duration: video.duration,
    }),
  }).catch(() => {}); // server may not be running
}

setInterval(postTimestamp, POLL_MS);
