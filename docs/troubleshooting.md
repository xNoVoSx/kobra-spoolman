# Troubleshooting

[Deutsch](de/troubleshooting.md) · [Back to README](../README.md)

Start with the logs: the bridge log (`docker logs ace-lane-bridge` or Portainer → Logs) and, for
Orca, `~/.config/OrcaSlicer/log/python_*.log`.

## Pairing and keys

| Problem | Cause / solution |
|---|---|
| Web UI asks for a code, I have none | First device: the setup code is in the bridge log (`Setup code: …`, printed at every start while nothing is paired). Otherwise get a code from a paired device: *Devices → Add device*. An old `APP_TOKEN` also works (*Pair with the old APP_TOKEN*). |
| *Code wrong or expired* | Codes are valid 5 minutes and only once. Get a new one. |
| *Too many wrong codes – wait a minute* | 5 wrong codes within a minute lock pairing for 60 s. |
| Browser suddenly asks to pair again | Its key was removed under *Devices*, or the bridge's data folder (`devices.json`) was lost. Pair again. |
| Lost a phone | *Devices* → **Remove** — its key stops working immediately. |
| Buttons lead to the pairing screen | You chose *View only*. Pair the browser (chip *view only – pair* at the top). |
| Orca: *Writing to Spoolman only works once the plugin is … paired* | Enter a pairing code in the panel (*Pair the plugin*), then save the profile again. Plugin older than 0.4.0? Update it — bridge 2.6.0+ refuses back-sync without a key. |
| App: *The bridge no longer knows this device* | The app's key was removed or the bridge was set up anew. Settings → pair again. |
| App shows nothing, requests time out (Android 17) | The app needs *Nearby devices* (local network). Allow it under Android settings → Apps → Kobra Spoolman → Permissions. |

## Connections

| Problem | Cause / solution |
|---|---|
| Web UI: *Kobra S1 · Offline* | Moonraker not reachable or Klipper not ready. Check `MOONRAKER_URL`, open `http://<printer-or-pi-ip>:7125/server/info`; on Klipper use *Reload Klipper* after an emergency stop or error, on Rinkhals switch the printer off and on. |
| Web UI: *Spoolman disconnected* | Check `SPOOLMAN_URL`. Inside the same stack use the service name (`http://spoolman:8000`). |
| Bridge does not start, `PermissionError` on `/data` | The image runs as user 1000. Make the data folder writable for it or add `user: "0:0"` to the service. |
| Orca panel: *Bridge not reachable* | Set the bridge address under Plugins → Kobra Spoolman → Configuration. |
| Orca panel does not appear | Run *Kobra Spoolman* from the Plugins dialog; check the Orca log. |

## Slots and printing

