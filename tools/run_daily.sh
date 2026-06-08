#!/bin/bash
# run_daily.sh — تشغيل الفحص اليومي التلقائي لكل العملاء
# الاستخدام: ./tools/run_daily.sh          (كل العملاء)
#            ./tools/run_daily.sh noura     (عميل محدد)
# cron: 0 8 * * * cd /Users/talal/Desktop/ads-ops && ./tools/run_daily.sh

set -euo pipefail

# --- الإعدادات ---
PROJECT_DIR="/Users/talal/Desktop/ads-ops"
TODAY=$(date +%Y-%m-%d)
LOG_FILE="$PROJECT_DIR/clients/last_run.log"

# تلقرام (اتركها فاضية لو ما تبغى إشعارات)
TELEGRAM_BOT_TOKEN=""
TELEGRAM_CHAT_ID=""

# --- العملاء ---
CLIENTS=("noura" "zain")
MCP_TOOLS="mcp__claude_ai_Windsor_ai__get_data,mcp__claude_ai_Windsor_ai__get_connectors,mcp__claude_ai_Windsor_ai__get_options,mcp__claude_ai_Windsor_ai__get_fields,mcp__claude_ai_Salla_-_Noura_Abayas__reports_traffic_campaigns,mcp__claude_ai_Salla_-_Noura_Abayas__reports_sales_summary,mcp__claude_ai_Salla_-_Noura_Abayas__reports_sales_monthly,mcp__claude_ai_Salla_-_Noura_Abayas__store_dashboard_card,Bash,Read,Write,Edit,Glob,Grep"

# لو مرّر عميل محدد
if [[ $# -gt 0 ]]; then
  CLIENTS=("$@")
fi

# --- التنفيذ ---
cd "$PROJECT_DIR"
echo "[$TODAY $(date +%H:%M)] بدء الفحص اليومي..." > "$LOG_FILE"

for CLIENT in "${CLIENTS[@]}"; do
  REPORTS_DIR="$PROJECT_DIR/clients/$CLIENT/data/reports"
  REPORT_FILE="$REPORTS_DIR/$TODAY.md"
  mkdir -p "$REPORTS_DIR"

  echo "[$TODAY $(date +%H:%M)] فحص $CLIENT..." >> "$LOG_FILE"

  PROMPT="أنت تشتغل بوضع الفحص اليومي التلقائي. نفّذ الفحص اليومي لعميل $CLIENT:
1. اقرأ clients/$CLIENT/profile.md و clients/$CLIENT/benchmarks.md
2. اقرأ memory/discoveries.md و clients/$CLIENT/data/learnings.md (لو موجود) — تعلّم من اكتشافات سابقة
3. اسحب بيانات أمس واليوم من Windsor على مستوى campaign + adgroup + ad (كل المنصات الخاصة بالعميل)
4. اسحب بيانات سلة إذا متاحة (reports_traffic_campaigns + reports_sales_summary)
5. خزّن الكل في SQLite عبر DailyCheck('$CLIENT')
6. اطلع التقرير الكامل checker.report()
7. شغّل checker.learnings_report() واعرض الاكتشافات
8. شغّل checker.export_learnings_md() لحفظ الاكتشافات تراكمياً
9. لا تسأل أسئلة — نفّذ مباشرة وأعطيني التقرير + الاكتشافات فقط"

  claude -p "$PROMPT" \
    --allowedTools "$MCP_TOOLS" \
    2>>"$LOG_FILE" \
    > "$REPORT_FILE"

  echo "[$TODAY $(date +%H:%M)] $CLIENT محفوظ: $REPORT_FILE" >> "$LOG_FILE"

  # --- إرسال تلقرام ---
  if [[ -n "$TELEGRAM_BOT_TOKEN" && -n "$TELEGRAM_CHAT_ID" ]]; then
    SUMMARY=$(head -c 3900 "$REPORT_FILE")
    curl -s -X POST "https://api.telegram.org/bot${TELEGRAM_BOT_TOKEN}/sendMessage" \
      -d chat_id="$TELEGRAM_CHAT_ID" \
      -d parse_mode="Markdown" \
      --data-urlencode "text=*$CLIENT — $TODAY*

$SUMMARY" \
      >> "$LOG_FILE" 2>&1
  fi
done

echo "[$TODAY $(date +%H:%M)] انتهى الفحص لـ ${CLIENTS[*]}." >> "$LOG_FILE"
