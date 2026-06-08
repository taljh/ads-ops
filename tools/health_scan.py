"""
health_scan.py — فحص صحة الحملات اللحظي

يأخذ بيانات يومية من Windsor ويكشف:
1. إشارات الإجهاد (تردد/CTR)
2. أداء الكرييتف (الرابح والخاسر)
3. مقارنة الأيام (trend)
4. تنبيهات فورية

الاستخدام:
    from tools.health_scan import HealthScanner
    scanner = HealthScanner("noura")
    scanner.add_daily("tiktok", rows)    # rows = list of dicts from Windsor
    scanner.add_daily("snapchat", rows)
    print(scanner.scan())
"""

from dataclasses import dataclass
from collections import defaultdict


@dataclass
class DayMetrics:
    date: str
    platform: str
    spend: float = 0
    conversions: int = 0
    roas: float = 0
    ctr: float = 0
    cpm: float = 0
    frequency: float = 0
    impressions: int = 0
    clicks: int = 0


THRESHOLDS = {
    "noura": {
        "ctr_drop_alert": 0.15,       # 15% هبوط أسبوع-لأسبوع
        "freq_daily_warn": 2.5,       # تردد يومي
        "roas_platform_floor": {
            "tiktok": 4.0,
            "snapchat": 6.0,          # لأن تضخمه 5x → 6.0 منصة = 1.2 حقيقي
        },
        "zero_conv_spend_kill": 150,  # صرف بدون أي تحويل → أوقف
        "inflation": {
            "tiktok": 1.39,
            "snapchat": 4.98,
        },
        "breakeven": 2.4,
    },
}


class HealthScanner:
    def __init__(self, client="noura"):
        self.client = client
        self.daily = defaultdict(list)  # platform -> [DayMetrics]
        self.th = THRESHOLDS.get(client, THRESHOLDS["noura"])

    def add_daily(self, platform, rows):
        """rows = list of dicts from Windsor daily data"""
        for r in rows:
            if not r.get("date"):
                continue
            spend = r.get("spend", 0) or 0
            if spend == 0:
                continue
            self.daily[platform].append(DayMetrics(
                date=r["date"],
                platform=platform,
                spend=spend,
                conversions=r.get("conversions", 0) or r.get("conversion_purchases", 0) or 0,
                roas=r.get("complete_payment_roas", 0) or 0,
                ctr=r.get("ctr", 0) or 0,
                cpm=r.get("cpm", 0) or 0,
                frequency=r.get("frequency", 0) or 0,
                impressions=r.get("impressions", 0) or 0,
                clicks=r.get("clicks", 0) or 0,
            ))

    def _last_n_days(self, platform, n=7):
        days = sorted(self.daily[platform], key=lambda d: d.date)
        return days[-n:] if len(days) >= n else days

    def _weekly_ctr_change(self, platform):
        """مقارنة CTR آخر 7 أيام مع الـ 7 قبلها"""
        days = sorted(self.daily[platform], key=lambda d: d.date)
        if len(days) < 14:
            return None
        recent = days[-7:]
        prev = days[-14:-7]
        avg_recent = sum(d.ctr for d in recent) / 7
        avg_prev = sum(d.ctr for d in prev) / 7
        if avg_prev == 0:
            return None
        return (avg_recent - avg_prev) / avg_prev

    def scan(self):
        alerts = []
        info = []

        for platform, days in self.daily.items():
            if not days:
                continue
            sorted_days = sorted(days, key=lambda d: d.date)
            last7 = sorted_days[-7:] if len(sorted_days) >= 7 else sorted_days
            last3 = sorted_days[-3:] if len(sorted_days) >= 3 else sorted_days
            inflation = self.th["inflation"].get(platform, 1.0)

            # --- 1. ROAS الحقيقي آخر 3 أيام ---
            for d in last3:
                real_roas = d.roas / inflation
                if d.conversions == 0 and d.spend >= self.th["zero_conv_spend_kill"]:
                    alerts.append(f"🔴 {platform} {d.date}: صرف {d.spend:.0f} بـ 0 تحويل → أوقف")
                elif real_roas < self.th["breakeven"] and d.spend > 50:
                    alerts.append(f"🟡 {platform} {d.date}: ROAS حقيقي {real_roas:.2f} < تعادل {self.th['breakeven']}")

            # --- 2. التردد ---
            for d in last3:
                if d.frequency > self.th["freq_daily_warn"]:
                    alerts.append(f"🔴 {platform} {d.date}: تردد يومي {d.frequency:.1f} > حد {self.th['freq_daily_warn']}")

            # --- 3. CTR أسبوع-لأسبوع ---
            ctr_change = self._weekly_ctr_change(platform)
            if ctr_change is not None and ctr_change < -self.th["ctr_drop_alert"]:
                alerts.append(f"⚠️ {platform}: CTR هبط {abs(ctr_change)*100:.0f}% أسبوع-لأسبوع → إشارة إجهاد")

            # --- 4. ملخص الأداء ---
            total_spend = sum(d.spend for d in last7)
            total_conv = sum(d.conversions for d in last7)
            avg_roas = sum(d.roas * d.spend for d in last7) / total_spend if total_spend > 0 else 0
            real_avg = avg_roas / inflation
            avg_ctr = sum(d.ctr * d.impressions for d in last7) / sum(d.impressions for d in last7) if sum(d.impressions for d in last7) > 0 else 0
            avg_freq = sum(d.frequency for d in last7) / len(last7)

            info.append(
                f"{platform:<12} آخر {len(last7)} أيام | "
                f"صرف {total_spend:>7,.0f} | "
                f"تحويل {total_conv:>3} | "
                f"ROAS منصة {avg_roas:>5.1f} → حقيقي {real_avg:>4.1f} | "
                f"CTR {avg_ctr*100:>4.1f}% | "
                f"freq {avg_freq:>3.1f}"
            )

        # --- تجميع ---
        lines = []
        lines.append("=" * 70)
        lines.append("  فحص صحة الحملات (Health Scan)")
        lines.append("=" * 70)

        if alerts:
            lines.append(f"\n🚨 تنبيهات ({len(alerts)}):")
            for a in alerts:
                lines.append(f"  {a}")
        else:
            lines.append("\n✅ لا تنبيهات")

        lines.append(f"\n📊 ملخص:")
        for i in info:
            lines.append(f"  {i}")

        return "\n".join(lines)


