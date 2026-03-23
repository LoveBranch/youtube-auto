"""결과물 다운로드 API."""

from pathlib import Path
from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import FileResponse
from server.jobs import get_job
from server.utils.zip_export import zip_capcut_project
from server.config import settings

router = APIRouter()


@router.get("/download/{job_id}")
async def download_result(job_id: str, format: str = Query("mp4", pattern="^(mp4|capcut|preview)$")):
    job = get_job(job_id)
    if not job:
        raise HTTPException(404, "작업을 찾을 수 없습니다")
    if job.status != "completed":
        raise HTTPException(400, f"작업이 아직 완료되지 않았습니다: {job.status}")

    if format == "mp4":
        mp4_path = job.outputs.get("mp4")
        if not mp4_path or not Path(mp4_path).exists():
            raise HTTPException(404, "MP4 파일이 없습니다")
        return FileResponse(mp4_path, media_type="video/mp4", filename="video.mp4")

    elif format == "preview":
        preview_path = job.outputs.get("preview")
        if not preview_path or not Path(preview_path).exists():
            raise HTTPException(404, "미리보기 파일이 없습니다")
        return FileResponse(preview_path, media_type="video/mp4", filename="preview.mp4")

    elif format == "capcut":
        project_name = job.outputs.get("capcut_project")
        if not project_name:
            raise HTTPException(404, "CapCut 프로젝트가 없습니다")
        # Use saved capcut_dir from job outputs, fall back to settings
        capcut_dir_str = job.outputs.get("capcut_dir") or settings.get("capcut", {}).get("project_dir", "")
        capcut_dir = Path(capcut_dir_str)
        project_dir = capcut_dir / project_name
        if not project_dir.exists():
            raise HTTPException(404, f"CapCut 프로젝트 폴더가 없습니다: {project_dir}")
        zip_path = project_dir.parent / f"{project_name}.zip"
        zip_capcut_project(project_dir, zip_path)
        return FileResponse(zip_path, media_type="application/zip", filename=f"{project_name}.zip")
