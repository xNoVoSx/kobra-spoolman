# Installation

[Deutsch](de/installation.md) · [Back to README](../README.md)

This guide takes you from zero to the full workflow. Allow about an hour — most of it is the
first OrcaSlicer build, which GitHub does for you.

**Overview**

1. [Printer: Rinkhals and Moonraker](#1-printer-rinkhals-and-moonraker)
2. [Spoolman and its extra fields](#2-spoolman-and-its-extra-fields)
3. [ace-lane-bridge](#3-ace-lane-bridge)
4. [Pair your first device](#4-pair-your-first-device)
5. [OrcaSlicer (orca-kobra build)](#5-orcaslicer-orca-kobra-build)
6. [Orca plugin "Kobra Spoolman"](#6-orca-plugin-kobra-spoolman)
7. [Android app (optional)](#7-android-app-optional)
8. [Check that everything works](#8-check-that-everything-works)

---

## 1. Printer: Rinkhals and Moonraker

- Install [Rinkhals](https://github.com/rinkhals-community/Rinkhals) on the Kobra S1. Moonraker must be
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
      MOONRAKER_URL: "http://<printer-ip>:7125"
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
      MOONRAKER_URL: "http://<printer-ip>:7125"
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

In Orca:

- Add the printer as usual (Anycubic Kobra S1 0.4 nozzle) and connect it to `http://<printer-ip>`.
- **Printer settings → Basic information → Advanced** (advanced mode): **Printer agent = Moonraker**.

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

## 8. Check that everything works

- [ ] Web UI: printer and Spoolman connected (*Einstellungen*), all four slots assigned, no warnings.
- [ ] Orca panel: bridge connected, four slots with spool names.
- [ ] Orca: filament **sync** button → the `SM…` profiles are in filament 1–4, panel says *passt* for each slot.
- [ ] Change a value in an `SM…` profile, save → dialog *Nach Spoolman übernehmen?* → value appears in Spoolman.
- [ ] After a print: the print appears under *Drucke* with grams per spool, and Spoolman's remaining weight dropped by that amount.
- [ ] *Geräte* lists your browser, the Orca plugin (and the phone).

Next: [daily use](usage.md).
