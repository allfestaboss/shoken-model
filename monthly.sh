#!/usr/bin/env bash
# 毎月の自動処理。launchd から呼ばれる（com.boss.shoken-food）。
#
#   1. 食品衛生の版を取る（中身が前の版と同じなら版を作らない）
#   2. 版が2つ以上あれば差分を取り、閉店を数える
#   3. 結果を data/food/REPORT.md に追記し、macOSの通知を出す
#
# このデータは上書き更新されるので、版を積まないと閉店が分からない。
# 取り逃すと二度と取れない（酒販免許は8〜12か月で消え、こちらは上書きされる）。
set -uo pipefail
cd "$(dirname "$0")"
PY=/usr/bin/python3
REPORT=data/food/REPORT.md
STAMP=$(date '+%Y-%m-%d %H:%M')

before=$(ls -d data/food/snapshots/*/ 2>/dev/null | wc -l | tr -d ' ')
$PY fetch_food.py
after=$(ls -d data/food/snapshots/*/ 2>/dev/null | wc -l | tr -d ' ')

{
  echo
  echo "## $STAMP"
} >> "$REPORT"

if [ "$after" -le "$before" ]; then
  echo "  版は増えなかった（公表がまだ更新されていない）"
  echo "版は増えなかった。手元の版 ${after} 個。" >> "$REPORT"
  exit 0
fi

echo "  版が ${before} -> ${after} に増えた。差分を取る"
OUT=$($PY diff_food.py 2>&1 | tail -12)
echo "$OUT"
{
  echo "版が ${before} → ${after} に増えた。"
  echo '```'
  echo "$OUT"
  echo '```'
} >> "$REPORT"

# 気づけるようにする。閉店データはこの企画の最後の未解決なので、
# 貯まったことに気づかないと意味がない
N=$(echo "$OUT" | grep -oE '飲食で座標のあるもの [0-9,]+' | head -1)
osascript -e "display notification \"${N:-差分を取りました}\" with title \"商圏モデル: 閉店データが貯まりました\"" 2>/dev/null || true
