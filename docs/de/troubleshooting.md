# Fehlersuche

[English](../troubleshooting.md) · [Zurück zur README](../../README.de.md)

| Problem | Ursache / Lösung |
|---|---|
| Slot-Seite: roter Punkt bei *Drucker* | Moonraker nicht erreichbar. `MOONRAKER_URL` prüfen, `http://<drucker-ip>:7125/server/info` öffnen. |
| Slot-Seite: roter Punkt bei *Spoolman* | `SPOOLMAN_URL` prüfen. Im selben Stack den Servicenamen nehmen (`http://spoolman:8000`). |
| Warnung *…doppelt gebucht* | Moonrakers `[spoolman]` ist aktiv oder die Firmware meldet `spoolman_support` ≠ `off`. Abschalten. |
| Spule steht nicht in der Auswahl | Ihr Hersteller ist der Vorlagen-Hersteller (`Vorlage`), oder die Spule ist archiviert. |
| *Material passt, Farbe nicht* | Die Farbe in Spoolman weicht vom ACE-Tag ab. Bei Anycubic-Spulen den Hex-Wert der ACE nehmen. |
| Orca-Panel: *Bridge nicht erreichbar* | Bridge-Adresse unter Plugins → Kobra Spoolman → Konfiguration eintragen. |
| Orca-Panel erscheint nicht | *Kobra Spoolman* im Plugins-Dialog ausführen; `~/.config/OrcaSlicer/log/python_*.log` ansehen. |
| *Orca-Basisprofil „…“ nicht gefunden* | Der Name muss exakt einem Orca-Systemprofil entsprechen (Groß/klein, Leerzeichen, `@…`). Am besten aus Orcas Filamentliste kopieren. |
| `SM…`-Profile fehlen in Orca | Orca neu starten (Profile werden nur beim Start gelesen). Einstellung *Orca-Benutzerordner* prüfen (`default` ohne Anmeldung). |
| Sync-Knopf wählt *Generic PLA* statt `SM…` | Nicht der orca-kobra-Build, oder der Printer Agent steht nicht auf *Moonraker*. |
| Panel: *Filament N ist „…“ – erwartet „…“* | Orcas Sync-Knopf drücken oder das Profil von Hand wählen. |
| Verbrauch nicht gebucht | Oben auf der Slot-Seite unter *Nicht gebucht* nachsehen. Spoolman weg → wird alle 30 s neu versucht. |
| Falsche Menge gebucht | Rohdaten (`/api/telemetry/<datei>`) und den Eintrag aus `/api/jobs` in einem Issue schicken. |

## Nützliche Befehle

```bash
docker logs -f ace-lane-bridge                      # Log der Bridge
curl -s http://<docker-host>:7913/api/health | jq   # Status
curl -s "http://<drucker-ip>:7125/printer/objects/query?mmu=gate_status,gate_material,gate_color"
grep kobra-spoolman ~/.config/OrcaSlicer/log/python_*.log | tail
```
