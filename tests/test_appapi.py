"""App-API (Stufe 1): Pruefung/Umwandlung, Tags, Druckerstatus und die HTTP-Routen gegen einen
Spoolman im Speicher."""

from __future__ import annotations

import asyncio
import json
import random

import pytest
from aiohttp.test_utils import TestClient, TestServer
from conftest import FakeMoonraker, ace_status

from acebridge.runtime_settings import RuntimeSettings
from acebridge.vision import Vision
from acebridge.appapi import (AppError, build_filament_body, choose_tag_nr, convert_extra, copy_filament_body,
                              normalize_uid, printer_state, tag_content)
from acebridge.ace import AceSettings
from acebridge.auth import CameraKey, Devices
from acebridge.camera import Camera
from acebridge.console import Console
from acebridge.render import PrintPreview
from acebridge.dryer import Dryer
from acebridge.slots import SlotManager
from acebridge.web import build_app

FIELDS = [
    {"key": "vorlage", "field_type": "choice", "choices": ["Vorlage PETG", "Vorlage PLA"]},
    {"key": "orca_basis", "field_type": "text"},
    {"key": "nozzle_temp_first_layer", "field_type": "integer"},
    {"key": "flow_ratio", "field_type": "float"},
    {"key": "air_filtration", "field_type": "boolean"},
]
VENDORS = [{"id": 1, "name": "Vorlage"}, {"id": 2, "name": "Sunlu"}]
TPL_PETG = {"id": 10, "name": "Vorlage PETG", "material": "PETG", "density": 1.27, "diameter": 1.75,
            "settings_extruder_temp": 255, "settings_bed_temp": 80, "vendor": {"id": 1, "name": "Vorlage"},
            "extra": {"nozzle_temp_first_layer": "255", "bed_temp_first_layer": "80"}}
LAVENDEL = {"id": 20, "name": "PETG 2.0 Lavendelviolett", "material": "PETG", "density": 1.27, "diameter": 1.75,
            "weight": 1000, "spool_weight": 160, "color_hex": "685BC7", "settings_extruder_temp": 250,
            "settings_bed_temp": 75, "vendor": {"id": 2, "name": "Sunlu"},
            "extra": {"flow_ratio": "0.95", "vorlage": "\"Vorlage PETG\""}}


# ====================================================================== reine Funktionen
def test_filament_body_only_contains_what_was_set():
    body = build_filament_body({"name": "PETG 2.0 Mint", "material": "PETG", "vendor_id": 2, "color_hex": "#3fa46a",
                                "settings_extruder_temp": "250", "extra": {"flow_ratio": "0.96"}},
                               FIELDS, VENDORS, [TPL_PETG], creating=True)
    assert body == {"name": "PETG 2.0 Mint", "material": "PETG", "vendor_id": 2, "color_hex": "3FA46A",
                    "settings_extruder_temp": 250, "extra": {"flow_ratio": "0.96"},
                    "density": 1.27, "diameter": 1.75}   # Dichte/Durchmesser aus der Vorlage (Pflicht in Spoolman)
    assert "settings_bed_temp" not in body and "nozzle_temp_first_layer" not in body["extra"]


def test_filament_body_validation():
    for bad, msg in (({"material": "PETG"}, "name"), ({"name": "x"}, "material"),
                     ({"name": "x", "material": "PETG", "color_hex": "lila"}, "Farbe"),
                     ({"name": "x", "material": "PETG", "extra": {"gibtsnicht": 1}}, "Zusatzfeld"),
                     ({"name": "x", "material": "PETG", "extra": {"vorlage": "Vorlage ABS"}}, "erlaubt"),
                     ({"name": "x", "material": "PETG", "vendor_id": 99}, "Hersteller"),
                     ({"name": "x", "material": "PETG", "remaining_weight": 5}, "nicht setzen"),
                     ({"name": "x", "material": "EXOTISCH"}, "density")):
        with pytest.raises(AppError, match=msg):
            build_filament_body(bad, FIELDS, VENDORS, [TPL_PETG], creating=True)
    # Aendern: null leert ein Feld (zurueck zur Vorlage)
    assert build_filament_body({"extra": {"flow_ratio": None}, "settings_bed_temp": None}, FIELDS, VENDORS,
                               [TPL_PETG], creating=False) == {"extra": {"flow_ratio": None}, "settings_bed_temp": None}


