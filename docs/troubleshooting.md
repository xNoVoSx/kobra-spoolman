# Troubleshooting

[Deutsch](de/troubleshooting.md) · [Back to README](../README.md)

Start with the logs: the bridge log (`docker logs ace-lane-bridge` or Portainer → Logs) and, for
Orca, `~/.config/OrcaSlicer/log/python_*.log`.

## Pairing and keys

| Problem | Cause / solution |
|---|---|
| Web UI asks for a code, I have none | First device: the setup code is in the bridge log (`Einrichtungscode: …`, printed at every start while nothing is paired). Otherwise get a code from a paired device: *Geräte → Gerät hinzufügen*. An old `APP_TOKEN` also works (*Mit altem APP_TOKEN koppeln*). |
| *Code falsch oder abgelaufen* | Codes are valid 5 minutes and only once. Get a new one. |
| *Zu viele falsche Codes – eine Minute warten* | 5 wrong codes within a minute lock pairing for 60 s. |
| Browser suddenly asks to pair again | Its key was removed under *Geräte*, or the bridge's data folder (`devices.json`) was lost. Pair again. |
| Lost a phone | *Geräte* → **Entfernen** — its key stops working immediately. |
| Buttons lead to the pairing screen | You chose *Nur ansehen*. Pair the browser (chip *nur ansehen – koppeln* at the top). |
| Orca: *Übernehmen nach Spoolman geht erst, wenn das Plugin … gekoppelt ist* | Enter a pairing code in the panel (*Plugin koppeln*), then save the profile again. Plugin older than 0.4.0? Update it — bridge 2.6.0+ refuses back-sync without a key. |
| App: *Die Bridge kennt dieses Gerät nicht mehr* | The app's key was removed or the bridge was set up anew. Settings → pair again. |
| App shows nothing, requests time out (Android 17) | The app needs *Nearby devices* (local network). Allow it under Android settings → Apps → Kobra Spoolman → Permissions. |

## Connections

| Problem | Cause / solution |
|---|---|
| Web UI: *Kobra S1 · Offline* | Moonraker not reachable. Check `MOONRAKER_URL`, open `http://<printer-ip>:7125/server/info`. |
| Web UI: *Spoolman getrennt* | Check `SPOOLMAN_URL`. Inside the same stack use the service name (`http://spoolman:8000`). |
| Bridge does not start, `PermissionError` on `/data` | The image runs as user 1000. Make the data folder writable for it or add `user: "0:0"` to the service. |
| Orca panel: *Bridge nicht erreichbar* | Set the bridge address under Plugins → Kobra Spoolman → Configuration. |
| Orca panel does not appear | Run *Kobra Spoolman* from the Plugins dialog; check the Orca log. |

## Slots and printing

| Problem | Cause / solution |
|---|---|
| Warning *…doppelt gebucht* | Moonraker's `[spoolman]` is enabled or the firmware's `spoolman_support` is on. Disable it. |
| Print fails ~5 min after start, Mainsail: `runtime error: index out of range [0] with length 0` | A slot used by the print has no material at the printer (spool without tag, nothing entered at the display). Assign the spool in the web UI or app (material and colour go to the ACE) or enter them at the display. Details: [findings](findings.md#print-start-and-ace-slot-info-2026-09-30). |
| Slot card: *Material/Farbe gehen nach dem Druck an die ACE* | The bridge never changes slot data while printing; it sends them when the print ends. |
| Spool not offered when assigning | Its vendor is the template vendor (`Vorlage`) or the spool is archived. |
| *ACE meldet …, zugeordnet ist …* / *Farbe weicht ab* | Spoolman's material or colour differs from what the ACE reads. For Anycubic spools use the ACE's hex colour. |
| Consumption not booked | See *Offene Buchungen*. Spoolman down → retried automatically every 30 s. |
| Wrong amount booked | Send the raw recording (`/api/telemetry/<file>`) and the `/api/jobs` entry in an issue. |
| Dryer starts colder than expected | The bridge never exceeds the most sensitive loaded filament (*Trocknen max.*, template, material default) or the ACE's maximum. The *Trockner* page shows which slot sets the limit. |

## Orca

| Problem | Cause / solution |
|---|---|
| *Orca-Basisprofil „…“ nicht gefunden* | Name must match an Orca system profile exactly (case, spaces, `@…`). Pick it from the list in the filament editor. |
| `SM…` profiles missing in Orca | Restart Orca (profiles are read at start-up). Check the Orca user folder setting (`default` without login). |
| Sync button selects *Generic PLA* instead of `SM…` | You are not running the orca-kobra build, or the printer agent is not *Moonraker*. |
| Panel: *Filament N ist „…“ – erwartet „…“* | Press Orca's sync button, or select the profile manually. |
| No *Geplanter Verbrauch* in the panel | The Orca build lacks patch 0003 (footer says so) — update via the orca-kobra launcher. Otherwise slice again; the preview hides when the slice result is outdated. |
| Preview says *reicht nicht* but the spool is full | Remaining weight in Spoolman is wrong. Weigh the spool and correct *Restgewicht* in the shelf. |

## Useful commands

```bash
docker logs -f ace-lane-bridge                      # bridge log (setup code, bookings, warnings)
curl -s http://<docker-host>:7913/api/health | jq   # status
curl -s http://<docker-host>:7913/api/auth/status   # setup_required = nothing paired yet
curl -s "http://<printer-ip>:7125/printer/objects/query?mmu=gate_status,gate_material,gate_color"
grep kobra-spoolman ~/.config/OrcaSlicer/log/python_*.log | tail
```
