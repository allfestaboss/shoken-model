#!/usr/bin/env python3
"""酒販免許の月次PDFを取りためる（launchdから毎月呼ばれる）。

国税庁が公表するのは直近ぶんだけで、古い月は消える。Waybackにも無い。
つまり**取り逃したら二度と手に入らない**ので、毎月ここで拾って積む。

**保存期間は局によって違う**（2026-08-17に全国を遡って取って判明）:
  ほとんどの局 … 12か月以上残っている
  金沢国税局（富山・石川・福井）  … 9か月ぶんしか残っていなかった
  大阪国税局（滋賀・京都・大阪・兵庫・奈良・和歌山）… 8か月ぶん
つまり「12か月あるから半年に1回でよい」ではない。この2局は取りこぼしが早い。

公表のタイミング: 令和8年5月分 の公表日は 令和8年6月30日。
つまり「ある月の分」は**翌月末**に出る。だから毎回、直近4か月ぶんを取りにいく
（すでにあるものは飛ばす）。

  python3 fetch_licenses.py          # 直近4か月を取得
  python3 fetch_licenses.py 24       # 直近24か月ぶんを試す（初回のバックフィル用）
"""
import sys
import time
import urllib.request
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent
DEST = ROOT / "data" / "nta"
BASE = "https://www.nta.go.jp/about/organization/{bureau}/sake/menkyo/hambai/data"
# 国税局ごとに管内の県が決まっている。URLの形はどの局も同じ。
# ファイル名は県のローマ字だが、実際に叩いて確かめた例外が2つある:
#   北海道 … 局が1県だけなので局名の sapporo.pdf（hokkaido.pdf は404）
#   群馬   … gumma.pdf（旧ヘボン式。gunma.pdf は404）
# 推測で並べると黙って抜けるので、全47県ぶん実際に200を確認済み。
BUREAUS = {
    "sapporo": ["sapporo"],
    "sendai": ["aomori", "iwate", "miyagi", "akita", "yamagata", "fukushima"],
    "kantoshinetsu": ["ibaraki", "tochigi", "gumma", "saitama", "niigata", "nagano"],
    "tokyo": ["chiba", "tokyo", "kanagawa", "yamanashi"],
    "kanazawa": ["toyama", "ishikawa", "fukui"],
    "nagoya": ["gifu", "shizuoka", "aichi", "mie"],
    "osaka": ["shiga", "kyoto", "osaka", "hyogo", "nara", "wakayama"],
    "hiroshima": ["tottori", "shimane", "okayama", "hiroshima", "yamaguchi"],
    "takamatsu": ["tokushima", "kagawa", "ehime", "kochi"],
    "fukuoka": ["fukuoka", "saga", "nagasaki"],
    "kumamoto": ["kumamoto", "oita", "miyazaki", "kagoshima"],
    "okinawa": ["okinawa"],
}
UA = "shoken-model/0.4 (research; boss@allfesta.com)"


def wareki(y: int, m: int) -> tuple:
    """西暦 -> (令和年2桁, 月2桁)"""
    return f"r{y - 2018:02d}", f"{m:02d}"


def months_back(n: int):
    y, m = date.today().year, date.today().month
    for _ in range(n):
        yield y, m
        m -= 1
        if m == 0:
            y, m = y - 1, 12


def main() -> None:
    n = int(sys.argv[1]) if len(sys.argv) > 1 else 4
    DEST.mkdir(parents=True, exist_ok=True)
    got, skipped, missing = 0, 0, 0

    for y, m in months_back(n):
        ry, rm = wareki(y, m)
        for bureau, prefs in BUREAUS.items():
          for pref in prefs:
            out = DEST / f"{ry}_{rm}_{pref}.pdf"
            if out.exists():
                skipped += 1
                continue
            url = f"{BASE.format(bureau=bureau)}/{ry}/{rm}/pdf/{pref}.pdf"
            try:
                req = urllib.request.Request(url, headers={"User-Agent": UA})
                with urllib.request.urlopen(req, timeout=60) as r:
                    body = r.read()
                if not body.startswith(b"%PDF"):
                    missing += 1
                    continue
                out.write_bytes(body)
                got += 1
                print(f"取得 {out.name}  {len(body)/1024:.0f}KB")
            except Exception as e:  # noqa: BLE001
                missing += 1
                print(f"取れず {ry}/{rm}/{pref}: {type(e).__name__}")
            time.sleep(1.5)

    print(f"[{date.today()}] 新規取得 {got} / 既存 {skipped} / 未公表・欠 {missing}"
          f" / 手元の総数 {len(list(DEST.glob('*.pdf')))}")


if __name__ == "__main__":
    main()
