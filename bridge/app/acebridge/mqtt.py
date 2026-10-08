"""Home Assistant ueber MQTT - die Bridge verteilt, was sie ohnehin weiss (Drucker, Slots, ACE, Meldungen, KI).

Der Drucker merkt davon nichts: alles stammt aus dem Moonraker-Abo der Bridge, keine eigene Verbindung fuer HA.
- Zustaende als JSON (retained) unter <MQTT_PREFIX>/printer, /ace, /slot/<n>, /notices, /vision;
  <MQTT_PREFIX>/status = online/offline (Testament/LWT).
- Home Assistant erkennt die Sensoren selbst (MQTT-Discovery unter <MQTT_DISCOVERY>/...), alle an einem Geraet
  "Kobra S1 (ace-lane-bridge)". MQTT_DISCOVERY leer = keine Discovery.
- Raumsensor (z. B. Zigbee2MQTT): ROOM_SENSOR_TOPIC abonnieren; JSON mit "humidity" (und "temperature") oder eine
  Zahl. Die gemessene Luftfeuchte ersetzt dann die eingestellte Raumfeuchte der Feuchte-Schaetzung (moisture.py).
Gesendet wird bei Aenderung, hoechstens alle 5 s; die Verbindung kommt nach Abbruechen von selbst wieder.
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from typing import TYPE_CHECKING, Any, Callable, Dict, List, Optional, Tuple

from .status import notices, printer_cpu

if TYPE_CHECKING:
    from .__main__ import Bridge

log = logging.getLogger("mqtt")

MIN_GAP_S = 5
RECONNECT_S = 15
ROOM_FRESH_S = 2 * 3600          # so lange gilt ein Messwert des Raumsensors


def _f(v: Any, digits: int = 1) -> Optional[float]:
    try:
        return round(float(v), digits)
    except (TypeError, ValueError):
        return None


def _de(x: float) -> str:
    return f"{x:g}".replace(".", ",")


def room_reading(payload: bytes) -> Tuple[Optional[float], Optional[float]]:
    """(Feuchte, Temperatur) aus einer Sensor-Nachricht: JSON wie Zigbee2MQTT oder nur eine Zahl."""
    text = payload.decode("utf-8", "ignore").strip()
    try:
        data = json.loads(text)
    except ValueError:
        return None, None
    if isinstance(data, (int, float)):
        return _f(data), None
    if isinstance(data, dict):
        return _f(data.get("humidity")), _f(data.get("temperature"))
    return None, None


class MqttBridge:
    def __init__(self, bridge: "Bridge", client_factory: Optional[Callable[..., Any]] = None,
                 clock: Callable[[], float] = time.time):
        self.b = bridge
        self.cfg = bridge.cfg
        self.clock = clock
        self.enabled = bool(self.cfg.mqtt_host)
        self.connected = False
        self.error: Optional[str] = None
        self.sent: Dict[str, str] = {}               # zuletzt gesendet je Thema (nur bei Aenderung neu)
        self.room: Optional[Dict[str, Any]] = None    # {"rh", "temp", "at"}
        self._client_factory = client_factory
        self._last_publish = 0.0
        self.prefix = self.cfg.mqtt_prefix.strip("/") or "kobra-spoolman"

    # ------------------------------------------------------------ Inhalte
    def payloads(self) -> Dict[str, Dict[str, Any]]:
        b = self.b
        st = b.moon.status
        ps = st.get("print_stats") or {}
        vsd = st.get("virtual_sdcard") or {}
        ext, bed = st.get("extruder") or {}, st.get("heater_bed") or {}
        info = ps.get("info") or {}
        state = ps.get("state") if b.moon.connected else "offline"
        prog = vsd.get("progress") or 0.0
        dur = ps.get("print_duration") or 0.0
        eta = (dur / prog - dur) if state == "printing" and prog > 0.01 and dur > 0 else None
        slots = b.slots.slots_view()
        active = next((s["slot"] for s in slots if s["ace"].get("active")), None)
        out: Dict[str, Dict[str, Any]] = {"printer": {
            "state": state, "progress": round(prog * 100, 1), "file": ps.get("filename") or None,
            "eta_min": round(eta / 60) if eta else None,
            "finish": time.strftime("%Y-%m-%dT%H:%M:%S%z", time.localtime(self.clock() + eta)) if eta else None,
            "layer": info.get("current_layer"), "layers": info.get("total_layer"),
            "nozzle": _f(ext.get("temperature")), "nozzle_target": _f(ext.get("target")),
            "bed": _f(bed.get("temperature")), "bed_target": _f(bed.get("target")),
            "active_slot": active, "cpu": _f(printer_cpu(b), 0)}}
        d = b.dryer.state()
        out["ace"] = {"humidity": d.get("humidity"), "temp": d.get("temp"), "drying": bool(d.get("drying")),
                      "target": d.get("target_temp"), "remaining_min": d.get("remaining_min")}
        for s in slots:
            sp = s.get("spool") or {}
            spool = b.sm.spool(sp["spool_id"]) if sp.get("spool_id") else None
            mv = b.moisture.view(spool) if spool else {}
            color = (sp.get("color") or s["ace"].get("color") or "")[:6]
            out[f"slot/{s['slot']}"] = {
                "spool": sp.get("display_name") or None, "spool_id": sp.get("spool_id"),
                "material": sp.get("material") or s["ace"].get("material") or None,
                "color": "#" + color if color else None,
                "remaining_g": _f(sp.get("remaining_weight"), 0), "moisture": mv.get("score"),
                "needs_drying": bool(mv.get("needs_drying")), "loaded": bool(s["ace"].get("present"))}
        n = notices(b)
        msgs = n.get("messages", [])
        out["notices"] = {"count": len(msgs), "errors": sum(m["level"] == "error" for m in msgs),
                          "warnings": sum(m["level"] == "warn" for m in msgs),
                          "top": msgs[0]["text"] if msgs else "alles gut", "messages": [m["text"] for m in msgs[:10]]}
        v = getattr(b, "vision", None)
        if v is not None and v.configured:
            out["vision"] = {"level": v.level, "score": v.pred.score(v.settings.sensitivity), "muted": bool(v.muted)}
        return out

    def discovery(self) -> List[Tuple[str, Dict[str, Any]]]:
        """(Thema, Konfiguration) fuer Home Assistants MQTT-Discovery."""
        base = (self.cfg.mqtt_discovery or "").strip("/")
        if not base:
            return []
        from . import __version__
        dev = {"identifiers": [f"{self.prefix}"], "name": "Kobra S1 (ace-lane-bridge)", "manufacturer": "kobra-spoolman",
               "model": "Kobra S1 + ACE 2 Pro", "sw_version": __version__}
        avail = {"availability_topic": f"{self.prefix}/status", "payload_available": "online", "payload_not_available": "offline"}
        out: List[Tuple[str, Dict[str, Any]]] = []

        def ent(comp: str, oid: str, name: str, topic: str, tpl: str, **extra: Any) -> None:
            uid = f"{self.prefix}_{oid}".replace("/", "_").replace("-", "_")
            out.append((f"{base}/{comp}/{uid}/config", {"name": name, "unique_id": uid, "object_id": uid,
                                                       "state_topic": f"{self.prefix}/{topic}", "value_template": tpl,
                                                       "device": dev, **avail, **extra}))
        ent("sensor", "state", "Druckerstatus", "printer", "{{ value_json.state }}", icon="mdi:printer-3d")
        ent("sensor", "progress", "Fortschritt", "printer", "{{ value_json.progress }}", unit_of_measurement="%", icon="mdi:progress-clock")
        ent("sensor", "eta", "Restzeit", "printer", "{{ value_json.eta_min }}", unit_of_measurement="min", device_class="duration")
        ent("sensor", "finish", "Fertig um", "printer", "{{ value_json.finish }}", device_class="timestamp")
        ent("sensor", "file", "Druckdatei", "printer", "{{ value_json.file }}", icon="mdi:file")
        ent("sensor", "layer", "Schicht", "printer", "{{ value_json.layer }}", icon="mdi:layers")
        ent("sensor", "nozzle", "Düse", "printer", "{{ value_json.nozzle }}", unit_of_measurement="°C", device_class="temperature")
        ent("sensor", "bed", "Bett", "printer", "{{ value_json.bed }}", unit_of_measurement="°C", device_class="temperature")
        ent("sensor", "cpu", "Klipper-CPU (Pi)", "printer", "{{ value_json.cpu }}", unit_of_measurement="%", icon="mdi:cpu-32-bit",
            entity_category="diagnostic")
        ent("sensor", "ace_humidity", "ACE Feuchte", "ace", "{{ value_json.humidity }}", unit_of_measurement="%", device_class="humidity")
        ent("sensor", "ace_temp", "ACE Temperatur", "ace", "{{ value_json.temp }}", unit_of_measurement="°C", device_class="temperature")
        ent("binary_sensor", "ace_drying", "ACE trocknet", "ace", "{{ 'ON' if value_json.drying else 'OFF' }}", device_class="running")
        for n in range(1, self.b.slots.num_gates() + 1):
            ent("sensor", f"slot{n}_spool", f"Slot {n} Spule", f"slot/{n}", "{{ value_json.spool or 'leer' }}", icon="mdi:printer-3d-nozzle")
            ent("sensor", f"slot{n}_remaining", f"Slot {n} Rest", f"slot/{n}", "{{ value_json.remaining_g }}",
                unit_of_measurement="g", device_class="weight")
            ent("sensor", f"slot{n}_moisture", f"Slot {n} Feuchte-Schätzung", f"slot/{n}", "{{ value_json.moisture }}",
                unit_of_measurement="%", icon="mdi:water-percent")
        ent("sensor", "notices", "Meldungen", "notices", "{{ value_json.count }}", icon="mdi:bell")
        ent("sensor", "notice_top", "Wichtigste Meldung", "notices", "{{ value_json.top }}", icon="mdi:message-alert")
        if getattr(self.b, "vision", None) is not None and self.b.vision.configured:
            ent("sensor", "vision", "KI", "vision", "{{ value_json.level }}", icon="mdi:eye")
            ent("sensor", "vision_score", "KI Wert", "vision", "{{ (value_json.score * 100) | round(0) }}", unit_of_measurement="%")
        return out

    # ------------------------------------------------------------ Raumsensor
    def on_room(self, payload: bytes) -> None:
        rh, temp = room_reading(payload)
        if rh is None or not 0 <= rh <= 100:
            return
        self.room = {"rh": rh, "temp": temp, "at": self.clock()}

    def room_rh(self) -> Optional[float]:
        """Gemessene Raumfeuchte, solange frisch (sonst None -> eingestellter Wert)."""
        if self.room and self.clock() - self.room["at"] <= ROOM_FRESH_S:
            return self.room["rh"]
        return None

    # ------------------------------------------------------------ Senden
    async def publish_changes(self, client: Any, force: bool = False) -> int:
        n = 0
        for topic, data in self.payloads().items():
            text = json.dumps(data, ensure_ascii=False, separators=(",", ":"))
            full = f"{self.prefix}/{topic}"
            if force or self.sent.get(full) != text:
                await client.publish(full, text, retain=True)
                self.sent[full] = text
                n += 1
        self._last_publish = self.clock()
        return n

    async def run(self) -> None:
        if not self.enabled:
            return
        import aiomqtt
        factory = self._client_factory or aiomqtt.Client
        status = f"{self.prefix}/status"
        log.info("MQTT: %s:%s, Präfix %s, Discovery %s%s", self.cfg.mqtt_host, self.cfg.mqtt_port, self.prefix,
                 self.cfg.mqtt_discovery or "aus", f", Raumsensor {self.cfg.room_sensor_topic}" if self.cfg.room_sensor_topic else "")
        while True:
            try:
                async with factory(self.cfg.mqtt_host, self.cfg.mqtt_port, username=self.cfg.mqtt_user or None,
                                   password=self.cfg.mqtt_password or None, identifier=f"{self.prefix}-bridge",
                                   will=aiomqtt.Will(status, "offline", retain=True)) as client:
                    self.connected, self.error = True, None
                    log.info("MQTT verbunden")
                    await client.publish(status, "online", retain=True)
                    for topic, conf in self.discovery():
                        await client.publish(topic, json.dumps(conf, ensure_ascii=False), retain=True)
                    if self.cfg.room_sensor_topic:
                        await client.subscribe(self.cfg.room_sensor_topic)
                    await self.publish_changes(client, force=True)
                    listener = asyncio.create_task(self._listen(client))
                    try:
                        while True:
                            await asyncio.sleep(MIN_GAP_S)
                            await self.publish_changes(client)
                    except asyncio.CancelledError:
                        # Bridge wird beendet: sauberes Trennen loest das Testament nicht aus -> selbst melden
                        try:
                            await asyncio.wait_for(client.publish(status, "offline", retain=True), 2)
                        except Exception:  # noqa: BLE001
                            pass
                        raise
                    finally:
                        listener.cancel()
                        self.connected = False
            except asyncio.CancelledError:
                raise
            except Exception as e:  # noqa: BLE001  (aiomqtt.MqttError, OSError ...)
                if self.connected or self.error is None:
                    log.warning("MQTT getrennt: %s – neuer Versuch in %d s", e, RECONNECT_S)
                self.connected, self.error = False, f"nicht erreichbar: {e}"
                await asyncio.sleep(RECONNECT_S)

    async def _listen(self, client: Any) -> None:
        async for message in client.messages:
            if self.cfg.room_sensor_topic and str(message.topic) == self.cfg.room_sensor_topic:
                self.on_room(message.payload if isinstance(message.payload, bytes) else str(message.payload).encode())

    def status_lines(self) -> List[Dict[str, Any]]:
        out = []
        if self.enabled:
            out.append({"key": "mqtt", "label": "MQTT / HA", "state": "ok" if self.connected else "warn",
                        "detail": f"verbunden · {len(self.sent)} Themen" if self.connected else (self.error or "verbindet …")})
        if self.cfg.room_sensor_topic:
            r = self.room
            if r and self.room_rh() is not None:
                age = int((self.clock() - r["at"]) / 60)
                out.append({"key": "room", "label": "Raumsensor", "state": "ok",
                            "detail": _de(r["rh"]) + " %" + (f" · {_de(r['temp'])} °C" if r.get("temp") is not None else "")
                            + f" · vor {age} min"})
            else:
                out.append({"key": "room", "label": "Raumsensor", "state": "warn",
                            "detail": f"kein aktueller Wert – rechne mit {_de(self.cfg.room_rh)} %"})
        return out
