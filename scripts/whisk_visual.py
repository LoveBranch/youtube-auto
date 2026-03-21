"""
Whisk (Google Labs) 이미지 생성 + 모션 영상 변환 스크립트

대본의 스토리보드 씬별로 이미지 프롬프트를 생성하고,
Whisk API로 이미지를 생성한 뒤 모션 영상으로 변환한다.

사용법:
    py scripts/whisk_visual.py <script.md> <subtitle.srt> <output_dir> [--lang ko] [--aspect-ratio 16:9]

출력:
    output_dir/
      scenes.json           # 씬 정보 + 프롬프트
      scene_001.png         # 생성된 이미지
      scene_001.mp4         # 모션 영상
      ...
"""

import argparse
import json
import re
import sys
import time
from pathlib import Path


def extract_sections(md_text: str, max_scenes: int = 25) -> list[dict]:
    """마크다운 대본에서 씬을 분리한다.

    max_scenes로 최대 씬 수를 제한한다 (기본: 25).
    섹션별로 2~3개 씬으로 나누어 적절한 수를 유지한다.
    """
    lines = md_text.splitlines()
    # 1단계: 섹션별로 텍스트 수집
    raw_sections: list[dict] = []
    current_title = "인트로"
    current_lines: list[str] = []

    for line in lines:
        stripped = line.strip()
        if re.match(r"^##?\s*참고\s*자료", stripped):
            break
        if re.match(r"^-\s*\*\*.*\*\*\s*:", stripped):
            continue
        if re.match(r"^[-=*]{3,}$", stripped):
            if current_lines:
                raw_sections.append({"title": current_title, "text": "\n".join(current_lines).strip()})
                current_lines = []
            continue
        header_match = re.match(r"^#{1,3}\s+(.+)$", stripped)
        if header_match:
            if current_lines:
                raw_sections.append({"title": current_title, "text": "\n".join(current_lines).strip()})
                current_lines = []
            current_title = header_match.group(1).strip()
            continue
        if re.match(r"^\(?\d+:\d+\s*~\s*\d+:\d+\)?$", stripped):
            continue
        if stripped:
            cleaned = re.sub(r"\*{1,2}([^*]+)\*{1,2}", r"\1", stripped)
            cleaned = re.sub(r"^[-*]\s+", "", cleaned)
            cleaned = re.sub(r"^\d+\.\s+", "", cleaned)
            cleaned = cleaned.lstrip("> ").strip()
            if cleaned:
                current_lines.append(cleaned)

    if current_lines:
        raw_sections.append({"title": current_title, "text": "\n".join(current_lines).strip()})

    raw_sections = [s for s in raw_sections if s["text"]]

    # 2단계: 섹션당 할당할 씬 수 계산
    if not raw_sections:
        return []

    scenes_per_section = max(1, max_scenes // len(raw_sections))
    remaining = max_scenes - scenes_per_section * len(raw_sections)

    sections: list[dict] = []
    for i, sec in enumerate(raw_sections):
        # 긴 섹션에 추가 씬 배분
        n = scenes_per_section + (1 if i < remaining else 0)
        sentences = _split_sentences(sec["text"])

        if len(sentences) <= n:
            # 문장 수가 할당보다 적으면 그대로
            for sent in sentences:
                if sent.strip():
                    sections.append({"title": sec["title"], "text": sent.strip()})
        else:
            # 문장들을 n개 그룹으로 균등 병합
            chunk_size = len(sentences) // n
            extra = len(sentences) % n
            idx = 0
            for j in range(n):
                size = chunk_size + (1 if j < extra else 0)
                merged = " ".join(sentences[idx:idx + size])
                if merged.strip():
                    sections.append({"title": sec["title"], "text": merged.strip()})
                idx += size

    return sections


def _split_sentences(text: str) -> list[str]:
    """텍스트를 문장 단위로 분리한다. 너무 짧으면 다음 문장과 합친다."""
    # 마침표, 물음표, 느낌표 뒤에서 분리 (단, 숫자.숫자는 제외)
    raw = re.split(r'(?<=[.?!。])\s+', text)
    # 너무 짧은 문장(20자 미만)은 다음 문장과 합침
    merged: list[str] = []
    buf = ""
    for s in raw:
        if buf:
            buf += " " + s
            if len(buf) >= 20:
                merged.append(buf)
                buf = ""
        elif len(s) < 20:
            buf = s
        else:
            merged.append(s)
    if buf:
        if merged:
            merged[-1] += " " + buf
        else:
            merged.append(buf)
    return merged


def parse_srt_timestamps(srt_path: str) -> list[dict]:
    """SRT에서 시작/종료 시간을 파싱한다."""
    content = Path(srt_path).read_text(encoding="utf-8")
    blocks = re.split(r"\n\s*\n", content.strip())
    entries = []

    def _parse_ts(ts_str: str) -> float:
        """HH:MM:SS,mmm 또는 MM:SS,mmm 형식의 타임스탬프를 초로 변환."""
        m = re.match(r"(\d{2}):(\d{2}):(\d{2}),(\d{3})", ts_str)
        if m:
            return int(m[1]) * 3600 + int(m[2]) * 60 + int(m[3]) + int(m[4]) / 1000
        m = re.match(r"(\d{2}):(\d{2}),(\d{3})", ts_str)
        if m:
            return int(m[1]) * 60 + int(m[2]) + int(m[3]) / 1000
        return 0.0

    for block in blocks:
        lines = block.strip().splitlines()
        if len(lines) < 3:
            continue
        arrow_match = re.match(r"(.+?)\s*-->\s*(.+)", lines[1])
        if not arrow_match:
            continue
        start_s = _parse_ts(arrow_match.group(1).strip())
        end_s = _parse_ts(arrow_match.group(2).strip())
        text = "\n".join(lines[2:])
        entries.append({"start": start_s, "end": end_s, "text": text})

    return entries


def map_scenes_to_timecodes(sections: list[dict], srt_entries: list[dict]) -> list[dict]:
    """섹션을 SRT 타임코드에 균등 매핑한다."""
    if not srt_entries or not sections:
        return []

    total_duration = srt_entries[-1]["end"]
    scene_duration = total_duration / len(sections)
    scenes = []

    for i, section in enumerate(sections):
        start = i * scene_duration
        end = (i + 1) * scene_duration
        scenes.append({
            "index": i + 1,
            "title": section["title"],
            "text_preview": section["text"][:200],
            "start_time": round(start, 3),
            "end_time": round(end, 3),
            "duration": round(end - start, 3),
        })

    return scenes


VISUAL_STYLE_PROMPTS = {
    "ko": "시네마틱 조명, 고품질 디지털 일러스트, 유튜브 교육 영상 스타일",
    "en": "cinematic lighting, high-quality digital illustration, YouTube educational style",
    "ja": "シネマティックライティング、高品質デジタルイラスト、YouTube教育動画スタイル",
    "zh": "电影级灯光，高质量数字插画，YouTube教育视频风格",
    "es": "iluminación cinematográfica, ilustración digital de alta calidad, estilo educativo de YouTube",
}


def generate_image_prompts(scenes: list[dict], lang: str, aspect_ratio: str, api_key: str = "") -> list[dict]:
    """Gemini API로 대본 내용을 시각적 이미지 프롬프트로 변환한다."""
    orientation = {
        "16:9": "wide landscape",
        "9:16": "tall portrait, vertical",
        "1:1": "square composition",
    }.get(aspect_ratio, "wide landscape")

    # Gemini API로 정확한 이미지 프롬프트 생성
    if api_key:
        prompts = _generate_prompts_with_gemini(scenes, lang, orientation, api_key)
        if prompts:
            for scene, prompt in zip(scenes, prompts):
                scene["image_prompt"] = prompt
                scene["image_file"] = f"scene_{scene['index']:03d}.jpg"
                scene["video_file"] = f"scene_{scene['index']:03d}.mp4"
                scene["is_hook"] = _is_hook_scene(scene)
            return scenes

    # 폴백: Gemini 실패 시 기존 방식
    style = VISUAL_STYLE_PROMPTS.get(lang, VISUAL_STYLE_PROMPTS["en"])
    for scene in scenes:
        text_preview = scene["text_preview"]
        scene["image_prompt"] = (
            f"{scene['title']}: {text_preview[:100]}. "
            f"{style}, {orientation}, no text overlay"
        )
        scene["image_file"] = f"scene_{scene['index']:03d}.jpg"
        scene["video_file"] = f"scene_{scene['index']:03d}.mp4"
        scene["is_hook"] = _is_hook_scene(scene)

    return scenes


def _is_hook_scene(scene: dict) -> bool:
    """핵심 씬(Hook)인지 판별한다. 첫 씬, 마지막 씬, 또는 제목에 키워드 포함."""
    hook_keywords = [
        "인트로", "intro", "hook", "훅", "오프닝", "opening",
        "결론", "conclusion", "마무리", "ending", "클로저",
        "핵심", "core", "중요", "key", "전환", "transition",
    ]
    title_lower = scene.get("title", "").lower()
    if scene.get("index") == 1:
        return True
    for kw in hook_keywords:
        if kw in title_lower:
            return True
    return False


def _generate_prompts_with_gemini(scenes: list[dict], lang: str, orientation: str, api_key: str) -> list[str]:
    """Gemini API에게 대본을 주고 각 씬의 시각적 이미지 프롬프트를 생성한다."""
    import requests

    scenes_text = ""
    for s in scenes:
        scenes_text += f"\n[씬 {s['index']}] {s['title']}\n{s['text_preview'][:200]}\n"

    system_prompt = f"""You are an expert image prompt engineer for AI image generators (Imagen, DALL-E, Midjourney).

Given the following script scenes, create ONE image generation prompt per scene in English.

Rules:
- Each prompt must be a concrete, visual description of what should appear in the image
- DO NOT use abstract concepts. Convert metaphors into literal visual scenes
- Style: cinematic, photorealistic, dramatic lighting, 8K ultra HD, shot on ARRI Alexa, shallow depth of field
- Include: subject, setting, lighting, camera angle, atmosphere
- For biblical/spiritual scenes: use real human figures, ancient Middle Eastern settings, golden hour or dramatic chiaroscuro lighting
- Avoid cartoonish, illustrated, or digital art styles. Everything must look like a real photograph or movie still
- End each prompt with: ", {orientation}, photorealistic, cinematic film still, 8K, no text overlay"
- Return ONLY a JSON array of strings, one prompt per scene
- Number of prompts must exactly match number of scenes: {len(scenes)}

Script language: {lang}"""

    try:
        resp = requests.post(
            f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent?key={api_key}",
            json={
                "contents": [{"parts": [{"text": f"{system_prompt}\n\n--- SCENES ---\n{scenes_text}"}]}],
                "generationConfig": {"temperature": 0.7, "responseMimeType": "application/json"},
            },
            timeout=60,
        )
        resp.raise_for_status()
        data = resp.json()
        text = data["candidates"][0]["content"]["parts"][0]["text"]
        prompts = json.loads(text)
        if isinstance(prompts, list) and len(prompts) == len(scenes):
            print(f"  Gemini 프롬프트 생성 완료: {len(prompts)}개")
            return prompts
        print(f"  경고: 프롬프트 수 불일치 (기대 {len(scenes)}, 받음 {len(prompts)})", file=sys.stderr)
    except Exception as e:
        print(f"  Gemini 프롬프트 생성 실패: {e}", file=sys.stderr)

    return []


def _get_whisk_token(cookie: str) -> str:
    """Google Labs 세션 쿠키로 Whisk access_token을 얻는다."""
    import requests

    resp = requests.get(
        "https://labs.google/fx/api/auth/session",
        headers={
            "Cookie": cookie,
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        },
        timeout=30,
    )
    resp.raise_for_status()
    data = resp.json()
    token = data.get("access_token", "")
    if not token:
        raise ValueError(f"access_token 없음: {list(data.keys())}")
    return token


def generate_gemini_images(scenes: list[dict], output_dir: Path, api_key: str, aspect_ratio: str = "16:9") -> None:
    """Gemini Imagen 3 API로 이미지를 무료 생성한다."""
    import requests
    import base64

    if not api_key:
        print("경고: Gemini API 키 없음", file=sys.stderr)
        return

    ar_map = {
        "16:9": "16:9",
        "9:16": "9:16",
        "1:1": "1:1",
    }
    gemini_ar = ar_map.get(aspect_ratio, "16:9")

    todo = []
    for scene in scenes:
        image_path = output_dir / scene["image_file"]
        if image_path.exists():
            print(f"  [스킵] {scene['image_file']} 이미 존재")
            continue
        todo.append({"scene": scene, "image_path": image_path})

    if not todo:
        print("  모든 이미지 이미 존재")
        return

    print(f"  Gemini Imagen 3으로 {len(todo)}개 이미지 생성 (무료)")

    fail_count = 0
    for item in todo:
        scene = item["scene"]
        image_path = item["image_path"]

        print(f"  [Imagen] 씬 {scene['index']}: {scene['title'][:30]}...", end=" ", flush=True)

        try:
            resp = requests.post(
                f"https://generativelanguage.googleapis.com/v1beta/models/imagen-3.0-generate-002:predict?key={api_key}",
                json={
                    "instances": [{"prompt": scene["image_prompt"]}],
                    "parameters": {
                        "sampleCount": 1,
                        "aspectRatio": gemini_ar,
                    },
                },
                timeout=90,
            )
            resp.raise_for_status()
            data = resp.json()

            predictions = data.get("predictions", [])
            if predictions:
                img_b64 = predictions[0].get("bytesBase64Encoded", "")
                if img_b64:
                    image_path.write_bytes(base64.b64decode(img_b64))
                    size_kb = image_path.stat().st_size // 1024
                    print(f"OK ({size_kb}KB)")
                    fail_count = 0
                else:
                    print("FAIL (데이터 없음)", file=sys.stderr)
                    fail_count += 1
            else:
                print("FAIL (predictions 비어있음)", file=sys.stderr)
                fail_count += 1

        except requests.RequestException as e:
            print(f"FAIL ({e})", file=sys.stderr)
            scene["image_error"] = str(e)
            fail_count += 1

        if fail_count >= 5:
            print("  연속 5회 실패 → 중단", file=sys.stderr)
            return

        # Rate limit 대응
        time.sleep(1)


def generate_grok_images(scenes: list[dict], output_dir: Path, xai_api_key: str, aspect_ratio: str = "16:9") -> None:
    """Grok Aurora (grok-2-image) API로 고품질 이미지를 생성한다. $0.07/장."""
    import requests

    if not xai_api_key:
        print("경고: xAI API 키 없음 → Grok 이미지 생성 불가", file=sys.stderr)
        return

    headers = {
        "Authorization": f"Bearer {xai_api_key}",
        "Content-Type": "application/json",
    }

    todo = []
    for scene in scenes:
        image_path = output_dir / scene["image_file"]
        if image_path.exists():
            print(f"  [스킵] {scene['image_file']} 이미 존재")
            continue
        todo.append({"scene": scene, "image_path": image_path})

    if not todo:
        print("  모든 이미지 이미 존재")
        return

    print(f"  Grok Aurora로 {len(todo)}개 이미지 생성 (예상 비용: ${len(todo) * 0.07:.2f})")

    for item in todo:
        scene = item["scene"]
        image_path = item["image_path"]

        print(f"  [Grok] 씬 {scene['index']}: {scene['title'][:30]}...", end=" ", flush=True)

        payload = {
            "model": "grok-2-image",
            "prompt": scene["image_prompt"],
            "n": 1,
            "response_format": "b64_json",
        }

        try:
            resp = requests.post(
                "https://api.x.ai/v1/images/generations",
                headers=headers,
                json=payload,
                timeout=90,
            )
            resp.raise_for_status()
            data = resp.json()

            images = data.get("data", [])
            if images:
                import base64
                img_b64 = images[0].get("b64_json", "")
                if img_b64:
                    image_path.write_bytes(base64.b64decode(img_b64))
                    size_kb = image_path.stat().st_size // 1024
                    print(f"OK ({size_kb}KB)")
                else:
                    # URL 방식 폴백
                    img_url = images[0].get("url", "")
                    if img_url:
                        img_data = requests.get(img_url, timeout=60).content
                        image_path.write_bytes(img_data)
                        size_kb = len(img_data) // 1024
                        print(f"OK ({size_kb}KB)")
                    else:
                        print("FAIL (데이터 없음)", file=sys.stderr)
            else:
                print("FAIL (응답 비어있음)", file=sys.stderr)

        except requests.RequestException as e:
            print(f"FAIL ({e})", file=sys.stderr)
            scene["image_error"] = str(e)

        # Rate limit 대응 (5 req/s 제한)
        time.sleep(0.3)


def generate_stable_horde_images(scenes: list[dict], output_dir: Path, api_key: str = "", aspect_ratio: str = "16:9") -> None:
    """Stable Horde API로 각 씬의 이미지를 무료 생성한다 (최후 폴백)."""
    import requests

    # aspect ratio → 해상도 매핑 (Stable Horde 무료: 각 변 576 이하)
    ar_resolutions = {
        "16:9": (576, 320),
        "9:16": (384, 576),
        "1:1": (512, 512),
    }
    gen_w, gen_h = ar_resolutions.get(aspect_ratio, (576, 320))

    horde_url = "https://stablehorde.net/api/v2/generate/async"
    headers = {"Content-Type": "application/json", "apikey": "0000000000"}

    # 미생성 씬 수집
    todo = []
    for scene in scenes:
        image_path = output_dir / scene["image_file"]
        if image_path.exists():
            print(f"  [스킵] {scene['image_file']} 이미 존재")
            continue
        todo.append({"scene": scene, "image_path": image_path})

    if not todo:
        print("  모든 이미지 이미 존재")
        return

    # 배치 단위로 제출 + 대기 (익명 사용자 동시 요청 제한 대응)
    BATCH_SIZE = 5
    for batch_start in range(0, len(todo), BATCH_SIZE):
        batch = todo[batch_start:batch_start + BATCH_SIZE]
        batch_num = batch_start // BATCH_SIZE + 1
        total_batches = (len(todo) + BATCH_SIZE - 1) // BATCH_SIZE
        print(f"\n  --- 배치 {batch_num}/{total_batches} ({len(batch)}개) ---")

        # 제출
        jobs = []
        for item in batch:
            scene = item["scene"]
            prompt = scene["image_prompt"] + " ### blurry, cartoon, anime, drawing, low quality, text, watermark"
            payload = {
                "prompt": prompt,
                "params": {
                    "width": gen_w,
                    "height": gen_h,
                    "steps": 20,
                    "n": 1,
                    "cfg_scale": 7.0,
                },
                "nsfw": False,
            }
            try:
                r = requests.post(horde_url, headers=headers, json=payload, timeout=30)
                if r.status_code == 202:
                    job_id = r.json().get("id", "")
                    jobs.append({"scene": scene, "job_id": job_id, "image_path": item["image_path"]})
                    print(f"  [제출] 씬 {scene['index']}: {scene['title'][:25]}... → {job_id[:8]}")
                else:
                    print(f"  [실패] 씬 {scene['index']}: HTTP {r.status_code}", file=sys.stderr)
            except requests.RequestException as e:
                print(f"  [실패] 씬 {scene['index']}: {e}", file=sys.stderr)
            time.sleep(2)

        if not jobs:
            continue

        # 완료 대기
        pending = list(jobs)
        max_wait = 300
        start_time = time.time()

        while pending and (time.time() - start_time) < max_wait:
            time.sleep(10)
            still_pending = []
            for job in pending:
                try:
                    check = requests.get(
                        f"https://stablehorde.net/api/v2/generate/check/{job['job_id']}",
                        timeout=15,
                    ).json()
                    if check.get("done"):
                        result = requests.get(
                            f"https://stablehorde.net/api/v2/generate/status/{job['job_id']}",
                            timeout=30,
                        ).json()
                        for gen in result.get("generations", []):
                            img_url = gen.get("img")
                            if img_url:
                                img_data = requests.get(img_url, timeout=60).content
                                job["image_path"].write_bytes(img_data)
                                size_kb = len(img_data) // 1024
                                scene = job["scene"]
                                print(f"  [완료] 씬 {scene['index']}: {scene['title'][:25]}... ({size_kb}KB)")
                    elif check.get("faulted"):
                        scene = job["scene"]
                        print(f"  [에러] 씬 {scene['index']}: 생성 실패", file=sys.stderr)
                    else:
                        still_pending.append(job)
                except requests.RequestException:
                    still_pending.append(job)

            pending = still_pending
            if pending:
                elapsed = int(time.time() - start_time)
                print(f"  ... 대기 중: {len(pending)}개 남음 ({elapsed}초 경과)")

        if pending:
            print(f"  경고: {len(pending)}개 이미지 타임아웃", file=sys.stderr)


def generate_whisk_images(scenes: list[dict], output_dir: Path, api_key: str, aspect_ratio: str = "16:9", whisk_cookie: str = "") -> None:
    """Whisk (Google Labs ImageFX) API로 각 씬의 이미지를 생성한다 (무료)."""
    import requests
    import base64
    import random

    if not whisk_cookie:
        print("경고: Whisk 쿠키 없음 → 이미지 생성 불가", file=sys.stderr)
        return

    # 1. 세션 토큰 얻기
    print("  Whisk 인증 중...")
    try:
        token = _get_whisk_token(whisk_cookie)
        print("  인증 성공")
    except Exception as e:
        print(f"  Whisk 인증 실패: {e}", file=sys.stderr)
        return

    # aspect ratio 매핑
    ar_map = {
        "16:9": "IMAGE_ASPECT_RATIO_LANDSCAPE",
        "9:16": "IMAGE_ASPECT_RATIO_PORTRAIT",
        "1:1": "IMAGE_ASPECT_RATIO_SQUARE",
    }
    whisk_ar = ar_map.get(aspect_ratio, "IMAGE_ASPECT_RATIO_LANDSCAPE")

    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
        "Referer": "https://labs.google/",
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    }

    for scene in scenes:
        image_path = output_dir / scene["image_file"]
        if image_path.exists():
            print(f"  [스킵] {scene['image_file']} 이미 존재")
            continue

        print(f"  [생성] 씬 {scene['index']}: {scene['title']}")

        # Rate limit 대응
        if scene["index"] > 1:
            time.sleep(4)

        payload = {
            "userInput": {
                "candidatesCount": 1,
                "prompts": [scene["image_prompt"]],
                "seed": random.randint(10000, 99999),
            },
            "clientContext": {
                "sessionId": f";{int(time.time() * 1000)}",
                "tool": "IMAGE_FX",
            },
            "modelInput": {
                "modelNameType": "IMAGEN_3_5",
            },
            "aspectRatio": whisk_ar,
        }

        try:
            resp = requests.post(
                "https://aisandbox-pa.googleapis.com/v1:runImageFx",
                headers=headers,
                json=payload,
                timeout=90,
            )
            resp.raise_for_status()
            data = resp.json()

            panels = data.get("imagePanels", [])
            if panels:
                images = panels[0].get("generatedImages", [])
                if images:
                    img_b64 = images[0].get("encodedImage", "")
                    if img_b64:
                        image_path.write_bytes(base64.b64decode(img_b64))
                        size_kb = image_path.stat().st_size // 1024
                        print(f"    → {scene['image_file']} 저장 완료 ({size_kb}KB)")
                    else:
                        print(f"    → 이미지 데이터 없음", file=sys.stderr)
                else:
                    print(f"    → generatedImages 없음", file=sys.stderr)
            else:
                print(f"    → imagePanels 없음", file=sys.stderr)

        except requests.RequestException as e:
            print(f"    → API 오류: {e}", file=sys.stderr)
            scene["image_error"] = str(e)
            # 401 연속 실패 시 쿠키 만료로 판단, 즉시 중단
            if "401" in str(e) or "Unauthorized" in str(e):
                if not hasattr(generate_whisk_images, "_fail_count"):
                    generate_whisk_images._fail_count = 0
                generate_whisk_images._fail_count += 1
                if generate_whisk_images._fail_count >= 3:
                    print("  Whisk 쿠키 만료 → 중단 (폴백으로 전환)", file=sys.stderr)
                    generate_whisk_images._fail_count = 0
                    return


