#!/usr/bin/env python3
import json
import os
import sys
import urllib.error
import urllib.request
from pathlib import Path

UNIVERSE_ID = "10516693405"
REPOSITORY = "InExperienceConfig"
CONFIG_DIR = Path("configs")

CONFIG_NAMES = [
    "Arenas",
    "Pets",
    "Pickaxes",
    "Rebirth",
    "RoomDrops",
    "Rooms",
    "SellItems",
    "Upgrades",
]

BASE = (
    "https://apis.roblox.com/creator-configs-public-api/v1/configs/"
    f"universes/{UNIVERSE_ID}/repositories/{REPOSITORY}"
)


def fail(message):
    print(f"ERROR: {message}", file=sys.stderr)
    sys.exit(1)


def request(method, url, api_key, body=None, allow_status=(200,)):
    headers = {
        "x-api-key": api_key,
        "Accept": "application/json",
    }

    data = None
    if body is not None:
        data = json.dumps(
            body,
            ensure_ascii=False,
            separators=(",", ":"),
        ).encode("utf-8")
        headers["Content-Type"] = "application/json"

    req = urllib.request.Request(
        url,
        data=data,
        headers=headers,
        method=method,
    )

    try:
        with urllib.request.urlopen(req, timeout=60) as response:
            raw = response.read().decode("utf-8")
            if response.status not in allow_status:
                fail(f"{method} {url}: HTTP {response.status}: {raw}")
            return response.status, raw
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode("utf-8", errors="replace")
        if exc.code in allow_status:
            return exc.code, raw
        fail(f"{method} {url}: HTTP {exc.code}: {raw}")
    except urllib.error.URLError as exc:
        fail(f"{method} {url}: network error: {exc}")


def load_configs():
    entries = {}

    for name in CONFIG_NAMES:
        path = CONFIG_DIR / f"{name}.json"

        if not path.exists():
            fail(f"Missing required file: {path}")

        try:
            with path.open("r", encoding="utf-8") as f:
                entries[name] = json.load(f)
        except json.JSONDecodeError as exc:
            fail(f"{path}: invalid JSON: {exc}")

    return entries


def assert_unique(values, label):
    seen = set()
    for value in values:
        key = str(value)
        if key in seen:
            fail(f"{label}: duplicate value {key}")
        seen.add(key)


def validate(configs):
    if not isinstance(configs["Arenas"], list):
        fail("Arenas must be an array")
    if not isinstance(configs["Pets"], list):
        fail("Pets must be an array")
    if not isinstance(configs["Pickaxes"], list):
        fail("Pickaxes must be an array")
    if not isinstance(configs["RoomDrops"], list):
        fail("RoomDrops must be an array")
    if not isinstance(configs["Upgrades"], list):
        fail("Upgrades must be an array")
    if not isinstance(configs["Rebirth"], dict):
        fail("Rebirth must be an object")

    if (
        not isinstance(configs["Rooms"], dict)
        or not isinstance(configs["Rooms"].get("rooms"), list)
    ):
        fail("Rooms.rooms must be an array")

    if (
        not isinstance(configs["SellItems"], dict)
        or not isinstance(configs["SellItems"].get("items"), list)
    ):
        fail("SellItems.items must be an array")

    assert_unique([x.get("id") for x in configs["Arenas"]], "Arenas.id")
    assert_unique([x.get("id") for x in configs["Pets"]], "Pets.id")
    assert_unique(
        [x.get("modelName") for x in configs["Pickaxes"]],
        "Pickaxes.modelName",
    )
    assert_unique(
        [x.get("index") for x in configs["Rooms"]["rooms"]],
        "Rooms.index",
    )
    assert_unique(
        [x.get("id") for x in configs["SellItems"]["items"]],
        "SellItems.id",
    )
    assert_unique(
        [x.get("id") for x in configs["Upgrades"]],
        "Upgrades.id",
    )

    sell_ids = {
        item["id"]
        for item in configs["SellItems"]["items"]
    }

    for room in configs["RoomDrops"]:
        room_index = room.get("index")
        drops = room.get("drops")

        if not isinstance(drops, list):
            fail(f"RoomDrops room {room_index}: drops must be an array")

        total = sum(float(drop.get("weight", 0)) for drop in drops)
        if abs(total - 100.0) > 1e-9:
            fail(
                f"RoomDrops room {room_index}: "
                f"weight sum is {total}, expected 100"
            )

        for drop in drops:
            if drop.get("itemId") not in sell_ids:
                fail(
                    f"RoomDrops room {room_index}: "
                    f"{drop.get('itemId')} missing in SellItems"
                )

    for upgrade in configs["Upgrades"]:
        prices = upgrade.get("prices")
        max_level = upgrade.get("maxLevel")

        if not isinstance(prices, list):
            fail(
                f"Upgrades {upgrade.get('id')}: "
                "prices must be an array"
            )

        if len(prices) != max_level:
            fail(
                f"Upgrades {upgrade.get('id')}: "
                f"{len(prices)} prices, maxLevel={max_level}"
            )

    print(f"Validation OK: {len(CONFIG_NAMES)} configs")


