#!/bin/bash
# sync.sh — اسحب + ارفع كل التغييرات بأمر واحد
# الاستخدام: ./sync.sh "وصف اختياري"

set -e

REPO="/Users/talal/Desktop/ads-ops"
cd "$REPO"

MSG="${1:-تحديث $(date '+%Y-%m-%d %H:%M')}"

echo "⬇️  pull ..."
git pull --rebase

echo "📦 staging ..."
git add \
  .gitignore \
  CLAUDE.md \
  clients/ \
  tools/ \
  faza3/ \
  2>/dev/null || true

# استثنِ الملفات الكبيرة/البينرية تلقائياً (DB + obsidian + DS_Store)
git reset HEAD -- '*.db' '*.sqlite' '.obsidian/' 2>/dev/null || true

STAGED=$(git diff --cached --name-only)
if [ -z "$STAGED" ]; then
  echo "✅ لا يوجد تغييرات جديدة."
  exit 0
fi

echo "📝 commit: $MSG"
git commit -m "$MSG"

echo "⬆️  push ..."
git push

echo "✅ تم. GitHub محدّث."
