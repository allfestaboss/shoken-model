#!/usr/bin/env python3
"""厚生局の「コード内容別医療機関一覧表」を取る（診療所・歯科・薬局の開店日）。

「この地域はどの業種が増えるか」を検証するには、開店データのある業種を増やすしかない。
酒販免許（コンビニ・ドラッグ・スーパー）と食品衛生（飲食・パン屋）に加えて、
厚生局の一覧には**指定年月日**が入っており、これが医療機関の開設日にあたる。

福岡県の医科4,347件で年次分布を確かめたところ、6年ごとの更新による山は無く、
なだらかだった（食品衛生の「初年度許可日」が更新で書き換わっていたのとは違う）。

**座標化はしない**。検証は県単位の集計で足りるので、住所を座標に直す必要がない
（全国3万件を1秒ずつ引くと8時間かかる）。

  .venv-duck/bin/python fetch_medical.py   ->  data/medical/*.xlsx
"""
import io
import re
import time
import urllib.request
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent
DEST = ROOT / "data" / "medical"
UA = {"User-Agent": "shoken-model/0.5 (research; boss@allfesta.com)"}
BASE = "https://kouseikyoku.mhlw.go.jp"

# 局ごとに一覧ページの場所が違う。実際に叩いて200かつ中身にzipがあるものを確認済み
PAGES = {
    "tohoku": "gyomu/gyomu/hoken_kikan/index.html",
    "kantoshinetsu": "gyomu/gyomu/hoken_kikan/index.html",
    "shikoku": "gyomu/gyomu/hoken_kikan/index.html",
    "kyushu": "gyomu/gyomu/hoken_kikan/index_00006.html",
}
MAX_ZIP = 14          # ページは新しい版が先頭に並ぶ。先頭のぶんだけ見れば足りる


def get(url: str) -> bytes:
    with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=120) as r:
        return r.read()


def main() -> None:
    DEST.mkdir(parents=True, exist_ok=True)
    have = {p.name for p in DEST.glob("*.xlsx")}
    got = 0
    for bureau, path in PAGES.items():
        try:
            body = get(f"{BASE}/{bureau}/{path}")
        except Exception as e:  # noqa: BLE001
            print(f"{bureau}: ページが取れず {type(e).__name__}")
            continue
        text = body.decode("utf-8", errors="replace")
        zips = []
        for href in re.findall(r'href="([^"]+\.zip)"', text):
            if href not in zips:
                zips.append(href)
        print(f"{bureau}: zip {len(zips)} 本のうち先頭 {min(len(zips), MAX_ZIP)} 本を見る")

        for href in zips[:MAX_ZIP]:
            url = href if href.startswith("http") else BASE + href
            try:
                blob = get(url)
                with zipfile.ZipFile(io.BytesIO(blob)) as z:
                    for name in z.namelist():
                        # 中のファイル名に種別と県が入る（r8_08_ika_fukuoka_02.xlsx）
                        base = Path(name).name
                        if not base.endswith((".xlsx", ".xls")) or base in have:
                            continue
                        (DEST / base).write_bytes(z.read(name))
                        have.add(base)
                        got += 1
            except Exception as e:  # noqa: BLE001
                print(f"   取れず {href}: {type(e).__name__}")
            time.sleep(1.0)

    files = sorted(DEST.glob("*.xls*"))
    kinds = {}
    for f in files:
        m = re.match(r"r\d+_\d+_([a-z]+)_([a-z]+)", f.stem)
        if m:
            kinds.setdefault(m.group(1), set()).add(m.group(2))
    print(f"\n-> {DEST}  新規 {got} / 合計 {len(files)} ファイル")
    for k, v in sorted(kinds.items()):
        print(f"   {k:<10}{len(v):>3}県  {' '.join(sorted(v))[:80]}")


if __name__ == "__main__":
    main()
