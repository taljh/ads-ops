#!/usr/bin/env python3
"""
render_report.py — Daily Brief visual renderer (English, self-contained HTML).

Takes a report data dict (or JSON file) and emits a single self-contained
HTML dashboard. Design language mirrors tools/brief_template.html:
color = signal only (red/amber = guardrail breach or danger trend), neutral gray
for everything else.

Hierarchy rendered per client:
  Store Truth (KPI + triple delta) → Source Attribution (who drove sales)
  → 8-day Revenue Trend → Guardrails → Data Quality → Ad Platform
  (Campaign → Ad Group → Ad → Creative).

Usage:
    python3 tools/render_report.py <data.json> <out.html>
"""

import json
import sys
from pathlib import Path


# ── delta helpers ────────────────────────────────────────────
def pct(cur, ref):
    if ref in (None, 0) or cur is None:
        return None
    return (cur - ref) / ref * 100.0


def delta_html(cur, ref, higher_is_good=True, money=False):
    p = pct(cur, ref)
    if p is None:
        return '<span class="delta delta-na">—</span>'
    up = p >= 0
    good = up if higher_is_good else not up
    cls = "delta-up" if good else "delta-down"
    arrow = "▲" if up else "▼"
    return f'<span class="delta {cls}">{arrow} {abs(p):.0f}%</span>'


def money(v):
    if v is None:
        return "—"
    return f"{v:,.0f}"


# ── section renderers ────────────────────────────────────────
def render_kpi(label, cur, y, d3, d7, higher_is_good=True, unit="SAR"):
    return f"""
      <div class="kpi">
        <div class="kpi-label">{label}</div>
        <div class="kpi-value">{money(cur)}<span class="kpi-unit">{unit}</span></div>
        <div class="kpi-deltas">
          <span class="dl">vs 1d {delta_html(cur, y, higher_is_good)}</span>
          <span class="dl">vs 3d {delta_html(cur, d3, higher_is_good)}</span>
          <span class="dl">vs 7d {delta_html(cur, d7, higher_is_good)}</span>
        </div>
      </div>"""


def render_trend(trend, value_key="revenue"):
    vals = [max(0.0, float(r.get(value_key) or 0)) for r in trend]
    mx = max(vals) or 1
    bars = ""
    for r, v in zip(trend, vals):
        h = 6 + int(52 * v / mx)
        last = ' bar-last' if r is trend[-1] else ''
        bars += (
            f'<div class="bar-col"><div class="bar{last}" style="height:{h}px" '
            f'title="{r.get("date")}: {money(v)}"></div>'
            f'<div class="bar-x">{r.get("date","")[-5:]}</div></div>'
        )
    return f'<div class="trend">{bars}</div>'


def render_sources(sources, best):
    rows = ""
    for s in sources:
        roas = s.get("roas")
        roas_txt = f'{roas:.2f}x' if roas else '<span class="muted">needs spend</span>'
        star = ' 🏆' if s.get("source") == best else ""
        rows += f"""
          <tr>
            <td class="src-name">{s.get('source')}{star}</td>
            <td class="num">{money(s.get('revenue'))}</td>
            <td class="num">{s.get('purchases','—')}</td>
            <td class="num">{s.get('share',0):.0f}%</td>
            <td class="num">{roas_txt}</td>
          </tr>"""
    return f"""
      <table class="tbl">
        <thead><tr>
          <th>Source</th><th class="num">Revenue</th><th class="num">Purchases</th>
          <th class="num">Share</th><th class="num">ROAS</th>
        </tr></thead>
        <tbody>{rows}</tbody>
      </table>"""


def render_guardrails(items):
    cells = ""
    for g in items:
        st = g.get("status", "na")
        cls = {"fail": "gr-fail", "warn": "gr-warn", "ok": "gr-ok"}.get(st, "gr-na")
        icon = {"fail": "🔴", "warn": "🟡", "ok": "🟢"}.get(st, "⚪")
        cells += f"""
          <div class="gr-item {cls}">
            <span class="gr-icon">{icon}</span>
            <div><div class="gr-name">{g.get('name')}</div>
            <div class="gr-detail">{g.get('detail','')}</div></div>
          </div>"""
    return f'<div class="gr-grid">{cells}</div>'


