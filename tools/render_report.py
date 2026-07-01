#!/usr/bin/env python3
"""
render_report.py — Daily Brief visual renderer (English, self-contained HTML).

Information architecture (v2 — platform-nested):
  1. Portfolio bird's-eye (all clients: total spend / revenue / MER + alerts)
  2. Per client:
       Today's Decision → Client Totals (blended, triple delta)
       → Salla layer (store truth + attribution + trend)
       → Meta layer  (campaigns + analysis lenses)
       → TikTok layer (campaigns + analysis lenses)
       → Guardrails
  Analysis "lenses" per platform bake in the InsightfulPipe prompt library
  (performance / audience / creative / budget / health / week-over-week).

Design language mirrors tools/brief_template.html: color = signal only.
Monitor-only report — never edits platforms.

Usage:
    python3 tools/render_report.py <data.json> <out.html> [--email <email_out.html>]
"""

import json
import sys
from pathlib import Path


# ── helpers ──────────────────────────────────────────────────
def pct(cur, ref):
    if ref in (None, 0) or cur is None:
        return None
    return (cur - ref) / ref * 100.0


def delta_html(cur, ref, higher_is_good=True):
    p = pct(cur, ref)
    if p is None:
        return '<span class="delta delta-na">—</span>'
    good = (p >= 0) == higher_is_good
    cls = "delta-up" if good else "delta-down"
    return f'<span class="delta {cls}">{"▲" if p>=0 else "▼"} {abs(p):.0f}%</span>'


def money(v):
    return "—" if v is None else f"{v:,.0f}"


def roas_class(v, floor=4.5, breakeven=2.5):
    if v is None:
        return "chip-na"
    if v >= floor:
        return "chip-ok"
    if v >= breakeven:
        return "chip-warn"
    return "chip-fail"


# ── shared blocks ────────────────────────────────────────────
def kpi(label, cur, y, d3, d7, hib=True, unit="SAR"):
    return f"""
      <div class="kpi">
        <div class="kpi-label">{label}</div>
        <div class="kpi-value">{money(cur)}<span class="kpi-unit">{unit}</span></div>
        <div class="kpi-deltas">
          <span>1d {delta_html(cur, y, hib)}</span>
          <span>3d {delta_html(cur, d3, hib)}</span>
          <span>7d {delta_html(cur, d7, hib)}</span>
        </div>
      </div>"""


def render_trend(trend, key="revenue"):
    vals = [max(0.0, float(r.get(key) or 0)) for r in trend]
    mx = max(vals) or 1
    bars = ""
    for r, v in zip(trend, vals):
        h = 6 + int(46 * v / mx)
        last = " bar-last" if r is trend[-1] else ""
        bars += (f'<div class="bar-col"><div class="bar{last}" style="height:{h}px" '
                 f'title="{r.get("date")}: {money(v)}"></div>'
                 f'<div class="bar-x">{str(r.get("date",""))[-5:]}</div></div>')
    return f'<div class="trend">{bars}</div>'


def render_sources(sources, best):
    rows = ""
    for s in sources:
        roas = s.get("roas")
        rt = f'{roas:.2f}x' if roas else '<span class="muted">—</span>'
        star = " 🏆" if s.get("source") == best else ""
        rows += (f'<tr><td class="src-name">{s.get("source")}{star}</td>'
                 f'<td class="num">{money(s.get("revenue"))}</td>'
                 f'<td class="num">{s.get("purchases","—")}</td>'
                 f'<td class="num">{s.get("share",0):.0f}%</td>'
                 f'<td class="num">{rt}</td></tr>')
    return (f'<table class="tbl"><thead><tr><th>Source</th><th class="num">Revenue</th>'
            f'<th class="num">Purch</th><th class="num">Share</th><th class="num">ROAS</th>'
            f'</tr></thead><tbody>{rows}</tbody></table>')


