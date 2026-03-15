require("hs.ipc")

local SERVER   = "http://localhost:5789"
local INCOMING = os.getenv("HOME") .. "/AnkiFox/incoming"
os.execute("mkdir -p " .. INCOMING)

local function getSession()
  local code, body = hs.http.get(SERVER .. "/api/session", {})
  if code == 200 then
    local ok, r = pcall(hs.json.decode, body)
    return ok and r or nil
  end
  return nil
end

-- ── Fox overlay indicator ───────────────────────────────────────────────────
local foxCanvas = nil

function showFox()
  if foxCanvas then foxCanvas:delete(); foxCanvas = nil end
  local screen = hs.screen.mainScreen():frame()
  foxCanvas = hs.canvas.new({ x = screen.x + 8, y = screen.y + 8, w = 44, h = 44 })
  foxCanvas:appendElements({
    type = "text",
    text = hs.styledtext.new("\u{1F98A}", { font = { size = 28 } }),
    frame = { x = "0%", y = "0%", w = "100%", h = "100%" },
  })
  foxCanvas:level(hs.canvas.windowLevels.overlay):show()
  hs.timer.doAfter(1, function()
    if foxCanvas then foxCanvas:delete(); foxCanvas = nil end
  end)
end

-- ── Brief text overlay ──────────────────────────────────────────────────────
local labelCanvas = nil

local function showLabel(text, duration)
  if labelCanvas then labelCanvas:delete(); labelCanvas = nil end
  local screen = hs.screen.mainScreen():frame()
  local width = 420
  labelCanvas = hs.canvas.new({
    x = screen.x + (screen.w - width) / 2,
    y = screen.y + 8,
    w = width, h = 28,
  })
  labelCanvas:appendElements({
    type = "rectangle",
    fillColor = { red = 0.15, green = 0.15, blue = 0.15, alpha = 0.9 },
    roundedRectRadii = { xRadius = 6, yRadius = 6 },
  }, {
    type = "text",
    text = hs.styledtext.new(text, {
      font = { name = ".AppleSystemUIFont", size = 13 },
      color = { red = 0.9, green = 0.9, blue = 0.9 },
      paragraphStyle = { alignment = "center" },
    }),
    frame = { x = "0%", y = "8%", w = "100%", h = "100%" },
  })
  labelCanvas:level(hs.canvas.windowLevels.overlay):show()
  hs.timer.doAfter(duration or 1.5, function()
    if labelCanvas then labelCanvas:delete(); labelCanvas = nil end
  end)
end

-- ── Single screenshot ───────────────────────────────────────────────────────
local function takeScreenshot()
  local ts   = os.date("%Y%m%d_%H%M%S")
  local path = INCOMING .. "/screenshot_" .. ts .. ".png"
  hs.task.new("/usr/sbin/screencapture", function(exitCode, _, _)
    hs.timer.doAfter(0.3, function()
      if hs.fs.attributes(path) then showFox() end
    end)
  end, {"-i", path}):start()
end

-- ── Multi-screenshot mode ───────────────────────────────────────────────────
local multiMode = false
local multiPaths = {}
local multiTimeout = nil
local multiEscTap = nil
local multiEnterTap = nil
local MULTI_TIMEOUT_SECS = 30

local function exitMultiMode()
  multiMode = false
  multiPaths = {}
  if labelCanvas then labelCanvas:delete(); labelCanvas = nil end
  if multiTimeout then multiTimeout:stop(); multiTimeout = nil end
  if multiEscTap then multiEscTap:delete(); multiEscTap = nil end
  if multiEnterTap then multiEnterTap:delete(); multiEnterTap = nil end
end

local function cancelMultiMode()
  -- Clean up temp files
  for _, p in ipairs(multiPaths) do
    os.remove(p)
  end
  exitMultiMode()
  showLabel("Multi cancelled")
end

