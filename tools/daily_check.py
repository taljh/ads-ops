"""
daily_check.py — الفحص اليومي للحملات

يستقبل بيانات Windsor + Salla، يخزّنها في SQLite، يقارن مع التاريخ، يطلع تقرير.

الاستخدام:
    checker = DailyCheck("noura")

    # خزّن بيانات Windsor (أنا أسحبها من MCP وأمررها)
    checker.store_windsor(tiktok_campaign_rows, "tiktok", "campaign")
    checker.store_windsor(tiktok_adgroup_rows, "tiktok", "adgroup")
    checker.store_windsor(tiktok_ad_rows, "tiktok", "ad")

    # خزّن بيانات سلة
    checker.store_salla(salla_campaign_rows)

    # التقرير
    print(checker.report())
"""

import sqlite3
import json
import os
from datetime import datetime, timedelta
from pathlib import Path


# ──────────────────────────────────────────────
# CONFIG
# ──────────────────────────────────────────────

CLIENTS = {
    "noura": {
        "db": "clients/noura/data/tracker.db",
        "monitor": "clients/noura/data/monitoring.json",
        "budget_cap": 15000,
        "breakeven": 2.4,
        "blended_floor": 4.5,
        "inflation": {"tiktok": 1.39, "snapchat": 4.98},
        "platforms": ["tiktok", "snapchat"],
        "windsor_accounts": {
            "tiktok": "7401593626448363521",
            "snapchat": "1dfe24d6-d8e8-42cb-bc69-8cf651cffdc4",
        },
        "guardrails": {
            "freq_prospecting": 3,
            "freq_retargeting": 6,
            "ctr_drop_pct": 0.15,
            "zero_conv_kill": 150,
            "cpa_ceiling": 90,
        },
        "peak_days": list(range(26, 32)) + list(range(1, 4)),
    },
    "zain": {
        "db": "clients/zain/data/tracker.db",
        "monitor": "clients/zain/data/monitoring.json",
        "budget_cap": 15000,
        "breakeven": 2.5,
        "blended_floor": 4.5,
        "inflation": {"tiktok": 1.39},
        "platforms": ["tiktok"],
        "windsor_accounts": {
            "tiktok": "7494645342479319056",
        },
        "guardrails": {
            "freq_prospecting": 3,
            "freq_retargeting": 6,
            "ctr_drop_pct": 0.15,
            "zero_conv_kill": 150,
            "cpa_ceiling": 90,
        },
        "peak_days": list(range(26, 32)) + list(range(1, 4)),
    },
}

SCHEMA = """
CREATE TABLE IF NOT EXISTS snapshots (
    pull_date    TEXT NOT NULL,
    report_date  TEXT NOT NULL,
    platform     TEXT NOT NULL,
    level        TEXT NOT NULL,
    name         TEXT NOT NULL,
    parent_name  TEXT DEFAULT '',
    spend        REAL DEFAULT 0,
    conversions  INTEGER DEFAULT 0,
    roas_platform REAL DEFAULT 0,
    ctr          REAL DEFAULT 0,
    cpm          REAL DEFAULT 0,
    frequency    REAL DEFAULT 0,
    impressions  INTEGER DEFAULT 0,
    clicks       INTEGER DEFAULT 0,
    status       TEXT DEFAULT '',
    PRIMARY KEY (pull_date, report_date, platform, level, parent_name, name)
);

CREATE TABLE IF NOT EXISTS salla_truth (
    pull_date      TEXT NOT NULL,
    report_date    TEXT NOT NULL,
    campaign_name  TEXT NOT NULL,
    revenue        REAL DEFAULT 0,
    purchases      INTEGER DEFAULT 0,
    PRIMARY KEY (pull_date, report_date, campaign_name)
);

CREATE TABLE IF NOT EXISTS salla_summary (
    pull_date      TEXT NOT NULL,
    period_start   TEXT NOT NULL,
    period_end     TEXT NOT NULL,
    total_revenue  REAL DEFAULT 0,
    total_orders   INTEGER DEFAULT 0,
    PRIMARY KEY (pull_date, period_start, period_end)
);

CREATE TABLE IF NOT EXISTS learnings (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    pull_date      TEXT NOT NULL,
    category       TEXT NOT NULL,
    signal         TEXT NOT NULL,
    detail         TEXT DEFAULT '',
    actionable     INTEGER DEFAULT 0,
    UNIQUE(pull_date, category, signal)
);
"""


# ──────────────────────────────────────────────
# DAILY CHECK
# ──────────────────────────────────────────────

