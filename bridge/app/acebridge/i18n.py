"""Translations: English is the source language, German the second language.

User-facing text is written in English and wrapped in ``tr()``::

    tr("PA for {name} measured: {k:.3f}", name=name, k=k)

``tr()`` returns a ``Text``: a ``str`` holding the English rendering (so logging, comparisons and old code keep
working) that also remembers its template and arguments. Texts are often built long before anyone reads them (events,
messages, switch labels), so the language is chosen when a response is sent: ``localize()`` walks the response and
renders every ``Text`` in the language of the requesting device (see ``request_lang``). Everything that is not a
request (MQTT / Home Assistant) uses the bridge's default language.

Catalogs: ``locale/<lang>.json`` maps the English template to the translated template (same ``{placeholders}``).
``tests/test_i18n.py`` checks that every ``tr()`` template in the code has a German entry and vice versa.

Rules: build texts from arguments, never by concatenating ``Text`` objects (``tr("a") + "b"`` is a plain English str).
"""

from __future__ import annotations

import contextvars
import json
import logging
import os
from typing import Any, Callable, Dict, List, Optional

log = logging.getLogger("i18n")

LANGS = ("en", "de")
SOURCE_LANG = "en"                                # language the code is written in
_HERE = os.path.dirname(os.path.abspath(__file__))
_catalogs: Dict[str, Dict[str, str]] = {}
_default: List[Callable[[], str]] = [lambda: SOURCE_LANG]   # bridge default (setting "language", see bind)
_current: contextvars.ContextVar[Optional[str]] = contextvars.ContextVar("lang", default=None)


def catalog(lang: str) -> Dict[str, str]:
    if lang not in _catalogs:
        path = os.path.join(_HERE, "locale", f"{lang}.json")
        try:
            with open(path, encoding="utf-8") as fh:
                _catalogs[lang] = json.load(fh)
        except (OSError, ValueError):
            _catalogs[lang] = {}
    return _catalogs[lang]


class Text(str):
    """English text that can render itself in another language (template + arguments)."""

    __slots__ = ("msg", "args")
    msg: str
    args: Dict[str, Any]

    def __new__(cls, msg: str, **args: Any) -> "Text":
        obj = super().__new__(cls, _fill(msg, args, SOURCE_LANG))
        obj.msg, obj.args = msg, args
        return obj

    def render(self, lang: Optional[str] = None) -> str:
        lang = lang or current_lang()
        if lang == SOURCE_LANG:
            return str.__str__(self)
        return _fill(catalog(lang).get(self.msg) or self.msg, self.args, lang)

    def __reduce__(self):
        return (str, (str.__str__(self),))


DECIMAL_COMMA = ("de",)


class _Num:
    """A float that formats with a decimal comma where the language uses one (12.5 -> "12,5")."""

    __slots__ = ("v",)

    def __init__(self, v: float):
        self.v = v

    def __format__(self, spec: str) -> str:
        return format(self.v, spec or "g").replace(".", ",")


def _fill(msg: str, args: Dict[str, Any], lang: str) -> str:
    if not args:
        return msg
    vals = {k: (v.render(lang) if isinstance(v, Text)
                else _Num(v) if isinstance(v, float) and lang in DECIMAL_COMMA else v) for k, v in args.items()}
    try:
        return msg.format(**vals)
    except (KeyError, IndexError, ValueError) as e:
        log.warning("Translation %r does not fit its arguments %s: %s", msg, sorted(vals), e)
        return msg


def msg_of(e: BaseException) -> str:
    """Message of an exception, keeping a translatable text (str(e) would be its English rendering)."""
    first = e.args[0] if e.args else None
    return first if isinstance(first, Text) else str(e)


def tr(msg: str, **args: Any) -> Text:
    """Mark ``msg`` (English) as user-facing text; ``args`` fill its ``{placeholders}``."""
    return Text(msg, **args)


# ------------------------------------------------------------------ language of the current request
def bind(get_default: Callable[[], str]) -> None:
    """Where the bridge default comes from (cfg.language - can change at runtime)."""
    _default[0] = get_default


def default_lang() -> str:
    lang = _default[0]()
    return lang if lang in LANGS else SOURCE_LANG


def current_lang() -> str:
    return _current.get() or default_lang()


def use(lang: Optional[str]) -> contextvars.Token:
    """Language for the rest of this task (a request handler); ``None`` = bridge default."""
    return _current.set(lang if lang in LANGS else None)


def reset(token: contextvars.Token) -> None:
    _current.reset(token)


def request_lang(headers: Any, query: Any = None) -> Optional[str]:
    """Language a client asked for: ``?lang=``, header ``X-Lang`` (web, app, display), else ``Accept-Language``
    (browsers send it on their own). ``None`` = not stated (bridge default)."""
    for v in ((query or {}).get("lang"), headers.get("X-Lang")):
        if v and v[:2].lower() in LANGS:
            return v[:2].lower()
    for part in (headers.get("Accept-Language") or "").split(","):
        code = part.split(";")[0].strip()[:2].lower()
        if code in LANGS:
            return code
    return None


def localize(obj: Any, lang: Optional[str] = None) -> Any:
    """Copy of ``obj`` with every ``Text`` rendered in ``lang`` (default: current request)."""
    lang = lang or current_lang()
    if isinstance(obj, Text):
        return obj.render(lang)
    if isinstance(obj, dict):
        return {k: localize(v, lang) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [localize(v, lang) for v in obj]
    return obj


def dumps(obj: Any) -> str:
    """``json.dumps`` for responses: texts in the request's language."""
    return json.dumps(localize(obj))
