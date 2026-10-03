# Fehlersuche

[English](../troubleshooting.md) · [Zurück zur README](../../README.de.md)

Zuerst in die Logs schauen: das Bridge-Log (`docker logs ace-lane-bridge` oder Portainer → Logs) und
für Orca `~/.config/OrcaSlicer/log/python_*.log`.

## Koppeln und Schlüssel

| Problem | Ursache / Lösung |
|---|---|
| Die Weboberfläche fragt nach einem Code, ich habe keinen | Erstes Gerät: Der Einrichtungscode steht im Bridge-Log (`Einrichtungscode: …`, bei jedem Start, solange nichts gekoppelt ist). Sonst an einem gekoppelten Gerät einen Code holen: *Geräte → Gerät hinzufügen*. Ein altes `APP_TOKEN` geht auch (*Mit altem APP_TOKEN koppeln*). |
| *Code falsch oder abgelaufen* | Codes gelten 5 Minuten und nur einmal. Neuen holen. |
| *Zu viele falsche Codes – eine Minute warten* | 5 falsche Codes innerhalb einer Minute sperren das Koppeln für 60 s. |
| Der Browser will plötzlich neu koppeln | Sein Schlüssel wurde unter *Geräte* entfernt, oder der Datenordner der Bridge (`devices.json`) ist weg. Neu koppeln. |
| Handy verloren | *Geräte* → **Entfernen** – der Schlüssel gilt sofort nicht mehr. |
| Knöpfe führen zum Koppeln | Du hast *Nur ansehen* gewählt. Den Browser koppeln (oben *nur ansehen – koppeln*). |
| Orca: *Übernehmen nach Spoolman geht erst, wenn das Plugin … gekoppelt ist* | Im Panel einen Kopplungscode eingeben (*Plugin koppeln*), dann das Profil nochmal speichern. Plugin älter als 0.4.0? Aktualisieren – ab Bridge 2.6.0 geht Rücksync nur mit Schlüssel. |
| App: *Die Bridge kennt dieses Gerät nicht mehr* | Der Schlüssel der App wurde entfernt oder die Bridge neu eingerichtet. Einstellungen → neu koppeln. |
| App zeigt nichts, Anfragen laufen ins Leere (Android 17) | Die App braucht *Geräte in der Nähe* (lokales Netz). In den Android-Einstellungen → Apps → Kobra Spoolman → Berechtigungen erlauben. |

## Verbindungen

| Problem | Ursache / Lösung |
|---|---|
| Weboberfläche: *Kobra S1 · Offline* | Moonraker nicht erreichbar. `MOONRAKER_URL` prüfen, `http://<drucker-ip>:7125/server/info` öffnen. |
| Weboberfläche: *Spoolman getrennt* | `SPOOLMAN_URL` prüfen. Im selben Stack den Servicenamen nehmen (`http://spoolman:8000`). |
| Bridge startet nicht, `PermissionError` bei `/data` | Das Image läuft als Benutzer 1000. Den Datenordner für ihn beschreibbar machen oder `user: "0:0"` im Dienst ergänzen. |
| Orca-Panel: *Bridge nicht erreichbar* | Bridge-Adresse unter Plugins → Kobra Spoolman → Konfiguration eintragen. |
| Orca-Panel erscheint nicht | *Kobra Spoolman* im Plugins-Dialog ausführen; Orca-Log prüfen. |

## Slots und Drucken

