# Installation

[Deutsch](de/installation.md) · [Back to README](../README.md)

This guide takes you from zero to the full workflow. Allow about an hour — most of it is the
first OrcaSlicer build, which GitHub does for you.

**Overview**

1. [Printer: Klipper, ACEPRO and Moonraker](#1-printer-klipper-acepro-and-moonraker)
2. [Spoolman and its extra fields](#2-spoolman-and-its-extra-fields)
3. [ace-lane-bridge](#3-ace-lane-bridge)
4. [Pair your first device](#4-pair-your-first-device)
5. [OrcaSlicer (orca-kobra build)](#5-orcaslicer-orca-kobra-build)
6. [Orca plugin "Kobra Spoolman"](#6-orca-plugin-kobra-spoolman)
7. [Android app (optional)](#7-android-app-optional)
8. [Check that everything works](#8-check-that-everything-works)

---

## 1. Printer: Klipper, ACEPRO and Moonraker

Bridge 3.x works with **Klipper on a Raspberry Pi**: the Kobra S1's own controllers are tunnelled to the
Pi over USB ([vanilla-klipper-swu](https://github.com/Kobra-S1/vanilla-klipper-swu), Klipper fork
[klipper-kobra-s1](https://github.com/Kobra-S1/klipper-kobra-s1)), the ACE 2 Pro hangs on the Pi with the
[ACEPRO](https://github.com/Kobra-S1/ACEPRO) driver. Follow those projects' guides; for the bridge:

- Moonraker must be reachable at `http://<pi-ip>:7125` (try `http://<pi-ip>:7125/server/info` in a browser).
- **ACEPRO's own `lane_data` sync off** — the bridge writes `lane_data` with the Spoolman profile IDs, ACEPRO
  would overwrite it. In `printer.cfg`, after the ACE include:
  ```ini
  [ace]
  moonraker_lane_sync_enabled: False
  ```
- **Moonraker's own Spoolman integration must stay off** (no `[spoolman]` section in
  `moonraker.conf`), otherwise consumption is booked twice.
- Give the Pi a fixed IP address (DHCP reservation) — everything else points at it.
- Still on the stock firmware with [Rinkhals](https://github.com/rinkhals-community/Rinkhals)? Use bridge **2.21.1**
  and plugin 0.5.2 (tag `v2.21.1`).

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
- **Spool fields** *NFC-Kennung* and *Tag-Nummer* (NFC tags from the app).
- Filament field *Trocknen max.* — the highest drying temperature the filament takes (ACE dryer).
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
      MOONRAKER_URL: "http://<pi-ip>:7125"
      SPOOLMAN_URL: "http://spoolman:8000"   # service name inside the same stack
      TZ: Europe/Berlin
    depends_on:
      - spoolman
```

The image runs as user 1000. If your data folder belongs to root (common with Portainer and
`/docker/...` paths), either make it writable for 1000 or run the container as root by adding
`user: "0:0"` to the service.

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
      MOONRAKER_URL: "http://<pi-ip>:7125"
      SPOOLMAN_URL: "http://spoolman:8000"
      TZ: Europe/Berlin
```

On first start the entrypoint creates a Python environment in `data/venv` (needs internet once).
Updating = copy the new `app/` folder and restart the container.

### Check

- `http://<docker-host>:7913` opens the **web UI** — first with the pairing screen (next step).
- `http://<docker-host>:7913/api/health` returns the version and both connections.
- All settings: [configuration.md](configuration.md).

## 4. Pair your first device

Reading works for everyone in your network; everything that changes something needs a **paired
device**. The bridge issues the keys itself — you never invent a password.

1. Open the bridge log (Portainer → Containers → *ace-lane-bridge* → Logs, or
   `docker logs ace-lane-bridge`). As long as nothing is paired it says
   `Noch kein Gerät gekoppelt. Einrichtungscode: 123456`.
2. Open `http://<docker-host>:7913`, enter the six digits and a name for the browser → **Koppeln**.
   The browser keeps its key and never asks again.
3. Every further device (another browser, the phone, the Orca plugin) gets a fresh code from a paired
   one: web UI → **Geräte → Gerät hinzufügen** shows a 6-digit code and a QR code (valid 5 minutes,
   single use). Devices can be removed there at any time.

> [!NOTE]
> Coming from a version with `APP_TOKEN`? The old token still works as a key and can be typed in as
> pairing code (*Mit altem APP_TOKEN koppeln*). Once all devices are paired you can drop it from the stack.

<p align="center"><img src="images/web-pair.png" width="560" alt="Pairing screen of the web UI"></p>

## 5. OrcaSlicer (orca-kobra build)

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
Updates, fallback and uninstall: [orca-kobra installation guide](https://github.com/xNoVoSx/orca-kobra/blob/main/docs/installation.md).

### Orca printer profile

- Add the printer as usual (Anycubic Kobra S1 0.4 nozzle), set the G-code flavour to **Klipper** and connect
  it to `http://<pi-ip>`.
- **Printer settings → Basic information → Advanced** (advanced mode): **Printer agent = Moonraker**.
- **Printer settings → Machine G-code → Change filament G-code** — the purge of every colour change comes
  from Orca's flushing volumes (the dialog next to *Filament*), ACEPRO purges that much after loading:
  ```
M104 S{max(old_filament_temp, new_filament_temp)}
{if previous_extruder >= 0}{local purge_mm = flush_volumes_matrix[previous_extruder * size(filament_colour) + next_extruder] * flush_multiplier[0] / (0.785398 * filament_diameter[next_extruder] * filament_diameter[next_extruder])}
ACE_SET_PURGE_AMOUNT PURGELENGTH={digits(purge_mm, 0, 1)}
T[next_extruder]
; EXTERNAL_PURGE {digits(purge_mm + 85, 0, 2)}
{else}T[next_extruder]
{endif}
  ```
  It reads the matrix directly because Orca's `flush_length` is always 0 when a prime tower is used.
  `; EXTERNAL_PURGE` tells Orca about load (85 mm from the toolhead sensor to the nozzle, ACEPRO's
  `toolhead_full_purge_length`) plus purge, so Orca's legend and the plugin's preview show the real
  consumption.
- **Flushing volumes:** multiplier 1.0 to start with, adjust single transitions in the matrix.
  *Purge in prime tower* (printer → multimaterial) stays **off**, otherwise the tower gets the same amount again.

> [!TIP]
> Without the orca-kobra build everything else still works (profiles, panel, back-sync,
> consumption) — you just select the `SM…` profiles in the filament boxes yourself.

## 6. Orca plugin "Kobra Spoolman"

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
4. **Pair the plugin**: the panel shows *Plugin koppeln* — get a code in the web UI
   (*Geräte → Gerät hinzufügen*) and enter it. Without pairing the panel and profiles still work,
   but saving a profile back to Spoolman is refused.
5. **Restart Orca once** — Orca reads profiles only at start-up. Your filaments now appear as
   `Vendor Name (SM000010)` in the filament lists.

## 7. Android app (optional)

Download `kobra-spoolman-app-<version>.apk` from the latest
[GitHub release](https://github.com/xNoVoSx/kobra-spoolman/releases) and open it on the phone (allow
installing from that source). Later updates come from the bridge: when the bridge brings a newer app,
**Mehr** shows *Update auf …* — one tap downloads it from the bridge and Android asks to install it.
Then: **Einstellungen → QR-Code scannen** and scan the QR code from
*Geräte → Gerät hinzufügen* in the web UI. Android 17 asks for *Nearby devices* (local network) —
allow it, otherwise the app cannot reach the bridge. More: [android-app.md](android-app.md).

## 7b. AI print-failure detection (optional)

Add the `kobra-vision` service to the same stack and set `VISION_URL: "http://kobra-vision:7917"` on
the bridge — the [compose example](../bridge/compose.yaml) has both commented out. It runs on the CPU
(~50 ms per picture); a GPU is optional. Details: [vision.md](vision.md).

## 8. Check that everything works

- [ ] Web UI: printer and Spoolman connected (*Einstellungen*), all four slots assigned, no warnings.
- [ ] Orca panel: bridge connected, four slots with spool names.
- [ ] Orca: filament **sync** button → the `SM…` profiles are in filament 1–4, panel says *passt* for each slot.
- [ ] Change a value in an `SM…` profile, save → dialog *Nach Spoolman übernehmen?* → value appears in Spoolman.
- [ ] After a print: the print appears under *Drucke* with grams per spool, and Spoolman's remaining weight dropped by that amount.
- [ ] *Geräte* lists your browser, the Orca plugin (and the phone).

Next: [daily use](usage.md).
