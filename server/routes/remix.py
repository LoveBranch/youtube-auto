"""리믹스 API 엔드포인트."""

import asyncio
import tempfile
from pathlib import Path

from fastapi import APIRouter, File, Form, UploadFile
from fastapi.responses import JSONResponse

from server.config import settings
from server.jobs import create_job
from server.models import JobResponse
from server.pipeline.remix_pipeline import (
    run_remix_pipeline,
    get_video_duration,
    extract_audio_from_video,
    extract_scene_thumbnails,
    select_scenes_to_replace,
    transcribe_video,
)

router = APIRouter()


# 임시 분석 결과 저장 (analyze → confirm 2단계 플로우용)
_analyze_cache: dict[str, dict] = {}


@router.post("/remix/analyze")
async def analyze_for_remix(
    total_scenes: int = Form(10),
    num_scenes_to_replace: int = Form(3),
    language: str = Form("ko"),
    direction: str = Form(""),
    style: str = Form(""),
    file: UploadFile = File(...),
):
    """Step 1: 영상을 분석 → 씬 썸네일 + 대본 전사 + AI 재작성 대본 반환.

    1. 영상 길이 감지 + 씬 썸네일 추출
    2. 오디오 추출 → Gemini 전사
    3. AI가 비슷한 대본을 재작성 + 씬별 중요도 분석
    4. 사용자에게 재작성 대본 + 씬 프리뷰 반환
    """
    suffix = Path(file.filename or "video.mp4").suffix or ".mp4"
    tmp_dir = Path(tempfile.mkdtemp(prefix="remix_analyze_"))
    source_path = tmp_dir / f"source{suffix}"
    source_path.write_bytes(await file.read())

    try:
        api_key_gemini = settings.get("tts", {}).get("api_key", "")

        # 1) 영상 길이 + 씬 썸네일 추출
        duration = await asyncio.to_thread(get_video_duration, source_path)
        thumbnails = await asyncio.to_thread(
            extract_scene_thumbnails, source_path, total_scenes, tmp_dir,
        )
        replace_indices = select_scenes_to_replace(total_scenes, num_scenes_to_replace)
        scene_dur = duration / total_scenes

        # 2) 오디오 추출 + 전사
        original_transcript = ""
        rewritten_script = ""
        scene_breakdown = []
        ai_recommended_replace = num_scenes_to_replace

        if api_key_gemini:
            try:
                audio_path = tmp_dir / "audio.wav"
                await asyncio.to_thread(extract_audio_from_video, source_path, audio_path)

                if audio_path.exists() and audio_path.stat().st_size > 1000:
                    original_transcript = await transcribe_video(audio_path, language, api_key_gemini)
            except Exception as e:
                print(f"[remix/analyze] Transcription failed: {e}")

            # 3) AI 대본 재작성
            if original_transcript.strip():
                try:
                    from server.pipeline.scene_analyzer import analyze_video_for_remix
                    analysis = await asyncio.to_thread(
                        analyze_video_for_remix, original_transcript, total_scenes, language, api_key_gemini,
                        direction=direction, style=style,
                    )
                    rewritten_script = analysis.get("rewritten_script", "")
                    scene_breakdown = analysis.get("scene_breakdown", [])
                    ai_recommended_replace = analysis.get("recommended_replace_count", num_scenes_to_replace)

                    # AI가 추천한 교체 인덱스 반영
                    if scene_breakdown:
                        ai_replace = [
                            s["scene_index"] for s in scene_breakdown
                            if s.get("recommend_replace", False)
                        ]
                        if ai_replace:
                            replace_indices = sorted(ai_replace[:num_scenes_to_replace])
                except Exception as e:
                    print(f"[remix/analyze] AI rewrite failed: {e}")

        # 씬 목록 구성
        scenes = []
        breakdown_map = {s.get("scene_index", -1): s for s in scene_breakdown}
        for i in range(total_scenes):
            bd = breakdown_map.get(i, {})
            scenes.append({
                "index": i,
                "start": round(i * scene_dur, 2),
                "end": round((i + 1) * scene_dur, 2),
                "duration": round(scene_dur, 2),
                "thumbnail": thumbnails[i] if i < len(thumbnails) else "",
                "will_replace": i in replace_indices,
                "title": bd.get("title", ""),
                "importance": bd.get("importance", 5),
            })

        # 캐시에 저장
        analyze_id = f"a_{id(source_path)}_{total_scenes}"
        _analyze_cache[analyze_id] = {
            "source_path": str(source_path),
            "total_scenes": total_scenes,
        }

        return JSONResponse({
            "analyze_id": analyze_id,
            "duration": round(duration, 2),
            "total_scenes": total_scenes,
            "scenes": scenes,
            "replace_indices": replace_indices,
            "source_path": str(source_path),
            "original_transcript": original_transcript,
            "rewritten_script": rewritten_script,
            "ai_recommended_replace": ai_recommended_replace,
        })
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)


@router.post("/remix", response_model=JobResponse)
async def remix_video(
    topic: str = Form(...),
    num_scenes_to_replace: int = Form(3),
    total_scenes: int = Form(10),
    aspect_ratio: str = Form("16:9"),
    language: str = Form("ko"),
    style: str = Form(""),
    image_provider: str = Form("gemini"),
    generation_tier: str = Form("free"),        # "free" | "premium"
    ai_video_provider: str = Form("hailuo"),    # "hailuo" | "pika"
    max_clip_duration: int = Form(5),           # AI video 최대 길이 (초)
    file: UploadFile = File(...),
):
    """기존 영상을 AI로 분석/재작성하고 선택한 씬을 교체한다.

    Free tier: 이미지 → Ken Burns (무료)
    Premium tier: 이미지 → AI video clip ($0.25/clip)
    """
    suffix = Path(file.filename or "video.mp4").suffix or ".mp4"

    # 업로드 파일을 임시 디렉토리에 저장 (파이프라인이 끝날 때까지 유지)
    tmp_dir = Path(tempfile.mkdtemp(prefix="remix_src_"))
    source_path = tmp_dir / f"source{suffix}"
    source_path.write_bytes(await file.read())

    job = create_job()
    asyncio.create_task(
        run_remix_pipeline(
            job=job,
            source_video=source_path,
            topic=topic,
            num_scenes_to_replace=num_scenes_to_replace,
            total_scenes=total_scenes,
            aspect_ratio=aspect_ratio,
            language=language,
            style=style,
            image_provider=image_provider,
            generation_tier=generation_tier,
            ai_video_provider=ai_video_provider,
            max_clip_duration=min(max_clip_duration, 5),
        )
    )
    return JobResponse(job_id=job.job_id, status=job.status)
