"""
클라우드용 비주얼 파이프라인 (Railway 배포 전용)

whisk_visual.py의 씬 추출/프롬프트 생성 + 선택 가능한 이미지 생성 백엔드.
--image-provider gemini  → Gemini 2.0 Flash (무료)
--image-provider grok    → xAI Grok Aurora (유료, 고품질)

사용법:
    python scripts/cloud_visual.py <script.md> <subtitle.srt> <output_dir> [--lang ko] [--aspect-ratio 16:9] [--image-provider gemini]
"""

import argparse
import json
import sys
from pathlib import Path

# 같은 scripts 폴더 내 모듈 import
sys.path.insert(0, str(Path(__file__).resolve().parent))

from whisk_visual import extract_sections, generate_image_prompts
from grok_visual import image_to_clip, load_settings

SETTINGS = load_settings()


def generate_cloud_visuals(
    script_path: str,
    srt_path: str,
    output_dir: str,
    lang: str = "ko",
    aspect_ratio: str = "16:9",
    image_provider: str = "gemini",
) -> None:
    """대본 → 씬 추출 → 프롬프트 생성 → 이미지 → Ken Burns 영상 클립."""
    script_text = Path(script_path).read_text(encoding="utf-8")
    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)

    api_key_gemini = SETTINGS.get("tts", {}).get("api_key", "")
    api_key_xai = SETTINGS.get("xai", {}).get("api_key", "")

    if image_provider == "grok" and not api_key_xai:
        print("오류: settings.json에 xai.api_key가 없음", file=sys.stderr)
        sys.exit(1)

    print(f"이미지 생성 백엔드: {image_provider}")

    # 1) 씬 추출
    scenes = extract_sections(script_text)
    print(f"씬 {len(scenes)}개 추출됨")

    # 2) 이미지 프롬프트 생성 (Gemini)
    scenes = generate_image_prompts(scenes, lang, aspect_ratio, api_key_gemini)
    print("이미지 프롬프트 생성 완료")

    # 3) 씬별 이미지 + 영상 클립 생성
    for scene in scenes:
        idx = scene["index"]
        image_file = out / f"scene_{idx:03d}.jpg"
        video_file = out / f"scene_{idx:03d}.mp4"

        if video_file.exists():
            print(f"  [스킵] scene_{idx:03d}.mp4 이미 존재")
            continue

        # 이미지 생성
        if not image_file.exists():
            print(f"  [{idx}/{len(scenes)}] 이미지 생성 중: {scene.get('title', '')}")
            try:
                if image_provider == "grok":
                    from grok_visual import generate_image_grok
                    generate_image_grok(scene["image_prompt"], api_key_xai, str(image_file))
                else:
                    from gemini_image import generate_image_gemini
                    generate_image_gemini(scene["image_prompt"], api_key_gemini, str(image_file))
            except Exception as e:
                print(f"  이미지 생성 실패 (scene {idx}): {e}", file=sys.stderr)
                continue

        # Ken Burns 영상 클립
        duration = scene.get("duration", 4.0)
        print(f"  [{idx}/{len(scenes)}] 영상 클립 생성 중...")
        try:
            image_to_clip(str(image_file), str(video_file), duration=duration, aspect_ratio=aspect_ratio)
        except Exception as e:
            print(f"  영상 클립 실패 (scene {idx}): {e}", file=sys.stderr)

    # scenes.json 저장
    (out / "scenes.json").write_text(
        json.dumps(scenes, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(f"완료: {out}")


def main() -> None:
    parser = argparse.ArgumentParser(description="클라우드용 비주얼 파이프라인")
    parser.add_argument("script", help="대본 파일 (script.md)")
    parser.add_argument("srt", help="자막 파일 (subtitle.srt)")
    parser.add_argument("output_dir", help="출력 디렉토리")
    parser.add_argument("--lang", default="ko", help="언어 코드 (기본: ko)")
    parser.add_argument("--aspect-ratio", default="16:9", help="화면 비율 (기본: 16:9)")
    parser.add_argument("--image-provider", default="gemini", choices=["gemini", "grok"],
                        help="이미지 생성 백엔드 (기본: gemini)")
    args = parser.parse_args()

    generate_cloud_visuals(
        args.script,
        args.srt,
        args.output_dir,
        lang=args.lang,
        aspect_ratio=args.aspect_ratio,
        image_provider=args.image_provider,
    )


if __name__ == "__main__":
    main()
