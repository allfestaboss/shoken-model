#!/usr/bin/env python3
"""食品衛生申請等システムのオープンデータを全国ぶん取って、版として貯める。

このデータは**上書き更新される**。閉店した店は次の版で消えるか廃業年月日が付く。
つまり1枚だけ持っていても閉店は分からない。**版を積んで差分を取ると閉店が取れる**。
廃業年月日の欄は2026年に記録され始めたばかりで、74,021件中192件しか入っていない。
歴史は取り返せないので、いま積み始めるしかない（酒販免許と同じ構造）。

対象は157自治体（47都道府県＋保健所設置市110）。都道府県の版には
その県の保健所設置市**以外**が入る。大牟田市のようにコードがあっても
保健所設置市でない市は単独では出てこない（県の版に含まれる）。

  https://i2fas.mhlw.go.jp/faspub/page/opendatadownload.jsp?param=<自治体コード>_food_business_all.csv

CSVには緯度経度・初回許可年月日・廃業年月日・業態が入っており、
ジオコーディングが要らない。ただし**申請者がオープンデータ掲載に同意したものだけ**。

  python3 fetch_food.py              # 今月の版を取る（既にあるものは飛ばす）
  python3 fetch_food.py 2026-07      # 版の名前を指定する
  python3 fetch_food.py --codes 40000,40130
"""
import gzip
import sys
import time
import urllib.request
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent
DATA = ROOT / "data"
SNAP = DATA / "food" / "snapshots"
CODES_FILE = DATA / "food" / "codes.tsv"
URL = "https://i2fas.mhlw.go.jp/faspub/page/opendatadownload.jsp?param={}_food_business_all.csv"
UA = "shoken-model/0.5 (research; boss@allfesta.com)"
SLEEP = 1.5


def codes() -> list:
    """自治体コードの一覧。オープンデータ閲覧画面の項目名から作った表を読む。"""
    out = []
    for line in CODES_FILE.read_text(encoding="utf-8").splitlines():
        if not line.strip() or line.startswith("#"):
            continue
        code, _, name = line.partition("\t")
        out.append((code.strip(), name.strip()))
    return out


def main() -> None:
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    tag = args[0] if args else date.today().strftime("%Y-%m")
    only = None
    for a in sys.argv[1:]:
        if a.startswith("--codes"):
            only = set(a.split("=", 1)[1].split(",")) if "=" in a else None
    dest = SNAP / tag
    dest.mkdir(parents=True, exist_ok=True)

    got = skipped = failed = 0
    total = 0
    targets = [(c, n) for c, n in codes() if only is None or c in only]
    for i, (code, name) in enumerate(targets, 1):
        out = dest / f"{code}_food_business_all.csv.gz"
        if out.exists() and out.stat().st_size > 0:
            skipped += 1
            total += out.stat().st_size
            continue
        try:
            req = urllib.request.Request(URL.format(code), headers={"User-Agent": UA})
            with urllib.request.urlopen(req, timeout=180) as r:
                body = r.read()
            # 中身がCSVか確かめる。エラー画面はHTMLで返ってくる
            head = body[:200].decode("utf-8-sig", errors="replace")
            if "自治体コード" not in head:
                failed += 1
                print(f"  [{i}/{len(targets)}] {code} {name}: CSVでない（{len(body):,}B）")
                continue
            out.write_bytes(gzip.compress(body, 6))
            got += 1
            total += out.stat().st_size
            print(f"  [{i}/{len(targets)}] {code} {name}  "
                  f"{len(body)/1048576:.1f}MB -> {out.stat().st_size/1048576:.1f}MB")
        except Exception as e:  # noqa: BLE001
            failed += 1
            print(f"  [{i}/{len(targets)}] {code} {name}: {type(e).__name__}")
        time.sleep(SLEEP)

    print(f"\n[{date.today()}] 版 {tag}: 新規 {got} / 既存 {skipped} / 失敗 {failed}"
          f" / 合計 {total/1048576:,.0f}MB")


if __name__ == "__main__":
    main()
