"""First start: new installations start with the core, existing ones keep everything as it is.

At the very first start of this version the bridge decides once, before any other part writes to DATA_DIR:

- existing: DATA_DIR already holds paired devices, bookings or saved settings -> every switch stays as it is; web and
  app show a one-time hint on the new Features page (each browser/app remembers that it was shown).
- new: an empty DATA_DIR -> the comfort features that act on their own start switched off (NEW_DEFAULTS), and the web
  UI opens the setup page at the first visit (after pairing). The core - spools, slots, bookings, RFID, camera, print
  preview - and the printer modules that are installed stay on.

What the installation sets (environment variables, Home Assistant add-on options) always wins and is never changed.
The decision is stored in DATA_DIR/setup.json; the setup page can be opened again any time.
"""

from __future__ import annotations

import json
import logging
import os
import time
from typing import TYPE_CHECKING, Any, Dict, Optional

from .storage import save_json

if TYPE_CHECKING:
    from .config import Config
    from .runtime_settings import RuntimeSettings

log = logging.getLogger("setup")

FILE = "setup.json"
# switched off for new installations (comfort that acts on its own); env variables and saved settings win
NEW_DEFAULTS = {"auto_dry_on_insert": False, "new_spools_dry": False, "telemetry": False}
# files and folders in DATA_DIR that mean "this bridge is already in use"
IN_USE = ("devices.json", "settings.json", "usage", "dryer.json", "moisture.json", "pa.json", "telemetry")

NEW, DONE, EXISTING = "new", "done", "existing"


def _in_use(data_dir: str) -> bool:
    for name in IN_USE:
        p = os.path.join(data_dir, name)
        if os.path.isfile(p) and os.path.getsize(p) > 2:
            if name == "devices.json":
                try:
                    with open(p, encoding="utf-8") as f:
                        if not (json.load(f).get("devices") or []):
                            continue
                except (OSError, ValueError):
                    pass
            return True
        if os.path.isdir(p) and any(os.scandir(p)):
            return True
    return False


class Setup:
    def __init__(self, cfg: "Config", settings: "RuntimeSettings"):
        self.cfg = cfg
        self.path = os.path.join(cfg.data_dir, FILE)
        self.state: str = EXISTING
        self.since: Optional[float] = None
        self._load_or_decide(settings)

    def _load_or_decide(self, settings: "RuntimeSettings") -> None:
        try:
            with open(self.path, encoding="utf-8") as f:
                data = json.load(f)
            self.state = data.get("state") if data.get("state") in (NEW, DONE, EXISTING) else EXISTING
            self.since = data.get("since")
            return
        except FileNotFoundError:
            pass
        except (OSError, ValueError) as e:
            log.warning("%s unreadable, treated as an existing installation: %s", FILE, e)
            return
        if _in_use(self.cfg.data_dir):
            self.state = EXISTING
            log.info("Existing installation: all switches stay as they are (Features page: hint only)")
        else:
            self.state = NEW
            self._apply_new_defaults(settings)
            log.info("New installation: core on, comfort features off until chosen on the setup page")
        self.since = round(time.time(), 1)
        self._save()

    def _apply_new_defaults(self, settings: "RuntimeSettings") -> None:
        changes = {k: v for k, v in NEW_DEFAULTS.items()
                   if not os.environ.get(k.upper(), "").strip() and k not in settings.saved}
        if changes:
            settings.update(changes)

    def _save(self) -> None:
        os.makedirs(self.cfg.data_dir, exist_ok=True)
        save_json(self.path, {"state": self.state, "since": self.since}, indent=1)

    def done(self) -> None:
        """The setup page was gone through (new installation) - it does not open by itself any more."""
        if self.state == NEW:
            self.state = DONE
            self._save()
            log.info("Setup done")

    def view(self) -> Dict[str, Any]:
        return {"state": self.state, "open_setup": self.state == NEW, "hint": self.state == EXISTING}