def generate_motion_videos(scenes: list[dict], output_dir: Path, api_key: str, hook_only: bool = True, xai_api_key: str = "") -> None:
    """이미지를 모션 영상으로 변환한다.

    xai_api_key가 있으면 Grok Imagine API 사용, 없으면 Veo API 사용.
    hook_only=True이면 핵심 씬(is_hook)만 영상으로 변환하여 비용 절약.
    """
    if xai_api_key:
        _generate_videos_grok(scenes, output_dir, xai_api_key, hook_only)
    else:
        _generate_videos_veo(scenes, output_dir, api_key, hook_only)


def _generate_videos_grok_selected(scenes: list[dict], output_dir: Path, xai_api_key: str, target_indices: set) -> None:
    """선택된 씬 인덱스만 Grok Video로 변환한다."""
    target_scenes = [s for s in scenes if s["index"] in target_indices]
    _generate_videos_grok_list(target_scenes, output_dir, xai_api_key)


def _generate_videos_grok(scenes: list[dict], output_dir: Path, xai_api_key: str, hook_only: bool) -> None:
    """Grok Imagine API로 이미지를 모션 영상으로 변환한다."""
    target_scenes = [s for s in scenes if s.get("is_hook")] if hook_only else scenes
    skip_count = len(scenes) - len(target_scenes)
    if hook_only and skip_count > 0:
        print(f"  Hook 씬만 변환: {len(target_scenes)}개 (일반 씬 {skip_count}개는 이미지 유지)")
    _generate_videos_grok_list(target_scenes, output_dir, xai_api_key)


