"""
Gemini TTS를 사용한 대본 → 음성 변환 스크립트

사용법:
    py scripts/tts.py <script.md> <output.wav> [--voice VOICE] [--lang ko]
    py scripts/tts.py --list-voices

settings.json에서 API 키, 기본 음성 등을 자동으로 읽는다.
"""

import argparse
import base64
import json
import re
import sys
import wave
from pathlib import Path

import requests

SETTINGS_PATH = Path(__file__).resolve().parent.parent / "settings.json"


def load_settings() -> dict:
    """settings.json을 로드한다."""
    if SETTINGS_PATH.exists():
        return json.loads(SETTINGS_PATH.read_text(encoding="utf-8"))
    return {}


SETTINGS = load_settings()

GEMINI_TTS_MODEL = SETTINGS.get("tts", {}).get("model", "gemini-2.5-flash-preview-tts")
API_URL = f"https://generativelanguage.googleapis.com/v1beta/models/{GEMINI_TTS_MODEL}:generateContent"

VOICES = SETTINGS.get("tts", {}).get("voices", {
    "Kore": "여성 - 차분하고 부드러운 톤",
    "Aoede": "여성 - 밝고 경쾌한 톤",
    "Leda": "여성 - 따뜻하고 안정적인 톤",
    "Charon": "남성 - 깊고 안정적인 톤",
    "Fenrir": "남성 - 활기차고 에너지 넘치는 톤",
    "Puck": "남성 - 친근하고 유쾌한 톤",
    "Orus": "남성 - 중후하고 신뢰감 있는 톤",
    "Zephyr": "중성 - 자연스럽고 편안한 톤",
})

LANGUAGES = SETTINGS.get("language", {}).get("options", {
    "ko": {"name": "한국어", "default_voice": "Kore"},
    "en": {"name": "English", "default_voice": "Puck"},
    "ja": {"name": "日本語", "default_voice": "Aoede"},
})
DEFAULT_LANG = SETTINGS.get("language", {}).get("default", "ko")


def extract_narration(md_text: str) -> str:
    """마크다운 대본에서 나레이션 텍스트를 빠짐없이 추출한다.

    이전 버전의 버그: --- 를 YAML frontmatter 토글로 사용하여
    섹션 구분선 사이의 내용이 통째로 누락됨. 수정 완료.
    """
    lines = md_text.splitlines()
    narration_lines: list[str] = []
    prev_was_blank = False

    for stripped_raw in lines:
        stripped = stripped_raw.strip()

        # --- 는 단순 섹션 구분선으로 스킵
        if re.match(r"^[-=*]{3,}$", stripped):
            continue

        # 참고 자료 섹션 이후 중단
        if re.match(r"^##?\s*참고\s*자료", stripped):
            break

        # 헤딩 스킵
        if stripped.startswith("#"):
            continue

        # 메타 정보 라인 스킵 (- **키**: 값)
        if re.match(r"^-\s*\*\*.*\*\*\s*:", stripped):
            continue

        # 타임코드 패턴 스킵 (0:00 ~ 1:30)
        if re.match(r"^\(?\d+:\d+\s*~\s*\d+:\d+\)?$", stripped):
            continue

        # 빈 줄 → 문단 구분 (연속 빈 줄은 하나로)
        if stripped == "":
            if narration_lines and not prev_was_blank:
                prev_was_blank = True
            continue

        prev_was_blank = False

        # 블록인용 기호 제거
        if stripped.startswith(">"):
            stripped = stripped.lstrip("> ").strip()

        # 마크다운 서식 제거
        stripped = re.sub(r"\*{1,2}([^*]+)\*{1,2}", r"\1", stripped)

        # 리스트 마커 제거
        stripped = re.sub(r"^[-*]\s+", "", stripped)
        stripped = re.sub(r"^\d+\.\s+", "", stripped)

        if stripped:
            narration_lines.append(stripped)

    return "\n".join(narration_lines)


