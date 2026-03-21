"""
YouTube 썸네일 자동 생성 스크립트

Whisk 배경 이미지 위에 굵은 한글 텍스트 + 그림자/외곽선을 합성한다.

사용법:
    py scripts/thumbnail.py <background.jpg> <output.jpg> --text "텍스트" [--aspect-ratio 16:9]
    py scripts/thumbnail.py <background.jpg> <output.jpg> --text "텍스트" --aspect-ratio 9:16

출력:
    텍스트가 합성된 썸네일 이미지 (JPG)
"""

import argparse
import textwrap
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont, ImageFilter


# 폰트 경로 (Windows)
FONT_PATHS = [
    "C:/Windows/Fonts/malgunbd.ttf",      # 맑은 고딕 Bold
    "C:/Windows/Fonts/NotoSansKR-VF.ttf",  # Noto Sans KR
    "C:/Windows/Fonts/malgun.ttf",          # 맑은 고딕
]

SIZES = {
    "16:9": (1920, 1080),
    "9:16": (1080, 1920),
    "1:1":  (1080, 1080),
}


def _load_font(size: int) -> ImageFont.FreeTypeFont:
    for path in FONT_PATHS:
        try:
            return ImageFont.truetype(path, size)
        except (OSError, IOError):
            continue
    return ImageFont.load_default()


def _wrap_text(text: str, aspect_ratio: str) -> str:
    """화면 비율에 따라 텍스트 줄바꿈."""
    if aspect_ratio == "9:16":
        max_chars = 6   # 세로 화면: 한 줄 최대 6글자
    elif aspect_ratio == "1:1":
        max_chars = 8
    else:
        max_chars = 10  # 16:9: 한 줄 최대 10글자
    return "\n".join(textwrap.wrap(text, width=max_chars))


def _draw_text_with_outline(draw: ImageDraw.Draw, position: tuple, text: str,
                            font: ImageFont.FreeTypeFont, fill: str,
                            outline_color: str, outline_width: int):
    """텍스트에 외곽선(stroke) 효과."""
    x, y = position
    # 외곽선
    for dx in range(-outline_width, outline_width + 1):
        for dy in range(-outline_width, outline_width + 1):
            if dx == 0 and dy == 0:
                continue
            draw.text((x + dx, y + dy), text, font=font, fill=outline_color, anchor="mm")
    # 본 텍스트
    draw.text(position, text, font=font, fill=fill, anchor="mm")


def generate_thumbnail(bg_path: str, output_path: str, text: str,
                       aspect_ratio: str = "16:9",
                       font_size: int = 0,
                       text_color: str = "#FFFFFF",
                       gradient: bool = True) -> str:
    """배경 이미지 위에 텍스트를 합성하여 썸네일 생성."""

    target_w, target_h = SIZES.get(aspect_ratio, SIZES["16:9"])

    # 1. 배경 이미지 로드 & 리사이즈
    bg = Image.open(bg_path).convert("RGB")
    bg = bg.resize((target_w, target_h), Image.LANCZOS)

    # 2. 하단 그라데이션 오버레이 (텍스트 가독성)
    if gradient:
        gradient_overlay = Image.new("RGBA", (target_w, target_h), (0, 0, 0, 0))
        gradient_draw = ImageDraw.Draw(gradient_overlay)
        gradient_start = int(target_h * 0.4)
        for y in range(gradient_start, target_h):
            alpha = int(200 * (y - gradient_start) / (target_h - gradient_start))
            gradient_draw.line([(0, y), (target_w, y)], fill=(0, 0, 0, alpha))
        bg = Image.alpha_composite(bg.convert("RGBA"), gradient_overlay).convert("RGB")

    # 3. 텍스트 줄바꿈
    wrapped = _wrap_text(text, aspect_ratio)
    lines = wrapped.split("\n")

    # 4. 폰트 크기 자동 계산
    if font_size == 0:
        if aspect_ratio == "9:16":
            font_size = target_w // 7  # 세로: 더 큰 비율
        else:
            font_size = target_h // 8  # 가로: 높이 기준
    font = _load_font(font_size)

    # 5. 텍스트 위치 (하단 중앙)
    draw = ImageDraw.Draw(bg)
    line_height = font_size * 1.3
    total_text_h = line_height * len(lines)

    if aspect_ratio == "9:16":
        text_y_center = target_h * 0.7  # 세로: 70% 위치
    else:
        text_y_center = target_h * 0.72  # 가로: 72% 위치

    start_y = text_y_center - total_text_h / 2

    # 6. 각 줄 렌더링 (외곽선 + 본 텍스트)
    outline_width = max(3, font_size // 20)
    for i, line in enumerate(lines):
        y = start_y + i * line_height + line_height / 2
        _draw_text_with_outline(
            draw, (target_w // 2, y), line, font,
            fill=text_color,
            outline_color="#000000",
            outline_width=outline_width
        )

    # 7. 저장
    bg.save(output_path, "JPEG", quality=95)
    return output_path


def main():
    parser = argparse.ArgumentParser(description="YouTube 썸네일 생성")
    parser.add_argument("background", help="배경 이미지 경로")
    parser.add_argument("output", help="출력 파일 경로")
    parser.add_argument("--text", required=True, help="썸네일 텍스트")
    parser.add_argument("--aspect-ratio", default="16:9", choices=["16:9", "9:16", "1:1"])
    parser.add_argument("--font-size", type=int, default=0, help="폰트 크기 (0=자동)")
    parser.add_argument("--no-gradient", action="store_true", help="그라데이션 끄기")
    args = parser.parse_args()

    result = generate_thumbnail(
        args.background, args.output, args.text,
        aspect_ratio=args.aspect_ratio,
        font_size=args.font_size,
        gradient=not args.no_gradient,
    )
    print(f"썸네일 생성 완료: {result}")


if __name__ == "__main__":
    main()