def parse_json(raw, context):
    if not raw:
        return {}
    try:
        return json.loads(raw)
    except json.JSONDecodeError as exc:
        fail(f"{context}: invalid JSON response: {exc}")


def main():
    api_key = os.environ.get("ROBLOX_API_KEY", "").strip()
    if not api_key:
        fail(
            "GitHub secret ROBLOX_API_KEY is missing. "
            "Create it in Settings -> Secrets and variables -> Actions."
        )

    configs = load_configs()
    validate(configs)

    # Read currently published values.
    _, published_raw = request(
        "GET",
        BASE,
        api_key,
        allow_status=(200,),
    )
    published = parse_json(published_raw, "GET published")
    published_entries = published.get("entries", {})

    # Check whether a previous draft exists.
    draft_status, draft_raw = request(
        "GET",
        f"{BASE}/draft",
        api_key,
        allow_status=(200, 404),
    )

    draft_entries = {}
    if draft_status == 200:
        draft = parse_json(draft_raw, "GET draft")
        draft_entries = draft.get("entries", {}) or {}

        # Do not accidentally publish someone else's manual draft.
        foreign_keys = sorted(
            set(draft_entries.keys()) - set(CONFIG_NAMES)
        )
        if foreign_keys:
            fail(
                "Roblox already has an unpublished draft containing "
                "keys outside Git-controlled configs: "
                + ", ".join(foreign_keys)
                + ". Publish or discard that draft in Creator Hub first."
            )

    # Avoid creating a useless Config revision when nothing changed.
    all_equal = all(
        published_entries.get(name) == configs[name]
        for name in CONFIG_NAMES
    )

    if all_equal and not draft_entries:
        print("No changes: Roblox Configs already match GitHub.")
        return

    # PATCH only our 8 keys. Other Roblox config keys remain untouched.
    patch_payload = {
        "entries": configs,
    }

    _, patch_raw = request(
        "PATCH",
        f"{BASE}/draft",
        api_key,
        body=patch_payload,
        allow_status=(200,),
    )
    patched_draft = parse_json(patch_raw, "PATCH draft")

    draft_hash = patched_draft.get("draftHash")
    if not draft_hash:
        fail("PATCH draft response did not contain draftHash")

    sha = os.environ.get("GITHUB_SHA", "")
    short_sha = sha[:7] if sha else "manual"

    publish_payload = {
        "draftHash": draft_hash,
        "message": f"GitHub configs sync {short_sha}",
        "deploymentStrategy": "Immediate",
    }

    _, publish_raw = request(
        "POST",
        f"{BASE}/publish",
        api_key,
        body=publish_payload,
        allow_status=(200,),
    )
    publish_result = parse_json(publish_raw, "POST publish")

    print(
        "Published Roblox Configs. "
        f"configVersion={publish_result.get('configVersion', 'unknown')}"
    )

    # Verify exact values after publication.
    _, verify_raw = request(
        "GET",
        BASE,
        api_key,
        allow_status=(200,),
    )
    verify = parse_json(verify_raw, "GET verify")
    verify_entries = verify.get("entries", {})

    mismatches = [
        name
        for name in CONFIG_NAMES
        if verify_entries.get(name) != configs[name]
    ]

    if mismatches:
        fail(
            "Published verification mismatch for: "
            + ", ".join(mismatches)
        )

    for name in CONFIG_NAMES:
        print(f"{name}: OK")

    print("DEPLOY COMPLETE")


if __name__ == "__main__":
    main()
