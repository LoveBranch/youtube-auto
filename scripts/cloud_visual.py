"""
클라우드용 비주얼 파이프라인 (Railway 배포 전용)

whisk_visual.py의 씬 추출/프롬프트 생성 + 선택 가능한 이미지 생성 백엔드.
--image-provider gemini  → Gemini 2.0 Flash (무료)
--image-provider grok    → xAI Grok Aurora (유료, 고품질)

사용법:
    python scripts/cloud_visual.py <script.md> <subtitle.srt> <output_dir> [--lang ko] [--aspect-ratio 16:9] [--image-provider gemini]
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

# 같은 scripts 폴더 내 모듈 import
sys.path.insert(0, str(Path(__file__).resolve().parent))

from whisk_visual import extract_sections, generate_image_prompts
from grok_visual import image_to_clip, load_settings

SETTINGS = load_settings()


def _get_srt_duration(srt_text: str) -> float:
    """SRT 파일에서 마지막 자막의 종료 시간(초)을 반환한다."""
    import re
    last_end = 0.0
    for m in re.finditer(r'(\d{2}):(\d{2}):(\d{2})[,.](\d{3})', srt_text):
        t = int(m.group(1)) * 3600 + int(m.group(2)) * 60 + int(m.group(3)) + int(m.group(4)) / 1000
        if t > last_end:
            last_end = t
    return last_end


def generate_cloud_visuals(
    script_path: str,
    srt_path: str,
    output_dir: str,
    lang: str = "ko",
    aspect_ratio: str = "16:9",
    image_provider: str = "gemini",
    style_preset: str | None = None,
) -> None:
    """대본 → 씬 추출 → 프롬프트 생성 → 이미지 → Ken Burns 영상 클립."""
    script_text = Path(script_path).read_text(encoding="utf-8")
    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)

    api_key_gemini = (
        SETTINGS.get("tts", {}).get("api_key", "")
        or SETTINGS.get("gemini", {}).get("api_key", "")
        or os.environ.get("GEMINI_API_KEY", "")
    )
    api_key_xai = SETTINGS.get("xai", {}).get("api_key", "") or os.environ.get("XAI_API_KEY", "")

    if image_provider == "grok" and not api_key_xai:
        print("오류: settings.json에 xai.api_key가 없음", file=sys.stderr)
        sys.exit(1)

    print(f"이미지 생성 백엔드: {image_provider}, 스타일: {style_preset or '기본'}")

    # 1) 씬 추출
    scenes = extract_sections(script_text)
    print(f"씬 {len(scenes)}개 추출됨")

    # 1.5) SRT에서 오디오 총 길이 → 씬별 duration 균등 분배
    srt_text = Path(srt_path).read_text(encoding="utf-8")
    total_audio_dur = _get_srt_duration(srt_text)
    if total_audio_dur > 0 and scenes:
        per_scene = total_audio_dur / len(scenes)
        for s in scenes:
            s["duration"] = round(per_scene, 2)
        print(f"오디오 {total_audio_dur:.1f}s → 씬당 {per_scene:.1f}s")
    else:
        print("SRT 기반 duration 계산 실패, 기본 4초 사용")

    # 2) 이미지 프롬프트 생성 (Gemini)
    scenes = generate_image_prompts(scenes, lang, aspect_ratio, api_key_gemini, style_preset=style_preset)
    print("이미지 프롬프트 생성 완료")

    # 3) 씬별 이미지 + 영상 클립 생성 (병렬)
    import concurrent.futures

    errors: list[str] = []
    MAX_PARALLEL_IMAGES = 5  # Imagen API rate limit 고려

    # --- 3a) 이미지 병렬 생성 ---
    def _generate_one_image(scene):
        idx = scene["index"]
        image_file = out / f"scene_{idx:03d}.jpg"
        if image_file.exists():
            return None
        print(f"  [{idx}/{len(scenes)}] 이미지 생성 중: {scene.get('title', '')}")
        try:
            if image_provider == "grok":
                from grok_visual import generate_image_grok
                generate_image_grok(scene["image_prompt"], api_key_xai, str(image_file))
            else:
                from gemini_image import generate_image_gemini
                generate_image_gemini(scene["image_prompt"], api_key_gemini, str(image_file))
            return None
        except Exception as e:
            return f"이미지 생성 실패 (scene {idx}): {e}"

    todo_images = [s for s in scenes if not (out / f"scene_{s['index']:03d}.jpg").exists()]
    if todo_images:
        print(f"\n=== 이미지 병렬 생성 ({len(todo_images)}개, 동시 {MAX_PARALLEL_IMAGES}개) ===")
        with concurrent.futures.ThreadPoolExecutor(max_workers=MAX_PARALLEL_IMAGES) as pool:
            results = list(pool.map(_generate_one_image, todo_images))
        for r in results:
            if r:
                print(f"  {r}", file=sys.stderr)
                errors.append(r)

    # --- 3b) 영상 클립 순차 생성 (ffmpeg는 CPU 집약적이므로 순차) ---
    MAX_PARALLEL_CLIPS = 2
    def _generate_one_clip(scene):
        idx = scene["index"]
        image_file = out / f"scene_{idx:03d}.jpg"
        video_file = out / f"scene_{idx:03d}.mp4"

        if video_file.exists():
            if video_file.stat().st_size < 50_000:
                print(f"  [경고] scene_{idx:03d}.mp4 손상 감지, 재생성")
                video_file.unlink()
            else:
                return None

        if not image_file.exists():
            return None

        duration = scene.get("duration", 4.0)
        print(f"  [{idx}/{len(scenes)}] 영상 클립 생성 중...")
        try:
            image_to_clip(str(image_file), str(video_file), duration=duration, aspect_ratio=aspect_ratio)
            return None
        except Exception as e:
            return f"영상 클립 실패 (scene {idx}): {e}"

    todo_clips = [s for s in scenes if not (out / f"scene_{s['index']:03d}.mp4").exists()
                  or (out / f"scene_{s['index']:03d}.mp4").stat().st_size < 50_000]
    if todo_clips:
        print(f"\n=== 영상 클립 생성 ({len(todo_clips)}개, 동시 {MAX_PARALLEL_CLIPS}개) ===")
        with concurrent.futures.ThreadPoolExecutor(max_workers=MAX_PARALLEL_CLIPS) as pool:
            results = list(pool.map(_generate_one_clip, todo_clips))
        for r in results:
            if r:
                print(f"  {r}", file=sys.stderr)
                errors.append(r)

    # scenes.json 저장
    (out / "scenes.json").write_text(
        json.dumps(scenes, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    # 클립이 하나도 없으면 에러와 함께 exit 1
    clip_count = len(list(out.glob("scene_*.mp4")))
    if clip_count == 0:
        err_summary = "\n".join(errors) if errors else "알 수 없는 오류 (stderr 로그 확인)"
        print(f"오류: 생성된 영상 클립 없음.\n{err_summary}", file=sys.stderr)
        sys.exit(1)

    print(f"완료: {out} ({clip_count}개 클립)")


def main() -> None:
    parser = argparse.ArgumentParser(description="클라우드용 비주얼 파이프라인")
    parser.add_argument("script", help="대본 파일 (script.md)")
    parser.add_argument("srt", help="자막 파일 (subtitle.srt)")
    parser.add_argument("output_dir", help="출력 디렉토리")
    parser.add_argument("--lang", default="ko", help="언어 코드 (기본: ko)")
    parser.add_argument("--aspect-ratio", default="16:9", help="화면 비율 (기본: 16:9)")
    parser.add_argument("--image-provider", default="gemini", choices=["gemini", "grok"],
                        help="이미지 생성 백엔드 (기본: gemini)")
    parser.add_argument("--style-preset", default=None,
                        help="스타일 프리셋 (예: cinematic_realism, anime_manhwa)")
    args = parser.parse_args()

    generate_cloud_visuals(
        args.script,
        args.srt,
        args.output_dir,
        lang=args.lang,
        aspect_ratio=args.aspect_ratio,
        image_provider=args.image_provider,
        style_preset=args.style_preset,
    )


if __name__ == "__main__":
    main()
