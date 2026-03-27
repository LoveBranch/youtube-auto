"""
CapCut 프로젝트 자동 생성 스크립트

오디오(WAV/MP3)와 자막(SRT)을 사용하여 CapCut draft_content.json을 생성한다.

사용법:
    py scripts/capcut_project.py <audio> <subtitle.srt> <project_name> [--capcut-dir DIR]
"""

import argparse
import json
import os
import re
import shutil
import sys
import time
import uuid
import wave
from pathlib import Path


def generate_id() -> str:
    """CapCut 스타일 UUID를 생성한다."""
    return str(uuid.uuid4()).upper()


def parse_srt(srt_path: str) -> list[dict]:
    """SRT 파일을 파싱하여 세그먼트 리스트를 반환한다."""
    content = Path(srt_path).read_text(encoding="utf-8")
    segments = []
    blocks = re.split(r"\n\s*\n", content.strip())

    for block in blocks:
        lines = block.strip().splitlines()
        if len(lines) < 3:
            continue

        time_match = re.match(
            r"(\d{2}):(\d{2}):(\d{2}),(\d{3})\s*-->\s*(\d{2}):(\d{2}):(\d{2}),(\d{3})",
            lines[1],
        )
        if not time_match:
            continue

        g = time_match.groups()
        start_us = (
            (int(g[0]) * 3600 + int(g[1]) * 60 + int(g[2])) * 1_000_000
            + int(g[3]) * 1000
        )
        end_us = (
            (int(g[4]) * 3600 + int(g[5]) * 60 + int(g[6])) * 1_000_000
            + int(g[7]) * 1000
        )

        text = "\n".join(lines[2:])
        segments.append({
            "start": start_us,
            "end": end_us,
            "duration": end_us - start_us,
            "text": text,
        })

    return segments


def get_audio_duration_us(audio_path: str) -> int:
    """오디오 파일의 길이를 마이크로초로 반환한다."""
    ext = Path(audio_path).suffix.lower()
    if ext == ".wav":
        with wave.open(audio_path, "rb") as wf:
            return int(wf.getnframes() / wf.getframerate() * 1_000_000)
    elif ext == ".mp3":
        from mutagen.mp3 import MP3
        return int(MP3(audio_path).info.length * 1_000_000)
    else:
        raise ValueError(f"지원하지 않는 형식: {ext}")


def make_platform_info() -> dict:
    return {
        "os": "windows",
        "os_version": "10.0.26200",
        "app_id": 359289,
        "app_version": "7.7.0",
        "app_source": "cc",
        "device_id": "",
        "hard_disk_id": "",
        "mac_address": "",
    }


def make_speed_material(speed: float = 1.0) -> dict:
    speed_id = generate_id()
    return {
        "id": speed_id,
        "type": "speed",
        "mode": 0,
        "speed": speed,
        "curve_speed": None,
    }, speed_id


def make_placeholder_info() -> dict:
    ph_id = generate_id()
    return {
        "id": ph_id,
        "type": "placeholder_info",
        "meta_type": "none",
        "res_path": "",
        "res_text": "",
        "error_path": "",
        "error_text": "",
    }, ph_id


def make_animation_material() -> dict:
    anim_id = generate_id()
    return {
        "id": anim_id,
        "type": "sticker_animation",
        "animations": [],
        "multi_language_current": "none",
    }, anim_id


def make_sound_channel_mapping() -> dict:
    sc_id = generate_id()
    return {
        "id": sc_id,
        "type": "",
        "audio_channel_mapping": 0,
        "is_config_open": False,
    }, sc_id


def make_vocal_separation() -> dict:
    vs_id = generate_id()
    return {
        "id": vs_id,
        "type": "vocal_separation",
        "choice": 0,
        "removed_sounds": [],
        "time_range": None,
        "production_path": "",
        "final_algorithm": "",
        "enter_from": "",
    }, vs_id


def make_beats_material() -> dict:
    beats_id = generate_id()
    return {
        "id": beats_id,
        "type": "beats",
        "enable_ai_beats": False,
        "gear": 404,
        "gear_count": 0,
        "mode": 404,
        "user_beats": [],
        "user_delete_ai_beats": None,
        "ai_beats": {
            "melody_url": "",
            "melody_path": "",
            "beats_url": "",
            "beats_path": "",
            "melody_percents": [0.0],
            "beat_speed_infos": [],
        },
    }, beats_id


