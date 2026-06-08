"""
reality_check.py — أداة التحقق من الحقيقة

تأخذ بيانات المنصة (Windsor) + بيانات المتجر (Salla) وتكشف الفرق.
تُستخدم قبل أي قرار ميزانية.

الاستخدام:
    from tools.reality_check import RealityEngine
    engine = RealityEngine()
    engine.add_platform("tiktok", spend=5823, platform_revenue=32318)
    engine.add_platform("snapchat", spend=3227, platform_revenue=26397)
    engine.set_store(store_revenue=52967, store_by_source={"tiktok": 23325, "snapchat": 5302, "direct": 39922})
    engine.report()
"""

from dataclasses import dataclass, field


@dataclass
class PlatformData:
    name: str
    spend: float
    platform_revenue: float
    platform_purchases: int = 0
    frequency: float = 0
    ctr: float = 0

    @property
    def platform_roas(self):
        return self.platform_revenue / self.spend if self.spend > 0 else 0


@dataclass
class StoreData:
    total_revenue: float
    by_source: dict = field(default_factory=dict)  # {"tiktok": 23325, "snapchat": 5302}
    total_orders: int = 0
    aov: float = 0


# نسب التضخم المُحدَّثة — تتعدّل مع كل شهر جديد
INFLATION_RATES = {
    "tiktok":   {"rate": 1.39, "source": "مايو 2026 نوره", "confidence": "high"},
    "snapchat": {"rate": 4.98, "source": "مايو 2026 نوره", "confidence": "high"},
    "meta":     {"rate": 1.50, "source": "تقدير صناعي",    "confidence": "low"},
}

# حدود الـ Guardrails — per-client
GUARDRAILS = {
    "noura": {
        "blended_floor": 4.5,
        "breakeven": 2.4,
        "cpa_ceiling": 90,
        "freq_prospecting": 3,
        "freq_retargeting": 6,
        "freq_creative": 2.5,
        "freq_cumulative_kill": 20,  # تردد تراكمي → أوقف فوراً
        "budget_cap": 15000,
    },
}


