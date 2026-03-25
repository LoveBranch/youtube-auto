"""
Imagen 3 이미지 생성 (Google Generative Language API)

settings.json의 tts.api_key를 재사용한다.
"""

import base64
import json
from pathlib import Path

import requests

SETTINGS_PATH = Path(__file__).resolve().parent.parent / "settings.json"


def load_settings() -> dict:
    if SETTINGS_PATH.exists():
        return json.loads(SETTINGS_PATH.read_text(encoding="utf-8"))
    return {}


def generate_image_gemini(prompt: str, api_key: str, output_path: str) -> str:
    """Imagen 3으로 이미지를 생성하여 저장한다."""
    resp = requests.post(
        f"https://generativelanguage.googleapis.com/v1beta/models/imagen-4.0-fast-generate-001:predict?key={api_key}",
        json={
            "instances": [{"prompt": prompt}],
            "parameters": {"sampleCount": 1},
        },
        timeout=90,
    )
    resp.raise_for_status()
    data = resp.json()

    predictions = data.get("predictions", [])
    if predictions:
        img_b64 = predictions[0].get("bytesBase64Encoded", "")
        if img_b64:
            Path(output_path).write_bytes(base64.b64decode(img_b64))
            return output_path

    raise ValueError(f"Imagen 이미지 생성 실패: {data}")
