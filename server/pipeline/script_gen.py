"""Gemini API로 대본을 생성한다."""

import requests
from server.config import settings

# 스타일 프리셋별 대본 작성 가이드
SCRIPT_STYLE_GUIDES: dict[str, dict] = {
    "cinematic_realism": {
        "narration": "gravitas-filled, measured pacing — like a prestige documentary narrator (think David Attenborough or Ken Burns)",
        "structure": "Open with a powerful real-world scene or quote. Build tension through facts and human stories. Resolve with insight.",
        "tone": "serious, authoritative, emotionally resonant",
    },
    "news_documentary": {
        "narration": "clear, neutral, journalistic — no opinion, just facts presented with confidence",
        "structure": "Lead with the key headline fact. Explain context. Present multiple angles. Close with implications.",
        "tone": "objective, informative, credible",
    },
    "epic_fantasy": {
        "narration": "mythic, grand, poetic — as if narrating an ancient legend or epic tale",
        "structure": "Open with an epic establishing moment. Build the world and stakes. Climax with revelation. End with wisdom.",
        "tone": "dramatic, sweeping, awe-inspiring",
    },
    "anime_manhwa": {
        "narration": "expressive, emotionally vivid — like an anime episode narrator with highs and lows",
        "structure": "Open with a personal emotional hook. Show character/concept growth. Include dramatic turning point. End with meaningful resolution.",
        "tone": "passionate, youthful, emotionally engaging",
    },
    "3d_render": {
        "narration": "clean, modern, slightly futuristic — like a tech product explainer",
        "structure": "Open with the core concept. Break down into clear numbered points. Use analogies. Close with practical application.",
        "tone": "smart, precise, forward-looking",
    },
    "minimalist_infographic": {
        "narration": "crisp, direct, punchy — one idea per sentence, no fluff",
        "structure": "Open with a surprising stat or question. Deliver 3-5 key insights clearly. End with one actionable takeaway.",
        "tone": "simple, accessible, confidence-building",
    },
    "dark_moody": {
        "narration": "slow, intense, psychological — like True Crime or thriller documentary",
        "structure": "Open with an unsettling question or disturbing fact. Layer in complexity and contradiction. End with an uncomfortable truth.",
        "tone": "brooding, provocative, thought-provoking",
    },
    "vintage_retro": {
        "narration": "warm, nostalgic, conversational — like a storyteller reminiscing",
        "structure": "Open with a vivid memory or historical moment. Take the viewer on a journey through time. End with reflection on what it means today.",
        "tone": "nostalgic, warm, humanistic",
    },
}


def generate_script(
    topic: str,
    language: str = "ko",
    duration_minutes: int = 10,
    style_profile: dict | None = None,
    source_content: str | None = None,
    style_preset: str | None = None,
) -> str:
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

    # style_preset 우선 적용, 없으면 style_profile 사용
    style_instruction = ""
    preset_guide = SCRIPT_STYLE_GUIDES.get(style_preset or "", {})
    if preset_guide:
        style_instruction = f"""
=== 스타일 지침 ({style_preset}) ===
- 나레이션 스타일: {preset_guide['narration']}
- 구성 방식: {preset_guide['structure']}
- 전반적 톤: {preset_guide['tone']}
이 스타일을 철저히 따라 대본을 작성하세요.
"""
    elif style_profile:
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

    url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.0-flash:generateContent?key={api_key}"
    payload = {
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {"temperature": 0.8, "maxOutputTokens": 8192},
    }

    import time
    for attempt in range(3):
        resp = requests.post(url, json=payload, timeout=60)
        if resp.status_code == 429:
            wait = 30 * (attempt + 1)
            print(f"[script_gen] 429 rate limit, {wait}s 후 재시도 ({attempt+1}/3)...")
            time.sleep(wait)
            continue
        resp.raise_for_status()
        break
    data = resp.json()

    text = ""
    for candidate in data.get("candidates", []):
        for part in candidate.get("content", {}).get("parts", []):
            text += part.get("text", "")

    return text.strip()
