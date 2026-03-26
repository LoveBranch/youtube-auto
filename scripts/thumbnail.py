"""
YouTube 썸네일 자동 생성

MrBeast / Veritasium / Ali Abdaal 스타일 벤치마킹:
- 고대비, 채도 높은 색감 (채도 +20%, 대비 +10%)
- 깔끔한 배경 + 드라마틱 조명 (림라이트, 사이드라이트)
- 큰 글씨 3~5단어 (굵은 폰트, 검정 테두리)
- 호기심 유발 (Curiosity Gap)
- 비네팅 효과 (모서리 어둡게)

사용법:
    # 대본에서 자동 생성 (배경 이미지 + 텍스트 오버레이)
    py scripts/thumbnail.py <script.md> <output.jpg> [--lang ko] [--title "커스텀 제목"]

    # 기존 이미지에 텍스트 오버레이만
    py scripts/thumbnail.py <background.jpg> <output.jpg> --text "텍스트" [--aspect-ratio 16:9]
"""

import argparse
import base64
import json
import os
import textwrap
from pathlib import Path

import requests
from PIL import Image, ImageDraw, ImageEnhance, ImageFilter, ImageFont

SETTINGS_PATH = Path(__file__).resolve().parent.parent / "settings.json"
FONT_DIR = Path(__file__).resolve().parent.parent / "fonts"

SIZES = {
    "16:9": (1280, 720),
    "9:16": (1080, 1920),
    "1:1": (1080, 1080),
}

# 폰트 후보 (Windows)
FONT_PATHS = {
    "ko": ["C:/Windows/Fonts/malgunbd.ttf", "C:/Windows/Fonts/malgun.ttf"],
    "en": ["C:/Windows/Fonts/impact.ttf", "C:/Windows/Fonts/ariblk.ttf"],
    "ja": ["C:/Windows/Fonts/msgothic.ttc", "C:/Windows/Fonts/meiryo.ttc"],
    "zh": ["C:/Windows/Fonts/msyh.ttc", "C:/Windows/Fonts/simsun.ttc"],
}


def load_settings() -> dict:
    if SETTINGS_PATH.exists():
        return json.loads(SETTINGS_PATH.read_text(encoding="utf-8"))
    return {}


def _get_api_key() -> str:
    settings = load_settings()
    key = (
        settings.get("tts", {}).get("api_key", "")
        or os.environ.get("GEMINI_API_KEY", "")
    )
    if not key:
        raise ValueError("Gemini API 키 없음 (settings.json 또는 GEMINI_API_KEY)")
    return key


def _load_font(size: int, lang: str = "ko") -> ImageFont.FreeTypeFont:
    """사용 가능한 폰트를 찾아 로드한다."""
    # 프로젝트 fonts/ 폴더 우선
    if FONT_DIR.exists():
        for f in list(FONT_DIR.glob("*.ttf")) + list(FONT_DIR.glob("*.otf")):
            try:
                return ImageFont.truetype(str(f), size)
            except (OSError, IOError):
                continue

    # 시스템 폰트
    candidates = FONT_PATHS.get(lang, []) + FONT_PATHS.get("en", [])
    for path in candidates:
        try:
            return ImageFont.truetype(path, size)
        except (OSError, IOError):
            continue

    return ImageFont.load_default()


def _extract_title_from_script(script_text: str) -> str:
    """대본에서 제목(# 헤딩)을 추출한다."""
    for line in script_text.splitlines():
        line = line.strip()
        if line.startswith("# "):
            return line[2:].strip()
    for line in script_text.splitlines():
        line = line.strip()
        if line and not line.startswith("#"):
            return line[:40]
    return "YouTube Video"


# ──────────────────────────────────────────────
# 1단계: 썸네일 배경 이미지 프롬프트 생성
# ──────────────────────────────────────────────

