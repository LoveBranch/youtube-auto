"""Make from Clips pipeline: align script to audio, then render a clip-based timeline with FFmpeg."""

from __future__ import annotations

import asyncio
import json
import math
import random
import re
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path

from server.config import BASE_DIR
from server.jobs import Job, complete_job, complete_phase, fail_job, update_phase
from server.utils.ffmpeg import generate_preview

sys.path.insert(0, str(BASE_DIR / "scripts"))

from gemini_srt import generate_srt_with_gemini, load_settings  # type: ignore

FPS = 30
MAX_DURATION_SEC = 180
SUPPORTED_SUBTITLE_FORMATS = {"vtt", "vtt+srt"}
VISUAL_MOTION_EFFECTS = [
    "zoom_in",
    "zoom_out",
    "pan_left",
    "pan_right",
    "tilt_up",
    "tilt_down",
    "drift",
    "push_in",
    "push_out",
]


@dataclass
class SubtitleSegment:
    index: int
    start_sec: float
    end_sec: float
    text: str


@dataclass
class ClipAsset:
    name: str
    path: Path
    category: str


def split_script_into_sentences(script: str) -> list[str]:
    return [
        sentence.strip()
        for block in re.split(r"\n+", script)
        for sentence in re.split(r"(?<=[.!?])\s+", block)
        if sentence.strip()
    ]


def normalize_text(text: str) -> str:
    lowered = text.lower()
    lowered = re.sub(r"[^\w\s가-힣]", " ", lowered)
    lowered = re.sub(r"\s+", " ", lowered)
    return lowered.strip()


def parse_srt_timestamp(value: str) -> float:
    hours, minutes, rest = value.split(":")
    seconds, millis = re.split(r"[,.]", rest)
    return (
        int(hours) * 3600
        + int(minutes) * 60
        + int(seconds)
        + int(millis) / 1000
    )


