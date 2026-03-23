"""TTS 미리듣기 API - Gemini TTS 사용 (짧은 샘플만)"""

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
    import asyncio
    from tts import call_gemini_tts, load_settings

    settings = load_settings()
    api_key = settings.get("tts", {}).get("api_key", "")
    if not api_key:
        from fastapi import HTTPException
        raise HTTPException(status_code=500, detail="TTS API key not configured")

    # 짧은 샘플만 — quota 절약
    MAX_CHARS = 60
    text = req.text[:MAX_CHARS]

    audio_bytes, sample_rate = await asyncio.to_thread(
        call_gemini_tts, text, req.voice, req.language, api_key
    )

    # PCM raw → WAV
    import wave, io as _io
    wav_buf = _io.BytesIO()
    with wave.open(wav_buf, "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(sample_rate)
        wf.writeframes(audio_bytes)
    wav_buf.seek(0)

    return StreamingResponse(
        wav_buf,
        media_type="audio/wav",
        headers={"Content-Disposition": "inline; filename=preview.wav"},
    )