def _generate_thumbnail_prompt(script_text: str, title: str, api_key: str, lang: str = "ko") -> str:
    """Gemini로 썸네일 이미지 프롬프트를 생성한다 (MrBeast 스타일)."""
    system = f"""You are a world-class thumbnail image director.

Read the script below carefully. Identify the CORE MESSAGE — the single most important idea the entire video is about.
Then create ONE vivid, dynamic image prompt that INSTANTLY communicates that core message to a viewer who has never seen the video.

=== YOUR MISSION ===
The thumbnail image alone must make someone understand WHAT this video is about.
A viewer should look at the image and immediately think: "Oh, this is about [topic]."

=== HOW TO DO THIS ===
1. FIND THE CORE: What is the ONE thing this video is really about? Not a side topic, not the intro — the HEART of the content.
2. MAKE IT VIVID: Turn that core idea into a DYNAMIC, ACTION-FILLED scene. Show movement, energy, life.
   - BAD: a person standing still looking at a screen (boring, static, generic)
   - GOOD: a person's morning routine being orchestrated by floating holographic AI panels — coffee pouring itself, calendar rearranging in mid-air, autonomous car visible through the window
3. MAKE IT SPECIFIC: The scene must be UNIQUE to this video's topic. Generic tech imagery is FORBIDDEN.
4. MAKE THE TOPIC OBVIOUS: Someone who sees ONLY this image (no title, no text) should be able to guess the video topic within 3 seconds.

=== MANDATORY HUMAN SUBJECT RULES ===
- The image MUST include a person shown from a SIDE PROFILE or 3/4 PROFILE angle (NOT facing camera directly)
- The person must occupy approximately HALF (50%) of the frame — large, dominant presence
- DYNAMIC EXPRESSION: the person's face must show strong emotion — awe, determination, excitement, focus, surprise
- ACTIVE POSE: the person must be IN ACTION — reaching, gesturing, walking, interacting with something. NEVER just standing still
- The person should be interacting with the environment or objects related to the topic

=== IMAGE QUALITY ===
- Photorealistic, cinematic, shot on ARRI Alexa with 35mm anamorphic lens
- Rich, saturated colors with complementary color contrast (blue/orange, teal/amber)
- Dramatic lighting: rim light + warm practical lights + volumetric atmosphere
- Shallow depth of field, hyper-detailed textures
- The scene should feel ALIVE — motion, energy, things happening simultaneously

=== CRITICAL RULES ===
- NO text, letters, numbers, words, watermarks, logos, UI elements
- NO abstract art, NO data visualizations, NO generic tech backgrounds, NO silhouettes
- ONLY concrete, real-world scenes with real people and real objects
- Leave the BOTTOM 30% slightly darker/simpler for text overlay
- Aspect ratio: 16:9 landscape

=== OUTPUT ===
Return ONLY the image prompt (100-150 words). No JSON, no quotes, no explanation.

Script language: {lang}
Video title: {title}"""

    # 대본 전체를 더 많이 보내서 인상적인 장면을 찾게 함
    script_preview = script_text[:3000]

    resp = requests.post(
        f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent?key={api_key}",
        json={
            "contents": [{"parts": [{"text": f"{system}\n\n--- SCRIPT EXCERPT ---\n{script_preview}"}]}],
            "generationConfig": {"temperature": 0.8},
        },
        timeout=30,
    )
    resp.raise_for_status()
    data = resp.json()
    prompt = data["candidates"][0]["content"]["parts"][0]["text"].strip()
    if prompt.startswith('"') and prompt.endswith('"'):
        prompt = prompt[1:-1]
    return prompt


# ──────────────────────────────────────────────
# 2단계: Imagen으로 배경 이미지 생성
# ──────────────────────────────────────────────

