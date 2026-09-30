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

## Firmware purge per filament change (2026-09-25)

### Measured (Orca G-code, no purge data in the header)

Two-colour print `color_PLA_0.2_2h55m` (white PLA slot 2, black PLA slot 4), 36 loads, measured by
the bridge per load (1.75 mm filament, 2.405 mm²/mm):

| Change | Loads | Purge per load | Orca's matrix (× 0.3 multiplier) |
|---|---|---|---|
| black → white | 17 | **364 mm** ≈ 875 mm³ | 165 mm³ |
| white → black | 18 | **106 mm** ≈ 255 mm³ | 41 mm³ |

- The purge depends strongly on the colour pair; one average per load (227 mm) spreads it wrongly
  over the slots (the plugin's usage preview does exactly that).
- The firmware purged roughly 5× Orca's matrix, i.e. it did not use Orca's values.
- Both values fit "≈ 50 mm³ fixed + 1.5 × Anycubic's default matrix" (551 / 137 mm³, see below) —
  only two points, not proven.
- The bridge's booking is not affected: the counter includes the purge and it is attributed to the
  slot that is active while purging.

### How AnycubicSlicer hands over the purge (G-code analysis)

Same plate sliced three times in AnycubicSlicerNext 1.3.9.4 (203 changes): default matrix,
re-calculated matrix (every value +36 mm³), and with *all* flushing auto-calculation disabled in
the preferences.

- At every change the only active command is `T<n>`. The whole block between `; FLUSH_START` and
  `; FLUSH_END` is commented out (`;;; …`), including `;;; M400 P54918 ; =183.06*300`, which only
  feeds the time estimate (its values do not match the matrix). Orca's G-code has the same block.
- AnycubicSlicer writes these lines into the G-code **header** (`HEADER_BLOCK`); Orca writes none
  of them (its matrix only appears in the config comments at the end of the file):
  ```
  ; paint_info = [{"material_type":"PLA","paint_color":[239,240,241],"paint_index":1},{"material_type":"PLA","paint_color":[33,39,33],"paint_index":3}]
  ; project_info = {"flush_multiplier":1.0,"flush_volumes_chan_multipliers":[1.0,1.0,1.0,1.0],"flush_volumes_matrix":[0.0,372.0,183.0,183.0,197.0,0.0,137.0,137.0,492.0,551.0,0.0,131.0,492.0,551.0,131.0,0.0],"flush_volumes_vector":[140.0,140.0,140.0,140.0,140.0,140.0,140.0,140.0]}
  ; flush_multiplier_calculate_by_acnext: 1
  ```
  `flush_volumes_matrix` is row-major, `from * 4 + to` (mm³); `paint_index` is 0-based.
- Changing the matrix changes only `project_info` (plus prime tower travel and time estimates).
  Disabling auto-calculation only sets `flush_multiplier_calculate_by_acnext: 0`; `project_info`
  and `paint_info` are still written. The header is therefore the only place a purge volume can
  reach the printer.
- AnycubicSlicer includes the purge in its statistics ("Flushed", "Flush time"); Orca does not.

**Hypothesis:** the firmware reads `project_info` from the header and falls back to its own
calculation (from the colours the ACE reports) when it is missing — as with Orca.

### Test A/B (2026-09-30): the firmware ignores the header — hypothesis rejected

Same two-colour cube (15 × 15 × 13 mm, 13 slabs, 12 changes, 13 loads; PETG lavender slot 1 /
magenta slot 2), sliced in AnycubicSlicer with the flush matrix set to 100 (A) and 600 mm³ (B),
`project_info` present, auto-calculation off. Both files extrude **exactly the same real amount**
(1391 mm: model + tower); the matrix only changes the header (`filament_used`, `project_info`).

| Test | measured by the bridge | real G-code extrusion | firmware purge | per load |
|---|---|---|---|---|
| A (100 mm³) | 4062 mm | 1391 mm | 2671 mm | ≈ 205 mm |
| B (600 mm³) | 3842 mm | 1391 mm | 2451 mm | ≈ 189 mm |

With the header in use, B would have purged ≈ 208 mm (500 mm³) more per load. It did not.

Both A and B had `flush_multiplier_calculate_by_acnext: 0` (auto-calculation switched off in the
preferences). **Test B2** repeated B with the option *Calculate flushing volume through Anycubic
Slicer Next* enabled (flag `1`, matrix still 600 by hand, identical real extrusion):
**≈ 215 mm per load** (slot 1: 231, slot 2: 200) — within the spread of A and B.

→ **The firmware computes the purge itself; the header is ignored, flag or not** (test C and an Orca
header patch are pointless). The Anycubic wiki's flushing settings apply to what AnycubicSlicer
computes and shows; for a print started via Moonraker/Rinkhals they do not reach the firmware.
Untested: printing directly from AnycubicSlicer (its print order might carry the values) — not
applicable to Orca, which always prints via Moonraker.
Per direction (A, B, B2): magenta → lavender 219–231 mm, lavender → magenta 163–200 mm per load.

Side effect: the header `filament_used` of AnycubicSlicer files contains the slicer's flush volume,
although no G-code extrudes it. The bridge's "overhead = measured − header target" is therefore
wrong for such files (test B: −345 mm) and pulls the average used by the plugin's usage preview down
(227 → 109 mm per load). Single-load prints (≈ 95 mm, first load only) lower it further.

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
- The Kobra's firmware purge does not appear in Orca's flush statistics (0 for this printer),
  see [Firmware purge per filament change](#firmware-purge-per-filament-change-2026-09-25).
- Printer agents get no file access to the temporary print 3MF → printing from a Python agent
  prompts on every print.
- Dock panels (`orca.host.ui.create_dock_panel`) are HTML with a message bridge and are safe to
  create from any thread — but are dropped silently if created before the main window exists.
- `PresetSaved` lifecycle event carries the preset name; the saved JSON is complete for base profiles.
- Filament colour: `filament_colour` is **not** a filament preset option (commented out in
  `s_Preset_filament_options`, `Preset.cpp`). Orca drops it on load with *"contains the following
  incorrect keys: filament_colour, which were removed"*. The preset's colour is
  `default_filament_colour`; selecting a filament preset manually takes the colour from there
  (`PresetComboBoxes.cpp`). The bridge therefore sends `default_filament_colour`, the plugin
  (0.3.2+) never writes `filament_colour`, and back-sync accepts both keys.

## Print start and ACE slot info (2026-09-30)

### Print fails with `runtime error: index out of range [0] with length 0`

Mainsail shows the error, the printer only *Druck fehlgeschlagen*, about 5 minutes after the start
(right after auto-levelling). Two attempts of the same two-colour PETG print failed like this; the
Moonraker log (`/server/files/logs/moonraker.log`, timestamps in UTC) shows why:

- Rinkhals does not start prints by G-code. `kobra.py` sends Anycubic's own print order over the
  printer's **internal MQTT broker** (`127.0.0.1:2883`, credentials from
  `/userdata/app/gk/config/device_account.json`, not reachable from outside).
- `mmu_ace.py:patch_print_data()` adds an `ams_box_mapping` built from the ACE gates. Slots 1 and 2
  (T0/T1, spools without RFID tag, nothing entered at the display) were sent as
  `"material_type": ""`, colour `[0, 0, 0, 255]`.
- GoKlipper (Go) looks up the material of the mapped slots and panics on the empty entry.
  After entering PETG at the display the same file printed fine — the slot temperatures stayed at
  0, so **material (and colour) is what counts**.

The bridge therefore flags a loaded slot without material (slot page, Orca panel card, usage
preview after slicing: *Druck bricht ab*).

### Setting slot material/colour without the display: `MMU_GATE_MAP`

GoKlipper's own G-code list has no command for it, but Rinkhals' Moonraker component (`mmu_ace.py`)
intercepts Happy Hare's `MMU_GATE_MAP` and forwards material and colour to GoKlipper as
`filament_hub/set_filament_info` (`{"id": ace, "index": slot, "type": "PETG", "color": {"R", "G", "B"}}`):

```
MMU_GATE_MAP MAP="{0: {'status': 1, 'name': 'Sunlu PETG', 'material': 'PETG', 'color': '685BC7FF', 'temp': 245, 'spool_id': 8, 'speed_override': 100}}"
```

- Parsed with `shlex.split` and `ast.literal_eval`; colour is 8-digit hex RGBA without `#`.
- Refused by Rinkhals for slots with an RFID tag (`rfid == 2`); allowed for untagged slots (`rfid == 1`).
- Rinkhals rebuilds its gate list from GoKlipper's ACE status about every 20 s, so a value only
  sticks if GoKlipper accepts it. Rinkhals' own comment in `update_gate` ("only works if gate has
  RFID tag") suggested otherwise. **Tested on the printer (2026-09-30, Rinkhals 20260901_01,
  firmware 2.7.2.7):** slot 1 (untagged spool, PETG entered at the display) set to colour
  `00FF00FF` via the Mainsail console → the display showed the slot green at once, and
  `mmu.gate_color` still read `00FF00FF` 35 s later. GoKlipper keeps material and colour; the
  `name` is not stored (`gate_filament_name` stays the material).
