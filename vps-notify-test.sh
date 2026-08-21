#!/usr/bin/env bash
# 通知の口が生きているか確かめる。Webhookの値は表示しない。
set -uo pipefail
cd /root/apps/shoken-collect
[ -f .env ] || { echo "  .env が無い。DISCORD_WEBHOOK= を書いてください"; exit 1; }
# source だけではシェル変数どまり。set -a で環境変数にする
set -a; . ./.env; set +a
HOOK="${DISCORD_WEBHOOK_URL:-${DISCORD_WEBHOOK:-}}"
[ -n "$HOOK" ] || { echo "  .env に DISCORD_WEBHOOK_URL がない"; exit 1; }
echo "  Webhook を読み込んだ（末尾4文字 …${HOOK: -4}）"
WEBHOOK="$HOOK" /usr/bin/python3 - <<'PY'
import json, os, urllib.request
body = json.dumps({"embeds": [{
    "title": "通知の口の確認",
    "description": ("収集は VPS の cron（毎月5・12・20・26日）で回っています。\n"
                    "食品衛生の版が増えたとき、閉店の件数をここに流します。\n"
                    "版が増えない月は投稿しません（記録は REPORT.md に残ります）。"),
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
    with urllib.request.urlopen(req, timeout=20) as r:
        print(f"  送信 OK（HTTP {r.status}）")
except Exception as e:
    print(f"  送信できず {type(e).__name__}: {e}")
PY