def _generate_videos_grok_list(target_scenes: list[dict], output_dir: Path, xai_api_key: str) -> None:
    """Grok Video API로 씬 리스트를 모션 영상으로 변환한다."""
    import requests
    import base64

    headers = {
        "Authorization": f"Bearer {xai_api_key}",
        "Content-Type": "application/json",
    }

    for scene in target_scenes:
        image_path = output_dir / scene["image_file"]
        video_path = output_dir / scene["video_file"]

        if video_path.exists():
            print(f"  [스킵] {scene['video_file']} 이미 존재")
            continue
        if not image_path.exists():
            print(f"  [스킵] {scene['image_file']} 없음 → 영상 생성 불가")
            continue

        print(f"  [Grok] 씬 {scene['index']}: {scene['title']}")

        # 이미지를 base64 data URI로 변환
        img_b64 = base64.b64encode(image_path.read_bytes()).decode()
        mime = "image/jpeg" if image_path.suffix.lower() in (".jpg", ".jpeg") else "image/png"
        data_uri = f"data:{mime};base64,{img_b64}"

        motion_prompt = _get_motion_prompt(scene)
        duration = min(int(scene.get("duration", 8)), 10)

        payload = {
            "model": "grok-imagine-video",
            "prompt": motion_prompt,
            "video_url": data_uri,
            "duration": duration,
            "aspect_ratio": "16:9",
            "resolution": "720p",
        }

        try:
            # 1단계: 생성 요청
            resp = requests.post(
                "https://api.x.ai/v1/videos/generations",
                headers=headers,
                json=payload,
                timeout=60,
            )
            resp.raise_for_status()
            data = resp.json()
            request_id = data.get("request_id") or data.get("id")

            if not request_id:
                print(f"    → request_id 없음: {data}", file=sys.stderr)
                scene["video_error"] = "no request_id"
                continue

            # 2단계: 폴링으로 완료 대기
            print(f"    → 영상 생성 대기 중... (request_id: {request_id[:16]}...)")
            for attempt in range(90):  # 최대 7.5분 대기
                time.sleep(5)
                poll_resp = requests.get(
                    f"https://api.x.ai/v1/videos/{request_id}",
                    headers=headers,
                    timeout=30,
                )
                poll_data = poll_resp.json()
                status = poll_data.get("status", "")

                if status == "done":
                    video_info = poll_data.get("video", {})
                    video_url = video_info.get("url", "")
                    if video_url:
                        # 영상 다운로드
                        vid_resp = requests.get(video_url, timeout=120)
                        vid_resp.raise_for_status()
                        video_path.write_bytes(vid_resp.content)
                        print(f"    → {scene['video_file']} 저장 완료 ({len(vid_resp.content) // 1024}KB)")
                    else:
                        print(f"    → 영상 URL 없음", file=sys.stderr)
                    break
                elif status == "expired" or status == "failed":
                    err_msg = poll_data.get("error", status)
                    print(f"    → 생성 실패: {err_msg}", file=sys.stderr)
                    scene["video_error"] = str(err_msg)
                    break
                # pending 상태면 계속 대기
            else:
                print(f"    → 타임아웃: 영상 생성 시간 초과", file=sys.stderr)

        except requests.RequestException as e:
            print(f"    → API 오류: {e}", file=sys.stderr)
            scene["video_error"] = str(e)