def call_gemini_tts(text: str, voice: str, language: str, api_key: str) -> tuple[bytes, int]:
    """Gemini TTS API를 호출하여 (오디오 바이트, 샘플레이트)를 반환한다."""
    payload = {
        "contents": [{"parts": [{"text": text}]}],
        "generationConfig": {
            "responseModalities": ["AUDIO"],
            "speechConfig": {
                "voiceConfig": {
                    "prebuiltVoiceConfig": {
                        "voiceName": voice,
                    }
                }
            },
        },
    }

    import time, re as _re
    for attempt in range(5):
        resp = requests.post(
            f"{API_URL}?key={api_key}",
            json=payload,
            headers={"Content-Type": "application/json"},
            timeout=600,
        )
        if resp.status_code == 429:
            retry_match = _re.search(r"retry in ([\d.]+)s", resp.text)
            wait = float(retry_match.group(1)) if retry_match else 60
            wait = min(wait + 5, 120)
            print(f"[TTS] 429 quota exceeded, {wait:.0f}초 후 재시도... (시도 {attempt+1}/5)", file=sys.stderr)
            time.sleep(wait)
            continue
        break

    if resp.status_code != 200:
        raise RuntimeError(f"TTS API 오류 ({resp.status_code}): {resp.text[:500]}")

    data = resp.json()
    if "error" in data:
        raise RuntimeError(f"TTS API 오류: {data['error']['message']}")

    part = data["candidates"][0]["content"]["parts"][0]
    inline_data = part["inlineData"]
    mime_type = inline_data["mimeType"]
    audio_bytes = base64.b64decode(inline_data["data"])

    rate_match = re.search(r"rate=(\d+)", mime_type)
    sample_rate = int(rate_match.group(1)) if rate_match else 24000

    return audio_bytes, sample_rate


def save_audio(audio_bytes: bytes, sample_rate: int, output_path: str) -> None:
    """오디오를 WAV 파일로 저장한다."""
    with wave.open(output_path, "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(sample_rate)
        wf.writeframes(audio_bytes)


def resolve_voice(lang: str, settings: dict | None = None) -> str:
    """언어별 기본 음성을 반환한다."""
    if settings is not None:
        lang_options = settings.get("language", {}).get("options", {})
        lang_info = lang_options.get(lang, {})
        if lang_info.get("default_voice"):
            return lang_info["default_voice"]
    lang_info = LANGUAGES.get(lang, {})
    return lang_info.get("default_voice", "Kore")


def main() -> None:
    default_api_key = SETTINGS.get("tts", {}).get("api_key", "")

    parser = argparse.ArgumentParser(description="Gemini TTS로 대본 → 음성 변환")
    parser.add_argument("script", nargs="?", help="마크다운 대본 파일")
    parser.add_argument("output", nargs="?", help="출력 오디오 파일 (.wav)")
    parser.add_argument("--api-key", default=default_api_key, help="Google AI Studio API 키 (settings.json에서 자동 로드)")
    parser.add_argument("--voice", default=None, help="목소리 (미지정 시 언어별 기본값)")
    parser.add_argument("--lang", default=DEFAULT_LANG, choices=list(LANGUAGES.keys()), help=f"언어 (기본: {DEFAULT_LANG})")
    parser.add_argument("--list-voices", action="store_true", help="사용 가능한 목소리 목록")
    args = parser.parse_args()

    if args.list_voices:
        print("사용 가능한 목소리:")
        for name, desc in VOICES.items():
            print(f"  {name:10s} {desc}")
        print("\n언어별 기본 목소리:")
        for code, info in LANGUAGES.items():
            print(f"  {code}: {info['name']} → {info['default_voice']}")
        return

    if not args.script or not args.output:
        parser.error("script와 output은 필수입니다 (--list-voices 제외)")

    if not args.api_key:
        parser.error("--api-key 필요 (또는 settings.json에 tts.api_key 설정)")

    voice = args.voice or resolve_voice(args.lang)

    script_path = Path(args.script)
    if not script_path.exists():
        print(f"오류: {script_path} 없음", file=sys.stderr)
        sys.exit(1)

    md_text = script_path.read_text(encoding="utf-8")
    narration = extract_narration(md_text)

    if not narration.strip():
        print("오류: 나레이션 텍스트 추출 실패", file=sys.stderr)
        sys.exit(1)

    lang_name = LANGUAGES.get(args.lang, {}).get("name", args.lang)
    print(f"언어: {lang_name}")
    print(f"목소리: {voice} ({VOICES.get(voice, '?')})")
    print(f"추출된 텍스트: {len(narration)}자")
    print("음성 생성 중...")

    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    audio_bytes, sample_rate = call_gemini_tts(narration, voice, args.lang, args.api_key)
    print(f"샘플레이트: {sample_rate}Hz")

    save_audio(audio_bytes, sample_rate, str(output_path))
    print(f"완료: {output_path} ({len(audio_bytes) / 1024:.0f}KB)")


if __name__ == "__main__":
    main()
