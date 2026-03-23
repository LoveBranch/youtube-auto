"""TTS 미리듣기 API - gTTS 사용 (무료, 무제한, 클라우드 서버 지원)"""

from fastapi import APIRouter
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
import asyncio
import io

router = APIRouter()


class TTSRequest(BaseModel):
    text: str
    voice: str = "SunHi"
    language: str = "ko"


@router.post("/tts-preview")
async def tts_preview(req: TTSRequest):
    from gtts import gTTS

    lang_code = (req.language or 'ko').split('-')[0]

    def generate() -> bytes:
        tts = gTTS(text=req.text, lang=lang_code)
        buf = io.BytesIO()
        tts.write_to_fp(buf)
        buf.seek(0)
        return buf.read()

    audio_bytes = await asyncio.to_thread(generate)

    return StreamingResponse(
        io.BytesIO(audio_bytes),
        media_type="audio/mpeg",
        headers={"Content-Disposition": "inline; filename=preview.mp3"},
    )
