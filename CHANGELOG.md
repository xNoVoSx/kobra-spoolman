# Changelog

All notable changes. Versions: **bridge** = ace-lane-bridge (also the repo tag),
**plugin** = Orca plugin "Kobra Spoolman". Plugin-only releases have no repo tag.
Changes to the Orca patches and build: [orca-kobra CHANGELOG](https://github.com/xNoVoSx/orca-kobra/blob/main/CHANGELOG.md). Format based on [Keep a Changelog](https://keepachangelog.com/).

## [Unreleased]

## [2.5.0] – 2026-10-01

### Added
- Bridge: **ACE dryer** — humidity, temperature and dryer state (from GoKlipper's `filament_hub`,
  in the existing subscription), start/stop by hand and an automation (start above / stop below a
  humidity, max. time, pause, optionally while printing). The temperature never exceeds what the most
  sensitive loaded filament allows (new Spoolman field *Trocknen max.*, else template, else a
  cautious default per material) or what the ACE can do; loading a more sensitive spool while drying
  lowers it at once. On the slot page and in the Android app.

## [2.4.0] – 2026-09-30

Ships plugin 0.3.4. The Android app is a preview (debug APK from CI), not part of this release.

### Added
- Android app (in development, `android/`): slots with printer status and active slot, spool card
  with actions, NFC scan → spool, new spool from an existing filament with the scanned tag,
  settings. Debug builds have virtual tags for the emulator. See [android/README.md](android/README.md).
- Android app: create filaments on the phone (wizard with all Orca fields, template values as
  placeholders only, copy a product line for a new colour, new vendors).
- Android app: write ACE-compatible NFC tags (own encoder, verified byte for byte against an
  original Anycubic tag), link them to the spool; original Anycubic tags are recognised as
  write-protected.
- CI: builds and tests the Android app; the debug APK is attached to every run.

### Added
- Bridge: API for the Android app (`/api/app/…`, [reference](docs/api.md#android-app)): printer status
  with active slot, catalog (vendors, templates, filaments, extra fields with Orca keys, Orca base
  profiles), create vendors/filaments/spools, copy a product line in a new colour, move/archive
  spools, reserve tag numbers and link NFC tags. Writing needs `APP_TOKEN`. Only fields the user sets
  are stored — template values are never copied into a filament.
- Bridge: creates the spool extra fields `nfc_uid` and `tag_nr` in Spoolman when first needed
  (also in `spoolman_setup.py`).
- Plugin 0.3.4: reports the names of Orca's filament base profiles to the bridge, so the app can
  offer them as a list.

## [2.3.0] – 2026-09-30

Ships plugin 0.3.3.

### Added
- Bridge: loaded slots without material at the printer get a hint on the slot page and in
  `/api/orca/state` — a print using such a slot fails at the start
  (`index out of range [0] with length 0`, see [findings](docs/findings.md#print-start-and-ace-slot-info-2026-09-30)).
- Bridge: assigning a spool on the slot page gives its material and colour from Spoolman to the ACE
  via Rinkhals' `MMU_GATE_MAP` — spools without an Anycubic tag no longer need to be entered at the
  printer's display. Only the assignment triggers it (once, after the spool is loaded, never while
  printing); restarts, display entries and Spoolman changes never overwrite a slot. Slots with an
  RFID tag (`gate_spool_id` set) are never written — the tag decides. Tested on the printer; `SET_ACE_SLOT_INFO=false` turns it off.
- Plugin 0.3.3: the slot card and the usage preview warn when a slot has no material at the printer
  (*Druck bricht ab*); the warning after slicing includes it.

## [2.2.2] – 2026-09-30

Ships plugin 0.3.2 (see below).

### Fixed
- Bridge: the filament colour is sent as `default_filament_colour` instead of `filament_colour`.
  Orca drops `filament_colour` from filament presets (log: *"incorrect keys: filament_colour, which
  were removed"*) and takes the colour of a manually selected preset from `default_filament_colour`.
  Back-sync (`POST /api/orca/backsync`) accepts both keys and writes them to `color_hex`.

### Changed
- Docs: Rinkhals links point to [rinkhals-community/Rinkhals](https://github.com/rinkhals-community/Rinkhals),
  where development continues. The installation guide links to the new orca-kobra installation
  guide for launcher details.
- Docs: [findings](docs/findings.md) on the firmware purge — measured purge per colour change and
  how AnycubicSlicer passes its flush matrix in the G-code header (`project_info`).

## plugin 0.3.2 – 2026-09-30

Works with bridge 2.2.1 and newer.

### Fixed
- Plugin 0.3.2: profiles carry the Spoolman colour as `default_filament_colour`, so a manually
  selected `SM…` profile shows the right colour. A `filament_colour` from an older bridge is
  written as `default_filament_colour`; `filament_colour` never ends up in a profile.
  Existing profiles are rewritten on the next profile update.

### Changed
- Panel button *Profile synchronisieren* is now **Profile aktualisieren** (menu action and
  settings accordingly); a hint below it says that the profiles only get into Orca's filament
  slots via Orca's sync icon. The panel's refresh button is now *Neu laden* (reload) to tell the two apart.

## plugin 0.3.1 – 2026-09-25

Bridge unchanged (2.2.1). Needs orca-kobra build `kobra-20260924-2257-87a5d20` or newer for the
exact per-filament loads.

### Fixed
- Plugin 0.3.1: the usage preview now shows the **same numbers as Orca's preview legend**
  (model, support, flush, tower, total). 0.3.0 used Orca's `total_volumes_per_extruder`, which
  attributes the prime tower differently at tool changes, so single filaments were off by up to ~1 g.
- Firmware purge ("Laden") uses the **real number of loads per filament** counted by Orca
  (orca-kobra patch 0003, updated) instead of spreading all filament changes evenly over the slots.
  Older builds keep the even split and the panel says so.

### Changed
- Usage preview is a compact block at the top of the panel (*Geplanter Verbrauch*: need / remaining
  per slot, ✓ ⚠ ✗); the breakdown with Orca's column names sits under *Details*. The duplicate
  line in each slot card is gone.

## plugin 0.3.0 – 2026-09-24

Bridge unchanged (2.2.1).

### Added
- Plugin 0.3.0: **usage preview after slicing**. Per slot the panel shows what the sliced plate
  needs — Orca's statistics (model, support, prime tower, flush) plus the firmware purge per load
  measured by the bridge — next to the spool's remaining weight, marked *reicht* / *knapp* /
  *reicht nicht*. If a spool is too short, Orca shows a warning notification.
  Needs `orca.host.slice_statistics` from orca-kobra patch 0003; without it only the preview is missing.
- Plugin settings: reserve in grams (threshold for *knapp*), warn after slicing on/off.
- Tests for the preview calculation.

### Decided
- Reloading profiles without restarting Orca is **deferred**: Orca skips presets it already
  knows, so a clean reload means removing and reloading all user presets, which can reset the
  selected printer. See [findings](docs/findings.md#orcaslicer-plugin-api-250-dev-commit-9859d788).

## [2.2.1] – 2026-09-24

First public release of the repository.

### Added
- Repository with bridge, Orca plugin, Spoolman setup script, English and German documentation.
- Docker image `ghcr.io/xnovosx/ace-lane-bridge` (amd64/arm64), CI, release workflow.
- Test suite: replay of a real two-colour print through the consumption tracker, restart and
  outage scenarios, Orca profile mapping, back-sync, plugin profile builder.
- Plugin 0.2.0: settings page (bridge address, user folder, options) in Orca's Plugins dialog;
  hint in the panel when the bridge is unreachable.

### Changed
- Bridge: `MOONRAKER_URL` is required (no hard-coded address anymore).
- Plugin: default bridge address `http://localhost:7913` — set yours in the plugin settings.
- `spoolman_setup.py`: default URL from `SPOOLMAN_URL` or `http://localhost:7912`.

## [2.2.0] – 2026-09-24 · plugin 0.1.0–0.1.2

### Added
- Orca profile API: values per filament (`/api/orca/profiles`), panel state (`/api/orca/state`),
  back-sync (`/api/orca/backsync`), reset to template (`/api/orca/reset`).
- Orca plugin "Kobra Spoolman": profiles from Spoolman, side panel, slot check, back-sync with confirmation.
- Plugin 0.1.1: panel reliably opens at Orca start. 0.1.2: base profiles are also found inside the AppImage.

## [2.1.1] – 2026-09-24

### Added
- Slot page footer (version, uptime, links) and info dialog with all settings and connections.

## [2.1.0] – 2026-09-24

### Added
- Consumption per slot measured from `filament_used` and booked into Spoolman (at colour changes,
  every 5 min, at the end), restart-safe state and journal, open items, target comparison with the
  G-code header, print history, purge statistics.
- Warning if Moonraker or the firmware would book into Spoolman as well.

### Changed
- Moonraker updates are reduced to fields that actually changed (the ACE sends the full `mmu` object
  twice per second); telemetry shrinks from ~25 MB to ~1 MB per print.

## [2.0.1] – 2026-09-24

### Fixed
- "passt zur ACE" checks material **and** colour, with the same rule as the slot hints.

### Changed
- A filament's own Orca base profile replaces the template completely.

## [2.0.0] – 2026-09-24

### Added
- Rewrite: Moonraker WebSocket, Spoolman connection, slot assignment via mobile page, `lane_data`, telemetry.
