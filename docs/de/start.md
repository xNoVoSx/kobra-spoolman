# Hier anfangen

[English](../start.md) · [Zurück zur README](../../README.de.md)

Fang mit dem Kern an und hol dir dazu, was du willst, wann du willst. Jede Funktion lässt sich später auf der Seite
**Funktionen** an- und ausschalten (Weboberfläche, oder *Mehr → Funktionen* in der App); die ausführliche Anleitung
Schritt für Schritt ist [installation.md](installation.md).

## Ziel 1 – Spoolman weiß, was in der ACE steckt und was jeder Druck verbraucht hat (etwa 5 Minuten)

Du brauchst einen Kobra S1 mit ACE, den Moonraker erreicht – entweder die Original-Firmware mit
[Rinkhals](https://github.com/rinkhals-community/Rinkhals) oder Klipper mit ACEPRO auf einem Raspberry Pi – und ein
laufendes [Spoolman](https://github.com/Donkie/Spoolman).

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
| Endlosspule | wird eine Spule leer, lädt die ACE eine passende andere | Klipper-Weg, ACEPRO | an, wenn installiert; *Funktionen* | keine | – | ja |
| Licht und Töne | Licht im Drucker und Piepser bei Ereignissen, nachts leise | Klipper-Weg, App kobra-io auf dem Drucker | an, wenn installiert; *Funktionen* | keine | – | ja |

Was die Installation festlegt (Umgebungsvariablen des Containers, Optionen des Home-Assistant-Add-ons), zeigt die Seite
*Funktionen* an und wird dort geändert – nie auf der Seite selbst.

## Schon eine ältere Version im Einsatz?

Nach einem Update ändert sich nichts: Jeder Schalter bleibt, wie er war. Die Übersicht (und die App einmal) zeigt einen
Hinweis auf die neue Seite *Funktionen*, und die Einrichtung lässt sich von dort jederzeit starten.
