# Bridge HTTP API

[Back to README](../README.md)

Base URL: `http://<docker-host>:7913`. All responses are JSON; errors are `{"error": "…"}` with a
4xx/5xx status. CORS is open (`*`), so browser tools and the Orca panel can call it directly.

## Status

| Method | Path | Purpose |
|---|---|---|
| GET | `/` | slot page (mobile web UI) |
| GET | `/api/health` | version, uptime, connections, settings, safety warnings, changelog |

```json
{
  "app": "ace-lane-bridge", "version": "2.2.1", "uptime_s": 5231,
  "moonraker": {"url": "http://192.168.1.50:7125", "connected": true, "klippy_ready": true},
  "spoolman": {"url": "http://spoolman:8000", "connected": true, "version": "0.26.1", "spools": 6},
  "print_state": "standby", "booking": true, "open_items": 0, "warnings": []
}
```

## Slots

| Method | Path | Purpose |
|---|---|---|
| GET | `/api/slots` | per slot: what the ACE reports, the assigned spool, hints; plus live/last usage and open items |
| POST | `/api/slots/{n}` | `{"spool_id": 5}` assign a spool to slot *n* (the previous one goes to the shelf), `{"spool_id": null}` unload |
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
| POST | `/api/open/{id}` | `{"spool_id": 5}` book an open item onto a spool |
| DELETE | `/api/open/{id}` | discard an open item |

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
| POST | `/api/orca/backsync` | write changed Orca values back to Spoolman |
| POST | `/api/orca/reset` | clear filament fields so the template / base profile applies again |

`GET /api/orca/profiles` (one entry):

```json
{
  "orca_id": "SM000008", "filament_id": 8, "display_name": "Sunlu PETG 2.0 Lavendelviolett",
  "base": "Generic PETG @System", "template": "Vorlage PETG",
  "values": {"nozzle_temperature": 250, "fan_min_speed": 20, "filament_colour": "#685BC7", "filament_id": "SM000008"},
  "sources": {"nozzle_temperature": "filament", "fan_min_speed": "vorlage", "filament_colour": "filament"},
  "spools": [{"id": 1, "remaining_weight": 1000.0, "slot": null}],
  "hash": "fc4c4e7cb9f3"
}
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

## Telemetry

| Method | Path | Purpose |
|---|---|---|
| GET | `/api/telemetry` | recorded prints (raw data) with a short summary |
| GET | `/api/telemetry/{file}` | raw JSONL of one print (changes of `mmu`, `print_stats`, `virtual_sdcard`) |
