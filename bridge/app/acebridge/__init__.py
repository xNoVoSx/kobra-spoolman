"""ace-lane-bridge v3 - Kobra S1 / ACE 2 Pro <-> Spoolman <-> OrcaSlicer."""

__version__ = "3.5.0"
__app_name__ = "ace-lane-bridge"
__description__ = "Kobra S1 mit ACE 2 Pro ↔ Spoolman ↔ OrcaSlicer"

# Neueste Version zuerst. Wird in der Weboberflaeche unter "Einstellungen" angezeigt.
CHANGELOG = [
    ("3.5.0", "2026-10-10", [
        "Ansicht fürs Display des Druckers (/display, 800×480): Start mit Slots und Trockner, Druckansicht mit "
        "Vorschaubild der Datei (kommt bei Druckstart von selbst), alle Schalter, Frage nach Stromausfall",
        "Alle Schalter der Klipper-Module an einer Stelle (/api/switches): Auto-PA, Z-Versatz, Endlosspule, "
        "Stromausfall, Verstopfung, Licht und Töne",
        "Das Display koppelt sich wie jedes Gerät mit einem Code (Ziffernfeld)",
    ]),
    ("3.4.0", "2026-10-10", [
        "Verstopfung erkennen: Klipper vergleicht im Druck die Förderung des Extruders mit dem Encoder am Filament-Eingang; "
        "bei Verdacht rote Meldung und Alarm in der App, bis wieder normal gefördert wird",
        "ACE-Seite: Schalter „Verstopfung erkennen“, bei Verdacht nur warnen (Standard) oder pausieren",
        "App 1.12.0: derselbe Schalter im ACE-Fenster",
    ]),
    ("3.3.0", "2026-10-10", [
        "Fortsetzen nach Stromausfall: Karte „Druck unterbrochen“ mit Live-Bild und Alarm in der App; Fortsetzen nur mit "
        "Rückfrage – der Drucker heizt erst auf Drucktemperatur, hebt langsam an, tastet die Höhe auf dem Teil an und "
        "druckt an der Stelle weiter; Verwerfen löscht die Sicherung",
        "ACE-Seite: Schalter „Fortsetzen nach Stromausfall“",
        "App 1.11.0: Karte „Druck unterbrochen“ auf der Startseite, Schalter im ACE-Fenster",
    ]),
    ("3.2.2", "2026-10-10", [
        "Direkt nach dem Start (Spoolman noch nicht geladen) schreibt die Bridge keine Slots ohne Filament mehr an den "
        "Drucker – Orcas Sync konnte sonst falsche Profile wählen, Auto-PA hielt alle Slots für leer",
    ]),
    ("3.2.1", "2026-10-09", [
        "Docker-Image wieder gebaut (Basis-Image jetzt vom AWS-Spiegel, Docker Hub hatte den Bau gedrosselt); "
        "sonst wie 3.2.0",
    ]),
    ("3.2.0", "2026-10-09", [
        "Z-Versatz pro Filament: Spoolman-Feld „Z-Versatz“ (erbt von der Vorlage), wird beim Druckstart zur ersten "
        "Schicht addiert (±0,5 mm); abschaltbar unter Einstellungen → Erste Schicht",
        "Wechsel-G-Code: mit Orcas „Purge in prime tower“ spült die ACE nichts zusätzlich (nie doppelt)",
    ]),
    ("3.1.0", "2026-10-09", [
        "Auto-PA: der Drucker misst Pressure Advance mit der Wiegezelle je Geschwindigkeit, der Wert landet am Filament "
        "in Spoolman (auch für Orca) und gilt beim nächsten Druck; fehlt er, misst der Drucker selbst",
        "ACE-Seite: Karte „Pressure Advance“ – an/aus, automatisch messen an/aus, PA je Slot, jetzt messen, neu messen",
        "Orca sah jeden Slot doppelt (alte Einträge des ACE-Treibers) – werden jetzt aufgeräumt",
        "App 1.10.0: Abschnitt „Pressure Advance“ im ACE-Fenster",
    ]),
    ("3.0.0", "2026-10-09", [
        "Drucker läuft jetzt mit Klipper auf dem Raspberry Pi und dem ACE-Treiber ACEPRO statt Original-Firmware",
        "Verbrauch pro Spule aus Klipper, beim Wechsel bekommt der neue Slot Laden und Spülen",
        "Spülen pro Farbwechsel aus Orcas Spülmengen; Spül-Multiplikator entfällt",
        "Trockner: von Hand, geplant oder beim Einlegen gestartet läuft bis zum Ende; Automatik startet erst nach "
        "15 min über der Schwelle (Deckel öffnen startet nichts)",
        "ACE-Karte: Endlosspule an/aus und Modus; Steuerung: „Klipper neu laden“ nach Not-Aus oder Fehler",
        "Kamera ohne CPU-Drosselung; Status zeigt die CPU des Pi",
        "Orca-Plugin 0.6.0 und App 1.9.0 empfohlen",
    ]),
    ("2.21.1", "2026-10-06", [
        "Rücksync aus Orca löscht nie mehr ein Spoolman-Feld, nur weil ein Wert unlesbar ist (Düsentemperatur war weg)",
        "Orca-Plugin 0.5.2 empfohlen: Profile aus Orca 2.5 laden wieder, Rücksync nimmt den Wert der aktiven Extruder-Variante",
    ]),
    ("2.21.0", "2026-10-04", [
        "Zeile „Benutzt“: welche Slots der Druck braucht, gesamt und was noch kommt",
        "3D-Ansicht: „Rest“ durchsichtig, voll oder aus; große Dateien ohne Löcher (zusammengefasst statt weggelassen)",
        "KI-Tab: gelöschte Bilder sauber angezeigt, „Funde“ statt „p“",
        "App 1.8.0: Zeile „Benutzt“ auf der Startseite",
    ]),
    ("2.20.0", "2026-10-03", [
        "3D-Ansicht wie in Orca: Druckplatte mit Raster, grauer Hintergrund, runde Stränge in echter Breite, kräftige Farben",
    ]),
    ("2.19.0", "2026-10-03", [
        "3D-Ansicht des laufenden Drucks (Volumen, Linien oder Bild – je nach Gerät einstellbar)",
        "Einstellungen der Bridge im Betrieb ändern, ohne Neustart",
        "Feuchte-Verlauf der ACE mit allen Trocknungen, Feuchte-Schätzung pro Spule, Trocknen beim Einlegen",
        "Prüfung beim Druckstart: Material, Farbe, Spule und Feuchte gegen die Druckdatei",
        "Home Assistant über MQTT, Raumsensor für die Feuchte im Lager",
        "App 1.7.0: 3D-Ansicht, Feuchte-Verlauf, Feuchte auf der Spulenkarte, Widget",
    ]),
    ("2.18.0", "2026-10-03", [
        "KI-Tab: Einstellungen, ignorierte Bereiche, Gedächtnis, Bildersammlung mit Kennzeichnen und ZIP",
        "KI gewöhnt sich nicht mehr an einen lange unbemerkten Fehldruck",
        "App 1.6.0: keine Fehlalarme mehr beim Aufheizen, KI-Seite, „Stimmt“ am Alarm",
    ]),
    ("2.17.0", "2026-10-03", [
        "KI-Fehldruck-Erkennung (kobra-vision): Alarm mit Kamerabild, Rahmen im Bild, Fehlalarm/Stimmt",
        "Bildersammlung für die nächsten KI-Stufen (bis 5 GB)",
        "App 1.5.0: KI-Alarm mit „Pausieren“ und „Fehlalarm“",
    ]),
    ("2.16.0", "2026-10-03", [
        "App 1.4.0: Druck als Live-Update immer oben, eigene Töne, Töne testen in den Einstellungen",
        "Drucker-CPU ist keine Meldung mehr, nur noch Status (gelb ab 90 %, rot ab 97 %)",
    ]),
    ("2.15.3", "2026-10-03", [
        "Handy: Fertig-Zeit wird umgebrochen statt abgeschnitten",
    ]),
    ("2.15.2", "2026-10-03", [
        "Trockner: Restzeit richtig (die ACE meldet Sekunden), Ist-Temperatur auch beim Trocknen",
    ]),
    ("2.15.1", "2026-10-02", [
        "Trockner: Standardwerte nach Herstellerangaben – PLA/TPU 55 °C statt 45/50, PETG bleibt 60",
        "Kamerabild auf breiten Bildschirmen mittig",
    ]),
    ("2.15.0", "2026-10-02", [
        "App 1.3.0: Druck-Benachrichtigungen aufs Handy (ersetzt den OctoApp-Companion)",
        "Kamera wird im Druck nicht mehr unnötig gedrosselt (Schwellen 90/97 %, sanfte Schritte)",
    ]),
    ("2.14.1", "2026-10-02", [
        "RFID automatisch: wartet beim Start auf Spoolman und prüft unbekannte Tags erneut",
    ]),
    ("2.14.0", "2026-10-02", [
        "RFID automatisch: Spule mit eigenem Tag im Slot wird zugeordnet, unbekannte Nummern gemerkt",
        "App 1.2.0: leerer Sticker wird beim Scannen gleich beschrieben",
    ]),
    ("2.13.0", "2026-10-02", [
        "Zwei NFC-Tags pro Spule (eine pro Seite für die ACE 2 Pro), App 1.1.0 schreibt beide",
    ]),
    ("2.12.0", "2026-10-01", [
        "Android-App 1.0.0 als signierte APK im Release und in der Bridge",
        "App-Updates kommen über die Bridge: Karte unter Mehr, ein Tipp installiert",
    ]),
    ("2.11.0", "2026-10-01", [
        "Drucksteuerung: Pause/Weiter, Abbrechen, Not-Aus (2 s halten), Nachjustieren (Tempo, Fluss, Lüfter, Temperaturen)",
        "Feld für den Spül-Multiplikator wieder auf Übersicht und Seite ACE",
    ]),
    ("2.10.1", "2026-10-01", [
        "Kamera schont den Drucker: Einzelbilder statt Stream, 1–10 fps je nach Drucker-CPU",
        "Status zeigt die Drucker-CPU; Warnung bei Dauerlast",
    ]),
    ("2.10.0", "2026-10-01", [
        "Terminal: Antworten des Druckers, Befehle mit Absender, senden mit Rückfrage bei Riskantem",
        "Logs: Bridge-Log, Ende der Drucker-Logs, Druck-Aufzeichnungen",
        "Nach Updates lädt sich die Seite selbst neu – kein Strg+Shift+R mehr",
    ]),
    ("2.9.0", "2026-10-01", [
        "Übersicht als Druckermonitor: Kamera vorn, Modell nur während des Drucks",
        "Meldungen & Status: u. a. „Spule reicht nicht für diesen Druck“, Verbindungen, App und Plugin",
        "Neuer Tab Filament: Spulen und Sorten an einem Ort",
    ]),
    ("2.8.1", "2026-10-01", [
        "Übersicht aufgeräumt: Druckerkarte von oben nach unten, Trockner und ACE nebeneinander gestapelt",
        "Handy: Zeiten in einer Zeile, Drucke in voller Breite",
    ]),
    ("2.8.0", "2026-10-01", [
        "ACE-Karte: Spül-Multiplikator, Nachfüllen und Ausgangserkennung; im Druck erst nach „Freischalten“",
        "Druckansicht: Bridge zeichnet die Druckdatei selbst in den ACE-Farben, dazu Kamera",
        "Kamera-Restream: eine Stream-Verbindung zum Drucker für alle, Kamera-Link für Mainsail, FPS-Anzeige",
        "Druckerdaten unter dem Bild: Düse, Bett, Lüfter, Tempo, Fluss, Schicht",
        "Druckzeit: läuft seit, noch ca., fertig um (z. B. ~17:35)",
        "Trocknen planen (z. B. heute 22:00)",
    ]),
    ("2.7.0", "2026-10-01", [
        "Spül-Modell der ACE: Spülen pro Farbwechsel wie die Firmware, Multiplikator vom Drucker gelesen",
        "Orca-Plugin 0.5.0: Verbrauchsvorschau rechnet das Spülen pro Farbwechsel aus den Slot-Farben",
    ]),
    ("2.6.0", "2026-10-01", [
        "Neue Weboberfläche für Handy, Desktop und Ultrawide: Slots, Regal, Filamente, Drucke, Trockner, Geräte",
        "Geräte koppeln: ein Schlüssel pro Browser, App und Orca-Plugin; Ändern nur noch gekoppelt",
        "Orca-Plugin 0.4.0 koppelt im Panel – zusammen mit der Bridge aktualisieren",
    ]),
    ("2.5.0", "2026-10-01", [
        "ACE-Trockner: Feuchte und Temperatur, Trocknen von Hand und Automatik nach Feuchte",
        "Trockentemperatur nie über dem empfindlichsten eingelegten Filament (Feld „Trocknen max.“)",
    ]),
    ("2.4.0", "2026-09-30", [
        "Schnittstelle für die Android-App: Status, Spulen und Filamente anlegen, NFC-Tags (APP_TOKEN)",
        "Orca-Plugin 0.3.4 meldet seine Basisprofile für die Auswahl in der App",
    ]),
    ("2.3.0", "2026-09-30", [
        "Spulen ohne Tag: Material und Farbe aus Spoolman gehen beim Zuordnen auf dieser Seite an die ACE",
        "Hinweis bei Slots ohne Material am Drucker – ein Druck damit würde beim Start abbrechen",
    ]),
    ("2.2.2", "2026-09-30", [
        "Orca-Profile: Farbe als default_filament_colour (filament_colour verwirft Orca in Filament-Presets)",
        "Rücksync nimmt beide Farbschlüssel an",
    ]),
    ("2.2.1", "2026-09-24", [
        "Eigenes Repo kobra-spoolman mit Docker-Image (ghcr.io), Tests und Doku",
        "MOONRAKER_URL ist Pflicht (keine feste IP mehr als Standard)",
    ]),
    ("2.2.0", "2026-09-24", [
        "Orca-Schnittstelle für das Plugin „Kobra Spoolman“: Profilwerte pro Filament (/api/orca/profiles)",
        "Rücksync Orca → Spoolman (/api/orca/backsync) und Zurücksetzen auf Vorlage (/api/orca/reset)",
        "Panel-Status unter einer festen Adresse (/api/orca/state)",
    ]),
    ("2.1.1", "2026-09-24", [
        "Fußzeile mit Version, Laufzeit und Links; Info-Fenster mit allen Einstellungen und Verbindungen",
    ]),
    ("2.1.0", "2026-09-24", [
        "Verbrauch pro Slot messen und in Spoolman buchen (beim Wechsel, bei Druckende, alle 5 min)",
        "Neustart-sicher: Zustand und Journal unter data/usage/",
        "Offene Posten für Slots ohne Spule, Nachbuchen und Verwerfen auf der Slot-Seite",
        "Abgleich mit den G-code-Sollwerten der Firmware, Druckhistorie",
        "Telemetrie speichert nur noch echte Änderungen (etwa 1 MB statt 25 MB pro Druck)",
        "Warnung, falls Moonraker oder Firmware selbst in Spoolman buchen",
    ]),
    ("2.0.1", "2026-09-24", [
        "„passt zur ACE“ prüft Material und Farbe (eine gemeinsame Regel für Hinweise und Auswahl)",
        "Eigenes Orca-Basisprofil am Filament ersetzt die Vorlage komplett",
    ]),
    ("2.0.0", "2026-09-24", [
        "Neuaufbau: Moonraker-WebSocket, Spoolman-Anbindung, Slot-Zuordnung per Handy-Seite, lane_data, Telemetrie",
    ]),
]
