# Findings

[Back to README](../README.md)

What we measured and learned while building this (Kobra S1, ACE 2 Pro, Rinkhals 20260901_01 on
firmware 2.7.2.7, OrcaSlicer 2.5.0-dev, Spoolman 0.26.1, September 2026).

## Consumption measurement (test print, 2026-09-24)

Two-colour print, printed *by object*: four blades in slot 2 (white PLA), then a handle in slot 1
(green silk PLA). Recording: [`tests/data/blade_print_2026-09-24.jsonl.gz`](../tests/data/).

| Phase | `filament_used` |
|---|---|
| Load slot 2 + start purge (before layer 1) | 0 → 449 mm (steps of 10 mm) |
| Blades printed | 449 → 3108 mm (**2659 mm**, Orca: 2660) |
| Retract before cut, slot 2 unloaded | → 3055 mm (−53 mm) |
| Slot 1 loaded, re-prime + purge | → 3250 mm (+50 +145) |
| Handle printed | 3250 → 8079 mm (**4829 mm**, Orca: 4830) |
| Final retract / unload | → 8025 mm |

**Result:** the counter includes the firmware purge and matches Orca's model lengths within 1 mm.
Counting only positive deltas would over-count by ~2.3 % (retract + re-extrude counted twice).

## Rinkhals / ACE quirks

- `mmu` is sent **in full** with every update (~2 per second); only a few fields actually change.
  The bridge filters unchanged fields at the source.
- The active slot is `gate_status == -1`. During loading/unloading the ACE briefly reports no active
  slot (up to ~2 s) and `gate` flickers.
- `virtual_sdcard.filament_used` holds the G-code header per filament, labelled `m` but containing
  **cm³** (11.61 cm³ = 4.83 m at 1.75 mm). `filament_used_g` holds grams. Both are cleared once the
  print really starts.
- `gate_spool_id` is **not** a unique chip ID: four different spools reported `[102, 107, 102, 107]`.
  It is the number after the dash in the tag's SKU (e.g. `AHPEBK-102` → 102), i.e. a product
  number shared by all spools of that product. The tag UID is not exposed.
- `gate_filament_name` appears to come from an Anycubic lookup table (sometimes only the material).
- The firmware's own Spoolman support reports `spoolman_support: off` — keep it that way.
- Preparation before layer 1 (homing, levelling, heating) took ~16 min vs. 2 min estimated by Orca.

## OrcaSlicer plugin API (2.5.0-dev, commit 9859d788)

- Presets are **read-only** for plugins; new profiles must be written as JSON files and appear
  after a restart (no reload call exposed).
- A reload patch was evaluated and deferred: `PresetCollection::load_presets` skips every name it
  already knows ("Preset already present, not loading"), so changed profiles are only picked up by
  removing and reloading *all* user presets (`remove_user_presets()` + `load_user_presets()` + UI
  refresh). That path can reset the selected user printer — too invasive for a carried patch.
- The plugin sandbox denies any path component containing `conf`, which includes Linux's
  `~/.config` data folder — fixed by patch 0002 in [orca-kobra](https://github.com/xNoVoSx/orca-kobra).
- No API for per-filament usage after slicing (only the G-code / 3MF contain it) → patch 0003 adds
  `orca.host.slice_statistics()` (read-only, from `GCodeProcessorResult::print_statistics`).
- `SlicingJobComplete` is dispatched synchronously on the UI thread **before** the plate's
  `slice_result_valid` flag is set; a handler of that event must read the result with
  `require_valid=False` (the flag is set right after the event returns).
- `total_filament_changes` counts changes only (not the first load): loads = changes + 1.
- The Kobra's firmware purge does not appear in Orca's flush statistics (0 for this printer).
- Printer agents get no file access to the temporary print 3MF → printing from a Python agent
  prompts on every print.
- Dock panels (`orca.host.ui.create_dock_panel`) are HTML with a message bridge and are safe to
  create from any thread — but are dropped silently if created before the main window exists.
- `PresetSaved` lifecycle event carries the preset name; the saved JSON is complete for base profiles.

## Anycubic RFID tags

- Tag fields per [ACE-RFID](https://github.com/DnG-Crafts/ACE-RFID): SKU (pages 5–8), brand (10–13),
  material (15–18), colour ABGR (20), temperatures, diameter/length.
- Open question for stage 4: which field (if any) the ACE passes through unchanged, so a custom ID
  written into a tag can be recognised. Planned test with an empty Anycubic spool:
  1. Read the tag with the ACE-RFID app and save the values.
  2. Change only the brand to `TEST42` and write it (a write error means the tag is locked).
  3. Load it and query `mmu`: where does `TEST42` show up, do material and colour stay?
  4. Then change the SKU slightly and watch `gate_spool_id` (careful: the ACE validates the SKU).
     Concretely: write SKU `AHPEBK-4711` to a sticker tag and check whether `gate_spool_id` becomes 4711.
- Original Anycubic tags are write-protected; the ACE-RFID app can read but not rewrite them.
- Colour is stored as ARGB on the tag; the ACE reports it as RGBA. Brand code `AC` = Anycubic.
- Fallback if nothing passes through: scan the tag with the phone (UID) right before loading;
  the bridge assigns the spool to the slot that gets occupied next, with the ACE's material and
  colour as a cross-check.
