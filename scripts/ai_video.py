"""
AI Video Clip Generation (Hailuo/MiniMax & Pika)

이미지를 AI 동영상 클립으로 변환한다 (최대 5초).
- Hailuo (MiniMax): $0.10-0.15/clip — 기본값
- Pika: ~$0.20/clip — 대안

settings.json에서 hailuo.api_key 또는 pika.api_key를 읽는다.
"""

import base64
import json
import os
import sys
import time
from pathlib import Path

import requests

SETTINGS_PATH = Path(__file__).resolve().parent.parent / "settings.json"


def load_settings() -> dict:
    if SETTINGS_PATH.exists():
        return json.loads(SETTINGS_PATH.read_text(encoding="utf-8"))
    return {}


def generate_video_hailuo(
    image_path: str,
    prompt: str,
    api_key: str,
    output_path: str,
    duration: int = 5,
) -> str:
    """Hailuo (MiniMax) Image-to-Video API로 AI 동영상 클립 생성.

    MiniMax video-01 모델 사용. 이미지 + 프롬프트 → 동영상.
    최대 5초, 해상도 1280x720.
    """
    # 1) 이미지를 base64로 인코딩
    img_data = Path(image_path).read_bytes()
    img_b64 = base64.b64encode(img_data).decode("utf-8")
    mime = "image/jpeg" if image_path.lower().endswith((".jpg", ".jpeg")) else "image/png"

    # 2) MiniMax Video Generation API 호출
    resp = requests.post(
        "https://api.minimaxi.chat/v1/video_generation",
        json={
            "model": "video-01",
            "prompt": prompt,
            "first_frame_image": f"data:{mime};base64,{img_b64}",
        },
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        timeout=30,
    )
    resp.raise_for_status()
    task_id = resp.json().get("task_id")
    if not task_id:
        raise RuntimeError(f"Hailuo task creation failed: {resp.text}")

    # 3) 폴링 — 완료까지 대기 (최대 5분)
    for _ in range(60):
        time.sleep(5)
        poll = requests.get(
            f"https://api.minimaxi.chat/v1/query/video_generation?task_id={task_id}",
            headers={"Authorization": f"Bearer {api_key}"},
            timeout=30,
        )
        poll.raise_for_status()
        data = poll.json()
        status = data.get("status", "")
        if status == "Success":
            video_url = data.get("file_id", "")
            if not video_url:
                raise RuntimeError("Hailuo returned success but no file_id")
            # 4) 다운로드
            dl = requests.get(
                f"https://api.minimaxi.chat/v1/files/retrieve?file_id={video_url}",
                headers={"Authorization": f"Bearer {api_key}"},
                timeout=120,
            )
            dl.raise_for_status()
            file_url = dl.json().get("file", {}).get("download_url", "")
            if file_url:
                video_data = requests.get(file_url, timeout=120)
                video_data.raise_for_status()
                Path(output_path).write_bytes(video_data.content)
            return output_path
        elif status == "Fail":
            raise RuntimeError(f"Hailuo generation failed: {data}")

    raise TimeoutError("Hailuo video generation timed out (5 min)")


def generate_video_pika(
    image_path: str,
    prompt: str,
    api_key: str,
    output_path: str,
    duration: int = 5,
) -> str:
    """Pika Image-to-Video API로 AI 동영상 클립 생성.

    Pika v2 모델. 이미지 + 프롬프트 → 동영상 (3-5초).
    """
    img_data = Path(image_path).read_bytes()
    img_b64 = base64.b64encode(img_data).decode("utf-8")

    # 1) 생성 요청
    resp = requests.post(
        "https://api.pika.art/v1/generate",
        json={
            "model": "pika-v2",
            "image": img_b64,
            "prompt": prompt,
            "duration": min(duration, 5),
            "fps": 24,
        },
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        timeout=30,
    )
    resp.raise_for_status()
    task_id = resp.json().get("id") or resp.json().get("task_id")
    if not task_id:
        raise RuntimeError(f"Pika task creation failed: {resp.text}")

    # 2) 폴링 (최대 5분)
    for _ in range(60):
        time.sleep(5)
        poll = requests.get(
            f"https://api.pika.art/v1/generate/{task_id}",
            headers={"Authorization": f"Bearer {api_key}"},
            timeout=30,
        )
        poll.raise_for_status()
        data = poll.json()
        status = data.get("status", "")
        if status in ("completed", "success"):
            video_url = data.get("video_url") or data.get("output", {}).get("video_url", "")
            if not video_url:
                raise RuntimeError("Pika returned success but no video_url")
            dl = requests.get(video_url, timeout=120)
            dl.raise_for_status()
            Path(output_path).write_bytes(dl.content)
            return output_path
        elif status in ("failed", "error"):
            raise RuntimeError(f"Pika generation failed: {data}")

    raise TimeoutError("Pika video generation timed out (5 min)")


def generate_ai_video_clip(
    image_path: str,
    prompt: str,
    output_path: str,
    provider: str = "hailuo",
    duration: int = 5,
    settings: dict | None = None,
) -> str:
    """통합 AI video clip 생성 함수.

    provider: "hailuo" | "pika"
    duration: 최대 5초
    """
    settings = settings or load_settings()
    duration = min(duration, 5)  # 절대 5초 초과 금지

    if provider == "hailuo":
        api_key = (
            settings.get("hailuo", {}).get("api_key", "")
            or os.environ.get("HAILUO_API_KEY", "")
        )
        if not api_key:
            raise ValueError("Hailuo API key not found (settings.json → hailuo.api_key or HAILUO_API_KEY env)")
        return generate_video_hailuo(image_path, prompt, api_key, output_path, duration)
    elif provider == "pika":
        api_key = (
            settings.get("pika", {}).get("api_key", "")
            or os.environ.get("PIKA_API_KEY", "")
        )
        if not api_key:
            raise ValueError("Pika API key not found (settings.json → pika.api_key or PIKA_API_KEY env)")
        return generate_video_pika(image_path, prompt, api_key, output_path, duration)
    else:
        raise ValueError(f"Unknown AI video provider: {provider}")
