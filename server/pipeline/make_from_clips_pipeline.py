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
    "none",
    "zoom_in_slow",
    "zoom_out_slow",
    "pan_lr",
    "pan_rl",
    "freeze_tail",
    "crop_center",
    "crop_left",
    "crop_right",
    "flip_horizontal",
    "brightness_up",
    "brightness_down",
]
WEIGHTED_SEGMENT_PRESETS = (
    ["none"] * 3
    + ["zoom_in_slow", "zoom_out_slow", "pan_lr", "pan_rl"] * 2
    + ["crop_center", "crop_left", "crop_right", "brightness_up", "brightness_down"]
    + ["freeze_tail", "flip_horizontal"]
)


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
    clip_number: int


def parse_number_mapped_script(script: str) -> list[dict]:
    parsed: list[dict] = []
    for index, raw_line in enumerate(re.split(r"\n+", script)):
        line = raw_line.strip()
        if not line:
            continue

        match = re.match(r"^(\d+)\s*[|:-]\s*(.+)$", line)
        if match:
            parsed.append(
                {
                    "index": len(parsed),
                    "clipNumber": max(1, int(match.group(1))),
                    "text": match.group(2).strip(),
                }
            )
            continue

        parsed.append(
            {
                "index": len(parsed),
                "clipNumber": len(parsed) + 1,
                "text": line,
            }
        )

    return parsed


def normalize_text(text: str) -> str:
    lowered = text.lower()
    lowered = re.sub(r"[^\w\s가-힣]", " ", lowered)
    lowered = re.sub(r"\s+", " ", lowered)
    return lowered.strip()


def extract_keywords(text: str) -> list[str]:
    stopwords = {
        "the", "and", "for", "with", "this", "that", "from", "into", "your",
        "you", "are", "was", "were", "have", "has", "had", "but", "not",
        "then", "than", "just", "over", "under", "after", "before", "into",
        "onto", "about", "their", "there", "here", "will", "would", "should",
    }
    normalized = normalize_text(text)
    if not normalized:
        return []
    tokens = [token for token in normalized.split(" ") if len(token) > 1 and token not in stopwords]
    return list(dict.fromkeys(tokens))


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


