#!/usr/bin/env python3
import json
import math
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CONFIG_DIR = ROOT / "configs"
FILES = ["Arenas", "Pets", "Pickaxes", "Rebirth", "RoomDrops", "Rooms", "SellItems", "Upgrades"]


def load(name):
    p = CONFIG_DIR / f"{name}.json"
    if not p.exists():
        raise SystemExit(f"Missing {p}")
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception as e:
        raise SystemExit(f"Invalid JSON {p}: {e}")


def unique(values, label):
    seen = set()
    for v in values:
        if v in seen:
            raise SystemExit(f"Duplicate {label}: {v}")
        seen.add(v)


def main():
    cfg = {name: load(name) for name in FILES}
    unique([x["id"] for x in cfg["Arenas"]], "Arenas.id")
    unique([x["id"] for x in cfg["Pets"]], "Pets.id")
    unique([x["modelName"] for x in cfg["Pickaxes"]], "Pickaxes.modelName")
    unique([x["index"] for x in cfg["Rooms"]["rooms"]], "Rooms.index")
    unique([x["id"] for x in cfg["SellItems"]["items"]], "SellItems.id")
    unique([x["id"] for x in cfg["Upgrades"]], "Upgrades.id")

    room_indices = [x["index"] for x in cfg["Rooms"]["rooms"]]
    if room_indices and sorted(room_indices) != list(range(min(room_indices), max(room_indices) + 1)):
        raise SystemExit("Rooms.index must be contiguous.")

    drop_indices = [x["index"] for x in cfg["RoomDrops"]]
    if drop_indices != sorted(drop_indices):
        raise SystemExit("RoomDrops must be sorted by index.")

    sell_ids = {x["id"] for x in cfg["SellItems"]["items"]}
    for room in cfg["RoomDrops"]:
        total = sum(float(d["weight"]) for d in room["drops"])
        if not math.isclose(total, 100.0, rel_tol=0, abs_tol=1e-9):
            raise SystemExit(f"RoomDrops room {room['index']} total weight = {total}, expected 100")
        for d in room["drops"]:
            if d["itemId"] not in sell_ids:
                raise SystemExit(f"RoomDrops room {room['index']} references missing SellItems id {d['itemId']}")

    for upg in cfg["Upgrades"]:
        if len(upg["prices"]) != int(upg["maxLevel"]):
            raise SystemExit(f"Upgrade {upg['id']}: prices={len(upg['prices'])}, maxLevel={upg['maxLevel']}")

    for name, obj in cfg.items():
        size = len(json.dumps(obj, separators=(",", ":"), ensure_ascii=False).encode("utf-8"))
        if size > 4_000_000:
            raise SystemExit(f"{name}.json too large for one Roblox DataStore entry: {size} bytes")
        print(f"OK {name}.json: {size:,} bytes")

    print("All config validation checks passed.")


if __name__ == "__main__":
    main()
