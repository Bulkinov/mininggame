#!/usr/bin/env python3
import json
import os
import sys
import urllib.error
import urllib.request
from pathlib import Path

CONFIG_DIR = Path("configs")
REPOSITORY = "InExperienceConfig"

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
                fail(
                    f"{method} {url}: "
                    f"HTTP {response.status}: {raw}"
                )

            return response.status, raw

    except urllib.error.HTTPError as exc:
        raw = exc.read().decode(
            "utf-8",
            errors="replace",
        )

        if exc.code in allow_status:
            return exc.code, raw

        fail(
            f"{method} {url}: "
            f"HTTP {exc.code}: {raw}"
        )

    except urllib.error.URLError as exc:
        fail(
            f"{method} {url}: network error: {exc}"
        )


def load_configs():
    result = {}

    for name in CONFIG_NAMES:
        path = CONFIG_DIR / f"{name}.json"

        if not path.exists():
            fail(f"Missing required file: {path}")

        try:
            with path.open("r", encoding="utf-8") as f:
                result[name] = json.load(f)

        except json.JSONDecodeError as exc:
            fail(
                f"{path}: invalid JSON: {exc}"
            )

    return result


def assert_unique(values, label):
    seen = set()

    for value in values:
        key = str(value)

        if key in seen:
            fail(
                f"{label}: duplicate value {key}"
            )

        seen.add(key)


def validate(configs):
    assert_unique(
        [x.get("id") for x in configs["Arenas"]],
        "Arenas.id",
    )

    assert_unique(
        [x.get("id") for x in configs["Pets"]],
        "Pets.id",
    )

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
        total = sum(
            float(drop.get("weight", 0))
            for drop in room.get("drops", [])
        )

        if abs(total - 100.0) > 1e-9:
            fail(
                f"RoomDrops room {room.get('index')}: "
                f"weight sum is {total}, expected 100"
            )

        for drop in room.get("drops", []):
            if drop.get("itemId") not in sell_ids:
                fail(
                    f"RoomDrops room {room.get('index')}: "
                    f"{drop.get('itemId')} missing in SellItems"
                )

    for upgrade in configs["Upgrades"]:
        prices = upgrade.get("prices", [])
        max_level = upgrade.get("maxLevel")

        if len(prices) != max_level:
            fail(
                f"Upgrades {upgrade.get('id')}: "
                f"{len(prices)} prices, "
                f"maxLevel={max_level}"
            )

    print(
        f"Validation OK: {len(CONFIG_NAMES)} configs"
    )


def parse_json(raw, context):
    if not raw:
        return {}

    try:
        return json.loads(raw)

    except json.JSONDecodeError as exc:
        fail(
            f"{context}: invalid JSON response: {exc}"
        )


def main():
    api_key = os.environ.get(
        "ROBLOX_API_KEY",
        "",
    ).strip()

    universe_id = os.environ.get(
        "ROBLOX_UNIVERSE_ID",
        "",
    ).strip()

    environment = os.environ.get(
        "ROBLOX_ENV",
        "UNKNOWN",
    ).strip()

    if not api_key:
        fail(
            "ROBLOX_API_KEY secret is missing"
        )

    if not universe_id:
        fail(
            "ROBLOX_UNIVERSE_ID is missing"
        )

    base = (
        "https://apis.roblox.com/"
        "creator-configs-public-api/v1/configs/"
        f"universes/{universe_id}/"
        f"repositories/{REPOSITORY}"
    )

    print(
        f"Target: {environment} "
        f"Universe {universe_id}"
    )

    configs = load_configs()
    validate(configs)

    _, published_raw = request(
        "GET",
        base,
        api_key,
        allow_status=(200,),
    )

    published = parse_json(
        published_raw,
        "GET published",
    )

    published_entries = (
        published.get("entries", {}) or {}
    )

    draft_status, draft_raw = request(
        "GET",
        f"{base}/draft",
        api_key,
        allow_status=(200, 404),
    )

    draft_entries = {}

    if draft_status == 200:
        draft = parse_json(
            draft_raw,
            "GET draft",
        )

        draft_entries = (
            draft.get("entries", {}) or {}
        )

        foreign_keys = sorted(
            set(draft_entries.keys())
            - set(CONFIG_NAMES)
        )

        if foreign_keys:
            fail(
                "Roblox already has an unpublished draft "
                "containing keys outside Git-controlled "
                "configs: "
                + ", ".join(foreign_keys)
            )

    all_equal = all(
        published_entries.get(name)
        == configs[name]
        for name in CONFIG_NAMES
    )

    if all_equal and not draft_entries:
        print(
            "No config value changes. "
            "Roblox already matches GitHub."
        )
        return

    _, patch_raw = request(
        "PATCH",
        f"{base}/draft",
        api_key,
        body={"entries": configs},
        allow_status=(200,),
    )

    patched = parse_json(
        patch_raw,
        "PATCH draft",
    )

    draft_hash = patched.get("draftHash")

    if not draft_hash:
        fail(
            "PATCH draft response did not contain draftHash"
        )

    sha = os.environ.get(
        "GITHUB_SHA",
        "",
    )

    short_sha = (
        sha[:7]
        if sha
        else "manual"
    )

    publish_payload = {
        "draftHash": draft_hash,
        "message":
            f"{environment} GitHub configs sync {short_sha}",
        "deploymentStrategy": "Immediate",
    }

    _, publish_raw = request(
        "POST",
        f"{base}/publish",
        api_key,
        body=publish_payload,
        allow_status=(200,),
    )

    publish_result = parse_json(
        publish_raw,
        "POST publish",
    )

    print(
        "Published Roblox Configs. "
        f"configVersion="
        f"{publish_result.get('configVersion', 'unknown')}"
    )

    _, verify_raw = request(
        "GET",
        base,
        api_key,
        allow_status=(200,),
    )

    verify = parse_json(
        verify_raw,
        "GET verify",
    )

    verify_entries = (
        verify.get("entries", {}) or {}
    )

    mismatches = [
        name
        for name in CONFIG_NAMES
        if verify_entries.get(name)
        != configs[name]
    ]

    if mismatches:
        fail(
            "Published verification mismatch for: "
            + ", ".join(mismatches)
        )

    for name in CONFIG_NAMES:
        print(f"{name}: OK")

    print(
        f"{environment} DEPLOY COMPLETE"
    )


if __name__ == "__main__":
    main()
