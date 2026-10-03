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

(1391 mm was counted with the start sequence; the extrusion moves of the print itself are 1192 mm.
The per-load values here are averages including the first load — see the model below.)

With the header in use, B would have purged ≈ 208 mm (500 mm³) more per load. It did not.

Both A and B had `flush_multiplier_calculate_by_acnext: 0` (auto-calculation switched off in the
preferences). **Test B2** repeated B with the option *Calculate flushing volume through Anycubic
Slicer Next* enabled (flag `1`, matrix still 600 by hand, identical real extrusion):
**≈ 215 mm per load** (slot 1: 231, slot 2: 200) — within the spread of A and B.

→ **The firmware computes the purge itself; the header is ignored, flag or not** (test C and an Orca
header patch are pointless). The Anycubic wiki's flushing settings apply to what AnycubicSlicer
computes and shows; for a print started via Moonraker/Rinkhals they do not reach the firmware.
### Direct print from AnycubicSlicer (2026-10-01): the matrix is used

The same cube, matrix 600 by hand, multiplier 1.0, sent with AnycubicSlicer's *Print* button (LAN
mode) instead of exporting. AnycubicSlicer then uploads a **`.gcode.3mf` package** (Bambu format:
`Metadata/plate_1.gcode`, `project_settings.config` with `flush_volumes_matrix`, `slice_info.config`)
plus a `.acm` file (only the colour/slot mapping, the same as for Moonraker prints); the firmware
unpacks it to `.3mf_temp/`. The G-code inside extrudes exactly as much as test A's.

| slab | test A, via Moonraker (× 1.0) | direct print, matrix 600 (× 1.0) | difference | (600 − colour volume) / 2.405 |
|---|---|---|---|---|
| lavender (after magenta) | 229–230 mm | 318–321 mm | **+89.5 mm** | +91.1 mm |
| magenta (after lavender) | 205–208 mm | 326–329 mm | **+120 mm** | +119.8 mm |

→ **With the package the firmware uses the slicer's matrix; with a plain G-code file it ignores it**
and computes (Orca colour formula + 107) × multiplier. The print start itself is the same MQTT
message in both cases — Rinkhals sends Mainsail prints the same way (`mqtt_print_file` in Rinkhals'
`kobra.py`, filename + `ams_box_mapping`, no flush fields) — so the package is the switch.

Not pursued: making Orca produce and start such a package (an exported *plate sliced file*, or the
bridge wrapping the G-code). Decision: keep the firmware's own calculation, set the multiplier to
1.0 (≈ 28 % less purge than 1.5) and *predict* the purge per transition instead.

### The firmware's own flush setting

GoKlipper keeps its own ACE flush configuration, readable at `GET /printer/filament_hub/get_config`
(Moonraker port; writable via `set_config`, used by Rinkhals' `SET_ACE_FLUSH_MULTIPLIER` /
`ACE_FLUSH_MINIMAL|NORMAL|MAXIMUM`):

```json
{"auto_refill": 1, "flush_multiplier": 1.5, "flush_multiplier_editable": 1,
 "flush_volume_max": 800, "flush_volume_min": 107, "runout_detect": 1}
```

