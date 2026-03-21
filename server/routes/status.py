"""작업 상태 조회 API."""

from fastapi import APIRouter, HTTPException
from server.jobs import get_job
from server.models import JobStatus

router = APIRouter()


@router.get("/status/{job_id}", response_model=JobStatus)
async def check_status(job_id: str):
    job = get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="작업을 찾을 수 없습니다")
    return JobStatus(
        job_id=job.job_id,
        status=job.status,
        current_phase=job.current_phase,
        overall_progress=job.overall_progress,
        phases_completed=job.phases_completed,
        error=job.error,
        outputs=job.outputs if job.status == "completed" else None,
    )
