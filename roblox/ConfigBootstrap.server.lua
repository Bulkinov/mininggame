-- Example bootstrap Script next to ConfigService ModuleScript.
local ConfigService = require(script.Parent.ConfigService)

local configs = ConfigService.LoadAll()
print("[ConfigBootstrap] Configs loaded for place", game.PlaceId)

-- Examples:
-- local Pickaxes = ConfigService.Get("Pickaxes")
-- local Rooms = ConfigService.Get("Rooms")
--
-- ConfigService.Changed:Connect(function(configName, newValue)
--     print("Config hot-reloaded:", configName)
--     -- Notify systems that keep their own derived/cache data here.
-- end)
