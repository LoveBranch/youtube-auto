"""TTS 미리듣기 API - Edge TTS 사용 (무료, 무제한)"""

from fastapi import APIRouter
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
import io
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / "scripts"))

router = APIRouter()


class TTSRequest(BaseModel):
    text: str
    voice: str = "Kore"
    language: str = "ko"


@router.post("/tts-preview")
async def tts_preview(req: TTSRequest):
    from tts import call_edge_tts
    import tempfile, os

    with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as f:
        tmp_path = f.name

    try:
        await call_edge_tts(req.text, req.voice, req.language, tmp_path)
        audio_bytes = open(tmp_path, "rb").read()
    finally:
        os.unlink(tmp_path)

    return StreamingResponse(
        io.BytesIO(audio_bytes),
        media_type="audio/mpeg",
        headers={"Content-Disposition": "inline; filename=preview.mp3"},
    )