def _generate_videos_veo(scenes: list[dict], output_dir: Path, api_key: str, hook_only: bool) -> None:
    """Veo API로 이미지를 모션 영상으로 변환한다 (폴백)."""
    import requests
    import base64

    endpoint = "https://generativelanguage.googleapis.com/v1beta/models/veo-2.0-generate-001:predict"

    target_scenes = [s for s in scenes if s.get("is_hook")] if hook_only else scenes
    skip_count = len(scenes) - len(target_scenes)
    if hook_only and skip_count > 0:
        print(f"  Hook 씬만 변환: {len(target_scenes)}개 (일반 씬 {skip_count}개는 이미지 유지)")

    for scene in target_scenes:
        image_path = output_dir / scene["image_file"]
        video_path = output_dir / scene["video_file"]

        if video_path.exists():
            print(f"  [스킵] {scene['video_file']} 이미 존재")
            continue
        if not image_path.exists():
            print(f"  [스킵] {scene['image_file']} 없음 → 영상 생성 불가")
            continue

        print(f"  [Veo] 씬 {scene['index']}: {scene['title']}")

        img_b64 = base64.b64encode(image_path.read_bytes()).decode()
        motion_prompt = _get_motion_prompt(scene)

        payload = {
            "instances": [{
                "prompt": motion_prompt,
                "image": {"bytesBase64Encoded": img_b64},
            }],
            "parameters": {
                "sampleCount": 1,
                "durationSeconds": min(int(scene.get("duration", 5)), 8),
            },
        }

        try:
            resp = requests.post(
                f"{endpoint}?key={api_key}",
                json=payload,
                timeout=120,
            )
            resp.raise_for_status()
            data = resp.json()

            operation = data.get("name")
            if operation:
                print(f"    → 영상 생성 대기 중...")
                for attempt in range(60):
                    time.sleep(5)
                    poll_resp = requests.get(
                        f"https://generativelanguage.googleapis.com/v1beta/{operation}?key={api_key}",
                        timeout=30,
                    )
                    poll_data = poll_resp.json()
                    if poll_data.get("done"):
                        result = poll_data.get("response", {})
                        videos = result.get("generateVideoResponse", {}).get("generatedSamples", [])
                        if not videos:
                            videos = result.get("predictions", [])
                        if videos:
                            vid_data = videos[0]
                            vid_b64 = vid_data.get("video", {}).get("bytesBase64Encoded", "") or vid_data.get("bytesBase64Encoded", "")
                            if vid_b64:
                                video_path.write_bytes(base64.b64decode(vid_b64))
                                print(f"    → {scene['video_file']} 저장 완료")
                        break
                else:
                    print(f"    → 타임아웃", file=sys.stderr)

        except requests.RequestException as e:
            print(f"    → API 오류: {e}", file=sys.stderr)
            scene["video_error"] = str(e)


