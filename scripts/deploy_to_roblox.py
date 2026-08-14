#!/usr/bin/env python3
import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CONFIG_DIR = ROOT / "configs"
CONFIG_NAMES = ["Arenas", "Pets", "Pickaxes", "Rebirth", "RoomDrops", "Rooms", "SellItems", "Upgrades"]
BASE = "https://apis.roblox.com/cloud/v2"


def required(name):
    value = os.getenv(name, "").strip()
    if not value:
        raise SystemExit(f"Missing environment variable: {name}")
    return value


def request(url, method, api_key, body=None):
    data = None
    headers = {"x-api-key": api_key}
    if body is not None:
        data = json.dumps(body, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(url=url, data=data, method=method, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=45) as resp:
            return resp.status, resp.read().decode("utf-8")
    except urllib.error.HTTPError as e:
        text = e.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"Roblox API {method} {url} -> {e.code}: {text}") from e


def main():
    api_key = required("ROBLOX_API_KEY")
    universe_id = required("ROBLOX_UNIVERSE_ID")
    place_id = required("ROBLOX_PLACE_ID")
    datastore = os.getenv("ROBLOX_DATASTORE", "GameConfigs").strip() or "GameConfigs"
    commit_sha = os.getenv("GITHUB_SHA", "manual")

    datastore_q = urllib.parse.quote(datastore, safe="")
    deployed = []

    for name in CONFIG_NAMES:
        path = CONFIG_DIR / f"{name}.json"
        if not path.exists():
            raise SystemExit(f"Missing {path}")
        config = json.loads(path.read_text(encoding="utf-8"))
        entry_id = f"place:{place_id}:{name}"
        if len(entry_id) > 50:
            raise SystemExit(f"Roblox DataStore key too long ({len(entry_id)}): {entry_id}")

        entry_q = urllib.parse.quote(entry_id, safe="")
        # allow_missing=true gives us idempotent create-or-update behavior for deployment.
        url = f"{BASE}/universes/{urllib.parse.quote(universe_id, safe='')}/data-stores/{datastore_q}/entries/{entry_q}?allow_missing=true"
        status, _ = request(url, "PATCH", api_key, {"value": config})
        print(f"DEPLOYED {name} -> {entry_id} (HTTP {status})")
        deployed.append(name)

    # Tell live servers that new configs are available. Servers in other places ignore the message.
    message = json.dumps({"placeId": str(place_id), "commit": commit_sha, "configs": deployed}, separators=(",", ":"))
    msg_url = f"{BASE}/universes/{urllib.parse.quote(universe_id, safe='')}:publishMessage"
    status, _ = request(msg_url, "POST", api_key, {"topic": "config-updated", "message": message})
    print(f"Published config-updated message (HTTP {status}).")


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        print(str(e), file=sys.stderr)
        raise
