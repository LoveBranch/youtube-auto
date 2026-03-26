"""
Gemini API 기반 SRT 자막 생성 스크립트

오디오 파일을 Gemini에 보내서 음성 인식 + 타임스탬프 자막을 생성한다.
Whisper보다 100배 빠르고 무료 티어로 사용 가능.

사용법:
    py scripts/gemini_srt.py <audio_file> <output.srt> [--max-chars 15] [--lang ko]
"""

import argparse
import base64
import json
import re
import sys
from pathlib import Path

import requests

SETTINGS_PATH = Path(__file__).resolve().parent.parent / "settings.json"


def load_settings() -> dict:
    if SETTINGS_PATH.exists():
        return json.loads(SETTINGS_PATH.read_text(encoding="utf-8"))
    return {}


def format_timestamp(seconds: float) -> str:
    hrs = int(seconds // 3600)
    mins = int((seconds % 3600) // 60)
    secs = int(seconds % 60)
    millis = int((seconds - int(seconds)) * 1000)
    return f"{hrs:02d}:{mins:02d}:{secs:02d},{millis:03d}"


def generate_srt_with_gemini(audio_path: str, max_chars: int, lang: str, api_key: str) -> str:
    """Gemini API로 오디오를 분석하여 SRT 자막을 생성한다."""

    audio_bytes = Path(audio_path).read_bytes()
    audio_b64 = base64.b64encode(audio_bytes).decode()
    size_mb = len(audio_bytes) / (1024 * 1024)
    print(f"오디오: {size_mb:.1f}MB")

    # 확장자로 MIME 타입 결정
    ext = Path(audio_path).suffix.lower()
    mime_map = {".wav": "audio/wav", ".mp3": "audio/mp3", ".m4a": "audio/mp4", ".ogg": "audio/ogg"}
    mime_type = mime_map.get(ext, "audio/wav")

    lang_names = {"ko": "Korean", "en": "English", "ja": "Japanese", "zh": "Chinese", "es": "Spanish"}
    lang_name = lang_names.get(lang, lang)

    prompt = f"""Listen to this audio and transcribe it into SRT subtitle format.

Rules:
- Language: {lang_name}
- Each subtitle line must be {max_chars} characters or less
- Use accurate timestamps based on the actual speech timing
- Split long sentences at natural pauses, commas, or phrase boundaries
- Every spoken word must be included - do not skip any content
- Output ONLY the SRT content, nothing else

SRT format example:
1
00:00:01,000 --> 00:00:03,500
첫 번째 자막 내용

2
00:00:03,500 --> 00:00:06,200
두 번째 자막 내용"""

    import time as _time
    print("Gemini 음성 인식 중...")
    payload = {
        "contents": [{
            "parts": [
                {
                    "inlineData": {
                        "mimeType": mime_type,
                        "data": audio_b64,
                    }
                },
                {"text": prompt},
            ]
        }],
        "generationConfig": {
            "temperature": 0.1,
        },
    }
    for attempt in range(3):
        try:
            resp = requests.post(
                f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent?key={api_key}",
                json=payload,
                timeout=180,
            )
        except requests.exceptions.Timeout:
            print(f"[gemini_srt] 타임아웃 ({attempt+1}/3), 재시도...")
            _time.sleep(10)
            continue
        if resp.status_code == 429:
            wait = 30 * (attempt + 1)
            print(f"[gemini_srt] 429 rate limit, {wait}s 후 재시도 ({attempt+1}/3)...")
            _time.sleep(wait)
            continue
        resp.raise_for_status()
        break
    data = resp.json()

    if "candidates" not in data:
        raise ValueError(f"Gemini SRT 응답에 candidates 없음. 전체 응답: {data}")

    text = data["candidates"][0]["content"]["parts"][0]["text"]

    # 코드 블록 제거
    text = re.sub(r"```srt\s*\n?", "", text)
    text = re.sub(r"```\s*$", "", text)
    text = text.strip()

    # SRT 유효성 검증
    blocks = re.split(r"\n\s*\n", text.strip())
    valid_count = 0
    for block in blocks:
        lines = block.strip().splitlines()
        if len(lines) >= 3 and re.match(r"\d+", lines[0]) and "-->" in lines[1]:
            valid_count += 1

    print(f"생성된 자막: {valid_count}개")
    return text + "\n"


def main() -> None:
    parser = argparse.ArgumentParser(description="Gemini 기반 SRT 자막 생성")
    parser.add_argument("audio", help="오디오 파일 (WAV/MP3)")
    parser.add_argument("output", help="출력 SRT 파일")
    parser.add_argument("--max-chars", type=int, default=15, help="자막 한 줄 최대 글자 수 (기본: 15)")
    parser.add_argument("--lang", default="ko", help="언어 코드 (기본: ko)")
    args = parser.parse_args()

    audio_path = Path(args.audio)
    if not audio_path.exists():
        print(f"오류: {audio_path} 없음", file=sys.stderr)
        sys.exit(1)

    settings = load_settings()
    api_key = settings.get("tts", {}).get("api_key", "")
    if not api_key:
        print("오류: settings.json에 tts.api_key가 없음", file=sys.stderr)
        sys.exit(1)

    srt_content = generate_srt_with_gemini(str(audio_path), args.max_chars, args.lang, api_key)

    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(srt_content, encoding="utf-8")

    print(f"완료: {output_path}")


if __name__ == "__main__":
    main()
