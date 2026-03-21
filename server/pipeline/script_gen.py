"""Gemini API로 대본을 생성한다."""

import requests
from server.config import settings


def generate_script(topic: str, language: str = "ko", duration_minutes: int = 10, style_profile: dict | None = None, source_content: str | None = None) -> str:
    """주제와 설정으로 영상 대본을 생성한다."""
    api_key = settings.get("tts", {}).get("api_key", "")
    if not api_key:
        raise ValueError("Gemini API 키가 설정되지 않았습니다.")

    lang_names = {"ko": "한국어", "en": "English", "ja": "日本語", "zh": "中文", "es": "Español"}
    lang_name = lang_names.get(language, language)

    # 분량 계산 (1분 ≈ 250자 한국어 / 150 words 영어)
    if language == "ko":
        char_target = duration_minutes * 250
        length_guide = f"약 {char_target}자 분량"
    else:
        word_target = duration_minutes * 150
        length_guide = f"약 {word_target} words"

    source_instruction = ""
    if source_content:
        preview = source_content[:2000]
        source_instruction = f"\n참고 자료 (이 내용을 바탕으로 대본을 작성하세요):\n{preview}\n"

    style_instruction = ""
    if style_profile:
        style_instruction = f"""
참고할 스타일:
- 톤: {style_profile.get('tone', '교육적')}
- 비주얼 분위기: {style_profile.get('visual_mood', '시네마틱')}
- 편집 스타일: {style_profile.get('editing_style', '보통 속도')}
- 나레이션 스타일: {style_profile.get('narration_style', '차분한 설명')}
이 스타일에 맞춰 대본을 작성하세요.
"""

    prompt = f"""유튜브 영상 대본을 작성하세요.

주제: {topic}
언어: {lang_name}
분량: {length_guide} ({duration_minutes}분 영상)
{source_instruction}{style_instruction}
형식:
- 마크다운 형식으로 작성
- # 제목으로 시작
- ## 소제목으로 섹션 구분
- 강한 훅으로 시작 (첫 3초에 시청자 주의 끌기)
- 핵심 메시지 전달 후 CTA로 마무리
- 숫자/통계는 구체적으로 포함
- 대화체, 쉬운 표현 사용 (TTS로 읽을 수 있도록)
- 괄호, 기호 등 TTS가 읽기 어려운 표현 피하기

대본만 출력하세요. 설명이나 주석은 넣지 마세요."""

    url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent?key={api_key}"
    payload = {
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {"temperature": 0.8, "maxOutputTokens": 8192},
    }

    resp = requests.post(url, json=payload, timeout=60)
    resp.raise_for_status()
    data = resp.json()

    text = ""
    for candidate in data.get("candidates", []):
        for part in candidate.get("content", {}).get("parts", []):
            text += part.get("text", "")

    return text.strip()
