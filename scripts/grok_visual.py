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

    # Ken Burns 효과 (Railway 메모리 최적화 버전)
    # 출력 해상도를 1280x720으로 낮추고 스케일업을 1.5배로 제한하여 OOM 방지
    cloud_w, cloud_h = (1280, 720) if aspect_ratio == "16:9" else (720, 1280) if aspect_ratio == "9:16" else (720, 720)
    sw, sh = int(cloud_w * 1.5), int(cloud_h * 1.5)
    # 씬 인덱스에 따라 효과 순환
    import hashlib
    effect_idx = int(hashlib.md5(image_path.encode()).hexdigest(), 16) % 4
    effects = ["zoom_in", "zoom_out", "pan_left", "pan_right"]
    effect = effects[effect_idx]
    smooth = f"(1/(1+exp(-12*(on/{frames}-0.5))))"
    if effect == "zoom_in":
        z = f"1+0.15*{smooth}"
        x = "iw/2-(iw/zoom/2)"
        y = "ih/2-(ih/zoom/2)"
    elif effect == "zoom_out":
        z = f"1.15-0.15*{smooth}"
        x = "iw/2-(iw/zoom/2)"
        y = "ih/2-(ih/zoom/2)"
    elif effect == "pan_left":
        z = "1.12"
        x = f"(iw*0.06)*(1-{smooth})"
        y = "ih/2-(ih/zoom/2)"
    else:
        z = "1.12"
        x = f"(iw*0.06)*{smooth}"
        y = "ih/2-(ih/zoom/2)"
    vf = f"scale={sw}x{sh},zoompan=z='{z}':x='{x}':y='{y}':d={frames}:s={cloud_w}x{cloud_h}:fps={fps}"

    result = subprocess.run(
        [
            "ffmpeg", "-y",
            "-threads", "1",
            "-loop", "1", "-i", image_path,
            "-vf", vf,
            "-c:v", "libx264", "-preset", "ultrafast", "-crf", "23", "-pix_fmt", "yuv420p",
            "-t", str(duration),
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
