# Installation

[Deutsch](de/installation.md) · [Back to README](../README.md)

This guide takes you from zero to the full workflow. Allow about an hour — most of it is the
first OrcaSlicer build, which GitHub does for you.

**Overview**

1. [Printer: Rinkhals and Moonraker](#1-printer-rinkhals-and-moonraker)
2. [Spoolman and its extra fields](#2-spoolman-and-its-extra-fields)
3. [ace-lane-bridge](#3-ace-lane-bridge)
4. [OrcaSlicer (orca-kobra build)](#4-orcaslicer-orca-kobra-build)
5. [Orca plugin "Kobra Spoolman"](#5-orca-plugin-kobra-spoolman)
6. [Check that everything works](#6-check-that-everything-works)

---

## 1. Printer: Rinkhals and Moonraker

- Install [Rinkhals](https://github.com/jbatonnet/Rinkhals) on the Kobra S1. Moonraker must be
  reachable at `http://<printer-ip>:7125` (try `http://<printer-ip>:7125/server/info` in a browser).
- **Moonraker's own Spoolman integration must stay off** (no `[spoolman]` section in
  `moonraker.conf`), otherwise consumption is booked twice. The bridge warns you if it is on.
- Give the printer a fixed IP address (DHCP reservation) — everything else points at it.

## 2. Spoolman and its extra fields

Spoolman 0.26 or newer. If you do not run it yet, put it into the same stack as the bridge
(see [bridge/compose.yaml](../bridge/compose.yaml)).

Then create the extra fields and material templates once:

```bash
python3 spoolman/spoolman_setup.py --url http://<spoolman-host>:7912 --dry-run   # show the plan
python3 spoolman/spoolman_setup.py --url http://<spoolman-host>:7912             # apply
```

The script only **creates** things; it never changes or deletes existing fields or filaments,
so running it again is harmless. It adds:

- **Filament fields** for every Orca filament setting you usually tune: first-layer and smooth-PEI
  temperatures, chamber, part fan min/max, fan off for the first layers, overhang fan, aux fan,
  air filtration and exhaust fan, flow ratio, pressure advance, max volumetric speed, retraction,
  Z-hop, a free *Orca overrides* field, plus *Orca base profile* and *Template*.
  Full list: [spoolman-fields.md](spoolman-fields.md).
- **Spool field** *NFC-Kennung* (used by stage 4).
- A vendor **"Vorlage"** with seven templates (PLA, PLA Silk, PETG, ASA, TPU, PLA-CF, PETG-CF),
  pre-filled from Orca's Generic profiles.

## 3. ace-lane-bridge

### Option A — Docker image (recommended)

Add the service to your stack (Portainer → Stacks, or `docker compose`):

```yaml
  ace-lane-bridge:
    image: ghcr.io/xnovosx/ace-lane-bridge:latest
    container_name: ace-lane-bridge
    restart: unless-stopped
    ports:
      - "7913:7913"
    volumes:
      - ./bridge-data:/data          # e.g. /docker/ace-lane-bridge/data
    environment:
      MOONRAKER_URL: "http://<printer-ip>:7125"
      SPOOLMAN_URL: "http://spoolman:8000"   # service name inside the same stack
      TZ: Europe/Berlin
    depends_on:
      - spoolman
```

### Option B — run from source

Useful while developing. Copy `bridge/app/` to the Docker host (e.g. `/docker/ace-lane-bridge/app`) and use:

```yaml
  ace-lane-bridge:
    image: python:3.12-slim
    container_name: ace-lane-bridge
    restart: unless-stopped
    entrypoint: ["sh", "/app/entrypoint.sh"]
    ports:
      - "7913:7913"
    volumes:
      - /docker/ace-lane-bridge/app:/app:ro
      - /docker/ace-lane-bridge/data:/data
    environment:
      MOONRAKER_URL: "http://<printer-ip>:7125"
      SPOOLMAN_URL: "http://spoolman:8000"
      TZ: Europe/Berlin
```

On first start the entrypoint creates a Python environment in `data/venv` (needs internet once).
Updating = copy the new `app/` folder and restart the container.

### Check

- `http://<docker-host>:7913` shows the **slot page** with four slots and green dots for
  printer and Spoolman.
- `http://<docker-host>:7913/api/health` returns the version and both connections.
- All settings: [configuration.md](configuration.md).

## 4. OrcaSlicer (orca-kobra build)

The plugin needs OrcaSlicer's plugin system (2.5.0-dev nightly). **Automatic profile selection**
additionally needs a small patch that is not merged upstream yet
([PR #14423](https://github.com/OrcaSlicer/OrcaSlicer/pull/14423)). The
[orca-kobra](https://github.com/xNoVoSx/orca-kobra) repository builds a Linux AppImage with it every
night and ships a self-updating launcher:

```bash
git clone https://github.com/xNoVoSx/orca-kobra && cd orca-kobra
tools/install.sh        # downloads the latest AppImage, adds "OrcaSlicer (Kobra)" to the menu
```

It uses the normal Orca data folder (`~/.config/OrcaSlicer`), so your existing printers and
profiles stay. Want your own build? Fork orca-kobra — the workflow builds it for you.

In Orca:

- Add the printer as usual (Anycubic Kobra S1 0.4 nozzle) and connect it to `http://<printer-ip>`.
- **Printer settings → Basic information → Advanced** (advanced mode): **Printer agent = Moonraker**.

> [!TIP]
> Without the orca-kobra build everything else still works (profiles, panel, back-sync,
> consumption) — you just select the `SM…` profiles in the filament boxes yourself.

## 5. Orca plugin "Kobra Spoolman"

With Orca closed:

```bash
mkdir -p ~/.config/OrcaSlicer/orca_plugins/kobra_spoolman
curl -fsSLo ~/.config/OrcaSlicer/orca_plugins/kobra_spoolman/kobra_spoolman.py \
  https://raw.githubusercontent.com/xNoVoSx/kobra-spoolman/main/orca-plugin/kobra_spoolman.py
```

1. Start Orca, open the **Plugins** dialog and enable **Kobra Spoolman**.
2. **Configuration** tab of the plugin: enter the bridge address, e.g. `http://192.168.1.10:7913`.
3. The **Kobra Spoolman** panel opens on the right and creates the profiles in the background.
   If Orca asks whether the plugin may connect to the bridge, allow it.
4. **Restart Orca once** — Orca reads profiles only at start-up. Your filaments now appear as
   `Vendor Name (SM000010)` in the filament lists.

## 6. Check that everything works

- [ ] Slot page: all four slots assigned, no warnings.
- [ ] Orca panel: bridge connected, four slots with spool names.
- [ ] Orca: filament **sync** button → the `SM…` profiles are in filament 1–4, panel says *passt* for each slot.
- [ ] Change a value in an `SM…` profile, save → dialog *Nach Spoolman übernehmen?* → value appears in Spoolman.
- [ ] After a print: the slot page shows *Letzter Druck* per slot and Spoolman's remaining weight dropped by that amount.

Next: [daily use](usage.md).