def test_extra_values_are_spoolman_json():
    assert convert_extra({"key": "a", "field_type": "integer"}, "249.6") == "250"
    assert convert_extra({"key": "a", "field_type": "boolean"}, "ja") == "true"
    assert convert_extra({"key": "a", "field_type": "text"}, "Generic PETG @System") == '"Generic PETG @System"'


def test_copy_keeps_product_line_values_but_not_name_and_colour():
    body = copy_filament_body(LAVENDEL, {"name": "PETG 2.0 Mintgrün", "color_hex": "3FA46A"}, FIELDS, VENDORS,
                              [TPL_PETG])
    assert body["name"] == "PETG 2.0 Mintgrün" and body["color_hex"] == "3FA46A" and body["vendor_id"] == 2
    assert body["settings_extruder_temp"] == 250 and body["weight"] == 1000
    assert body["extra"] == {"flow_ratio": "0.95", "vorlage": "\"Vorlage PETG\""}


def test_tag_numbers_and_uids():
    rng = random.Random(1)
    n = choose_tag_nr([1000, 1001], 1000, 1003, rng)
    assert n in (1002, 1003)
    with pytest.raises(AppError):
        choose_tag_nr([5, 6], 5, 6, rng)
    assert normalize_uid("04:a1:b2:c3:d4:e5:f6") == "04A1B2C3D4E5F6"
    assert normalize_uid("hallo") == ""


def test_tag_content_uses_filament_then_template():
    spool = {"id": 1, "initial_weight": 1000, "filament": LAVENDEL}
    t = tag_content(spool, [TPL_PETG], 4711, "AHPEBK")
    assert t["sku"] == "AHPEBK-4711" and t["brand"] == "Sunlu" and t["material"] == "PETG"
    assert t["color"] == "685BC7"
    assert (t["nozzle_min"], t["nozzle_max"]) == (250, 255)   # 250 vom Filament, 255 erste Schicht aus Vorlage
    assert (t["bed_min"], t["bed_max"]) == (75, 80)
    assert 310 < t["length_m"] < 340                          # 1 kg PETG 1,75 mm


def test_printer_state():
    st = {"print_stats": {"state": "printing", "filename": "a.gcode", "print_duration": 600},
          "virtual_sdcard": {"progress": 0.25}, "ace": {"current_index": 0, "target_index": -1}}
    p = printer_state(st, True, True, 1)
    assert p["state"] == "printing" and p["file"] == "a.gcode" and p["eta_s"] == 1800 and p["active_slot"] == 1
    assert p["changing_filament"] is False and p["mmu_action"] is None
    st["ace"] = {"current_index": -1, "target_index": 2}           # ACEPRO wechselt gerade auf Slot 3
    p = printer_state(st, True, True, None)
    assert p["changing_filament"] is True and p["mmu_action"] == "Wechsel auf Slot 3"
    assert printer_state(st, False, False, None)["state"] == "offline"
    idle = printer_state({"print_stats": {"state": "standby", "filename": "a.gcode"}}, True, True, None)
    assert idle["state"] == "standby" and idle["file"] is None and idle["progress"] is None
    assert idle["nozzle"] is None and idle["fans"] == []          # Drucker meldet nichts -> nichts anzeigen


def test_printer_state_machine_values():
    """Werte wie GoKlipper am S1 sie meldet (objects/query vom 01.10.)."""
    st = {"print_stats": {"state": "printing", "info": {"current_layer": 29, "total_layer": 65}},
          "extruder": {"temperature": 219.6, "target": 220, "power": 0.41},
          "heater_bed": {"temperature": 70, "target": 70, "power": 0.2},
          "fan": {"speed": 0.8, "rpm": 6120}, "fan_generic box_fan": {"name": "box_fan", "speed": 0.4},
          "fan_generic air_filter_fan": {"name": "air_filter_fan", "speed": 0},
          "gcode_move": {"speed_factor": 1.5, "extrude_factor": 0.95, "speed_mode": 2}}
    p = printer_state(st, True, True, 1)
    assert p["nozzle"] == {"temp": 219.6, "target": 220, "power": 0.41} and p["bed"]["target"] == 70
    assert [(f["key"], f["speed"]) for f in p["fans"]] == [("part", 0.8), ("box", 0.4), ("filter", 0)]
    assert p["fans"][0]["rpm"] == 6120 and "rpm" not in p["fans"][1]
    assert (p["speed_factor"], p["flow_factor"], p["speed_mode"]) == (1.5, 0.95, 2)
    assert (p["layer"], p["layers"]) == (29, 65)


