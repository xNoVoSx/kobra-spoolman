# Contributing

Contributions are welcome - bug reports, ideas, documentation and code.

## Development setup

```bash
python3 -m venv .venv && . .venv/bin/activate
pip install -r bridge/app/requirements.txt -r requirements-dev.txt
pytest
```

The tests run without a printer: `tests/test_usage_rinkhals.py` and `tests/test_usage_acepro.py` replay real
recorded prints through the consumption tracker (one per firmware), the other tests cover the Orca profile mapping,
back-sync, the plugin, the web UI's and the app's texts, and both firmware variants of the ACE. Lint with `ruff check .`.
The Android app builds with Gradle in `android/` (`./gradlew testDebugUnitTest assembleDebug`).

## Guidelines

- Keep the principle: **Spoolman is the single source of truth** for filament data.
- No patches to printer firmware; the bridge only talks to Moonraker and Spoolman.
- Both firmwares stay supported: anything that depends on Rinkhals or Klipper + ACEPRO goes through `acemodel.py`.
- Every feature can be switched off and must never get in the way of printing.
- Behaviour changes need a test and a CHANGELOG entry.
- **English first:** code, comments, logs, API and docs are English. User-facing texts are English source strings in
  `tr()` / `t()` with a German entry in the catalogs (`locale/de.json`, `static/i18n/de.json`, the app's
  `assets/i18n/de.json`, the plugin's `DE`); the tests fail on a missing entry. The German docs in `docs/de/` and
  `README.de.md` are kept in sync where possible.
- The project is developed with an AI coding assistant (see the README's AI notice); contributions written with AI tools
  are welcome — you are responsible for what you submit, so test it.