| Problem | Cause / solution |
|---|---|
| Warning *…consumption would be booked twice* | Moonraker's `[spoolman]` is enabled. Remove the section from `moonraker.conf`. |
| Slot card: *Material/colour go to the ACE after the print* | The bridge never changes slot data while printing; it sends them (ACEPRO `ACE_SET_SLOT`, Rinkhals `MMU_GATE_MAP`) when the print ends. |
| Orca's sync button picks Anycubic profiles, not the `SM…` ones | ACEPRO's own `lane_data` sync is on and overwrites the bridge's. Set `[ace] moonraker_lane_sync_enabled: False` ([installation](installation.md#b--klipper-on-a-raspberry-pi-with-acepro)). |
| Plugin: *The ACE purge is missing in Orca's numbers* | Klipper + ACEPRO: the printer profile's change-filament G-code is the old one (no `EXTERNAL_PURGE`). Replace it, see [installation](installation.md#orca-printer-profile). |
| Spool not offered when assigning | Its vendor is the template vendor (`Template`, or `Vorlage` in installs before 3.12) or the spool is archived. |
| *ACE reports …, assigned is …* / *colour differs* | Spoolman's material or colour differs from what the ACE reads. For Anycubic spools use the ACE's hex colour. |
| Consumption not booked | See *Open bookings*. Spoolman down → retried automatically every 30 s. |
| Wrong amount booked | Send the raw recording (`/api/telemetry/<file>`) and the `/api/jobs` entry in an issue. |
| Dryer starts colder than expected | The bridge never exceeds the most sensitive loaded filament (*Dry max.*, template, material default) or the ACE's maximum. The *Dryer* page shows which slot sets the limit. |

## Rinkhals

| Problem | Cause / solution |
|---|---|
| ACE card shows no purge multiplier (*not read yet*) | The bridge reads GoKlipper's ACE configuration every 10 minutes through Moonraker (`/printer/filament_hub/get_config`). Rinkhals' Moonraker must be reachable; the bridge log says *ACE settings not readable* with the reason. |
| *A print is running – unlock the change first* | On Rinkhals the ACE settings change during a print only after you confirm; the web UI and the app ask. Through the API send `"confirm_printing": true`. |
| Slot card / Orca panel: *no material is set at the printer – the print gets cancelled* | GoKlipper cancels a print that uses a slot with an empty material. Assign a spool (the bridge sends material and colour with `MMU_GATE_MAP` — not while printing, and never for slots with an Anycubic RFID tag) or set it on the printer display. |
| Assigned spool, but the printer display keeps the old material | Slots with an Anycubic RFID tag are refused by Rinkhals — the tag wins. Untagged slots take the value about 20 s later. |
| *Firmware purge* in the Orca preview differs from what was booked | The model learns from finished Orca prints (offset and first load). After a few prints it fits better; see [findings](findings.md). |
| Camera stutters (1–2 fps) during a print | Intended: the bridge lowers the frame rate while the printer's CPU is above `CAMERA_CPU_HIGH` (97 %) — the stock firmware needs it for printing. The corner shows *throttled*. |
| No *Reload Klipper* button | Rinkhals does not allow a firmware restart from outside; switch the printer off and on. |
| Auto-PA, Z offset, resume, clog detection missing | These need Klipper modules and are not available on the stock firmware ([what works where](../README.md#what-works-on-which-setup)). |

## Orca

| Problem | Cause / solution |
|---|---|
| *Orca base profile “…” not found in Orca* | No Orca system profile has that name (case and an optional `@System` are ignored since plugin 0.6.1). Pick it from the list in the filament editor. With *(fallback …)*: Spoolman names no base profile, the `Generic <material> @System` fallback is missing in Orca — set *Orca base profile* on the filament or template. |
| *no Orca base profile in Spoolman and no material* | Neither the filament nor a template names a base profile and the filament has no material. Set the material, *Orca base profile*, or run `spoolman_setup.py` once (creates the templates). |
| `SM…` profiles missing in Orca | Restart Orca (profiles are read at start-up). Check the Orca user folder setting (`default` without login). |
| Sync button selects *Generic PLA* instead of `SM…` | You are not running the orca-kobra build, or the printer agent is not *Moonraker*. |
| Panel: *Filament N in Orca is “…” – expected “…”* | Press Orca's sync button, or select the profile manually. |
| No *Planned usage* in the panel | The Orca build lacks patch 0003 (footer says so) — update via the orca-kobra launcher. Otherwise slice again; the preview hides when the slice result is outdated. |
| Preview says *not enough* but the spool is full | Remaining weight in Spoolman is wrong. Weigh the spool and correct *Remaining weight* in the shelf. |
| Status *MQTT / HA* yellow | The broker is unreachable or refuses the login — the line shows the reason; check `MQTT_HOST`, `MQTT_PORT`, `MQTT_USER`/`MQTT_PASSWORD`. The bridge retries every 15 s. |
| Home Assistant shows no *Kobra S1* device | MQTT integration in Home Assistant set up, discovery prefix `homeassistant` (or the same as `MQTT_DISCOVERY`)? `MQTT_DISCOVERY` must not be empty. |
| Status *Room sensor* yellow | No value for 2 h on `ROOM_SENSOR_TOPIC` — check the topic name (e.g. in Zigbee2MQTT) and that the payload has `humidity`. Until then the bridge uses `ROOM_RH`. |
| A spool says *drying recommended* but it is dry | The estimate cannot know how the spool was stored before. Dry it once (or *Dried elsewhere …* on the spool card); new spools count as wet only if *Dry new spools first* is on. |

## Useful commands

```bash
docker logs -f ace-lane-bridge                      # bridge log (setup code, bookings, warnings)
curl -s http://<docker-host>:7913/api/health | jq   # status
curl -s http://<docker-host>:7913/api/auth/status   # setup_required = nothing paired yet
curl -s "http://<pi-ip>:7125/printer/objects/query?ace&ace_instance_0"   # what ACEPRO reports (Klipper)
curl -s "http://<printer-ip>:7125/printer/objects/query?mmu&filament_hub"  # what Rinkhals reports
grep kobra-spoolman ~/.config/OrcaSlicer/log/python_*.log | tail
```