def render_campaigns(rows):
    trs = ""
    for r in rows:
        st = r.get("status", "")
        rcls = {"fail": "row-fail", "warn": "row-warn"}.get(st, "")
        cpa = r.get("cpa")
        freq = r.get("frequency")
        flag = ""
        if cpa and r.get("cpa_ceiling") and cpa > r["cpa_ceiling"]:
            flag += ' <span class="mini-flag">CPA↑</span>'
        if freq and freq >= 2.5:
            flag += ' <span class="mini-flag">fatigue</span>'
        trs += (f'<tr class="{rcls}"><td>{r.get("name")}{flag}</td>'
                f'<td class="num">{money(r.get("spend"))}</td>'
                f'<td class="num">{r.get("conversions","—")}</td>'
                f'<td class="num">{f"{cpa:.0f}" if cpa else "—"}</td>'
                f'<td class="num">{f"{freq:.2f}" if freq else "—"}</td>'
                f'<td class="num">{r.get("ctr","—")}%</td>'
                f'<td class="num">{delta_html(r.get("spend"), r.get("spend_7d"))}</td></tr>')
    return (f'<table class="tbl"><thead><tr><th>Campaign</th><th class="num">Spend</th>'
            f'<th class="num">Conv</th><th class="num">CPA</th><th class="num">Freq</th>'
            f'<th class="num">CTR</th><th class="num">Spend·7d</th></tr></thead>'
            f'<tbody>{trs}</tbody></table>')


def render_creatives(creatives, pending=None):
    if pending:
        return (f'<div class="sub-label">Creatives</div>'
                f'<div class="plat-none">⏳ {pending}</div>')
    if not creatives:
        return ""
    cards = ""
    for c in creatives:
        freq = c.get("frequency")
        fatigue = ' <span class="mini-flag">fatigue</span>' if freq and freq >= 2.5 else ""
        thumb = c.get("thumb")
        img = (f'<img src="{thumb}" class="thumb"/>' if thumb
               else '<div class="thumb thumb-blank">no preview</div>')
        cards += (f'<div class="cr-card">{img}'
                  f'<div class="cr-name">{c.get("name")}{fatigue}</div>'
                  f'<div class="cr-meta">CTR {c.get("ctr","—")}% · freq {f"{freq:.2f}" if freq else "—"} · '
                  f'CPM {c.get("cpm","—")} · {money(c.get("spend"))} SAR</div></div>')
    return f'<div class="sub-label">Creatives — last 7d</div><div class="cr-grid">{cards}</div>'


def render_lenses(lenses):
    if not lenses:
        return ""
    cards = ""
    for ln in lenses:
        pts = "".join(f"<li>{p}</li>" for p in ln.get("points", []))
        cards += f'<div class="lens"><div class="lens-t">{ln.get("title")}</div><ul>{pts}</ul></div>'
    return f'<div class="lens-grid">{cards}</div>'


def render_chips(chips):
    out = ""
    for c in chips:
        out += (f'<div class="chip {c.get("cls","")}"><div class="chip-l">{c["label"]}</div>'
                f'<div class="chip-v">{c["value"]}</div>'
                f'<div class="chip-d">{c.get("sub","")}</div></div>')
    return f'<div class="chip-row">{out}</div>'


def render_platform(p):
    kind = p.get("kind")
    head = f'<div class="plat-head">{p.get("label")}</div>'
    if kind == "none":
        return f'<div class="platform">{head}<div class="plat-none">{p.get("message","")}</div></div>'
    if kind == "salla":
        k = p.get("kpis", {})
        rev, o, aov = k.get("revenue", {}), k.get("orders", {}), k.get("aov", {})
        notes = "".join(f"<li>{n}</li>" for n in p.get("notes", []))
        notes_b = f'<div class="notes"><b>Data quality:</b><ul>{notes}</ul></div>' if notes else ""
        return f"""<div class="platform platform-salla">{head}
          <div class="kpi-row">
            {kpi("Revenue", rev.get('today'), rev.get('yesterday'), rev.get('d3'), rev.get('d7'))}
            {kpi("Orders", o.get('today'), o.get('yesterday'), o.get('d3'), o.get('d7'), unit="")}
            {kpi("AOV", aov.get('today'), aov.get('yesterday'), aov.get('d3'), aov.get('d7'))}
          </div>
          <div class="sub-label">Source attribution — who drove the sales</div>
          {render_sources(p.get('sources', []), p.get('best_source'))}
          <div class="sub-label">8-day revenue trend</div>
          {render_trend(p.get('trend', []))}
          {notes_b}
          {render_lenses(p.get('lenses'))}
        </div>"""
    # ads platform (meta / tiktok)
    ch = p.get("chips", [])
    camps = p.get("campaigns", [])
    camp_b = render_campaigns(camps) if camps else '<div class="plat-none">No active campaigns with spend today.</div>'
    return f"""<div class="platform">{head}
      {render_chips(ch)}
      <div class="sub-label">Campaigns — today</div>
      {camp_b}
      {render_creatives(p.get('creatives'), p.get('creatives_pending'))}
      {render_lenses(p.get('lenses'))}
    </div>"""


