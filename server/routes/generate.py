"""영상 생성 API 엔드포인트."""

import asyncio
from fastapi import APIRouter
from server.jobs import create_job
from server.models import GenerateRequest, JobResponse
from server.pipeline.runner import run_pipeline

router = APIRouter()


@router.post("/generate", response_model=JobResponse)
async def generate_video(req: GenerateRequest):
    """전체 파이프라인을 비동기 실행한다."""
    job = create_job()
    asyncio.create_task(run_pipeline(job, req))
    return JobResponse(job_id=job.job_id, status=job.status)
