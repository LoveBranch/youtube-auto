"""Channel Factory - 채널 분석 엔드포인트."""

import json
import re
from urllib.parse import unquote
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
import requests

from server.config import settings

router = APIRouter()

YOUTUBE_API_KEY = settings.get("youtube", {}).get("api_key", "")
GEMINI_KEY = settings.get("tts", {}).get("api_key", "") or settings.get("gemini", {}).get("api_key", "")


class ChannelAnalyzeRequest(BaseModel):
    channel_url: str


def extract_channel_id(url: str) -> str:
    """YouTube URL에서 채널 ID 또는 handle 추출."""
    url = unquote(url.strip().rstrip("/"))
    # @handle
    m = re.search(r"youtube\.com/@([\w.-]+)", url)
    if m:
        return f"@{m.group(1)}"
    # /channel/UC...
    m = re.search(r"youtube\.com/channel/([\w-]+)", url)
    if m:
        return m.group(1)
    # /c/name or /user/name
    m = re.search(r"youtube\.com/(?:c|user)/([\w.-]+)", url)
    if m:
        return m.group(1)
    raise ValueError(f"Cannot parse channel ID from URL: {url}")


def fetch_channel_info(channel_ref: str) -> dict:
    """YouTube Data API로 채널 기본 정보 가져오기."""
    if not YOUTUBE_API_KEY:
        raise HTTPException(status_code=500, detail="YouTube API key not configured")

    # handle(@xxx) → forHandle, UCxxx → id
    if channel_ref.startswith("@"):
        params = {"forHandle": channel_ref, "part": "id,snippet,statistics", "key": YOUTUBE_API_KEY}
    elif channel_ref.startswith("UC"):
        params = {"id": channel_ref, "part": "id,snippet,statistics", "key": YOUTUBE_API_KEY}
    else:
        params = {"forUsername": channel_ref, "part": "id,snippet,statistics", "key": YOUTUBE_API_KEY}

    resp = requests.get("https://www.googleapis.com/youtube/v3/channels", params=params, timeout=15)
    if not resp.ok:
        raise HTTPException(status_code=502, detail=f"YouTube API error: {resp.text[:200]}")
    data = resp.json()
    items = data.get("items", [])
    if not items:
        raise HTTPException(status_code=404, detail="Channel not found")
    return items[0]


def fetch_recent_videos(channel_id: str, max_results: int = 20) -> list:
    """채널의 최근 영상 목록 가져오기."""
    if not YOUTUBE_API_KEY:
        return []
    # uploads playlist ID: UC... → UU...
    playlist_id = "UU" + channel_id[2:]
    params = {
        "playlistId": playlist_id,
        "part": "snippet",
        "maxResults": max_results,
        "key": YOUTUBE_API_KEY,
    }
    resp = requests.get("https://www.googleapis.com/youtube/v3/playlistItems", params=params, timeout=15)
    if not resp.ok:
        return []
    items = resp.json().get("items", [])
    videos = []
    for item in items:
        snippet = item.get("snippet", {})
        videos.append({
            "title": snippet.get("title", ""),
            "description": snippet.get("description", "")[:200],
            "published": snippet.get("publishedAt", "")[:10],
            "thumbnail": snippet.get("thumbnails", {}).get("medium", {}).get("url", ""),
        })
    return videos