def render_client(c):
    dec = c.get("decision", {})
    dcls = {"high": "dec-high", "med": "dec-med", "low": "dec-low"}.get(dec.get("priority"), "dec-med")
    tt = c.get("totals", {})
    rev, sp, mer, o = tt.get("revenue", {}), tt.get("spend", {}), tt.get("mer", {}), tt.get("orders", {})
    plats = "".join(render_platform(p) for p in c.get("platforms", []))
    grs = ""
    for g in c.get("guardrails", []):
        st = g.get("status", "na")
        icon = {"fail": "🔴", "warn": "🟡", "ok": "🟢"}.get(st, "⚪")
        gc = {"fail": "gr-fail", "warn": "gr-warn", "ok": "gr-ok"}.get(st, "")
        grs += (f'<div class="gr-item {gc}"><span>{icon}</span><div>'
                f'<div class="gr-name">{g.get("name")}</div>'
                f'<div class="gr-detail">{g.get("detail","")}</div></div></div>')
    return f"""
    <section class="client">
      <div class="client-head"><h2>{c.get('name')}</h2>
        <span class="pill">{c.get('settlement','').upper()}</span></div>
      <div class="decision {dcls}">
        <div class="dec-tag">🎯 TODAY'S DECISION</div>
        <div class="dec-title">{dec.get('title','')}</div>
        <div class="dec-detail">{dec.get('detail','')}</div>
      </div>
      <div class="sub-label sub-strong">Client totals (blended, all platforms)</div>
      <div class="kpi-row">
        {kpi("Revenue", rev.get('today'), rev.get('yesterday'), rev.get('d3'), rev.get('d7'))}
        {kpi("Ad spend", sp.get('today'), sp.get('yesterday'), sp.get('d3'), sp.get('d7'), hib=False)}
        {kpi("Blended MER", mer.get('today'), mer.get('yesterday'), mer.get('d3'), mer.get('d7'), unit="x")}
        {kpi("Orders", o.get('today'), o.get('yesterday'), o.get('d3'), o.get('d7'), unit="")}
      </div>
      <div class="layers">{plats}</div>
      <div class="sub-label">Guardrails</div>
      <div class="gr-grid">{grs}</div>
    </section>"""


def render_overview(data):
    p = data.get("portfolio", {})
    minis = ""
    for c in data.get("clients", []):
        tt = c.get("totals", {})
        mer = tt.get("mer", {}).get("today")
        dec = c.get("decision", {})
        dot = {"high": "#dc2626", "med": "#d97706", "low": "#16a34a"}.get(dec.get("priority"), "#6b7280")
        merc = f'{mer:.2f}x' if mer else '<span class="muted">COD pending</span>'
        minis += (f'<div class="mini"><span class="dot" style="background:{dot}"></span>'
                  f'<div class="mini-name">{c.get("name")}</div>'
                  f'<div class="mini-mer">MER {merc}</div>'
                  f'<div class="mini-rev">{money(tt.get("revenue",{}).get("today"))} SAR · '
                  f'spend {money(tt.get("spend",{}).get("today"))}</div>'
                  f'<div class="mini-dec">{dec.get("title","")}</div></div>')
    alerts = "".join(f"<li>{a}</li>" for a in p.get("alerts", []))
    alert_b = f'<div class="alerts"><b>⚠️ Portfolio alerts</b><ul>{alerts}</ul></div>' if alerts else ""
    return f"""
    <section class="overview">
      <div class="ov-row">
        <div class="ov-stat"><div class="ov-l">Total ad spend</div><div class="ov-v">{money(p.get('total_spend'))}<span> SAR</span></div></div>
        <div class="ov-stat"><div class="ov-l">Total revenue (Salla)</div><div class="ov-v">{money(p.get('total_revenue'))}<span> SAR</span></div></div>
        <div class="ov-stat"><div class="ov-l">Portfolio MER</div><div class="ov-v">{p.get('blended_mer','—')}<span>x</span></div></div>
        <div class="ov-stat"><div class="ov-l">Orders</div><div class="ov-v">{p.get('total_orders','—')}</div></div>
      </div>
      <div class="mini-row">{minis}</div>
      {alert_b}
    </section>"""


