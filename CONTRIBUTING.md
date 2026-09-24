# Contributing

Contributions are welcome - bug reports, ideas, documentation and code.

## Development setup

```bash
python3 -m venv .venv && . .venv/bin/activate
pip install -r bridge/app/requirements.txt -r requirements-dev.txt
pytest
```

The tests run without a printer: `tests/test_usage_replay.py` replays a real recorded
two-colour print through the consumption tracker, the other tests cover the Orca profile
mapping, back-sync and the plugin's profile builder.

## Guidelines

- Keep the principle: **Spoolman is the single source of truth** for filament data.
- No patches to printer firmware; the bridge only talks to Moonraker and Spoolman.
- Behaviour changes need a test and a CHANGELOG entry.
- Code comments are German (the project started that way); docs are English with a German
  translation in `docs/de/` - please keep both in sync where you can.
