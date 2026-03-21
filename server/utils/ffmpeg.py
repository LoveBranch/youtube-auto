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

    resolutions = {"16:9": (1920, 1080), "9:16": (1080, 1920), "1:1": (1080, 1080)}
    w, h = resolutions.get(aspect_ratio, (1920, 1080))

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
        # 1단계: 씬 영상 합치기
        concat_path = output_path.with_suffix(".concat.mp4")
        subprocess.run(
            [
                "ffmpeg", "-y", "-f", "concat", "-safe", "0",
                "-i", concat_file,
                "-c:v", "libx264", "-crf", "23",
                "-pix_fmt", "yuv420p",
                "-vf", f"scale={w}:{h}:force_original_aspect_ratio=decrease,pad={w}:{h}:(ow-iw)/2:(oh-ih)/2",
                str(concat_path),
            ],
            capture_output=True, timeout=300,
        )

        # 2단계: 오디오 + 자막 합성
        srt_path_posix = srt_path.as_posix()
        subprocess.run(
            [
                "ffmpeg", "-y",
                "-i", str(concat_path),
                "-i", str(audio_path),
                "-vf", f"subtitles='{srt_path_posix}':force_style='FontSize=22,PrimaryColour=&HFFFFFF,OutlineColour=&H000000,Outline=2,Alignment=2'",
                "-c:v", "libx264", "-crf", "23",
                "-c:a", "aac", "-b:a", "128k",
                "-shortest",
                "-pix_fmt", "yuv420p",
                str(output_path),
            ],
            capture_output=True, timeout=300,
        )

        # 임시 파일 정리
        concat_path.unlink(missing_ok=True)

    finally:
        Path(concat_file).unlink(missing_ok=True)

    return output_path


def generate_preview(input_path: Path, output_path: Path, max_height: int = 480) -> Path:
    """저해상도 미리보기 영상을 생성한다."""
    subprocess.run(
        [
            "ffmpeg", "-y", "-i", str(input_path),
            "-vf", f"scale=-2:{max_height}",
            "-c:v", "libx264", "-crf", "30",
            "-c:a", "aac", "-b:a", "64k",
            str(output_path),
        ],
        capture_output=True, timeout=300,
    )
    return output_path