def make_video_material(
    video_path: str, video_name: str, duration_us: int, width: int = 1920, height: int = 1080,
) -> tuple[dict, str]:
    """비디오 소재를 생성한다 (씬 영상용)."""
    video_id = generate_id()
    mat = {
        "id": video_id,
        "type": "video",
        "name": video_name,
        "duration": duration_us,
        "path": video_path.replace("\\", "/"),
        "category_name": "local",
        "width": width,
        "height": height,
        "source_platform": 0,
        "material_name": video_name,
        "local_material_id": str(uuid.uuid4()),
        "check_flag": 1,
        "crop": {
            "lower_left_x": 0.0, "lower_left_y": 1.0,
            "lower_right_x": 1.0, "lower_right_y": 1.0,
            "upper_left_x": 0.0, "upper_left_y": 0.0,
            "upper_right_x": 1.0, "upper_right_y": 0.0,
        },
        "has_audio": False,
        "extra_type_option": 0,
    }
    return mat, video_id


def make_image_material(
    image_path: str, image_name: str, duration_us: int, width: int = 1920, height: int = 1080,
) -> tuple[dict, str]:
    """이미지 소재를 생성한다 (씬 이미지용)."""
    image_id = generate_id()
    mat = {
        "id": image_id,
        "type": "photo",
        "name": image_name,
        "duration": duration_us,
        "path": image_path.replace("\\", "/"),
        "category_name": "local",
        "width": width,
        "height": height,
        "source_platform": 0,
        "material_name": image_name,
        "local_material_id": str(uuid.uuid4()),
        "check_flag": 1,
        "crop": {
            "lower_left_x": 0.0, "lower_left_y": 1.0,
            "lower_right_x": 1.0, "lower_right_y": 1.0,
            "upper_left_x": 0.0, "upper_left_y": 0.0,
            "upper_right_x": 1.0, "upper_right_y": 0.0,
        },
        "has_audio": False,
        "extra_type_option": 0,
    }
    return mat, image_id


def _make_kf_entry(time_offset: int, value: float) -> dict:
    """CapCut common_keyframes용 단일 키프레임 엔트리."""
    return {
        "id": generate_id(),
        "curveType": "Line",
        "time_offset": time_offset,
        "left_control": {"x": 0.0, "y": 0.0},
        "right_control": {"x": 0.0, "y": 0.0},
        "values": [value],
        "string_value": "",
        "graphID": "",
    }


def make_ken_burns_common_keyframes(duration_us: int, effect_type: str = "zoom_in") -> list[dict]:
    """Ken Burns 효과를 common_keyframes 형식으로 생성한다 (CapCut 데스크톱 형식).

    반환: segment['common_keyframes']에 넣을 리스트.
    """
    if effect_type == "zoom_in":
        start_scale, end_scale = 1.0, 1.3
        start_x, end_x = 0.0, 0.0
        start_y, end_y = 0.0, 0.0
    elif effect_type == "zoom_out":
        start_scale, end_scale = 1.3, 1.0
        start_x, end_x = 0.0, 0.0
        start_y, end_y = 0.0, 0.0
    elif effect_type == "pan_left":
        start_scale, end_scale = 1.2, 1.2
        start_x, end_x = 50.0, -50.0
        start_y, end_y = 0.0, 0.0
    elif effect_type == "pan_right":
        start_scale, end_scale = 1.2, 1.2
        start_x, end_x = -50.0, 50.0
        start_y, end_y = 0.0, 0.0
    else:
        start_scale, end_scale = 1.0, 1.2
        start_x, end_x = 0.0, 0.0
        start_y, end_y = 0.0, 0.0

    return [
        {
            "id": generate_id(),
            "material_id": "",
            "property_type": "KFTypePositionX",
            "keyframe_list": [
                _make_kf_entry(0, start_x),
                _make_kf_entry(duration_us, end_x),
            ],
        },
        {
            "id": generate_id(),
            "material_id": "",
            "property_type": "KFTypePositionY",
            "keyframe_list": [
                _make_kf_entry(0, start_y),
                _make_kf_entry(duration_us, end_y),
            ],
        },
        {
            "id": generate_id(),
            "material_id": "",
            "property_type": "KFTypeScaleX",
            "keyframe_list": [
                _make_kf_entry(0, start_scale),
                _make_kf_entry(duration_us, end_scale),
            ],
        },
        {
            "id": generate_id(),
            "material_id": "",
            "property_type": "KFTypeRotation",
            "keyframe_list": [
                _make_kf_entry(0, 0.0),
            ],
        },
    ]


KEN_BURNS_EFFECTS = ["zoom_in", "zoom_out", "pan_left", "pan_right"]


def make_canvas_material() -> dict:
    canvas_id = generate_id()
    return {
        "id": canvas_id,
        "type": "canvas_color",
        "color": "",
        "blur": 0.0,
        "image": "",
        "album_image": "",
        "image_id": "",
        "image_name": "",
        "source_platform": 0,
        "team_id": "",
    }, canvas_id


