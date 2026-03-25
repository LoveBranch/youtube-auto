"""
Gemini 2.0 Flash 이미지 생성 (무료 티어 사용 가능)

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
    """Gemini 2.0 Flash로 이미지를 생성하여 저장한다."""
    resp = requests.post(
        f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.0-flash-preview-image-generation:generateContent?key={api_key}",
        json={
            "contents": [{"parts": [{"text": prompt}]}],
            "generationConfig": {"responseModalities": ["IMAGE", "TEXT"]},
        },
        timeout=120,
    )
    resp.raise_for_status()
    data = resp.json()

    for candidate in data.get("candidates", []):
        for part in candidate.get("content", {}).get("parts", []):
            if "inlineData" in part:
                img_bytes = base64.b64decode(part["inlineData"]["data"])
                Path(output_path).write_bytes(img_bytes)
                return output_path

    raise ValueError(f"Gemini 이미지 생성 실패: {data}")