def _get_motion_prompt(scene: dict) -> str:
    """씬 내용에 맞는 모션 프롬프트를 생성한다."""
    title_lower = scene.get("title", "").lower()

    if any(kw in title_lower for kw in ["인트로", "intro", "hook", "훅", "오프닝"]):
        return "dynamic camera zoom in, energetic motion, cinematic opening"
    elif any(kw in title_lower for kw in ["결론", "conclusion", "마무리", "ending"]):
        return "slow camera pull back, gentle fade, peaceful ending motion"
    elif any(kw in title_lower for kw in ["전환", "transition"]):
        return "smooth camera pan, gentle transition motion"
    else:
        return "subtle camera motion, slow zoom in, gentle parallax effect"


def _build_zoompan_filter(effect: str, frames: int, w: int, h: int, sw: int, sh: int) -> str:
    """duration-adaptive zoompan 필터를 생성한다. ease-in-out으로 부드러운 모션."""
    # progress: 0→1 (ease-in-out using smoothstep: 3t²-2t³)
    # on = current frame number (0-indexed in zoompan)
    t = f"(on/{frames})"
    smooth = f"(3*{t}*{t}-2*{t}*{t}*{t})"  # smoothstep easing

    if effect == "zoom_in":
        # 1.0 → 1.15 with easing
        z = f"1.0+0.15*{smooth}"
        x = "iw/2-(iw/zoom/2)"
        y = "ih/2-(ih/zoom/2)"
    elif effect == "zoom_out":
        # 1.15 → 1.0 with easing (reverse smoothstep)
        z = f"1.15-0.15*{smooth}"
        x = "iw/2-(iw/zoom/2)"
        y = "ih/2-(ih/zoom/2)"
    elif effect == "pan_left":
        # zoom 1.12 고정, x: 오른쪽→왼쪽 이동 with easing
        z = "1.12"
        max_x = "iw*0.06"
        x = f"({max_x})*(1-{smooth})"
        y = "ih/2-(ih/zoom/2)"
    elif effect == "pan_right":
        # zoom 1.12 고정, x: 왼쪽→오른쪽 이동 with easing
        z = "1.12"
        max_x = "iw*0.06"
        x = f"({max_x})*{smooth}"
        y = "ih/2-(ih/zoom/2)"
    else:
        z = "1.0"
        x = "iw/2-(iw/zoom/2)"
        y = "ih/2-(ih/zoom/2)"

    return f"scale={sw}x{sh},zoompan=z='{z}':x='{x}':y='{y}':d={frames}:s={w}x{h}:fps=30"

