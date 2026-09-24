# Changelog

All notable changes. Versions: **bridge** = ace-lane-bridge (also the repo tag),
**plugin** = Orca plugin "Kobra Spoolman". Plugin-only releases have no repo tag.
Changes to the Orca patches and build: [orca-kobra CHANGELOG](https://github.com/xNoVoSx/orca-kobra/blob/main/CHANGELOG.md). Format based on [Keep a Changelog](https://keepachangelog.com/).

## [Unreleased]

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
