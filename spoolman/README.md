# spoolman_setup.py

One-time setup of Spoolman for this project (standard library only, tested with Spoolman 0.26.1):

- extra fields on **filaments** for the Orca settings (see [docs/spoolman-fields.md](../docs/spoolman-fields.md))
- extra field on **spools**: *NFC-Kennung*
- vendor **"Vorlage"** with seven material templates (PLA, PLA Silk, PETG, ASA, TPU, PLA-CF, PETG-CF)

```bash
python3 spoolman_setup.py --url http://<spoolman-host>:7912 --dry-run   # show the plan
python3 spoolman_setup.py --url http://<spoolman-host>:7912             # apply (asks first)
python3 spoolman_setup.py --url http://<spoolman-host>:7912 --yes       # apply without asking
```

It only creates what is missing — existing fields, vendors and filaments are never changed or
deleted. Note: Spoolman does not allow removing choices from a choice field later.