class CreativeRanker:
    """ترتيب الكرييتف من الأفضل للأسوأ"""

    def __init__(self, inflation=1.0, breakeven=2.4):
        self.creatives = []
        self.inflation = inflation
        self.breakeven = breakeven

    def add(self, name, spend, conversions, roas, ctr=0, frequency=0, group=""):
        self.creatives.append({
            "name": name, "group": group,
            "spend": spend, "conversions": conversions,
            "roas": roas, "real_roas": roas / self.inflation,
            "ctr": ctr, "frequency": frequency,
        })

    def rank(self, min_spend=50):
        """رتّب حسب: تحويلات (حجم) × ROAS حقيقي (كفاءة)"""
        valid = [c for c in self.creatives if c["spend"] >= min_spend]
        for c in valid:
            c["score"] = c["conversions"] * c["real_roas"]
            if c["frequency"] > 2.5:
                c["status"] = "⚠️ إجهاد"
            elif c["real_roas"] < self.breakeven:
                c["status"] = "🔴 تحت التعادل"
            elif c["conversions"] >= 5:
                c["status"] = "🟢 رابح"
            else:
                c["status"] = "🟡 عينة صغيرة"
        return sorted(valid, key=lambda c: c["score"], reverse=True)

    def report(self, min_spend=50):
        ranked = self.rank(min_spend)
        lines = []
        lines.append(f"\n{'#':<3} {'الكرييتف':<30} {'صرف':>6} {'تحويل':>5} {'ROAS حقيقي':>11} {'freq':>5} {'الحكم'}")
        lines.append("-" * 80)
        for i, c in enumerate(ranked, 1):
            lines.append(
                f"{i:<3} {c['name'][:29]:<30} {c['spend']:>6.0f} "
                f"{c['conversions']:>5} {c['real_roas']:>11.2f} "
                f"{c['frequency']:>5.1f} {c['status']}"
            )
        return "\n".join(lines)
