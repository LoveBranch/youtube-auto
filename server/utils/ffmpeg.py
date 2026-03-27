"""ffmpeg 유틸리티 함수."""

import subprocess
import tempfile
from pathlib import Path


def composite_final_video(
    scenes_dir: Path,
    audio_path: Path,
    srt_path: Path,
    output_path: Path,
    aspect_ratio: str = "16:9",
) -> Path:
    """씬 영상들 + 오디오 + 자막을 하나의 MP4로 합성한다."""

    resolutions = {"16:9": (1280, 720), "9:16": (720, 1280), "1:1": (720, 720)}
    w, h = resolutions.get(aspect_ratio, (1280, 720))

    # 씬 영상 목록 수집 (정렬)
    scene_videos = sorted(scenes_dir.glob("scene_*.mp4"))
    if not scene_videos:
        raise FileNotFoundError(f"씬 영상이 없습니다: {scenes_dir}")

    # ffmpeg concat 파일 생성
    with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False, encoding="utf-8") as f:
        for v in scene_videos:
            f.write(f"file '{v.as_posix()}'\n")
        concat_file = f.name

    try:
        # 1단계: 씬 영상 합치기 (스트림 복사 — 재인코딩 없이 메모리 절약)
        concat_path = output_path.with_suffix(".concat.mp4")
        r1 = subprocess.run(
            [
                "ffmpeg", "-y", "-f", "concat", "-safe", "0",
                "-i", concat_file,
                "-c:v", "copy", "-c:a", "copy",
                str(concat_path),
            ],
            capture_output=True, timeout=300,
        )
        if r1.returncode != 0:
            raise RuntimeError(f"ffmpeg concat 실패 (exit {r1.returncode}): {r1.stderr.decode(errors='ignore')[-500:]}")

        # 2단계: 오디오 + 자막 합성 (720p + 저메모리 설정으로 OOM 방지)
        srt_path_posix = srt_path.as_posix()
        r2 = subprocess.run(
            [
                "ffmpeg", "-y",
                "-threads", "1",
                "-i", str(concat_path),
                "-i", str(audio_path),
                "-vf", (
                    f"scale={w}:{h}:force_original_aspect_ratio=decrease,"
                    f"pad={w}:{h}:(ow-iw)/2:(oh-ih)/2,"
                    f"subtitles='{srt_path_posix}':force_style='FontSize=18,PrimaryColour=&HFFFFFF,OutlineColour=&H000000,Outline=2,Alignment=2'"
                ),
                "-c:v", "libx264", "-preset", "ultrafast", "-crf", "23",
                "-c:a", "aac", "-b:a", "128k",
                "-map", "0:v:0", "-map", "1:a:0",
                "-pix_fmt", "yuv420p",
                str(output_path),
            ],
            capture_output=True, timeout=600,
        )
        if r2.returncode != 0:
            raise RuntimeError(f"ffmpeg 합성 실패 (exit {r2.returncode}): {r2.stderr.decode(errors='ignore')[-500:]}")

        # 임시 파일 정리
        concat_path.unlink(missing_ok=True)

    finally:
        Path(concat_file).unlink(missing_ok=True)

    return output_path


def generate_preview(input_path: Path, output_path: Path, max_height: int = 480) -> Path:
    """저해상도 미리보기 영상을 생성한다."""
    r = subprocess.run(
        [
            "ffmpeg", "-y",
            "-threads", "1",
            "-i", str(input_path),
            "-vf", f"scale=-2:{max_height}",
            "-c:v", "libx264", "-preset", "ultrafast", "-crf", "30",
            "-c:a", "aac", "-b:a", "64k",
            str(output_path),
        ],
        capture_output=True, timeout=600,
    )
    if r.returncode != 0:
        raise RuntimeError(f"ffmpeg preview 실패 (exit {r.returncode}): {r.stderr.decode(errors='ignore')[-300:]}")
    return output_path
