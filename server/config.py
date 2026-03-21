"""전역 설정 로더."""

import json
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
SETTINGS_PATH = BASE_DIR / "settings.json"
SCRIPTS_DIR = BASE_DIR / "scripts"
CHANNELS_DIR = BASE_DIR / "channels"


def load_settings() -> dict:
    if SETTINGS_PATH.exists():
        return json.loads(SETTINGS_PATH.read_text(encoding="utf-8"))
    return {}


settings = load_settings()
