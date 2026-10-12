"""Print phase (acebridge/phase.py): text from kobra_phase, auto PA, ACE change with sub step, layer."""

from acebridge import phase
from acebridge.appapi import printer_state


def st(state="printing", **objs):
    s = {"print_stats": {"state": state, "info": {}}}
    s.update(objs)
    return s


def text(status, steps=None):
    d = phase.describe(status, steps)
    return d["text"] if d else None


def test_start_phases_with_temperatures():
    assert text(st(kobra_phase={"phase": "heat_bed"}, heater_bed={"temperature": 63.4, "target": 100})) \
        == "Heating bed 63/100 °C"
    assert text(st(kobra_phase={"phase": "soak", "done": 5, "total": 15})) == "Heat soak 5/15 min"
    assert text(st(kobra_phase={"phase": "heat_nozzle"}, extruder={"temperature": 180, "target": 255})) \
        == "Heating nozzle 180/255 °C"
    assert text(st(kobra_phase={"phase": "cool"}, extruder={"temperature": 171.6, "target": 140})) \
        == "Cooling nozzle for probing (172 °C)"
    assert text(st(kobra_phase={"phase": "mesh"})) == "Measuring bed mesh"
    assert text(st(kobra_phase={"phase": "heat_bed"}, heater_bed={"temperature": 20, "target": 0})) == "Heating bed"


def test_layer_and_plain_printing():
    assert text(st(print_stats={"state": "printing", "info": {"current_layer": 34, "total_layer": 120}})) \
        == "Printing · layer 34/120"
    assert text(st()) == "Printing"


def test_not_printing_only_resume_change_and_pa():
    assert text(st("paused", kobra_phase={"phase": "mesh"})) is None
    assert text(st("standby", kobra_phase={"phase": "resume"})) == "Resuming print"
    assert text(st("standby", kobra_pa={"measuring": True})) == "Measuring pressure advance"
    assert text(st("standby")) is None
    assert text(st("error", kobra_phase={"phase": "wipe"})) is None, "abgebrochener Start: alte Phase nicht zeigen"


def test_pa_wins_over_phase():
    assert text(st(kobra_phase={"phase": "purge"}, kobra_pa={"measuring": True})) == "Measuring pressure advance"


def test_change_with_console_step():
    now = [1000.0]
    steps = phase.ChangeSteps(clock=lambda: now[0])
    s = st(kobra_phase={"phase": "change", "slot": 2, "since": 999.0})
    assert text(s, steps) == "Change to slot 2"
    steps.on_console({"text": "// ACE[M]: Pre toolchange"})
    assert text(s, steps) == "Change to slot 2 · heating"
    steps.on_console({"text": "// ACE: Smart unload tool 0 (current: 0)"})
    assert text(s, steps) == "Change to slot 2 · unloading"
    steps.on_console({"text": "// ACE[0]: Loading tool 1..."})
    assert text(s, steps) == "Change to slot 2 · loading"
    steps.on_console({"text": "// ACE[M]: Post toolchange"})
    assert text(s, steps) == "Change to slot 2 · purging"
    steps.on_console({"text": "// irgendwas anderes"})
    assert text(s, steps) == "Change to slot 2 · purging"
    # next change: the old sub step (before it starts) does not count
    now[0] = 1300.0
    s2 = st(kobra_phase={"phase": "change", "slot": 3, "since": 1290.0})
    assert text(s2, steps) == "Change to slot 3"


def test_change_without_kobra_phase_from_ace_target():
    s = st(ace={"current_index": 0, "target_index": 1})
    assert text(s) == "Change to slot 2"
    assert text(st(ace={"current_index": 1, "target_index": 1})) == "Printing"


def test_disabled_module_falls_back():
    assert text(st(kobra_phase={"phase": "mesh", "enabled": False})) == "Printing"


def test_printer_state_fields():
    s = st(kobra_phase={"phase": "soak", "done": 1, "total": 15})
    p = printer_state(s, True, True, None)
    assert p["phase"] == "Heat soak 1/15 min" and p["phase_key"] == "soak"
    p = printer_state(s, False, False, None)
    assert p["phase"] is None and p["phase_key"] is None
    idle = printer_state(st("standby"), True, True, None)
    assert idle["phase"] is None


def test_all_klipper_phases_have_text():
    # same list as kobra-klipper/klipper-extras/kobra_phase.py PHASES
    for key in ("heat_bed", "soak", "wipe", "cool", "home_z", "mesh", "heat_nozzle", "change", "purge", "pa", "prime",
                "resume", "end"):
        assert key in phase.TEXT


def test_texts_render_in_german():
    """Same phases in German (catalog locale/de.json) - what web, app and display show with language de."""
    t = phase.describe(st(kobra_phase={"phase": "heat_bed"}, heater_bed={"temperature": 63.4, "target": 100}))["text"]
    assert t.render("de") == "Heizt Bett 63/100 °C"
    steps = phase.ChangeSteps(clock=lambda: 1000.0)
    steps.on_console({"text": "ACE[M]: Purging 30mm"})
    t = phase.describe(st(kobra_phase={"phase": "change", "slot": 2, "since": 999.0}), steps)["text"]
    assert t.render("de") == "Wechsel auf Slot 2 · spült"   # i18n: keep
