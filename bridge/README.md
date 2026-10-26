# ace-lane-bridge

The service between **Moonraker** (Kobra S1 + ACE 2 Pro or Kobra 3 + ACE Pro — stock firmware with Rinkhals, or Klipper on
a Raspberry Pi with ACEPRO; detected by itself) and **Spoolman**:

- web UI for phone, desktop, ultrawide and the printer's touchscreen (`http://<host>:7913`, `/display`): slots, shelf,
  filaments, prints, dryer, ACE, terminal, logs, devices, features, settings
- device pairing: one key per browser, app, display and Orca plugin; everything that writes needs one
- writes Moonraker `lane_data` (material, colour, `filament_id` = `SM` + Spoolman ID) for OrcaSlicer's sync button
- measures consumption per slot and books it per spool into Spoolman (restart-safe, open items, print history)
- spools assign themselves by NFC tag; Anycubic tags by material, colour and vendor
- ACE dryer with automation by humidity, humidity history, moisture estimate per spool, print start check
- ACE settings: endless spool; on Rinkhals also runout detection and the firmware's purge multiplier with a preview
- printer monitor: camera restream, 3D view of the print, print phase, pause/cancel/tune, messages for the app
- the bridge side of the Klipper modules: auto PA, Z offset per filament, resume, clog detection, direct feed,
  swappable hotends, another spool when one runs out, pause in the print start, USB watchdog, eject a slot
- Home Assistant over MQTT, the web UI under HA ingress, the ingress path for the app away from home
- optional AI print-failure detection with [kobra-vision](../vision/)
- web UI, messages and app texts in English or German (per device)
- Orca profile API for the [Kobra Spoolman plugin](../orca-plugin/), API for the [Android app](../android/), app updates

Python 3.11+, only dependency `aiohttp`.

| | |
|---|---|
| Run with Docker | [compose.yaml](compose.yaml), image `ghcr.io/xnovosx/ace-lane-bridge` |
| Run from source | `entrypoint.sh` (creates a venv in `$DATA_DIR`) or `pip install -r app/requirements.txt && cd app && python -m acebridge` |
| Settings | [docs/configuration.md](../docs/configuration.md) |
| API | [docs/api.md](../docs/api.md) |
| How it works | [docs/architecture.md](../docs/architecture.md) |

```
app/acebridge/
  __main__.py        wiring, background loops
  config.py          environment variables; runtime_settings.py: what the web UI can change while running
  moonraker.py       WebSocket subscription, database access, firmware detection
  acemodel.py        one view of the ACE for both firmwares (ACEPRO, Rinkhals), commands per firmware
  ace.py, purge.py   ACE settings card; Rinkhals: model of the firmware's own purge per colour change
  spoolman.py        REST client with cache (spools, filaments, use, patch)
  slots.py           slot assignment, ACE and tag matching, lane_data, auto-unassign
  usage.py           consumption measurement and booking, journal, open items, history
  profiles.py        template / base profile resolution, Orca IDs; orca_profiles.py: Spoolman -> Orca, back-sync
  dryer.py           ACE dryer state and automation; humidity.py: history and drying runs; moisture.py: per spool
  printcheck.py      check at print start: do the slots match the file?
  camera.py          camera restream; printercpu.py: CPU of the printer; render.py: print preview
  phase.py           print phase ("Heating bed 63/100 °C"); printerinfo.py: printer and ACE model
  control.py         pause/resume/cancel/emergency stop and tuning; machine.py: home, jog, load, eject
  files.py, prompts.py  print files for the display, macro prompts
  pa.py, filament_z.py, resume.py, clog.py, direct.py, nozzle.py, spare.py, startseq.py
                     the bridge side of the Klipper modules (kobra-klipper); switches.py: their switches
  usb.py             USB tunnel watchdog state; gcodepush.py: sync through G-code
  status.py          messages and status for the overview and the app
  features.py        every feature with its switch; setup.py: first start
  mqtt.py            Home Assistant over MQTT; ingress.py: HA ingress (sidebar, path for the app)
  vision.py          AI print-failure detection (vision_data.py, vision_settings.py)
  console.py         printer console, sent commands, bridge log; telemetry.py, printlog.py: print recordings
  diagnostics.py     bug report text
  auth.py            device pairing and keys; appupdate.py: app update through the bridge
  web.py, api_*.py   HTTP API; appapi.py: API for the app and the web UI; webcommon.py: shared helpers
  i18n.py            English source texts, German catalog (locale/de.json), language per request
  storage.py         atomic writes in the data folder
  static/            web UI (Preact + htm, bundled fonts, no build step)
```