- Tagged slots: Rinkhals does not expose the internal `rfid` flag, but `mmu.gate_spool_id` is only
  set with a tag (Anycubic tags `102`/`107`, untagged `0`) — the bridge uses it to leave tagged
  slots alone.
- The bridge sends it **only when a spool is assigned on the slot page** (`SET_ACE_SLOT_INFO`,
  default on) — once per assignment, after the spool is loaded and never while printing; skipped
  when the ACE already reports exactly these values. A bridge restart, an entry at the display or a
  change in Spoolman never overwrites the slot; to push again, assign the spool again.
- Alternative not needed: Anycubic's LAN mode exposes the same function over TLS MQTT (port 9883,
  signed handshake, `multiColorBox` / `setInfo`, documented by
  [anycubic-lan](https://github.com/Nino6689/anycubic-lan)). It would be a second client with its
  own credentials; `MMU_GATE_MAP` goes over the bridge's existing Moonraker connection.

## Android 17: local network protection (2026-09-30)

Apps targeting Android 17 (API 37) cannot reach the local network (10.0.0.0/8, 192.168.0.0/16, …,
including the emulator's `10.0.2.2`) unless they hold the runtime permission
`ACCESS_LOCAL_NETWORK` (group *Nearby devices*). Blocked TCP connections do not fail — they hang
until the timeout ([docs](https://developer.android.com/privacy-and-security/local-network-permission)).
The app declares the permission, requests it on first start and shows a hint while it is missing.

## Anycubic RFID tags

Page layout (4 bytes per page), verified against a memory dump of an original tag (Anycubic PETG
black, NTAG213, read with NFC Tools; `android/app/src/test/resources/`) and cross-checked with
[ACE-RFID](https://github.com/DnG-Crafts/ACE-RFID). The app's own encoder reproduces pages 4–31 of
that tag byte for byte (`AceTagTest`).

| Page | Content | Original tag |
|---|---|---|
| 4 | header | `7B 00 65 00` |
| 5–9 | SKU, ASCII | `AHPEBK-102` → ACE reports `gate_spool_id` 102 |
| 10–14 | brand, ASCII | `AC` (Anycubic) |
| 15–19 | material, ASCII | `PETG` |
| 20 | colour, alpha + B G R | `FF 21 27 21` = #212721; confirmed with PLA Silk green: `FF BC D2 52` = #52D2BC |
| 23 | speed min/max, uint16 LE | 50 / 200 (not written by ACE-RFID) |
| 24 | nozzle min/max °C | 230 / 250 (= what the ACE reports for the slot) |
| 29 | bed min/max °C | 60 / 70 |
| 30 | diameter ×100, length m | 175 / 320 |
| 31 | weight g | 1000 |
| 41–42 | NTAG213 CFG | `AUTH0 = 04`, `ACCESS = 47`: password-protected **writes** from page 4 → original tags can be read, not rewritten |

- The number after the SKU's dash is **not** unique: PETG black (`AHPEBK-102`) and PLA Silk green
  (`AHSCGR-102`) both end in 102. Self-written tags use a unique number per spool instead.
- Pure black is written as `010101` (as ACE-RFID does); `000000` probably reads as "no colour".
- The app writes pages 4–31 (all others zero), reads them back to verify, then links the tag's UID
  to the spool. The tag number comes from the bridge (`POST /api/app/tag/issue`).
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
