"""
xAI API 크레딧 잔액 확인 유틸리티

사용법:
    py scripts/xai_credits.py                    # 잔액 확인
    py scripts/xai_credits.py --check-cost 2.10  # 잔액이 $2.10 이상인지 확인

settings.json에서 xai.management_api_key와 xai.team_id를 읽는다.
Management API 키가 없으면 일반 API 키로 테스트 호출하여 유효성만 확인한다.
"""

import argparse
import json
import sys
from pathlib import Path

import requests

SETTINGS_PATH = Path(__file__).resolve().parent.parent / "settings.json"


def load_settings() -> dict:
    if SETTINGS_PATH.exists():
        return json.loads(SETTINGS_PATH.read_text(encoding="utf-8"))
    return {}


def check_balance_management(management_key: str, team_id: str) -> dict:
    """Management API로 프리페이드 잔액을 조회한다.

    Returns:
        {"available": True/False, "balance_usd": float, "raw": dict}
    """
    resp = requests.get(
        f"https://management-api.x.ai/v1/billing/teams/{team_id}/prepaid/balance",
        headers={
            "Authorization": f"Bearer {management_key}",
            "Content-Type": "application/json",
        },
        timeout=15,
    )
    resp.raise_for_status()
    data = resp.json()

    # 잔액은 cents 단위
    balance_cents = data.get("balance", data.get("remaining_balance", 0))
    if isinstance(balance_cents, dict):
        balance_cents = balance_cents.get("amount", 0)
    balance_usd = balance_cents / 100.0

    return {
        "available": True,
        "balance_usd": balance_usd,
        "raw": data,
    }


def check_api_key_valid(api_key: str) -> dict:
    """일반 API 키로 간단한 모델 목록 요청을 보내 유효성을 확인한다.

    Returns:
        {"available": True/False, "balance_usd": None, "error": str or None}
    """
    try:
        resp = requests.get(
            "https://api.x.ai/v1/models",
            headers={"Authorization": f"Bearer {api_key}"},
            timeout=10,
        )
        if resp.status_code == 200:
            return {"available": True, "balance_usd": None, "error": None}
        elif resp.status_code == 401:
            return {"available": False, "balance_usd": None, "error": "API 키 무효"}
        elif resp.status_code == 429:
            return {"available": True, "balance_usd": None, "error": "Rate limit (키는 유효)"}
        else:
            return {"available": False, "balance_usd": None, "error": f"HTTP {resp.status_code}"}
    except requests.RequestException as e:
        return {"available": False, "balance_usd": None, "error": str(e)}


def get_credit_status() -> dict:
    """settings.json 기반으로 xAI 크레딧 상태를 확인한다.

    Returns:
        {
            "has_key": bool,
            "key_valid": bool,
            "balance_usd": float or None,  # None이면 잔액 확인 불가
            "balance_known": bool,
            "error": str or None,
        }
    """
    settings = load_settings()
    xai = settings.get("xai", {})
    api_key = xai.get("api_key", "")
    mgmt_key = xai.get("management_api_key", "")
    team_id = xai.get("team_id", "")

    if not api_key:
        return {
            "has_key": False,
            "key_valid": False,
            "balance_usd": None,
            "balance_known": False,
            "error": "xai.api_key가 settings.json에 없음",
        }

    # 1) Management API로 정확한 잔액 확인 시도
    if mgmt_key and team_id:
        try:
            result = check_balance_management(mgmt_key, team_id)
            return {
                "has_key": True,
                "key_valid": True,
                "balance_usd": result["balance_usd"],
                "balance_known": True,
                "error": None,
            }
        except Exception as e:
            # Management API 실패 → 일반 키 유효성으로 폴백
            pass

    # 2) 일반 API 키 유효성만 확인
    result = check_api_key_valid(api_key)
    return {
        "has_key": True,
        "key_valid": result["available"],
        "balance_usd": None,
        "balance_known": False,
        "error": result.get("error"),
    }


def estimate_cost(num_scenes: int, include_video_hooks: int = 0) -> dict:
    """예상 비용을 계산한다.

    Args:
        num_scenes: 총 씬 수
        include_video_hooks: Grok Video로 변환할 Hook 씬 수

    Returns:
        {"image_cost": float, "video_cost": float, "total_cost": float, "breakdown": str}
    """
    image_cost = num_scenes * 0.07  # Grok Aurora $0.07/장
    video_cost = include_video_hooks * 0.25  # Grok Video 추정 $0.25/개
    total = image_cost + video_cost

    breakdown = f"이미지 {num_scenes}장 × $0.07 = ${image_cost:.2f}"
    if include_video_hooks > 0:
        breakdown += f" + 영상 {include_video_hooks}개 × ~$0.25 = ${video_cost:.2f}"
    breakdown += f" → 합계 ${total:.2f}"

    return {
        "image_cost": image_cost,
        "video_cost": video_cost,
        "total_cost": total,
        "breakdown": breakdown,
    }


def main():
    parser = argparse.ArgumentParser(description="xAI 크레딧 잔액 확인")
    parser.add_argument(
        "--check-cost", type=float, default=0,
        help="이 금액 이상 잔액이 있는지 확인 (USD)",
    )
    parser.add_argument(
        "--json", action="store_true",
        help="JSON 형식으로 출력",
    )
    args = parser.parse_args()

    status = get_credit_status()

    if args.json:
        if args.check_cost > 0:
            status["required_usd"] = args.check_cost
            if status["balance_known"]:
                status["sufficient"] = status["balance_usd"] >= args.check_cost
            else:
                status["sufficient"] = None  # 알 수 없음
        print(json.dumps(status, ensure_ascii=False, indent=2))
        return

    # 사람용 출력
    if not status["has_key"]:
        print("xAI API 키가 설정되어 있지 않습니다.")
        print("settings.json → xai.api_key에 키를 추가하세요.")
        sys.exit(1)

    if not status["key_valid"]:
        print(f"xAI API 키가 유효하지 않습니다: {status['error']}")
        sys.exit(1)

    print("xAI API 키: 유효")

    if status["balance_known"]:
        balance = status["balance_usd"]
        print(f"프리페이드 잔액: ${balance:.2f}")

        if args.check_cost > 0:
            if balance >= args.check_cost:
                print(f"충분: ${balance:.2f} >= ${args.check_cost:.2f}")
            else:
                print(f"부족: ${balance:.2f} < ${args.check_cost:.2f}")
                print("크레딧을 충전하세요: https://console.x.ai → Billing")
                sys.exit(2)
    else:
        print("잔액 확인 불가 (Management API 키 미설정)")
        print("정확한 잔액 확인을 위해 settings.json에 추가하세요:")
        print("  xai.management_api_key: Management API 키")
        print("  xai.team_id: 팀 ID")
        print("발급: https://console.x.ai → API Keys → Management")


if __name__ == "__main__":
    main()
