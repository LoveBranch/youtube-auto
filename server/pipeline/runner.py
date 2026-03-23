"""파이프라인 오케스트레이터. 전체 영상 생성 과정을 순차 실행한다."""

import asyncio
import re
import sys
from pathlib import Path

from server.config import BASE_DIR, CHANNELS_DIR, settings
from server.jobs import Job, complete_job, complete_phase, fail_job, update_phase
from server.models import GenerateRequest

# 기존 스크립트를 import할 수 있도록 경로 추가
sys.path.insert(0, str(BASE_DIR / "scripts"))


def safe_dirname(name: str, max_len: int = 60) -> str:
    """Windows/Mac 경로에 사용할 수 없는 문자를 제거하고 안전한 폴더명 반환."""
    name = re.sub(r'[\\/:*?"<>|()\[\]{}]', '', name)  # 특수문자 제거
    name = re.sub(r'\s+', '_', name.strip())           # 공백 → 언더스코어
    name = name.strip('._')                             # 앞뒤 점/언더스코어 제거
    return name[:max_len] or "project"


def _check_cancelled(job: Job):
    if job.status == "cancelled":
        raise RuntimeError("cancelled")


async def run_pipeline(job: Job, req: GenerateRequest):
    """전체 파이프라인을 비동기 실행한다."""
    try:
        project_name = safe_dirname(req.topic)
        project_dir = CHANNELS_DIR / req.channel / "projects" / project_name
        project_dir.mkdir(parents=True, exist_ok=True)

        script_path = project_dir / "script.md"
        audio_path = project_dir / "audio.mp3"
        srt_path = project_dir / "subtitle.srt"
        visuals_dir = project_dir / "visuals"
        final_mp4 = project_dir / "final.mp4"
        preview_mp4 = project_dir / "preview.mp4"

        # === Phase 1: 대본 생성 ===
        update_phase(job, "script", 0.0)
        if not script_path.exists():
            if req.script_content:
                # 사용자가 직접 대본 제공 → 생성 스킵
                script_path.write_text(req.script_content, encoding="utf-8")
            else:
                from server.pipeline.script_gen import generate_script

                style_profile = None
                if req.style_reference_url:
                    from server.pipeline.style_analyzer import analyze_style
                    style_profile = await asyncio.to_thread(
                        analyze_style, url=req.style_reference_url, language=req.language
                    )
                    job.outputs["style_profile"] = style_profile

                script_text = await asyncio.to_thread(
                    generate_script, req.topic, req.language, req.duration_minutes,
                    style_profile, req.source_content
                )
                script_path.write_text(script_text, encoding="utf-8")
        complete_phase(job, "script")
        _check_cancelled(job)

        # === Phase 2: TTS ===
        update_phase(job, "tts", 0.0)
        if not audio_path.exists():
            from tts import extract_narration, call_edge_tts, resolve_voice

            voice = req.voice or resolve_voice(req.language, settings)
            text = extract_narration(script_path.read_text(encoding="utf-8"))
            await call_edge_tts(text, voice, req.language, str(audio_path))
        complete_phase(job, "tts")
        _check_cancelled(job)

        # === Phase 3: 자막 생성 (Gemini) ===
        update_phase(job, "whisper", 0.0)
        if not srt_path.exists():
            from gemini_srt import generate_srt_with_gemini

            api_key = settings.get("tts", {}).get("api_key", "")
            max_chars = 10 if req.aspect_ratio == "9:16" else 15
            srt_text = await asyncio.to_thread(
                generate_srt_with_gemini,
                str(audio_path),
                max_chars, req.language, api_key,
            )
            srt_path.write_text(srt_text, encoding="utf-8")
        complete_phase(job, "whisper")
        _check_cancelled(job)

        # === Phase 4: 이미지 + 모션 (Grok Aurora) ===
        update_phase(job, "visuals", 0.0)
        if not visuals_dir.exists() or not list(visuals_dir.glob("scene_*.mp4")):
            import subprocess
            cmd = [
                sys.executable, str(BASE_DIR / "scripts" / "cloud_visual.py"),
                str(script_path), str(srt_path), str(visuals_dir),
                "--lang", req.language,
                "--aspect-ratio", req.aspect_ratio,
                "--image-provider", req.image_provider,
            ]
            if req.style_preset:
                cmd.extend(["--style-preset", req.style_preset])
            await asyncio.to_thread(
                subprocess.run, cmd, capture_output=True, timeout=600,
                env={**__import__("os").environ, "PYTHONIOENCODING": "utf-8"},
            )
        complete_phase(job, "visuals")

        # === Phase 5: 최종 MP4 합성 ===
        outputs = {
            "script": str(script_path),
            "audio": str(audio_path),
            "subtitle": str(srt_path),
            "visuals": str(visuals_dir),
        }

        if req.output_format in ("mp4", "both"):
            update_phase(job, "compositing", 0.0)
            from server.utils.ffmpeg import composite_final_video, generate_preview

            await asyncio.to_thread(
                composite_final_video,
                visuals_dir, audio_path, srt_path, final_mp4, req.aspect_ratio,
            )
            outputs["mp4"] = str(final_mp4)

            # 미리보기 생성
            await asyncio.to_thread(generate_preview, final_mp4, preview_mp4)
            outputs["preview"] = str(preview_mp4)
            complete_phase(job, "compositing")

        if req.output_format in ("capcut", "both"):
            update_phase(job, "capcut", 0.0)
            import subprocess
            # Use settings capcut dir if set (local), otherwise use a path inside project dir
            capcut_dir = settings.get("capcut", {}).get("project_dir", "") or str(project_dir / "capcut_export")
            cmd = [
                sys.executable, str(BASE_DIR / "scripts" / "capcut_project.py"),
                str(audio_path), str(srt_path), req.topic,
                "--aspect-ratio", req.aspect_ratio,
                "--scenes-dir", str(visuals_dir),
                "--capcut-dir", capcut_dir,
            ]
            await asyncio.to_thread(
                subprocess.run, cmd, capture_output=True, timeout=120,
                env={**__import__("os").environ, "PYTHONIOENCODING": "utf-8"},
            )
            outputs["capcut_project"] = project_name
            outputs["capcut_dir"] = capcut_dir
            complete_phase(job, "capcut")

        complete_job(job, outputs)

    except BaseException as e:
        fail_job(job, str(e))
