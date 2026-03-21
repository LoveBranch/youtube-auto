"""리믹스 API 엔드포인트."""

import asyncio
import tempfile
from pathlib import Path

from fastapi import APIRouter, File, Form, UploadFile

from server.jobs import create_job
from server.models import JobResponse
from server.pipeline.remix_pipeline import run_remix_pipeline

router = APIRouter()


@router.post("/remix", response_model=JobResponse)
async def remix_video(
    topic: str = Form(...),
    num_scenes_to_replace: int = Form(3),
    total_scenes: int = Form(10),
    aspect_ratio: str = Form("16:9"),
    language: str = Form("ko"),
    style: str = Form(""),
    image_provider: str = Form("gemini"),
    file: UploadFile = File(...),
):
    """기존 영상의 선택한 씬을 Grok으로 교체한다."""
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
        )
    )
    return JobResponse(job_id=job.job_id, status=job.status)