def make_segment(
    material_id: str,
    target_start: int,
    target_duration: int,
    extra_refs: list[str],
    render_index: int = 0,
    track_render_index: int = 0,
    source_start: int = 0,
    source_duration: int | None = None,
    has_clip: bool = False,
    clip_data: dict | None = None,
) -> dict:
    src_duration = source_duration if source_duration is not None else target_duration
    seg = {
        "id": generate_id(),
        "source_timerange": {"start": source_start, "duration": src_duration},
        "target_timerange": {"start": target_start, "duration": target_duration},
        "render_timerange": {"start": 0, "duration": 0},
        "desc": "",
        "state": 0,
        "speed": 1.0,
        "is_loop": False,
        "is_tone_modify": False,
        "reverse": False,
        "intensifies_audio": False,
        "cartoon": False,
        "volume": 1.0,
        "last_nonzero_volume": 1.0,
        "clip": clip_data,
        "uniform_scale": {"on": True, "value": 1.0} if has_clip else None,
        "material_id": material_id,
        "extra_material_refs": extra_refs,
        "render_index": render_index,
        "keyframe_refs": [],
        "enable_lut": False,
        "enable_adjust": False,
        "enable_hsl": False,
        "visible": True,
        "group_id": "",
        "enable_color_curves": True,
        "enable_hsl_curves": True,
        "track_render_index": track_render_index,
        "hdr_settings": None,
        "enable_color_wheels": True,
        "track_attribute": 0,
        "is_placeholder": False,
        "template_id": "",
        "enable_smart_color_adjust": False,
        "template_scene": "default",
        "common_keyframes": [],
        "caption_info": None,
        "responsive_layout": {
            "enable": False,
            "target_follow": "",
            "size_layout": 0,
            "horizontal_pos_layout": 0,
            "vertical_pos_layout": 0,
        },
        "enable_color_match_adjust": False,
        "enable_color_correct_adjust": False,
        "enable_adjust_mask": False,
        "raw_segment_id": "",
        "lyric_keyframes": None,
        "enable_video_mask": True,
        "digital_human_template_group_id": "",
        "color_correct_alg_result": "",
        "source": "segmentsourcenormal",
    }
    return seg


def make_text_material(text: str, font_path: str) -> tuple[dict, str]:
    text_id = generate_id()
    content_obj = {
        "text": text,
        "styles": [{
            "fill": {"content": {"render_type": "solid", "solid": {"color": [1, 1, 1]}}},
            "font": {"path": font_path, "id": ""},
            "size": 8.0,
            "range": [0, len(text)],
        }],
    }
    mat = {
        "id": text_id,
        "name": "",
        "type": "text",
        "content": json.dumps(content_obj, ensure_ascii=False),
        "base_content": "",
        "words": {"start_time": [], "end_time": [], "text": []},
        "current_words": {"start_time": [], "end_time": [], "text": []},
        "global_alpha": 1.0,
        "background_color": "",
        "background_alpha": 1.0,
        "background_style": 0,
        "combo_info": {"text_templates": []},
        "caption_template_info": {
            "resource_id": "", "third_resource_id": "", "resource_name": "",
            "category_id": "", "category_name": "", "effect_id": "",
            "request_id": "", "path": "", "is_new": False, "source_platform": 0,
        },
        "layer_weight": 1,
        "letter_spacing": 0.0,
        "text_curve": None,
        "text_loop_on_path": False,
        "offset_on_path": 0.0,
        "enable_path_typesetting": False,
        "text_exceeds_path_process_type": 0,
        "text_typesetting_paths": None,
        "text_typesetting_paths_file": "",
        "text_typesetting_path_index": 0,
        "line_spacing": 0.02,
        "has_shadow": False,
        "shadow_color": "",
        "shadow_alpha": 0.9,
        "shadow_smoothing": 0.45,
        "shadow_distance": 5.0,
        "shadow_point": {"x": 0.636, "y": -0.636},
        "shadow_angle": -45.0,
        "border_alpha": 1.0,
        "border_color": "#000000",
        "border_width": 0.15,
        "style_name": "",
        "text_color": "#FFFFFF",
        "text_alpha": 1.0,
        "font_name": "",
        "font_title": "none",
        "font_size": 8.0,
        "font_path": font_path,
        "font_id": "",
        "font_resource_id": "",
        "initial_scale": 1.0,
        "font_url": "",
        "typesetting": 0,
        "alignment": 1,
        "line_feed": 1,
        "use_effect_default_color": False,
        "is_rich_text": False,
        "shape_clip_x": False,
        "shape_clip_y": False,
        "ktv_color": "",
        "text_to_audio_ids": [],
        "bold_width": 0.0,
        "italic_degree": 0,
        "underline": False,
        "underline_width": 0.05,
        "underline_offset": 0.22,
        "sub_type": 0,
        "check_flag": 7,
        "text_size": 30,
        "font_category_name": "",
        "font_source_platform": 0,
        "font_third_resource_id": "",
        "font_category_id": "",
        "add_type": 0,
        "operation_type": 0,
        "recognize_type": 0,
        "fonts": [],
        "background_round_radius": 0.0,
        "background_width": 0.14,
        "background_height": 0.14,
        "background_vertical_offset": 0.0,
        "background_horizontal_offset": 0.0,
        "background_fill": "",
        "font_team_id": "",
        "tts_auto_update": False,
        "text_preset_resource_id": "",
        "group_id": "",
        "preset_id": "",
        "preset_name": "",
        "preset_category": "",
        "preset_category_id": "",
        "preset_index": 0,
        "preset_has_set_alignment": False,
        "force_apply_line_max_width": False,
        "language": "",
        "relevance_segment": [],
        "original_size": [],
        "fixed_width": -1.0,
        "fixed_height": -1.0,
        "line_max_width": 0.82,
        "oneline_cutoff": False,
        "cutoff_postfix": "",
        "subtitle_template_original_fontsize": 0.0,
        "subtitle_keywords": None,
        "inner_padding": -1.0,
        "multi_language_current": "none",
        "source_from": "",
        "is_lyric_effect": False,
        "lyric_group_id": "",
        "lyrics_template": {
            "resource_id": "", "resource_name": "", "panel": "",
            "effect_id": "", "path": "", "category_id": "",
            "category_name": "", "request_id": "",
        },
        "is_batch_replace": False,
        "is_words_linear": False,
        "ssml_content": "",
        "subtitle_keywords_config": None,
        "sub_template_id": -1,
        "translate_original_text": "",
        "recognize_task_id": "",
        "recognize_text": "",
        "recognize_model": "",
        "punc_model": "",
    }
    return mat, text_id


