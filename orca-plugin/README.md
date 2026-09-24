# Kobra Spoolman (OrcaSlicer plugin)

Makes Spoolman the source for OrcaSlicer filament profiles.

- Creates one **user base profile per Spoolman filament** with an active spool, named
  `Vendor Name (SM000010)`, `filament_id = SM000010`. Values: Orca base profile (resolved from Orca's
  own system profiles) + template + filament fields + overrides, provided by the
  [ace-lane-bridge](../bridge/).
- **Side panel**: slots with spool, remaining weight, consumption, and a check that filament 1–4 in
  Orca match slots 1–4.
- **Back-sync**: saving an `SM…` profile in Orca asks whether the changes should go to Spoolman.
- Removes profiles of filaments without an active spool (only its own, marked in `filament_notes`).

Requirements: OrcaSlicer with the Python plugin system (2.5.0-dev). Automatic profile selection with
Orca's sync button needs the [orca-kobra](https://github.com/xNoVoSx/orca-kobra) build.

## Install

```bash
mkdir -p ~/.config/OrcaSlicer/orca_plugins/kobra_spoolman
cp kobra_spoolman.py ~/.config/OrcaSlicer/orca_plugins/kobra_spoolman/
```

Enable it in Orca's **Plugins** dialog, set the bridge address in its **Configuration** tab,
restart Orca once. Menu actions: *Kobra Spoolman* (open panel) and
*Kobra Spoolman: Profile synchronisieren*.

Notes:

- Orca reads profiles only at start-up — new or changed profiles need a restart (the panel tells you).
- Network and file work happen in a background thread; Orca objects are only read on the UI thread.
- Logs: `~/.config/OrcaSlicer/log/python_*.log` (`[kobra-spoolman]`).