local function finishMultiMode()
  local paths = {}
  for _, p in ipairs(multiPaths) do
    table.insert(paths, p)
  end
  exitMultiMode()

  if #paths == 0 then
    showLabel("No screenshots taken")
    return
  end

  if #paths == 1 then
    -- Just move the single screenshot to incoming
    local ts = os.date("%Y%m%d_%H%M%S")
    local dest = INCOMING .. "/screenshot_" .. ts .. ".png"
    os.rename(paths[1], dest)
    showFox()
    return
  end

  -- Stitch via server endpoint
  local body = hs.json.encode({ paths = paths })
  hs.http.asyncPost(SERVER .. "/api/multi/finish", body,
    { ["Content-Type"] = "application/json" },
    function(code, respBody, _)
      if code == 200 then
        showFox()
      else
        showLabel("Stitch failed")
        print("Multi stitch error: " .. (respBody or ""))
      end
    end)
end

local function takeMultiScreenshot()
  local ts   = os.date("%Y%m%d_%H%M%S") .. "_" .. #multiPaths
  local path = INCOMING .. "/.multi_" .. ts .. ".png"
  hs.task.new("/usr/sbin/screencapture", function(exitCode, _, _)
    hs.timer.doAfter(0.3, function()
      if hs.fs.attributes(path) then
        table.insert(multiPaths, path)
        showLabel(#multiPaths .. " captured — ⌥⇧A for more, Enter to finish, Esc to cancel", MULTI_TIMEOUT_SECS)
        -- Reset timeout on each screenshot
        if multiTimeout then multiTimeout:stop() end
        multiTimeout = hs.timer.doAfter(MULTI_TIMEOUT_SECS, cancelMultiMode)
      end
    end)
  end, {"-i", path}):start()
end

local function enterMultiMode()
  multiMode = true
  multiPaths = {}
  showLabel("Multi: select a region — Enter to finish, Esc to cancel", MULTI_TIMEOUT_SECS)

  -- Timeout: cancel if no activity
  multiTimeout = hs.timer.doAfter(MULTI_TIMEOUT_SECS, cancelMultiMode)

  -- Escape to cancel
  multiEscTap = hs.hotkey.new({}, "escape", cancelMultiMode)
  multiEscTap:enable()

  -- Enter to finish
  multiEnterTap = hs.hotkey.new({}, "return", finishMultiMode)
  multiEnterTap:enable()

  -- Take the first screenshot immediately
  takeMultiScreenshot()
end

-- ── Hotkeys ─────────────────────────────────────────────────────────────────

-- ⌥⇧A: screenshot if session active, else open config page
hs.hotkey.bind({"alt", "shift"}, "a", function()
  -- In multi mode, take another screenshot
  if multiMode then
    takeMultiScreenshot()
    return
  end

  local s = getSession()
  if not s or not s.active then
    hs.urlevent.openURL(SERVER)
    if not s then
      hs.alert.show("Server not running — check /tmp/anki-fox.log")
    end
    return
  end

  -- Dispatch based on source mode
  if s.source == "multi" then
    enterMultiMode()
  else
    takeScreenshot()
  end
end)

-- ⌥⇧M: cycle source mode (screen → multi → video → screen)
hs.hotkey.bind({"alt", "shift"}, "m", function()
  local s = getSession()
  if not s or not s.active then return end

  local code, body = hs.http.asyncPost(
    SERVER .. "/api/source/cycle", "", { ["Content-Type"] = "application/json" },
    function(code, respBody, _)
      if code == 200 then
        local ok, r = pcall(hs.json.decode, respBody)
        if ok and r and r.source then
          local labels = { screen = "Screen", multi = "Multi", video = "Video" }
          showLabel(labels[r.source] or r.source)
        end
      end
    end)
end)

-- ⌥⇧⌘A: open config page
hs.hotkey.bind({"alt", "shift", "cmd"}, "a", function()
  hs.urlevent.openURL(SERVER)
end)

hs.alert.show("anki-fox loaded — ⌥⇧A ready")

-- Locus quick capture
dofile(os.getenv("HOME") .. "/code/locus/hammerspoon/locus_hotkey.lua")
