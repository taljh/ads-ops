---
name: daily-check
description: >
  Runs the operational DAILY CHECK for paid-social clients (Noura, Raghad/Zain):
  pulls Salla store truth + source attribution and ad-platform spend, reconciles
  Blended ROAS, applies the 4-day backfill for late data, computes 1d/3d/7d deltas,
  breaks performance down to campaign → ad group → ad → creative, and ends with the
  single most important decision for today. Emits an ENGLISH visual HTML dashboard.
  Monitor-only — never edits or pauses anything on the platforms. Use for "daily check",
  "الفحص اليومي", "شيك اليوم", "review the accounts today", or the scheduled morning run.
---

# Daily Check — operational monitor (monitor, don't touch)

**This is NOT `faza3/daily-improvement.md`.** That engine strengthens *the system itself*
(one self-improvement task/day). THIS skill is the **operational campaign monitor**: read the
accounts, surface signals and one decision, take **zero** platform actions. Keep them separate.

Golden rules (from `CLAUDE.md`): **Salla revenue is the numerator and always wins.** Platforms
are diagnostic. **Never invent numbers** — if a source is missing, say so. Always state the
**date range** and the **payroll-cycle phase** (peak 26→3 / maintenance 4→25).

## 1) Data sources — best-of-breed (no single source is cleanest for everything)

| Purpose | Source | Tool |
|---|---|---|
| Truth: revenue / orders / AOV | **Salla** `reports_sales_summary` | per store MCP |
| Which source drove sales | **Salla** `reports_traffic_sources` / `reports_traffic_campaigns` | per store MCP |
| Daily revenue trend (deltas) | **Salla** `reports_sales_breakdowns` (`sales-per-day`) | per store MCP |
| TikTok spend / performance / creative | **InsightfulPipe MCP** (live, both advertisers, to ad+creative) | `query_contexts` → `query_data` (action `report/integrated/get/`, `campaign/get/`, `ad/get/`) |
| Meta spend (Raghad only) | **InsightfulPipe MCP** once `facebook-ads` is connected | same flow, `platform="facebook-ads"` |

- **Primary ad source = InsightfulPipe MCP** (goes through the MCP channel, not blocked by network egress).
  Discover accounts with `query_contexts request=accounts`; workspace_id=3106, brand_id=3300.
  TikTok advertiser IDs: Noura `7401593626448363521`, Raghad/Zain `7494645342479319056`.
- ⚠️ **Meta is NOT connected yet** in InsightfulPipe (only `tiktok-ads` shows under sources). Until Raghad's
  `facebook-ads` account is connected, her FB/IG spend is missing → FB/IG ROAS and true blended MER are partial. Say so.
- ⚠️ TikTok returns `total_purchase_value = 0` (pixel value not passed) → **never** derive ROAS from TikTok;
  revenue comes from Salla. TikTok gives spend / conversions (`complete_payment`) / CPA / CTR / frequency.
- Fallbacks if InsightfulPipe is down: TikTok pipeboard (`get_tiktok_insights`, low daily quota) or Porter (bills).
- Client config (accounts, settlement type, guardrails, inflation) lives in `tools/daily_check.py` → `CLIENTS`.

## 2) The daily loop (per client)

1. **Read state:** `clients/<c>/profile.md`, `benchmarks.md`, last 5–10 `decisions.md`, `data/learnings.md`.
2. **Cycle phase:** compute peak (26→3) vs maintenance (4→25) from today. Every decision names the phase.
3. **Pull** (rolling window = today + last 4 days for backfill):
   - Salla: sales summary, traffic sources, sales-per-day.
   - TikTok (pipeboard): campaign insights; drill ad/creative for movers.
   - Meta (Porter): campaign insights for Raghad.
4. **Truth & Blended ROAS** = Salla revenue ÷ total ad spend (all platforms). Platform ROAS = diagnostic only.
5. **Per-source ROAS** = Salla revenue attributed to source ÷ that platform's spend → name the **best source** per client.
6. **Backfill / restatement** (see §3). **Triple delta** 1d/3d/7d (see §4).
7. **Guardrails** (the 7 from `CLAUDE.md`). Any breach → flag; if it implies an action, phrase as a spec, don't do it.
8. **Store** via `DailyCheck(<c>)` in `tools/daily_check.py` (SQLite; keyed by pull_date+report_date).
9. **Render** the English HTML (see §7) and **log** the decision to `decisions.md` if material.

## 3) Backfill — data that appears late

Platform conversions and **COD revenue** are not final same-day. Each run **re-pulls the last 4 days**
and compares to what was stored on earlier `pull_date`s (the SQLite PK is `pull_date + report_date`, so
restatements are first-class). Surface: *"Correction: 06-28 gained 3 late conversions → ROAS 5.1, not 4.2."*

**Per-client settlement (critical):**
- **Noura = COD** → `orders_count` leads; `sales_total` settles over 2–3 days. **Judge on orders until settled.**
  `sales_summary` (settled) will diverge from `traffic_sources` (placed) — that is expected, not an error.
- **Raghad/Zain = prepaid** → orders == paid sales same-day; numbers reconcile; no lag.

## 4) Triple delta — are we improving or dropping?

Every core metric (Blended ROAS, revenue, spend, CPA, CTR) shows **vs 1d / vs 3d / vs 7d** as **% + arrow**
(🟢↑ good / 🔴↓ bad). The 7-day compare is same-weekday (cancels day-of-week effects).

## 5) Hierarchy — campaign → ad group → ad → creative

Render every level with the triple delta. **Creatives** get a card grid: thumbnail
(`get_tiktok_video_info`/`image_info`) + CTR + frequency + spend, with a **🔴 fatigue** badge when
`frequency ≥ 2.5×` (creative-refresh guardrail). This is where creative decisions are made.

## 6) Today's decision

End each client with **one** ranked decision, tied to cycle phase + guardrails + monitor-only. Not a list —
the single most important thing to do (or explicitly "hold / re-check in N days" when data is not final).

## 7) Output — English visual HTML (not text)

Build the report with `tools/render_report.py` (design language from `tools/brief_template.html`;
color = signal only). Report language is **English** (renders cleanly, no RTL issues).

```
python3 tools/render_report.py <data.json> clients/<c>/data/reports/<date>.html
```

Present it **visually** (open/render the file), never as a wall of text. On the scheduled cloud run,
also write it under `clients/<c>/data/reports/` and commit; optionally push a Telegram/email link.

## 8) Guardrails for this skill

Monitor-only (no pause/edit/budget change on any platform) · every number cites its source + date ·
Salla revenue wins · clients stay fully separated (no cross-client numbers) · one report, both clients,
each in its own section.
