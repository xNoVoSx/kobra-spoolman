# Configuration

[Back to README](../README.md)

## Bridge (environment variables)

| Variable | Default | Meaning |
|---|---|---|
| `MOONRAKER_URL` | **required** | Moonraker on the printer, e.g. `http://192.168.1.50:7125` |
| `MOONRAKER_API_KEY` | – | only if Moonraker requires one |
| `SPOOLMAN_URL` | `http://spoolman:8000` | inside the same stack via the service name |
| `SPOOLMAN_POLL_S` | `20` | how often Spoolman is re-read |
| `HTTP_HOST` / `HTTP_PORT` | `0.0.0.0` / `7913` | API and slot page |
| `SLOT_LOCATION_PREFIX` | `ACE Slot ` | Spoolman location of a loaded spool (`ACE Slot 1` …) |
| `SHELF_LOCATION` | `Regal` | location of unloaded spools |
| `TEMPLATE_VENDOR` | `Vorlage` | vendor name of the material templates |
| `AUTO_UNASSIGN_ON_EMPTY` | `true` | move the spool to the shelf when the ACE reports its slot empty |
| `EMPTY_DEBOUNCE_S` | `15` | …after the slot stayed empty this long (during a print: after it ends) |
| `WRITE_LANE_DATA` | `true` | write Moonraker `lane_data` for Orca/Mainsail/Fluidd |
| `LANE_NAMESPACE` | `lane_data` | Moonraker database namespace |
| `EMPTY_GATE_MODE` | `delete` | `delete` empty gates from `lane_data`, or `keep` |
| `BOOK_USAGE` | `true` | book consumption into Spoolman |
| `BOOK_INTERVAL_S` | `300` | intermediate booking during a print |
| `BOOK_MIN_MM` | `10` | smallest intermediate booking |
| `GATE_DEBOUNCE_S` | `3` | a new active slot counts only after this long (ACE flicker) |
| `USAGE_TOLERANCE` | `0.03` | hint if a slot used less than the G-code model minus 3 % |
| `JOB_HISTORY` | `50` | prints kept in the history |
| `TELEMETRY` / `TELEMETRY_KEEP` | `true` / `30` | raw recordings of the last prints |
| `DEFAULT_DIAMETER` / `DEFAULT_DENSITY` | `1.75` / `1.24` | only for estimates without a spool |
| `SPOOLMAN_PUBLIC_URL` | – | Spoolman link on the slot page; empty = same host, port 7912 |
| `PRINTER_UI_URL` | – | Mainsail link; empty = printer IP, port 4409 (Rinkhals) |
| `DRY_RUN` | `false` | log only, write nothing |
| `DATA_DIR` | `/data` | state, journal, history, telemetry |
| `LOG_LEVEL` | `INFO` | `DEBUG` for more detail |

### Data folder

```
data/
  usage/state.json      running print + open items (restart-safe)
  usage/jobs.json       print history
  usage/journal.jsonl   every booking, open item, start/end (rotated at 5 MB)
  telemetry/            raw recordings of the last prints
  venv/                 only when running from source (option B)
```

## Orca plugin

Plugins dialog → **Kobra Spoolman** → **Configuration**:

| Setting | Default | Meaning |
|---|---|---|
| Bridge address | `http://localhost:7913` | where the ace-lane-bridge runs |
| Orca user folder | `default` | profiles go to `user/<folder>/filament/base` (`default` without an Orca login) |
| Refresh (seconds) | `5` | how often the panel asks the bridge |
| Sync profiles on start | on | |
| Open panel on start | on | |
| Ask before back-sync | on | off = profile edits go to Spoolman without asking |
| Warn after slicing | on | Orca notification when a spool does not hold enough for the sliced plate |
| Reserve (g) | `5` | usage preview says *knapp* (tight) when less than this (or 5 % of the need) would be left |

Plugin files: `~/.config/OrcaSlicer/orca_plugins/kobra_spoolman/` (the plugin keeps its state in
`kobra_state.json` and its last written profiles in `written/` there). Log output:
`~/.config/OrcaSlicer/log/python_*.log`, lines start with `[kobra-spoolman]`.