class DailyCheck:

    def __init__(self, client, today=None, base_dir="."):
        self.client = client
        self.cfg = CLIENTS.get(client)
        if not self.cfg:
            raise ValueError(f"Unknown client: {client}. Available: {list(CLIENTS.keys())}")
        self.today = today or datetime.now().strftime("%Y-%m-%d")
        self.base_dir = Path(base_dir)
        self.db_path = self.base_dir / self.cfg["db"]
        self.monitor_path = self.base_dir / self.cfg["monitor"]
        self._init_db()

    def _init_db(self):
        os.makedirs(self.db_path.parent, exist_ok=True)
        with self._conn() as conn:
            conn.executescript(SCHEMA)
            # Migrate: if old PRIMARY KEY (without parent_name), rebuild the table
            idx = conn.execute(
                "SELECT sql FROM sqlite_master WHERE type='table' AND name='snapshots'"
            ).fetchone()
            if idx and "parent_name, name" not in idx[0]:
                conn.executescript("""
                    ALTER TABLE snapshots RENAME TO snapshots_old;
                    CREATE TABLE snapshots (
                        pull_date    TEXT NOT NULL,
                        report_date  TEXT NOT NULL,
                        platform     TEXT NOT NULL,
                        level        TEXT NOT NULL,
                        name         TEXT NOT NULL,
                        parent_name  TEXT DEFAULT '',
                        spend        REAL DEFAULT 0,
                        conversions  INTEGER DEFAULT 0,
                        roas_platform REAL DEFAULT 0,
                        ctr          REAL DEFAULT 0,
                        cpm          REAL DEFAULT 0,
                        frequency    REAL DEFAULT 0,
                        impressions  INTEGER DEFAULT 0,
                        clicks       INTEGER DEFAULT 0,
                        status       TEXT DEFAULT '',
                        PRIMARY KEY (pull_date, report_date, platform, level, parent_name, name)
                    );
                    INSERT OR IGNORE INTO snapshots SELECT * FROM snapshots_old;
                    DROP TABLE snapshots_old;
                """)
            # Migrate: add status column if missing from older DBs
            cols = [row[1] for row in conn.execute("PRAGMA table_info(snapshots)").fetchall()]
            if "status" not in cols:
                conn.execute("ALTER TABLE snapshots ADD COLUMN status TEXT DEFAULT ''")


    def _conn(self):
        conn = sqlite3.connect(str(self.db_path))
        conn.row_factory = sqlite3.Row
        return conn

    def _date_ago(self, days):
        return (datetime.strptime(self.today, "%Y-%m-%d") - timedelta(days=days)).strftime("%Y-%m-%d")

    # ── STORE ────────────────────────────────

    def store_windsor(self, rows, platform, level="campaign"):
        """Store Windsor daily data.

        Args:
            rows: list of dicts from Windsor get_data
            platform: "tiktok" | "snapchat"
            level: "campaign" | "adgroup" | "ad"
        """
        name_keys = {
            "campaign": ["campaign_name", "campaign"],
            "adgroup":  ["ad_group_name", "adgroup_name", "ad_squad_name", "adgroup"],
            "ad":       ["ad_name", "ad"],
        }
        parent_keys = {
            "campaign": [],
            "adgroup":  ["campaign_name", "campaign"],
            "ad":       ["ad_group_name", "adgroup_name", "ad_squad_name", "adgroup"],
        }
        status_keys = {
            "campaign": ["campaign_status"],
            "adgroup":  ["adgroup_status", "ad_group_status"],
            "ad":       ["ad_status"],
        }

        stored = 0
        with self._conn() as conn:
            for r in rows:
                date = r.get("date", "")
                if not date:
                    continue

                name = self._pick(r, name_keys[level])
                if not name:
                    continue

                spend = float(r.get("spend", 0) or 0)
                if spend == 0:
                    continue

                parent = self._pick(r, parent_keys[level])
                status = self._pick(r, status_keys.get(level, []))
                conv = int(r.get("conversions", 0) or r.get("conversion_purchases", 0) or 0)
                roas = float(r.get("complete_payment_roas", 0) or r.get("roas", 0) or 0)
                # Snapchat: compute ROAS from purchase value if no direct ROAS field
                if roas == 0 and spend > 0:
                    rev = float(r.get("conversion_purchases_value", 0) or 0)
                    if rev > 0:
                        roas = rev / spend

                conn.execute("""
                    INSERT OR REPLACE INTO snapshots
                    (pull_date, report_date, platform, level, name, parent_name,
                     spend, conversions, roas_platform, ctr, cpm, frequency, impressions, clicks, status)
                    VALUES (?,?,?,?,?,?, ?,?,?,?,?,?,?,?,?)
                """, (
                    self.today, date, platform, level, name, parent,
                    spend, conv, roas,
                    float(r.get("ctr", 0) or 0),
                    float(r.get("cpm", 0) or 0),
                    float(r.get("frequency", 0) or 0),
                    int(r.get("impressions", 0) or 0),
                    int(r.get("clicks", 0) or 0),
                    status,
                ))
                stored += 1
        return stored

    def store_salla(self, rows, report_date=None):
        """Store Salla campaign truth.

        Args:
            rows: list of dicts from reports_traffic_campaigns
            report_date: override date (if Salla returns aggregate, not daily)
        """
        stored = 0
        with self._conn() as conn:
            for r in rows:
                name = r.get("campaign") or r.get("campaign_name") or ""
                if not name:
                    continue
                date = report_date or r.get("date") or self.today
                revenue = float(
                    r.get("revenue", 0) or r.get("total_amount", 0)
                    or r.get("gross_sales", 0) or 0
                )
                purchases = int(r.get("purchases", 0) or r.get("orders_count", 0) or 0)
                conn.execute("""
                    INSERT OR REPLACE INTO salla_truth
                    (pull_date, report_date, campaign_name, revenue, purchases)
                    VALUES (?,?,?,?,?)
                """, (self.today, date, name, revenue, purchases))
                stored += 1
        return stored

    def store_salla_summary(self, total_revenue, total_orders, period_start, period_end):
        """Store Salla store-level totals (for Blended ROAS).

        Args:
            total_revenue: total net revenue from sales summary
            total_orders: total completed orders
            period_start: date range start (YYYY-MM-DD)
            period_end: date range end (YYYY-MM-DD)
        """
        with self._conn() as conn:
            conn.execute("""
                INSERT OR REPLACE INTO salla_summary
                (pull_date, period_start, period_end, total_revenue, total_orders)
                VALUES (?,?,?,?,?)
            """, (self.today, period_start, period_end, total_revenue, total_orders))
        return 1

    @staticmethod
    def _pick(row, keys):
        for k in keys:
            if row.get(k):
                return row[k]
        return ""

    # ── QUERY ────────────────────────────────

    def _latest_dates(self, platform=None, n=4):
        """Get the N most recent report_dates in today's pull."""
        q = "SELECT DISTINCT report_date FROM snapshots WHERE pull_date = ?"
        p = [self.today]
        if platform:
            q += " AND platform = ?"
            p.append(platform)
        q += " ORDER BY report_date DESC LIMIT ?"
        p.append(n)
        with self._conn() as conn:
            return [r[0] for r in conn.execute(q, p).fetchall()]

    def _get_day(self, report_date, platform=None, level=None, pull_date=None):
        """Get all entities for a specific report_date."""
        pd = pull_date or self.today
        q = "SELECT * FROM snapshots WHERE pull_date=? AND report_date=?"
        p = [pd, report_date]
        if platform:
            q += " AND platform=?"
            p.append(platform)
        if level:
            q += " AND level=?"
            p.append(level)
        q += " ORDER BY spend DESC"
        with self._conn() as conn:
            return [dict(r) for r in conn.execute(q, p).fetchall()]

    def _get_avg(self, start, end, platform=None, level=None, name=None):
        """Weighted average over date range (latest pull per date)."""
        q = """
            SELECT name, parent_name, platform,
                   AVG(spend) as spend,
                   AVG(conversions) as conversions,
                   CASE WHEN SUM(spend)>0
                        THEN SUM(spend*roas_platform)/SUM(spend)
                        ELSE 0 END as roas_platform,
                   CASE WHEN SUM(impressions)>0
                        THEN SUM(ctr*impressions)/SUM(impressions)
                        ELSE 0 END as ctr,
                   AVG(cpm) as cpm,
                   AVG(frequency) as frequency,
                   COUNT(*) as days
            FROM snapshots
            WHERE report_date BETWEEN ? AND ?
              AND pull_date = (
                  SELECT MAX(s2.pull_date) FROM snapshots s2
                  WHERE s2.report_date=snapshots.report_date
                    AND s2.platform=snapshots.platform
                    AND s2.level=snapshots.level
                    AND s2.name=snapshots.name
              )
        """
        p = [start, end]
        if platform:
            q += " AND platform=?"
            p.append(platform)
        if level:
            q += " AND level=?"
            p.append(level)
        if name:
            q += " AND name=?"
            p.append(name)
        q += " GROUP BY name, parent_name, platform"
        with self._conn() as conn:
            return [dict(r) for r in conn.execute(q, p).fetchall()]

    def _maturity_delta(self):
        """How much did yesterday's numbers change when re-pulled today?"""
        yesterday = self._date_ago(1)
        prev_pull = self._date_ago(1)

        old = self._get_day(yesterday, pull_date=prev_pull)
        new = self._get_day(yesterday, pull_date=self.today)
        if not old or not new:
            return []

        old_map = {(r["platform"], r["level"], r["name"]): r for r in old}
        deltas = []
        for r in new:
            key = (r["platform"], r["level"], r["name"])
            o = old_map.get(key)
            if not o:
                continue
            dc = r["conversions"] - o["conversions"]
            ds = r["spend"] - o["spend"]
            if dc != 0 or abs(ds) > 1:
                deltas.append({
                    "platform": r["platform"], "name": r["name"],
                    "conv_old": o["conversions"], "conv_new": r["conversions"],
                    "conv_delta": dc, "spend_delta": ds,
                })
        return deltas

    # ── TREND ────────────────────────────────

    def _adgroup_history(self, name, platform, parent_name="", n=4):
        """Get last N days of ROAS for a specific adgroup under a specific campaign."""
        with self._conn() as conn:
            rows = conn.execute("""
                SELECT report_date, roas_platform, conversions
                FROM snapshots
                WHERE level='adgroup' AND name=? AND platform=? AND parent_name=?
                  AND pull_date = (
                      SELECT MAX(s2.pull_date) FROM snapshots s2
                      WHERE s2.report_date=snapshots.report_date
                        AND s2.name=snapshots.name
                        AND s2.platform=snapshots.platform
                        AND s2.level=snapshots.level
                        AND s2.parent_name=snapshots.parent_name
                  )
                ORDER BY report_date DESC LIMIT ?
            """, (name, platform, parent_name, n)).fetchall()
        return list(reversed([dict(r) for r in rows]))

    @staticmethod
    def _trend(current, reference):
        if reference == 0:
            return "🆕" if current > 0 else "—"
        pct = (current - reference) / reference
        if pct > 0.15:
            return "↑"
        elif pct < -0.15:
            return "↓"
        return "→"

    # ── STATUS ───────────────────────────────

    @staticmethod
    def _is_alertable(status):
        """True if entity should be included in guardrail alerts.
        Paused/deleted entities are excluded — the user already acted on them.
        Empty status = unknown = include (backward compat with old pulls).
        """
        if not status:
            return True
        return "DELIVERY_OK" in status or status == "CAMPAIGN_STATUS_ENABLE"

    @staticmethod
    def _status_badge(status):
        """Short emoji badge shown next to paused/deleted entities in the report."""
        if not status or "DELIVERY_OK" in status or status == "CAMPAIGN_STATUS_ENABLE":
            return ""
        if "DELETE" in status:
            return " 🗑"
        return " ⏸"

    # ── PACING ───────────────────────────────

    def _pacing(self):
        today_dt = datetime.strptime(self.today, "%Y-%m-%d")
        month_start = today_dt.replace(day=1).strftime("%Y-%m-%d")
        day_of_month = today_dt.day
        days_in_month = 30

        with self._conn() as conn:
            row = conn.execute("""
                SELECT COALESCE(SUM(spend), 0) FROM snapshots
                WHERE level='campaign'
                  AND report_date BETWEEN ? AND ?
                  AND pull_date = (
                      SELECT MAX(s2.pull_date) FROM snapshots s2
                      WHERE s2.report_date=snapshots.report_date
                        AND s2.platform=snapshots.platform
                        AND s2.name=snapshots.name
                  )
            """, (month_start, self.today)).fetchone()
            month_spend = row[0]

        projected = (month_spend / day_of_month * days_in_month) if day_of_month > 0 else 0
        cap = self.cfg["budget_cap"]

        if projected > cap * 1.1:
            status = "🔴 فوق السقف — خفّف"
        elif projected >= cap * 0.85:
            status = "🟢 مثالي"
        elif projected >= cap * 0.6:
            status = "🟡 مساحة للزيادة"
        else:
            status = "⚠️ منخفض جداً"

        is_peak = day_of_month in self.cfg.get("peak_days", [])

        return {
            "spent": month_spend,
            "projected": projected,
            "cap": cap,
            "status": status,
            "phase": "ذروة (26→3)" if is_peak else "صيانة",
            "day": day_of_month,
        }

    # ── SIGNALS ──────────────────────────────

    def _load_monitor(self):
        if self.monitor_path.exists():
            with open(self.monitor_path) as f:
                return json.load(f)
        return {}

    def _save_monitor(self, data):
        os.makedirs(self.monitor_path.parent, exist_ok=True)
        with open(self.monitor_path, "w") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

    def _detect_alerts(self, campaign_data, avg_data):
        """Detect guardrail violations. Returns list of alert dicts."""
        g = self.cfg["guardrails"]
        inf = self.cfg["inflation"]
        avg_map = {(a["platform"], a["name"]): a for a in avg_data}
        alerts = []

        for row in campaign_data:
            if not self._is_alertable(row.get("status", "")):
                continue
            plat = row["platform"]
            name = row["name"]
            key_base = f"{plat}_{name}".replace(" ", "_").replace("|", "").lower().strip("_")
            inflation = inf.get(plat, 1.0)
            real_roas = row["roas_platform"] / inflation if inflation > 0 else 0

            # 1. ROAS under breakeven (significant spend only)
            if real_roas > 0 and real_roas < self.cfg["breakeven"] and row["spend"] > 50:
                alerts.append({
                    "key": f"{key_base}_roas",
                    "signal": f"{plat} {name}: ROAS حقيقي {real_roas:.1f} < تعادل {self.cfg['breakeven']}",
                })

            # 2. Frequency too high
            if row["frequency"] > g["freq_prospecting"]:
                alerts.append({
                    "key": f"{key_base}_freq",
                    "signal": f"{plat} {name}: تردد {row['frequency']:.1f} > حد {g['freq_prospecting']}",
                })

            # 3. Zero conversions with real spend
            if row["conversions"] == 0 and row["spend"] >= g["zero_conv_kill"]:
                alerts.append({
                    "key": f"{key_base}_zero",
                    "signal": f"{plat} {name}: صرف {row['spend']:.0f} بـ 0 تحويل — أوقف",
                })

            # 4. CTR drop vs 3-day avg
            avg = avg_map.get((plat, name))
            if avg and avg.get("ctr", 0) > 0 and row["ctr"] > 0:
                ctr_chg = (row["ctr"] - avg["ctr"]) / avg["ctr"]
                if ctr_chg < -g["ctr_drop_pct"]:
                    alerts.append({
                        "key": f"{key_base}_ctr",
                        "signal": f"{plat} {name}: CTR هبط {abs(ctr_chg)*100:.0f}%",
                    })

        return alerts

    def _update_monitor(self, alerts):
        """Update monitoring.json: track signal duration, escalate level."""
        mon = self._load_monitor()
        seen = set()

        for a in alerts:
            k = a["key"]
            seen.add(k)
            if k in mon:
                mon[k]["days"] += 1
                mon[k]["last_seen"] = self.today
                mon[k]["signal"] = a["signal"]
            else:
                mon[k] = {
                    "first_seen": self.today,
                    "last_seen": self.today,
                    "days": 1,
                    "signal": a["signal"],
                }
            d = mon[k]["days"]
            mon[k]["level"] = "action" if d >= 3 else ("warn" if d >= 2 else "monitor")

        # Clear signals not seen today
        for k in list(mon):
            if k not in seen:
                del mon[k]

        self._save_monitor(mon)
        return mon

    # ── REPORT ───────────────────────────────

    def report(self):
        """Generate the complete daily check report."""
        dates = self._latest_dates()
        if not dates:
            return f"{'='*55}\n  {self.client} — {self.today}\n{'='*55}\n\n  لا بيانات مخزنة. شغّل store_windsor أولاً."

        latest = dates[0]
        prev = dates[1] if len(dates) > 1 else None
        three_ago = self._date_ago(3)
        lines = []

        # ── Header + Pacing ──
        pace = self._pacing()
        lines.append(f"{'='*55}")
        lines.append(f"  {self.client} — {self.today} — {pace['phase']}")
        lines.append(f"  الشهر: {pace['spent']:,.0f} / {pace['cap']:,.0f} SAR | متوقع: {pace['projected']:,.0f} | {pace['status']}")
        lines.append(f"{'='*55}")

        # ── Per platform ──
        with self._conn() as conn:
            platforms = [r[0] for r in conn.execute(
                "SELECT DISTINCT platform FROM snapshots WHERE pull_date=? ORDER BY platform",
                (self.today,)
            ).fetchall()]

        all_campaigns = []
        all_avg = []

        for plat in platforms:
            lines.append(f"\n{'─'*55}")
            lines.append(f"  {plat.upper()}")
            lines.append(f"{'─'*55}")

            # Get this platform's latest available date
            plat_dates = self._latest_dates(platform=plat)
            plat_latest = plat_dates[0] if plat_dates else None
            plat_prev = plat_dates[1] if len(plat_dates) > 1 else None

            if not plat_latest:
                lines.append("  لا بيانات حملات")
                continue

            if plat_latest != latest:
                lines.append(f"  ⚠️ آخر بيانات متاحة: {plat_latest} (Windsor متأخر)")

            # Campaigns for latest date
            campaigns = self._get_day(plat_latest, platform=plat, level="campaign")
            if not campaigns:
                lines.append("  لا بيانات حملات")
                continue

            all_campaigns.extend(campaigns)

            # Previous day + 3-day avg
            prev_camps = {c["name"]: c for c in self._get_day(plat_prev, platform=plat, level="campaign")} if plat_prev else {}
            avg_camps = {a["name"]: a for a in self._get_avg(three_ago, plat_prev or plat_latest, platform=plat, level="campaign")}
            all_avg.extend(avg_camps.values())

            # Platform totals for the day
            plat_spend = sum(c["spend"] for c in campaigns)
            plat_conv = sum(c["conversions"] for c in campaigns)
            lines.append(f"  صرف اليوم: {plat_spend:,.0f} | تحويل: {plat_conv}")

            for c in campaigns:
                name = c["name"]
                p = prev_camps.get(name, {})
                a = avg_camps.get(name, {})

                roas_trend = self._trend(c["roas_platform"], a.get("roas_platform", 0))

                # Main line
                conv_s = f"{c['conversions']} conv"
                roas_s = f"ROAS {c['roas_platform']:.1f}" if c["roas_platform"] > 0 else "ROAS —"
                freq_s = f"freq {c['frequency']:.1f}" if c["frequency"] > 0.5 else ""
                badge = self._status_badge(c.get("status", ""))
                lines.append(f"\n  {name[:32]:<32} {roas_trend}{badge}")
                lines.append(f"    صرف {c['spend']:>6.0f} | {conv_s} | {roas_s} {freq_s}")

                # Comparison line
                if p or a:
                    p_s = f"أمس {p.get('spend',0):,.0f}/{p.get('conversions',0)}/{p.get('roas_platform',0):.1f}" if p else ""
                    a_s = f"3-يوم {a.get('spend',0):,.0f}/{a.get('conversions',0):.0f}/{a.get('roas_platform',0):.1f}" if a else ""
                    sep = " · " if p_s and a_s else ""
                    lines.append(f"    ({p_s}{sep}{a_s})")

                # Ad groups under this campaign
                adgroups = self._get_day(plat_latest, platform=plat, level="adgroup")
                for ag in adgroups:
                    if ag.get("parent_name") != name:
                        continue
                    ag_avg = self._get_avg(three_ago, plat_prev or plat_latest, platform=plat, level="adgroup", name=ag["name"])
                    ag_ref = ag_avg[0].get("roas_platform", 0) if ag_avg else 0
                    ag_trend = self._trend(ag["roas_platform"], ag_ref)

                    ag_conv = f"{ag['conversions']} conv"
                    ag_roas = f"ROAS {ag['roas_platform']:.1f}" if ag["roas_platform"] > 0 else ""
                    ag_freq = f"f{ag['frequency']:.1f}" if ag["frequency"] > 1 else ""

                    # 3-day trend sparkline — مقيّد بالحملة الأم
                    history = self._adgroup_history(ag["name"], plat, parent_name=name)
                    if len(history) >= 2:
                        vals = [r["roas_platform"] for r in history]
                        spark = "→".join(f"{v:.1f}" if v > 0 else "—" for v in vals)
                        arrows = ""
                        for i in range(1, len(vals)):
                            if vals[i-1] == 0:
                                arrows += "🆕"
                            elif vals[i] > vals[i-1] * 1.10:
                                arrows += "↑"
                            elif vals[i] < vals[i-1] * 0.90:
                                arrows += "↓"
                            else:
                                arrows += "→"
                        ag_trend_str = f" [{spark}] {arrows}"
                    else:
                        ag_trend_str = f" {ag_trend}"

                    ag_badge = self._status_badge(ag.get("status", ""))
                    lines.append(f"    └ {ag['name'][:26]:<26} صرف {ag['spend']:>5.0f} | {ag_conv} | {ag_roas} {ag_freq}{ag_trend_str}{ag_badge}")

                    # Ads under this ad group
                    ads = self._get_day(plat_latest, platform=plat, level="ad")
                    for ad in ads:
                        if ad.get("parent_name") != ag["name"]:
                            continue
                        ad_avg_list = self._get_avg(three_ago, plat_prev or plat_latest, platform=plat, level="ad", name=ad["name"])
                        ad_ref = ad_avg_list[0].get("roas_platform", 0) if ad_avg_list else 0
                        ad_trend = self._trend(ad["roas_platform"], ad_ref)

                        ad_conv = f"{ad['conversions']}" if ad["conversions"] > 0 else "0"
                        ad_roas = f"ROAS {ad['roas_platform']:.1f}" if ad["roas_platform"] > 0 else ""
                        ad_badge = self._status_badge(ad.get("status", ""))
                        lines.append(f"        {ad['name'][:24]:<24} {ad['spend']:>4.0f} | {ad_conv} conv | {ad_roas} {ad_trend}{ad_badge}")

        # ── Salla truth + Blended ROAS ──
        with self._conn() as conn:
            salla_rows = conn.execute(
                "SELECT * FROM salla_truth WHERE pull_date=? ORDER BY revenue DESC",
                (self.today,)
            ).fetchall()
            salla_sum = conn.execute(
                "SELECT * FROM salla_summary WHERE pull_date=? ORDER BY period_end DESC LIMIT 1",
                (self.today,)
            ).fetchone()

        # Total ad spend for the period
        with self._conn() as conn:
            row = conn.execute("""
                SELECT COALESCE(SUM(spend),0) FROM snapshots
                WHERE level='campaign'
                  AND pull_date=(SELECT MAX(pull_date) FROM snapshots)
            """).fetchone()
            period_spend = row[0] if row else 0

        if salla_rows or salla_sum:
            lines.append(f"\n{'─'*55}")
            lines.append("  SALLA (حقيقة المتجر)")
            lines.append(f"{'─'*55}")

        # Campaign-level truth
        campaign_rev = 0
        campaign_purch = 0
        if salla_rows:
            for s in salla_rows:
                s = dict(s)
                lines.append(f"  {s['campaign_name'][:30]:<30} إيراد {s['revenue']:>8,.0f} | {s['purchases']} طلب")
                campaign_rev += s["revenue"]
                campaign_purch += s["purchases"]

        # Blended ROAS (store-level) + Campaign ROAS + Halo
        if salla_sum:
            salla_sum = dict(salla_sum)
            store_rev = salla_sum["total_revenue"]
            store_orders = salla_sum["total_orders"]
            lines.append(f"\n  {'─'*50}")
            lines.append(f"  إيراد المتجر الكامل: {store_rev:,.0f} SAR ({store_orders} طلب)")

            if period_spend > 0:
                blended = store_rev / period_spend
                floor = self.cfg["blended_floor"]
                be = self.cfg["breakeven"]
                bl_status = "🟢" if blended >= floor else ("🔴" if blended < be else "⚠️")
                lines.append(f"  Blended ROAS:  {blended:.2f} {bl_status}  (متجر {store_rev:,.0f} / صرف {period_spend:,.0f})")

                if campaign_rev > 0:
                    camp_roas = campaign_rev / period_spend
                    halo_rev = store_rev - campaign_rev
                    halo_pct = (halo_rev / store_rev * 100) if store_rev > 0 else 0
                    lines.append(f"  Campaign ROAS: {camp_roas:.2f}      (حملات {campaign_rev:,.0f} / صرف {period_spend:,.0f})")
                    lines.append(f"  الهالة: {halo_pct:.0f}% من الإيراد ({halo_rev:,.0f} SAR) — مبيعات بسبب الإعلان لكن بدون UTM")
                    lines.append(f"  [Campaign = أرضية | Blended = الحقيقة | الفرق = هالة الإعلان]")
        elif period_spend > 0 and campaign_rev > 0:
            # Fallback: no salla_summary, show campaign ROAS only
            camp_roas = campaign_rev / period_spend
            lines.append(f"  {'─'*50}")
            lines.append(f"  Campaign ROAS: {camp_roas:.2f} (إيراد {campaign_rev:,.0f} / صرف {period_spend:,.0f})")
            lines.append(f"  ⚠️ Blended ROAS غير متاح — يحتاج سحب reports_sales_summary")

        # ── Maturity ──
        deltas = self._maturity_delta()
        if deltas:
            lines.append(f"\n{'─'*55}")
            lines.append("  نضج أمس (أرقام تغيرت بعد إعادة السحب):")
            for d in deltas:
                sign = "+" if d["conv_delta"] > 0 else ""
                lines.append(f"    {d['platform']} {d['name'][:25]}: {sign}{d['conv_delta']} conv ({d['conv_old']}→{d['conv_new']})")

        # ── Alerts & Monitoring ──
        raw_alerts = self._detect_alerts(all_campaigns, all_avg)
        monitor = self._update_monitor(raw_alerts)

        lines.append(f"\n{'─'*55}")

        if not monitor:
            lines.append("  ✅ لا تنبيهات")
        else:
            actions = {k: v for k, v in monitor.items() if v["level"] == "action"}
            warns = {k: v for k, v in monitor.items() if v["level"] == "warn"}
            monitors = {k: v for k, v in monitor.items() if v["level"] == "monitor"}

            if actions:
                lines.append(f"  🔴 أكشن ({len(actions)}):")
                for v in actions.values():
                    lines.append(f"    • {v['signal']} — {v['days']} أيام (منذ {v['first_seen']})")
            if warns:
                lines.append(f"  ⚠️ تحذير ({len(warns)}):")
                for v in warns.values():
                    lines.append(f"    • {v['signal']} — يومين")
            if monitors:
                lines.append(f"  📋 مراقبة ({len(monitors)}):")
                for v in monitors.values():
                    lines.append(f"    • {v['signal']}")

        lines.append("")
        return "\n".join(lines)

    # ── LEARN ───────────────────────────────────

    def learn(self):
        """Analyze today's data and extract learnings for future checks.

        Returns a list of learning dicts + saves them to SQLite.
        Categories:
            data_quality  — missing/late/changed data
            performance   — notable ROAS/CPA/CTR patterns
            anomaly       — unexpected spikes or drops
            budget        — pacing insights
        """
        learnings = []
        dates = self._latest_dates()
        if not dates:
            return learnings

        latest = dates[0]
        prev = dates[1] if len(dates) > 1 else None

        # --- 1. Data quality: platform delays ---
        for plat in self.cfg["platforms"]:
            plat_dates = self._latest_dates(platform=plat)
            if not plat_dates:
                learnings.append({
                    "category": "data_quality",
                    "signal": f"{plat}: لا بيانات اليوم",
                    "detail": f"Windsor لم يُرجع بيانات {plat} لأي يوم في هذا السحب",
                    "actionable": 1,
                })
            elif plat_dates[0] != latest:
                delay_days = (datetime.strptime(latest, "%Y-%m-%d") -
                              datetime.strptime(plat_dates[0], "%Y-%m-%d")).days
                learnings.append({
                    "category": "data_quality",
                    "signal": f"{plat}: بيانات متأخرة {delay_days} يوم",
                    "detail": f"آخر بيانات {plat}: {plat_dates[0]} بينما أحدث منصة: {latest}",
                    "actionable": 0,
                })

        # --- 2. Data quality: maturity shifts ---
        deltas = self._maturity_delta()
        big_shifts = [d for d in deltas if abs(d["conv_delta"]) >= 2]
        if big_shifts:
            names = ", ".join(f"{d['name'][:20]} ({d['conv_delta']:+d})" for d in big_shifts)
            learnings.append({
                "category": "data_quality",
                "signal": f"نضج كبير: {len(big_shifts)} حملة تغيرت بـ2+ تحويل",
                "detail": names,
                "actionable": 0,
            })

        # --- 3. Performance: best & worst campaigns ---
        campaigns = self._get_day(latest, level="campaign")
        if campaigns:
            # Sort by ROAS
            with_roas = [c for c in campaigns if c["roas_platform"] > 0 and c["spend"] > 30]
            if with_roas:
                best = max(with_roas, key=lambda c: c["roas_platform"])
                worst = min(with_roas, key=lambda c: c["roas_platform"])
                if best["name"] != worst["name"]:
                    learnings.append({
                        "category": "performance",
                        "signal": f"أفضل حملة: {best['name'][:25]} (ROAS {best['roas_platform']:.1f})",
                        "detail": f"صرف {best['spend']:.0f}, {best['conversions']} تحويل",
                        "actionable": 0,
                    })
                    be = self.cfg["breakeven"]
                    inf = self.cfg["inflation"].get(worst["platform"], 1.0)
                    real_roas = worst["roas_platform"] / inf
                    if real_roas < be:
                        learnings.append({
                            "category": "performance",
                            "signal": f"أسوأ حملة: {worst['name'][:25]} (ROAS حقيقي {real_roas:.1f} < تعادل {be})",
                            "detail": f"صرف {worst['spend']:.0f}, {worst['conversions']} تحويل, ROAS منصة {worst['roas_platform']:.1f}",
                            "actionable": 1,
                        })

            # Zero-conversion campaigns with spend
            zero_conv = [c for c in campaigns if c["conversions"] == 0 and c["spend"] >= 50]
            for c in zero_conv:
                learnings.append({
                    "category": "anomaly",
                    "signal": f"صفر تحويل: {c['name'][:25]} (صرف {c['spend']:.0f})",
                    "detail": f"منصة {c['platform']}, CTR {c['ctr']:.2%}",
                    "actionable": 1 if c["spend"] >= self.cfg["guardrails"]["zero_conv_kill"] else 0,
                })

        # --- 4. Performance: day-over-day ROAS change ---
        if prev:
            prev_camps = {c["name"]: c for c in self._get_day(prev, level="campaign")}
            for c in campaigns:
                p = prev_camps.get(c["name"])
                if p and p["roas_platform"] > 0 and c["roas_platform"] > 0 and c["spend"] > 30:
                    chg = (c["roas_platform"] - p["roas_platform"]) / p["roas_platform"]
                    if abs(chg) > 0.30:
                        direction = "ارتفاع" if chg > 0 else "انخفاض"
                        learnings.append({
                            "category": "anomaly",
                            "signal": f"ROAS {direction} {abs(chg)*100:.0f}%: {c['name'][:25]}",
                            "detail": f"أمس {p['roas_platform']:.1f} → اليوم {c['roas_platform']:.1f}",
                            "actionable": 1 if chg < -0.30 else 0,
                        })

        # --- 5. Performance: ad group heroes & zeroes ---
        adgroups = self._get_day(latest, level="adgroup")
        if adgroups:
            # Only analyze ACTIVE adgroups for hero/zero detection
            active_ags = [a for a in adgroups if self._is_alertable(a.get("status", ""))]

            # Hero: high ROAS ad group
            ag_with_roas = [a for a in active_ags if a["roas_platform"] > 0 and a["spend"] > 20]
            if ag_with_roas:
                hero = max(ag_with_roas, key=lambda a: a["roas_platform"])
                if hero["roas_platform"] > 8:
                    learnings.append({
                        "category": "performance",
                        "signal": f"مجموعة بطلة: {hero['name'][:25]} (ROAS {hero['roas_platform']:.1f})",
                        "detail": f"تحت {hero.get('parent_name','')[:20]}, صرف {hero['spend']:.0f}",
                        "actionable": 0,
                    })

            # Zero: active ad group draining budget (skip paused — user already acted)
            ag_zero = [a for a in active_ags if a["conversions"] == 0 and a["spend"] >= 40]
            for a in ag_zero:
                learnings.append({
                    "category": "anomaly",
                    "signal": f"مجموعة بدون تحويل: {a['name'][:25]} (صرف {a['spend']:.0f})",
                    "detail": f"تحت {a.get('parent_name','')[:20]}, CTR {a['ctr']:.2%}",
                    "actionable": 1,
                })

        # --- 6. Budget: pacing insight ---
        pace = self._pacing()
        if pace["projected"] > pace["cap"] * 1.1:
            learnings.append({
                "category": "budget",
                "signal": f"تخطي السقف المتوقع: {pace['projected']:,.0f} / {pace['cap']:,.0f}",
                "detail": f"يوم {pace['day']} من الشهر, صُرف {pace['spent']:,.0f}",
                "actionable": 1,
            })
        elif pace["projected"] < pace["cap"] * 0.5 and pace["day"] > 7:
            learnings.append({
                "category": "budget",
                "signal": f"صرف منخفض جداً: متوقع {pace['projected']:,.0f} / {pace['cap']:,.0f}",
                "detail": f"يوم {pace['day']}, فرصة لزيادة الصرف في الذروة",
                "actionable": 1,
            })

        # --- 7. Frequency: creative fatigue early warning ---
        for c in campaigns:
            if c["frequency"] > 2.0 and c["spend"] > 30:
                limit = self.cfg["guardrails"]["freq_prospecting"]
                ratio = c["frequency"] / limit
                if ratio > 0.75:
                    learnings.append({
                        "category": "performance",
                        "signal": f"تردد مرتفع: {c['name'][:25]} ({c['frequency']:.1f}/{limit})",
                        "detail": f"بلغ {ratio*100:.0f}% من الحد — جهّز كرييتف بديل",
                        "actionable": 1 if ratio >= 1.0 else 0,
                    })

        # --- 8. Blended ROAS trend (if salla_summary available) ---
        with self._conn() as conn:
            salla_recent = conn.execute("""
                SELECT pull_date, total_revenue FROM salla_summary
                ORDER BY pull_date DESC LIMIT 3
            """).fetchall()
        if len(salla_recent) >= 2:
            today_rev = salla_recent[0]["total_revenue"]
            prev_rev = salla_recent[1]["total_revenue"]
            if prev_rev > 0:
                rev_chg = (today_rev - prev_rev) / prev_rev
                if abs(rev_chg) > 0.25:
                    direction = "ارتفاع" if rev_chg > 0 else "انخفاض"
                    learnings.append({
                        "category": "performance",
                        "signal": f"إيراد المتجر {direction} {abs(rev_chg)*100:.0f}%",
                        "detail": f"{prev_rev:,.0f} → {today_rev:,.0f} SAR",
                        "actionable": 1 if rev_chg < -0.25 else 0,
                    })

        # --- Save to DB ---
        with self._conn() as conn:
            for l in learnings:
                conn.execute("""
                    INSERT OR IGNORE INTO learnings
                    (pull_date, category, signal, detail, actionable)
                    VALUES (?, ?, ?, ?, ?)
                """, (self.today, l["category"], l["signal"], l["detail"], l["actionable"]))

        return learnings

    def learnings_report(self):
        """Format learnings into a readable section for the daily report."""
        learnings = self.learn()
        if not learnings:
            return "\nلا اكتشافات جديدة اليوم."

        lines = []
        lines.append(f"\n{'='*55}")
        lines.append(f"  اكتشافات اليوم ({len(learnings)})")
        lines.append(f"{'='*55}")

        by_cat = {}
        for l in learnings:
            by_cat.setdefault(l["category"], []).append(l)

        cat_labels = {
            "data_quality": "جودة البيانات",
            "performance": "الأداء",
            "anomaly": "شذوذ",
            "budget": "الميزانية",
        }
        cat_icons = {
            "data_quality": "📊",
            "performance": "📈",
            "anomaly": "⚡",
            "budget": "💰",
        }

        for cat, items in by_cat.items():
            icon = cat_icons.get(cat, "•")
            label = cat_labels.get(cat, cat)
            lines.append(f"\n  {icon} {label}:")
            for item in items:
                action_mark = " ← تحتاج تدخل" if item["actionable"] else ""
                lines.append(f"    • {item['signal']}{action_mark}")
                if item["detail"]:
                    lines.append(f"      {item['detail']}")

        # History: how many total learnings we have
        with self._conn() as conn:
            total = conn.execute("SELECT COUNT(*) FROM learnings").fetchone()[0]
            days = conn.execute("SELECT COUNT(DISTINCT pull_date) FROM learnings").fetchone()[0]
        lines.append(f"\n  {'─'*50}")
        lines.append(f"  المجموع التراكمي: {total} اكتشاف من {days} يوم فحص")
        lines.append("")

        return "\n".join(lines)

    def export_learnings_md(self):
        """Export all learnings to a markdown file for the client."""
        client_dir = self.base_dir / f"clients/{self.client}/data"
        os.makedirs(client_dir, exist_ok=True)
        filepath = client_dir / "learnings.md"

        with self._conn() as conn:
            rows = conn.execute("""
                SELECT pull_date, category, signal, detail, actionable
                FROM learnings ORDER BY pull_date DESC, category
            """).fetchall()

        if not rows:
            return str(filepath)

        lines = [f"# اكتشافات {self.client} — تراكمي\n"]
        lines.append(f"> آخر تحديث: {self.today}\n")

        current_date = None
        for r in rows:
            r = dict(r)
            if r["pull_date"] != current_date:
                current_date = r["pull_date"]
                lines.append(f"\n## {current_date}")
            action = " **[تدخل]**" if r["actionable"] else ""
            lines.append(f"- [{r['category']}] {r['signal']}{action}")
            if r["detail"]:
                lines.append(f"  - {r['detail']}")

        with open(filepath, "w") as f:
            f.write("\n".join(lines))

        return str(filepath)


