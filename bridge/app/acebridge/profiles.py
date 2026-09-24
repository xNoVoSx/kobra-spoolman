"""Aufloesung Filament -> Vorlage -> Orca-Basisprofil.

Etappe 1 nutzt davon nur die Grundwerte (Material, Temperaturen, Orca-ID) fuer
lane_data und die Slot-API. Etappe 3 baut darauf die vollstaendige Orca-Werteliste auf.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from .spoolman import extra_value

ORCA_ID_PREFIX = "SM"


def orca_filament_id(filament_id: int) -> str:
    """Stabile, eindeutige Orca-ID aus der Spoolman-Filament-ID (8 Zeichen wie bei Orca)."""
    return f"{ORCA_ID_PREFIX}{filament_id:06d}"


def find_template(filament: Dict[str, Any], templates: List[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    """Explizit ueber das Feld 'vorlage', sonst ueber das Material ("Vorlage <Material>")."""
    if not templates:
        return None
    wanted = extra_value(filament, "vorlage")
    if wanted:
        hit = next((t for t in templates if t.get("name") == wanted), None)
        if hit:
            return hit
    material = (filament.get("material") or "").strip().upper()
    if not material:
        return None
    exact = [t for t in templates if (t.get("material") or "").strip().upper() == material]
    if not exact:
        return None
    preferred = next((t for t in exact if (t.get("name") or "").upper() == f"VORLAGE {material}"), None)
    return preferred or sorted(exact, key=lambda t: t.get("id", 0))[0]


def _pick(filament: Dict[str, Any], template: Optional[Dict[str, Any]], native: str) -> Any:
    v = filament.get(native)
    if v is None and template is not None:
        v = template.get(native)
    return v


def color_hex(filament: Dict[str, Any]) -> str:
    c = filament.get("color_hex") or ""
    if not c and filament.get("multi_color_hexes"):
        c = filament["multi_color_hexes"].split(",")[0]
    c = c.strip().lstrip("#").upper()
    return c[:6] if len(c) >= 6 else ""


def basic_info(filament: Dict[str, Any], templates: List[Dict[str, Any]]) -> Dict[str, Any]:
    # Eigenes Orca-Basisprofil am Filament (z.B. "Anycubic PLA @Anycubic Kobra S1 0.4 nozzle")
    # ersetzt die Vorlage komplett - sonst wuerden die Generic-Werte der Vorlage die
    # abgestimmten Herstellerwerte ueberschreiben.
    own_basis = extra_value(filament, "orca_basis")
    tpl = None if own_basis else find_template(filament, templates)
    vendor = (filament.get("vendor") or {}).get("name") or ""
    return {
        "filament_id": filament.get("id"),
        "orca_filament_id": orca_filament_id(filament["id"]),
        "name": filament.get("name") or "",
        "vendor": vendor,
        "display_name": f"{vendor} {filament.get('name') or ''}".strip(),
        "material": filament.get("material") or (tpl or {}).get("material") or "",
        "color": color_hex(filament),
        "nozzle_temp": _pick(filament, tpl, "settings_extruder_temp"),
        "bed_temp": _pick(filament, tpl, "settings_bed_temp"),
        "template": (tpl or {}).get("name"),
        "orca_basis": own_basis or (extra_value(tpl, "orca_basis") if tpl else None),
    }