CSS = """
:root{--ink:#111827;--ink3:#6b7280;--bg:#f3f4f6;--surface:#fff;--border:#e5e7eb;
--green:#16a34a;--amber:#d97706;--red:#dc2626;--blue:#2563eb}
*{box-sizing:border-box;margin:0;padding:0}
body{font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;background:var(--bg);color:var(--ink);font-size:13px;line-height:1.5;padding-bottom:40px}
.header{background:#0f172a;color:#fff;padding:18px 32px;display:flex;justify-content:space-between;align-items:center;flex-wrap:wrap;gap:8px}
.header h1{font-size:18px}.header .sub{font-size:11px;color:#94a3b8;margin-top:2px}
.pills{display:flex;gap:6px}.pill{background:#e5e7eb;color:#374151;font-size:10px;font-weight:600;padding:3px 8px;border-radius:10px;letter-spacing:.03em}
.header .pill{background:#1e293b;color:#cbd5e1}
.page{max-width:1040px;margin:0 auto;padding:0 20px}
.overview{background:#0f172a;color:#e5e7eb;border-radius:12px;padding:18px 20px;margin-top:20px}
.ov-row{display:flex;gap:24px;flex-wrap:wrap;border-bottom:1px solid #1e293b;padding-bottom:12px}
.ov-l{font-size:10.5px;color:#94a3b8;text-transform:uppercase;letter-spacing:.04em}
.ov-v{font-size:22px;font-weight:700;color:#fff}.ov-v span{font-size:12px;font-weight:400;color:#94a3b8}
.mini-row{display:flex;gap:12px;flex-wrap:wrap;margin-top:14px}
.mini{flex:1;min-width:260px;background:#1e293b;border-radius:9px;padding:12px;position:relative}
.dot{width:8px;height:8px;border-radius:50%;display:inline-block;position:absolute;top:14px;right:12px}
.mini-name{font-size:14px;font-weight:700;color:#fff}
.mini-mer{font-size:12px;color:#cbd5e1;margin:1px 0}.mini-rev{font-size:11px;color:#94a3b8}
.mini-dec{font-size:11.5px;color:#e5e7eb;margin-top:6px;border-top:1px solid #334155;padding-top:6px}
.alerts{margin-top:12px;background:#7f1d1d33;border:1px solid #b91c1c55;border-radius:8px;padding:8px 12px;font-size:12px;color:#fecaca}
.alerts ul{margin:4px 0 0 18px}
.client{background:var(--surface);border:1px solid var(--border);border-radius:12px;padding:22px;margin-top:18px}
.client-head{display:flex;align-items:center;gap:10px;margin-bottom:12px}.client-head h2{font-size:18px}
.decision{border-radius:10px;padding:14px 16px;margin-bottom:14px;border-left:4px solid var(--blue);background:#f8fafc}
.dec-high{border-left-color:var(--red);background:#fef2f2}.dec-med{border-left-color:var(--amber);background:#fffbeb}.dec-low{border-left-color:var(--green);background:#f0fdf4}
.dec-tag{font-size:10px;font-weight:700;letter-spacing:.08em;color:var(--ink3)}
.dec-title{font-size:15px;font-weight:700;margin:3px 0 4px}.dec-detail{font-size:12.5px;color:var(--ink3)}
.sub-label{font-size:11px;font-weight:700;text-transform:uppercase;letter-spacing:.04em;color:var(--ink3);margin:14px 0 8px}
.sub-strong{color:var(--ink);border-bottom:1px solid var(--border);padding-bottom:5px}
.kpi-row{display:flex;gap:10px;flex-wrap:wrap}
.kpi{flex:1;min-width:150px;border:1px solid var(--border);border-radius:8px;padding:10px 12px}
.kpi-label{font-size:11px;color:var(--ink3)}.kpi-value{font-size:22px;font-weight:700;margin:2px 0}
.kpi-unit{font-size:11px;font-weight:400;color:var(--ink3);margin-left:3px}
.kpi-deltas{display:flex;gap:9px;flex-wrap:wrap;font-size:10px;color:var(--ink3)}
.delta{font-weight:700}.delta-up{color:var(--green)}.delta-down{color:var(--red)}.delta-na{color:var(--ink3)}
.layers{margin-top:6px}
.platform{border:1px solid var(--border);border-left:3px solid #cbd5e1;border-radius:8px;padding:14px;margin-top:10px;background:#fcfcfd}
.platform-salla{border-left-color:#0f766e}
.plat-head{font-size:13px;font-weight:700;margin-bottom:8px}
.plat-none{font-size:12px;color:var(--ink3);font-style:italic;padding:4px 0}
.chip-row{display:flex;gap:10px;flex-wrap:wrap}
.chip{flex:1;min-width:120px;border:1px solid var(--border);border-radius:7px;padding:8px 10px;background:#fff}
.chip-l{font-size:10px;color:var(--ink3);text-transform:uppercase;letter-spacing:.03em}
.chip-v{font-size:18px;font-weight:700}.chip-d{font-size:10px;color:var(--ink3)}
.chip-ok{background:#f0fdf4;border-color:#bbf7d0}.chip-warn{background:#fffbeb;border-color:#fde68a}.chip-fail{background:#fef2f2;border-color:#fecaca}
.tbl{width:100%;border-collapse:collapse;font-size:12px;margin-top:4px}
.tbl th,.tbl td{text-align:left;padding:6px 9px;border-bottom:1px solid var(--border)}
.tbl th{font-size:10px;text-transform:uppercase;letter-spacing:.03em;color:var(--ink3)}
.num{text-align:right;font-variant-numeric:tabular-nums}.src-name{font-weight:600;text-transform:capitalize}
.muted{color:var(--ink3);font-style:italic}
.row-fail td{background:#fef2f2}.row-warn td{background:#fffbeb}
.mini-flag{font-size:9px;font-weight:700;color:var(--red);background:#fee2e2;padding:1px 5px;border-radius:4px;margin-left:4px}
.trend{display:flex;align-items:flex-end;gap:7px;height:70px;padding-top:6px}
.bar-col{display:flex;flex-direction:column;align-items:center;gap:3px;flex:1}
.bar{width:70%;background:#cbd5e1;border-radius:3px 3px 0 0}.bar-last{background:var(--blue)}
.bar-x{font-size:9px;color:var(--ink3)}
.notes{font-size:11.5px;color:var(--ink3);margin-top:10px;background:#f8fafc;border:1px solid var(--border);border-radius:6px;padding:8px 10px}
.notes ul{margin:3px 0 0 16px}
.lens-grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(220px,1fr));gap:8px;margin-top:10px}
.lens{border:1px solid var(--border);border-radius:7px;padding:8px 10px;background:#fff}
.lens-t{font-size:10.5px;font-weight:700;text-transform:uppercase;letter-spacing:.04em;color:var(--blue)}
.lens ul{margin:4px 0 0 15px;font-size:11.5px;color:var(--ink3)}.lens li{margin:2px 0}
.gr-grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(220px,1fr));gap:8px}
.gr-item{display:flex;gap:8px;border:1px solid var(--border);border-radius:8px;padding:8px 10px}
.gr-fail{background:#fef2f2;border-color:#fecaca}.gr-warn{background:#fffbeb;border-color:#fde68a}.gr-ok{background:#f0fdf4;border-color:#bbf7d0}
.gr-name{font-size:12px;font-weight:600}.gr-detail{font-size:11px;color:var(--ink3)}
.cr-grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(155px,1fr));gap:10px;margin-top:4px}
.cr-card{border:1px solid var(--border);border-radius:8px;overflow:hidden;background:#fff}
.thumb{width:100%;height:100px;object-fit:cover;display:block}
.thumb-blank{display:flex;align-items:center;justify-content:center;height:100px;background:#f3f4f6;color:#9ca3af;font-size:11px}
.cr-name{font-size:11px;font-weight:600;padding:6px 8px 2px;word-break:break-word}
.cr-meta{font-size:10px;color:var(--ink3);padding:0 8px 8px}
.foot{max-width:1040px;margin:16px auto 0;padding:0 20px;font-size:11px;color:var(--ink3)}
"""


