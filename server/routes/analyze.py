"""스타일 분석 + 텍스트 추출 API."""

import asyncio
import tempfile
from pathlib import Path

from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from server.models import AnalyzeStyleRequest
from server.pipeline.style_analyzer import analyze_style

router = APIRouter()


@router.post("/analyze-style")
async def analyze_video_style(
    url: str | None = Form(None),
    language: str = Form("ko"),
    file: UploadFile | None = File(None),
):
    """소스 영상/URL의 스타일을 분석한다. URL 또는 파일 업로드 둘 다 지원."""
    if file:
        suffix = Path(file.filename or "video.mp4").suffix or ".mp4"
        with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
            tmp.write(await file.read())
            tmp_path = Path(tmp.name)
        try:
            result = await asyncio.to_thread(analyze_style, video_path=tmp_path, language=language)
        finally:
            tmp_path.unlink(missing_ok=True)
        return result
    else:
        result = await asyncio.to_thread(analyze_style, url=url, language=language)
        return result


@router.post("/extract-text")
async def extract_text(file: UploadFile = File(...)):
    """PDF/DOCX/TXT 파일에서 텍스트를 추출한다."""
    filename = file.filename or ""
    ext = Path(filename).suffix.lower()
    content = await file.read()

    if ext in (".txt", ".md"):
        try:
            text = content.decode("utf-8")
        except UnicodeDecodeError:
            text = content.decode("cp949", errors="replace")
        return {"text": text, "chars": len(text)}

    if ext == ".pdf":
        try:
            import io
            from pypdf import PdfReader
            reader = PdfReader(io.BytesIO(content))
            pages = [page.extract_text() or "" for page in reader.pages]
            text = "\n\n".join(pages).strip()
            return {"text": text, "chars": len(text)}
        except Exception as e:
            raise HTTPException(status_code=422, detail=f"PDF 추출 실패: {e}")

    if ext in (".docx",):
        try:
            import io
            from docx import Document
            doc = Document(io.BytesIO(content))
            text = "\n".join(p.text for p in doc.paragraphs if p.text.strip())
            return {"text": text, "chars": len(text)}
        except Exception as e:
            raise HTTPException(status_code=422, detail=f"DOCX 추출 실패: {e}")

    raise HTTPException(status_code=415, detail=f"지원하지 않는 파일 형식: {ext}")