def make_audio_material(
    audio_path: str, audio_name: str, duration_us: int
) -> tuple[dict, str]:
    audio_id = generate_id()
    mat = {
        "id": audio_id,
        "type": "extract_music",
        "name": audio_name,
        "duration": duration_us,
        "path": audio_path.replace("\\", "/"),
        "category_name": "local",
        "wave_points": [],
        "music_id": str(uuid.uuid4()),
        "app_id": 0,
        "text_id": "",
        "tone_type": "",
        "source_platform": 0,
        "video_id": "",
        "effect_id": "",
        "resource_id": "",
        "third_resource_id": "",
        "category_id": "",
        "intensifies_path": "",
        "formula_id": "",
        "check_flag": 1,
        "team_id": "",
        "local_material_id": str(uuid.uuid4()),
        "tone_speaker": "",
        "mock_tone_speaker": "",
        "tone_effect_id": "",
        "tone_effect_name": "",
        "tone_platform": "",
        "cloned_model_type": "",
        "tone_category_id": "",
        "tone_category_name": "",
        "tone_second_category_id": "",
        "tone_second_category_name": "",
        "tone_emotion_name_key": "",
        "tone_emotion_style": "",
        "tone_emotion_role": "",
        "tone_emotion_selection": "",
        "tone_emotion_scale": 0.0,
        "moyin_emotion": "",
        "request_id": "",
        "query": "",
        "search_id": "",
        "sound_separate_type": "",
        "is_text_edit_overdub": False,
        "is_ugc": False,
        "is_ai_clone_tone": False,
        "is_ai_clone_tone_post": False,
        "source_from": "",
        "copyright_limit_type": "none",
        "aigc_history_id": "",
        "aigc_item_id": "",
        "music_source": "",
        "pgc_id": "",
        "pgc_name": "",
        "similiar_music_info": {
            "original_song_id": "", "original_song_name": "",
        },
        "ai_music_type": 0,
        "lyric_type": 0,
        "tts_task_id": "",
        "tts_generate_scene": "",
        "ai_music_generate_scene": 0,
    }
    return mat, audio_id


ASPECT_RATIOS = {
    "16:9": (1920, 1080),
    "9:16": (1080, 1920),
    "1:1":  (1080, 1080),
}