# ──────────────────────────────────────────────
# TEST
# ──────────────────────────────────────────────

if __name__ == "__main__":
    import tempfile, shutil

    tmp = tempfile.mkdtemp()
    os.makedirs(os.path.join(tmp, "clients/noura/data"), exist_ok=True)

    checker = DailyCheck("noura", today="2026-06-07", base_dir=tmp)

    # Simulate 3 days of Windsor data (active campaign)
    for day, spend, conv, roas in [
        ("2026-06-05", 420, 6, 5.2),
        ("2026-06-06", 410, 7, 5.1),
        ("2026-06-07", 385, 5, 4.2),
    ]:
        checker.store_windsor([{
            "date": day, "campaign_name": "Main | May 2026",
            "campaign_status": "CAMPAIGN_STATUS_ENABLE",
            "spend": spend, "conversions": conv, "complete_payment_roas": roas,
            "ctr": 0.031, "cpm": 7.5, "frequency": 1.8,
            "impressions": 50000, "clicks": 1550,
        }], "tiktok", "campaign")

    # Ad groups — 3 days: Wasayef active, Asayel paused today
    for day, name, status, spend, conv, roas in [
        ("2026-06-05", "Wasayef",               "ADGROUP_STATUS_DELIVERY_OK", 200, 4, 5.2),
        ("2026-06-05", "Asayel | NTC | looklike","ADGROUP_STATUS_DELIVERY_OK", 150, 3, 5.5),
        ("2026-06-06", "Wasayef",               "ADGROUP_STATUS_DELIVERY_OK", 210, 3, 4.1),
        ("2026-06-06", "Asayel | NTC | looklike","ADGROUP_STATUS_DELIVERY_OK", 155, 3, 6.0),
        ("2026-06-07", "Wasayef",               "ADGROUP_STATUS_DELIVERY_OK", 220, 2, 3.1),
        ("2026-06-07", "Asayel | NTC | looklike","ADGROUP_STATUS_DISABLE",     160, 0, 0.0),
    ]:
        checker.store_windsor([{
            "date": day, "adgroup_name": name, "campaign_name": "Main | May 2026",
            "adgroup_status": status,
            "spend": spend, "conversions": conv, "complete_payment_roas": roas,
            "ctr": 0.029, "cpm": 8.0, "frequency": 1.5,
            "impressions": 25000, "clicks": 725,
        }], "tiktok", "adgroup")

    # Gulf campaign (new, active)
    checker.store_windsor([{
        "date": "2026-06-07", "campaign_name": "Gulf Sales | JUN",
        "campaign_status": "CAMPAIGN_STATUS_ENABLE",
        "spend": 45, "conversions": 0, "complete_payment_roas": 0,
        "ctr": 0.012, "cpm": 5.0, "frequency": 1.0,
        "impressions": 9000, "clicks": 108,
    }], "tiktok", "campaign")

    # Ads (creatives) under Wasayef — one active, one paused
    for ad_name, status, spend, conv, roas in [
        ("Image carousel 3", "AD_STATUS_DELIVERY_OK",    350, 6, 4.8),
        ("Image carousel 4", "AD_STATUS_DELIVERY_OK",    180, 3, 3.9),
        ("وصايف تجنن",        "AD_STATUS_DISABLE",         90, 0, 0.0),
    ]:
        checker.store_windsor([{
            "date": "2026-06-07", "ad_name": ad_name,
            "ad_group_name": "Wasayef", "campaign_name": "Main | May 2026",
            "ad_status": status,
            "spend": spend, "conversions": conv, "complete_payment_roas": roas,
            "ctr": 0.04, "cpm": 7.0, "frequency": 0,
            "impressions": 0, "clicks": 0,
        }], "tiktok", "ad")

    # Salla truth (campaign-level)
    checker.store_salla([
        {"campaign": "Main | May 2026", "revenue": 1200, "purchases": 3},
    ], report_date="2026-06-07")

    # Salla summary (store-level — for Blended ROAS)
    checker.store_salla_summary(
        total_revenue=3500, total_orders=9,
        period_start="2026-06-05", period_end="2026-06-07",
    )

    print(checker.report())
    print(checker.learnings_report())
    print(f"Learnings exported to: {checker.export_learnings_md()}")

    shutil.rmtree(tmp)