| Problem | Ursache / Lösung |
|---|---|
| Warnung *…doppelt gebucht* | Moonrakers `[spoolman]` ist aktiv oder `spoolman_support` der Firmware ist an. Abschalten. |
| Druck bricht ~5 min nach dem Start ab, Mainsail: `runtime error: index out of range [0] with length 0` | Ein Slot des Drucks hat am Drucker kein Material (Spule ohne Tag, nichts am Display eingetragen). Die Spule in Weboberfläche oder App zuordnen (Material und Farbe gehen an die ACE) oder am Display eintragen. Details: [Befunde](../findings.md#print-start-and-ace-slot-info-2026-09-30) (englisch). |
| Slot-Karte: *Material/Farbe gehen nach dem Druck an die ACE* | Während eines Drucks ändert die Bridge nie Slot-Daten; sie schickt sie, sobald der Druck endet. |
| Spule steht nicht in der Auswahl | Ihr Hersteller ist der Vorlagen-Hersteller (`Vorlage`), oder die Spule ist archiviert. |
| *ACE meldet …, zugeordnet ist …* / *Farbe weicht ab* | Material oder Farbe in Spoolman weichen vom ACE-Tag ab. Bei Anycubic-Spulen den Hex-Wert der ACE nehmen. |
| Verbrauch nicht gebucht | Siehe *Offene Buchungen*. Spoolman weg → alle 30 s automatisch nachgeholt. |
| Falsche Menge gebucht | Die Rohaufzeichnung (`/api/telemetry/<datei>`) und den Eintrag aus `/api/jobs` in ein Issue packen. |
| Trockner startet kühler als gedacht | Die Bridge geht nie über das empfindlichste eingelegte Filament (*Trocknen max.*, Vorlage, Materialwert) oder das Maximum der ACE. Die Seite *Trockner* zeigt, welcher Slot die Grenze setzt. |

## Orca

| Problem | Ursache / Lösung |
|---|---|
| *Orca-Basisprofil „…“ nicht gefunden* | Der Name muss exakt einem Orca-Systemprofil entsprechen (Groß/klein, Leerzeichen, `@…`). Aus der Liste im Filament-Editor wählen. |
| `SM…`-Profile fehlen in Orca | Orca neu starten (Profile werden beim Start gelesen). Orca-Benutzerordner prüfen (`default` ohne Anmeldung). |
| Sync-Knopf wählt *Generic PLA* statt `SM…` | Nicht der orca-kobra-Build, oder Printer Agent ist nicht *Moonraker*. |
| Panel: *Filament N ist „…“ – erwartet „…“* | Orcas Sync-Knopf drücken oder das Profil von Hand wählen. |
| Kein *Geplanter Verbrauch* im Panel | Dem Orca-Build fehlt Patch 0003 (steht in der Fußzeile) – über den orca-kobra-Starter aktualisieren. Sonst neu slicen; die Vorschau verschwindet, wenn das Slice-Ergebnis veraltet ist. |
| Vorschau sagt *reicht nicht*, die Spule ist aber voll | Restgewicht in Spoolman stimmt nicht. Spule wiegen und *Restgewicht* im Regal korrigieren. |
| Status *MQTT / HA* gelb | Broker nicht erreichbar oder Anmeldung abgelehnt – die Zeile nennt den Grund; `MQTT_HOST`, `MQTT_PORT`, `MQTT_USER`/`MQTT_PASSWORD` prüfen. Die Bridge versucht es alle 15 s neu. |
| Home Assistant zeigt kein Gerät *Kobra S1* | MQTT-Integration in Home Assistant eingerichtet, Discovery-Präfix `homeassistant` (bzw. gleich `MQTT_DISCOVERY`)? `MQTT_DISCOVERY` darf nicht leer sein. |
| Status *Raumsensor* gelb | Seit 2 h kein Wert auf `ROOM_SENSOR_TOPIC` – Themenname (z. B. in Zigbee2MQTT) prüfen und ob die Nachricht `humidity` enthält. Bis dahin rechnet die Bridge mit `ROOM_RH`. |
| Spule sagt *trocknen empfohlen*, ist aber trocken | Die Schätzung weiß nicht, wie die Spule vorher gelagert war. Einmal trocknen (oder *Außerhalb getrocknet …* auf der Spulenkarte); neue Spulen gelten nur als feucht, wenn *Neue Spulen zuerst trocknen* an ist. |

## Nützliche Befehle

```bash
docker logs -f ace-lane-bridge                      # Bridge-Log (Einrichtungscode, Buchungen, Warnungen)
curl -s http://<docker-host>:7913/api/health | jq   # Status
curl -s http://<docker-host>:7913/api/auth/status   # setup_required = noch nichts gekoppelt
curl -s "http://<drucker-ip>:7125/printer/objects/query?mmu=gate_status,gate_material,gate_color"
grep kobra-spoolman ~/.config/OrcaSlicer/log/python_*.log | tail
```
