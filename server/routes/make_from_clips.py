"""Make from Clips API endpoints."""

from __future__ import annotations

import asyncio
import json
import tempfile
from pathlib import Path

from fastapi import APIRouter, File, Form, HTTPException, UploadFile

from server.jobs import create_job
from server.models import JobResponse
from server.pipeline.make_from_clips_pipeline import (
    MAX_DURATION_SEC,
    ClipAsset,
    SUPPORTED_SUBTITLE_FORMATS,
    analyze_make_from_clips_audio,
    run_make_from_clips_pipeline,
)

router = APIRouter()


def _save_upload(upload: UploadFile, target_dir: Path, filename: str | None = None) -> Path:
    suffix = Path(upload.filename or "asset").suffix
    resolved_name = filename or f"{Path(upload.filename or 'asset').stem}{suffix or ''}"
    output_path = target_dir / resolved_name
    output_path.write_bytes(upload.file.read())
    return output_path


@router.post("/make-from-clips/analyze")
async def analyze_make_from_clips(
    audio: UploadFile = File(...),
    script: str = Form(...),
    language: str = Form("ko"),
):
    script = script.strip()
    if not script:
        raise HTTPException(status_code=400, detail="script is required")

    tmp_dir = Path(tempfile.mkdtemp(prefix="make_from_clips_analyze_"))
    audio_suffix = Path(audio.filename or "audio").suffix or ".wav"
    audio_path = _save_upload(audio, tmp_dir, f"audio{audio_suffix}")

    try:
        result = await analyze_make_from_clips_audio(
            audio_path=audio_path,
            script=script,
            language=language,
        )
    except Exception as error:
        raise HTTPException(status_code=500, detail=str(error)) from error

    if result["totalDurationSec"] > MAX_DURATION_SEC:
        raise HTTPException(status_code=400, detail="aligned timeline exceeds 3 minutes")

    result["audioPath"] = str(audio_path)
    return result


@router.post("/make-from-clips/render", response_model=JobResponse)
async def render_make_from_clips(
    audio: UploadFile = File(...),
    clips: list[UploadFile] = File(...),
    script: str = Form(...),
    aligned_segments_json: str = Form(...),
    clip_meta_json: str = Form(...),
    language: str = Form("ko"),
    aspect_ratio: str = Form("9:16"),
    subtitle_format: str = Form("vtt+srt"),
    primary_motion: str = Form("slowdown"),
):
    if subtitle_format not in SUPPORTED_SUBTITLE_FORMATS:
        raise HTTPException(status_code=400, detail="unsupported subtitle format")

    try:
        aligned_segments = json.loads(aligned_segments_json)
        clip_meta = json.loads(clip_meta_json)
    except json.JSONDecodeError as error:
        raise HTTPException(status_code=400, detail=f"invalid json payload: {error}") from error

    if not isinstance(aligned_segments, list) or not aligned_segments:
        raise HTTPException(status_code=400, detail="aligned segments are required")
    if not isinstance(clip_meta, list) or not clip_meta:
        raise HTTPException(status_code=400, detail="clip metadata is required")
    if len(clips) != len(clip_meta):
        raise HTTPException(status_code=400, detail="clip metadata count must match uploaded clips")

    total_duration = sum(float(segment.get("durationSec", 0)) for segment in aligned_segments)
    if total_duration > MAX_DURATION_SEC:
        raise HTTPException(status_code=400, detail="final video exceeds 3 minutes")

    tmp_dir = Path(tempfile.mkdtemp(prefix="make_from_clips_render_"))
    audio_suffix = Path(audio.filename or "audio").suffix or ".wav"
    audio_path = _save_upload(audio, tmp_dir, f"audio{audio_suffix}")

    clip_assets: list[ClipAsset] = []
    for upload, meta in zip(clips, clip_meta, strict=False):
        category = str(meta.get("category", "main"))
        upload_name = str(meta.get("name") or upload.filename or f"clip_{len(clip_assets) + 1}")
        clip_path = _save_upload(upload, tmp_dir, f"{len(clip_assets) + 1:03d}_{Path(upload_name).name}")
        clip_assets.append(ClipAsset(name=upload_name, path=clip_path, category=category))

    job = create_job()
    asyncio.create_task(
        run_make_from_clips_pipeline(
            job=job,
            audio_path=audio_path,
            script=script,
            language=language,
            subtitle_format=subtitle_format,
            aspect_ratio=aspect_ratio,
            primary_motion=primary_motion,
            aligned_segments=aligned_segments,
            clip_assets=clip_assets,
        )
    )
    return JobResponse(job_id=job.job_id, status=job.status)