def build_draft(
    audio_abs_path: str,
    srt_segments: list[dict],
    audio_duration_us: int,
    project_name: str,
    aspect_ratio: str = "16:9",
) -> dict:
    """CapCut draft_content.json 구조를 생성한다."""

    width, height = ASPECT_RATIOS.get(aspect_ratio, (1920, 1080))

    # 폰트 경로 (CapCut 기본)
    font_path = "C:/Users/shinh/AppData/Local/CapCut/Apps/7.7.0.3143/Resources/Font/SystemFont/en.ttf"

    # --- Materials ---
    audio_mat, audio_mat_id = make_audio_material(
        audio_abs_path, Path(audio_abs_path).name, audio_duration_us
    )

    text_materials = []
    text_segments = []

    # Audio extra materials
    audio_speed, audio_speed_id = make_speed_material(1.0)
    audio_ph, audio_ph_id = make_placeholder_info()
    audio_beats, audio_beats_id = make_beats_material()
    audio_sc, audio_sc_id = make_sound_channel_mapping()
    audio_vs, audio_vs_id = make_vocal_separation()

    audio_extra_refs = [audio_speed_id, audio_ph_id, audio_beats_id, audio_sc_id, audio_vs_id]

    # Audio segment
    audio_seg = make_segment(
        material_id=audio_mat_id,
        target_start=0,
        target_duration=audio_duration_us,
        extra_refs=audio_extra_refs,
        source_start=0,
        source_duration=audio_duration_us,
        track_render_index=0,
    )

    # Canvas material (black background)
    canvas_mat, canvas_id = make_canvas_material()

    # Text track segments + materials
    all_animations = []
    all_placeholders = [audio_ph]
    all_speeds = [audio_speed]
    all_beats = [audio_beats]
    all_sound_channels = [audio_sc]
    all_vocal_seps = [audio_vs]

    for sub in srt_segments:
        text_mat, text_mat_id = make_text_material(sub["text"], font_path)
        text_materials.append(text_mat)

        anim_mat, anim_id = make_animation_material()
        all_animations.append(anim_mat)

        text_clip = {
            "scale": {"x": 1.0, "y": 1.0},
            "rotation": 0.0,
            "transform": {"x": 0.0, "y": -0.75},
            "flip": {"vertical": False, "horizontal": False},
            "alpha": 1.0,
        }

        seg = make_segment(
            material_id=text_mat_id,
            target_start=sub["start"],
            target_duration=sub["duration"],
            extra_refs=[anim_id],
            render_index=14000,
            track_render_index=1,
            has_clip=True,
            clip_data=text_clip,
        )
        seg["source_timerange"] = None
        text_segments.append(seg)

    # --- Tracks ---
    audio_track = {
        "id": generate_id(),
        "type": "audio",
        "segments": [audio_seg],
        "flag": 0,
        "attribute": 0,
        "name": "",
        "is_default_name": True,
    }

    text_track = {
        "id": generate_id(),
        "type": "text",
        "segments": text_segments,
        "flag": 0,
        "attribute": 0,
        "name": "",
        "is_default_name": True,
    }

    tracks = [audio_track, text_track]

    # --- Full draft ---
    draft = {
        "id": generate_id(),
        "version": 360000,
        "new_version": "151.0.0",
        "name": "",
        "duration": audio_duration_us,
        "create_time": 0,
        "update_time": 0,
        "fps": 30.0,
        "is_drop_frame_timecode": False,
        "color_space": 0,
        "config": {
            "video_mute": False,
            "record_audio_last_index": 1,
            "extract_audio_last_index": 1,
            "original_sound_last_index": 1,
            "subtitle_recognition_id": "",
            "subtitle_taskinfo": [],
            "lyrics_recognition_id": "",
            "lyrics_taskinfo": [],
            "subtitle_sync": True,
            "lyrics_sync": True,
            "sticker_max_index": 1,
            "adjust_max_index": 1,
            "material_save_mode": 0,
            "export_range": None,
            "maintrack_adsorb": True,
            "combination_max_index": 1,
            "attachment_info": [],
            "zoom_info_params": None,
            "system_font_list": [],
            "multi_language_mode": "none",
            "multi_language_main": "none",
            "multi_language_current": "none",
            "multi_language_list": [],
            "subtitle_keywords_config": None,
            "use_float_render": False,
        },
        "canvas_config": {
            "ratio": aspect_ratio,
            "width": width,
            "height": height,
            "background": None,
        },
        "tracks": tracks,
        "group_container": None,
        "materials": {
            "flowers": [],
            "videos": [],
            "tail_leaders": [],
            "audios": [audio_mat],
            "images": [],
            "texts": text_materials,
            "effects": [],
            "stickers": [],
            "canvases": [canvas_mat],
            "transitions": [],
            "audio_effects": [],
            "audio_fades": [],
            "beats": all_beats,
            "material_animations": all_animations,
            "placeholders": [],
            "placeholder_infos": all_placeholders,
            "speeds": all_speeds,
            "common_mask": [],
            "chromas": [],
            "text_templates": [],
            "realtime_denoises": [],
            "audio_pannings": [],
            "audio_pitch_shifts": [],
            "video_trackings": [],
            "hsl": [],
            "drafts": [],
            "color_curves": [],
            "hsl_curves": [],
            "primary_color_wheels": [],
            "log_color_wheels": [],
            "video_effects": [],
            "audio_balances": [],
            "handwrites": [],
            "manual_deformations": [],
            "manual_beautys": [],
            "plugin_effects": [],
            "sound_channel_mappings": all_sound_channels,
            "green_screens": [],
            "shapes": [],
            "material_colors": [],
            "digital_humans": [],
            "digital_human_model_dressing": [],
            "smart_crops": [],
            "ai_translates": [],
            "audio_track_indexes": [],
            "loudnesses": [],
            "vocal_beautifys": [],
            "vocal_separations": all_vocal_seps,
            "smart_relights": [],
            "time_marks": [],
            "multi_language_refs": [],
            "video_shadows": [],
            "video_strokes": [],
            "video_radius": [],
        },
        "keyframes": {
            "videos": [], "audios": [], "texts": [], "stickers": [],
            "filters": [], "adjusts": [], "handwrites": [], "effects": [],
        },
        "keyframe_graph_list": [],
        "platform": make_platform_info(),
        "last_modified_platform": make_platform_info(),
        "mutable_config": None,
        "cover": None,
        "retouch_cover": None,
        "extra_info": None,
        "relationships": [],
        "render_index_track_mode_on": True,
        "free_render_index_mode_on": False,
        "static_cover_image_path": "",
        "source": "default",
        "time_marks": None,
        "path": "",
        "lyrics_effects": [],
        "draft_type": "video",
    }

    return draft