The multiplier is the value shown/editable on the printer's display. Model: the firmware computes
the flush per colour pair itself (AnycubicSlicer's colour algorithm), multiplies by
`flush_multiplier` and clamps to `flush_volume_min..max` (mm³). It fits all measurements within
≈ 10–30 mm (a fixed part per load):

| change | AnycubicSlicer auto | × 1.5 (clamped) | ≈ mm filament | measured |
|---|---|---|---|---|
| lavender → magenta | 312 mm³ | 468 mm³ | 195 | 163–200 |
| magenta → lavender | 381 mm³ | 572 mm³ | 238 | 219–231 |
| black → white | 551 mm³ | 800 mm³ (826) | 333 | 364 |
| white → black | 137 mm³ | 205 mm³ | 85 | 106 |

**Confirmed (2026-10-01):** test A printed again with the multiplier set to 1.0 at the display.
Same G-code, so the model part of each of the 13 slabs is identical — the difference per slab is
purge only. Steady slabs (4–13) are constant to ±1 mm:

| change | × 1.5 slab | × 1.0 slab | measured difference | model: colour volume × 0.5 / 2.405 |
|---|---|---|---|---|
| lavender → magenta | 271–274 mm | 205–208 mm | **66 mm** | 64.9 mm (312 mm³) |
| magenta → lavender | 307–308 mm | 229–230 mm | **78 mm** | 79.2 mm (381 mm³) |

Total: 4064 mm → 2946 mm (−28 %).

**The colour volume is Orca's own formula + 107 mm³.** Orca's `FlushVolCalculator::calc_flush_vol`
(`src/libslic3r/FlushVolCalc.cpp`, inherited from Bambu Studio: HSV distance + luminance, 60 mm³
floor) gives 205 / 274 mm³ for lavender ↔ magenta and 480 / 67 mm³ for black ↔ white
(`#212721` / `#EFF0F1`); adding `flush_volume_min` = 107 gives exactly AnycubicSlicer's automatic
values 312 / 381 and 587 / 173. (One older black/white export shows 551 / 137 — a different
minimum was set in that slicer project.)

**Absolute values from an Orca print.** Orca writes a clean per-filament target into the G-code
header, so *measured − target* is the firmware purge alone. The black/white print of 2026-09-24
(`color_PLA_0.2_2h55m`, multiplier 1.5, first load green, then 1 × green → black, 17 × black →
white, 17 × white → black):

| slot | measured − target | model: Σ colour volume × 1.5 / 2.405 | difference per load |
|---|---|---|---|
| white (17 × black → white) | 6186 mm (363.9 per load) | 6231 mm (366.5 per load) | −2.6 mm |
| black (17 × white → black, 1 × green → black) | 1907 mm | 1980 mm | −4.0 mm |
| green (first load of the print) | 94.6 mm | — | — |

Black → white is 882 mm³ after the multiplier and is **not** capped at 800: the firmware's limits
apply to the colour volume *before* the multiplier. With these numbers the cube tests are
consistent as well — test A and the direct print give the same model part per slab (lavender
75 / 73 mm, magenta 80.3 / 80.2 mm), and the purge totals fit the real G-code extrusion (1192 mm).

→ **purge per change ≈ clamp(orca_colour_volume + 107, 107, 800) × flush_multiplier / 2.405 − ≈ 3 mm,
first load of a print ≈ 95 mm.** Colours are the ones the ACE reports for the slots (the firmware
uses them in `ams_box_mapping`). The firmware values (`flush_multiplier`, `flush_volume_min`,
`flush_volume_max`) are readable at `/printer/filament_hub/get_config`.

Consequences:
- The bridge's bookings were already right (it measures; purge lands on the newly loaded spool).
- The usage preview can compute the purge per transition from the slot colours; the bridge can
  refine the small offset and the first load from finished Orca prints.

[Kobra-S1/ACEPRO](https://github.com/Kobra-S1/ACEPRO) (vanilla Klipper replacing the stock
firmware — not compatible with Rinkhals) converts Orca's flush matrix into a purge length per change,
the same per-transition idea.
Per direction (A, B, B2, slab totals including the model part): magenta → lavender 219–231 mm,
lavender → magenta 163–200 mm per load.

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

The bridge therefore flags a loaded slot without material (web UI, Orca panel card, usage
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
- The bridge sends it **only when a spool is assigned in the web UI or app** (`SET_ACE_SLOT_INFO`,
  default on) — once per assignment, after the spool is loaded and never while printing; skipped
  when the ACE already reports exactly these values. A bridge restart, an entry at the display or a
  change in Spoolman never overwrites the slot; to push again, assign the spool again.
- Alternative not needed: Anycubic's LAN mode exposes the same function over TLS MQTT (port 9883,
  signed handshake, `multiColorBox` / `setInfo`, documented by
  [anycubic-lan](https://github.com/Nino6689/anycubic-lan)). It would be a second client with its
  own credentials; `MMU_GATE_MAP` goes over the bridge's existing Moonraker connection.

## ACE status and dryer (`filament_hub`)

GoKlipper's object `filament_hub` (queryable/subscribable via Moonraker, not listed in
`printer/objects/list`) carries the raw ACE state, updated about every 20 s:

```json
{"filament_hubs": [{"id": 0, "status": "ready", "temp": 33, "humidity": 24,
  "filament_model": "Anycubic Color Engine Pro 2.0", "enable_rfid": 1,
  "dryer_status": {"status": "stop", "target_temp": 0, "duration": 0, "remain_time": 0},
  "slots": [{"index": 0, "status": "ready", "type": "PETG", "rfid": 1}, …]}]}
```

- `rfid` per slot: 1 = no tag, 2 = tag (more reliable than `gate_spool_id > 0`).
- Rinkhals' `mmu` view reports `dryer_humidity`/`dryer_remaining` as 0: it reads `humidity` inside
  `dryer_status` and `remaining_time` instead of the hub's `humidity` and `remain_time`.
- `dryer_status.duration` is in **minutes**, `remain_time` in **seconds** (2026-10-02: `duration 360`,
  `remain_time 21540` right after the start). `temp` is the current air temperature in the ACE,
  `target_temp` the set point.
- Dryer commands (Rinkhals): `MMU_DRYER_START UNIT=0 DURATION=<min> TEMP=<°C> [FAN_SPEED=…]`,
  `MMU_DRYER_STOP UNIT=0`. ACE 2 Pro dries up to 65 °C (Anycubic), the first ACE Pro up to 55 °C.

## Printer objects on the Kobra S1 (GoKlipper, 2026-10-01)

`printer/objects/list` offers `extruder`, `heater_bed`, `fan` (part cooling, with `rpm`),
`fan_generic box_fan`, `fan_generic air_filter_fan`, `gcode_move` (with an extra `speed_mode`,
Anycubic's speed preset — values not yet mapped), `toolhead`, `print_stats` (`info.current_layer`/
`total_layer`), `pause_resume`, `idle_timeout`, `exclude_object`, `bed_mesh`. There is **no chamber
temperature sensor**; `motion_report` and `display_status` are empty. Temperatures come as whole
numbers. Field lists in `objects/query`/`subscribe` are honoured, which keeps the bridge's
subscription small.

## Camera load on the Kobra S1 (2026-10-01)

Measured with Moonraker's `machine/proc_stats` (system CPU, single core), Rinkhals' mjpg-streamer at
1280×720, printer idle, nothing else watching:

| Running | Printer CPU |
|---|---|
| nothing | 30–50 % |
| single snapshots (`?action=snapshot`) at 1, 2, 4 and ~5 per second | 30–50 % — no difference |
| **one** MJPEG stream (`?action=stream`, ~15 fps × ~230 KB) | **100 %**, Moonraker answers take 1–6 s |

Fetching an image is cheap; the stream mode is what costs. Mainsail's default webcam on Rinkhals uses
the *mjpegstreamer-adaptive* service, which polls snapshots — that is why Mainsail alone does not load
the printer like this. Since bridge 2.10.1 the bridge polls snapshots too and adapts the rate to the
printer CPU (`notify_proc_stat_update`).

## What loads the printer CPU (2026-10-02)

`top` on the Kobra S1 during a print (single core, load average 13, 8 MB free memory):

| Process | CPU |
|---|---|
| `moonraker_octoapp` (OctoApp companion, a Rinkhals app) | **64 %** |
| `gklib` (GoKlipper, the print itself) | 21 % |
| Moonraker, mjpg-streamer, display, VNC, bridge requests | ≈ 0 % |

After disabling the companion at the printer display (Rinkhals → Apps) the CPU dropped from 100 % to
40–55 % during the same print, free memory rose from 72 to 85 MB. Per the Rinkhals FAQ the
companion is not needed for OctoApp itself — it only provides live notifications. The bridge's camera
(snapshot polling, adapted to the CPU) did not show up in `top` at all.

## Print control on GoKlipper (2026-10-01)

Checked on the idle printer (each set and reset): `M220 S…` → `gcode_move.speed_factor`, `M221 S…` →
`extrude_factor`, `M106 S0–255` → `fan.speed`, `SET_FAN_SPEED FAN=box_fan|air_filter_fan SPEED=0–1` →
`fan_generic …`, `M104 S…` / `M140 S…` → heater targets. From Rinkhals' `kobra.py`: `CANCEL_PRINT` is
redirected to Anycubic's MQTT stop for MQTT prints; `FIRMWARE_RESTART`/`RESTART` are refused (GoKlipper
deadlocks, issue #32), so an emergency stop needs a power cycle. Pause/resume (GoKlipper macros) not
yet tested during a real print.

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
- **Confirmed 2026-10-02 (ACE 2 Pro):** a blank NTAG215 sticker written by the app with SKU
  `AHPEBK-34532` (PETG, `#685BC7`, 250 °C) is read by the ACE: `mmu.gate_spool_id` = **34532**,
  material, colour (byte order correct) and nozzle temperature come from the tag. About 45 s after
  inserting, the gate first reports empty data while loading, then the tag values. The ACE reports
  the vendor as `Anycubic` although the tag says `Sunlu` — the brand field is not passed through. So
  the tag number is a usable spool ID: the bridge can recognise a spool by `gate_spool_id`.
- The ACE 2 Pro reads only the spool side facing its reader, so each spool gets two stickers with the
  same content (one per side).
- Original Anycubic tags are write-protected; the ACE-RFID app can read but not rewrite them.
- Colour is stored as ARGB on the tag; the ACE reports it as RGBA. Brand code `AC` = Anycubic.
- Fallback if nothing passes through: scan the tag with the phone (UID) right before loading;
  the bridge assigns the spool to the slot that gets occupied next, with the ACE's material and
  colour as a cross-check.

## AI print-failure detection (2026-10-03)

- Obico's failure model as ONNX (192 MB, input 416×416, outputs boxes `[1, 845, 1, 4]` and
  confidences `[1, 845, 1]`) needs **~50 ms per picture with 2 threads** on the CPU (Ryzen 7 9800X3D,
  ONNX Runtime 1.30; 19 ms with all cores). At one picture every 10 s a GPU is not needed.
- A clean Kobra S1 camera frame gives no box at all (sum 0.00); real spaghetti photos 1.35–5.23,
  spaghetti composited into a Kobra frame 1.97 — Obico's "definitely failing" threshold is 0.78.
  Spaghetti drawn as flat coloured lines gives only 0.25: the model reacts to real 3-D tangles.
- With Obico's judging (EWM against a baseline, 30 safe pictures) a sudden failure after a clean start
  is *verdächtig* after 2 and *Fehldruck* after 4 pictures; a constant pattern never alarms.
- `camera.snapshot()` keeps the restream pump running for 20 s at up to 10 fps — the AI therefore uses
  `camera.still()`: newest frame or one single snapshot.
- Android sets a notification channel's `USAGE_ALARM` back to `USAGE_NOTIFICATION` (checked on the
  Android 17 emulator), so alarm notifications follow the notification volume.
- Obico's baseline (`long`) absorbs a failure that keeps going: after ~21,000 spaghetti pictures in the
  demo it stood at 1.96 and the AI stayed silent. The bridge therefore freezes the baseline while an
  alarm is open.
- Suspicious pictures saved at every check filled 4.8 GB in one unattended demo print (2 s interval) —
  now at most one every 30 s.

## Print preparation on the Kobra S1 (recording 2026-10-03)

- The nozzle target goes 0 → 205 °C (heating ~76 s from room temperature), then 140 °C for probing, then
  back to 205 or up to 250 °C (33–70 s each) — all in layer 0. An alarm on "more than 15 °C below
  target for 30 s" fired five times in one preparation.
- GoKlipper reports `print_stats.state = error` for under a second during the preparation (twice in one
  print) and continues printing.

