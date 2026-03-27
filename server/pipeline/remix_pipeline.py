"""리믹스 파이프라인: 기존 영상을 AI가 분석 → 대본 재작성 → 선택 씬 교체.

Free tier: 이미지 → Ken Burns 모션
Premium tier: 이미지 → AI video clip (Hailuo/Pika, 최대 5초, $0.25/clip)
"""

import asyncio
import json
import subprocess
import sys
import tempfile
from pathlib import Path

from server.config import BASE_DIR, settings
from server.jobs import Job, complete_job, complete_phase, fail_job, update_phase

sys.path.insert(0, str(BASE_DIR / "scripts"))

REMIX_PHASES = ["analyze", "split", "generate", "ai_video", "compositing"]


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


def extract_audio_from_video(video_path: Path, audio_path: Path) -> None:
    """영상에서 오디오를 추출한다."""
    subprocess.run(
        ["ffmpeg", "-y", "-i", str(video_path), "-vn", "-acodec", "pcm_s16le",
         "-ar", "16000", "-ac", "1", str(audio_path)],
        capture_output=True, timeout=120,
    )


def extract_scene_thumbnails(video_path: Path, num_scenes: int, output_dir: Path) -> list[str]:
    """각 씬의 중앙 프레임을 JPEG 썸네일로 추출한다."""
    import base64
    duration = get_video_duration(video_path)
    scene_dur = duration / num_scenes
    thumbnails: list[str] = []

    for i in range(num_scenes):
        mid = (i + 0.5) * scene_dur
        out = output_dir / f"thumb_{i:03d}.jpg"
        subprocess.run(
            ["ffmpeg", "-y", "-ss", str(mid), "-i", str(video_path),
             "-frames:v", "1", "-q:v", "8",
             "-vf", "scale=320:-1",
             str(out)],
            capture_output=True, timeout=15,
        )
        if out.exists():
            b64 = base64.b64encode(out.read_bytes()).decode("utf-8")
            thumbnails.append(f"data:image/jpeg;base64,{b64}")
        else:
            thumbnails.append("")

    return thumbnails


def extract_original_audio_full(video_path: Path, audio_path: Path) -> None:
    """원본 오디오를 원본 품질로 추출한다 (Scene Swap용)."""
    subprocess.run(
        ["ffmpeg", "-y", "-i", str(video_path), "-vn", "-acodec", "aac",
         "-b:a", "192k", str(audio_path)],
        capture_output=True, timeout=120,
    )


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


def concat_scenes_video_only(scenes: list[Path], output_path: Path, aspect_ratio: str) -> None:
    """씬 클립들을 비디오 트랙만 합친다 (오디오 없음)."""
    resolutions = {"16:9": (1280, 720), "9:16": (720, 1280), "1:1": (720, 720)}
    w, h = resolutions.get(aspect_ratio, (1280, 720))

    with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False, encoding="utf-8") as f:
        for s in scenes:
            f.write(f"file '{s.as_posix()}'\n")
        concat_file = f.name

    try:
        subprocess.run(
            [
                "ffmpeg", "-y",
                "-threads", "1",
                "-f", "concat", "-safe", "0",
                "-i", concat_file,
                "-vf", (
                    f"scale={w}:{h}:force_original_aspect_ratio=decrease,"
                    f"pad={w}:{h}:(ow-iw)/2:(oh-ih)/2"
                ),
                "-c:v", "libx264", "-preset", "ultrafast", "-crf", "23",
                "-pix_fmt", "yuv420p",
                "-an",
                str(output_path),
            ],
            capture_output=True, timeout=600,
        )
    finally:
        Path(concat_file).unlink(missing_ok=True)


