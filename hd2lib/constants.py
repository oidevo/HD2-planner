from pathlib import Path

SCHEMA_VERSION = "1.0.0"
APP_VERSION = "0.1.0"
ROOT = Path(__file__).resolve().parent.parent
CATALOG_DIR = ROOT / "catalog"
PROFILES_DIR = ROOT / "profiles"
GENERATED_DIR = ROOT / "generated"
LOADOUTS_DIR = PROFILES_DIR / "loadouts"

CATALOG_FILES = {
    "weapons": "weapons.json",
    "attachments": "attachments.json",
    "grenades": "grenades.json",
    "armor": "armor.json",
    "armor_passives": "armor_passives.json",
    "boosters": "boosters.json",
    "stratagems": "stratagems.json",
    "ship_modules": "ship_modules.json",
    "warbonds": "warbonds.json",
    "enemies": "enemies.json",
    "mission_types": "mission_types.json",
    "biomes": "biomes.json",
}

INVENTORY_TO_CATALOG = {
    "warbonds": "warbonds",
    "primary_weapons": "weapons",
    "secondary_weapons": "weapons",
    "support_weapons": "weapons",
    "weapon_attachments": "attachments",
    "grenades": "grenades",
    "armor": "armor",
    "armor_passives": "armor_passives",
    "boosters": "boosters",
    "stratagems": "stratagems",
    "ship_modules": "ship_modules",
}

DISPLAY_CATEGORIES = {
    "primaries": "primary_weapons",
    "primary": "primary_weapons",
    "secondaries": "secondary_weapons",
    "secondary": "secondary_weapons",
    "support": "support_weapons",
    "support-weapons": "support_weapons",
    "attachments": "weapon_attachments",
    "grenades": "grenades",
    "armor": "armor",
    "passives": "armor_passives",
    "boosters": "boosters",
    "stratagems": "stratagems",
    "ship-modules": "ship_modules",
    "warbonds": "warbonds",
}

UNLOCK_STATES = {"unknown", "locked", "unlocked"}
PREFERENCE_STATES = {"favorite", "like", "neutral", "dislike", "avoid"}