def _generate_image(prompt: str, api_key: str, output_path: Path) -> None:
    """Imagen API로 썸네일 배경 이미지를 생성한다."""
    resp = requests.post(
        f"https://generativelanguage.googleapis.com/v1beta/models/imagen-4.0-fast-generate-001:predict?key={api_key}",
        json={
            "instances": [{"prompt": prompt}],
            "parameters": {
                "sampleCount": 1,
                "aspectRatio": "16:9",
            },
        },
        timeout=90,
    )
    resp.raise_for_status()
    data = resp.json()

    predictions = data.get("predictions", [])
    if not predictions:
        raise ValueError(f"Imagen 이미지 생성 실패: {data}")

    img_b64 = predictions[0].get("bytesBase64Encoded", "")
    if not img_b64:
        raise ValueError("이미지 데이터 없음")

    output_path.write_bytes(base64.b64decode(img_b64))


# ──────────────────────────────────────────────
# 3단계: 짧은 제목 생성
# ──────────────────────────────────────────────

def _make_short_title(title: str, lang: str, api_key: str) -> str:
    """Gemini로 긴 제목을 썸네일용 짧은 텍스트로 압축한다."""
    try:
        resp = requests.post(
            f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent?key={api_key}",
            json={
                "contents": [{"parts": [{"text": (
                    f"이 YouTube 영상 제목을 썸네일 텍스트로 바꿔줘.\n"
                    f"규칙:\n"
                    f"- 한국어: 4~8자 한 줄 텍스트 (예: AI가 바꾼 일상)\n"
                    f"- 영어: 2~4단어 한 줄 텍스트 (예: AI Changed Everything)\n"
                    f"- 깊고 본질적인 제목. 가벼운 후킹 금지\n"
                    f"- 쉼표, 마침표, 줄바꿈 넣지 마\n"
                    f"- 텍스트만 반환. 따옴표, 설명, 줄바꿈 없이 딱 한 줄만\n\n"
                    f"제목: {title}"
                )}]}],
                "generationConfig": {"temperature": 0.9},
            },
            timeout=15,
        )
        resp.raise_for_status()
        short = resp.json()["candidates"][0]["content"]["parts"][0]["text"].strip()
        short = short.strip('"\'')
        # 리터럴 \n을 실제 줄바꿈으로 변환
        short = short.replace("\\n", "\n")
        # 모든 줄을 합쳐서 1줄로 (오버레이에서 필요시 2줄 분리)
        parts = [p.strip() for p in short.split("\n") if p.strip()]
        short = " ".join(parts)
        # 끝에 쉼표 제거
        short = short.rstrip(",.")
        if 1 < len(short) <= 25:
            return short
    except Exception:
        pass

    # 폴백
    if lang == "ko" and len(title) > 6:
        return title[:6]
    elif len(title) > 20:
        return title[:20]
    return title


# ──────────────────────────────────────────────
# 4단계: 후처리 + 텍스트 오버레이
# ──────────────────────────────────────────────