FFMPEG_EFFECT_CYCLE = ["zoom_in", "zoom_out", "pan_left", "pan_right"]


def generate_ffmpeg_motion(scenes: list[dict], output_dir: Path, aspect_ratio: str = "16:9") -> None:
    """ffmpeg zoompan 필터로 이미지를 모션 영상(mp4)으로 변환한다 (무료, 로컬)."""
    import subprocess

    resolutions = {
        "16:9": (1920, 1080),
        "9:16": (1080, 1920),
        "1:1": (1080, 1080),
    }
    w, h = resolutions.get(aspect_ratio, (1920, 1080))

    for i, scene in enumerate(scenes):
        image_path = output_dir / scene["image_file"]
        video_path = output_dir / scene["video_file"]

        if video_path.exists():
            print(f"  [스킵] {scene['video_file']} 이미 존재")
            continue
        if not image_path.exists():
            print(f"  [스킵] {scene['image_file']} 없음")
            continue

        duration = scene.get("duration", 6.0)
        frames = int(duration * 30)
        effect_name = FFMPEG_EFFECT_CYCLE[i % len(FFMPEG_EFFECT_CYCLE)]
        # 입력 이미지를 출력의 2배로 스케일 (zoompan 떨림 방지)
        sw, sh = w * 2, h * 2
        vf = _build_zoompan_filter(effect_name, frames, w, h, sw, sh)

        cmd = [
            "ffmpeg", "-y", "-loop", "1", "-i", str(image_path),
            "-vf", vf,
            "-c:v", "libx264", "-t", str(round(duration, 1)),
            "-pix_fmt", "yuv420p", str(video_path),
        ]

        print(f"  [{effect_name:9s}] 씬 {scene['index']:02d}: {scene['title'][:20]}...", end=" ", flush=True)
        try:
            r = subprocess.run(cmd, capture_output=True, timeout=120)
            if r.returncode == 0:
                size_kb = video_path.stat().st_size // 1024
                print(f"OK ({size_kb}KB)")
            else:
                print("FAIL", file=sys.stderr)
                scene["video_error"] = r.stderr.decode(errors="ignore")[-200:]
        except subprocess.TimeoutExpired:
            print("TIMEOUT", file=sys.stderr)
            scene["video_error"] = "ffmpeg timeout"


