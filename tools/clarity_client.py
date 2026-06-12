"""
clarity_client.py — Microsoft Clarity behavioral signals

يسحب بيانات سلوك الزوار من Clarity API.
يعمل فقط للعملاء اللي عندهم clarity_config.py — العزل مضمون.

الاستخدام:
    from tools.clarity_client import get_clarity
    data = get_clarity("noura", num_days=1)
    # data = None إذا ما في config للعميل (زين مثلاً)
"""

import importlib
import json
import urllib.request
import urllib.parse

_BASE = "https://www.clarity.ms/export-data/api/v1"


def get_clarity(client: str, num_days: int = 1) -> dict | None:
    """
    Fetch behavioral signals from Clarity for the given client.

    Args:
        client:   اسم العميل مثل "noura"
        num_days: آخر كم 24 ساعة (1, 2, أو 3)

    Returns:
        dict مع الإشارات السلوكية — أو None لو ما في config للعميل
    """
    try:
        cfg = importlib.import_module(f"clients.{client}.clarity_config")
        token = cfg.CLARITY_TOKEN
        base  = getattr(cfg, "CLARITY_BASE_URL", _BASE)
    except (ImportError, AttributeError):
        return None

    try:
        params = urllib.parse.urlencode({"numOfDays": num_days})
        req = urllib.request.Request(
            f"{base}/project-live-insights?{params}",
            headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
        )
        with urllib.request.urlopen(req, timeout=15) as resp:
            return _parse(json.loads(resp.read()))
    except Exception:
        return None


def _parse(raw: list) -> dict:
    idx = {m["metricName"]: m["information"] for m in raw}

    traffic    = (idx.get("Traffic")        or [{}])[0]
    scroll     = (idx.get("ScrollDepth")    or [{}])[0]
    engage     = (idx.get("EngagementTime") or [{}])[0]
    quickback  = (idx.get("QuickbackClick") or [{}])[0]
    dead       = (idx.get("DeadClickCount") or [{}])[0]
    rage       = (idx.get("RageClickCount") or [{}])[0]

    # TikTok % من مجموع الـ referrers
    referrers = idx.get("ReferrerUrl") or []
    total_ref = sum(int(r.get("sessionsCount", 0)) for r in referrers)
    tiktok_s  = sum(
        int(r.get("sessionsCount", 0)) for r in referrers
        if r.get("name") and "tiktok" in r["name"].lower()
    )

    return {
        "sessions":            int(traffic.get("totalSessionCount", 0)),
        "unique_users":        int(traffic.get("distinctUserCount", 0)),
        "scroll_depth":        round(float(scroll.get("averageScrollDepth", 0)), 1),
        "engagement_active":   int(engage.get("activeTime", 0)),
        "quickback_pct":       round(float(quickback.get("sessionsWithMetricPercentage", 0)), 2),
        "dead_click_pct":      round(float(dead.get("sessionsWithMetricPercentage", 0)), 2),
        "rage_click_pct":      round(float(rage.get("sessionsWithMetricPercentage", 0)), 2),
        "tiktok_pct":          round(tiktok_s / total_ref * 100, 1) if total_ref else 0.0,
        "top_referrers": [
            {"url": r.get("name") or "direct", "sessions": int(r.get("sessionsCount", 0))}
            for r in referrers[:4]
        ],
        "top_pages": [
            {"url": p.get("url", ""), "visits": int(p.get("visitsCount", 0))}
            for p in (idx.get("PopularPages") or [])[:5]
        ],
        "countries": [
            {"name": c.get("name", ""), "sessions": int(c.get("sessionsCount", 0))}
            for c in (idx.get("Country") or [])[:3]
        ],
        "devices": [
            {"name": d.get("name", ""), "sessions": int(d.get("sessionsCount", 0))}
            for d in (idx.get("Device") or [])
        ],
    }