def overlay_original_audio(
    video_path: Path, source_video: Path, output_path: Path
) -> None:
    """비디오 트랙 위에 원본 영상의 오디오를 오버레이한다.

    Scene Swap: 비주얼만 교체, 원본 오디오 유지.
    """
    subprocess.run(
        [
            "ffmpeg", "-y",
            "-i", str(video_path),       # 새 비디오 (오디오 없음)
            "-i", str(source_video),      # 원본 영상 (오디오 소스)
            "-c:v", "copy",               # 비디오는 그대로
            "-map", "0:v:0",              # 비디오: 첫 번째 입력 (새 비디오)
            "-map", "1:a:0?",             # 오디오: 두 번째 입력 (원본) — 오디오 없으면 무시
            "-c:a", "aac", "-b:a", "192k",
            "-shortest",                  # 짧은 쪽에 맞춤
            str(output_path),
        ],
        capture_output=True, timeout=300,
    )


async def transcribe_video(audio_path: Path, language: str, api_key: str) -> str:
    """영상 오디오를 Gemini로 텍스트 전사한다."""
    import requests
    import base64

    audio_data = audio_path.read_bytes()
    audio_b64 = base64.b64encode(audio_data).decode("utf-8")

    resp = requests.post(
        "https://generativelanguage.googleapis.com/v1beta/models/gemini-2.0-flash:generateContent",
        params={"key": api_key},
        json={
            "contents": [{
                "parts": [
                    {"inline_data": {"mime_type": "audio/wav", "data": audio_b64}},
                    {"text": f"Transcribe this audio to text. Language: {language}. Return only the transcript, no timestamps."},
                ]
            }],
            "generationConfig": {"temperature": 0.1, "maxOutputTokens": 8000},
        },
        timeout=120,
    )
    resp.raise_for_status()
    return resp.json()["candidates"][0]["content"]["parts"][0]["text"]


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
    generation_tier: str = "free",
    ai_video_provider: str = "hailuo",
    max_clip_duration: int = 5,
) -> None:
    """리믹스 파이프라인 전체 실행.

    1) analyze: 영상 → 오디오 추출 → 전사 → AI 대본 분석/재작성
    2) split: 영상을 씬별로 분리
    3) generate: 교체할 씬의 이미지 생성
    4) ai_video: (Premium) 이미지 → AI video clip 변환
    5) compositing: 최종 합성
    """
    try:
        from grok_visual import image_to_clip

        api_key_xai = settings.get("xai", {}).get("api_key", "")
        api_key_gemini = settings.get("tts", {}).get("api_key", "")

        if image_provider == "grok" and not api_key_xai:
            raise ValueError("xAI API 키 없음 (settings.json → xai.api_key)")
        if not api_key_gemini:
            raise ValueError("Gemini API 키 없음 (settings.json → tts.api_key)")

        output_dir = source_video.parent / f"remix_{job.job_id}"
        output_dir.mkdir(exist_ok=True)

        # === Phase 0: AI 분석 — 영상 전사 + 대본 재작성 ===
        update_phase(job, "analyze", 0.0)

        # 오디오 추출
        audio_path = output_dir / "source_audio.wav"
        await asyncio.to_thread(extract_audio_from_video, source_video, audio_path)
        update_phase(job, "analyze", 0.3)

        # Gemini로 전사
        transcript = ""
        if audio_path.exists() and audio_path.stat().st_size > 1000:
            try:
                transcript = await asyncio.to_thread(
                    transcribe_video, audio_path, language, api_key_gemini
                )
            except Exception as e:
                print(f"[remix] Transcription failed, continuing with topic only: {e}")
        update_phase(job, "analyze", 0.6)

        # AI 분석: 대본 재작성 + 씬별 중요도 + 교체 추천
        remix_analysis = None
        if transcript.strip():
            try:
                from server.pipeline.scene_analyzer import analyze_video_for_remix
                remix_analysis = await asyncio.to_thread(
                    analyze_video_for_remix, transcript, total_scenes, language, api_key_gemini
                )
                job.outputs["rewritten_script"] = remix_analysis.get("rewritten_script", "")
                job.outputs["ai_recommended_replace"] = remix_analysis.get("recommended_replace_count", num_scenes_to_replace)
            except Exception as e:
                print(f"[remix] AI analysis failed, using basic mode: {e}")

        complete_phase(job, "analyze")

        # === Phase 1: 씬 분리 ===
        update_phase(job, "split", 0.0)
        scenes = await asyncio.to_thread(
            split_video_into_scenes, source_video, total_scenes, output_dir
        )
        complete_phase(job, "split")

        # === Phase 2: 교체할 씬 결정 + 이미지 생성 ===
        # AI 분석 결과가 있으면 중요도 기반, 없으면 기본 균등 분포
        if remix_analysis and remix_analysis.get("scene_breakdown"):
            breakdown = remix_analysis["scene_breakdown"]
            # 중요도 높은 순으로 정렬해서 교체 대상 선정
            ranked = sorted(
                [s for s in breakdown if s.get("recommend_replace", False)],
                key=lambda x: x.get("importance", 0),
                reverse=True,
            )
            replace_indices = [s["scene_index"] for s in ranked[:num_scenes_to_replace]]
            if not replace_indices:
                replace_indices = select_scenes_to_replace(total_scenes, num_scenes_to_replace)
            # 씬별 motion prompt 저장
            motion_prompts = {s["scene_index"]: s.get("motion_prompt", "") for s in breakdown}
        else:
            replace_indices = select_scenes_to_replace(total_scenes, num_scenes_to_replace)
            motion_prompts = {}

        replace_indices = sorted(set(replace_indices))
        job.outputs["replace_indices"] = replace_indices
        job.outputs["total_scenes"] = total_scenes

        update_phase(job, "generate", 0.0)
        img_paths: dict[int, str] = {}
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

            img_paths[idx] = img_path

            # Free tier: Ken Burns 모션으로 바로 클립 생성
            if generation_tier != "premium":
                await asyncio.to_thread(image_to_clip, img_path, clip_path, orig_dur, aspect_ratio)
                scenes[idx] = Path(clip_path)

        complete_phase(job, "generate")

        # === Phase 3: Premium AI Video Clips ===
        if generation_tier == "premium" and img_paths:
            update_phase(job, "ai_video", 0.0)
            from ai_video import generate_ai_video_clip

            ai_clips_generated = []
            for i, idx in enumerate(replace_indices):
                update_phase(job, "ai_video", i / len(replace_indices))

                img_path = img_paths.get(idx)
                if not img_path or not Path(img_path).exists():
                    continue

                ai_clip_path = str(output_dir / f"new_{idx:03d}_ai.mp4")
                motion = motion_prompts.get(idx, "cinematic slow motion with dramatic lighting")
                clip_dur = min(max_clip_duration, 5)

                try:
                    await asyncio.to_thread(
                        generate_ai_video_clip,
                        img_path, motion, ai_clip_path,
                        provider=ai_video_provider,
                        duration=clip_dur,
                        settings=settings,
                    )
                    scenes[idx] = Path(ai_clip_path)
                    ai_clips_generated.append(idx)
                except Exception as exc:
                    print(f"[remix ai_video] Scene {idx} failed, falling back to Ken Burns: {exc}")
                    # 폴백: Ken Burns
                    clip_path = str(output_dir / f"new_{idx:03d}.mp4")
                    orig_dur = await asyncio.to_thread(get_video_duration, scenes[idx])
                    await asyncio.to_thread(image_to_clip, img_path, clip_path, orig_dur, aspect_ratio)
                    scenes[idx] = Path(clip_path)

            job.outputs["ai_clips_generated"] = ai_clips_generated
            job.outputs["generation_tier"] = "premium"
            complete_phase(job, "ai_video")

        # === Phase 4: 최종 합성 (원본 오디오 보존) ===
        update_phase(job, "compositing", 0.0)

        # Step 1: 비디오 트랙만 합치기
        video_only = output_dir / "remix_video_only.mp4"
        await asyncio.to_thread(concat_scenes_video_only, scenes, video_only, aspect_ratio)
        update_phase(job, "compositing", 0.5)

        # Step 2: 원본 오디오 오버레이
        final_path = output_dir / "remix_final.mp4"
        await asyncio.to_thread(overlay_original_audio, video_only, source_video, final_path)

        # video_only 임시 파일 정리
        video_only.unlink(missing_ok=True)

        complete_phase(job, "compositing")

        complete_job(job, {**job.outputs, "mp4": str(final_path)})

    except Exception as e:
        fail_job(job, str(e))
