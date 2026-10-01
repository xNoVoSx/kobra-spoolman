# Bridge HTTP API

[Back to README](../README.md)

Base URL: `http://<docker-host>:7913`. All responses are JSON; errors are `{"error": "…"}` with a
4xx/5xx status. CORS is open (`*`), so browser tools and the Orca panel can call it directly.

**Keys:** reading is open. Everything that writes (Spoolman, slot assignment, open items) or makes
the printer do something (dryer) needs the key of a [paired device](#pairing-devices) in
`Authorization: Bearer <key>` — marked *(paired)* below. Without one: 401 (unknown key) or 403
(nothing paired yet).

## Status

| Method | Path | Purpose |
|---|---|---|
| GET | `/` | web UI (phone, desktop, ultrawide); files under `/static/` |
| GET | `/api/health` | version, uptime, connections, settings, safety warnings, changelog |

```json
{
  "app": "ace-lane-bridge", "version": "2.3.0", "uptime_s": 5231,
  "moonraker": {"url": "http://192.168.1.50:7125", "connected": true, "klippy_ready": true},
  "spoolman": {"url": "http://spoolman:8000", "connected": true, "version": "0.26.1", "spools": 6},
  "print_state": "standby", "booking": true, "open_items": 0, "warnings": []
}
```

## Slots

| Method | Path | Purpose |
|---|---|---|
| GET | `/api/slots` | per slot: what the ACE reports, the assigned spool, hints; plus live/last usage and open items |
| POST | `/api/slots/{n}` | *(paired)* `{"spool_id": 5}` assign a spool to slot *n* (the previous one goes to the shelf), `{"spool_id": null}` unload |
| GET | `/api/spools?slot=n` | assignable spools; with `slot` each entry has `match` (`material`, `color`, `full`) against the ACE |

A slot entry:

```json
{
  "slot": 1, "gate": 0,
  "ace": {"present": true, "active": false, "material": "PLA Silk", "color": "52D2BC"},
  "spool": {"spool_id": 3, "display_name": "Anycubic PLA Silk Grün", "material": "PLA",
            "remaining_weight": 585.2, "orca_filament_id": "SM000010"},
  "hints": []
}
```

## Consumption

| Method | Path | Purpose |
|---|---|---|
| GET | `/api/usage` | running print per slot (`live`), last print per slot, open items, purge statistics |
| GET | `/api/jobs?limit=20` | print history: per slot mm/g, spools, G-code targets, overhead, warnings |
| GET | `/api/open` | open items |
| POST | `/api/open/{id}` | *(paired)* `{"spool_id": 5}` book an open item onto a spool |
| DELETE | `/api/open/{id}` | *(paired)* discard an open item |

A history entry:

```json
{
  "file": "Blade_PLA_0.2_56m37s.gcode", "state": "complete",
  "total_mm": 8025.0, "target_mm": 7487.7, "overhead_mm": 537.3, "loads": 2, "changes": 1,
  "slots": [
    {"slot": 1, "mm": 4970.0, "g": 14.82, "target_mm": 4826.9, "overhead_mm": 143.1,
     "spools": [{"id": 3, "label": "#3 Anycubic PLA Silk Grün", "mm": 4970.0}]},
    {"slot": 2, "mm": 3055.0, "g": 9.11, "target_mm": 2660.8, "overhead_mm": 394.2,
     "spools": [{"id": 4, "label": "#4 Anycubic PLA Weiß", "mm": 3055.0}]}
  ],
  "warnings": []
}
```

## Orca

| Method | Path | Purpose |
|---|---|---|
| GET | `/api/orca/profiles` | Orca values per filament that has an active spool |
| GET | `/api/orca/state` | everything the Orca panel needs (slots, usage, profile hash) at one fixed URL |
| POST | `/api/orca/backsync` | *(paired)* write changed Orca values back to Spoolman |
| POST | `/api/orca/reset` | *(paired)* clear filament fields so the template / base profile applies again |

`GET /api/orca/profiles` (one entry):

```json
{
  "orca_id": "SM000008", "filament_id": 8, "display_name": "Sunlu PETG 2.0 Lavendelviolett",
  "base": "Generic PETG @System", "template": "Vorlage PETG",
  "values": {"nozzle_temperature": 250, "fan_min_speed": 20, "default_filament_colour": "#685BC7", "filament_id": "SM000008"},
  "sources": {"nozzle_temperature": "filament", "fan_min_speed": "vorlage", "default_filament_colour": "filament"},
  "spools": [{"id": 1, "remaining_weight": 1000.0, "slot": null}],
  "hash": "fc4c4e7cb9f3"
}
```

`usage.purge` in `GET /api/orca/state` and `/api/usage` carries the purge model the plugin uses for
its preview ([architecture](architecture.md#usage-preview-after-slicing)):

```json
{"jobs": 3, "overhead_per_load_mm": 118.4,
 "model": {"model": "colour", "flush_multiplier": 1.0, "flush_volume_min": 107.0, "flush_volume_max": 800.0,
           "flush_source": "printer", "offset_mm": -3.4, "first_load_mm": 94.6, "learned_from": 1}}
```

`sources` tells where each value comes from: `filament`, `vorlage` (template),
`override-filament` / `override-vorlage` (free Orca overrides). The base profile itself is resolved
by the plugin inside Orca, so the values always match the installed Orca version.

`POST /api/orca/backsync`:

```json
{"orca_id": "SM000009", "changes": {"nozzle_temperature": "235", "slow_down_layer_time": "8"}}
```
→ `{"ok": true, "applied": {"nozzle_temperature": 235, "slow_down_layer_time": "8"}, "ignored": []}`

`POST /api/orca/reset`:

```json
{"orca_id": "SM000009", "keys": ["fan_max_speed", "slow_down_layer_time"]}
```

## Dryer (ACE)

Nothing is written to Spoolman; the commands go to the printer, so they need a paired device.

| Method | Path | Purpose |
|---|---|---|
| GET | `/api/dryer` | humidity, ACE temperature, dryer state, highest allowed temperature with reasons, automation settings, last event |
| POST | `/api/dryer/start` | *(paired)* `{"temp": <°C or null>, "hours": <h or null>}` — null = automatic / automation's max hours; capped by the loaded filaments |
| POST | `/api/dryer/stop` | *(paired)* stop drying |
| POST | `/api/dryer/config` | *(paired)* automation: `enabled`, `start_above`, `stop_below` (%), `max_hours`, `pause_minutes`, `while_printing` |

| POST | `/api/dryer/schedule` | *(paired)* `{"at": <ISO time or epoch s>, "temp": <°C or null>, "hours": <h or null>}` — one planned start, at most a week ahead; the temperature is capped like a manual start |
| DELETE | `/api/dryer/schedule` | *(paired)* remove the planned start |

The dryer block is also part of `/api/slots` and `/api/app/state`. Data source: GoKlipper's
`filament_hub` object in the bridge's Moonraker subscription (the ACE reports about every 20 s);
commands: Rinkhals' `MMU_DRYER_START` / `MMU_DRYER_STOP`.

## ACE settings

Settings the printer display hides, read from GoKlipper (`/printer/filament_hub/get_config`, every
10 minutes and right after a change).

| Method | Path | Purpose |
|---|---|---|
| GET | `/api/ace?multiplier=` | `settings` (flush multiplier, `auto_refill`, `runout_detect`, presets, `printing`) and `purge`: the purge of every change between the loaded spools — with the current multiplier or the one given |
| POST | `/api/ace/flush` | *(paired)* `{"multiplier": 0.1–3.0, "confirm_printing": false}` — via Rinkhals' `SET_ACE_FLUSH_MULTIPLIER` |
| POST | `/api/ace/options` | *(paired)* `{"auto_refill": bool, "runout_detect": bool, "confirm_printing": false}` — via `filament_hub/set_config` |

While a print runs, changes are refused with 409 unless `confirm_printing` is true (the UIs ask
for an extra unlock first); a new multiplier applies from the next colour change. `/api/app/state`
contains `ace` (the settings).

## Camera and print preview

| Method | Path | Purpose |
|---|---|---|
| GET | `/api/camera` | camera state: `mode` (`stream`, `snapshot`, `idle`), `viewers`, `fps` (frame rate the printer delivers, measured by the bridge), last image time, error |
| GET | `/api/camera/stream.mjpg` | *(paired or camera key)* live MJPEG restream. Optional `?fps=5` caps the rate for this viewer |
| GET | `/api/camera/snapshot.jpg` | *(paired or camera key)* the current camera image, taken from the running stream if there is one |
| GET | `/api/camera/link` | *(paired)* `{"key": "…"}` — the camera key for links |
| POST | `/api/camera/link` | *(paired)* create a new camera key; old camera links stop working |

**One connection to the printer.** The bridge opens the printer's MJPEG stream only while someone
watches (or needs a snapshot) and closes it 20 s after the last viewer. However many viewers there
are, the printer serves one stream. If the printer has no stream, the bridge falls back to single
snapshots (at most one per `CAMERA_INTERVAL_S`) and tries the stream again after 5 minutes.

**Camera key.** Mainsail and an `<img>` tag cannot send an `Authorization` header, so camera URLs
also accept `?key=<camera key>`. The key only shows camera images; it is stored in `camera.json`
in the data folder and can be replaced by any paired device.
| GET | `/api/print/info` | preview of the running print: `status` (`loading`, `ready`, `too_big`, `error`, `idle`), `layer`/`layers`, `thumbnail` |
| GET | `/api/print/preview.png` | the print file drawn by the bridge in the ACE colours; printed part solid, the rest as a shadow, nozzle marked; refreshed at most every `RENDER_INTERVAL_S` |
| GET | `/api/print/thumbnail.png` | the thumbnail the slicer embedded in the file |

The bridge downloads the running file once at print start through Moonraker (throttled) and
renders it itself; progress comes from `virtual_sdcard.file_position`.

## Pairing devices

The bridge issues the keys itself. Each device (app, browser, Orca plugin) gets its own
key; the bridge stores only its SHA-256 (`devices.json` in the data folder).

| Method | Path | Purpose |
|---|---|---|
| GET | `/api/auth/status` | `setup_required`, number of devices, the calling device (by its key) |
| POST | `/api/auth/pair` | `{"code", "name", "kind": "app"\|"web"\|"plugin"}` → `{"token", "device"}` |
| POST | `/api/auth/code` | *(paired)* new 6-digit pairing code, valid 5 minutes, single use |
| GET | `/api/auth/devices` | *(paired)* paired devices (`me` marks the caller) |
| DELETE | `/api/auth/devices/{id}` | *(paired)* remove a device |

- **First device:** while nothing is paired, the bridge logs a setup code at start
  (`Noch kein Gerät gekoppelt. Einrichtungscode: …`) — Portainer → container → Logs.
- A set `APP_TOKEN` keeps working as a key and as a pairing code (transition).
- Wrong codes are throttled (5 attempts, then 60 s).
- QR code content for the app: `kobraspoolman://pair?b=<bridge-url>&c=<code>`.

## App and web UI

For the [Android app](android-app.md) and the web UI. Reading is open like the rest of the API; every writing call
needs `Authorization: Bearer <device key>` from [pairing](#pairing-devices) (401 unknown key,
403 nothing paired yet). Errors: `{"error": "…"}` with 400 (invalid input), 404, 409 (conflict),
429 (too many wrong codes), 502 (Spoolman).

| Method | Path | Purpose |
|---|---|---|
| GET | `/api/app/state` | printer status, slots (with `tag_nr`/`nfc_uid`), shelf spools, dryer, `usage` (`live`, `open`), `can_write` |
| GET | `/api/app/catalog` | vendors, templates (with their values), filaments, extra-field definitions with Orca keys, Orca base profiles |
| GET | `/api/app/spools?q=` | all active spools, optional text filter |
| GET | `/api/app/spool/{id}` | one spool, its filament, the last prints that used it |
| POST | `/api/app/vendor` | `{"name", "empty_spool_weight"?}` |
| POST | `/api/app/filament` | create a filament: native fields + `extra`; only the fields sent are stored |
| POST | `/api/app/filament/{id}/copy` | new colour of a product line: `{"name", "color_hex", …}` override the copy |
| PATCH | `/api/app/filament/{id}` | change fields; `null` clears one (back to template / Orca base profile) |
| POST | `/api/app/spool` | `{"filament_id", "initial_weight"?, "spool_weight"?, "price"?, "lot_nr"?, "comment"?, "slot"?}` |
| PATCH | `/api/app/spool/{id}` | `remaining_weight`, `initial_weight`, `spool_weight`, `price`, `lot_nr`, `comment`, `location` (shelf only — slots go through the assignment) |
| POST | `/api/app/spool/{id}/location` | `{"slot": 1–4}` or `{"slot": null}` (shelf) |
| POST | `/api/app/spool/{id}/archive` | empty spool: out of its slot, archived |
| POST | `/api/app/tag/issue` | `{"spool_id"}` → tag number (reserved at the spool) and the tag content to write |
| POST | `/api/app/tag/link` | `{"spool_id", "uid", "force"?}` → links a tag's UID (also original Anycubic tags) |
| GET | `/api/app/tag/{uid}` | spool for a scanned tag |
| POST | `/api/orca/bases` | *(paired)* the Orca plugin reports its filament base profile names |

`GET /api/app/state` → `printer`:

```json
{"state": "printing", "file": "test-A-100.gcode", "progress": 0.42, "print_duration_s": 1260, "eta_s": 1740,
 "message": null, "active_slot": 1, "mmu_action": "Idle", "changing_filament": false}
```

`state` is Moonraker's `print_stats.state` (`standby`, `printing`, `paused`, `complete`, `cancelled`,
`error`) or `offline` when the printer is not reachable. `changing_filament` is derived from
`mmu.action` (anything but idle while printing) — the exact Rinkhals values are still to be verified.

`POST /api/app/filament` (only what the user set; density/diameter default to the template):

```json
{"name": "PETG 2.0 Mintgrün", "vendor_id": 2, "material": "PETG", "color_hex": "3FA46A",
 "settings_extruder_temp": 250, "weight": 1000, "spool_weight": 160,
 "extra": {"flow_ratio": 0.95, "vorlage": "Vorlage PETG"}}
```

`POST /api/app/tag/issue` → `tag` (the app encodes it in the ACE page layout):

```json
{"tag_nr": 48213, "sku": "AHPEBK-48213", "brand": "Sunlu", "material": "PETG", "color": "685BC7",
 "nozzle_min": 250, "nozzle_max": 255, "bed_min": 75, "bed_max": 80,
 "diameter_mm": 1.75, "weight_g": 1000.0, "length_m": 327.5}
```

Temperatures span the print and first-layer values (filament, else template). The SKU format is
provisional until the tag test shows what the ACE accepts (`TAG_SKU_PREFIX`, `TAG_NR_MIN`/`MAX`).

## Telemetry

| Method | Path | Purpose |
|---|---|---|
| GET | `/api/telemetry` | recorded prints (raw data) with a short summary |
| GET | `/api/telemetry/{file}` | raw JSONL of one print (changes of `mmu`, `print_stats`, `virtual_sdcard`) |
