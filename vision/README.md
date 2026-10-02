# kobra-vision

AI print-failure detection for [ace-lane-bridge](../bridge): a small HTTP service that runs
[Obico](https://github.com/TheSpaghettiDetective/obico-server)'s failure model with ONNX Runtime.
The bridge sends it a camera picture every 10 s while printing and judges the results over time.

Everything about how it works, setup and settings: **[docs/vision.md](../docs/vision.md)**.

```bash
pip install -r requirements.txt
python fetch_model.py ./models/obico-failure.onnx         # downloads Obico's ONNX model, checks SHA-256
MODEL_PATH=./models/obico-failure.onnx python -m kobravision
curl -X POST -H "Content-Type: image/jpeg" --data-binary @picture.jpg http://127.0.0.1:7917/v1/detect
```

Tests: `pytest` (without the model); with `MODEL_PATH` and `TEST_IMAGES` (a folder with
`kobra_clean.jpg` and `spaghetti_monster.jpg`) also against the real model.

## Licence

AGPL-3.0 ([LICENSE](LICENSE)) — it runs Obico's model and post-processing (obico-server is AGPL-3.0).
The model itself is not part of this repository; the Docker image downloads it while building.
The rest of kobra-spoolman is MIT and talks to this service over HTTP only.