def align_script_to_segments(script: str, subtitle_segments: list[SubtitleSegment]) -> list[dict]:
    script_lines = parse_number_mapped_script(script)
    if not script_lines:
        return []
    if not subtitle_segments:
        return [
            {
                "slotId": f"slot_{index + 1:02d}",
                "sentenceIndex": index,
                "clipNumber": int(line["clipNumber"]),
                "text": str(line["text"]),
                "startSec": float(index),
                "endSec": float(index + 1),
                "durationSec": 1.0,
            }
            for index, line in enumerate(script_lines)
        ]

    sentence_weights = [max(1, len(normalize_text(str(line["text"])).replace(" ", ""))) for line in script_lines]
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

    for sentence_index, line in enumerate(script_lines):
        consumed_weight += sentence_weights[sentence_index]
        target_weight = total_subtitle_weight * (consumed_weight / total_sentence_weight)
        start_idx = cursor
        while cursor < len(subtitle_segments) - 1 and cumulative_subtitle[cursor] < target_weight:
            cursor += 1
        end_idx = max(start_idx, cursor)
        start_segment = subtitle_segments[start_idx]
        end_segment = subtitle_segments[end_idx]
        aligned.append(
            {
                "slotId": f"slot_{sentence_index + 1:02d}",
                "sentenceIndex": sentence_index,
                "clipNumber": int(line["clipNumber"]),
                "text": str(line["text"]),
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
    preferred_number = int(segment.get("clipNumber") or 0)
    if preferred_number > 0:
        exact_match = next((clip for clip in clip_assets if clip.clip_number == preferred_number), None)
        if exact_match:
            return exact_match

    ordered = sorted(clip_assets, key=lambda clip: clip.clip_number)
    if not ordered:
        raise RuntimeError("No clip assets available for Make from Clips render.")

    fallback_index = min(int(segment.get("sentenceIndex", 0)), len(ordered) - 1)
    if ordered[fallback_index].name not in recent_names:
        return ordered[fallback_index]

    for clip in ordered:
        if clip.name not in recent_names:
            return clip

    return ordered[fallback_index]


def choose_segment_effect(rng: random.Random, previous_effect: str | None) -> str:
    pool = [preset for preset in WEIGHTED_SEGMENT_PRESETS if preset != previous_effect]
    return rng.choice(pool or list(WEIGHTED_SEGMENT_PRESETS))


def get_motion_crop_filter(effect_id: str, width: int, height: int, duration_sec: float) -> str:
    safe_duration = max(duration_sec, 0.2)
    ratio = f"{width}/{height}"
    padded_w = int(width * 1.18)
    padded_h = int(height * 1.18)
    base_scale = (
        f"scale=w='if(gte(iw/ih,{ratio}),-2,{padded_w})':"
        f"h='if(gte(iw/ih,{ratio}),{padded_h},-2)'"
    )

    if effect_id == "zoom_in_slow":
        crop = (
            f"crop=w='max({width},iw*(1-0.06*min(1,t/{safe_duration})))':"
            f"h='max({height},ih*(1-0.06*min(1,t/{safe_duration})))':"
            f"x='(in_w-out_w)/2':y='(in_h-out_h)/2',"
            f"scale={width}:{height}"
        )
        return f"{base_scale},{crop}"

    if effect_id == "zoom_out_slow":
        crop = (
            f"crop=w='max({width},iw*(0.94+0.06*min(1,t/{safe_duration})))':"
            f"h='max({height},ih*(0.94+0.06*min(1,t/{safe_duration})))':"
            f"x='(in_w-out_w)/2':y='(in_h-out_h)/2',"
            f"scale={width}:{height}"
        )
        return f"{base_scale},{crop}"

    if effect_id == "pan_lr":
        return f"{base_scale},crop={width}:{height}:x='(in_w-out_w)*min(1,t/{safe_duration})':y='(in_h-out_h)/2'"

    if effect_id == "pan_rl":
        return f"{base_scale},crop={width}:{height}:x='(in_w-out_w)*(1-min(1,t/{safe_duration}))':y='(in_h-out_h)/2'"

    if effect_id == "crop_left":
        return f"{base_scale},crop={width}:{height}:x='0':y='(in_h-out_h)/2'"

    if effect_id == "crop_right":
        return f"{base_scale},crop={width}:{height}:x='in_w-out_w':y='(in_h-out_h)/2'"

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
    effective_motion = motion_effect
    hold_duration = 0.0
    segment_fill_ratio = source_duration / safe_target

    if segment_fill_ratio < 1:
        hold_duration = max(0.0, safe_target - source_duration)
        if effective_motion not in {"freeze_tail", "none"}:
            hold_duration = max(hold_duration, random.uniform(0.3, 0.6))

    clip_trim_duration = min(source_duration, max(0.1, safe_target - hold_duration))
    hold_duration = max(0.0, safe_target - clip_trim_duration)
    motion_filter = get_motion_crop_filter(effective_motion, width, height, max(clip_trim_duration, safe_target))

    extra_filters: list[str] = []
    if effective_motion == "flip_horizontal":
        extra_filters.append("hflip")
    elif effective_motion == "brightness_up":
        extra_filters.append("eq=brightness=0.06")
    elif effective_motion == "brightness_down":
        extra_filters.append("eq=brightness=-0.06")

    filter_parts = [
        motion_filter,
        f"trim=duration={clip_trim_duration:.3f}",
        *extra_filters,
    ]
    if hold_duration > 0:
        filter_parts.append(f"tpad=stop_mode=clone:stop_duration={hold_duration:.3f}")
    filter_parts.extend([
        f"trim=duration={safe_target:.3f}",
        f"fps={FPS}",
        "format=yuv420p",
    ])
    filter_chain = ",".join(filter_parts)

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
        effect_rng = random.Random(f"make-from-clips:{job.job_id}")
        previous_effect: str | None = None

        for index, segment in enumerate(aligned_segments):
            update_phase(job, "slot_render", index / max(len(aligned_segments), 1))
            clip = pick_clip_for_segment(segment, clip_assets, recent_names)
            recent_names.append(clip.name)
            if len(recent_names) > 4:
                recent_names.pop(0)
            slot_motion = primary_motion if primary_motion != "none" else choose_segment_effect(effect_rng, previous_effect)
            previous_effect = slot_motion
            slot_output = output_dir / f"slot_{index + 1:03d}.mp4"
            await asyncio.to_thread(
                render_clip_slot,
                clip.path,
                slot_output,
                target_duration_sec=float(segment["durationSec"]),
                aspect_ratio=aspect_ratio,
                motion_effect=slot_motion,
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