def build_meta_info(
    project_folder: str,
    project_name: str,
    draft_root: str,
    audio_abs_path: str,
    audio_duration_us: int,
) -> dict:
    now_us = int(time.time() * 1_000_000)
    return {
        "cloud_draft_cover": True,
        "cloud_draft_sync": True,
        "cloud_package_completed_time": "",
        "draft_cloud_capcut_purchase_info": "",
        "draft_cloud_last_action_download": False,
        "draft_cloud_package_type": "",
        "draft_cloud_purchase_info": "",
        "draft_cloud_template_id": "",
        "draft_cloud_tutorial_info": "",
        "draft_cloud_videocut_purchase_info": "",
        "draft_cover": "",
        "draft_deeplink_url": "",
        "draft_enterprise_info": {
            "draft_enterprise_extra": "",
            "draft_enterprise_id": "",
            "draft_enterprise_name": "",
            "enterprise_material": [],
        },
        "draft_fold_path": project_folder.replace("\\", "/"),
        "draft_id": str(uuid.uuid4()),
        "draft_is_ae_produce": False,
        "draft_is_ai_packaging_used": False,
        "draft_is_ai_shorts": False,
        "draft_is_ai_translate": False,
        "draft_is_article_video_draft": False,
        "draft_is_cloud_temp_draft": False,
        "draft_is_from_deeplink": "false",
        "draft_is_invisible": False,
        "draft_is_web_article_video": False,
        "draft_materials": [
            {
                "type": 0,
                "value": [
                    {
                        "ai_group_type": "",
                        "create_time": int(time.time()),
                        "duration": audio_duration_us,
                        "extra_info": Path(audio_abs_path).name,
                        "file_Path": audio_abs_path.replace("\\", "/"),
                        "height": 0,
                        "id": str(uuid.uuid4()),
                        "import_time": int(time.time()),
                        "import_time_ms": now_us,
                        "item_source": 1,
                        "md5": "",
                        "metetype": "music",
                        "roughcut_time_range": {
                            "duration": audio_duration_us,
                            "start": 0,
                        },
                        "sub_time_range": {"duration": -1, "start": -1},
                        "type": 0,
                        "width": 0,
                    }
                ],
            },
            {"type": 1, "value": []},
            {"type": 2, "value": []},
            {"type": 3, "value": []},
            {"type": 6, "value": []},
            {"type": 7, "value": []},
            {"type": 8, "value": []},
        ],
        "draft_materials_copied_info": [],
        "draft_name": project_name,
        "draft_need_rename_folder": False,
        "draft_new_version": "",
        "draft_removable_storage_device": "",
        "draft_root_path": draft_root.replace("/", "\\"),
        "draft_segment_extra_info": [],
        "draft_timeline_materials_size_": 0,
        "draft_type": "",
        "draft_web_article_video_enter_from": "",
        "tm_draft_cloud_completed": "",
        "tm_draft_cloud_entry_id": -1,
        "tm_draft_cloud_modified": 0,
        "tm_draft_cloud_parent_entry_id": -1,
        "tm_draft_cloud_space_id": -1,
        "tm_draft_cloud_user_id": -1,
        "tm_draft_create": now_us,
        "tm_draft_modified": now_us,
        "tm_draft_removed": 0,
        "tm_duration": audio_duration_us,
    }


