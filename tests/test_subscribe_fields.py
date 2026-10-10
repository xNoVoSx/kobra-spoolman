"""Abo: Objekte, deren Felder erst spaeter auftauchen koennen (ACE nach dem Verbinden), nie mit None abonnieren -
Klipper friert bei None die Feldliste beim ersten Abfragen ein."""

from acebridge import acemodel
from acebridge.moonraker import OPTIONAL_OBJECTS


def test_ace_objects_have_explicit_fields():
    for obj in ("ace", "ace_instance_0"):
        fields = acemodel.SUBSCRIBE[obj]
        assert isinstance(fields, list) and fields, obj
    assert {"humidity", "firmware", "slots", "dryer_status", "temp"} <= set(acemodel.SUBSCRIBE["ace_instance_0"])
    assert {"current_index", "target_index", "endless_spool_enabled"} <= set(acemodel.SUBSCRIBE["ace"])


def test_no_optional_object_subscribes_all_fields():
    assert [k for k, v in OPTIONAL_OBJECTS.items() if v is None] == []
