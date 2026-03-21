"""
Whisper 기반 SRT 자막 생성 스크립트

오디오 파일을 Whisper로 분석하여 실제 음성 타이밍에 맞는 자막을 생성한다.

사용법:
    py scripts/whisper_srt.py <audio_file> <output.srt> [--max-chars 15] [--model base] [--lang ko]
"""

import argparse
import sys
from pathlib import Path


def split_segment_text(text: str, max_chars: int, start: float, end: float) -> list[dict]:
    """긴 세그먼트를 max_chars 이내로 분할하고 시간을 비례 배분한다."""
    text = text.strip()
    if not text:
        return []

    if len(text) <= max_chars:
        return [{"start": start, "end": end, "text": text}]

    chunks: list[str] = []
    remaining = text

    while remaining:
        if len(remaining) <= max_chars:
            chunks.append(remaining)
            break

        best = -1
        search_end = min(max_chars, len(remaining))
        for i in range(search_end, 0, -1):
            if i < len(remaining) and remaining[i] == " ":
                best = i
                break
            if remaining[i - 1] in ",，.。!?!？":
                best = i
                break

        if best <= 0:
            best = max_chars

        chunk = remaining[:best].rstrip()
        if chunk:
            chunks.append(chunk)
        remaining = remaining[best:].lstrip()

    chunks = [c for c in chunks if c]
    if not chunks:
        return []

    total_chars = sum(len(c) for c in chunks)
    duration = end - start
    results = []
    current = start

    for chunk in chunks:
        chunk_dur = (len(chunk) / total_chars) * duration
        chunk_dur = max(chunk_dur, 0.2)
        results.append({
            "start": current,
            "end": current + chunk_dur,
            "text": chunk,
        })
        current += chunk_dur

    return results


def format_timestamp(seconds: float) -> str:
    """초를 SRT 타임스탬프로 변환한다."""
    hrs = int(seconds // 3600)
    mins = int((seconds % 3600) // 60)
    secs = int(seconds % 60)
    millis = int((seconds - int(seconds)) * 1000)
    return f"{hrs:02d}:{mins:02d}:{secs:02d},{millis:03d}"


def generate_srt_from_whisper(audio_path: str, max_chars: int, model_name: str, language: str | None) -> str:
    """Whisper로 오디오를 분석하여 SRT 자막을 생성한다."""
    try:
        import whisper
    except ImportError:
        print("오류: openai-whisper 패키지가 필요합니다.", file=sys.stderr)
        print("  pip install openai-whisper", file=sys.stderr)
        sys.exit(1)

    print(f"Whisper 모델 로딩: {model_name}")
    model = whisper.load_model(model_name)

    print("오디오 분석 중...")
    transcribe_opts = {
        "verbose": False,
        "word_timestamps": True,
    }
    if language:
        transcribe_opts["language"] = language

    result = model.transcribe(audio_path, **transcribe_opts)

    detected_lang = result.get("language", "unknown")
    print(f"감지된 언어: {detected_lang}")

    all_chunks: list[dict] = []

    for segment in result.get("segments", []):
        # word-level timestamps가 있으면 활용
        words = segment.get("words", [])
        if words:
            # 단어들을 max_chars 이내로 그룹핑
            current_text = ""
            current_start = words[0].get("start", segment["start"])
            current_end = current_start

            for word_info in words:
                word = word_info.get("word", "").strip()
                if not word:
                    continue

                candidate = (current_text + " " + word).strip() if current_text else word

                if len(candidate) > max_chars and current_text:
                    all_chunks.append({
                        "start": current_start,
                        "end": current_end,
                        "text": current_text,
                    })
                    current_text = word
                    current_start = word_info.get("start", current_end)
                    current_end = word_info.get("end", current_start)
                else:
                    current_text = candidate
                    current_end = word_info.get("end", current_end)

            if current_text:
                all_chunks.append({
                    "start": current_start,
                    "end": current_end,
                    "text": current_text,
                })
        else:
            # word timestamps 없으면 segment 단위로 분할
            sub_chunks = split_segment_text(
                segment["text"], max_chars, segment["start"], segment["end"]
            )
            all_chunks.extend(sub_chunks)

    # SRT 생성
    srt_entries: list[str] = []
    for i, chunk in enumerate(all_chunks, 1):
        start_ts = format_timestamp(chunk["start"])
        end_ts = format_timestamp(chunk["end"])
        srt_entries.append(f"{i}\n{start_ts} --> {end_ts}\n{chunk['text']}")

    return "\n\n".join(srt_entries) + "\n"


def main() -> None:
    parser = argparse.ArgumentParser(description="Whisper 기반 SRT 자막 생성")
    parser.add_argument("audio", help="오디오 파일 (WAV/MP3)")
    parser.add_argument("output", help="출력 SRT 파일")
    parser.add_argument(
        "--max-chars", type=int, default=15, help="자막 한 줄 최대 글자 수 (기본: 15)"
    )
    parser.add_argument(
        "--model", default="base", help="Whisper 모델 (tiny/base/small/medium/large, 기본: base)"
    )
    parser.add_argument(
        "--lang", default=None, help="언어 코드 (미지정 시 자동 감지)"
    )
    args = parser.parse_args()

    audio_path = Path(args.audio)
    if not audio_path.exists():
        print(f"오류: {audio_path} 없음", file=sys.stderr)
        sys.exit(1)

    srt_content = generate_srt_from_whisper(
        str(audio_path), args.max_chars, args.model, args.lang
    )

    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(srt_content, encoding="utf-8")

    count = srt_content.count("\n\n") + 1 if srt_content.strip() else 0
    print(f"완료: {output_path} ({count}개 자막)")


if __name__ == "__main__":
    main()