def format_srt_timestamp(seconds: float) -> str:
    safe = max(0.0, seconds)
    hours = int(safe // 3600)
    minutes = int((safe % 3600) // 60)
    secs = int(safe % 60)
    millis = int(round((safe - math.floor(safe)) * 1000))
    return f"{hours:02d}:{minutes:02d}:{secs:02d},{millis:03d}"


def format_vtt_timestamp(seconds: float) -> str:
    return format_srt_timestamp(seconds).replace(",", ".")


def parse_srt_content(srt_text: str) -> list[SubtitleSegment]:
    segments: list[SubtitleSegment] = []
    blocks = re.split(r"\n\s*\n", srt_text.strip())
    for block in blocks:
        lines = [line.strip() for line in block.splitlines() if line.strip()]
        if len(lines) < 3 or "-->" not in lines[1]:
            continue
        start_raw, end_raw = [part.strip() for part in lines[1].split("-->")]
        text = " ".join(lines[2:]).strip()
        if not text:
            continue
        segments.append(
            SubtitleSegment(
                index=len(segments) + 1,
                start_sec=parse_srt_timestamp(start_raw),
                end_sec=parse_srt_timestamp(end_raw),
                text=text,
            )
        )
    return segments


def infer_sentence_category(index: int, total: int) -> str:
    if index == 0:
        return "intro"
    if index == total - 1:
        return "outro"
    return "main"


def align_script_to_segments(script: str, subtitle_segments: list[SubtitleSegment]) -> list[dict]:
    script_sentences = split_script_into_sentences(script)
    if not script_sentences:
        return []
    if not subtitle_segments:
        total = len(script_sentences)
        return [
            {
                "slotId": f"slot_{index + 1:02d}",
                "sentenceIndex": index,
                "category": infer_sentence_category(index, total),
                "text": sentence,
                "startSec": float(index),
                "endSec": float(index + 1),
                "durationSec": 1.0,
            }
            for index, sentence in enumerate(script_sentences)
        ]

    sentence_weights = [max(1, len(normalize_text(sentence).replace(" ", ""))) for sentence in script_sentences]
    total_sentence_weight = sum(sentence_weights)

    subtitle_weights = [max(1, len(normalize_text(segment.text).replace(" ", ""))) for segment in subtitle_segments]
    total_subtitle_weight = sum(subtitle_weights)
    cumulative_subtitle = []
    running = 0
    for weight in subtitle_weights:
        running += weight
        cumulative_subtitle.append(running)

    aligned: list[dict] = []
    cursor = 0
    consumed_weight = 0

    for sentence_index, sentence in enumerate(script_sentences):
        consumed_weight += sentence_weights[sentence_index]
        target_weight = total_subtitle_weight * (consumed_weight / total_sentence_weight)
        start_idx = cursor
        while cursor < len(subtitle_segments) - 1 and cumulative_subtitle[cursor] < target_weight:
            cursor += 1
        end_idx = max(start_idx, cursor)
        start_segment = subtitle_segments[start_idx]
        end_segment = subtitle_segments[end_idx]
        total = len(script_sentences)
        aligned.append(
            {
                "slotId": f"slot_{sentence_index + 1:02d}",
                "sentenceIndex": sentence_index,
                "category": infer_sentence_category(sentence_index, total),
                "text": sentence,
                "startSec": round(start_segment.start_sec, 3),
                "endSec": round(end_segment.end_sec, 3),
                "durationSec": round(max(0.2, end_segment.end_sec - start_segment.start_sec), 3),
            }
        )
        cursor = min(end_idx + 1, len(subtitle_segments) - 1)

    if aligned:
        aligned[-1]["endSec"] = round(subtitle_segments[-1].end_sec, 3)
        aligned[-1]["durationSec"] = round(
            max(0.2, aligned[-1]["endSec"] - aligned[-1]["startSec"]),
            3,
        )

    return aligned


def build_srt_from_aligned_segments(aligned_segments: list[dict]) -> str:
    chunks = []
    for index, segment in enumerate(aligned_segments, start=1):
        chunks.append(
            "\n".join(
                [
                    str(index),
                    f"{format_srt_timestamp(segment['startSec'])} --> {format_srt_timestamp(segment['endSec'])}",
                    str(segment["text"]).strip(),
                ]
            )
        )
    return "\n\n".join(chunks) + ("\n" if chunks else "")


def build_vtt_from_aligned_segments(aligned_segments: list[dict]) -> str:
    rows = ["WEBVTT", ""]
    for segment in aligned_segments:
        rows.extend(
            [
                f"{format_vtt_timestamp(segment['startSec'])} --> {format_vtt_timestamp(segment['endSec'])}",
                str(segment["text"]).strip(),
                "",
            ]
        )
    return "\n".join(rows).rstrip() + "\n"


def get_video_duration(path: Path) -> float:
    result = subprocess.run(
        ["ffprobe", "-v", "quiet", "-print_format", "json", "-show_streams", str(path)],
        capture_output=True,
        text=True,
        timeout=30,
    )
    try:
        data = json.loads(result.stdout)
        for stream in data.get("streams", []):
            if stream.get("codec_type") == "video" and "duration" in stream:
                return float(stream["duration"])
    except Exception:
        pass
    return 0.0


def get_aspect_resolution(aspect_ratio: str) -> tuple[int, int]:
    return {
        "16:9": (1280, 720),
        "9:16": (720, 1280),
        "1:1": (720, 720),
    }.get(aspect_ratio, (1280, 720))


def pick_clip_for_segment(segment: dict, clip_assets: list[ClipAsset], recent_names: list[str]) -> ClipAsset:
    category = str(segment.get("category", "main"))
    exact_pool = [clip for clip in clip_assets if clip.category == category]
    pool = exact_pool or clip_assets
    preferred = [clip for clip in pool if clip.name not in recent_names]
    final_pool = preferred or pool
    return random.choice(final_pool)


def get_motion_crop_filter(effect_id: str, width: int, height: int, duration_sec: float) -> str:
    safe_duration = max(duration_sec, 0.2)
    ratio = f"{width}/{height}"
    padded_w = int(width * 1.18)
    padded_h = int(height * 1.18)
    base_scale = (
        f"scale=w='if(gte(iw/ih,{ratio}),-2,{padded_w})':"
        f"h='if(gte(iw/ih,{ratio}),{padded_h},-2)'"
    )

    if effect_id in {"zoom_in", "push_in"}:
        crop = (
            f"crop=w='max({width},iw*(1-0.08*min(1,t/{safe_duration})))':"
            f"h='max({height},ih*(1-0.08*min(1,t/{safe_duration})))':"
            f"x='(in_w-out_w)/2':y='(in_h-out_h)/2',"
            f"scale={width}:{height}"
        )
        return f"{base_scale},{crop}"

    if effect_id in {"zoom_out", "push_out"}:
        crop = (
            f"crop=w='max({width},iw*(0.92+0.08*min(1,t/{safe_duration})))':"
            f"h='max({height},ih*(0.92+0.08*min(1,t/{safe_duration})))':"
            f"x='(in_w-out_w)/2':y='(in_h-out_h)/2',"
            f"scale={width}:{height}"
        )
        return f"{base_scale},{crop}"

    if effect_id == "pan_left":
        return f"{base_scale},crop={width}:{height}:x='(in_w-out_w)*(1-min(1,t/{safe_duration}))':y='(in_h-out_h)/2'"

    if effect_id == "pan_right":
        return f"{base_scale},crop={width}:{height}:x='(in_w-out_w)*min(1,t/{safe_duration})':y='(in_h-out_h)/2'"

    if effect_id == "tilt_up":
        return f"{base_scale},crop={width}:{height}:x='(in_w-out_w)/2':y='(in_h-out_h)*(1-min(1,t/{safe_duration}))'"

    if effect_id == "tilt_down":
        return f"{base_scale},crop={width}:{height}:x='(in_w-out_w)/2':y='(in_h-out_h)*min(1,t/{safe_duration})'"

    if effect_id == "drift":
        return (
            f"{base_scale},crop={width}:{height}:"
            f"x='(in_w-out_w)/2 + (in_w-out_w)*0.12*sin(2*PI*t/{safe_duration})':"
            f"y='(in_h-out_h)/2 + (in_h-out_h)*0.08*cos(2*PI*t/{safe_duration})'"
        )

    return f"{base_scale},crop={width}:{height}:x='(in_w-out_w)/2':y='(in_h-out_h)/2'"


def render_clip_slot(
    clip_path: Path,
    output_path: Path,
    *,
    target_duration_sec: float,
    aspect_ratio: str,
    motion_effect: str,
) -> None:
    width, height = get_aspect_resolution(aspect_ratio)
    source_duration = max(0.1, get_video_duration(clip_path))
    safe_target = max(target_duration_sec, 0.2)
    duration_ratio = source_duration / safe_target
    effective_motion = motion_effect
    speed = 1.0
    hold_duration = 0.0

    # When the clip already fits the slot, vary the treatment so exports do not
    # feel mechanically identical across different users.
    if 0.9 <= duration_ratio <= 1.1:
        strategy = random.choice(["trim", "slowdown", "freeze_tail", "motion"])
        if strategy == "slowdown":
            speed = random.uniform(0.88, 0.97)
        elif strategy == "freeze_tail":
            speed = random.uniform(0.97, 1.01)
            hold_duration = random.uniform(0.18, 0.55)
        elif strategy == "motion":
            effective_motion = random.choice(VISUAL_MOTION_EFFECTS)
            speed = random.uniform(0.96, 1.02)
        else:
            speed = random.uniform(0.98, 1.03)
    elif source_duration < safe_target:
        slowdown_factor = max(0.8, source_duration / safe_target)
        speed = min(random.uniform(0.9, 0.98), slowdown_factor)
    else:
        speed = random.uniform(0.96, 1.04)

    post_speed_duration = source_duration / speed
    hold_duration = max(hold_duration, target_duration_sec - post_speed_duration)
    motion_filter = get_motion_crop_filter(effective_motion, width, height, target_duration_sec)
    filter_chain = (
        f"{motion_filter},"
        f"setpts=PTS/{speed},"
        f"tpad=stop_mode=clone:stop_duration={hold_duration:.3f},"
        f"trim=duration={target_duration_sec:.3f},"
        f"fps={FPS},format=yuv420p"
    )

    result = subprocess.run(
        [
            "ffmpeg",
            "-y",
            "-i",
            str(clip_path),
            "-an",
            "-vf",
            filter_chain,
            "-c:v",
            "libx264",
            "-preset",
            "ultrafast",
            "-crf",
            "23",
            str(output_path),
        ],
        capture_output=True,
        timeout=600,
    )
    if result.returncode != 0:
        raise RuntimeError(result.stderr.decode(errors="ignore")[-600:])


def mux_video_with_audio(
    slot_paths: list[Path],
    audio_path: Path,
    output_path: Path,
) -> None:
    with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False, encoding="utf-8") as handle:
        for path in slot_paths:
            handle.write(f"file '{path.as_posix()}'\n")
        concat_path = Path(handle.name)

    concat_output = output_path.with_suffix(".concat.mp4")
    try:
        concat_result = subprocess.run(
            [
                "ffmpeg",
                "-y",
                "-f",
                "concat",
                "-safe",
                "0",
                "-i",
                str(concat_path),
                "-c:v",
                "copy",
                "-an",
                str(concat_output),
            ],
            capture_output=True,
            timeout=600,
        )
        if concat_result.returncode != 0:
            raise RuntimeError(concat_result.stderr.decode(errors="ignore")[-600:])

        mux_result = subprocess.run(
            [
                "ffmpeg",
                "-y",
                "-i",
                str(concat_output),
                "-i",
                str(audio_path),
                "-map",
                "0:v:0",
                "-map",
                "1:a:0",
                "-c:v",
                "copy",
                "-c:a",
                "aac",
                "-b:a",
                "192k",
                "-shortest",
                str(output_path),
            ],
            capture_output=True,
            timeout=600,
        )
        if mux_result.returncode != 0:
            raise RuntimeError(mux_result.stderr.decode(errors="ignore")[-600:])
    finally:
        concat_path.unlink(missing_ok=True)
        concat_output.unlink(missing_ok=True)


async def analyze_make_from_clips_audio(
    *,
    audio_path: Path,
    script: str,
    language: str,
) -> dict:
    settings = load_settings()
    api_key = settings.get("tts", {}).get("api_key", "")
    if not api_key:
        raise RuntimeError("Gemini API key is missing in pipeline settings.")

    raw_srt = await asyncio.to_thread(generate_srt_with_gemini, str(audio_path), 42, language, api_key)
    subtitle_segments = parse_srt_content(raw_srt)
    aligned_segments = align_script_to_segments(script, subtitle_segments)
    aligned_srt = build_srt_from_aligned_segments(aligned_segments)
    aligned_vtt = build_vtt_from_aligned_segments(aligned_segments)
    total_duration = round(aligned_segments[-1]["endSec"], 3) if aligned_segments else 0.0

    return {
        "segments": aligned_segments,
        "subtitle_segments": [
            {
                "index": segment.index,
                "startSec": round(segment.start_sec, 3),
                "endSec": round(segment.end_sec, 3),
                "text": segment.text,
            }
            for segment in subtitle_segments
        ],
        "srt": aligned_srt,
        "vtt": aligned_vtt,
        "totalDurationSec": total_duration,
        "alignmentMode": "gemini_srt_sentence_alignment",
    }


async def run_make_from_clips_pipeline(
    *,
    job: Job,
    audio_path: Path,
    script: str,
    language: str,
    subtitle_format: str,
    aspect_ratio: str,
    primary_motion: str,
    aligned_segments: list[dict],
    clip_assets: list[ClipAsset],
) -> None:
    try:
        output_dir = audio_path.parent / f"make_from_clips_{job.job_id}"
        output_dir.mkdir(parents=True, exist_ok=True)

        update_phase(job, "slot_render", 0.0)
        slot_paths: list[Path] = []
        recent_names: list[str] = []

        for index, segment in enumerate(aligned_segments):
            update_phase(job, "slot_render", index / max(len(aligned_segments), 1))
            clip = pick_clip_for_segment(segment, clip_assets, recent_names)
            recent_names.append(clip.name)
            if len(recent_names) > 4:
                recent_names.pop(0)
            slot_output = output_dir / f"slot_{index + 1:03d}.mp4"
            await asyncio.to_thread(
                render_clip_slot,
                clip.path,
                slot_output,
                target_duration_sec=float(segment["durationSec"]),
                aspect_ratio=aspect_ratio,
                motion_effect=primary_motion,
            )
            slot_paths.append(slot_output)

        complete_phase(job, "slot_render")

        subtitle_srt = build_srt_from_aligned_segments(aligned_segments)
        subtitle_vtt = build_vtt_from_aligned_segments(aligned_segments)
        srt_path = output_dir / "subtitles.srt"
        vtt_path = output_dir / "subtitles.vtt"
        srt_path.write_text(subtitle_srt, encoding="utf-8")
        vtt_path.write_text(subtitle_vtt, encoding="utf-8")

        update_phase(job, "mux", 0.0)
        final_mp4 = output_dir / "make_from_clips_final.mp4"
        await asyncio.to_thread(mux_video_with_audio, slot_paths, audio_path, final_mp4)
        complete_phase(job, "mux")

        update_phase(job, "preview", 0.0)
        preview_path = output_dir / "make_from_clips_preview.mp4"
        await asyncio.to_thread(generate_preview, final_mp4, preview_path, 480)
        complete_phase(job, "preview")

        outputs = {
            "mp4": str(final_mp4),
            "preview": str(preview_path),
            "srt": str(srt_path) if subtitle_format in SUPPORTED_SUBTITLE_FORMATS else None,
            "vtt": str(vtt_path),
            "aligned_segments": aligned_segments,
        }
        complete_job(job, outputs)
    except Exception as error:
        fail_job(job, str(error))