def analyze_channel_with_gemini(channel_name: str, videos: list) -> dict:
    """Gemini로 채널 스타일 분석."""
    if not GEMINI_KEY:
        return {
            "tone": "educational",
            "format": "documentary",
            "language": "ko",
            "target_audience": "general",
            "title_pattern": "keyword",
            "content_pillars": [],
            "avg_duration_minutes": 5,
        }

    titles = "\n".join([f"- {v['title']}" for v in videos[:15]])
    prompt = f"""YouTube 채널 "{channel_name}"의 최근 영상 제목들을 분석해서 채널 스타일 프로필을 JSON으로 반환해주세요.

최근 영상 제목:
{titles}

다음 JSON 형식으로만 응답하세요 (다른 텍스트 없이):
{{
  "tone": "educational|entertaining|news|motivational|tutorial|commentary",
  "format": "talking-head|documentary|tutorial|vlog|news|animation",
  "language": "ko|en|ja|zh",
  "target_audience": "간단한 설명",
  "title_pattern": "숫자형|질문형|키워드형|감성형|자극형",
  "content_pillars": ["주제1", "주제2", "주제3"],
  "avg_duration_minutes": 5,
  "default_voice": "Kore",
  "thumbnail_style": "dark|bright|minimal|bold"
}}"""

    resp = requests.post(
        f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.0-flash:generateContent?key={GEMINI_KEY}",
        json={"contents": [{"parts": [{"text": prompt}]}]},
        headers={"Content-Type": "application/json"},
        timeout=30,
    )
    if not resp.ok:
        return {"tone": "educational", "format": "documentary", "language": "ko",
                "target_audience": "general", "title_pattern": "keyword",
                "content_pillars": [], "avg_duration_minutes": 5}

    text = resp.json()["candidates"][0]["content"]["parts"][0]["text"]
    # JSON 추출
    json_match = re.search(r"\{[\s\S]*\}", text)
    if json_match:
        try:
            return json.loads(json_match.group())
        except Exception:
            pass
    return {"tone": "educational", "format": "documentary", "language": "ko",
            "target_audience": "general", "title_pattern": "keyword",
            "content_pillars": [], "avg_duration_minutes": 5}


def build_thumbnail_template(style_profile: dict, videos: list) -> dict:
    """채널 스타일 기반 썸네일 템플릿 생성."""
    thumbnail_style = style_profile.get("thumbnail_style", "dark")
    color_map = {
        "dark": {"bg": "#1a1a2e", "text": "#ffffff", "accent": "#e94560"},
        "bright": {"bg": "#ffffff", "text": "#1a1a1a", "accent": "#ff6b35"},
        "minimal": {"bg": "#f8f9fa", "text": "#212529", "accent": "#6c757d"},
        "bold": {"bg": "#ff0000", "text": "#ffffff", "accent": "#ffdd00"},
    }
    colors = color_map.get(thumbnail_style, color_map["dark"])
    return {
        "background_color": colors["bg"],
        "text_color": colors["text"],
        "accent_color": colors["accent"],
        "text_position": "bottom-left",
        "font_size": "large",
        "has_overlay": True,
        "overlay_opacity": 0.6,
        "style": thumbnail_style,
    }


@router.post("/channel/analyze")
async def analyze_channel(req: ChannelAnalyzeRequest):
    """YouTube 채널 분석 → 스타일 프로필 + 썸네일 템플릿 반환."""
    try:
        channel_ref = extract_channel_id(req.channel_url)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    # 채널 기본 정보
    channel_info = fetch_channel_info(channel_ref)
    channel_id = channel_info["id"]
    snippet = channel_info.get("snippet", {})
    statistics = channel_info.get("statistics", {})

    channel_name = snippet.get("title", "Unknown Channel")
    channel_avatar = snippet.get("thumbnails", {}).get("medium", {}).get("url", "")
    subscriber_count = int(statistics.get("subscriberCount", 0))

    # 최근 영상
    recent_videos = fetch_recent_videos(channel_id)

    # Gemini 스타일 분석
    style_profile = analyze_channel_with_gemini(channel_name, recent_videos)

    # 썸네일 템플릿
    thumbnail_template = build_thumbnail_template(style_profile, recent_videos)

    return {
        "channel_id": channel_id,
        "channel_name": channel_name,
        "channel_avatar": channel_avatar,
        "subscriber_count": subscriber_count,
        "style_profile": style_profile,
        "thumbnail_template": thumbnail_template,
        "recent_videos": recent_videos,
    }
