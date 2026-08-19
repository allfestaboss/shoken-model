#!/usr/bin/env bash
# VPSが集めたものを手元に引く。**VPSが正本**で、こちらは複製。
#
# 収集はVPSのcron（毎月5・12・20・26日）が回している。Macが落ちていても取り逃さない。
# こちらはMacが起きているときに追いつけばよいので、片方向に引くだけ。
set -euo pipefail
cd "$(dirname "$0")"
HOST=dx-fukuoka-vps
SRC=/root/apps/shoken-collect

echo "== VPSの状態 =="
ssh $HOST "cd $SRC && printf '  版 %s 個 / 酒販免許PDF %s本 / %s\n' \
  \"\$(ls -d data/food/snapshots/*/ 2>/dev/null | wc -l | tr -d ' ')\" \
  \"\$(ls data/nta/*.pdf 2>/dev/null | wc -l | tr -d ' ')\" \
  \"\$(du -sh data | cut -f1)\""

echo "== 引く =="
# macOS標準のrsyncは古く --info を解さない。渡すと使い方が表示されて
# 転送されない（黙って空振りするので気づきにくい。実際に踏んだ）
rsync -az --stats "$HOST:$SRC/data/food/snapshots/" data/food/snapshots/ \
  | grep -E "files transferred|Total transferred" | sed "s/^/  /"
rsync -az $HOST:$SRC/data/nta/ data/nta/
rsync -az $HOST:$SRC/data/food/REPORT.md data/food/ 2>/dev/null || true

echo "== 手元 =="
printf '  版 %s 個 / 酒販免許PDF %s本\n' \
  "$(ls -d data/food/snapshots/*/ 2>/dev/null | wc -l | tr -d ' ')" \
  "$(ls data/nta/*.pdf 2>/dev/null | wc -l | tr -d ' ')"
[ -f data/food/REPORT.md ] && tail -4 data/food/REPORT.md | sed 's/^/  /'
