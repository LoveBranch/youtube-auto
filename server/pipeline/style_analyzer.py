"""소스 영상의 스타일을 Gemini로 분석한다."""

import base64
import subprocess
import tempfile
from pathlib import Path

import requests
from server.config import settings


def extract_frames(video_path: Path, count: int = 4) -> list[bytes]:
    """영상에서 균등 간격으로 프레임을 추출한다."""
    frames = []
    for i in range(count):
        with tempfile.NamedTemporaryFile(suffix=".jpg", delete=False) as f:
            tmp_path = f.name

        # 영상 길이 대비 균등 위치에서 프레임 추출
        position = f"{i}/{count}"
        subprocess.run(
            [
                "ffmpeg", "-y", "-i", str(video_path),
                "-vf", f"select=eq(n\\,{i * 30})",
                "-frames:v", "1",
                tmp_path,
            ],
            capture_output=True, timeout=30,
        )

        tmp = Path(tmp_path)
        if tmp.exists() and tmp.stat().st_size > 0:
            frames.append(tmp.read_bytes())
            tmp.unlink()

    return frames


def analyze_style(video_path: Path | None = None, url: str | None = None, language: str = "ko") -> dict:
    """Gemini Vision으로 영상 스타일을 분석한다."""
    api_key = settings.get("tts", {}).get("api_key", "")
    if not api_key:
        raise ValueError("Gemini API 키 필요")

    parts = []

    if video_path and video_path.exists():
        frames = extract_frames(video_path)
        for frame in frames:
            parts.append({
                "inlineData": {
                    "mimeType": "image/jpeg",
                    "data": base64.b64encode(frame).decode(),
                }
            })
    elif url:
        parts.append({"text": f"이 YouTube 영상을 분석하세요: {url}"})

    lang_names = {"ko": "한국어", "en": "English", "ja": "日本語"}
    lang_name = lang_names.get(language, language)

    parts.append({"text": f"""이 영상의 스타일을 분석하여 다음 JSON 형식으로 {lang_name}로 응답하세요:

{{
  "tone": "영상의 전체적인 톤 (예: 차분한 교육, 활기찬 엔터테인먼트, 진지한 다큐)",
  "visual_mood": "비주얼 분위기 (예: 어두운 시네마틱, 밝고 깔끔한, 따뜻한 톤)",
  "color_palette": "주요 색감 (예: 다크 블루 + 골드, 파스텔 톤)",
  "editing_style": "편집 스타일 (예: 빠른 컷, 느린 전환, 줌인 활용)",
  "narration_style": "나레이션 스타일 (예: 남성 저음 차분, 여성 활기찬, 대화체)",
  "scene_duration_avg": "평균 씬 길이 초 단위 숫자",
  "text_overlay_style": "자막/텍스트 스타일 (예: 미니멀 하단, 큰 글씨 중앙)",
  "target_audience": "타겟 시청자층",
  "image_prompt_style": "이 스타일에 맞는 이미지 생성 프롬프트 키워드 (영어)"
}}

JSON만 출력하세요."""})

    api_url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.0-flash-001:generateContent?key={api_key}"
    payload = {"contents": [{"parts": parts}]}

    resp = requests.post(api_url, json=payload, timeout=60)
    resp.raise_for_status()
    data = resp.json()

    text = ""
    for candidate in data.get("candidates", []):
        for part in candidate.get("content", {}).get("parts", []):
            text += part.get("text", "")

    # JSON 파싱
    import json
    text = text.strip()
    if text.startswith("```"):
        text = text.split("\n", 1)[1].rsplit("```", 1)[0]

    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return {"raw_analysis": text}
