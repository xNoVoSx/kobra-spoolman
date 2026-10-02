"""Laedt Obicos ONNX-Modell und prueft die Pruefsumme (beim Bauen des Images oder fuer Tests).

    python fetch_model.py <ziel.onnx>
"""

import hashlib
import os
import sys
import urllib.request

# aus obico-server: ml_api/model/model-weights.onnx.url und .sha256
URL = "https://www.obico.io/static_pub/ml-models/model-weights-5a6b1be1fa.onnx"
SHA256 = "0a6ebd8e30dbf6a450c50f9c0a5406f04ba7eb1c99fd5996e888c78bb383b9aa"


def main(target: str) -> None:
    data = urllib.request.urlopen(URL, timeout=300).read()
    got = hashlib.sha256(data).hexdigest()
    if got != SHA256:
        sys.exit(f"Prüfsumme falsch: {got} (erwartet {SHA256})")
    os.makedirs(os.path.dirname(os.path.abspath(target)), exist_ok=True)
    with open(target, "wb") as f:
        f.write(data)
    print(f"{target}: {len(data) // 1024 // 1024} MB, Prüfsumme ok")


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "/models/obico-failure.onnx")