def _postprocess_and_overlay(image_path: Path, text: str, output_path: Path,
                              lang: str = "ko", aspect_ratio: str = "16:9") -> None:
    """고품질 후처리 + 프로급 텍스트 오버레이 (MrBeast/Veritasium 스타일)."""
    target_w, target_h = SIZES.get(aspect_ratio, SIZES["16:9"])
    img = Image.open(image_path).convert("RGBA")
    img = img.resize((target_w, target_h), Image.LANCZOS)

    # ── 후처리 ──
    rgb = img.convert("RGB")
    rgb = ImageEnhance.Color(rgb).enhance(1.25)       # 채도 +25%
    rgb = ImageEnhance.Contrast(rgb).enhance(1.15)     # 대비 +15%
    rgb = ImageEnhance.Sharpness(rgb).enhance(1.1)     # 선명도 +10%
    img = rgb.convert("RGBA")

    # ── 가벼운 비네팅 (모서리만 살짝) ──
    vignette = Image.new("L", img.size, 0)
    draw_v = ImageDraw.Draw(vignette)
    cx, cy = img.size[0] // 2, img.size[1] // 2
    max_r = int((cx**2 + cy**2) ** 0.5)
    for i in range(max_r, 0, -1):
        brightness = int(255 * (i / max_r) ** 0.25)  # 0.4→0.25 더 자연스럽게
        draw_v.ellipse([cx - i, cy - i, cx + i, cy + i], fill=brightness)
    rgb_base = img.convert("RGB")
    rgb_base = Image.composite(rgb_base, Image.new("RGB", img.size, (0, 0, 0)), vignette)
    img = rgb_base.convert("RGBA")

    # ── 텍스트 준비 (1줄 우선, 넘치면 2줄까지) ──
    # 먼저 1줄로 시도
    lines = [text.replace("\n", " ")]

    # ── 폰트 크기: 썸네일 높이의 약 5/8 (2.5배 키움) ──
    target_text_height = int(target_h * 0.625)
    line_count = 1
    font_size = int(target_text_height / 1.1)
    font_size = min(font_size, 400)
    font_size = max(font_size, 80)

    # 1줄로 안 들어가면 2줄로 분리
    test_font = _load_font(font_size, lang)
    test_draw = ImageDraw.Draw(Image.new("RGBA", (1, 1)))
    bbox = test_draw.textbbox((0, 0), lines[0], font=test_font)
    if bbox[2] - bbox[0] > target_w * 0.85:
        # 2줄로 분리
        if "\n" in text:
            lines = [l.strip() for l in text.split("\n") if l.strip()][:2]
        else:
            mid = len(text) // 2
            # 가장 가까운 공백에서 자르기
            space_pos = text.rfind(" ", 0, mid + 3)
            if space_pos == -1:
                space_pos = mid
            lines = [text[:space_pos].strip(), text[space_pos:].strip()]
            lines = [l for l in lines if l][:2]
        line_count = len(lines)
        font_size = int(target_text_height / (line_count * 1.1))
        font_size = min(font_size, 400)
        font_size = max(font_size, 80)
    font = _load_font(font_size, lang)

    # ── 텍스트 레이어 (별도 RGBA) ──
    text_layer = Image.new("RGBA", img.size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(text_layer)

    # 각 줄 크기 계산
    line_spacing = int(font_size * 1.15)
    total_text_h = line_spacing * line_count

    # ── 하단 배치: 이미지 하단 15% 여백 남기고 텍스트 배치 ──
    bottom_margin = int(target_h * 0.08)
    start_y = target_h - total_text_h - bottom_margin

    # ── 하단 그라데이션 (텍스트 가독성) ──
    gradient_layer = Image.new("RGBA", img.size, (0, 0, 0, 0))
    gradient_draw = ImageDraw.Draw(gradient_layer)
    grad_start = int(target_h * 0.40)
    for gy in range(grad_start, target_h):
        alpha = int(180 * ((gy - grad_start) / (target_h - grad_start)) ** 1.5)
        gradient_draw.line([(0, gy), (target_w, gy)], fill=(0, 0, 0, alpha))
    img = Image.alpha_composite(img, gradient_layer)

    # ── 텍스트 그리기 (글로우 + 두꺼운 테두리 + 본문) ──
    stroke_w = max(8, font_size // 8)

    for i, line in enumerate(lines):
        bbox = draw.textbbox((0, 0), line, font=font)
        line_w = bbox[2] - bbox[0]
        x = (target_w - line_w) // 2
        y = start_y + i * line_spacing

        # 1) 글로우 효과
        glow_layer = Image.new("RGBA", img.size, (0, 0, 0, 0))
        glow_draw = ImageDraw.Draw(glow_layer)
        glow_draw.text(
            (x, y), line, font=font,
            fill=(255, 255, 255, 80),
            stroke_width=stroke_w + 12,
            stroke_fill=(0, 0, 0, 100),
        )
        glow_layer = glow_layer.filter(ImageFilter.GaussianBlur(radius=12))
        text_layer = Image.alpha_composite(text_layer, glow_layer)

        # 2) 두꺼운 검정 테두리
        text_draw = ImageDraw.Draw(text_layer)
        text_draw.text(
            (x, y), line, font=font,
            fill="#FFFFFF",
            stroke_width=stroke_w,
            stroke_fill="#000000",
        )

    # ── 합성 ──
    img = Image.alpha_composite(img, text_layer)
    img = img.convert("RGB")
    img.save(output_path, "JPEG", quality=95)


# ──────────────────────────────────────────────
# 메인 함수
# ──────────────────────────────────────────────

def generate_thumbnail_from_script(
    script_path: str,
    output_path: str,
    lang: str = "ko",
    custom_title: str | None = None,
    aspect_ratio: str = "16:9",
) -> str:
    """대본 → 프롬프트 → 배경 이미지 → 텍스트 오버레이 → 완성 썸네일."""
    api_key = _get_api_key()
    script_text = Path(script_path).read_text(encoding="utf-8")
    out = Path(output_path)
    out.parent.mkdir(parents=True, exist_ok=True)

    # 1) 제목 추출
    full_title = custom_title or _extract_title_from_script(script_text)
    print(f"[썸네일] 제목: {full_title}")

    # 2) 프롬프트 생성
    print("[썸네일] 프롬프트 생성 중...")
    prompt = _generate_thumbnail_prompt(script_text, full_title, api_key, lang)
    print(f"[썸네일] 프롬프트: {prompt[:100]}...")

    prompt_path = out.parent / "thumbnail_prompt.txt"
    prompt_path.write_text(prompt, encoding="utf-8")

    # 3) 배경 이미지 생성
    raw_path = out.parent / "thumbnail_raw.jpg"
    print("[썸네일] 배경 이미지 생성 중...")
    _generate_image(prompt, api_key, raw_path)
    print(f"[썸네일] 배경 OK ({raw_path.stat().st_size // 1024}KB)")

    # 4) 짧은 제목 + 오버레이
    short_title = _make_short_title(full_title, lang, api_key)
    print(f"[썸네일] 텍스트: \"{short_title}\"")
    _postprocess_and_overlay(raw_path, short_title, out, lang, aspect_ratio)
    print(f"[썸네일] 완료: {out} ({out.stat().st_size // 1024}KB)")

    return str(out)


def generate_thumbnail(bg_path: str, output_path: str, text: str,
                       aspect_ratio: str = "16:9", **kwargs) -> str:
    """기존 이미지에 텍스트 오버레이만 (하위호환)."""
    out = Path(output_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    lang = kwargs.get("lang", "ko")
    _postprocess_and_overlay(Path(bg_path), text, out, lang, aspect_ratio)
    return str(out)


def main():
    parser = argparse.ArgumentParser(description="YouTube 썸네일 자동 생성")
    parser.add_argument("input", help="대본 파일(.md) 또는 배경 이미지(.jpg/.png)")
    parser.add_argument("output", help="출력 파일 (thumbnail.jpg)")
    parser.add_argument("--lang", default="ko", help="언어 (기본: ko)")
    parser.add_argument("--title", default=None, help="커스텀 제목")
    parser.add_argument("--text", default=None, help="직접 텍스트 지정 (이미지 입력 시)")
    parser.add_argument("--aspect-ratio", default="16:9", choices=["16:9", "9:16", "1:1"])
    args = parser.parse_args()

    input_path = Path(args.input)

    if input_path.suffix.lower() == ".md":
        # 대본 → 전체 자동 생성
        generate_thumbnail_from_script(
            str(input_path), args.output,
            lang=args.lang, custom_title=args.title,
            aspect_ratio=args.aspect_ratio,
        )
    else:
        # 이미지 → 텍스트 오버레이만
        text = args.text or args.title or "YouTube"
        generate_thumbnail(str(input_path), args.output, text,
                          aspect_ratio=args.aspect_ratio, lang=args.lang)


if __name__ == "__main__":
    main()
