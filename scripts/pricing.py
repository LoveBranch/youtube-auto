"""
영상 생성 가격 계산 모듈

ContentFission 플랜별 크레딧 가치를 기반으로 계산한다.
크레딧 1개의 실제 가치는 플랜마다 다르므로, API 비용을 크레딧으로 환산할 때
플랜별 단가를 적용한다.

사용법:
    from pricing import calculate_price, to_credits

    price = calculate_price(num_scenes=30, num_videos=5, quality="premium")
    credits = to_credits(price, plan="pro")
"""

import math

# === API 단가 (USD) ===
GROK_AURORA_PER_IMAGE = 0.07     # Grok Aurora 이미지 1장
GROK_VIDEO_PER_CLIP = 0.25       # Grok Video 1개 (추정)

# === ContentFission 플랜별 크레딧 ===
PLANS = {
    "free":     {"price_usd": 0,     "credits": 30,   "usd_per_credit": 0},
    "pro":      {"price_usd": 9.99,  "credits": 150,  "usd_per_credit": round(9.99 / 150, 4)},
    "scale":    {"price_usd": 19.99, "credits": 400,  "usd_per_credit": round(19.99 / 400, 4)},
    "business": {"price_usd": 49.00, "credits": 1200, "usd_per_credit": round(49.00 / 1200, 4)},
}
# pro: $0.0666/credit, scale: $0.05/credit, business: $0.0408/credit


def calculate_price(
    num_scenes: int,
    num_videos: int = 0,
    quality: str = "free",
) -> dict:
    """영상 생성 예상 API 비용을 계산한다."""
    if quality == "free":
        return {
            "quality": "free",
            "num_scenes": num_scenes,
            "num_videos": 0,
            "image_cost": 0.0,
            "video_cost": 0.0,
            "total_api_cost": 0.0,
            "is_free": True,
        }

    image_cost = round(num_scenes * GROK_AURORA_PER_IMAGE, 2)
    video_cost = round(num_videos * GROK_VIDEO_PER_CLIP, 2)
    total_api = round(image_cost + video_cost, 2)

    return {
        "quality": "premium",
        "num_scenes": num_scenes,
        "num_videos": num_videos,
        "image_cost": image_cost,
        "video_cost": video_cost,
        "total_api_cost": total_api,
        "is_free": False,
    }


def to_credits(price: dict, plan: str = "pro") -> dict:
    """API 비용을 해당 플랜의 크레딧으로 환산한다.

    Returns:
        {
            "plan": str,
            "credits_needed": int,
            "credits_available": int,
            "usd_per_credit": float,
            "affordable": bool,
        }
    """
    plan_info = PLANS.get(plan, PLANS["pro"])

    if price["is_free"]:
        return {
            "plan": plan,
            "credits_needed": 0,
            "credits_available": plan_info["credits"],
            "usd_per_credit": plan_info["usd_per_credit"],
            "affordable": True,
        }

    usd_per_credit = plan_info["usd_per_credit"]
    if usd_per_credit <= 0:
        # Free 플랜은 유료 서비스 사용 불가
        return {
            "plan": plan,
            "credits_needed": -1,
            "credits_available": plan_info["credits"],
            "usd_per_credit": 0,
            "affordable": False,
            "reason": "Free 플랜은 Premium을 사용할 수 없습니다. Pro 이상 플랜으로 업그레이드하세요.",
        }

    credits_needed = math.ceil(price["total_api_cost"] / usd_per_credit)
    credits_needed = max(credits_needed, 1)

    return {
        "plan": plan,
        "credits_needed": credits_needed,
        "credits_available": plan_info["credits"],
        "usd_per_credit": usd_per_credit,
        "affordable": credits_needed <= plan_info["credits"],
    }


def get_video_options(num_scenes: int) -> list[dict]:
    """사용자에게 보여줄 Grok Video 옵션 목록."""
    options = [
        {"label": "없음 (ffmpeg만)", "num_videos": 0},
    ]

    hook_estimate = max(3, num_scenes // 7)
    options.append({"label": f"핵심 씬만 ({hook_estimate}개)", "num_videos": hook_estimate})

    half = num_scenes // 2
    if half > hook_estimate:
        options.append({"label": f"절반 ({half}개)", "num_videos": half})

    options.append({"label": f"전체 ({num_scenes}개)", "num_videos": num_scenes})

    return options


def format_breakdown(price: dict, plan: str = "pro", lang: str = "ko") -> str:
    """사람이 읽을 수 있는 가격 + 크레딧 내역."""
    if price["is_free"]:
        return "FREE (0 크레딧)" if lang == "ko" else "FREE (0 credits)"

    cr = to_credits(price, plan)
    lines = []

    if lang == "ko":
        lines.append(f"이미지 {price['num_scenes']}장 × $0.07 = ${price['image_cost']:.2f}")
        if price["num_videos"] > 0:
            lines.append(f"AI 영상 {price['num_videos']}개 × $0.25 = ${price['video_cost']:.2f}")
        lines.append(f"API 비용: ${price['total_api_cost']:.2f}")
        lines.append(f"필요 크레딧: {cr['credits_needed']}개 ({plan} 플랜 월 {cr['credits_available']}개)")
    else:
        lines.append(f"{price['num_scenes']} images × $0.07 = ${price['image_cost']:.2f}")
        if price["num_videos"] > 0:
            lines.append(f"{price['num_videos']} AI videos × $0.25 = ${price['video_cost']:.2f}")
        lines.append(f"API cost: ${price['total_api_cost']:.2f}")
        lines.append(f"Credits needed: {cr['credits_needed']} ({plan} plan: {cr['credits_available']}/mo)")

    return "\n".join(lines)


if __name__ == "__main__":
    print("=" * 60)
    print("  영상 생성 가격 시뮬레이션 (30씬 기준)")
    print("=" * 60)

    for plan_name in ["free", "pro", "scale", "business"]:
        plan_info = PLANS[plan_name]
        print(f"\n{'─'*60}")
        print(f"  {plan_name.upper()} 플랜 (${plan_info['price_usd']}/월, {plan_info['credits']}크레딧)")
        if plan_info["usd_per_credit"] > 0:
            print(f"  크레딧 1개 = ${plan_info['usd_per_credit']:.4f}")
        print(f"{'─'*60}")

        # FREE 품질
        print(f"\n  🆓 FREE 품질: 0 크레딧")

        # PREMIUM 품질
        if plan_name == "free":
            print(f"\n  ⭐ PREMIUM: 사용 불가 (Pro 이상 필요)")
            continue

        for opt in get_video_options(30):
            price = calculate_price(30, opt["num_videos"], "premium")
            cr = to_credits(price, plan_name)
            max_count = plan_info["credits"] // cr["credits_needed"] if cr["credits_needed"] > 0 else 0
            print(f"\n  ⭐ {opt['label']}")
            print(f"     API: ${price['total_api_cost']:.2f} → {cr['credits_needed']} 크레딧 → 월 {max_count}개 가능")
