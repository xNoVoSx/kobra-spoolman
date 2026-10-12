"""Prompts of Klipper macros (action:prompt_*) for the display - the same format Mainsail and KlipperScreen read
(docs.mainsail.xyz/features/macro-prompts):

    RESPOND TYPE=command MSG="action:prompt_begin Title"
    RESPOND TYPE=command MSG="action:prompt_text Text"
    RESPOND TYPE=command MSG="action:prompt_button Label|G-code|primary"
    RESPOND TYPE=command MSG="action:prompt_button_group_start" ... "action:prompt_button_group_end"
    RESPOND TYPE=command MSG="action:prompt_footer_button Label|G-code|error"
    RESPOND TYPE=command MSG="action:prompt_show"   /   "action:prompt_end"

The lines arrive as G-code responses ("// action:prompt_..."). A button sends exactly the G-code the macro gave it
(it comes from the printer itself, not from the display); afterwards the bridge closes the prompt, like Mainsail.
"""

from __future__ import annotations

import time
from typing import Any, Dict, List, Optional

from .i18n import tr

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
        self._draft: Optional[Dict[str, Any]] = None   # being built (between begin and show)
        self._group: Optional[List[Dict[str, Any]]] = None
        self.current: Optional[Dict[str, Any]] = None  # shown

    def feed(self, line: str) -> None:
        if "\n" in str(line):                      # several response lines in one text
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
            self._draft = {"title": arg or tr("Question"), "text": [], "items": [], "footer": [], "at": self.clock()}
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
        """The shown prompt without the G-codes (the display sends only the button number)."""
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
        """G-code of button number button_id of the shown prompt (KeyError if there is none)."""
        if not self.current:
            raise KeyError(tr("no prompt open"))
        buttons = [b for item in self.current["items"] for b in item["group"]] + list(self.current["footer"])
        if not isinstance(button_id, int) or isinstance(button_id, bool) or not 0 <= button_id < len(buttons):
            raise KeyError(tr("unknown button"))
        return buttons[button_id]["command"]

    def close(self) -> None:
        self.current = self._draft = self._group = None
