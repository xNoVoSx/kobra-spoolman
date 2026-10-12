# Fehlersuche

[English](../troubleshooting.md) · [Zurück zur README](../../README.de.md)

Zuerst in die Logs schauen: das Bridge-Log (`docker logs ace-lane-bridge` oder Portainer → Logs) und
für Orca `~/.config/OrcaSlicer/log/python_*.log`.

## Koppeln und Schlüssel

| Problem | Ursache / Lösung |
|---|---|
| Die Weboberfläche fragt nach einem Code, ich habe keinen | Erstes Gerät: Der Einrichtungscode steht im Bridge-Log (`Setup code: …` – das Log ist englisch –, bei jedem Start, solange nichts gekoppelt ist). Sonst an einem gekoppelten Gerät einen Code holen: *Geräte → Gerät hinzufügen*. Ein altes `APP_TOKEN` geht auch (*Mit altem APP_TOKEN koppeln*). |
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
| Weboberfläche: *Kobra S1 · Offline* | Moonraker nicht erreichbar oder Klipper nicht bereit. `MOONRAKER_URL` prüfen, `http://<drucker-oder-pi-ip>:7125/server/info` öffnen; unter Klipper nach Not-Aus/Fehler *Klipper neu laden*, unter Rinkhals den Drucker aus- und einschalten. |
| Weboberfläche: *Spoolman getrennt* | `SPOOLMAN_URL` prüfen. Im selben Stack den Servicenamen nehmen (`http://spoolman:8000`). |
| Bridge startet nicht, `PermissionError` bei `/data` | Das Image läuft als Benutzer 1000. Den Datenordner für ihn beschreibbar machen oder `user: "0:0"` im Dienst ergänzen. |
| Orca-Panel: *Bridge nicht erreichbar* | Bridge-Adresse unter Plugins → Kobra Spoolman → Konfiguration eintragen. |
| Orca-Panel erscheint nicht | *Kobra Spoolman* im Plugins-Dialog ausführen; Orca-Log prüfen. |

## Slots und Drucken

