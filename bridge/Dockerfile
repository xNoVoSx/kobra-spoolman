# ace-lane-bridge - Kobra S1 / ACE 2 Pro <-> Spoolman <-> OrcaSlicer
FROM python:3.12-slim

LABEL org.opencontainers.image.title="ace-lane-bridge" \
      org.opencontainers.image.description="Kobra S1 + ACE 2 Pro (Rinkhals/Moonraker) <-> Spoolman <-> OrcaSlicer: slot assignment, per-spool consumption booking, Orca profiles" \
      org.opencontainers.image.source="https://github.com/xNoVoSx/kobra-spoolman" \
      org.opencontainers.image.licenses="MIT"

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    DATA_DIR=/data \
    HTTP_PORT=7913

WORKDIR /app
COPY app/requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r /app/requirements.txt \
 && useradd --system --uid 1000 --home-dir /data bridge \
 && mkdir -p /data && chown bridge /data
COPY app/acebridge /app/acebridge

USER bridge
VOLUME ["/data"]
EXPOSE 7913
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
  CMD python -c "import os,urllib.request; urllib.request.urlopen('http://127.0.0.1:%s/api/health' % os.environ.get('HTTP_PORT','7913'), timeout=4)" || exit 1

CMD ["python", "-m", "acebridge"]
