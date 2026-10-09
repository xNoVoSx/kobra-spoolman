# kobra-vision - Fehldruck-Erkennung fuer die ace-lane-bridge (Obicos "failure"-Modell, ONNX)
# Standard: CPU (reicht: ~50 ms pro Bild mit 2 Threads). Mit Nvidia-Grafikkarte:
#   docker build --build-arg ORT=onnxruntime-gpu -t kobra-vision:gpu vision/   und USE_GPU=true
# Offizielles Python-Image ueber den AWS-Spiegel (gleicher Inhalt wie Docker Hub, ohne dessen Abruf-Limit fuer CI)
FROM public.ecr.aws/docker/library/python:3.12-slim

ARG ORT=onnxruntime

LABEL org.opencontainers.image.title="kobra-vision" \
      org.opencontainers.image.description="Print-failure detection for ace-lane-bridge (Obico failure model, ONNX Runtime)" \
      org.opencontainers.image.source="https://github.com/xNoVoSx/kobra-spoolman" \
      org.opencontainers.image.licenses="AGPL-3.0-only"

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    MODEL_PATH=/models/obico-failure.onnx \
    HTTP_PORT=7917

WORKDIR /app
COPY requirements.txt fetch_model.py /app/
RUN sed -i "s/^onnxruntime\b/${ORT}/" /app/requirements.txt \
 && pip install --no-cache-dir -r /app/requirements.txt \
 && python /app/fetch_model.py /models/obico-failure.onnx \
 && useradd --system --uid 1000 vision
COPY kobravision /app/kobravision
COPY LICENSE /app/LICENSE

USER vision
EXPOSE 7917
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
  CMD python -c "import os,urllib.request; urllib.request.urlopen('http://127.0.0.1:%s/v1/health' % os.environ.get('HTTP_PORT','7917'), timeout=4)" || exit 1

CMD ["python", "-m", "kobravision"]
