"""채널 썸네일 템플릿 시스템 — 시리즈 전체 일관된 스타일 유지."""

from pathlib import Path
from PIL import Image, ImageDraw, ImageFont
import requests
import io
import textwrap


def hex_to_rgb(hex_color: str) -> tuple:
    hex_color = hex_color.lstrip("#")
    return tuple(int(hex_color[i:i+2], 16) for i in (0, 2, 4))


def download_image(url: str) -> Image.Image | None:
    try:
        resp = requests.get(url, timeout=10)
        return Image.open(io.BytesIO(resp.content)).convert("RGB")
    except Exception:
        return None


def render_thumbnail(
    title: str,
    background_image_path: str | None,
    template: dict,
    output_path: str,
    width: int = 1280,
    height: int = 720,
) -> str:
    """
    채널 썸네일 템플릿으로 일관된 썸네일 생성.
    template: { background_color, text_color, accent_color, text_position,
                font_size, has_overlay, overlay_opacity, style }
    """
    bg_color = hex_to_rgb(template.get("background_color", "#1a1a2e"))
    text_color = hex_to_rgb(template.get("text_color", "#ffffff"))
    accent_color = hex_to_rgb(template.get("accent_color", "#e94560"))
    overlay_opacity = template.get("overlay_opacity", 0.6)
    text_position = template.get("text_position", "bottom-left")
    font_size_preset = template.get("font_size", "large")

    # 캔버스 생성
    canvas = Image.new("RGB", (width, height), bg_color)

    # 배경 이미지 합성
    if background_image_path and Path(background_image_path).exists():
        try:
            bg_img = Image.open(background_image_path).convert("RGB")
            bg_img = bg_img.resize((width, height), Image.LANCZOS)
            canvas.paste(bg_img)
        except Exception:
            pass

    # 어두운 오버레이
    if template.get("has_overlay", True):
        overlay = Image.new("RGBA", (width, height), (0, 0, 0, int(255 * overlay_opacity)))
        canvas = canvas.convert("RGBA")
        canvas = Image.alpha_composite(canvas, overlay).convert("RGB")

    draw = ImageDraw.Draw(canvas)

    # 폰트 크기
    size_map = {"small": 48, "medium": 60, "large": 72, "xlarge": 88}
    font_size = size_map.get(font_size_preset, 72)

    # 폰트 로드 (시스템 폰트 fallback)
    font = None
    font_paths = [
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
        "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
        "/System/Library/Fonts/Helvetica.ttc",
        "C:/Windows/Fonts/arialbd.ttf",
    ]
    for fp in font_paths:
        if Path(fp).exists():
            try:
                font = ImageFont.truetype(fp, font_size)
                break
            except Exception:
                continue
    if font is None:
        font = ImageFont.load_default()

    # 텍스트 줄바꿈 (최대 20자)
    lines = textwrap.wrap(title, width=20)
    line_height = font_size + 12
    total_text_height = len(lines) * line_height

    # 텍스트 위치 계산
    padding = 60
    if text_position == "bottom-left":
        text_x = padding
        text_y = height - total_text_height - padding
    elif text_position == "center":
        text_x = None  # 중앙 정렬
        text_y = (height - total_text_height) // 2
    elif text_position == "top-left":
        text_x = padding
        text_y = padding
    else:
        text_x = padding
        text_y = height - total_text_height - padding

    # 액센트 바 (하단 좌측 정렬일 때)
    if text_position == "bottom-left":
        bar_y = text_y - 16
        draw.rectangle([padding, bar_y, padding + 80, bar_y + 6], fill=accent_color)

    # 텍스트 렌더링
    for i, line in enumerate(lines):
        y = text_y + i * line_height
        if text_x is None:
            # 중앙 정렬
            bbox = draw.textbbox((0, 0), line, font=font)
            lw = bbox[2] - bbox[0]
            x = (width - lw) // 2
        else:
            x = text_x

        # 텍스트 그림자
        draw.text((x + 3, y + 3), line, font=font, fill=(0, 0, 0, 180) if hasattr(Image, 'RGBA') else (0, 0, 0))
        draw.text((x, y), line, font=font, fill=text_color)

    # 저장
    canvas.save(output_path, "JPEG", quality=90)
    return output_path