class RealityEngine:
    def __init__(self, client="noura"):
        self.client = client
        self.platforms = {}
        self.store = None
        self.guards = GUARDRAILS.get(client, GUARDRAILS["noura"])

    def add_platform(self, name, spend, platform_revenue, platform_purchases=0, frequency=0, ctr=0):
        self.platforms[name] = PlatformData(
            name=name, spend=spend,
            platform_revenue=platform_revenue,
            platform_purchases=platform_purchases,
            frequency=frequency, ctr=ctr
        )

    def set_store(self, total_revenue, by_source=None, total_orders=0, aov=0):
        self.store = StoreData(
            total_revenue=total_revenue,
            by_source=by_source or {},
            total_orders=total_orders,
            aov=aov
        )

    def real_roas(self, platform_name):
        """ROAS الحقيقي = ROAS المنصة ÷ التضخم"""
        p = self.platforms.get(platform_name)
        if not p:
            return 0
        inf = INFLATION_RATES.get(platform_name, {}).get("rate", 1.0)
        return p.platform_roas / inf

    def real_roas_from_store(self, platform_name):
        """ROAS من سلة مباشرة (أدق)"""
        p = self.platforms.get(platform_name)
        if not p or not self.store:
            return 0
        store_rev = self.store.by_source.get(platform_name, 0)
        return store_rev / p.spend if p.spend > 0 else 0

    def blended_roas(self):
        """Blended ROAS = إيراد سلة الكلي ÷ كل الصرف"""
        if not self.store:
            return 0
        total_spend = sum(p.spend for p in self.platforms.values())
        return self.store.total_revenue / total_spend if total_spend > 0 else 0

    def inflation_factor(self, platform_name):
        """التضخم الفعلي من المقارنة مع سلة"""
        p = self.platforms.get(platform_name)
        if not p or not self.store:
            return None
        store_rev = self.store.by_source.get(platform_name, 0)
        if store_rev == 0:
            return float('inf')
        return p.platform_revenue / store_rev

    def opportunity_cost(self, from_platform, to_platform):
        """لو حوّلت ميزانية منصة لأخرى — كم الفرق؟"""
        frm = self.platforms.get(from_platform)
        to = self.platforms.get(to_platform)
        if not frm or not to:
            return {}
        to_real_roas = self.real_roas_from_store(to_platform) or self.real_roas(to_platform)
        frm_real_roas = self.real_roas_from_store(from_platform) or self.real_roas(from_platform)
        return {
            "budget_moved": frm.spend,
            "current_revenue": frm.spend * frm_real_roas,
            "potential_revenue": frm.spend * to_real_roas,
            "revenue_difference": frm.spend * (to_real_roas - frm_real_roas),
        }

    def check_guardrails(self):
        """فحص كل الـ Guardrails — يرجع قائمة المخالفات"""
        violations = []
        g = self.guards

        # Blended ROAS
        br = self.blended_roas()
        if br > 0 and br < g["blended_floor"]:
            violations.append(f"🔴 Blended ROAS {br:.2f} < أرضية {g['blended_floor']}")

        # Per-platform
        for name, p in self.platforms.items():
            real = self.real_roas_from_store(name) or self.real_roas(name)
            if real > 0 and real < g["breakeven"]:
                violations.append(f"🔴 {name}: ROAS حقيقي {real:.2f} < التعادل {g['breakeven']}")

            if p.frequency > g["freq_prospecting"]:
                violations.append(f"🟡 {name}: تردد {p.frequency:.1f} > حد {g['freq_prospecting']}")

            if p.frequency > g["freq_cumulative_kill"]:
                violations.append(f"🔴 {name}: تردد تراكمي {p.frequency:.1f} > حد الإيقاف {g['freq_cumulative_kill']} — أوقف فوراً")

        return violations

    def report(self):
        """تقرير كامل"""
        lines = []
        lines.append("=" * 60)
        lines.append("  تقرير التحقق من الحقيقة (Reality Check)")
        lines.append("=" * 60)

        # Blended
        br = self.blended_roas()
        if br > 0:
            status = "🟢" if br >= self.guards["blended_floor"] else "🔴"
            lines.append(f"\n{status} Blended ROAS: {br:.2f} (أرضية {self.guards['blended_floor']})")

        # Per-platform
        lines.append(f"\n{'المنصة':<12} {'صرف':>8} {'ROAS منصة':>10} {'ROAS حقيقي':>11} {'التضخم':>8} {'الحكم':>6}")
        lines.append("-" * 60)
        for name, p in self.platforms.items():
            real_store = self.real_roas_from_store(name)
            real_est = self.real_roas(name)
            real = real_store if real_store > 0 else real_est
            inf = self.inflation_factor(name)
            inf_str = f"{inf:.1f}x" if inf and inf != float('inf') else "∞"
            status = "🟢" if real >= self.guards["blended_floor"] else "🔴"
            source = "(سلة)" if real_store > 0 else "(تقدير)"
            lines.append(f"{name:<12} {p.spend:>8,.0f} {p.platform_roas:>10.2f} {real:>8.2f} {source} {inf_str:>5} {status}")

        # Guardrails
        violations = self.check_guardrails()
        if violations:
            lines.append(f"\n⚠️  مخالفات ({len(violations)}):")
            for v in violations:
                lines.append(f"  {v}")
        else:
            lines.append("\n✅ لا مخالفات")

        return "\n".join(lines)