# ====================================================================== HTTP-Routen
class MemSpoolman:
    """Spoolman im Speicher mit den Methoden, die Bridge und App-API nutzen."""

    def __init__(self, cfg):
        self.cfg = cfg
        self.connected = True
        self.vendors = [dict(v) for v in VENDORS]
        self.filaments = [json.loads(json.dumps(TPL_PETG)), json.loads(json.dumps(LAVENDEL))]
        self.spools = [{"id": 1, "location": "ACE Slot 1", "initial_weight": 1000, "remaining_weight": 978,
                        "filament": self.filaments[1], "extra": {}}]
        self.field_defs = {"filament": [dict(f) for f in FIELDS], "spool": [{"key": "nfc_uid", "field_type": "text"}]}
        self.calls = []
        self._next = 100

    async def refresh(self):
        return True

    def spool(self, sid):
        return next((s for s in self.spools if s["id"] == sid and not s.get("archived")), None)

    def filament(self, fid):
        return next((f for f in self.filaments if f["id"] == fid), None)

    def templates(self):
        return [f for f in self.filaments if (f.get("vendor") or {}).get("name") == "Vorlage"]

    def is_template(self, fil):
        return (fil.get("vendor") or {}).get("name") == "Vorlage"

    async def fields(self, entity, refresh=False):
        return self.field_defs[entity]

    async def ensure_field(self, entity, key, body):
        if not any(f["key"] == key for f in self.field_defs[entity]):
            self.field_defs[entity].append({"key": key, **body})
            self.calls.append(("field", entity, key))

    async def create(self, entity, data):
        self._next += 1
        self.calls.append(("create", entity, data))
        obj = {"id": self._next, **{k: v for k, v in data.items() if k != "vendor_id"}}
        if entity == "vendor":
            self.vendors.append(obj)
        elif entity == "filament":
            obj["vendor"] = next((v for v in self.vendors if v["id"] == data.get("vendor_id")), None)
            self.filaments.append(obj)
        else:
            obj["filament"] = self.filament(data["filament_id"])
            obj.setdefault("extra", {})
            self.spools.append(obj)
        return obj

    async def patch_spool(self, sid, data):
        self.calls.append(("patch_spool", sid, data))
        s = next(s for s in self.spools if s["id"] == sid)
        extra = data.get("extra") or {}
        s.update({k: v for k, v in data.items() if k != "extra"})
        for k, v in extra.items():
            if v is None:
                s["extra"].pop(k, None)
            else:
                s["extra"][k] = v
        return s

    async def patch_filament(self, fid, data):
        self.calls.append(("patch_filament", fid, data))
        return self.filament(fid)


class GMoon(FakeMoonraker):
    async def gcode(self, script, source="Bridge"):
        pass

    async def db_post(self, *a):
        pass

    async def db_delete(self, *a):
        pass


class FakeUsage:
    history = [{"file": "wuerfel.gcode", "ended": "2026-09-30T20:00:00", "state": "complete",
                "slots": [{"slot": 1, "spools": [{"id": 1, "mm": 3300.0}]}]}]
    open: list = []

    def grams(self, mm, sid):
        return mm * 0.003

    def live(self):
        return None

    def last_by_slot(self):
        return {}


