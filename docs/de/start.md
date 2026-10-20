# Hier anfangen

[English](../start.md) · [Zurück zur README](../../README.de.md)

Fang mit dem Kern an und hol dir dazu, was du willst, wann du willst. Jede Funktion lässt sich später auf der Seite
**Funktionen** an- und ausschalten (Weboberfläche, oder *Mehr → Funktionen* in der App); die ausführliche Anleitung
Schritt für Schritt ist [installation.md](installation.md).

## Ziel 1 – Spoolman weiß, was in der ACE steckt und was jeder Druck verbraucht hat (etwa 5 Minuten)

Du brauchst einen Anycubic-Drucker mit ACE, den Moonraker erreicht – einen Kobra S1 oder Kobra 3 mit Original-Firmware
und [Rinkhals](https://github.com/rinkhals-community/Rinkhals) oder einen Kobra S1 mit Klipper und ACEPRO auf einem
Raspberry Pi ([unterstützte Drucker](../../README.de.md#unterstützte-drucker)) – und ein laufendes
[Spoolman](https://github.com/Donkie/Spoolman). Läuft **Home Assistant OS**? Dann statt Schritt 1 das Community-Add-on
[MineTech13/ha-addons](https://github.com/MineTech13/ha-addons) installieren (eigene Anleitung, dieselbe Bridge) und mit
Schritt 2 in der HA-Seitenleiste weitermachen.

1. **Bridge hinzufügen** – in den Stack, in dem Spoolman läuft ([Beispiel](../../bridge/compose.yaml)):
   ```yaml
     ace-lane-bridge:
       image: ghcr.io/xnovosx/ace-lane-bridge:latest
       restart: unless-stopped
       ports: ["7913:7913"]
       volumes: ["./bridge-data:/data"]
       environment:
         MOONRAKER_URL: "http://<drucker-ip>:7125"   # Rinkhals; Klipper: http://<pi-ip>:7125
         SPOOLMAN_URL: "http://spoolman:8000"
   ```
2. **Browser koppeln:** `http://<docker-host>:7913` öffnen und den Einrichtungscode aus dem Bridge-Log eingeben
   (`Setup code: …`).
3. **Einrichtung:** Die Weboberfläche öffnet die Einrichtungsseite. Sie zeigt, was die Bridge gefunden hat – Drucker und
   Aufbau, ACE, Spoolman, Kamera – und lässt dich gleich oder später mehr dazunehmen. Nimmst du nichts dazu, bist du fertig.

**Was du jetzt hast:** Spulen den ACE-Slots zuordnen (Material und Farbe gehen an die ACE), den Verbrauch jedes Drucks
pro Spule gebucht, Kamera und Druckvorschau und die Daten, die Orcas Sync-Knopf liest. Spulen mit einem unserer
RFID-Tags werden beim Einlegen von selbst zugeordnet – die Tags schreibt die App (Ziel 2).

**Läuft es?** Eine Minute nach dem Start:

- [ ] Die Liste *Status* in der Übersicht (oder `/api/health`) zeigt Drucker und Spoolman als verbunden; im Kopf steht nach dem ersten Druck
      der Name deines Druckers (bis dahin *Drucker*; einstellbar unter *Einstellungen → Druckername*).
- [ ] Die vier Slot-Karten zeigen, was die ACE meldet (Material, Farbe) – ordne ihnen deine Spulen zu.
- [ ] Nach einem Druck steht er unter *Drucke* mit den Millimetern je Slot, und das Verbrauchsgewicht der Spulen in
      Spoolman ist um genau so viel gestiegen. In der Übersicht steht keine Karte *Offene Buchungen*.

## Ziel 2 und mehr – dazunehmen, was du willst

| Funktion | Was du bekommst | Braucht | Einschalten | Last am Drucker | Rinkhals | Klipper |
|---|---|---|---|---|---|---|
| Android-App | schreibt die RFID-Tags, Meldungen des Druckers aufs Handy, alles aus der Weboberfläche | Android mit NFC | *Geräte → Gerät hinzufügen*, QR-Code mit der App scannen ([App](../android-app.md)) | keine – die App fragt nur die Bridge | ja | ja |
| Drucker-Display | die Weboberfläche für den Touchscreen des Druckers | der Klipper-Rechner startet den Kiosk | Kiosk installieren ([Display](usage.md#das-display-des-druckers)) | keine | – | ja |
| Orca-Plugin | Spoolman-Profile in Orca, Verbrauchsvorschau nach dem Slicen, Rückabgleich | OrcaSlicer, für die Vorschau der Build [orca-kobra](https://github.com/xNoVoSx/orca-kobra) | Plugin installieren ([Installation](installation.md#6-orca-plugin-kobra-spoolman)) | keine | ja | ja |
| Kamera | die Druckerkamera in Web, App und Display | eine Kamera am Drucker | von Anfang an an; *Funktionen* | eine Verbindung zum Drucker, egal wie viele zuschauen | ja | ja |
| Druckvorschau | 3D-Modell, Restmenge pro Spule, Schichtfortschritt | – | von Anfang an an; *Funktionen* | liest die Druckdatei einmal von Moonraker | ja | ja |
| Automatisch trocknen | feuchte Spulen werden beim Einlegen getrocknet | ACE mit Trockner | *Funktionen* | keine | ja | ja |
| Druckaufzeichnungen | Rohdaten jedes Drucks, um die Buchungen später nachzuprüfen | – | *Funktionen* | keine | ja | ja |
| Home Assistant / MQTT | Drucker, Slots und Spulen als Home-Assistant-Geräte | ein MQTT-Broker | `MQTT_HOST` und Zugangsdaten ([Konfiguration](../configuration.md)) oder das [HA-Add-on](installation.md#variante-b--home-assistant-add-on) | keine | ja | ja |
| KI-Fehldruck-Erkennung | **experimentell** – warnt oder pausiert bei Spaghetti und Fehldrucken | der Container kobra-vision und die Kamera | `VISION_URL` ([KI-Erkennung](../vision.md)) | keine – die Bridge schaut sich die Kamerabilder an | ja | ja |
| Auto-PA | Pressure Advance je Geschwindigkeit aus Spoolman, gemessen, wenn es fehlt | Klipper-Weg mit unseren Drucker-Modulen | an, wenn das Modul installiert ist; *Funktionen* | etwa 2 Minuten Messung pro neuem Filament | – | ja |
| Z-Versatz pro Filament | Z-Versatz der ersten Schicht vom Filament in Spoolman | Klipper-Weg, Makro `KOBRA_START` | an, wenn installiert; *Funktionen* | keine | – | ja |
| Fortsetzen nach Stromausfall | setzt einen unterbrochenen Druck in der richtigen Höhe fort | Klipper-Weg, Modul `kobra_resume` | an, wenn installiert; *Funktionen* | schreibt regelmäßig die Druckposition | – | ja |
| Verstopfung | vergleicht Extruder und Filament-Encoder, warnt oder pausiert | Klipper-Weg, Modul `kobra_clog` | an, wenn installiert; *Funktionen* | keine | – | ja |
| Wechsel-Hotends | PID, Düsengröße und Z-Korrektur je Hotend, Auto-PA je Düse, eine Datei für die falsche Düse wird gestoppt | Klipper-Weg, Modul `kobra_nozzle` | an, wenn installiert; *Funktionen* | keine | – | ja |
| Endlosspule | wird eine Spule leer, lädt die ACE eine passende andere | ACEPRO (Klipper) oder die Firmware (Rinkhals) | Klipper: *Funktionen*; Rinkhals: die ACE-Karte | keine | ja | ja |
| Nach anderer Spule fragen | keine passende Spule, wenn eine leer wird → der Druck wartet über dem Abfallkanal und fragt, mit welcher geladenen Spule es weitergeht | Klipper-Weg, Modul `kobra_spare` (mit der Endlosspule) | an, wenn installiert; *Funktionen* | keine | – | ja |
| Licht und Töne | Licht im Drucker und Piepser bei Ereignissen, nachts leise | Klipper-Weg, App kobra-io auf dem Drucker | an, wenn installiert; *Funktionen* | keine | – | ja |

Was die Installation festlegt (Umgebungsvariablen des Containers, Optionen des Home-Assistant-Add-ons), zeigt die Seite
*Funktionen* an und wird dort geändert – nie auf der Seite selbst.

## Was ohne was geht

| Ohne … | Was trotzdem geht | Was fehlt |
|---|---|---|
| das Orca-Plugin | alles in der Bridge: Buchungen, Slots, Trockner, App, Kamera; Orcas Sync-Knopf liest weiterhin Material und Farbe der Slots | Orca-Profile aus Spoolman (und damit das passende Profil je Slot), Seitenpanel, Rückabgleich |
| den orca-kobra-Build (offizielles Orca) | das Plugin: Profile, Seitenpanel, Rückabgleich | die Verbrauchsvorschau nach dem Slicen, das automatische Profil beim Sync-Knopf (bis Orca die Patches übernimmt) |
| die App | die Weboberfläche am Handy kann dasselbe, bis auf NFC | RFID-Tags schreiben, Meldungen im Hintergrund, das Widget |
| NFC-Tags | Spulen von Hand in Web oder App zuordnen (passende Spulen stehen oben) | Spulen, die sich beim Einlegen selbst zuordnen |
| eine Kamera | alles andere | das Bild in Web, App und Display, die KI-Erkennung |
| MQTT / Home Assistant | alles andere | die Geräte in Home Assistant |
| unsere Klipper-Module (Aufbau B) | alles von Aufbau A | Auto-PA, Z-Versatz pro Filament, Fortsetzen nach Stromausfall, Verstopfung |

## Schon eine ältere Version im Einsatz?

Nach einem Update ändert sich nichts: Jeder Schalter bleibt, wie er war. Die Übersicht (und die App einmal) zeigt einen
Hinweis auf die neue Seite *Funktionen*, und die Einrichtung lässt sich von dort jederzeit starten.
