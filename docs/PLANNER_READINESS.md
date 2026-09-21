# Planner Readiness Audit

Audit date: 2026-09-21  
Accepted catalog: `2026.09.21.2`  
Scope: Pass 1 schemas, accepted catalog, importer, provenance, overrides, profiles, saved loadouts, planner rules, tests, and generated ChatGPT context. No recommendation engine was implemented.

## Verdict

The repository is **not ready for an unrestricted Pass 2 recommendation engine**. It is ready for a deliberately narrow, fixture-backed loadout-composition prototype that excludes personalized Warbond strategy, attachment progression, detailed enemy threat scoring, and environmental scoring.

The architecture is sound: canonical JSON, generated presentation files, source provenance, manual overrides, player state, and community observations are already separated. The blockers are semantic coverage and source contamination, not a need to redesign that architecture.

## Existing implementation audit

- **Catalog schema:** the envelope, IDs, provenance, tags, and derived-field provenance are documented, but `facts` remains intentionally open-ended. Category-specific semantics are enforced by normalization/tests rather than a large union schema. This is appropriate for the current importer, but Pass 2 must not interpret arbitrary raw keys as typed facts.
- **Importer:** Cargo/MediaWiki revision provenance is strong and ordinary use is offline. The old generic deduplication is lossy when one ID represents multiple row relationships; this is visible in attachment effects and merged HD1/HD2 enemy names. Cross-catalog normalization now runs after all tables are present. Candidate review remains mandatory.
- **Provenance and overrides:** imported records retain source revisions and manual patches append separate provenance. The only manual overrides seed a few planner tags. Those tags now identify themselves as manually curated; they are not game facts.
- **Player/profile schema:** multiple characters, independent inventories, three-state ownership, preferences, resources, and scoped observations are suitable foundations. Warbond ownership is only one coarse status, resources are untyped, and there is no page/reward claim state. Separately recording `armor_passives` can drift from owned armor; planners should derive equipped passive from armor rather than treat it as an owned slot.
- **Saved-loadout schema:** it represents the actual planning slots used by Pass 1 and allows partial drafts. It intentionally has no attachment configuration, helmet, or cape. Runtime validation now enforces item category and stratagem selectability, but the JSON schema alone cannot enforce catalog referential integrity or distinguish a draft from an ordinary complete loadout.
- **Planner rules:** the three existing rules correctly separate immediate availability, future progression targets, and scoped player observations. Mechanical rules were missing and are now in `planner/constraints.json`; no scoring or ranking rules were added.
- **Tests:** the original suite covered storage, character isolation, availability, provenance, catalog comparison, export integrity, privacy, and offline operation. New tests cover normalized relationships, non-equippable stratagems, slot semantics, tag provenance, constraints, and the reviewed fixture.
- **Generated ChatGPT context:** JSON includes raw and normalized facts only for inventory entries; Markdown is a concise ownership/preference view and does not embed the full catalog or capability model. Both remain generated artifacts with source hashes and were refreshed. They are suitable profile handoffs, not a standalone knowledge base for recommendation scoring.

## Ready

