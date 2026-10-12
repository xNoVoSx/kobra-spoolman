"""Macro prompts (prompts.py): format like Mainsail/KlipperScreen, buttons only by number."""

from acebridge.prompts import Prompts


def feed(p, *lines):
    for line in lines:
        p.feed("// action:prompt_" + line)


def test_build_show_and_answer():
    p = Prompts(clock=lambda: 5.0)
    feed(p, "begin Filament Runout", "text Spool empty - insert a new one", "button_group_start",
         "button Load|T0|primary", "button Unload|ACE_SMART_UNLOAD", "button_group_end",
         "button Resume|RESUME|warning", "footer_button Cancel|CANCEL_PRINT|error")
    assert p.view() is None                          # only after show
    feed(p, "show")
    v = p.view()
    assert v["title"] == "Filament Runout" and v["text"] == ["Spool empty - insert a new one"]
    assert [[b["label"] for b in row] for row in v["rows"]] == [["Load", "Unload"], ["Resume"]]
    assert v["footer"] == [{"id": 3, "label": "Cancel", "style": "error"}]
    assert "command" not in str(v)                   # the G-code stays in the bridge
    assert [p.command(i) for i in range(4)] == ["T0", "ACE_SMART_UNLOAD", "RESUME", "CANCEL_PRINT"]


def test_end_close_and_bad_ids():
    p = Prompts()
    feed(p, "begin X", "button OK", "show")
    assert p.command(0) == "OK"                       # without G-code: the label is the command (like Mainsail)
    for bad in (1, -1, "0", True, None):
        try:
            p.command(bad)
            raise AssertionError(bad)
        except KeyError:
            pass
    feed(p, "end")
    assert p.view() is None
    p.feed("normal answer without a prompt")
    p.feed("// action:prompt_text verwaist")            # without begin: ignore
    assert p.view() is None
    feed(p, "begin Y", "show")
    p.close()
    assert p.view() is None


def test_several_lines_in_one_response():
    p = Prompts()
    p.feed("// action:prompt_begin A\n// action:prompt_button Resume|RESUME\n// action:prompt_show")
    assert p.view()["title"] == "A" and p.command(0) == "RESUME"
