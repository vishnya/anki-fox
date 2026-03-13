// anki-fox YouTube Timestamp Extension
// Responds to messages from anki-fox web UI with the current video state.

chrome.runtime.onMessageExternal.addListener((request, sender, sendResponse) => {
  if (request.type !== "anki-fox-get-timestamp") return;

  const video = document.querySelector("video");
  if (!video) {
    sendResponse({ error: "No video found on this page" });
    return;
  }

  // Extract video ID from URL
  const params = new URLSearchParams(window.location.search);
  const videoId = params.get("v") || "";

  sendResponse({
    videoId: videoId,
    currentTime: video.currentTime,
    duration: video.duration,
    paused: video.paused,
    title: document.title.replace(" - YouTube", ""),
  });
});