- Catalog collections load deterministically, have unique IDs within the accepted snapshot, verify manifest content hashes, and retain source page, URL, revision, retrieval time, and importer version.
- All 114 weapon records have an explicit primary/secondary/support category: 54 primary, 25 secondary, and 35 support weapons.
- Weapon and grenade damage-type labels can be deterministically extracted from the structured damage markup for 111/114 weapons and 19/23 grenades. This is a damage-type label, not a damage simulation.
- Explicit weapon-trait armor penetration is normalized for 70/114 weapons. Missing penetration is unknown, not “none.”
- All 30 attachment records have a normalized slot and explicit `compatible_weapon_ids`. The 508 source compatibility references resolve to 43 weapon IDs without name inference at planner runtime.
- All 115 stratagem records now state `player_equippable`. Ninety-three are ordinary selectable records; 22 are objective, ship-action, or other non-loadout records.
- All 33 support-weapon stratagems explicitly reference their weapon record. Nine explicitly state backpack use. The SG-88 Break-Action Shotgun and Trench Shovel weapon records have no matching selectable support-weapon stratagem and must not be treated as call-ins.
- Cooldown seconds are normalized for 111/115 stratagems. Anti-Tank, armor-penetration, explosive, and backpack facts are normalized only when explicit source traits support them.
- Body armor and helmets are distinct: 109 body armor and 110 helmets. All body armor has an armor class, numerical armor/speed/stamina fields, and either a normalized passive ID or explicit no-passive (`null`) state.
- Warbond headers reliably provide identity, type, date, normalized purchase cost, total listed medal cost, and included Super Credits (including explicit zero). Reward-side links are partially normalized for equipment records.
- Ship-module identity, six paths, tiers, and costs are normalized. Twenty-nine of 30 prerequisite fields resolve to explicit module IDs.
- Core faction IDs are normalized only where the imported value is unambiguous: 47 enemies and 69 missions.
- Saved-loadout validation now rejects wrong equipment-slot categories, duplicate stratagems, and non-player-equippable stratagems.
- Mechanical constraints and a compact capability vocabulary are explicit data files rather than hidden planner assumptions.
- The representative fixture is a reviewed slice tied to the accepted catalog version and includes weapons, grenades, support weapons, Eagle, Orbital, sentry, anti-tank, utility, three enemies per core faction, missions, and a partial Warbond reward example.

## Needs normalization

### Weapons

| Semantic | Status | Evidence / gap |
|---|---|---|
| category and loadout role | Ready | Explicit for all 114. |
| armor penetration | Partial | Explicit trait for 70; unknown for 44. |
| damage type | Mostly ready | Extracted for 111; raw markup remains for audit. |
| explosive capability | Partial | 14 explicit weapon traits; 28 records have explosion damage labels. Explosion does not prove structure destruction. |
| structure/objective destruction | Not normalized | No general structured fact. Existing `structure_destroy` is a manually curated planner tag on one seed record. |
| range | Missing | Optic ranges exist for some attachments, but reliable weapon effective-range facts do not. |
| reload | Partial | Sixteen weapon records explicitly say rounds reload; stationary reload appears on support-stratagem traits. Reload duration, tactical reload, and reload mobility are absent. |
| ammunition | Partial | 90 numeric capacities; other values include `N/A`, infinity, or compound presentation values. Magazine count and reserve ammunition are not generally normalized. |
| backpack dependency | Ready for selectable support weapons | Explicit on the stratagem, not the duplicate weapon record. |
| special mechanics | Partial | Trait strings exist for 82 weapons but are not a complete behavioral model. |
| progression | Partial | Warbond/page/cost links exist for many rewards; other sources and incomplete Warbond data remain. |
| attachments | Compatibility ready; effects/progression blocked | Explicit IDs are now available, but per-weapon effects and unlock state are not. |

Every weapon record still contains at least one presentation-markup field, usually source or damage. Planner code should use normalized fields and preserve raw values only for audit/display.

### Attachments

The catalog can reliably answer which of the 30 attachment definitions is compatible with which of 43 weapons and whether its slot is optics, muzzle, underbarrel, or magazine. Attachments in the same slot are mechanically mutually exclusive for a particular weapon; this rule is explicit in `planner/constraints.json`.

It cannot reliably answer unlock requirement, attachment cost, or per-weapon resulting effect. Five attachment rows were produced by multiple Cargo rows and contain list-valued effects after deduplication. The importer lost the row-level pairing between weapon and effect, so those arrays must not be assigned across weapons by position. The current global inventory key (for example `drum_magazine`) also cannot represent a magazine being unlocked for one weapon but not another.

**Attachment progression is not sufficiently reliable for Pass 2.** A future source/import must preserve `(weapon_id, attachment_id, slot, unlock_requirement, cost, effect)` as a relationship record or equivalent composite-key structure.

### Stratagems

The accepted table mixes player loadout choices with 16 objective call-ins, five ship actions, and one “Other” record (Orbital Illumination Flare). These 22 are now explicitly non-equippable rather than deleted, preserving source fidelity.

