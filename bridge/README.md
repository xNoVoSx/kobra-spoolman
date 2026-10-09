# ace-lane-bridge

The service between **Moonraker** (Kobra S1 + ACE 2 Pro, Klipper on a Raspberry Pi with ACEPRO) and **Spoolman**:

- web UI for phone, desktop and ultrawide (`http://<host>:7913`): slots, shelf, filaments, prints, dryer, devices
- device pairing: one key per browser, app and Orca plugin; everything that writes needs one
- writes Moonraker `lane_data` (material, colour, `filament_id` = `SM` + Spoolman ID) for OrcaSlicer
- measures consumption per slot and books it per spool into Spoolman (restart-safe, open items)
- ACE dryer: state, manual start/stop, automation by humidity
- Orca profile API for the [Kobra Spoolman plugin](../orca-plugin/), API for the [Android app](../android/)

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
  __main__.py      wiring, background loops
  config.py        environment variables
  moonraker.py     WebSocket subscription, changed-fields filter, database access
  spoolman.py      REST client with cache (spools, filaments, use, patch)
  slots.py         slot assignment, ACE matching, lane_data, auto-unassign
  usage.py         consumption measurement and booking, journal, open items, history
  orca_profiles.py Spoolman -> Orca values, back-sync
  profiles.py      template / base profile resolution, Orca IDs
  telemetry.py     raw recordings per print
  web.py           HTTP API
  appapi.py        API for the app and the web UI
  auth.py          device pairing and keys
  dryer.py         ACE dryer state and automation
  static/            web UI (Preact + htm, bundled fonts, no build step)
```