class FakeBridge:
    def __init__(self, cfg):
        self.cfg = cfg
        self.moon = GMoon()
        self.moon.merge({**ace_status([{"material": "PETG", "color": "685BC7"}, {"material": "", "color": "000000"}],
                                      current=0),
                         "print_stats": {"state": "standby"}})
        self.sm = MemSpoolman(cfg)
        self.slots = SlotManager(cfg, self.moon, self.sm)
        self.usage = FakeUsage()
        self.dryer = Dryer(cfg, self.moon, self.slots)
        self.ace = AceSettings(self.moon, self.slots)
        self.devices = Devices(cfg.data_dir, cfg.app_token)
        self.camera_key = CameraKey(cfg.data_dir)
        self.console = Console()
        self.camera = Camera(cfg, self.moon, None)       # ohne Zuschauer kein Abruf
        self.preview = PrintPreview(cfg, self.moon, None)
        self.vision = Vision(cfg, self.moon, self.camera, None)  # VISION_URL leer: aus
        self.settings = RuntimeSettings(cfg)

    def safety_warnings(self):
        return []


@pytest.fixture
def api(cfg, tmp_path):
    cfg.app_token = "geheim"
    cfg.write_lane_data = False
    cfg.set_ace_slot_info = False
    bridge = FakeBridge(cfg)

    def call(method, path, body=None, token="geheim"):
        async def go():
            async with TestClient(TestServer(build_app(bridge))) as client:
                headers = {"Authorization": f"Bearer {token}"} if token else {}
                resp = await client.request(method, path, json=body, headers=headers)
                return resp.status, await resp.json()
        return asyncio.run(go())
    return bridge, call


def test_state_catalog_and_spool_detail(api):
    bridge, call = api
    status, st = call("GET", "/api/app/state", token=None)
    assert status == 200 and st["printer"]["state"] == "standby" and st["printer"]["active_slot"] == 1
    assert st["slots"][0]["spool"]["spool_id"] == 1 and st["can_write"] is False   # ohne Schluessel
    assert call("GET", "/api/app/state")[1]["can_write"] is True                     # mit Schluessel
    status, cat = call("GET", "/api/app/catalog", token=None)
    assert [v["name"] for v in cat["vendors"]] == ["Sunlu"]            # Vorlagen-Hersteller ausgeblendet
    assert cat["templates"][0]["name"] == "Vorlage PETG"
    assert {f["key"]: f["orca_key"] for f in cat["fields"]}["flow_ratio"] == "filament_flow_ratio"
    assert cat["filaments"][0]["display_name"] == "Sunlu PETG 2.0 Lavendelviolett"
    status, det = call("GET", "/api/app/spool/1", token=None)
    assert det["jobs"][0]["file"] == "wuerfel.gcode" and det["jobs"][0]["g"] == 9.9


def test_writes_need_the_token(api):
    bridge, call = api
    assert call("POST", "/api/app/vendor", {"name": "Elegoo"}, token=None)[0] == 401
    assert call("POST", "/api/app/vendor", {"name": "Elegoo"}, token="falsch")[0] == 401
    bridge.devices.legacy = ""          # kein APP_TOKEN, nichts gekoppelt -> Einrichtung noetig
    assert call("POST", "/api/app/vendor", {"name": "Elegoo"})[0] == 403


def test_every_write_route_needs_a_paired_device(api):
    """Slots, Trockner, offene Posten und Orca-Ruecksync: ohne Schluessel abgelehnt, Lesen bleibt offen."""
    bridge, call = api
    for method, path, body in (("POST", "/api/slots/1", {"spool_id": None}),
                               ("POST", "/api/dryer/start", {}), ("POST", "/api/dryer/stop", None),
                               ("POST", "/api/dryer/config", {"enabled": True}),
                               ("POST", "/api/open/x", {"spool_id": 1}), ("DELETE", "/api/open/x", None),
                               ("POST", "/api/orca/backsync", {"orca_id": "SM000020", "changes": {"a": 1}}),
                               ("POST", "/api/orca/reset", {"orca_id": "SM000020", "keys": ["a"]}),
                               ("PATCH", "/api/app/spool/1", {"comment": "x"}),
                               ("POST", "/api/ace/flush", {"multiplier": 1.0}),
                               ("POST", "/api/ace/options", {"auto_refill": True}),
                               ("POST", "/api/dryer/schedule", {"at": 9999999999}),
                               ("DELETE", "/api/dryer/schedule", None),
                               ("POST", "/api/camera/link", None), ("GET", "/api/camera/link", None),
                               ("POST", "/api/console", {"script": "M115"})):
        assert call(method, path, body, token=None)[0] == 401, path
        assert call(method, path, body, token="falsch")[0] == 401, path
    for path in ("/api/slots", "/api/dryer", "/api/orca/state", "/api/orca/profiles", "/api/app/state", "/api/ace"):
        assert call("GET", path, token=None)[0] == 200, path
    # mit Schluessel kommt die Anfrage durch (hier: Slot leeren)
    status, res = call("POST", "/api/slots/1", {"spool_id": None})
    assert status == 200 and res["slots"][0]["spool"] is None