| Problem | Ursache / Lösung |
|---|---|
| Warnung *…doppelt gebucht* | Moonrakers `[spoolman]` ist aktiv. Den Abschnitt aus `moonraker.conf` entfernen. |
| Slot-Karte: *Material/Farbe gehen nach dem Druck an die ACE* | Während eines Drucks ändert die Bridge nie Slot-Daten; sie schickt sie (ACEPRO `ACE_SET_SLOT`, Rinkhals `MMU_GATE_MAP`), sobald der Druck endet. |
| Orcas Sync-Knopf wählt Anycubic-Profile statt der `SM…`-Profile | ACEPROs eigener `lane_data`-Sync ist an und überschreibt die Daten der Bridge. `[ace] moonraker_lane_sync_enabled: False` setzen ([Installation](installation.md#b--klipper-auf-einem-raspberry-pi-mit-acepro)). |
| Plugin: *Spülen der ACE fehlt in Orcas Zahlen* | Klipper + ACEPRO: Der Filamentwechsel-G-Code des Druckerprofils ist der alte (ohne `EXTERNAL_PURGE`). Ersetzen, siehe [Installation](installation.md#orca-druckerprofil). |
| Spule steht nicht in der Auswahl | Ihr Hersteller ist der Vorlagen-Hersteller (`Vorlage` bzw. `Template`), oder die Spule ist archiviert. |
| *ACE meldet …, zugeordnet ist …* / *Farbe weicht ab* | Material oder Farbe in Spoolman weichen vom ACE-Tag ab. Bei Anycubic-Spulen den Hex-Wert der ACE nehmen. |
| Verbrauch nicht gebucht | Siehe *Offene Buchungen*. Spoolman weg → alle 30 s automatisch nachgeholt. |
| Falsche Menge gebucht | Die Rohaufzeichnung (`/api/telemetry/<datei>`) und den Eintrag aus `/api/jobs` in ein Issue packen. |
| Trockner startet kühler als gedacht | Die Bridge geht nie über das empfindlichste eingelegte Filament (*Trocknen max.*, Vorlage, Materialwert) oder das Maximum der ACE. Die Seite *Trockner* zeigt, welcher Slot die Grenze setzt. |

## Rinkhals

| Problem | Ursache / Lösung |
|---|---|
| ACE-Karte zeigt keinen Spül-Multiplikator (*noch nicht gelesen*) | Die Bridge liest GoKlippers ACE-Konfiguration alle 10 Minuten über Moonraker (`/printer/filament_hub/get_config`). Moonraker von Rinkhals muss erreichbar sein; das Bridge-Log nennt den Grund (*ACE settings not readable*). |
| *Es läuft ein Druck – Änderung erst nach dem Freischalten* | Unter Rinkhals ändern sich ACE-Einstellungen während eines Drucks erst nach Bestätigung; Weboberfläche und App fragen nach. Über die API `"confirm_printing": true` mitschicken. |
| Slot-Karte / Orca-Panel: *Am Drucker ist kein Material eingetragen – der Druck bricht ab* | GoKlipper bricht einen Druck ab, der einen Slot ohne Material nutzt. Spule zuordnen (die Bridge schickt Material und Farbe per `MMU_GATE_MAP` – nicht im Druck und nie für Slots mit Anycubic-RFID-Tag) oder am Drucker-Display eintragen. |
| Spule zugeordnet, aber das Drucker-Display zeigt das alte Material | Slots mit Anycubic-RFID-Tag lehnt Rinkhals ab – der Tag gewinnt. Slots ohne Tag übernehmen den Wert etwa 20 s später. |
| *Spülen Firmware* in der Orca-Vorschau weicht von der Buchung ab | Das Modell lernt aus fertigen Orca-Drucken (Versatz und erstes Laden). Nach ein paar Drucken passt es besser; siehe [Befunde](../findings.md) (englisch). |
| Kamera ruckelt (1–2 fps) im Druck | Gewollt: Die Bridge senkt die Bildrate, solange die Drucker-CPU über `CAMERA_CPU_HIGH` (97 %) liegt – die Original-Firmware braucht sie zum Drucken. In der Ecke steht *gedrosselt*. |
| Kein Knopf *Klipper neu laden* | Rinkhals erlaubt keinen Firmware-Neustart von außen; den Drucker aus- und einschalten. |
| Auto-PA, Z-Versatz, Fortsetzen, Verstopfung fehlen | Die brauchen Klipper-Module und gibt es auf der Original-Firmware nicht ([was wo geht](../../README.de.md#was-auf-welchem-aufbau-geht)). |

## Orca

| Problem | Ursache / Lösung |
|---|---|
| *Orca-Basisprofil „…“ nicht in Orca gefunden* | Kein Orca-Systemprofil heißt so (Groß/klein und ein optionales `@System` zählen seit Plugin 0.6.1 nicht). Aus der Liste im Filament-Editor wählen. Mit *(Ersatz …)*: Spoolman nennt kein Basisprofil, und der Ersatz `Generic <Material> @System` fehlt in Orca – *Orca-Basisprofil* am Filament oder an der Vorlage setzen. |
| *kein Orca-Basisprofil in Spoolman und kein Material* | Weder Filament noch Vorlage nennen ein Basisprofil, und das Filament hat kein Material. Material oder *Orca-Basisprofil* setzen, oder einmal `spoolman_setup.py` laufen lassen (legt die Vorlagen an). |
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
docker logs -f ace-lane-bridge                      # Bridge-Log (Setup code, Buchungen, Warnungen)
curl -s http://<docker-host>:7913/api/health | jq   # Status
curl -s http://<docker-host>:7913/api/auth/status   # setup_required = noch nichts gekoppelt
curl -s "http://<pi-ip>:7125/printer/objects/query?ace&ace_instance_0"   # was ACEPRO meldet (Klipper)
curl -s "http://<drucker-ip>:7125/printer/objects/query?mmu&filament_hub"  # was Rinkhals meldet
grep kobra-spoolman ~/.config/OrcaSlicer/log/python_*.log | tail
```

## Fehler melden

Weboberfläche → *Logs* → **Fehler melden**: kopiert die Diagnose (Versionen, Aufbau, Verbindungen, Slots,
Einstellungen und die letzten Log-Zeilen) und öffnet das [Fehlerformular](https://github.com/xNoVoSx/kobra-spoolman/issues/new?template=bug_report.yml)
auf GitHub – dort unter *Diagnostics* einfügen. Hostnamen, IP-Adressen, E-Mail-Adressen und Schlüssel sind entfernt,
Geheimnisse stehen nur als *set* drin; vor dem Absenden trotzdem kurz drüberschauen. Ohne Weboberfläche:
`curl -s -H "Authorization: Bearer <schlüssel>" http://<docker-host>:7913/api/diagnostics`. Probleme mit dem
gepatchten OrcaSlicer gehören zu [orca-kobra](https://github.com/xNoVoSx/orca-kobra/issues).
