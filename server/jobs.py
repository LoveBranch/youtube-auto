"""비동기 작업 관리자."""

import time
import uuid
from dataclasses import dataclass, field


@dataclass
class Job:
    job_id: str
    status: str = "queued"  # queued | running | completed | failed
    current_phase: str | None = None
    overall_progress: float = 0.0
    phases_completed: list[str] = field(default_factory=list)
    error: str | None = None
    outputs: dict = field(default_factory=dict)
    created_at: float = field(default_factory=time.time)


# 전역 작업 저장소
_jobs: dict[str, Job] = {}

# 파이프라인 단계별 가중치 (전체 진행률 계산용)
PHASE_WEIGHTS = {
    # Generate pipeline
    "script": 0.05,
    "tts": 0.10,
    "whisper": 0.10,
    "visuals": 0.35,
    "ai_video": 0.15,   # Premium tier: AI video clip generation
    "compositing": 0.15,
    "capcut": 0.10,
    # Remix pipeline
    "analyze": 0.15,
    "split": 0.10,
    "generate": 0.30,
    # ai_video: 0.15 (shared)
    # compositing: 0.15 (shared)
    # Make from Clips pipeline
    "slot_render": 0.55,
    "mux": 0.30,
    "preview": 0.15,
}


def create_job() -> Job:
    job_id = uuid.uuid4().hex[:12]
    job = Job(job_id=job_id)
    _jobs[job_id] = job
    return job


def get_job(job_id: str) -> Job | None:
    return _jobs.get(job_id)


def update_phase(job: Job, phase: str, progress: float = 0.0):
    """현재 단계와 전체 진행률을 업데이트한다."""
    job.status = "running"
    job.current_phase = phase

    # 이전 단계들의 가중치 합산
    completed_weight = sum(PHASE_WEIGHTS.get(p, 0) for p in job.phases_completed)
    current_weight = PHASE_WEIGHTS.get(phase, 0) * progress
    job.overall_progress = min(completed_weight + current_weight, 1.0)


def complete_phase(job: Job, phase: str):
    """단계를 완료로 표시한다."""
    if phase not in job.phases_completed:
        job.phases_completed.append(phase)
    job.overall_progress = sum(PHASE_WEIGHTS.get(p, 0) for p in job.phases_completed)


def fail_job(job: Job, error: str):
    job.status = "failed"
    job.error = error


def complete_job(job: Job, outputs: dict):
    job.status = "completed"
    job.overall_progress = 1.0
    job.outputs = outputs


def cleanup_old_jobs(max_age_seconds: int = 3600):
    """오래된 작업을 제거한다."""
    now = time.time()
    expired = [jid for jid, j in _jobs.items() if now - j.created_at > max_age_seconds]
    for jid in expired:
        del _jobs[jid]