def build_html(data):
    clients = "".join(render_client(c) for c in data.get("clients", []))
    return f"""<!DOCTYPE html><html lang="en"><head><meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Daily Brief — {data.get('date','')}</title><style>{CSS}</style></head>
<body>
  <div class="header">
    <div><h1>Daily Brief</h1><div class="sub">{data.get('date','')} · generated {data.get('generated','')}</div></div>
    <div class="pills"><span class="pill">{len(data.get('clients',[]))} clients</span>
      <span class="pill">cycle: {data.get('cycle_phase','')}</span>
      <span class="pill">backfill last {data.get('backfill_window',4)}d</span></div>
  </div>
  <div class="page">
    {render_overview(data)}
    {clients}
  </div>
  <div class="foot">Truth = Salla revenue (numerator). Platform numbers are diagnostic; Blended MER governs budget.
  Monitor-only — no platform actions taken. {data.get('footer','')}</div>
</body></html>"""


# ── email (inline styles; Gmail strips <head>/<style>) ───────
def build_email_html(data):
    def dl(cur, ref, hib=True):
        p = pct(cur, ref)
        if p is None:
            return '<span style="color:#6b7280">—</span>'
        col = "#16a34a" if (p >= 0) == hib else "#dc2626"
        return f'<span style="color:{col};font-weight:700">{"▲" if p>=0 else "▼"} {abs(p):.0f}%</span>'
    blocks = ""
    for c in data.get("clients", []):
        dec = c.get("decision", {})
        bar = {"high": "#dc2626", "med": "#d97706", "low": "#16a34a"}.get(dec.get("priority"), "#2563eb")
        tt = c.get("totals", {}); rev = tt.get("revenue", {}); mer = tt.get("mer", {})
        platlines = ""
        for p in c.get("platforms", []):
            if p.get("kind") == "salla":
                continue
            if p.get("kind") == "none":
                platlines += f'<div style="font-size:12px;color:#6b7280">• {p.get("label")}: {p.get("message","")}</div>'
                continue
            chips = {ch["label"]: ch["value"] for ch in p.get("chips", [])}
            platlines += (f'<div style="font-size:12px;margin:2px 0">• <b>{p.get("label")}</b>: '
                          f'spend {chips.get("Spend","—")} · rev {chips.get("Revenue","—")} · '
                          f'ROAS {chips.get("ROAS","—")} · CPA {chips.get("CPA","—")}</div>')
        blocks += f"""
        <div style="border:1px solid #e5e7eb;border-radius:10px;padding:16px;margin:14px 0">
          <div style="font-size:16px;font-weight:700">{c.get('name')} <span style="font-size:10px;background:#e5e7eb;color:#374151;padding:2px 7px;border-radius:8px">{c.get('settlement','').upper()}</span>
            &nbsp; <span style="font-size:12px;color:#374151">MER {mer.get('today','—')}x · Rev {money(rev.get('today'))} SAR {dl(rev.get('today'),rev.get('yesterday'))}</span></div>
          <div style="border-left:4px solid {bar};background:#f8fafc;border-radius:8px;padding:10px 12px;margin:10px 0">
            <div style="font-size:10px;font-weight:700;letter-spacing:.06em;color:#6b7280">🎯 TODAY'S DECISION</div>
            <div style="font-size:14px;font-weight:700;margin:2px 0">{dec.get('title','')}</div>
            <div style="font-size:12px;color:#374151">{dec.get('detail','')}</div>
          </div>
          {platlines}
        </div>"""
    p = data.get("portfolio", {})
    return f"""<div style="font-family:-apple-system,Segoe UI,sans-serif;max-width:680px;margin:0 auto;color:#111827">
      <div style="background:#0f172a;color:#fff;padding:14px 18px;border-radius:10px">
        <div style="font-size:17px;font-weight:700">Daily Brief — {data.get('date','')}</div>
        <div style="font-size:11px;color:#94a3b8">cycle: {data.get('cycle_phase','')} · spend {money(p.get('total_spend'))} · rev {money(p.get('total_revenue'))} SAR · portfolio MER {p.get('blended_mer','—')}x · monitor-only</div>
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
