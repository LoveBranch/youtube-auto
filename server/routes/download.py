"""Result download API."""

from pathlib import Path

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import FileResponse

from server.config import settings
from server.jobs import get_job
from server.utils.zip_export import zip_capcut_project

router = APIRouter()


@router.get("/download/{job_id}")
async def download_result(job_id: str, format: str = Query("mp4", pattern="^(mp4|capcut|preview|vtt|srt)$")):
    job = get_job(job_id)
    if not job:
        raise HTTPException(404, "Job not found")
    if job.status != "completed":
        raise HTTPException(400, f"Job is not complete yet: {job.status}")

    if format == "mp4":
        mp4_path = job.outputs.get("mp4")
        if not mp4_path or not Path(mp4_path).exists():
            raise HTTPException(404, "MP4 file is missing")
        return FileResponse(mp4_path, media_type="video/mp4", filename="video.mp4")

    if format == "preview":
        preview_path = job.outputs.get("preview")
        if not preview_path or not Path(preview_path).exists():
            raise HTTPException(404, "Preview file is missing")
        return FileResponse(preview_path, media_type="video/mp4", filename="preview.mp4")

    if format in {"vtt", "srt"}:
        subtitle_path = job.outputs.get(format)
        if not subtitle_path or not Path(subtitle_path).exists():
            raise HTTPException(404, f"{format.upper()} file is missing")
        media_type = "text/vtt" if format == "vtt" else "application/x-subrip"
        return FileResponse(subtitle_path, media_type=media_type, filename=f"subtitles.{format}")

    project_name = job.outputs.get("capcut_project")
    if not project_name:
        raise HTTPException(404, "CapCut project is missing")

    capcut_dir_str = job.outputs.get("capcut_dir") or settings.get("capcut", {}).get("project_dir", "")
    capcut_dir = Path(capcut_dir_str)
    project_dir = capcut_dir / project_name
    if not project_dir.exists():
        raise HTTPException(404, f"CapCut project directory is missing: {project_dir}")

    zip_path = project_dir.parent / f"{project_name}.zip"
    zip_capcut_project(project_dir, zip_path)
    return FileResponse(zip_path, media_type="application/zip", filename=f"{project_name}.zip")
