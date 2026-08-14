-- Server-side ModuleScript. Place it in ServerScriptService (or another server-only container).
-- GitHub deploys entries to DataStore "GameConfigs" with keys place:<PlaceId>:<ConfigName>.

local DataStoreService = game:GetService("DataStoreService")
local MessagingService = game:GetService("MessagingService")
local HttpService = game:GetService("HttpService")

local ConfigService = {}

local DATASTORE_NAME = "GameConfigs"
local UPDATE_TOPIC = "config-updated"
local CONFIG_NAMES = {
    "Arenas",
    "Pets",
    "Pickaxes",
    "Rebirth",
    "RoomDrops",
    "Rooms",
    "SellItems",
    "Upgrades",
}

local store = DataStoreService:GetDataStore(DATASTORE_NAME)
local cache = {}
local changedEvent = Instance.new("BindableEvent")
ConfigService.Changed = changedEvent.Event

local function keyFor(name)
    return string.format("place:%d:%s", game.PlaceId, name)
end

function ConfigService.Load(name)
    assert(table.find(CONFIG_NAMES, name), "Unknown config: " .. tostring(name))

    local ok, value = pcall(function()
        return store:GetAsync(keyFor(name))
    end)

    if not ok then
        warn(string.format("[ConfigService] Failed loading %s: %s", name, tostring(value)))
        return nil
    end

    if value == nil then
        warn(string.format("[ConfigService] Missing config %s (%s)", name, keyFor(name)))
        return nil
    end

    cache[name] = value
    changedEvent:Fire(name, value)
    return value
end

function ConfigService.LoadAll()
    local loaded = {}
    for _, name in ipairs(CONFIG_NAMES) do
        loaded[name] = ConfigService.Load(name)
    end
    return loaded
end

function ConfigService.Get(name)
    if cache[name] == nil then
        return ConfigService.Load(name)
    end
    return cache[name]
end

function ConfigService.GetAll()
    return cache
end

local function subscribeForHotReload()
    local ok, connectionOrError = pcall(function()
        return MessagingService:SubscribeAsync(UPDATE_TOPIC, function(message)
            local decodedOk, payload = pcall(function()
                return HttpService:JSONDecode(message.Data)
            end)
            if not decodedOk or type(payload) ~= "table" then
                warn("[ConfigService] Bad config-updated payload")
                return
            end

            if tostring(payload.placeId) ~= tostring(game.PlaceId) then
                return
            end

            task.defer(function()
                print("[ConfigService] Reloading configs from deploy", payload.commit or "")
                ConfigService.LoadAll()
            end)
        end)
    end)

    if not ok then
        warn("[ConfigService] Messaging subscription failed: " .. tostring(connectionOrError))
    end
end

subscribeForHotReload()

return ConfigService
