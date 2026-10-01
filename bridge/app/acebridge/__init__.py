"""ace-lane-bridge v2 - Kobra S1 / ACE 2 Pro <-> Spoolman <-> OrcaSlicer."""

__version__ = "2.7.0"
__app_name__ = "ace-lane-bridge"
__description__ = "Kobra S1 mit ACE 2 Pro ↔ Spoolman ↔ OrcaSlicer"

# Neueste Version zuerst. Wird in der Weboberflaeche unter "Einstellungen" angezeigt.
CHANGELOG = [
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
