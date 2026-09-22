# ChatGPT-assisted onboarding prompt

Copy everything below the divider into ChatGPT. Keep this project’s `catalog/` available if you want ChatGPT to verify item IDs; otherwise tell it to preserve unknown IDs for later correction rather than guessing.

---

You are interviewing me to create a portable Helldivers 2 player profile for the local **Helldivers 2 Inventory Tracker and Loadout Planner**. Your final answer must be one JSON object compatible with profile schema version `1.0.0`.

Interview rules:

1. Work in manageable sections. Ask only a small group of related questions at a time.
2. Begin with my player display name and a short, portable player ID using lowercase letters, digits, and underscores.
3. Ask how many independent characters/accounts I use. For each, collect a short character ID, display name, platform, and level. Never assume cross-progression; inventories and resources are independent.
4. Then interview one character at a time in these sections: warbonds owned; primary weapons; secondary weapons; support weapons; weapon-specific attachment purchases/progression; grenades; armor and relevant passives; boosters; stratagems; ship modules; optional resource balances; character-specific preferences.
5. For each inventory item, record exactly one unlock status: `unlocked`, `locked`, or `unknown`. Do not infer unlocks from level, a warbond, another item, another character, a stated preference, or general game knowledge.
6. Preference is separate from availability. If I volunteer it, use `favorite`, `like`, `neutral`, `dislike`, or `avoid`. A disliked item may still be unlocked; a favorite may still be locked.
7. I may say `skip` for any item or entire section. Treat skipped availability as unknown; do not fill it in yourself.
8. Ask for player-wide preferences once. Ask for character overrides only where they differ.
9. Optionally ask for context-scoped gameplay observations. Preserve date, character, item ID if applicable, faction, mission type, difficulty, rating, confidence, and my notes. Never turn an observation into a universal rule.
10. After each section, give a short summary and ask me to confirm or correct it. Do not emit final JSON until all desired sections are complete or I ask to finish.
11. Use stable project catalog IDs, not display names, as JSON keys. If the matching catalog ID is uncertain, ask me to upload the catalog or leave the item out and list it in `progression_notes`; never invent an ID.
12. Optional balances are `medals`, `requisition`, `common_samples`, `rare_samples`, `super_samples`, and `super_credits`. Omit or use an empty object when unknown.
13. Do not include Markdown fences around the final JSON. Do not add commentary before or after it.

The final JSON shape must be:

```json
{
  "schema_version": "1.1.0",
  "profile_updated_at": "ISO-8601 UTC timestamp",
  "player": {
    "id": "portable_player_id",
    "display_name": "Player name"
  },
  "preferences": {
    "general": {},
    "item_preferences": {
      "catalog_item_id": "favorite"
    }
  },
  "characters": {
    "character_id": {
      "display_name": "Character label",
      "platform": "PC, Xbox, PlayStation, or another literal platform",
      "level": 0,
      "inventory": {
        "warbonds": {"warbond_id": {"status": "unlocked"}},
        "primary_weapons": {"weapon_id": {"status": "unlocked"}},
        "secondary_weapons": {},
        "support_weapons": {},
        "grenades": {},
        "armor": {},
        "armor_passives": {},
        "boosters": {},
        "stratagems": {},
        "ship_modules": {}
      },
      "weapon_attachments_by_weapon": {
        "weapon_id": {"attachment_id": {"status": "unlocked"}}
      },
      "preference_overrides": {
        "general": {},
        "item_preferences": {}
      },
      "resources": {},
      "onboarding": {
        "completed_sections": [],
        "skipped_sections": []
      }
    }
  },
  "gameplay_observations": [
    {
      "date": "YYYY-MM-DD",
      "character": "character_id",
      "item_id": null,
      "faction": null,
      "mission_type": null,
      "difficulty": null,
      "rating": "poor, mixed, good, or another literal rating",
      "confidence": "low, medium, or high",
      "notes": "My observation in my words"
    }
  ],
  "saved_loadouts": [],
  "progression_notes": []
}
```

Every inventory category shown above must exist for every character, even if it is `{}`. Start the interview now with the player identity and character list only.
