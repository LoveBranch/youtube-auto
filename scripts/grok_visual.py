"""
Grok Aurora API를 사용한 이미지 생성 + 영상 클립 변환

settings.json에서 xai.api_key를 읽는다.
"""

import base64
import json
import subprocess
import sys
from pathlib import Path

import requests

SETTINGS_PATH = Path(__file__).resolve().parent.parent / "settings.json"


def load_settings() -> dict:
    if SETTINGS_PATH.exists():
        return json.loads(SETTINGS_PATH.read_text(encoding="utf-8"))
    return {}


SETTINGS = load_settings()


def generate_image_grok(prompt: str, api_key: str, output_path: str) -> str:
    """Grok Aurora로 이미지를 생성하여 저장한다."""
    resp = requests.post(
        "https://api.x.ai/v1/images/generations",
        json={
            "model": "grok-2-image",
            "prompt": prompt,
            "n": 1,
            "response_format": "b64_json",
        },
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        timeout=120,
    )
    resp.raise_for_status()
    b64 = resp.json()["data"][0]["b64_json"]
    Path(output_path).write_bytes(base64.b64decode(b64))
    return output_path


def image_to_clip(image_path: str, output_path: str, duration: float = 4.0, aspect_ratio: str = "16:9") -> str:
    """이미지를 Ken Burns 효과 MP4 클립으로 변환한다."""
    resolutions = {"16:9": (1920, 1080), "9:16": (1080, 1920), "1:1": (1080, 1080)}
    w, h = resolutions.get(aspect_ratio, (1920, 1080))
    fps = 25
    frames = int(duration * fps)

    # Ken Burns (줌인 효과)
    # 정적 클립 생성 (zoompan은 메모리를 과도하게 사용해 Railway에서 OOM 발생)
    result = subprocess.run(
        [
            "ffmpeg", "-y",
            "-loop", "1", "-i", image_path,
            "-t", str(duration),
            "-vf", f"scale={w}:{h}:force_original_aspect_ratio=decrease,pad={w}:{h}:(ow-iw)/2:(oh-ih)/2",
            "-c:v", "libx264", "-crf", "23", "-pix_fmt", "yuv420p",
            "-r", str(fps),
            output_path,
        ],
        capture_output=True,
        timeout=120,
    )

    if result.returncode != 0:
        # 실패 시 불완전 파일 삭제 후 예외 발생
        import os
        if os.path.exists(output_path):
            os.remove(output_path)
        raise RuntimeError(
            f"image_to_clip 실패 (exit {result.returncode}): "
            f"{result.stderr.decode(errors='ignore')[-300:]}"
        )

    return output_path
