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
  The tag UID is not exposed.
- `gate_filament_name` appears to come from an Anycubic lookup table (sometimes only the material).
- The firmware's own Spoolman support reports `spoolman_support: off` — keep it that way.
- Preparation before layer 1 (homing, levelling, heating) took ~16 min vs. 2 min estimated by Orca.

## OrcaSlicer plugin API (2.5.0-dev, commit 9859d788)

- Presets are **read-only** for plugins; new profiles must be written as JSON files and appear
  after a restart (no reload call exposed).
- The plugin sandbox denies any path component containing `conf`, which includes Linux's
  `~/.config` data folder — fixed by patch 0002 in [orca-kobra](https://github.com/xNoVoSx/orca-kobra).
- No API for per-filament usage after slicing (only the G-code / 3MF contain it).
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
- Fallback if nothing passes through: scan the tag with the phone (UID) right before loading;
  the bridge assigns the spool to the slot that gets occupied next, with the ACE's material and
  colour as a cross-check.
