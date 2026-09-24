"""ace-lane-bridge v2 - Kobra S1 / ACE 2 Pro <-> Spoolman <-> OrcaSlicer."""

__version__ = "2.2.1"
__app_name__ = "ace-lane-bridge"
__description__ = "Kobra S1 mit ACE 2 Pro ↔ Spoolman ↔ OrcaSlicer"

# Neueste Version zuerst. Wird auf der Slot-Seite unter "Info" angezeigt.
CHANGELOG = [
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