There are no duplicate canonical IDs. The 33 same-named weapon/stratagem pairs are not duplicates: one record describes the weapon and one describes the call-in. They now have explicit `support_weapon_id` relationships. Vehicle, sentry, emplacement, backpack, Eagle, and Orbital variants remain distinct source records. The source does not provide a reliable deprecated/released/mission-availability status for every record, so `player_equippable` is based strictly on structured stratagem type, not presumed release history.

Cooldown, category, backpack use, support-weapon link, Anti-Tank, armor penetration, and explosive traits are usable where present. Uses/charges, Eagle rearm capacity, structure destruction, and detailed offensive/defensive performance are not generally available. `permit_type` and category are factual classifications; anti-heavy effectiveness beyond an explicit Anti-Tank trait is a planner assessment.

### Armor

Body armor is planner-usable for slot, armor class, ratings, and passive identity. Helmets are preserved as a separate equipment slot and are not assigned strategic value. The imported snapshot contains **no capes**, despite the source table being capable of carrying a cape type.

The 31 armor-passive records have identity and provenance but no structured mechanical effects. A planner may match armor to a passive ID, but it cannot explain the passive from this catalog. Helmet “Standard Issue” is normalized as no mechanical passive. Cape strategy is unavailable because cape records are missing.

### Warbonds

Warbond identity and headline costs are reliable. Reverse reward links are partially useful:

- weapons: 80 linked to a known Warbond, 78 with page, 64 with normalized medal cost;
- grenades: 19 linked, 18 with page, all 19 with medal cost;
- armor/helmets: 120 linked, all with page and medal cost;
- stratagems: 29 linked, all with page and medal cost.

This is not a complete reward graph. The structured import omits booster sources entirely and does not contain capes, cosmetics, currencies, titles, emotes, patterns, or every other page reward. Three Castellan's Creed equipment rewards lack a page in the source row. Nine Ironclad Democracy equipment rows point to a Warbond absent from `warbonds.json` (three weapons, two grenades, and two armor/helmet pairs). Some weapon costs are absent or malformed.

Most importantly, there are no page-unlock thresholds, medal-spend prerequisites, reward dependencies, or a player’s page-level/reward-level claim state. `all_pages` is a total cost, not a progression graph.

Consequently:

- **“What can this player unlock next?” — No.** Ownership, resource balance, page gates, claimed rewards, prerequisites, and per-reward state cannot be combined accurately.
- **“What would obtaining this Warbond give this player access to?” — Only partially.** The app can list a subset of linked equipment, but not the complete contents or dependency path.

Do not implement personalized Warbond ranking or next-unlock advice until a complete reward table and player reward/page state exist.

### Ship modules

All 30 modules have an identity, six path IDs, tiers, and normalized resource costs. Twenty-nine prerequisites are explicit IDs. `rapid_launch_system` has raw prior value `Engineering Bay`, which is a path name rather than a module ID; that single link remains unresolved. Five paths are fully reconstructible and the Engineering Bay chain has a gap at tier 3.

No structured gameplay-effect text is imported for any module. Dependency-aware affordability can be prototyped for five paths, but benefit-aware module advice cannot be explained from the current catalog.

### Enemies

Enemy data is not planner-ready for general threat modeling. All 115 records have a raw faction, but only 47 have an unambiguous core HD2 faction value. The source includes HD1 factions, subfactions/strains, Super Earth records, and eight IDs where deduplication merged different game/faction rows (for example Hunter and Watcher). This is source-table contamination, not a multi-faction gameplay fact.

Only three records have `class`; `size` is present for 84 but is an undocumented numeric scale, not a safe light/medium/heavy role. Armor, shields, weak points, flying/ground, ranged/melee, and special mechanics are not structured. Health and difficulty frequently contain wiki markup or compound prose. Do not derive a combat simulator or assign threat roles from these values.

Before threat-based Pass 2 work, import an explicit game scope/edition, canonical parent faction, coarse reviewed threat role, armor/shield facts, movement domain, attack mode, and only a small number of reliable weak-point/special-mechanic facts.

