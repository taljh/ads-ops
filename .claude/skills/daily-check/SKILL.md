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
| Meta spend / creative (Raghad only) | **Meta MCP** (live) | `ads_get_ad_entities` (account `1686054965972322`, level campaign/adset/ad, `time_increment=1`) |

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

## 4b) Report architecture — one wide view, platform-nested

The report is a **single page** built for an away-from-desk operator:
1. **Portfolio bird's-eye** (top): total ad spend, total Salla revenue, portfolio MER,
   per-client mini-cards (MER + decision), and cross-client **alerts**.
2. **Per client**, in order: Today's Decision → **Client totals (blended)** → then one
   **layer per platform**: 🛒 Salla (truth) → 📘 Meta → 🎵 TikTok → Guardrails.
   Each platform is shown **separately** (its own spend/ROAS/CPA/campaigns) AND rolled
   into the client blended total — so you get both the wide overview and the detail.
   A platform the client doesn't run renders as an explicit "not running" note.

## 4c) Analysis lenses — bake in the prompt library

Every ads platform layer carries short **analysis lenses** distilled from
`insightfulpipe_prompts.md` (the 10-prompt InsightfulPipe library, saved in this
folder). Apply the matching lenses per platform, each as 1–2 evidence-based bullets:

- **Meta:** Performance (#1) · Audience (#2) · Creative (#3) · Budget (#4) · Weekly (#5)
- **TikTok:** Performance (#6) · Targeting (#7) · Creative (#8) · Weekly (#9) · Health (#10)
- **Salla:** Performance + Attribution (store-truth lenses).

Lenses **summarize**, they don't replace the tables — pull the real numbers first,
then let the lens say what to do. This is pure enhancement; nothing already built changes.

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
python3 tools/render_report.py reports/<date>/data.json reports/<date>/daily-brief.html \
    --email reports/<date>/daily-brief-email.html
python3 tools/send_email.py reports/<date>/daily-brief-email.html --subject "Daily Brief — <date>"
```

Present it **visually** (open/render the file), never as a wall of text. On the scheduled cloud run,
commit the report and **email it via `tools/send_email.py`** (Gmail SMTP; needs `GMAIL_ADDRESS` +
`GMAIL_APP_PASSWORD` secrets — see `SCHEDULING.md`). Fallback: `mcp__Gmail__create_draft`. Never paste
the app password into a prompt.

## 8) Guardrails for this skill

Monitor-only (no pause/edit/budget change on any platform) · every number cites its source + date ·
Salla revenue wins · clients stay fully separated (no cross-client numbers) · one report, both clients,
each in its own section.
