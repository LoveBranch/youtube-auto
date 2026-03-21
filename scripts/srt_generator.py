"""
대본 + 오디오 길이 기반 SRT 자막 생성 스크립트

문장을 최대 N자 이내로 분할하여 자막을 생성한다.
타이밍은 오디오 길이에 비례하여 분배한다.

사용법:
    py scripts/srt_generator.py <script.md> <audio_file> <output.srt> [--max-chars 15]
"""

import argparse
import re
import sys
import wave
from pathlib import Path


def get_audio_duration_seconds(audio_path: str) -> float:
    """오디오 파일의 길이를 초 단위로 반환한다."""
    path = Path(audio_path)
    ext = path.suffix.lower()

    if ext == ".wav":
        with wave.open(str(path), "rb") as wf:
            return wf.getnframes() / wf.getframerate()
    elif ext == ".mp3":
        from mutagen.mp3 import MP3
        return MP3(str(path)).info.length
    else:
        raise ValueError(f"지원하지 않는 형식: {ext}")


def extract_narration(md_text: str) -> str:
    """마크다운 대본에서 나레이션 텍스트를 추출한다."""
    lines = md_text.splitlines()
    narration_lines: list[str] = []

    for stripped_raw in lines:
        stripped = stripped_raw.strip()

        if re.match(r"^[-=*]{3,}$", stripped):
            continue
        if re.match(r"^##?\s*참고\s*자료", stripped):
            break
        if stripped.startswith("#"):
            continue
        if re.match(r"^-\s*\*\*.*\*\*\s*:", stripped):
            continue
        if re.match(r"^\(?\d+:\d+\s*~\s*\d+:\d+\)?$", stripped):
            continue
        if stripped == "":
            continue

        if stripped.startswith(">"):
            stripped = stripped.lstrip("> ").strip()

        stripped = re.sub(r"\*{1,2}([^*]+)\*{1,2}", r"\1", stripped)
        stripped = re.sub(r"^[-*]\s+", "", stripped)
        stripped = re.sub(r"^\d+\.\s+", "", stripped)

        if stripped:
            narration_lines.append(stripped)

    return "\n".join(narration_lines)


def split_to_chunks(text: str, max_chars: int) -> list[str]:
    """텍스트를 max_chars 이내로 자연스럽게 분할한다.

    분할 우선순위: 쉼표/마침표 뒤 > 공백 > 강제 분할
    """
    if len(text) <= max_chars:
        return [text]

    chunks: list[str] = []
    remaining = text

    while remaining:
        if len(remaining) <= max_chars:
            chunks.append(remaining)
            break

        # max_chars 범위 내에서 가장 좋은 분할 지점 찾기
        best = -1
        # 쉼표/마침표 뒤 공백 우선
        for i in range(min(max_chars, len(remaining)), 0, -1):
            if i < len(remaining) and remaining[i] == " ":
                best = i
                break
            if remaining[i - 1] in ",，.。!?":
                best = i
                break

        if best <= 0:
            # 자연 분할점 없으면 강제 분할
            best = max_chars

        chunk = remaining[:best].rstrip()
        if chunk:
            chunks.append(chunk)
        remaining = remaining[best:].lstrip()

    return [c for c in chunks if c]


def split_narration_to_sentences(narration: str) -> list[str]:
    """나레이션을 문장 단위로 분리한다."""
    sentences: list[str] = []
    for line in narration.splitlines():
        line = line.strip()
        if not line:
            continue
        # 문장 종결 부호로 분리
        parts = re.split(r"(?<=[.!?。])\s+", line)
        for p in parts:
            p = p.strip()
            if p:
                sentences.append(p)
    return sentences


def format_timestamp(seconds: float) -> str:
    """초를 SRT 타임스탬프로 변환한다."""
    hrs = int(seconds // 3600)
    mins = int((seconds % 3600) // 60)
    secs = int(seconds % 60)
    millis = int((seconds - int(seconds)) * 1000)
    return f"{hrs:02d}:{mins:02d}:{secs:02d},{millis:03d}"


def generate_srt(narration: str, audio_duration: float, max_chars: int) -> str:
    """나레이션에서 SRT 자막을 생성한다.

    1. 문장 단위로 분리
    2. 각 문장을 max_chars 이내 청크로 분할
    3. 오디오 길이에 비례하여 타이밍 배분
    """
    sentences = split_narration_to_sentences(narration)

    # 전체 글자 수 (타이밍 비례 배분용)
    total_chars = sum(len(s) for s in sentences)
    if total_chars == 0:
        return ""

    srt_entries: list[str] = []
    current_time = 0.0
    index = 1

    for sentence in sentences:
        # 이 문장의 비례 시간
        sentence_duration = (len(sentence) / total_chars) * audio_duration

        # 문장을 표시용 청크로 분할
        chunks = split_to_chunks(sentence, max_chars)
        chunk_total_chars = sum(len(c) for c in chunks)
        if chunk_total_chars == 0:
            continue

        for chunk in chunks:
            chunk_duration = (len(chunk) / chunk_total_chars) * sentence_duration
            # 최소 0.3초 보장
            chunk_duration = max(chunk_duration, 0.3)

            start = current_time
            end = current_time + chunk_duration

            srt_entries.append(
                f"{index}\n{format_timestamp(start)} --> {format_timestamp(end)}\n{chunk}"
            )
            index += 1
            current_time = end

    return "\n\n".join(srt_entries) + "\n"


def main() -> None:
    parser = argparse.ArgumentParser(description="대본 + 오디오에서 SRT 자막 생성")
    parser.add_argument("script", help="마크다운 대본 파일")
    parser.add_argument("audio", help="오디오 파일 (WAV/MP3)")
    parser.add_argument("output", help="출력 SRT 파일")
    parser.add_argument(
        "--max-chars", type=int, default=15, help="자막 한 줄 최대 글자 수 (기본: 15)"
    )
    args = parser.parse_args()

    script_path = Path(args.script)
    audio_path = Path(args.audio)

    if not script_path.exists():
        print(f"오류: {script_path} 없음", file=sys.stderr)
        sys.exit(1)
    if not audio_path.exists():
        print(f"오류: {audio_path} 없음", file=sys.stderr)
        sys.exit(1)

    md_text = script_path.read_text(encoding="utf-8")
    narration = extract_narration(md_text)
    audio_duration = get_audio_duration_seconds(str(audio_path))

    print(f"오디오 길이: {audio_duration:.1f}초")
    print(f"나레이션: {len(narration)}자")
    print(f"최대 자막 길이: {args.max_chars}자")

    srt_content = generate_srt(narration, audio_duration, args.max_chars)

    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(srt_content, encoding="utf-8")

    count = srt_content.count("\n\n") + 1
    print(f"완료: {output_path} ({count}개 자막)")


if __name__ == "__main__":
    main()