### Missions

Seventy-one of 97 records have basic faction, difficulty, and time data; 26 have no facts and are primarily secondary objectives or installations mixed into the table. One Blitz ID merges Automaton and Terminid variants. Sixty-nine records have an unambiguous normalized faction ID.

The catalog lacks explicit objective style, mobile/static/defensive classification, and structured special conditions. Names are insufficient evidence for planner code to infer these properties. Representative mission IDs are safe fixture anchors, but mission-style capability requirements require manual curation with provenance.

### Biomes and environment

The 31 records contain a name, broad archetype, internal name, and landscape filename. The queried `environmental_conditions` field is empty for every record. These are reference records, not planner-useful environment semantics. Biome scoring should remain out of the initial engine.

## Relationships

| Relationship | Readiness |
|---|---|
| Warbond -> rewards | Partial reverse links only; incomplete categories and missing graph. |
| reward -> Warbond/page/cost | Partial and explicit for the counts above. |
| weapon -> compatible attachments | Ready for compatibility; not effects or progression. |
| ship module -> prerequisite | 29/30 explicit; one source artifact unresolved. |
| enemy -> faction | Partial; only unambiguous core values normalized. |
| mission -> faction | Mostly ready for main mission rows; variants/secondary rows remain. |
| stratagem -> backpack use | Ready when explicitly tagged; 23 stratagems occupy the slot, including nine support weapons. |
| support stratagem -> weapon | Ready for all 33 support-weapon stratagems. |
| equipment -> capability facts | Partial; only deterministic mechanical facts normalized. Planner assessments remain tags. |

The planner no longer needs runtime name matching for attachments, support weapons, ship prerequisites, or normalized Warbond reward links. Raw source strings remain alongside the derived IDs for audit.

## Stable IDs

IDs are deterministic but not genuinely immutable: the importer slugs mutable display titles. A wiki rename therefore creates a remove/add pair and can break profiles/loadouts. Armor IDs containing encoded presentation text (for example `_39_` from `&#39;`) demonstrate the risk.

No disruptive migration is warranted in this pass because the accepted snapshot has unique IDs and existing profile/loadout references. Before broad adoption, the importer should retain a stable upstream page/entity identifier and an alias/tombstone map so reviewed renames preserve canonical IDs. Catalog comparison should continue to require review for removals and category changes.

## Facts, assessments, and opinions

- **Imported facts:** raw Cargo values such as cooldown, traits, source, cost, faction, and capacity. They retain record provenance and may contain presentation markup.
- **Derived facts:** deterministic transformations such as `cooldown_seconds`, `compatible_weapon_ids`, `support_weapon_id`, `warbond_id`, and `prerequisite_module_id`. Each has `fact_provenance.kind = derived` and source field paths.
- **Planner assessments:** semantic judgments such as `light_clear`, `sustained_output`, or `structure_destroy`. These belong in `planner_tags` with `provenance_kind`, origin, and confidence.
- **Player/community opinions:** profile observations/preferences and dated community observations. They remain outside catalog facts and must be scoped by character/context.

Existing manually seeded planner tags now explicitly use `provenance_kind: manually_curated`. Raw imported traits are not silently promoted to subjective effectiveness claims.

## Minimum capability vocabulary

The initial vocabulary is in `planner/capabilities.json`.

**Fact-supported capability:**

- `anti_tank` — only when the structured source explicitly says Anti-Tank.

**Curated planner assessments:**

- `light_clear`
- `medium_armor_damage`
- `structure_destroy`
- `crowd_control`
- `burst_output`
- `sustained_output`
- `close_range`
- `long_range`
- `area_denial`
- `defensive_utility`
- `mobility`
- `team_support`
- `objective_utility`

Supporting facts such as armor penetration, damage types, explosive trait, cooldown, and backpack use are not themselves proof of effectiveness. `shield_breaking` is excluded because the catalog lacks reliable shield interaction data. Generic `heavy_damage` is excluded in favor of explicit Anti-Tank evidence plus a curated assessment where necessary.

## Mechanical constraints