class CampaignMatcher:
    """مطابقة مباشرة: صرف Windsor ↔ إيراد سلة (reports_traffic_campaigns) لكل حملة.

    هذا أدق من التضخم التقديري — يستخدم إيراد سلة الفعلي لكل حملة (عبر UTM).

    الاستخدام:
        matcher = CampaignMatcher()
        # من Windsor:
        matcher.add_windsor("Main | May 2026", spend=5823)
        matcher.add_windsor("Main Sales 22", spend=3227)
        # من Salla reports_traffic_campaigns:
        matcher.add_salla("Main | May 2026", revenue=12284, purchases=29)
        matcher.add_salla("Main Sales 22", revenue=3806, purchases=9)
        print(matcher.report())
    """

    def __init__(self, breakeven=2.4, store_total_revenue=0):
        self.campaigns = {}
        self.breakeven = breakeven
        self.store_total_revenue = store_total_revenue  # for blended calc

    def add_windsor(self, campaign_name, spend):
        if campaign_name not in self.campaigns:
            self.campaigns[campaign_name] = {"spend": 0, "salla_revenue": 0, "salla_purchases": 0}
        self.campaigns[campaign_name]["spend"] += spend

    def add_salla(self, campaign_name, revenue, purchases=0):
        if campaign_name not in self.campaigns:
            self.campaigns[campaign_name] = {"spend": 0, "salla_revenue": 0, "salla_purchases": 0}
        self.campaigns[campaign_name]["salla_revenue"] += revenue
        self.campaigns[campaign_name]["salla_purchases"] += purchases

    def true_roas(self, campaign_name):
        c = self.campaigns.get(campaign_name)
        if not c or c["spend"] == 0:
            return 0
        return c["salla_revenue"] / c["spend"]

    def true_cpa(self, campaign_name):
        c = self.campaigns.get(campaign_name)
        if not c or c["salla_purchases"] == 0:
            return float('inf')
        return c["spend"] / c["salla_purchases"]

    def total_spend(self):
        return sum(c["spend"] for c in self.campaigns.values())

    def total_salla_revenue(self):
        return sum(c["salla_revenue"] for c in self.campaigns.values())

    def campaign_blended_roas(self):
        """Campaign-attributed ROAS = total salla campaign revenue / total spend"""
        ts = self.total_spend()
        return self.total_salla_revenue() / ts if ts > 0 else 0

    def full_blended_roas(self):
        """Full Blended ROAS = total store revenue / total spend (includes halo)"""
        ts = self.total_spend()
        return self.store_total_revenue / ts if ts > 0 and self.store_total_revenue > 0 else 0

    def halo_revenue(self):
        """الإيراد غير المنسوب مباشرة = store total - campaign total"""
        return max(0, self.store_total_revenue - self.total_salla_revenue())

    def report(self):
        lines = []
        lines.append("=" * 70)
        lines.append("  Campaign Truth Match — Windsor spend <> Salla revenue")
        lines.append("=" * 70)

        total_spend = 0
        total_revenue = 0
        total_purchases = 0

        sorted_camps = sorted(
            self.campaigns.items(),
            key=lambda x: x[1]["spend"],
            reverse=True,
        )

        lines.append(f"\n{'الحملة':<36} {'صرف':>7} {'إيراد سلة':>9} {'ROAS':>6} {'CPA':>6} {'طلب':>4}")
        lines.append("-" * 70)

        for name, c in sorted_camps:
            if c["spend"] == 0:
                continue
            roas = c["salla_revenue"] / c["spend"]
            cpa = c["spend"] / c["salla_purchases"] if c["salla_purchases"] > 0 else float('inf')
            status = "🟢" if roas >= self.breakeven else "🔴"
            cpa_str = f"{cpa:>6.0f}" if cpa != float('inf') else "   inf"
            lines.append(
                f"{status} {name[:34]:<34} {c['spend']:>7,.0f} "
                f"{c['salla_revenue']:>9,.0f} {roas:>6.2f} "
                f"{cpa_str} {c['salla_purchases']:>4}"
            )
            total_spend += c["spend"]
            total_revenue += c["salla_revenue"]
            total_purchases += c["salla_purchases"]

        lines.append("-" * 70)
        camp_roas = total_revenue / total_spend if total_spend > 0 else 0
        lines.append(f"   Campaign ROAS: {camp_roas:.2f} (صرف {total_spend:,.0f} | إيراد {total_revenue:,.0f} | {total_purchases} طلب)")

        if self.store_total_revenue > 0:
            full_br = self.full_blended_roas()
            halo = self.halo_revenue()
            halo_pct = halo / self.store_total_revenue * 100 if self.store_total_revenue > 0 else 0
            lines.append(f"   Blended ROAS:  {full_br:.2f} (إيراد سلة كامل {self.store_total_revenue:,.0f} | هالة {halo:,.0f} = {halo_pct:.0f}%)")

        return "\n".join(lines)


# مثال الاستخدام — يونيو نوره
if __name__ == "__main__":
    engine = RealityEngine("noura")
    engine.add_platform("tiktok", spend=2579, platform_revenue=12157, platform_purchases=31)
    engine.add_platform("snapchat", spend=987, platform_revenue=6895, platform_purchases=18, frequency=48.7)
    engine.set_store(
        total_revenue=16073,  # 9756+6317 (مباشر+tiktok)
        by_source={"tiktok": 6317, "snapchat": 0, "direct": 9756},
        total_orders=42
    )
    print(engine.report())

    print("\n" + "=" * 60)
    print("  تكلفة الفرصة: لو Snapchat → TikTok")
    print("=" * 60)
    opp = engine.opportunity_cost("snapchat", "tiktok")
    for k, v in opp.items():
        print(f"  {k}: {v:,.0f}")

    # --- CampaignMatcher: مطابقة مباشرة (مايو نوره) ---
    print("\n")
    matcher = CampaignMatcher(breakeven=2.4, store_total_revenue=52967)
    # Windsor spend:
    matcher.add_windsor("Main | May 2026", spend=5823)
    matcher.add_windsor("Main Sales 22", spend=3227)
    # Salla reports_traffic_campaigns:
    matcher.add_salla("Main | May 2026", revenue=12284, purchases=29)
    matcher.add_salla("Main Sales 22", revenue=3806, purchases=9)
    print(matcher.report())