def render_ad_platform(ap):
    if ap.get("status") == "pending":
        return f"""
      <div class="pending">
        <div class="pending-title">⏳ Ad-platform layer pending — {ap.get('reason','')}</div>
        <div class="pending-body">{ap.get('note','')}</div>
        <div class="pending-scaffold">Will render: Campaign → Ad Group → Ad → Creative
        (spend · ROAS · CTR · CPM · frequency + fatigue badge · thumbnails), each with 1d/3d/7d deltas.</div>
      </div>"""
    # populated hierarchy
    html = ""
    note = ap.get("note", "")
    if note:
        html += f'<div class="ap-note">{note}</div>'
    for lvl, rows in [("Campaigns", ap.get("campaigns", [])),
                      ("Ad Groups", ap.get("adgroups", [])),
                      ("Ads", ap.get("ads", []))]:
        if not rows:
            continue
        trs = ""
        for r in rows:
            st = r.get("status", "")
            rcls = {"fail": "row-fail", "warn": "row-warn"}.get(st, "")
            cpa = r.get("cpa")
            cpa_txt = f'{cpa:.0f}' if cpa else "—"
            freq = r.get("frequency")
            freq_txt = f'{freq:.2f}' if freq else "—"
            flag = ""
            if cpa and r.get("cpa_ceiling") and cpa > r["cpa_ceiling"]:
                flag += ' <span class="mini-flag">CPA↑</span>'
            if freq and freq >= 2.5:
                flag += ' <span class="mini-flag">fatigue</span>'
            trs += (f'<tr class="{rcls}"><td>{r.get("name")}{flag}</td>'
                    f'<td class="num">{money(r.get("spend"))}</td>'
                    f'<td class="num">{r.get("conversions","—")}</td>'
                    f'<td class="num">{cpa_txt}</td>'
                    f'<td class="num">{freq_txt}</td>'
                    f'<td class="num">{r.get("ctr","—")}%</td>'
                    f'<td class="num">{delta_html(r.get("spend"), r.get("spend_7d"))}</td></tr>')
        html += (f'<div class="sub-label">{lvl} <span class="section-sub">today</span></div>'
                 f'<table class="tbl"><thead><tr>'
                 f'<th>Name</th><th class="num">Spend</th><th class="num">Conv</th>'
                 f'<th class="num">CPA</th><th class="num">Freq</th><th class="num">CTR</th>'
                 f'<th class="num">Spend vs 7d</th></tr></thead>'
                 f'<tbody>{trs}</tbody></table>')
    # creatives grid
    cr = ap.get("creatives", [])
    if cr:
        cards = ""
        for c in cr:
            fatigue = ' <span class="badge-fatigue">🔴 fatigue</span>' if c.get("frequency", 0) >= 2.5 else ""
            thumb = c.get("thumb", "")
            img = f'<img src="{thumb}" class="thumb"/>' if thumb else '<div class="thumb thumb-blank">no preview</div>'
            cards += (f'<div class="cr-card">{img}<div class="cr-name">{c.get("name")}{fatigue}</div>'
                      f'<div class="cr-meta">CTR {c.get("ctr","—")}% · freq {c.get("frequency","—")} · '
                      f'{money(c.get("spend"))} SAR</div></div>')
        html += f'<div class="sub-label">Creatives</div><div class="cr-grid">{cards}</div>'
    return html


def render_client(c):
    t = c.get("truth", {})
    rev, orders, aov = t.get("revenue", {}), t.get("orders", {}), t.get("aov", {})
    dec = c.get("decision", {})
    dcls = {"high": "dec-high", "med": "dec-med", "low": "dec-low"}.get(dec.get("priority"), "dec-med")
    dq = "".join(f"<li>{x}</li>" for x in c.get("data_quality", []))
    dq_block = f'<div class="section"><div class="section-label">Data Quality & Backfill</div><ul class="dq">{dq}</ul></div>' if dq else ""
    return f"""
    <section class="client">
      <div class="client-head">
        <h2>{c.get('name')}</h2>
        <span class="pill">{c.get('settlement','').upper()}</span>
      </div>

      <div class="decision {dcls}">
        <div class="dec-tag">🎯 TODAY'S DECISION</div>
        <div class="dec-title">{dec.get('title','')}</div>
        <div class="dec-detail">{dec.get('detail','')}</div>
      </div>

      <div class="section">
        <div class="section-label">Store Truth <span class="section-sub">Salla — ground truth</span></div>
        <div class="kpi-row">
          {render_kpi("Revenue (today)", rev.get('today'), rev.get('yesterday'), rev.get('d3'), rev.get('d7'))}
          {render_kpi("Orders (today)", orders.get('today'), orders.get('yesterday'), orders.get('d3'), orders.get('d7'), unit="")}
          {render_kpi("AOV", aov.get('today'), aov.get('yesterday'), aov.get('d3'), aov.get('d7'))}
        </div>
      </div>

      <div class="section">
        <div class="section-label">Source Attribution <span class="section-sub">who drove the sales</span></div>
        {render_sources(c.get('sources', []), c.get('best_source'))}
      </div>

      <div class="section">
        <div class="section-label">8-Day Revenue Trend</div>
        {render_trend(c.get('trend', []))}
      </div>

      <div class="section">
        <div class="section-label">Guardrails</div>
        {render_guardrails(c.get('guardrails', []))}
      </div>

      {dq_block}

      <div class="section">
        <div class="section-label">Ad Platform <span class="section-sub">campaign → ad group → ad → creative</span></div>
        {render_ad_platform(c.get('ad_platform', {}))}
      </div>
    </section>"""