def main() -> None:
    default_capcut = os.path.expanduser(
        "~/AppData/Local/CapCut/User Data/Projects/com.lveditor.draft"
    )

    parser = argparse.ArgumentParser(description="CapCut 프로젝트 자동 생성")
    parser.add_argument("audio", help="오디오 MP3 파일 경로")
    parser.add_argument("srt", help="SRT 자막 파일 경로")
    parser.add_argument("name", help="프로젝트 이름")
    parser.add_argument(
        "--capcut-dir", default=default_capcut, help="CapCut 프로젝트 루트 경로"
    )
    parser.add_argument(
        "--aspect-ratio", default="16:9",
        choices=["16:9", "9:16", "1:1"],
        help="화면 비율 (기본: 16:9)",
    )
    parser.add_argument(
        "--scenes-dir", default=None,
        help="Whisk 씬 영상 디렉토리 (scenes.json 포함)",
    )
    args = parser.parse_args()

    audio_path = os.path.abspath(args.audio)
    srt_path = os.path.abspath(args.srt)

    if not os.path.exists(audio_path):
        print(f"오류: 오디오 파일 없음: {audio_path}", file=sys.stderr)
        sys.exit(1)
    if not os.path.exists(srt_path):
        print(f"오류: SRT 파일 없음: {srt_path}", file=sys.stderr)
        sys.exit(1)

    # 오디오 길이
    audio_duration_us = get_audio_duration_us(audio_path)
    print(f"오디오 길이: {audio_duration_us / 1_000_000:.1f}초")

    # SRT 파싱
    srt_segments = parse_srt(srt_path)
    print(f"자막 세그먼트: {len(srt_segments)}개")

    # 프로젝트 폴더 생성
    project_folder = os.path.join(args.capcut_dir, args.name)
    os.makedirs(project_folder, exist_ok=True)

    # 오디오를 프로젝트 Resources 폴더에 복사
    resources_dir = os.path.join(project_folder, "Resources")
    os.makedirs(resources_dir, exist_ok=True)
    dest_audio = os.path.join(resources_dir, os.path.basename(audio_path))
    shutil.copy2(audio_path, dest_audio)
    audio_abs_for_draft = os.path.abspath(dest_audio)

    # 씬 영상/이미지 로드 (있을 경우)
    scene_assets = []  # {"type": "video"|"image", "path", "name", "start_us", "duration_us"}
    if args.scenes_dir:
        scenes_json = os.path.join(args.scenes_dir, "scenes.json")
        if os.path.exists(scenes_json):
            with open(scenes_json, "r", encoding="utf-8") as f:
                scenes_data = json.load(f)
            elapsed_us = 0
            for scene in scenes_data:
                video_file = os.path.join(args.scenes_dir, scene.get("video_file", ""))
                image_file = os.path.join(args.scenes_dir, scene.get("image_file", ""))
                start_us = int(scene.get("start_time", elapsed_us / 1_000_000) * 1_000_000)
                duration_us = int(scene.get("duration", 4.0) * 1_000_000)

                if os.path.exists(video_file):
                    # 영상 파일이 있으면 영상 사용
                    dest = os.path.join(resources_dir, os.path.basename(video_file))
                    shutil.copy2(video_file, dest)
                    scene_assets.append({
                        "type": "video",
                        "path": os.path.abspath(dest),
                        "name": os.path.basename(video_file),
                        "start_us": start_us,
                        "duration_us": duration_us,
                    })
                    print(f"  씬 영상 추가: {os.path.basename(video_file)}")
                    elapsed_us = start_us + duration_us
                elif os.path.exists(image_file):
                    # 이미지만 있으면 Ken Burns 효과 적용
                    dest = os.path.join(resources_dir, os.path.basename(image_file))
                    shutil.copy2(image_file, dest)
                    scene_assets.append({
                        "type": "image",
                        "path": os.path.abspath(dest),
                        "name": os.path.basename(image_file),
                        "start_us": start_us,
                        "duration_us": duration_us,
                        "scene_index": scene.get("index", 0),
                    })
                    print(f"  씬 이미지 추가 (Ken Burns): {os.path.basename(image_file)}")
                    elapsed_us = start_us + duration_us
            print(f"  총 {len(scene_assets)}개 씬 로드 (영상 {len([s for s in scene_assets if s['type'] == 'video'])}개 + 이미지 {len([s for s in scene_assets if s['type'] == 'image'])}개)")

    # draft_content.json 생성
    print(f"화면 비율: {args.aspect_ratio}")
    draft = build_draft(
        audio_abs_path=audio_abs_for_draft,
        srt_segments=srt_segments,
        audio_duration_us=audio_duration_us,
        project_name=args.name,
        aspect_ratio=args.aspect_ratio,
    )

    # 씬 영상/이미지 트랙 추가
    if scene_assets:
        width, height = ASPECT_RATIOS.get(args.aspect_ratio, (1920, 1080))
        video_materials = []
        image_materials = []
        visual_segments = []
        all_keyframes = []

        for i, sa in enumerate(scene_assets):
            if sa["type"] == "video":
                vid_mat, vid_mat_id = make_video_material(
                    sa["path"], sa["name"], sa["duration_us"], width, height,
                )
                video_materials.append(vid_mat)

                vid_speed, vid_speed_id = make_speed_material(1.0)
                draft["materials"]["speeds"].append(vid_speed)

                vid_canvas, vid_canvas_id = make_canvas_material()
                draft["materials"]["canvases"].append(vid_canvas)

                vid_seg = make_segment(
                    material_id=vid_mat_id,
                    target_start=sa["start_us"],
                    target_duration=sa["duration_us"],
                    extra_refs=[vid_speed_id, vid_canvas_id],
                    render_index=0,
                    track_render_index=0,
                    source_start=0,
                    source_duration=sa["duration_us"],
                )
                visual_segments.append(vid_seg)

            elif sa["type"] == "image":
                img_mat, img_mat_id = make_image_material(
                    sa["path"], sa["name"], sa["duration_us"], width, height,
                )
                image_materials.append(img_mat)

                img_speed, img_speed_id = make_speed_material(1.0)
                draft["materials"]["speeds"].append(img_speed)

                img_canvas, img_canvas_id = make_canvas_material()
                draft["materials"]["canvases"].append(img_canvas)

                img_clip = {
                    "scale": {"x": 1.0, "y": 1.0},
                    "rotation": 0.0,
                    "transform": {"x": 0.0, "y": 0.0},
                    "flip": {"vertical": False, "horizontal": False},
                    "alpha": 1.0,
                }
                img_seg = make_segment(
                    material_id=img_mat_id,
                    target_start=sa["start_us"],
                    target_duration=sa["duration_us"],
                    extra_refs=[img_speed_id, img_canvas_id],
                    render_index=0,
                    track_render_index=0,
                    source_start=0,
                    source_duration=sa["duration_us"],
                    has_clip=True,
                    clip_data=img_clip,
                )

                visual_segments.append(img_seg)

        draft["materials"]["videos"] = video_materials + image_materials

        video_track = {
            "id": generate_id(),
            "type": "video",
            "segments": visual_segments,
            "flag": 0,
            "attribute": 0,
            "name": "",
            "is_default_name": True,
        }
        # 비디오 트랙을 맨 앞에 삽입
        draft["tracks"].insert(0, video_track)
        video_count = len([s for s in scene_assets if s["type"] == "video"])
        image_count = len([s for s in scene_assets if s["type"] == "image"])
        print(f"비주얼 트랙 추가: 영상 {video_count}개 + 이미지(Ken Burns) {image_count}개")

    draft_path = os.path.join(project_folder, "draft_content.json")
    with open(draft_path, "w", encoding="utf-8") as f:
        json.dump(draft, f, ensure_ascii=False)

    # draft_meta_info.json 생성
    meta = build_meta_info(
        project_folder=project_folder,
        project_name=args.name,
        draft_root=args.capcut_dir,
        audio_abs_path=audio_abs_for_draft,
        audio_duration_us=audio_duration_us,
    )
    meta_path = os.path.join(project_folder, "draft_meta_info.json")
    with open(meta_path, "w", encoding="utf-8") as f:
        json.dump(meta, f, ensure_ascii=False)

    # draft_agency_config.json 생성
    agency = {
        "is_auto_agency_enabled": False,
        "is_auto_agency_popup": False,
        "is_single_agency_mode": False,
        "marterials": None,
        "use_converter": True,
        "video_resolution": 720,
    }
    agency_path = os.path.join(project_folder, "draft_agency_config.json")
    with open(agency_path, "w", encoding="utf-8") as f:
        json.dump(agency, f, ensure_ascii=False)

    # 빈 파일들 생성
    for fname in ["draft_biz_config.json", "draft_settings"]:
        fpath = os.path.join(project_folder, fname)
        if not os.path.exists(fpath):
            Path(fpath).write_text("", encoding="utf-8")

    # 필요한 빈 디렉토리
    for dname in ["adjust_mask", "matting", "smart_crop", "subdraft", "qr_upload"]:
        os.makedirs(os.path.join(project_folder, dname), exist_ok=True)

    print(f"\nCapCut 프로젝트 생성 완료!")
    print(f"  경로: {project_folder}")
    print(f"  CapCut을 열면 '{args.name}' 프로젝트가 표시됩니다.")


if __name__ == "__main__":
    main()
