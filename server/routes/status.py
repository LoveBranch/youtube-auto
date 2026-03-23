"""작업 상태 조회 API."""

from fastapi import APIRouter, HTTPException
from server.jobs import get_job, fail_job
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


@router.delete("/status/{job_id}")
async def cancel_job(job_id: str):
    job = get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="작업을 찾을 수 없습니다")
    if job.status in ("completed", "failed", "cancelled"):
        return {"ok": True}
    job.status = "cancelled"
    job.error = "사용자가 취소했습니다"
    return {"ok": True}
