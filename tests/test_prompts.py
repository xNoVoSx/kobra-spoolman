"""Rueckfragen von Makros (prompts.py): Format wie Mainsail/KlipperScreen, Knoepfe nur per Nummer."""

from acebridge.prompts import Prompts


def feed(p, *lines):
    for line in lines:
        p.feed("// action:prompt_" + line)


def test_build_show_and_answer():
    p = Prompts(clock=lambda: 5.0)
    feed(p, "begin Filament Runout", "text Spule leer - neue einlegen", "button_group_start",
         "button Laden|T0|primary", "button Entladen|ACE_SMART_UNLOAD", "button_group_end",
         "button Weiter|RESUME|warning", "footer_button Abbrechen|CANCEL_PRINT|error")
    assert p.view() is None                          # erst nach show
    feed(p, "show")
    v = p.view()
    assert v["title"] == "Filament Runout" and v["text"] == ["Spule leer - neue einlegen"]
    assert [[b["label"] for b in row] for row in v["rows"]] == [["Laden", "Entladen"], ["Weiter"]]
    assert v["footer"] == [{"id": 3, "label": "Abbrechen", "style": "error"}]
    assert "command" not in str(v)                   # G-Code bleibt in der Bridge
    assert [p.command(i) for i in range(4)] == ["T0", "ACE_SMART_UNLOAD", "RESUME", "CANCEL_PRINT"]


def test_end_close_and_bad_ids():
    p = Prompts()
    feed(p, "begin X", "button OK", "show")
    assert p.command(0) == "OK"                       # ohne G-Code: Beschriftung ist der Befehl (wie Mainsail)
    for bad in (1, -1, "0", True, None):
        try:
            p.command(bad)
            raise AssertionError(bad)
        except KeyError:
            pass
    feed(p, "end")
    assert p.view() is None
    p.feed("normale Antwort ohne Rueckfrage")
    p.feed("// action:prompt_text verwaist")            # ohne begin: ignorieren
    assert p.view() is None
    feed(p, "begin Y", "show")
    p.close()
    assert p.view() is None


def test_several_lines_in_one_response():
    p = Prompts()
    p.feed("// action:prompt_begin A\n// action:prompt_button Weiter|RESUME\n// action:prompt_show")
    assert p.view()["title"] == "A" and p.command(0) == "RESUME"