def load_settings() -> dict:
    """settings.json에서 설정을 로드한다."""
    settings_path = Path(__file__).parent.parent / "settings.json"
    if settings_path.exists():
        return json.loads(settings_path.read_text(encoding="utf-8"))
    return {}


def main() -> None:
    parser = argparse.ArgumentParser(description="Whisk 이미지 + 모션 영상 생성")
    parser.add_argument("script", help="마크다운 대본 파일")
    parser.add_argument("srt", help="SRT 자막 파일 (타임코드 매핑용)")
    parser.add_argument("output_dir", help="출력 디렉토리")
    parser.add_argument("--lang", default="ko", help="언어 코드 (기본: ko)")
    parser.add_argument(
        "--aspect-ratio", default="16:9",
        choices=["16:9", "9:16", "1:1"],
        help="화면 비율 (기본: 16:9)",
    )
    parser.add_argument(
        "--max-scenes", type=int, default=25,
        help="최대 씬 수 (기본: 25). 씬이 적을수록 비용 절약",
    )
    parser.add_argument(
        "--prompts-only", action="store_true",
        help="프롬프트만 생성하고 API 호출은 건너뛴다",
    )
    parser.add_argument(
        "--quality", default="free",
        choices=["free", "premium"],
        help="품질 모드: free(Whisk→Stable Horde, ffmpeg만) / premium(Grok Aurora+Video, 유료)",
    )
    parser.add_argument(
        "--video-scenes", type=int, default=0,
        help="Grok Video로 변환할 씬 수 (0=Hook만 자동선택, -1=전부, N=상위 N개)",
    )
    args = parser.parse_args()

    script_path = Path(args.script)
    srt_path = Path(args.srt)

    if not script_path.exists():
        print(f"오류: {script_path} 없음", file=sys.stderr)
        sys.exit(1)
    if not srt_path.exists():
        print(f"오류: {srt_path} 없음", file=sys.stderr)
        sys.exit(1)

    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    settings = load_settings()
    api_key = settings.get("tts", {}).get("api_key", "")

    # 1. 대본에서 섹션 추출
    md_text = script_path.read_text(encoding="utf-8")
    sections = extract_sections(md_text, max_scenes=args.max_scenes)
    print(f"대본 섹션: {len(sections)}개")

    # 2. SRT 타임코드 파싱
    srt_entries = parse_srt_timestamps(str(srt_path))
    print(f"자막 엔트리: {len(srt_entries)}개")

    # 3. 씬-타임코드 매핑
    scenes = map_scenes_to_timecodes(sections, srt_entries)
    print(f"씬 매핑: {len(scenes)}개")

    # 4. 이미지 프롬프트 생성 (Gemini AI로 정확한 프롬프트)
    scenes = generate_image_prompts(scenes, args.lang, args.aspect_ratio, api_key)

    # scenes.json 저장
    scenes_json_path = output_dir / "scenes.json"
    scenes_json_path.write_text(
        json.dumps(scenes, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(f"씬 정보 저장: {scenes_json_path}")

    if args.prompts_only:
        print("\n--prompts-only: API 호출 건너뜀")
        for scene in scenes:
            print(f"  씬 {scene['index']}: {scene['image_prompt'][:80]}...")
        return

    if not api_key:
        print("경고: API 키 없음 → 프롬프트만 저장됨", file=sys.stderr)
        return

    xai_api_key = settings.get("xai", {}).get("api_key", "")
    whisk_cookie = settings.get("whisk", {}).get("cookie", "")
    is_premium = args.quality == "premium"

    # Grok Video 대상 씬 결정
    video_scene_count = args.video_scenes  # 0=Hook자동, -1=전부, N=상위N개
    if is_premium:
        from xai_credits import get_credit_status, estimate_cost

        # video 대상 수 계산
        if video_scene_count == -1:
            video_target_count = len(scenes)
        elif video_scene_count == 0:
            video_target_count = sum(1 for s in scenes if _is_hook_scene(s))
        else:
            video_target_count = min(video_scene_count, len(scenes))

        cost = estimate_cost(len(scenes), video_target_count)
        credit = get_credit_status()

        print(f"\n{'='*55}")
        print(f"  품질 모드: PREMIUM")
        print(f"  이미지: {len(scenes)}장 × $0.07 = ${len(scenes) * 0.07:.2f}")
        print(f"  영상:   {video_target_count}개 × ~$0.25 = ${video_target_count * 0.25:.2f}")
        print(f"  ────────────────────────────")
        print(f"  합계:   ${cost['total_cost']:.2f}")
        print(f"{'='*55}")

        if not credit["has_key"] or not credit["key_valid"]:
            print(f"\n  xAI API 키 문제: {credit.get('error', '키 없음')}")
            print(f"  → 무료 모드(free)로 전환합니다.\n")
            is_premium = False
        elif credit["balance_known"]:
            balance = credit["balance_usd"]
            print(f"  크레딧 잔액: ${balance:.2f}")
            if balance >= cost["total_cost"]:
                print(f"  잔액 충분 → 진행합니다.")
            else:
                print(f"  잔액 부족 (${balance:.2f} < ${cost['total_cost']:.2f})")
                print(f"  충전: https://console.x.ai → Billing")
                print(f"  → 무료 모드(free)로 전환합니다.\n")
                is_premium = False
        else:
            print(f"  잔액 확인 불가 → API 호출 시도, 실패 시 무료 폴백")

        print()
    else:
        print(f"\n{'='*55}")
        print(f"  품질 모드: FREE (비용: $0)")
        print(f"{'='*55}\n")

    # 5. 이미지 생성
    missing = [s for s in scenes if not (output_dir / s["image_file"]).exists()]

    if is_premium:
        # 유료: Grok Aurora
        if not xai_api_key:
            print("오류: xAI API 키가 없습니다. settings.json에 xai.api_key를 설정하세요.", file=sys.stderr)
            sys.exit(1)
        print(f"\n=== 이미지 생성 [Grok Aurora] ({len(missing)}개) ===")
        generate_grok_images(scenes, output_dir, xai_api_key, args.aspect_ratio)
    else:
        # 무료: Whisk
        if not whisk_cookie:
            print("오류: Whisk 쿠키가 없습니다. settings.json에 whisk.cookie를 설정하세요.", file=sys.stderr)
            sys.exit(1)
        print(f"\n=== 이미지 생성 [Whisk ImageFX] ({len(missing)}개) ===")
        generate_whisk_images(scenes, output_dir, api_key, args.aspect_ratio, whisk_cookie=whisk_cookie)

    missing = [s for s in scenes if not (output_dir / s["image_file"]).exists()]
    if missing:
        print(f"\n경고: {len(missing)}개 이미지 미생성", file=sys.stderr)

    # 6. 모션 영상 생성
    if is_premium and xai_api_key:
        # Premium: 선택된 씬은 Grok Video, 나머지 ffmpeg
        if video_scene_count == -1:
            # 전체 씬 Grok Video
            grok_targets = [s for s in scenes if not (output_dir / s["video_file"]).exists()]
        elif video_scene_count == 0:
            # Hook 씬만 자동
            grok_targets = [s for s in scenes if s.get("is_hook") and not (output_dir / s["video_file"]).exists()]
        else:
            # 상위 N개 (Hook 우선, 나머지는 앞에서부터)
            hooks = [s for s in scenes if s.get("is_hook") and not (output_dir / s["video_file"]).exists()]
            non_hooks = [s for s in scenes if not s.get("is_hook") and not (output_dir / s["video_file"]).exists()]
            grok_targets = (hooks + non_hooks)[:video_scene_count]

        if grok_targets:
            # Grok Video 대상 씬에 마킹
            grok_indices = {s["index"] for s in grok_targets}
            for s in scenes:
                if s["index"] in grok_indices:
                    s["use_grok_video"] = True

            print(f"\n=== 모션 영상 [Grok Video - {len(grok_targets)}개] ===")
            _generate_videos_grok_selected(scenes, output_dir, xai_api_key, grok_indices)

        print(f"\n=== 모션 영상 [ffmpeg zoompan - 나머지] ===")
        generate_ffmpeg_motion(scenes, output_dir, args.aspect_ratio)
    else:
        # Free: 전부 ffmpeg
        print(f"\n=== 모션 영상 [ffmpeg zoompan - 전체] ===")
        generate_ffmpeg_motion(scenes, output_dir, args.aspect_ratio)

    # scenes.json 업데이트 (에러 정보 포함)
    scenes_json_path.write_text(
        json.dumps(scenes, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    print(f"\n완료: {output_dir}")


if __name__ == "__main__":
    main()
