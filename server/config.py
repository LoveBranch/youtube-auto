"""전역 설정 로더."""

import json
import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
SETTINGS_PATH = BASE_DIR / "settings.json"
SCRIPTS_DIR = BASE_DIR / "scripts"
CHANNELS_DIR = BASE_DIR / "channels"


def load_settings() -> dict:
    data: dict = {}
    if SETTINGS_PATH.exists():
        try:
            data = json.loads(SETTINGS_PATH.read_text(encoding="utf-8"))
        except Exception:
            pass

    # Railway 환경변수가 있으면 settings.json보다 우선 적용
    gemini_key = os.environ.get("GEMINI_API_KEY", "")
    if gemini_key:
        data.setdefault("tts", {})["api_key"] = gemini_key

    xai_key = os.environ.get("XAI_API_KEY", "")
    if xai_key:
        data.setdefault("xai", {})["api_key"] = xai_key

    return data


settings = load_settings()
