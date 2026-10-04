# Configuration

[Back to README](../README.md)

## Bridge (environment variables)

| Variable | Default | Meaning |
|---|---|---|
| `MOONRAKER_URL` | **required** | Moonraker on the printer, e.g. `http://192.168.1.50:7125` |
| `MOONRAKER_API_KEY` | – | only if Moonraker requires one |
| `SPOOLMAN_URL` | `http://spoolman:8000` | inside the same stack via the service name |
| `SPOOLMAN_POLL_S` | `20` | how often Spoolman is re-read |
| `HTTP_HOST` / `HTTP_PORT` | `0.0.0.0` / `7913` | API and web UI |
| `SLOT_LOCATION_PREFIX` | `ACE Slot ` | Spoolman location of a loaded spool (`ACE Slot 1` …) |
| `SHELF_LOCATION` | `Regal` | location of unloaded spools |
| `TEMPLATE_VENDOR` | `Vorlage` | vendor name of the material templates |
| `AUTO_UNASSIGN_ON_EMPTY` | `true` | move the spool to the shelf when the ACE reports its slot empty |
| `AUTO_ASSIGN_BY_TAG` | `true` | a spool with one of our tags (number ≥ `TAG_NR_MIN`) in a slot is assigned to it automatically |
| `EMPTY_DEBOUNCE_S` | `15` | …after the slot stayed empty this long (during a print: after it ends) |
| `WRITE_LANE_DATA` | `true` | write Moonraker `lane_data` for Orca/Mainsail/Fluidd |
| `LANE_NAMESPACE` | `lane_data` | Moonraker database namespace |
| `EMPTY_GATE_MODE` | `delete` | `delete` empty gates from `lane_data`, or `keep` |
| `SET_ACE_SLOT_INFO` | `true` | when a spool is assigned (web UI, app), give its material/colour to the ACE (Rinkhals `MMU_GATE_MAP`) — once, after it is loaded, never while printing; slots with RFID tag are refused by Rinkhals — see [findings](findings.md#print-start-and-ace-slot-info-2026-09-30) |
| `BOOK_USAGE` | `true` | book consumption into Spoolman |
| `BOOK_INTERVAL_S` | `300` | intermediate booking during a print |
| `BOOK_MIN_MM` | `10` | smallest intermediate booking |
| `GATE_DEBOUNCE_S` | `3` | a new active slot counts only after this long (ACE flicker) |
| `USAGE_TOLERANCE` | `0.03` | hint if a slot used less than the G-code model minus 3 % |
| `JOB_HISTORY` | `50` | prints kept in the history |
| `APP_TOKEN` | *(empty)* | **optional, transition only** — devices are now [paired](api.md#pairing-devices) and get their own keys. A set value still works as a key and as a pairing code |
| `TAG_SKU_PREFIX` / `TAG_NR_MIN` / `TAG_NR_MAX` | `AHPEBK` / `1000` / `99999` | tag numbers for self-written NFC tags (SKU `<prefix>-<number>`); provisional until the tag test |
| `TELEMETRY` / `TELEMETRY_KEEP` | `true` / `30` | raw recordings of the last prints |
| `DEFAULT_DIAMETER` / `DEFAULT_DENSITY` | `1.75` / `1.24` | only for estimates without a spool |
| `SPOOLMAN_PUBLIC_URL` | – | Spoolman link in the web UI; empty = same host, port 7912 |
| `PRINTER_UI_URL` | – | Mainsail link (*In Mainsail öffnen*); empty = printer IP, port 4409 (Rinkhals) |
| `CAMERA` | `true` | camera through the bridge (web UI, app, Mainsail via camera link) |
| `CAMERA_STREAM` | `false` | `false`: the bridge fetches single snapshots (like Mainsail's *adaptive* mode) and restreams them; `true`: it holds the printer's MJPEG stream instead — on the Kobra S1 that alone costs 100 % CPU |
| `CAMERA_FPS_MIN` / `CAMERA_FPS_MAX` | `1` / `10` | range of the snapshot rate |
| `CAMERA_CPU_LOW` / `CAMERA_CPU_HIGH` | `90` / `97` | printer CPU (%, mean over 10 s): below LOW the rate goes up by 1 fps every 5 s, above HIGH down by 1 fps every 5 s. During a print the S1 sits at 75–89 % from GoKlipper alone; snapshots cost next to nothing |
| `CAMERA_STREAM_URL` | – | stream URL; empty = from Moonraker's webcam list (`/webcam/?action=stream` on the printer) |
| `CAMERA_SNAPSHOT_URL` | – | snapshot URL; empty = from Moonraker's webcam list (`/webcam/?action=snapshot` on the printer) |
| `CAMERA_INTERVAL_S` | `1` | a single `snapshot.jpg` request reuses an image younger than this |
| `RENDER` | `true` | draw the running print file (preview) |
| `RENDER_MAX_MB` | `200` | larger files only get the slicer thumbnail |
| `RENDER_INTERVAL_S` | `15` | redraw at most this often while printing |
| `GEOMETRY_MAX_SEGMENTS` | `1500000` | detail of the 3D view: above this, connected pieces of a line are merged (deviation 0.02 → 0.2 mm, as little as needed); only if that is not enough, segments are left out. 1.5 M ≈ 20 MB transfer |
| `HUMIDITY_DAYS` | `30` | days of ACE humidity history kept (`DATA_DIR/humidity/`) |
| `ROOM_RH` | `50` | humidity (%) of the storage room for the spool moisture estimate, used while no room sensor delivers fresh values |
| `DRY_LOCATIONS` | – | Spoolman locations with their own humidity, e.g. `Trockenbox=15; Vakuumbeutel=10` |
| `AUTO_DRY_ON_INSERT` | `true` | start the ACE dryer when a spool that needs drying is loaded (temperature of the most sensitive loaded spool, time of the wettest) |
| `NEW_SPOOLS_DRY` | `true` | spools without history count as *needs drying* when first loaded |
| `WET_PRINT_ACTION` | `warn` | print start with a spool that needs drying: `warn` or `pause` (pauses once, within the first 10 min) |
| `LOW_SPOOL_G` | `100` | notice *Spule fast leer* below this |
| `REACH_RESERVE_PCT` | `5` | reserve for the notice *Spule reicht nicht* |
| `MQTT_HOST` | – | [Home Assistant over MQTT](#home-assistant-mqtt): broker address; empty = off |
| `MQTT_PORT` / `MQTT_USER` / `MQTT_PASSWORD` | `1883` / – / – | broker login |
| `MQTT_PREFIX` | `kobra-spoolman` | topic prefix of the bridge |
| `MQTT_DISCOVERY` | `homeassistant` | Home Assistant discovery prefix; empty = no discovery (topics only) |
| `ROOM_SENSOR_TOPIC` | – | MQTT topic of a humidity sensor in the storage room, e.g. `zigbee2mqtt/Filamentlager` |
| `VISION_URL` | – | AI print-failure detection: address of [kobra-vision](vision.md), e.g. `http://kobra-vision:7917`; empty = off |
| `VISION_TOKEN` | – | shared key if kobra-vision has `VISION_TOKEN` set |
| `VISION_INTERVAL_S` / `VISION_SENSITIVITY` / `VISION_ACTION` / `VISION_DATASET_GB` / `VISION_SAVE_EVERY_S` | `10` / `1.0` / `warn` / `5` / `60` | **start values only** — once anything is saved in the [KI tab](vision.md#the-ki-tab) (`DATA_DIR/vision/settings.json`), that wins |
| `DRY_RUN` | `false` | log only, write nothing |
| `DATA_DIR` | `/data` | state, journal, history, telemetry |
| `LOG_LEVEL` | `INFO` | `DEBUG` for more detail |

The dryer automation (on/off, thresholds, max. time, pause, while printing) is set in the web UI or
app (*Trockner → Regeln*) and stored in `dryer.json`, not in the environment.

### Changing settings at runtime

Most values above can be changed in the web UI (*Einstellungen*, one card per group) without a restart: camera,
print preview, slots and RFID, spool moisture, notices, consumption and data. The environment only gives
the start values; a changed value is stored in `DATA_DIR/settings.json` and wins from then on (*zurücksetzen*
next to a value restores the start value). Addresses (printer, Spoolman, camera, AI service, MQTT) need
a restart and are only shown there.

### Home Assistant (MQTT)

With `MQTT_HOST` set, the bridge publishes what it knows anyway — the printer gets no extra client:

| Topic (retained JSON) | Content |
|---|---|
| `<prefix>/status` | `online` / `offline` (last will) |
| `<prefix>/printer` | state, progress, ETA, finish time, file, layer, nozzle/bed, active slot, printer CPU |
| `<prefix>/ace` | humidity, temperature, drying, target, remaining time |
| `<prefix>/slot/<n>` | spool, material, colour, remaining weight, moisture estimate, needs drying |
| `<prefix>/notices` | count, errors, warnings, most important text |
| `<prefix>/vision` | AI level and score (only with `VISION_URL`) |

Values are sent on change, at most every 5 s. With `MQTT_DISCOVERY` Home Assistant creates the device
*Kobra S1 (ace-lane-bridge)* with all sensors by itself.

**Room sensor:** `ROOM_SENSOR_TOPIC` is subscribed; a JSON payload with `humidity` (and `temperature`),
as Zigbee2MQTT sends it, or a plain number. While the last value is younger than 2 h it replaces
`ROOM_RH` in the moisture estimate of spools on the shelf (locations from `DRY_LOCATIONS` keep their
own value). The status shows *Raumsensor* with the last value.

### AI print-failure detection

Settings of the kobra-vision container itself (threads, unloading, GPU) are in [vision.md](vision.md#kobra-vision-settings).

### Docker user

The image runs as user 1000. If the data folder belongs to root, make it writable for that user or
run the container as root with `user: "0:0"` in the service.

### Data folder

```
data/
  devices.json          paired devices (name, kind, SHA-256 of the key — never the key itself)
  dryer.json            dryer automation settings
  settings.json         settings changed in the web UI (wins over the environment)
  humidity/             ACE humidity, one point per minute (<day>.jsonl), and drying sessions (sessions.json)
  moisture.json         moisture estimate and history per spool
  orca_bases.json       Orca base profile names reported by the plugin
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
| Update profiles on start | on | |
| Open panel on start | on | |
| Ask before back-sync | on | off = profile edits go to Spoolman without asking |
| Warn after slicing | on | Orca notification when a spool does not hold enough for the sliced plate |
| Reserve (g) | `5` | usage preview says *knapp* (tight) when less than this (or 5 % of the need) would be left |

Pairing is not a setting: when the plugin is not paired, its panel shows a field for the pairing
code. The key is then stored in `kobra_device.json` and belongs to that bridge address — changing
the address means pairing again.

Plugin files: `~/.config/OrcaSlicer/orca_plugins/kobra_spoolman/` (the plugin keeps its state in
`kobra_state.json`, its key in `kobra_device.json` and its last written profiles in `written/` there). Log output:
`~/.config/OrcaSlicer/log/python_*.log`, lines start with `[kobra-spoolman]`.
