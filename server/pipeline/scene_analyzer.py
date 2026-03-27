"""씬 중요도 분석 — Gemini Flash로 대본의 어떤 씬에 AI video를 적용할지 결정한다.

hook, intro, climax, CTA 등 중요한 씬을 식별하고
각 클립의 적정 길이(3-5초)를 AI가 유동적으로 결정한다.
"""

import json
import re

import requests


def analyze_scene_importance(
    script_text: str,
    scenes_json: list[dict],
    premium_clip_count: int,
    max_clip_duration: int,
    language: str,
    api_key: str,
) -> list[dict]:
    """대본과 씬 목록을 분석하여 AI video로 교체할 씬을 선정한다.

    Returns:
        list of dicts: [{"scene_index": int, "reason": str, "clip_duration": int, "motion_prompt": str}, ...]
    """
    total_scenes = len(scenes_json)
    scene_summaries = []
    for s in scenes_json:
        idx = s.get("index", 0)
        title = s.get("title", "")
        text = s.get("text", s.get("narration", ""))[:200]
        scene_summaries.append(f"Scene {idx}: [{title}] {text}")

    scenes_list_text = "\n".join(scene_summaries)

    prompt = f"""You are a video production AI director. Analyze the following script scenes and select exactly {premium_clip_count} scenes that would benefit most from AI-generated video clips (instead of static image with Ken Burns zoom).

RULES:
- Scene 0 (hook/opening) should almost always be selected — first impressions matter
- Prefer scenes with: dramatic action, emotional peaks, climax moments, CTA (call-to-action), visual spectacle
- Avoid scenes that are: narration-heavy with no visual action, transition/filler scenes
- Each clip duration must be between 2 and {max_clip_duration} seconds
- Vary the durations! Not all clips should be the same length:
  - Hook/intro: 3-{max_clip_duration}s (needs impact)
  - Action/climax: 4-{max_clip_duration}s (dramatic effect)
  - Transition/CTA: 2-3s (quick punch)
- Write a short motion_prompt for each: describe the camera movement and action (e.g. "slow zoom into face with dramatic lighting", "aerial flyover of cityscape at sunset")
- motion_prompt should be in English regardless of script language

TOTAL SCENES: {total_scenes}
SCENES TO SELECT: {premium_clip_count}
MAX CLIP DURATION: {max_clip_duration}s

SCENES:
{scenes_list_text}

Respond ONLY with a JSON array (no markdown, no explanation):
[
  {{"scene_index": 0, "reason": "hook — first impression", "clip_duration": 4, "motion_prompt": "dramatic slow zoom..."}},
  ...
]"""

    resp = requests.post(
        "https://generativelanguage.googleapis.com/v1beta/models/gemini-2.0-flash:generateContent",
        params={"key": api_key},
        json={
            "contents": [{"parts": [{"text": prompt}]}],
            "generationConfig": {"temperature": 0.3, "maxOutputTokens": 2000},
        },
        timeout=60,
    )
    resp.raise_for_status()
    raw = resp.json()["candidates"][0]["content"]["parts"][0]["text"]

    # JSON 추출 (마크다운 코드블록 처리)
    raw = raw.strip()
    if raw.startswith("```"):
        raw = re.sub(r"^```\w*\n?", "", raw)
        raw = re.sub(r"\n?```$", "", raw)
    raw = raw.strip()

    selected: list[dict] = json.loads(raw)

    # 검증 및 클램핑
    validated = []
    seen_indices = set()
    for item in selected:
        idx = item.get("scene_index", -1)
        if idx < 0 or idx >= total_scenes or idx in seen_indices:
            continue
        seen_indices.add(idx)
        item["clip_duration"] = max(2, min(item.get("clip_duration", 4), max_clip_duration))
        validated.append(item)
        if len(validated) >= premium_clip_count:
            break

    # 부족하면 균등 분포로 채우기
    if len(validated) < premium_clip_count:
        remaining = premium_clip_count - len(validated)
        step = max(1, total_scenes // (remaining + 1))
        for i in range(total_scenes):
            if len(validated) >= premium_clip_count:
                break
            candidate = (i * step) % total_scenes
            if candidate not in seen_indices:
                seen_indices.add(candidate)
                validated.append({
                    "scene_index": candidate,
                    "reason": "auto-fill for coverage",
                    "clip_duration": min(4, max_clip_duration),
                    "motion_prompt": "cinematic slow motion with dynamic camera movement",
                })

    return sorted(validated, key=lambda x: x["scene_index"])


def analyze_video_for_remix(
    video_transcript: str,
    num_scenes: int,
    language: str,
    api_key: str,
    direction: str = "",
    style: str = "",
) -> dict:
    """업로드된 동영상의 대본을 분석하여 리믹스용 정보를 생성한다.

    Returns:
        {
            "rewritten_script": str,       # 비슷하지만 새로운 대본
            "scene_breakdown": [...],       # 각 씬의 중요도와 교체 추천
            "recommended_replace_count": int
        }
    """
    direction_block = ""
    if direction or style:
        parts = []
        if direction:
            parts.append(f"DIRECTION: {direction}")
        if style:
            parts.append(f"VISUAL STYLE: {style}")
        direction_block = "\n".join(parts) + "\nApply the above direction/style when rewriting the script and choosing motion prompts.\n\n"

    prompt = f"""You are a video remix AI. Analyze the following video transcript and:

1. Rewrite a SIMILAR but ORIGINAL script (same topic, different wording, fresh angle)
2. Break the rewritten script into exactly {num_scenes} scenes
3. For each scene, rate importance (1-10) and whether it should be replaced with AI video
4. Recommend how many scenes to replace for best impact

{direction_block}LANGUAGE: {language}
TARGET SCENES: {num_scenes}

ORIGINAL TRANSCRIPT:
{video_transcript[:5000]}

Respond ONLY with JSON (no markdown):
{{
  "rewritten_script": "Full rewritten script text here...",
  "scene_breakdown": [
    {{"scene_index": 0, "title": "Hook", "text": "scene text...", "importance": 9, "recommend_replace": true, "motion_prompt": "dramatic zoom..."}},
    ...
  ],
  "recommended_replace_count": 5
}}"""

    resp = requests.post(
        "https://generativelanguage.googleapis.com/v1beta/models/gemini-2.0-flash:generateContent",
        params={"key": api_key},
        json={
            "contents": [{"parts": [{"text": prompt}]}],
            "generationConfig": {"temperature": 0.5, "maxOutputTokens": 8000},
        },
        timeout=90,
    )
    resp.raise_for_status()
    raw = resp.json()["candidates"][0]["content"]["parts"][0]["text"]

    raw = raw.strip()
    if raw.startswith("```"):
        raw = re.sub(r"^```\w*\n?", "", raw)
        raw = re.sub(r"\n?```$", "", raw)

    return json.loads(raw.strip())
