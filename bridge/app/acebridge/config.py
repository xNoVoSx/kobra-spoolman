"""Konfiguration ausschliesslich ueber Umgebungsvariablen (Portainer-Stack)."""

from __future__ import annotations

import os
from dataclasses import dataclass, field


def _bool(name: str, default: bool) -> bool:
    raw = os.environ.get(name)
    if raw is None or raw.strip() == "":
        return default
    return raw.strip().lower() in ("1", "true", "yes", "ja", "on")


def _float(name: str, default: float) -> float:
    try:
        return float(os.environ.get(name, default))
    except (TypeError, ValueError):
        return default


def _int(name: str, default: int) -> int:
    try:
        return int(os.environ.get(name, default))
    except (TypeError, ValueError):
        return default


@dataclass
class Config:
    # Drucker
    moonraker_url: str = field(default_factory=lambda: os.environ.get("MOONRAKER_URL", "").rstrip("/"))
    moonraker_api_key: str = field(default_factory=lambda: os.environ.get("MOONRAKER_API_KEY", ""))

    # Spoolman (im selben Stack ueber den Servicenamen erreichbar)
    spoolman_url: str = field(default_factory=lambda: os.environ.get("SPOOLMAN_URL", "http://spoolman:8000").rstrip("/"))
    spoolman_poll_s: float = field(default_factory=lambda: _float("SPOOLMAN_POLL_S", 20.0))

    # Webserver fuer API und Handy-Seite
    http_host: str = field(default_factory=lambda: os.environ.get("HTTP_HOST", "0.0.0.0"))
    http_port: int = field(default_factory=lambda: _int("HTTP_PORT", 7913))

    # Orte in Spoolman
    slot_location_prefix: str = field(default_factory=lambda: os.environ.get("SLOT_LOCATION_PREFIX", "ACE Slot "))
    shelf_location: str = field(default_factory=lambda: os.environ.get("SHELF_LOCATION", "Regal"))
    template_vendor: str = field(default_factory=lambda: os.environ.get("TEMPLATE_VENDOR", "Vorlage"))

    # Spule automatisch ins Regal, wenn die ACE einen Slot laenger leer meldet
    auto_unassign_on_empty: bool = field(default_factory=lambda: _bool("AUTO_UNASSIGN_ON_EMPTY", True))
    empty_debounce_s: float = field(default_factory=lambda: _float("EMPTY_DEBOUNCE_S", 15.0))

    # lane_data fuer Orca/Mainsail/Fluidd
    write_lane_data: bool = field(default_factory=lambda: _bool("WRITE_LANE_DATA", True))
    lane_namespace: str = field(default_factory=lambda: os.environ.get("LANE_NAMESPACE", "lane_data"))
    empty_gate_mode: str = field(default_factory=lambda: os.environ.get("EMPTY_GATE_MODE", "delete").lower())

    # Telemetrie-Logger: Rohdaten jedes Drucks (nur echte Aenderungen)
    telemetry: bool = field(default_factory=lambda: _bool("TELEMETRY", True))
    telemetry_keep: int = field(default_factory=lambda: _int("TELEMETRY_KEEP", 30))

    # Verbrauchsbuchung (Etappe 2)
    book_usage: bool = field(default_factory=lambda: _bool("BOOK_USAGE", True))
    book_interval_s: float = field(default_factory=lambda: _float("BOOK_INTERVAL_S", 300.0))  # Zwischenbuchung im Druck
    book_min_mm: float = field(default_factory=lambda: _float("BOOK_MIN_MM", 10.0))           # kleinste Zwischenbuchung
    gate_debounce_s: float = field(default_factory=lambda: _float("GATE_DEBOUNCE_S", 3.0))    # Flackern der ACE ignorieren
    usage_tolerance: float = field(default_factory=lambda: _float("USAGE_TOLERANCE", 0.03))   # Abgleich mit Sollwerten
    job_history: int = field(default_factory=lambda: _int("JOB_HISTORY", 50))
    default_diameter: float = field(default_factory=lambda: _float("DEFAULT_DIAMETER", 1.75))
    default_density: float = field(default_factory=lambda: _float("DEFAULT_DENSITY", 1.24))

    dry_run: bool = field(default_factory=lambda: _bool("DRY_RUN", False))
    data_dir: str = field(default_factory=lambda: os.environ.get("DATA_DIR", "/data"))
    log_level: str = field(default_factory=lambda: os.environ.get("LOG_LEVEL", "INFO").upper())

    # Links fuer die Slot-Seite (vom Browser aus erreichbar). Leer = automatisch.
    spoolman_public_url: str = field(default_factory=lambda: os.environ.get("SPOOLMAN_PUBLIC_URL", "").rstrip("/"))
    printer_ui_url: str = field(default_factory=lambda: os.environ.get("PRINTER_UI_URL", "").rstrip("/"))

    def links(self) -> dict:
        """Spoolman: im Stack heisst der Host 'spoolman' - das kennt der Browser nicht,
        dann baut die Seite den Link selbst (gleicher Host, Port 7912).
        Drucker-Oberflaeche: Mainsail laeuft unter Rinkhals fest auf Port 4409."""
        from urllib.parse import urlparse
        sm = self.spoolman_public_url
        if not sm:
            host = urlparse(self.spoolman_url).hostname or ""
            sm = self.spoolman_url if ("." in host or host == "localhost") else ""
        ui = self.printer_ui_url
        if not ui:
            host = urlparse(self.moonraker_url).hostname
            ui = f"http://{host}:4409" if host else ""
        return {"spoolman": sm or None, "printer_ui": ui or None}

    def slot_location(self, slot: int) -> str:
        """slot ist 1-basiert (Slot 1 = Gate 0)."""
        return f"{self.slot_location_prefix}{slot}"

    def slot_from_location(self, location: str | None) -> int | None:
        if not location or not location.startswith(self.slot_location_prefix):
            return None
        rest = location[len(self.slot_location_prefix):].strip()
        return int(rest) if rest.isdigit() else None
