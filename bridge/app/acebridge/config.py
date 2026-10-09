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

    # Webserver fuer API und Weboberflaeche
    http_host: str = field(default_factory=lambda: os.environ.get("HTTP_HOST", "0.0.0.0"))
    http_port: int = field(default_factory=lambda: _int("HTTP_PORT", 7913))

    # Orte in Spoolman
    slot_location_prefix: str = field(default_factory=lambda: os.environ.get("SLOT_LOCATION_PREFIX", "ACE Slot "))
    shelf_location: str = field(default_factory=lambda: os.environ.get("SHELF_LOCATION", "Regal"))
    template_vendor: str = field(default_factory=lambda: os.environ.get("TEMPLATE_VENDOR", "Vorlage"))

    # Spule automatisch ins Regal, wenn die ACE einen Slot laenger leer meldet
    auto_unassign_on_empty: bool = field(default_factory=lambda: _bool("AUTO_UNASSIGN_ON_EMPTY", True))
    # RFID: Spule mit eigenem Tag (Nummer >= TAG_NR_MIN) im Slot -> automatisch zuordnen
    auto_assign_by_tag: bool = field(default_factory=lambda: _bool("AUTO_ASSIGN_BY_TAG", True))
    empty_debounce_s: float = field(default_factory=lambda: _float("EMPTY_DEBOUNCE_S", 15.0))

    # lane_data fuer Orca/Mainsail/Fluidd
    write_lane_data: bool = field(default_factory=lambda: _bool("WRITE_LANE_DATA", True))
    lane_namespace: str = field(default_factory=lambda: os.environ.get("LANE_NAMESPACE", "lane_data"))
    empty_gate_mode: str = field(default_factory=lambda: os.environ.get("EMPTY_GATE_MODE", "delete").lower())

    # Material/Farbe/Temperatur der zugeordneten Spule an die ACE geben (ACEPRO ACE_SET_SLOT), nur Slots ohne
    # RFID-Tag und nur beim Zuordnen auf der Slot-Seite.
    set_ace_slot_info: bool = field(default_factory=lambda: _bool("SET_ACE_SLOT_INFO", True))

    # Android-App: Schluessel fuer alle schreibenden /api/app-Aufrufe (leer = App darf nur lesen)
    app_token: str = field(default_factory=lambda: os.environ.get("APP_TOKEN", ""))
    # Tag-Nummern fuer selbst beschriebene NFC-Tags (SKU "<Praefix>-<Nummer>"); vorlaeufig, bis der
    # Test zeigt, welche SKU die ACE akzeptiert (docs/findings.md)
    tag_nr_min: int = field(default_factory=lambda: _int("TAG_NR_MIN", 1000))
    tag_nr_max: int = field(default_factory=lambda: _int("TAG_NR_MAX", 99999))
    tag_sku_prefix: str = field(default_factory=lambda: os.environ.get("TAG_SKU_PREFIX", "AHPEBK"))

    # Telemetrie-Logger: Rohdaten jedes Drucks (nur echte Aenderungen)
    telemetry: bool = field(default_factory=lambda: _bool("TELEMETRY", True))
    telemetry_keep: int = field(default_factory=lambda: _int("TELEMETRY_KEEP", 30))

    # Verbrauchsbuchung (Etappe 2)
    book_usage: bool = field(default_factory=lambda: _bool("BOOK_USAGE", True))
    book_interval_s: float = field(default_factory=lambda: _float("BOOK_INTERVAL_S", 300.0))  # Zwischenbuchung im Druck
    book_min_mm: float = field(default_factory=lambda: _float("BOOK_MIN_MM", 10.0))           # kleinste Zwischenbuchung
    gate_debounce_s: float = field(default_factory=lambda: _float("GATE_DEBOUNCE_S", 3.0))    # RFID-Tag erst nach so vielen Sekunden im Slot zuordnen
    usage_tolerance: float = field(default_factory=lambda: _float("USAGE_TOLERANCE", 0.03))   # Abgleich mit Sollwerten
    job_history: int = field(default_factory=lambda: _int("JOB_HISTORY", 50))
    humidity_days: int = field(default_factory=lambda: _int("HUMIDITY_DAYS", 30))

    # Feuchte der Spulen (moisture.py)
    room_rh: float = field(default_factory=lambda: _float("ROOM_RH", 50.0))
    dry_locations: str = field(default_factory=lambda: os.environ.get("DRY_LOCATIONS", ""))
    auto_dry_on_insert: bool = field(default_factory=lambda: _bool("AUTO_DRY_ON_INSERT", True))
    new_spools_dry: bool = field(default_factory=lambda: _bool("NEW_SPOOLS_DRY", True))
    wet_print_action: str = field(default_factory=lambda: os.environ.get("WET_PRINT_ACTION", "warn").strip().lower())

    # Home Assistant ueber MQTT (mqtt.py). MQTT_HOST leer = aus. MQTT_DISCOVERY leer = keine HA-Discovery.
    mqtt_host: str = field(default_factory=lambda: os.environ.get("MQTT_HOST", "").strip())
    mqtt_port: int = field(default_factory=lambda: _int("MQTT_PORT", 1883))
    mqtt_user: str = field(default_factory=lambda: os.environ.get("MQTT_USER", ""))
    mqtt_password: str = field(default_factory=lambda: os.environ.get("MQTT_PASSWORD", ""))
    mqtt_prefix: str = field(default_factory=lambda: os.environ.get("MQTT_PREFIX", "kobra-spoolman"))
    mqtt_discovery: str = field(default_factory=lambda: os.environ.get("MQTT_DISCOVERY", "homeassistant"))
    room_sensor_topic: str = field(default_factory=lambda: os.environ.get("ROOM_SENSOR_TOPIC", "").strip())

    # Meldungen
    low_spool_g: float = field(default_factory=lambda: _float("LOW_SPOOL_G", 100.0))
    reach_reserve_pct: float = field(default_factory=lambda: _float("REACH_RESERVE_PCT", 5.0))
    default_diameter: float = field(default_factory=lambda: _float("DEFAULT_DIAMETER", 1.75))
    default_density: float = field(default_factory=lambda: _float("DEFAULT_DENSITY", 1.24))

    # Kamera: die Bridge holt Einzelbilder (nur solange jemand zuschaut, mit CAMERA_FPS_MAX) und verteilt sie als
    # Stream an Weboberflaeche, App, Mainsail und die KI. CAMERA_STREAM=true nimmt den Dauerstream des Druckers
    # (im Tunnel-Betrieb ist die Drucker-CPU frei). URLs leer = aus Moonrakers Webcam-Liste.
    camera: bool = field(default_factory=lambda: _bool("CAMERA", True))
    camera_stream: bool = field(default_factory=lambda: _bool("CAMERA_STREAM", False))
    camera_fps_min: float = field(default_factory=lambda: _float("CAMERA_FPS_MIN", 1.0))
    camera_fps_max: float = field(default_factory=lambda: _float("CAMERA_FPS_MAX", 10.0))
    camera_stream_url: str = field(default_factory=lambda: os.environ.get("CAMERA_STREAM_URL", ""))
    camera_snapshot_url: str = field(default_factory=lambda: os.environ.get("CAMERA_SNAPSHOT_URL", ""))
    camera_interval_s: float = field(default_factory=lambda: _float("CAMERA_INTERVAL_S", 1.0))

    # Vorschau der Druckdatei: die Bridge laedt die Datei beim Druckstart einmal (gedrosselt) und zeichnet sie
    render: bool = field(default_factory=lambda: _bool("RENDER", True))
    render_max_mb: float = field(default_factory=lambda: _float("RENDER_MAX_MB", 200.0))
    render_interval_s: float = field(default_factory=lambda: _float("RENDER_INTERVAL_S", 15.0))
    geometry_max_segments: int = field(default_factory=lambda: _int("GEOMETRY_MAX_SEGMENTS", 1_500_000))

    # KI (kobra-vision): leer = aus. Im Druck alle VISION_INTERVAL_S ein Bild an den Dienst; warn = nur melden,
    # pause = bei sicherem Fehldruck pausieren. Bilder fuer spaeteres Training: hoechstens VISION_DATASET_GB.
    vision_url: str = field(default_factory=lambda: os.environ.get("VISION_URL", "").rstrip("/"))
    vision_token: str = field(default_factory=lambda: os.environ.get("VISION_TOKEN", ""))
    vision_interval_s: float = field(default_factory=lambda: _float("VISION_INTERVAL_S", 10.0))
    vision_sensitivity: float = field(default_factory=lambda: _float("VISION_SENSITIVITY", 1.0))
    vision_action: str = field(default_factory=lambda: os.environ.get("VISION_ACTION", "warn").strip().lower())
    vision_dataset_gb: float = field(default_factory=lambda: _float("VISION_DATASET_GB", 5.0))
    vision_save_every_s: float = field(default_factory=lambda: _float("VISION_SAVE_EVERY_S", 60.0))

    dry_run: bool = field(default_factory=lambda: _bool("DRY_RUN", False))
    data_dir: str = field(default_factory=lambda: os.environ.get("DATA_DIR", "/data"))
    log_level: str = field(default_factory=lambda: os.environ.get("LOG_LEVEL", "INFO").upper())

    # Links fuer die Weboberflaeche (vom Browser aus erreichbar). Leer = automatisch.
    spoolman_public_url: str = field(default_factory=lambda: os.environ.get("SPOOLMAN_PUBLIC_URL", "").rstrip("/"))
    printer_ui_url: str = field(default_factory=lambda: os.environ.get("PRINTER_UI_URL", "").rstrip("/"))

    def links(self) -> dict:
        """Spoolman: im Stack heisst der Host 'spoolman' - das kennt der Browser nicht,
        dann baut die Seite den Link selbst (gleicher Host, Port 7912).
        Drucker-Oberflaeche: Mainsail am Klipper-Rechner (Pi), Port 80 - gleicher Host wie Moonraker."""
        from urllib.parse import urlparse
        sm = self.spoolman_public_url
        if not sm:
            host = urlparse(self.spoolman_url).hostname or ""
            sm = self.spoolman_url if ("." in host or host == "localhost") else ""
        ui = self.printer_ui_url
        if not ui:
            host = urlparse(self.moonraker_url).hostname
            ui = f"http://{host}" if host else ""
        return {"spoolman": sm or None, "printer_ui": ui or None}

    def printer_base_url(self) -> str:
        """Webserver des Klipper-Rechners (Pi, Mainsail/nginx Port 80) - Rueckfall fuer /webcam/, wenn Moonrakers
        Webcam-Liste nichts liefert (die Kamera selbst haengt am Drucker, siehe moonraker.conf)."""
        from urllib.parse import urlparse
        host = urlparse(self.moonraker_url).hostname
        return f"http://{host}" if host else ""

    def slot_location(self, slot: int) -> str:
        """slot ist 1-basiert (Slot 1 = Gate 0)."""
        return f"{self.slot_location_prefix}{slot}"

    def slot_from_location(self, location: str | None) -> int | None:
        if not location or not location.startswith(self.slot_location_prefix):
            return None
        rest = location[len(self.slot_location_prefix):].strip()
        return int(rest) if rest.isdigit() else None
