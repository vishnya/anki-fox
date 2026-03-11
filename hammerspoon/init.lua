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

local function takeScreenshot()
  local ts   = os.date("%Y%m%d_%H%M%S")
  local path = INCOMING .. "/screenshot_" .. ts .. ".png"
  hs.task.new("/usr/sbin/screencapture", function(exitCode, _, _)
    hs.timer.doAfter(0.3, function()
      if hs.fs.attributes(path) then showFox() end
    end)
  end, {"-i", path}):start()
end

-- ⌥⇧A: screenshot if session active, else open config page
hs.hotkey.bind({"alt", "shift"}, "a", function()
  local s = getSession()
  if s and s.active then
    takeScreenshot()
  else
    hs.urlevent.openURL(SERVER)
    if not s then
      hs.alert.show("Server not running — check /tmp/anki-fox.log")
    end
  end
end)

-- ⌥⇧⌘A: open config page
hs.hotkey.bind({"alt", "shift", "cmd"}, "a", function()
  hs.urlevent.openURL(SERVER)
end)

hs.alert.show("anki-fox loaded — ⌥⇧A ready")
