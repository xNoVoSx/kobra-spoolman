"""Rueckfragen von Klipper-Makros (action:prompt_*) fuer das Display - dasselbe Format, das Mainsail und KlipperScreen
lesen (docs.mainsail.xyz/features/macro-prompts):

    RESPOND TYPE=command MSG="action:prompt_begin Titel"
    RESPOND TYPE=command MSG="action:prompt_text Text"
    RESPOND TYPE=command MSG="action:prompt_button Beschriftung|G-Code|primary"
    RESPOND TYPE=command MSG="action:prompt_button_group_start" ... "action:prompt_button_group_end"
    RESPOND TYPE=command MSG="action:prompt_footer_button Beschriftung|G-Code|error"
    RESPOND TYPE=command MSG="action:prompt_show"   /   "action:prompt_end"

Die Zeilen kommen als G-Code-Antworten ("// action:prompt_..."). Ein Knopf schickt genau den G-Code, den das Makro fuer
ihn angegeben hat (kommt vom Drucker selbst, nicht vom Display); danach schliesst die Bridge die Rueckfrage, wie Mainsail.
"""

from __future__ import annotations

import time
from typing import Any, Dict, List, Optional

STYLES = ("primary", "secondary", "info", "warning", "error")


def _button(arg: str) -> Dict[str, Any]:
    parts = arg.split("|")
    label = parts[0].strip()
    command = parts[1].strip() if len(parts) > 1 and parts[1].strip() else label
    style = parts[2].strip() if len(parts) > 2 and parts[2].strip() in STYLES else None
    return {"label": label, "command": command, "style": style}


class Prompts:
    def __init__(self, clock=time.time):
        self.clock = clock
        self._draft: Optional[Dict[str, Any]] = None   # wird gerade aufgebaut (zwischen begin und show)
        self._group: Optional[List[Dict[str, Any]]] = None
        self.current: Optional[Dict[str, Any]] = None  # angezeigt

    def feed(self, line: str) -> None:
        if "\n" in str(line):                      # mehrere Antwortzeilen in einem Text
            for part in str(line).splitlines():
                self.feed(part)
            return
        text = str(line).strip()
        if text.startswith("//"):
            text = text[2:].strip()
        if not text.startswith("action:prompt_"):
            return
        cmd, _, arg = text[len("action:prompt_"):].partition(" ")
        arg = arg.strip()
        if cmd == "begin":
            self._draft = {"title": arg or "Frage", "text": [], "items": [], "footer": [], "at": self.clock()}
            self._group = None
            return
        if cmd == "end":
            self._draft = self._group = self.current = None
            return
        if self._draft is None:
            return
        if cmd == "text":
            self._draft["text"].append(arg)
        elif cmd == "button":
            btn = _button(arg)
            if self._group is not None:
                self._group.append(btn)
            else:
                self._draft["items"].append({"group": [btn]})
        elif cmd == "button_group_start":
            self._group = []
        elif cmd == "button_group_end":
            if self._group:
                self._draft["items"].append({"group": self._group})
            self._group = None
        elif cmd == "footer_button":
            self._draft["footer"].append(_button(arg))
        elif cmd == "show":
            self.current = self._draft

    def view(self) -> Optional[Dict[str, Any]]:
        """Angezeigte Rueckfrage ohne die G-Codes (das Display schickt nur die Nummer des Knopfs)."""
        if not self.current:
            return None
        c = self.current
        n = 0
        rows, footer = [], []
        for item in c["items"]:
            row = []
            for b in item["group"]:
                row.append({"id": n, "label": b["label"], "style": b["style"]})
                n += 1
            rows.append(row)
        for b in c["footer"]:
            footer.append({"id": n, "label": b["label"], "style": b["style"]})
            n += 1
        return {"title": c["title"], "text": c["text"], "rows": rows, "footer": footer, "at": c["at"]}

    def command(self, button_id: int) -> str:
        """G-Code des Knopfs Nummer button_id der angezeigten Rueckfrage (KeyError, wenn es ihn nicht gibt)."""
        if not self.current:
            raise KeyError("keine Rueckfrage offen")
        buttons = [b for item in self.current["items"] for b in item["group"]] + list(self.current["footer"])
        if not isinstance(button_id, int) or isinstance(button_id, bool) or not 0 <= button_id < len(buttons):
            raise KeyError("unbekannter Knopf")
        return buttons[button_id]["command"]

    def close(self) -> None:
        self.current = self._draft = self._group = None
