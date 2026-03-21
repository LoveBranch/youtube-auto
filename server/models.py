"""Pydantic 요청/응답 모델."""

from pydantic import BaseModel


class GenerateRequest(BaseModel):
    channel: str
    topic: str
    language: str = "ko"
    duration_minutes: int = 10
    voice: str | None = None
    aspect_ratio: str = "16:9"
    include_shorts: bool = False
    output_format: str = "mp4"  # "mp4" | "capcut" | "both"
    style_reference_url: str | None = None
    script_content: str | None = None   # 사용자가 직접 제공한 대본 (생성 스킵)
    source_content: str | None = None   # 참고 자료 텍스트 (AI 대본 생성 시 활용)
    image_provider: str = "gemini"      # "gemini" (무료) | "grok" (유료, 고품질)


class ScriptRequest(BaseModel):
    channel: str
    topic: str
    language: str = "ko"
    duration_minutes: int = 10


class AnalyzeStyleRequest(BaseModel):
    url: str
    language: str = "ko"


class JobResponse(BaseModel):
    job_id: str
    status: str


class JobStatus(BaseModel):
    job_id: str
    status: str  # queued | running | completed | failed
    current_phase: str | None = None
    overall_progress: float = 0.0
    phases_completed: list[str] = []
    error: str | None = None
    outputs: dict | None = None
