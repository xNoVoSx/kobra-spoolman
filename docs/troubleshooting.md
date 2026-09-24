# Troubleshooting

[Deutsch](de/troubleshooting.md) · [Back to README](../README.md)

| Problem | Cause / solution |
|---|---|
| Slot page: red dot at *Drucker* | Moonraker not reachable. Check `MOONRAKER_URL`, open `http://<printer-ip>:7125/server/info`. |
| Slot page: red dot at *Spoolman* | Check `SPOOLMAN_URL`. Inside the same stack use the service name (`http://spoolman:8000`). |
| Warning *…doppelt gebucht* | Moonraker's `[spoolman]` is enabled or the firmware reports `spoolman_support` ≠ `off`. Disable it. |
| Spool not offered in the picker | Its vendor is the template vendor (`Vorlage`) or the spool is archived. |
| *Material passt, Farbe nicht* | Spoolman colour differs from what the ACE reads. For Anycubic spools use the ACE's hex colour. |
| Orca panel: *Bridge nicht erreichbar* | Set the bridge address under Plugins → Kobra Spoolman → Configuration. |
| Orca panel does not appear | Run *Kobra Spoolman* from the Plugins dialog; check `~/.config/OrcaSlicer/log/python_*.log`. |
| *Orca-Basisprofil „…“ nicht gefunden* | Name must match an Orca system profile exactly (case, spaces, `@…`). Copy it from Orca's filament list. |
| `SM…` profiles missing in Orca | Restart Orca (profiles are read at start-up). Check the Orca user folder setting (`default` without login). |
| Sync button selects *Generic PLA* instead of `SM…` | You are not running the orca-kobra build, or the printer agent is not *Moonraker*. |
| Panel: *Filament N ist „…“ – erwartet „…“* | Press Orca's sync button, or select the profile manually. |
| Consumption not booked | See *Nicht gebucht* on the slot page (open items). Spoolman down → retried automatically every 30 s. |
| Wrong amount booked | Send the raw recording (`/api/telemetry/<file>`) and the `/api/jobs` entry in an issue. |

## Useful commands

```bash
docker logs -f ace-lane-bridge                      # bridge log
curl -s http://<docker-host>:7913/api/health | jq   # status
curl -s "http://<printer-ip>:7125/printer/objects/query?mmu=gate_status,gate_material,gate_color"
grep kobra-spoolman ~/.config/OrcaSlicer/log/python_*.log | tail
```
