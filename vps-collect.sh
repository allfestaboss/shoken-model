#!/usr/bin/env bash
# VPS側の毎月の収集。cron から呼ばれる。
#
# Macのlaunchdだと**Macが落ちている間は発火しない**。酒販免許は国税局によって
# 8か月（大阪）〜9か月（金沢）しか残らず、食品衛生は上書き更新されるので、
# 取り逃すと二度と取れない。常時稼働のVPSに置き換える。
#
#   1. 食品衛生の版を取る（中身が前の版と同じなら版を作らない）
#   2. 酒販免許のPDFを取る（直近4か月ぶん。既にあるものは飛ばす）
#   3. 版が増えたら差分を取って閉店を数える
#   4. REPORT.md に追記。Discordの口があれば通知する
set -uo pipefail
cd /root/apps/shoken-collect
PY=/usr/bin/python3
REPORT=data/food/REPORT.md
STAMP=$(date '+%Y-%m-%d %H:%M')
# set -a を挟まないと、source しただけではシェル変数どまりで
# Python の os.environ に渡らない（KeyError で落ちる）
set -a; [ -f .env ] && . ./.env; set +a

before=$(ls -d data/food/snapshots/*/ 2>/dev/null | wc -l | tr -d ' ')
$PY fetch_food.py
$PY fetch_licenses.py
after=$(ls -d data/food/snapshots/*/ 2>/dev/null | wc -l | tr -d ' ')
pdfs=$(ls data/nta/*.pdf 2>/dev/null | wc -l | tr -d ' ')

# 送り先の変数名と見た目は、既にVPSで動いている news-digest / quake-watch に合わせる
#   変数名  DISCORD_WEBHOOK_URL（無ければ DISCORD_WEBHOOK）
#   見た目  embeds（title / description / color / footer）
notify() {
  local hook="${DISCORD_WEBHOOK_URL:-${DISCORD_WEBHOOK:-}}"
  [ -n "$hook" ] || return 0
  WEBHOOK="$hook" $PY - "$1" "$2" <<'PYEOF'
import json, os, sys, urllib.request
body = json.dumps({"embeds": [{
    "title": sys.argv[1],
    "description": sys.argv[2][:4000],
    "color": 0x1F5C55,
    "footer": {"text": "商圏モデル / shoken-model・VPSの定期収集"},
}]}).encode()
req = urllib.request.Request(
    os.environ["WEBHOOK"], data=body,
    # Discord(Cloudflare)は名乗らない urllib を 403 code 1010 で弾く。
    # curl は通るのに urllib だけ落ちるときはこれ。VPSの news-digest にも同じ注記がある
    headers={"Content-Type": "application/json",
             "User-Agent": "shoken-model (+https://shoken.monosashi.work, 1.0)"})
try:
    urllib.request.urlopen(req, timeout=20)
except Exception as e:
    print(f"  通知できず {type(e).__name__}: {e}")
PYEOF
}

{ echo; echo "## $STAMP （VPS）"; } >> "$REPORT"

if [ "$after" -le "$before" ]; then
  echo "  版は増えなかった。酒販免許PDF ${pdfs}本"
  echo "版は増えなかった。手元の版 ${after} 個 / 酒販免許PDF ${pdfs}本。" >> "$REPORT"
  exit 0
fi

echo "  版が ${before} -> ${after}。差分を取る"
OUT=$($PY diff_food.py 2>&1 | tail -12)
echo "$OUT"
{ echo "版が ${before} → ${after} に増えた。酒販免許PDF ${pdfs}本。"
  echo '```'; echo "$OUT"; echo '```'; } >> "$REPORT"
notify "閉店データが貯まりました（版 ${before} → ${after}）" \
       "\`\`\`
$(echo "$OUT" | head -10)
\`\`\`"
