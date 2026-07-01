# daily-check — Scheduling & Email delivery

How to run `daily-check` automatically every morning while you travel, and get the
report by email. **Read this before relying on the schedule** — there are two real
platform limits.

## ⚠️ Two limits to know

1. **In-session `CronCreate` is ephemeral.** A cron created inside a Claude session
   is *session-only* here (dies when the container is reclaimed; auto-expires in 7
   days). It is a stopgap, **not** a reliable daily runner while you're away.
   → For guaranteed daily runs, create a **Scheduled Session** in the Claude Code
   **web dashboard** (see below).
2. **Gmail MCP can only create drafts, not send.** So "auto-arrive in inbox" is not
   available through Gmail MCP. Options: a daily **draft** (zero setup, you open
   Gmail) or true **SMTP auto-send** (needs a Gmail App Password stored as a secret).

## A) Recommended: web-dashboard Scheduled Session

In the Claude Code web dashboard for this repo, create a scheduled session:

- **Schedule (cron, KSA):** `3 9 * * *` — daily ~09:03. If the dashboard runs in
  **UTC**, use `3 6 * * *` (09:03 KSA = 06:03 UTC). Verify the timezone in the UI.
- **Why 9am:** yesterday's TikTok/Meta spend has settled (don't run before ~7am);
  the 4-day backfill cleans late COD revenue on later runs.
- **Prompt to paste:**

> Run the daily-check skill for both clients (Noura, Raghad/Zain). Read each
> client's profile/benchmarks/last decisions; determine the payroll cycle phase;
> pull Salla sales_summary + traffic_sources + sales-per-day (last 4 days for
> backfill) and TikTok campaign spend via InsightfulPipe MCP (advertisers
> 7401593626448363521 Noura / 7494645342479319056 Raghad; also Meta for Raghad if
> facebook-ads is connected). Compute Blended/channel + per-source ROAS,
> CPA/frequency/CTR per campaign, and 1d/3d/7d deltas; apply COD handling for Noura
> (judge on orders until settled). Write reports/<today>/data.json, render
> reports/<today>/daily-brief.html and the --email version via
> tools/render_report.py, commit+push, then create a Gmail draft of the email
> version to t.aljh98@gmail.com. Monitor-only — no ad-platform writes.

### Environment requirements for the scheduled run

- **Secret:** `INSIGHTFULPIPE_TOKEN` = your `ip_sk_...` key (env secret in the
  environment config — do not paste it in prompts).
- **MCP availability:** the scheduled/headless run must have the **InsightfulPipe**
  and **Salla** MCP servers connected. Interactively-authenticated MCPs may be
  absent in headless runs — verify after the first scheduled run.
- **Network egress:** MCP traffic is fine. Only the `insightfulpipe` *CLI* needs
  `app.insightfulpipe.com` on the egress allowlist (the MCP does not).

## B) Email delivery — SMTP auto-send (chosen)

Real auto-send is wired via `tools/send_email.py` (Gmail SMTP). One-time setup:

1. Google Account → **Security → App passwords** → create one for "Mail". You get a
   16-char password (needs 2-Step Verification enabled).
2. Store two **env secrets** in the environment config (do NOT paste in prompts):
   - `GMAIL_ADDRESS` = `t.aljh98@gmail.com`
   - `GMAIL_APP_PASSWORD` = the 16-char app password
3. The daily run then sends automatically:

   ```
   python3 tools/render_report.py reports/<date>/data.json \
       reports/<date>/daily-brief.html --email reports/<date>/daily-brief-email.html
   python3 tools/send_email.py reports/<date>/daily-brief-email.html \
       --subject "Daily Brief — <date>"        # --to defaults to GMAIL_ADDRESS
   ```

Test without sending: add `--dry-run`. Exit codes: 0 ok · 2 missing creds · 3 send error.

> Update the scheduled-session prompt's final step to: *"…then send the email version
> via `python3 tools/send_email.py <email_html> --subject 'Daily Brief — <today>'`."*
> (replaces the Gmail-draft step). A daily Gmail **draft** remains available as a
> fallback via `mcp__Gmail__create_draft` if SMTP creds are ever missing.

- **Alternative:** Slack delivery can auto-send (Slack MCP) if you prefer a DM.

## C) Local fallback (your own machine)

`tools/run_daily.sh` runs the check headless via `claude -p` and can push a Telegram
message. It requires your machine to be on — not suitable while traveling, but fine
as a backup. (Its old Windsor tool list is superseded by InsightfulPipe.)

## Output locations

- Full visual dashboard: `reports/<date>/daily-brief.html`
- Structured data: `reports/<date>/data.json`
- Email HTML: generated on demand with `--email <path>`