def test_spool_patch(api):
    bridge, call = api
    status, res = call("PATCH", "/api/app/spool/1", {"remaining_weight": "812,5".replace(",", "."), "lot_nr": "L17",
                                                     "comment": "getrocknet"})
    assert status == 200 and res["spool"]["remaining_weight"] == 812.5 and res["spool"]["lot_nr"] == "L17"
    assert bridge.sm.calls[-1] == ("patch_spool", 1, {"remaining_weight": 812.5, "lot_nr": "L17",
                                                      "comment": "getrocknet"})
    # Spule im Slot: Lagerort nur ueber die Zuordnung; Slot-Ort nie als freier Text
    assert call("PATCH", "/api/app/spool/1", {"location": "Regal A"})[0] == 400
    call("POST", "/api/slots/1", {"spool_id": None})
    assert call("PATCH", "/api/app/spool/1", {"location": "ACE Slot 2"})[0] == 400
    status, res = call("PATCH", "/api/app/spool/1", {"location": "Regal A"})
    assert status == 200 and res["spool"]["location"] == "Regal A"
    assert call("PATCH", "/api/app/spool/1", {"filament_id": 5})[0] == 400
    assert call("PATCH", "/api/app/spool/1", {"remaining_weight": -3})[0] == 400


def test_create_vendor_filament_spool_into_slot(api):
    bridge, call = api
    status, v = call("POST", "/api/app/vendor", {"name": "Elegoo", "empty_spool_weight": "150"})
    assert status == 201
    assert call("POST", "/api/app/vendor", {"name": "elegoo"})[0] == 409
    status, f = call("POST", "/api/app/filament", {"name": "PETG Pro Weiß", "material": "PETG",
                                                  "vendor_id": v["vendor"]["id"], "color_hex": "FFFFFF",
                                                  "weight": 1000})
    assert status == 201 and f["filament"]["orca_id"].startswith("SM")
    status, sp = call("POST", "/api/app/spool", {"filament_id": f["filament"]["filament_id"], "slot": 2})
    assert status == 201 and sp["spool"]["slot"] == 2 and sp["spool"]["initial_weight"] == 1000


def test_copy_and_archive(api):
    bridge, call = api
    status, f = call("POST", "/api/app/filament/20/copy", {"name": "PETG 2.0 Mintgrün", "color_hex": "3FA46A"})
    assert status == 201 and f["filament"]["color"] == "3FA46A"
    assert call("POST", "/api/app/filament/10/copy", {"name": "x"})[0] == 404       # Vorlage ist kein Filament
    status, _ = call("POST", "/api/app/spool/1/archive")
    assert status == 200 and bridge.sm.spools[0]["archived"] is True
    assert bridge.sm.spools[0]["location"] == "Regal"


def test_tag_issue_link_lookup(api):
    bridge, call = api
    status, t = call("POST", "/api/app/tag/issue", {"spool_id": 1})
    assert status == 200 and t["tag"]["sku"] == f"AHPEBK-{t['tag']['tag_nr']}"
    assert ("field", "spool", "tag_nr") in bridge.sm.calls                # Feld wird bei Bedarf angelegt
    status, t2 = call("POST", "/api/app/tag/issue", {"spool_id": 1})
    assert t2["tag"]["tag_nr"] == t["tag"]["tag_nr"]                       # bleibt stabil
    status, _ = call("POST", "/api/app/tag/link", {"spool_id": 1, "uid": "04:A1:B2:C3:D4:E5:F6"})
    assert status == 200
    status, hit = call("GET", "/api/app/tag/04a1b2c3d4e5f6", token=None)
    assert status == 200 and hit["spool"]["spool_id"] == 1 and hit["spool"]["nfc_uid"] == "04A1B2C3D4E5F6"
    assert call("GET", "/api/app/tag/0000000000", token=None)[0] == 404