`planner/constraints.json` defines:

- exactly one primary, secondary, grenade, and body armor for a complete loadout;
- zero or one booster per player loadout (team-wide booster uniqueness is not yet modeled);
- four distinct stratagems for an ordinary complete loadout;
- one backpack slot shared by backpack stratagems and backpack support weapons;
- support weapons selected through their linked stratagem;
- armor passive as a property of body armor, not an independent equipment slot;
- at most one attachment per weapon/attachment-slot pair, currently blocked for progression use.

The saved-loadout format permits incomplete drafts (`null` equipment and fewer than four stratagems), while validation enforces slot type, uniqueness, and selectability. Mission modifiers that reduce stratagem slots, team-wide booster uniqueness, armor/helmet/cape cosmetic slots, and dual-purpose vehicle/passenger constraints are not represented and should be added only from reliable rules.

## Missing

Planner-critical missing information:

- complete Warbond reward/page/prerequisite graph and player claim state;
- per-weapon attachment unlock, cost, effect, and ownership state;
- armor-passive mechanical effects;
- enemy game scope, coarse threat role, armor/shield facts, movement/attack mode, and selected reliable mechanics;
- mission objective style and static/mobile/defensive classification;
- stratagem uses/charges and reliable structure-destruction facts;
- effective weapon range and generally reliable reload/ammunition behavior;
- ship-module gameplay effects;
- biome environmental conditions;
- a reviewed capability assessment set beyond the small seed/fixture.

## Optional

Not required for an initial, conservative loadout composer:

- exact damage/health simulation;
- detailed enemy weak-point anatomy;
- cosmetic armor/helmet/cape relationships;
- landscape assets and internal biome names;
- community meta rankings;
- team-composition optimization;
- exact patch/build binding beyond catalog retrieval/revision provenance.

## Risks

- Treating raw wiki markup as typed data will produce incorrect comparisons and explanations.
- Treating every stratagem row as selectable can recommend mission call-ins or ship actions.
- Treating same-named weapon/stratagem rows as duplicates can remove the call-in relationship.
- Treating missing traits as false facts will understate capabilities.
- Treating explosion damage as structure destruction will overclaim objective utility.
- Treating attachment effect arrays as positional will attach the wrong stat to a weapon.
- Treating a global attachment ID as a per-weapon unlock will misstate player progression.
- Treating separately recorded armor-passive ownership as an equip choice can contradict the selected body armor.
- Treating the enemy table as HD2-only will mix legacy enemies and merged identities into threat modeling.
- Treating Warbond totals as a progression graph will generate impossible “unlock next” advice.
- Treating helmet or cape selection as strategic without mechanics will fabricate value.
- Treating names as stable IDs will break profiles when source titles change.
- Generated JSON context includes both raw and normalized facts for owned items; consumers must prefer normalized fields and respect provenance. Generated Markdown intentionally remains a concise inventory view, not a complete planner knowledge base.

## Bounded changes made

- Added deterministic importer normalization for costs, cooldowns, traits, damage types, armor slots/classes/passives, attachment compatibility, support-weapon links, Warbond reward links, ship prerequisites, selectability, and unambiguous core faction IDs.
- Preserved raw imported fields and added field-level derived provenance.
- Added planner-tag provenance kind and aligned the small manual tag seed to the final vocabulary.
- Added explicit mechanical constraints and capability vocabulary data.
- Tightened profile/loadout validation for slot/category semantics and non-equippable stratagems.
- Added a reviewed deterministic Pass 2 fixture and tests.
- Bumped the accepted catalog to `2026.09.21.2` and refreshed manifest hashes/generated context.

## Pass 2 entry recommendation

Proceed only with a constrained first slice after a human approves the capability assessments used by the fixture. That slice may compose legal owned loadouts, enforce backpack/slot conflicts, and explain choices using explicit normalized facts plus curated tags.

Keep Warbond “unlock next,” attachment progression/effects, enemy-driven scoring outside that slice. Those are blocking data projects, not scoring-tuning tasks. Do not compensate with name parsing or prose inference inside recommendation code.