CSS = """
:root{--ink:#111827;--ink3:#6b7280;--bg:#f3f4f6;--surface:#fff;--border:#e5e7eb;
--green:#16a34a;--amber:#d97706;--red:#dc2626;--blue:#2563eb;}
*{box-sizing:border-box;margin:0;padding:0}
body{font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;background:var(--bg);color:var(--ink);font-size:13px;line-height:1.5;padding-bottom:40px}
.header{background:#0f172a;color:#fff;padding:18px 32px;display:flex;justify-content:space-between;align-items:center;flex-wrap:wrap;gap:8px}
.header h1{font-size:18px}.header .sub{font-size:11px;color:#94a3b8;margin-top:2px}
.pills{display:flex;gap:6px}.pill{background:#e5e7eb;color:#374151;font-size:10px;font-weight:600;padding:3px 8px;border-radius:10px;letter-spacing:.03em}
.header .pill{background:#1e293b;color:#cbd5e1}
.page{max-width:1000px;margin:0 auto;padding:0 20px}
.client{background:var(--surface);border:1px solid var(--border);border-radius:12px;padding:22px;margin-top:20px}
.client-head{display:flex;align-items:center;gap:10px;margin-bottom:14px}
.client-head h2{font-size:17px}
.decision{border-radius:10px;padding:14px 16px;margin-bottom:18px;border-left:4px solid var(--blue);background:#f8fafc}
.dec-high{border-left-color:var(--red);background:#fef2f2}.dec-med{border-left-color:var(--amber);background:#fffbeb}.dec-low{border-left-color:var(--green);background:#f0fdf4}
.dec-tag{font-size:10px;font-weight:700;letter-spacing:.08em;color:var(--ink3)}
.dec-title{font-size:15px;font-weight:700;margin:3px 0 4px}.dec-detail{font-size:12.5px;color:var(--ink3)}
.section{margin-top:18px}
.section-label{font-size:12px;font-weight:700;text-transform:uppercase;letter-spacing:.05em;color:var(--ink);border-bottom:1px solid var(--border);padding-bottom:5px;margin-bottom:10px}
.section-sub{text-transform:none;letter-spacing:0;font-weight:400;color:var(--ink3);font-size:11px;margin-left:6px}
.sub-label{font-size:11px;font-weight:700;color:var(--ink3);margin:12px 0 6px}
.kpi-row{display:flex;gap:12px;flex-wrap:wrap}
.kpi{flex:1;min-width:180px;border:1px solid var(--border);border-radius:8px;padding:12px}
.kpi-label{font-size:11px;color:var(--ink3)}.kpi-value{font-size:24px;font-weight:700;margin:2px 0}
.kpi-unit{font-size:12px;font-weight:400;color:var(--ink3);margin-left:4px}
.kpi-deltas{display:flex;gap:10px;flex-wrap:wrap;font-size:10.5px;color:var(--ink3)}
.delta{font-weight:700}.delta-up{color:var(--green)}.delta-down{color:var(--red)}.delta-na{color:var(--ink3)}
.tbl{width:100%;border-collapse:collapse;font-size:12.5px}
.tbl th,.tbl td{text-align:left;padding:7px 10px;border-bottom:1px solid var(--border)}
.tbl th{font-size:10.5px;text-transform:uppercase;letter-spacing:.04em;color:var(--ink3)}
.num{text-align:right;font-variant-numeric:tabular-nums}.src-name{font-weight:600;text-transform:capitalize}
.muted{color:var(--ink3);font-style:italic}
.trend{display:flex;align-items:flex-end;gap:8px;height:80px;padding-top:6px}
.bar-col{display:flex;flex-direction:column;align-items:center;gap:4px;flex:1}
.bar{width:70%;background:#cbd5e1;border-radius:3px 3px 0 0}.bar-last{background:var(--blue)}
.bar-x{font-size:9px;color:var(--ink3)}
.gr-grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(220px,1fr));gap:8px}
.gr-item{display:flex;gap:8px;border:1px solid var(--border);border-radius:8px;padding:8px 10px}
.gr-fail{background:#fef2f2;border-color:#fecaca}.gr-warn{background:#fffbeb;border-color:#fde68a}.gr-ok{background:#f0fdf4;border-color:#bbf7d0}
.gr-name{font-size:12px;font-weight:600}.gr-detail{font-size:11px;color:var(--ink3)}
.dq{margin-left:18px;color:var(--ink3);font-size:12px}.dq li{margin:3px 0}
.pending{border:1px dashed #cbd5e1;border-radius:8px;padding:14px;background:#f8fafc}
.pending-title{font-weight:700;color:var(--amber);font-size:12.5px}
.pending-body{font-size:12px;color:var(--ink3);margin:6px 0}
.pending-scaffold{font-size:11px;color:#94a3b8;border-top:1px dashed #e5e7eb;padding-top:6px;margin-top:6px}
.cr-grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(150px,1fr));gap:10px}
.cr-card{border:1px solid var(--border);border-radius:8px;overflow:hidden}
.thumb{width:100%;height:110px;object-fit:cover;display:block}
.thumb-blank{display:flex;align-items:center;justify-content:center;background:#f3f4f6;color:#9ca3af;font-size:11px}
.cr-name{font-size:11.5px;font-weight:600;padding:6px 8px 2px}.cr-meta{font-size:10.5px;color:var(--ink3);padding:0 8px 8px}
.badge-fatigue{font-size:9px;color:var(--red);font-weight:700}
.ap-note{font-size:11.5px;color:var(--ink3);background:#f8fafc;border:1px solid var(--border);border-radius:6px;padding:8px 10px;margin-bottom:10px}
.row-fail td{background:#fef2f2}.row-warn td{background:#fffbeb}
.mini-flag{font-size:9px;font-weight:700;color:var(--red);background:#fee2e2;padding:1px 5px;border-radius:4px;margin-left:4px}
.foot{max-width:1000px;margin:16px auto 0;padding:0 20px;font-size:11px;color:var(--ink3)}
"""


