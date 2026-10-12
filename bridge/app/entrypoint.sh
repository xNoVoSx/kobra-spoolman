#!/bin/sh
# Starts the bridge. The Python environment lives in the data folder and is only filled
# at the first start or when requirements.txt changed.
set -e

VENV="${DATA_DIR:-/data}/venv"
STAMP="$VENV/.requirements"

if [ ! -x "$VENV/bin/python" ]; then
    echo "[entrypoint] lege Python-Umgebung an: $VENV"
    python -m venv "$VENV"
fi

if [ "$(cat /app/requirements.txt)" != "$(cat "$STAMP" 2>/dev/null)" ]; then
    echo "[entrypoint] installiere Abhaengigkeiten"
    "$VENV/bin/pip" install --disable-pip-version-check -q -r /app/requirements.txt
    cp /app/requirements.txt "$STAMP"
fi

cd /app
exec "$VENV/bin/python" -m acebridge
