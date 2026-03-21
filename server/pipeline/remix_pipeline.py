"""리믹스 파이프라인: 기존 영상의 선택한 씬을 Grok으로 교체한다."""

import asyncio
import json
import subprocess
import sys
import tempfile
from pathlib import Path

from server.config import BASE_DIR, settings
from server.jobs import Job, complete_job, complete_phase, fail_job, update_phase

sys.path.insert(0, str(BASE_DIR / "scripts"))

REMIX_PHASES = ["split", "generate", "compositing"]


def get_video_duration(path: Path) -> float:
    """영상 길이(초)를 반환한다."""
    result = subprocess.run(
        ["ffprobe", "-v", "quiet", "-print_format", "json", "-show_streams", str(path)],
        capture_output=True, text=True, timeout=30,
    )
    try:
        data = json.loads(result.stdout)
        for s in data.get("streams", []):
            if s.get("codec_type") == "video" and "duration" in s:
                return float(s["duration"])
    except Exception:
        pass
    return 10.0


def split_video_into_scenes(video_path: Path, num_scenes: int, output_dir: Path) -> list[Path]:
    """영상을 num_scenes개의 동일 길이 클립으로 분리한다."""
    duration = get_video_duration(video_path)
    scene_dur = duration / num_scenes
    scenes: list[Path] = []

    for i in range(num_scenes):
        start = i * scene_dur
        out = output_dir / f"orig_{i:03d}.mp4"
        subprocess.run(
            [
                "ffmpeg", "-y",
                "-ss", str(start), "-i", str(video_path),
                "-t", str(scene_dur),
                "-c", "copy",
                str(out),
            ],
            capture_output=True, timeout=60,
        )
        scenes.append(out)

    return scenes


def select_scenes_to_replace(num_scenes: int, num_replace: int) -> list[int]:
    """교체할 씬 인덱스를 선택한다.
    - 0번(훅/인트로) 항상 포함
    - 나머지는 균등 분포
    """
    num_replace = min(num_replace, num_scenes)
    selected = [0]
    remaining = num_replace - 1

    if remaining > 0 and num_scenes > 1:
        step = (num_scenes - 1) / remaining
        for i in range(remaining):
            idx = round(1 + i * step)
            idx = min(idx, num_scenes - 1)
            if idx not in selected:
                selected.append(idx)

    return sorted(selected)


def concat_scenes(scenes: list[Path], output_path: Path, aspect_ratio: str) -> None:
    """씬 클립들을 하나의 MP4로 합친다."""
    resolutions = {"16:9": (1920, 1080), "9:16": (1080, 1920), "1:1": (1080, 1080)}
    w, h = resolutions.get(aspect_ratio, (1920, 1080))

    with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False, encoding="utf-8") as f:
        for s in scenes:
            f.write(f"file '{s.as_posix()}'\n")
        concat_file = f.name

    try:
        subprocess.run(
            [
                "ffmpeg", "-y", "-f", "concat", "-safe", "0",
                "-i", concat_file,
                "-vf", (
                    f"scale={w}:{h}:force_original_aspect_ratio=decrease,"
                    f"pad={w}:{h}:(ow-iw)/2:(oh-ih)/2"
                ),
                "-c:v", "libx264", "-crf", "23", "-pix_fmt", "yuv420p",
                str(output_path),
            ],
            capture_output=True, timeout=300,
        )
    finally:
        Path(concat_file).unlink(missing_ok=True)


async def run_remix_pipeline(
    job: Job,
    source_video: Path,
    topic: str,
    num_scenes_to_replace: int,
    total_scenes: int,
    aspect_ratio: str,
    language: str,
    style: str,
    image_provider: str = "gemini",
) -> None:
    """리믹스 파이프라인 전체 실행."""
    try:
        from grok_visual import image_to_clip

        api_key_xai = settings.get("xai", {}).get("api_key", "")
        api_key_gemini = settings.get("tts", {}).get("api_key", "")

        if image_provider == "grok" and not api_key_xai:
            raise ValueError("xAI API 키 없음 (settings.json → xai.api_key)")
        if image_provider == "gemini" and not api_key_gemini:
            raise ValueError("Gemini API 키 없음 (settings.json → tts.api_key)")

        output_dir = source_video.parent / f"remix_{job.job_id}"
        output_dir.mkdir(exist_ok=True)

        # 1단계: 씬 분리
        update_phase(job, "split", 0.0)
        scenes = await asyncio.to_thread(
            split_video_into_scenes, source_video, total_scenes, output_dir
        )
        complete_phase(job, "split")

        # 2단계: 교체할 씬 결정 + Grok 생성
        replace_indices = select_scenes_to_replace(total_scenes, num_scenes_to_replace)
        job.outputs["replace_indices"] = replace_indices
        job.outputs["total_scenes"] = total_scenes

        update_phase(job, "generate", 0.0)
        for i, idx in enumerate(replace_indices):
            update_phase(job, "generate", i / len(replace_indices))

            position_label = "hook intro" if idx == 0 else f"scene {idx + 1} of {total_scenes}"
            prompt = (
                f"{topic}, {position_label}, cinematic, 4K, "
                f"{'vertical 9:16' if aspect_ratio == '9:16' else 'widescreen 16:9'}, "
                f"high quality photo"
            )
            if style:
                prompt += f", {style}"

            img_path = str(output_dir / f"new_{idx:03d}.jpg")
            clip_path = str(output_dir / f"new_{idx:03d}.mp4")

            orig_dur = await asyncio.to_thread(get_video_duration, scenes[idx])
            if image_provider == "grok":
                from grok_visual import generate_image_grok
                await asyncio.to_thread(generate_image_grok, prompt, api_key_xai, img_path)
            else:
                from gemini_image import generate_image_gemini
                await asyncio.to_thread(generate_image_gemini, prompt, api_key_gemini, img_path)
            await asyncio.to_thread(image_to_clip, img_path, clip_path, orig_dur, aspect_ratio)
            scenes[idx] = Path(clip_path)

        complete_phase(job, "generate")

        # 3단계: 최종 합성
        update_phase(job, "compositing", 0.0)
        final_path = output_dir / "remix_final.mp4"
        await asyncio.to_thread(concat_scenes, scenes, final_path, aspect_ratio)
        complete_phase(job, "compositing")

        complete_job(job, {"mp4": str(final_path)})

    except Exception as e:
        fail_job(job, str(e))
