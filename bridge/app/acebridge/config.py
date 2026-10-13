"""Configuration only through environment variables (Docker/Portainer stack, Home Assistant add-on options)."""

from __future__ import annotations

import os
from dataclasses import dataclass, field


def _bool(name: str, default: bool) -> bool:
    raw = os.environ.get(name)
    if raw is None or raw.strip() == "":
        return default
    return raw.strip().lower() in ("1", "true", "yes", "ja", "on")   # "ja": older German configs


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


# names in Spoolman: current (English) first, then the German ones of installs before 3.12
SHELF_NAMES = ("Shelf", "Regal")
TEMPLATE_VENDORS = ("Template", "Vorlage")


@dataclass
class Config:
    # printer
    moonraker_url: str = field(default_factory=lambda: os.environ.get("MOONRAKER_URL", "").rstrip("/"))
    moonraker_api_key: str = field(default_factory=lambda: os.environ.get("MOONRAKER_API_KEY", ""))

    # Spoolman (reachable by its service name in the same stack)
    spoolman_url: str = field(default_factory=lambda: os.environ.get("SPOOLMAN_URL", "http://spoolman:8000").rstrip("/"))
    spoolman_poll_s: float = field(default_factory=lambda: _float("SPOOLMAN_POLL_S", 20.0))

    # web server for API and web UI
    http_host: str = field(default_factory=lambda: os.environ.get("HTTP_HOST", "0.0.0.0"))
    http_port: int = field(default_factory=lambda: _int("HTTP_PORT", 7913))

    # locations and names in Spoolman (data - keep them when upgrading). Unset = automatic: an existing install
    # keeps its names (German ones from before 3.12: "Regal", "Vorlage"), a new one gets "Shelf" and "Template"
    # (spoolman.Spoolman.resolve_names).
    slot_location_prefix: str = field(default_factory=lambda: os.environ.get("SLOT_LOCATION_PREFIX", "ACE Slot "))
    shelf_location: str = field(default_factory=lambda: os.environ.get("SHELF_LOCATION", ""))
    template_vendor: str = field(default_factory=lambda: os.environ.get("TEMPLATE_VENDOR", ""))

    # move the spool to the shelf when the ACE reports a slot empty for a while
    auto_unassign_on_empty: bool = field(default_factory=lambda: _bool("AUTO_UNASSIGN_ON_EMPTY", True))
    # RFID: spool with our own tag (number >= TAG_NR_MIN) in the slot -> assign automatically
    auto_assign_by_tag: bool = field(default_factory=lambda: _bool("AUTO_ASSIGN_BY_TAG", True))
    # original Anycubic tag (names only the kind): assign the one fitting spool on the shelf
    auto_assign_by_kind: bool = field(default_factory=lambda: _bool("AUTO_ASSIGN_BY_KIND", True))
    empty_debounce_s: float = field(default_factory=lambda: _float("EMPTY_DEBOUNCE_S", 15.0))

    # lane_data for Orca/Mainsail/Fluidd
    write_lane_data: bool = field(default_factory=lambda: _bool("WRITE_LANE_DATA", True))
    lane_namespace: str = field(default_factory=lambda: os.environ.get("LANE_NAMESPACE", "lane_data"))
    empty_gate_mode: str = field(default_factory=lambda: os.environ.get("EMPTY_GATE_MODE", "delete").lower())

    # give material/colour/temperature of the assigned spool to the ACE (ACEPRO ACE_SET_SLOT), only slots without an
    # RFID tag and only when assigning on the slot page
    set_ace_slot_info: bool = field(default_factory=lambda: _bool("SET_ACE_SLOT_INFO", True))

    # legacy key for writing calls (before pairing existed); empty = pairing only
    app_token: str = field(default_factory=lambda: os.environ.get("APP_TOKEN", ""))
    # Home Assistant ingress (ingress.py): requests from the ingress proxy count as a paired device
    ha_ingress_trust: bool = field(default_factory=lambda: _bool("HA_INGRESS_TRUST", False))
    # direct address of the bridge for copyable links under ingress (empty: the HA host on HTTP_PORT)
    bridge_public_url: str = field(default_factory=lambda: os.environ.get("BRIDGE_PUBLIC_URL", ""))
    # tag numbers for self-written NFC tags (SKU "<prefix>-<number>"), see docs/findings.md
    tag_nr_min: int = field(default_factory=lambda: _int("TAG_NR_MIN", 1000))
    tag_nr_max: int = field(default_factory=lambda: _int("TAG_NR_MAX", 99999))
    tag_sku_prefix: str = field(default_factory=lambda: os.environ.get("TAG_SKU_PREFIX", "AHPEBK"))

    # telemetry recorder: raw data of every print (real changes only)
    telemetry: bool = field(default_factory=lambda: _bool("TELEMETRY", True))
    telemetry_keep: int = field(default_factory=lambda: _int("TELEMETRY_KEEP", 30))

    # consumption booking
    book_usage: bool = field(default_factory=lambda: _bool("BOOK_USAGE", True))
    book_interval_s: float = field(default_factory=lambda: _float("BOOK_INTERVAL_S", 300.0))  # interim booking while printing
    book_min_mm: float = field(default_factory=lambda: _float("BOOK_MIN_MM", 10.0))           # smallest interim booking
    gate_debounce_s: float = field(default_factory=lambda: _float("GATE_DEBOUNCE_S", 3.0))    # assign an RFID tag after this many seconds in the slot
    usage_tolerance: float = field(default_factory=lambda: _float("USAGE_TOLERANCE", 0.03))   # check against expected values
    job_history: int = field(default_factory=lambda: _int("JOB_HISTORY", 50))
    humidity_days: int = field(default_factory=lambda: _int("HUMIDITY_DAYS", 30))

    # spool moisture (moisture.py)
    room_rh: float = field(default_factory=lambda: _float("ROOM_RH", 50.0))
    dry_locations: str = field(default_factory=lambda: os.environ.get("DRY_LOCATIONS", ""))
    auto_dry_on_insert: bool = field(default_factory=lambda: _bool("AUTO_DRY_ON_INSERT", True))
    # auto PA (Klipper module kobra_pa): PA from Spoolman to Klipper, measurements written back
    pa_sync: bool = field(default_factory=lambda: _bool("PA_SYNC", True))
    # Z offset per filament (Spoolman field z_offset) to KOBRA_START
    filament_z_sync: bool = field(default_factory=lambda: _bool("FILAMENT_Z_SYNC", True))
    new_spools_dry: bool = field(default_factory=lambda: _bool("NEW_SPOOLS_DRY", True))
    # drying in the model approaches the humidity measured in the ACE (lid open: hardly any drying is credited)
    moisture_ace_rh: bool = field(default_factory=lambda: _bool("MOISTURE_ACE_RH", True))
    # the ACE stays far below its target while drying -> message "lid open?"
    dryer_lid_check: bool = field(default_factory=lambda: _bool("DRYER_LID_CHECK", True))
    wet_print_action: str = field(default_factory=lambda: os.environ.get("WET_PRINT_ACTION", "warn").strip().lower())

    # Home Assistant over MQTT (mqtt.py). MQTT_HOST empty = off. MQTT_DISCOVERY empty = no HA discovery.
    mqtt_host: str = field(default_factory=lambda: os.environ.get("MQTT_HOST", "").strip())
    mqtt_port: int = field(default_factory=lambda: _int("MQTT_PORT", 1883))
    mqtt_user: str = field(default_factory=lambda: os.environ.get("MQTT_USER", ""))
    mqtt_password: str = field(default_factory=lambda: os.environ.get("MQTT_PASSWORD", ""))
    mqtt_prefix: str = field(default_factory=lambda: os.environ.get("MQTT_PREFIX", "kobra-spoolman"))
    mqtt_discovery: str = field(default_factory=lambda: os.environ.get("MQTT_DISCOVERY", "homeassistant"))
    room_sensor_topic: str = field(default_factory=lambda: os.environ.get("ROOM_SENSOR_TOPIC", "").strip())

    # messages
    low_spool_g: float = field(default_factory=lambda: _float("LOW_SPOOL_G", 100.0))
    reach_reserve_pct: float = field(default_factory=lambda: _float("REACH_RESERVE_PCT", 5.0))
    default_diameter: float = field(default_factory=lambda: _float("DEFAULT_DIAMETER", 1.75))
    default_density: float = field(default_factory=lambda: _float("DEFAULT_DENSITY", 1.24))

    # camera: the bridge fetches snapshots (only while someone watches, at most CAMERA_FPS_MAX) and re-distributes
    # them as a stream to web UI, app, Mainsail and the AI. CAMERA_STREAM=true uses the printer's continuous stream.
    # URLs empty = from Moonraker's webcam list.
    camera: bool = field(default_factory=lambda: _bool("CAMERA", True))
    camera_stream: bool = field(default_factory=lambda: _bool("CAMERA_STREAM", False))
    # under HA ingress the browser fetches single images (the proxy chain does not pass the MJPEG stream reliably)
    camera_ingress_snapshots: bool = field(default_factory=lambda: _bool("CAMERA_INGRESS_SNAPSHOTS", True))
    camera_fps_min: float = field(default_factory=lambda: _float("CAMERA_FPS_MIN", 1.0))
    camera_fps_max: float = field(default_factory=lambda: _float("CAMERA_FPS_MAX", 10.0))
    # Rinkhals: the frame rate follows the printer CPU (GoKlipper and the camera share it); not under Klipper on a Pi
    camera_cpu_low: float = field(default_factory=lambda: _float("CAMERA_CPU_LOW", 90.0))
    camera_cpu_high: float = field(default_factory=lambda: _float("CAMERA_CPU_HIGH", 97.0))
    camera_stream_url: str = field(default_factory=lambda: os.environ.get("CAMERA_STREAM_URL", ""))
    camera_snapshot_url: str = field(default_factory=lambda: os.environ.get("CAMERA_SNAPSHOT_URL", ""))
    camera_interval_s: float = field(default_factory=lambda: _float("CAMERA_INTERVAL_S", 1.0))

    # print file preview: the bridge downloads the file once at print start (throttled) and draws it
    render: bool = field(default_factory=lambda: _bool("RENDER", True))
    render_max_mb: float = field(default_factory=lambda: _float("RENDER_MAX_MB", 200.0))
    render_interval_s: float = field(default_factory=lambda: _float("RENDER_INTERVAL_S", 15.0))
    geometry_max_segments: int = field(default_factory=lambda: _int("GEOMETRY_MAX_SEGMENTS", 1_500_000))

    # AI (kobra-vision): empty = off. While printing an image to the service every VISION_INTERVAL_S; warn = report
    # only, pause = pause on a certain failure. Images for later training: at most VISION_DATASET_GB.
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
    # language for devices that do not say which one they want, and for MQTT / Home Assistant: en | de
    # (not LANGUAGE - that one belongs to gettext and may be set by the system)
    language: str = field(default_factory=lambda: os.environ.get("UI_LANGUAGE", "en").strip().lower()[:2] or "en")

    # links for the web UI (reachable from the browser). Empty = automatic.
    spoolman_public_url: str = field(default_factory=lambda: os.environ.get("SPOOLMAN_PUBLIC_URL", "").rstrip("/"))
    printer_ui_url: str = field(default_factory=lambda: os.environ.get("PRINTER_UI_URL", "").rstrip("/"))

    def links(self) -> dict:
        """Spoolman: in the stack the host is called 'spoolman' - the browser does not know it, then the page builds
        the link itself (same host, port 7912).
        Printer UI: Mainsail on the Klipper computer, port 80 - same host as Moonraker."""
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
        """Web server of the Klipper computer (Mainsail/nginx, port 80) - fallback for /webcam/ when Moonraker's webcam
        list returns nothing."""
        from urllib.parse import urlparse
        host = urlparse(self.moonraker_url).hostname
        return f"http://{host}" if host else ""

    def __post_init__(self) -> None:
        # explicitly set names stay as they are; empty ones are resolved when Spoolman answers (see above)
        self.shelf_location_auto = not self.shelf_location
        self.template_vendor_auto = not self.template_vendor
        self.shelf_location = self.shelf_location or SHELF_NAMES[0]
        self.template_vendor = self.template_vendor or TEMPLATE_VENDORS[0]

    def slot_location(self, slot: int) -> str:
        """slot is 1-based (slot 1 = gate 0)."""
        return f"{self.slot_location_prefix}{slot}"

    def slot_from_location(self, location: str | None) -> int | None:
        if not location or not location.startswith(self.slot_location_prefix):
            return None
        rest = location[len(self.slot_location_prefix):].strip()
        return int(rest) if rest.isdigit() else None