def test_two_tags_per_spool(api):
    """ACE 2 Pro: ein Tag pro Spulenseite. Zweiter Tag kommt dazu (reset=false), beide finden die Spule."""
    bridge, call = api
    call("POST", "/api/app/tag/link", {"spool_id": 1, "uid": "04A1B2C3D4E5F6", "reset": True})
    status, res = call("POST", "/api/app/tag/link", {"spool_id": 1, "uid": "04FFEEDDCCBBAA", "reset": False})
    assert status == 200 and res["spool"]["nfc_uids"] == ["04A1B2C3D4E5F6", "04FFEEDDCCBBAA"]
    assert res["spool"]["nfc_uid"] == "04A1B2C3D4E5F6"                    # aeltere Apps: erste Kennung
    for uid in ("04a1b2c3d4e5f6", "04ffeeddccbbaa"):
        assert call("GET", f"/api/app/tag/{uid}", token=None)[1]["spool"]["spool_id"] == 1
    # derselbe Tag noch einmal: keine Dublette
    res = call("POST", "/api/app/tag/link", {"spool_id": 1, "uid": "04FFEEDDCCBBAA", "reset": False})[1]
    assert res["spool"]["nfc_uids"] == ["04A1B2C3D4E5F6", "04FFEEDDCCBBAA"]
    # ein dritter: hoechstens zwei, der aelteste faellt raus
    res = call("POST", "/api/app/tag/link", {"spool_id": 1, "uid": "04111111111111", "reset": False})[1]
    assert res["spool"]["nfc_uids"] == ["04FFEEDDCCBBAA", "04111111111111"]
    # neu schreiben (Standard wie aeltere Apps): ersetzt beide
    res = call("POST", "/api/app/tag/link", {"spool_id": 1, "uid": "04222222222222"})[1]
    assert res["spool"]["nfc_uids"] == ["04222222222222"]
    assert call("GET", "/api/app/tag/04ffeeddccbbaa", token=None)[0] == 404


def test_orca_bases_are_stored(api, cfg):
    bridge, call = api
    names = {"names": ["Generic PETG @System", "Generic PLA @System"]}
    assert call("POST", "/api/orca/bases", names, token=None)[0] == 401      # Plugin muss gekoppelt sein
    status, res = call("POST", "/api/orca/bases", names)
    assert status == 200 and res["count"] == 2
    assert call("GET", "/api/app/catalog", token=None)[1]["orca_bases"] == ["Generic PETG @System",
                                                                             "Generic PLA @System"]


def test_bad_requests_and_spoolman_failures_never_break_the_bridge(api):
    """Die App ist nur ein Client: kaputte Anfragen oder ein ausgefallener Spoolman ergeben eine
    Fehlerantwort, die Bridge laeuft weiter (Status bleibt abrufbar)."""
    bridge, call = api

    async def raw(method, path, data, headers):
        async with TestClient(TestServer(build_app(bridge))) as client:
            resp = await client.request(method, path, data=data, headers=headers)
            return resp.status

    auth = {"Authorization": "Bearer geheim"}
    assert asyncio.run(raw("POST", "/api/app/filament", "kein json", auth)) == 400
    assert asyncio.run(raw("POST", "/api/app/spool", "[1, 2]", {**auth, "Content-Type": "application/json"})) == 400
    assert call("POST", "/api/app/spool", {"filament_id": "abc"})[0] == 400
    assert call("GET", "/api/app/spool/99999", token=None)[0] == 404

    async def boom(*a, **k):
        raise ConnectionError("Spoolman weg")
    bridge.sm.create = boom
    status, body = call("POST", "/api/app/vendor", {"name": "Elegoo"})
    assert status == 502 and "Spoolman weg" in body["error"]
    assert call("GET", "/api/app/state", token=None)[0] == 200