def build_html(data):
    clients = "".join(render_client(c) for c in data.get("clients", []))
    phase = data.get("cycle_phase", "")
    return f"""<!DOCTYPE html><html lang="en"><head><meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Daily Brief — {data.get('date','')}</title><style>{CSS}</style></head>
<body>
  <div class="header">
    <div><h1>Daily Brief</h1><div class="sub">{data.get('date','')} · generated {data.get('generated','')}</div></div>
    <div class="pills">
      <span class="pill">{len(data.get('clients',[]))} clients</span>
      <span class="pill">cycle: {phase}</span>
      <span class="pill">backfill: last {data.get('backfill_window',4)}d</span>
    </div>
  </div>
  <div class="page">{clients}</div>
  <div class="foot">Truth = Salla revenue. Platform numbers are diagnostic. Blended ROAS governs budget.
  Monitor-only report — no platform actions taken. {data.get('footer','')}</div>
</body></html>"""


# ── email version (inline styles — Gmail strips <head>/<style>) ──
def build_email_html(data):
    def dl(cur, ref, hib=True):
        p = pct(cur, ref)
        if p is None:
            return '<span style="color:#6b7280">—</span>'
        good = (p >= 0) == hib
        col = "#16a34a" if good else "#dc2626"
        return f'<span style="color:{col};font-weight:700">{"▲" if p>=0 else "▼"} {abs(p):.0f}%</span>'
    blocks = ""
    for c in data.get("clients", []):
        dec = c.get("decision", {})
        bar = {"high": "#dc2626", "med": "#d97706", "low": "#16a34a"}.get(dec.get("priority"), "#2563eb")
        t = c.get("truth", {}); rev = t.get("revenue", {}); orders = t.get("orders", {})
        srows = ""
        for s in c.get("sources", []):
            star = " 🏆" if s.get("source") == c.get("best_source") else ""
            roas = f'{s["roas"]:.2f}x' if s.get("roas") else "—"
            srows += (f'<tr><td style="padding:3px 8px;text-transform:capitalize">{s.get("source")}{star}</td>'
                      f'<td style="padding:3px 8px;text-align:right">{money(s.get("revenue"))}</td>'
                      f'<td style="padding:3px 8px;text-align:right">{s.get("share",0):.0f}%</td>'
                      f'<td style="padding:3px 8px;text-align:right">{roas}</td></tr>')
        crows = ""
        for r in c.get("ad_platform", {}).get("campaigns", []):
            flag = ""
            if r.get("cpa") and r.get("cpa_ceiling") and r["cpa"] > r["cpa_ceiling"]:
                flag += ' <b style="color:#dc2626">CPA↑</b>'
            if r.get("frequency", 0) >= 2.5:
                flag += ' <b style="color:#dc2626">fatigue</b>'
            crows += (f'<tr><td style="padding:3px 8px">{r.get("name")}{flag}</td>'
                      f'<td style="padding:3px 8px;text-align:right">{money(r.get("spend"))}</td>'
                      f'<td style="padding:3px 8px;text-align:right">{r.get("conversions")}</td>'
                      f'<td style="padding:3px 8px;text-align:right">{r.get("cpa",0):.0f}</td>'
                      f'<td style="padding:3px 8px;text-align:right">{r.get("frequency","—")}</td></tr>')
        blocks += f"""
        <div style="border:1px solid #e5e7eb;border-radius:10px;padding:16px;margin:14px 0">
          <div style="font-size:16px;font-weight:700">{c.get('name')} <span style="font-size:10px;background:#e5e7eb;color:#374151;padding:2px 7px;border-radius:8px">{c.get('settlement','').upper()}</span></div>
          <div style="border-left:4px solid {bar};background:#f8fafc;border-radius:8px;padding:10px 12px;margin:10px 0">
            <div style="font-size:10px;font-weight:700;letter-spacing:.06em;color:#6b7280">🎯 TODAY'S DECISION</div>
            <div style="font-size:14px;font-weight:700;margin:2px 0">{dec.get('title','')}</div>
            <div style="font-size:12px;color:#374151">{dec.get('detail','')}</div>
          </div>
          <div style="font-size:13px;margin:6px 0">
            <b>Revenue</b> {money(rev.get('today'))} SAR &nbsp; vs1d {dl(rev.get('today'),rev.get('yesterday'))}
            &nbsp; vs7d {dl(rev.get('today'),rev.get('d7'))} &nbsp;·&nbsp;
            <b>Orders</b> {orders.get('today')} &nbsp; vs1d {dl(orders.get('today'),orders.get('yesterday'))}
          </div>
          <table style="border-collapse:collapse;font-size:12px;width:100%;margin-top:6px">
            <tr style="color:#6b7280;text-align:left"><th style="padding:3px 8px">Source</th><th style="padding:3px 8px;text-align:right">Revenue</th><th style="padding:3px 8px;text-align:right">Share</th><th style="padding:3px 8px;text-align:right">ROAS</th></tr>
            {srows}
          </table>
          <table style="border-collapse:collapse;font-size:12px;width:100%;margin-top:8px">
            <tr style="color:#6b7280;text-align:left"><th style="padding:3px 8px">Campaign (today)</th><th style="padding:3px 8px;text-align:right">Spend</th><th style="padding:3px 8px;text-align:right">Conv</th><th style="padding:3px 8px;text-align:right">CPA</th><th style="padding:3px 8px;text-align:right">Freq</th></tr>
            {crows}
          </table>
        </div>"""
    return f"""<div style="font-family:-apple-system,Segoe UI,sans-serif;max-width:680px;margin:0 auto;color:#111827">
      <div style="background:#0f172a;color:#fff;padding:14px 18px;border-radius:10px">
        <div style="font-size:17px;font-weight:700">Daily Brief — {data.get('date','')}</div>
        <div style="font-size:11px;color:#94a3b8">cycle: {data.get('cycle_phase','')} · backfill last {data.get('backfill_window',4)}d · monitor-only</div>
      </div>
      {blocks}
      <div style="font-size:11px;color:#6b7280;margin-top:10px">{data.get('footer','')}</div>
    </div>"""


def main():
    if len(sys.argv) < 3:
        print("usage: render_report.py <data.json> <out.html> [--email <email_out.html>]")
        sys.exit(1)
    data = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
    Path(sys.argv[2]).write_text(build_html(data), encoding="utf-8")
    print(f"wrote {sys.argv[2]}")
    if "--email" in sys.argv:
        eout = sys.argv[sys.argv.index("--email") + 1]
        Path(eout).write_text(build_email_html(data), encoding="utf-8")
        print(f"wrote {eout}")


if __name__ == "__main__":
    main()
