#!/usr/bin/env python3
"""食品衛生申請等システムのオープンデータを読んで、飲食店の開店・閉店を組み立てる。

酒販免許は直近12か月しか残らなかったが、こちらは**2021年6月以降が丸ごと残る**。
しかも緯度経度が入っているのでジオコーディングが要らず、廃業年月日まである。
つまり開店と閉店の両方が、同じ台帳から同じ精度で取れる。

取得元（オープンデータ閲覧の画面が生成するURL）:
  https://i2fas.mhlw.go.jp/faspub/page/opendatadownload.jsp?param=<自治体コード>_food_business_all.csv
  福岡県内は 40000（県＝保健所設置市以外）/ 40100 北九州市 / 40130 福岡市 / 40203 久留米市。
  大牟田市(40202)はこの命名では取れない。

重要な制約:
  - **申請者がオープンデータ掲載に同意したものだけ**が載る。全数ではない
  - 2021年6月の制度開始以降のみ。それ以前の許可は各自治体のオープンデータ側にある
  - 業態「自動車」はキッチンカーで所在地が定まらないため、立地の分析からは外す

  python3 parse_food.py   ->  data/food_open.csv（開店）と要約
"""
import csv
import gzip
import io
import re
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent
DATA = ROOT / "data"
SNAP = DATA / "food" / "snapshots"


def latest_snapshot() -> Path:
    """いちばん新しい版のディレクトリ。版が無ければ従来の data/food を見る。"""
    vs = sorted(d for d in SNAP.glob("*") if d.is_dir())
    return vs[-1] if vs else DATA / "food"


SRC = latest_snapshot()

# 営業の種類は「① 飲食店営業」のように丸数字が頭に付く。番号は落として名前で判定する
DINING = ("飲食店営業", "喫茶店営業")
# 立地が定まらない業態は除く。「自動車営業」のように語尾が付くので部分一致で判定する
MOBILE = ("自動車", "露店", "仮設", "臨時", "自動販売機", "行商", "移動")


def clean(s: str) -> str:
    return re.sub(r"^[\s①-⑿\d.、]+", "", (s or "").strip())


def load(src: Path = None) -> list:
    """版のディレクトリから全自治体ぶんを読む。gz でも素の CSV でも読める。"""
    src = src or SRC
    rows = []
    for path in sorted(list(src.glob("*_food_business_all.csv.gz"))
                       + list(src.glob("*_food_business_all.csv"))):
        raw = path.read_bytes()
        if path.suffix == ".gz":
            raw = gzip.decompress(raw)
        text = raw.decode("utf-8-sig", errors="replace")
        for r in csv.DictReader(io.StringIO(text)):
            rows.append(r)
    return rows


def main() -> None:
    rows = load()
    print(f"読み込み {len(rows):,} 件（版 {SRC.name} / {len(list(SRC.glob('*_food_business_all.csv*')))} 自治体）\n")

    print("営業の種類 上位10")
    for k, n in Counter(clean(r["営業の種類"]) for r in rows).most_common(10):
        print(f"   {k:<24}{n:>8,}")

    dining = [r for r in rows if clean(r["営業の種類"]).startswith(DINING)]
    fixed = [r for r in dining
             if not any(w in clean(r["業態"]) for w in MOBILE)]
    geo = [r for r in fixed if (r["緯度"] or "").strip() and (r["経度"] or "").strip()]
    print(f"\n飲食・喫茶 {len(dining):,} → 移動営業を除く {len(fixed):,} → 緯度経度あり {len(geo):,}")

    print("\n業態 上位12（緯度経度あり）")
    for k, n in Counter(clean(r["業態"]) for r in geo).most_common(12):
        print(f"   {k:<20}{n:>8,}")

    print("\n初回許可年月日の年次分布（＝開店年）")
    yrs = Counter((r["初回許可年月日"] or "")[:4] for r in geo)
    for y in sorted(yrs):
        if y:
            print(f"   {y}   {yrs[y]:>7,}")

    closed = [r for r in geo if (r["廃業年月日"] or "").strip()]
    print(f"\n廃業年月日あり {len(closed):,}（{len(closed)/max(len(geo),1):.1%}）")
    cy = Counter((r["廃業年月日"] or "")[:4] for r in closed)
    for y in sorted(cy):
        if y:
            print(f"   {y}   {cy[y]:>7,}")

    out = DATA / "food_open.csv"
    fields = ["自治体コード", "市区町村名", "営業施設名称、屋号又は商号", "業態",
              "営業施設所在地", "緯度", "経度", "初回許可年月日", "廃業年月日"]
    with out.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
        w.writeheader()
        for r in geo:
            w.writerow({k: r.get(k, "") for k in fields})
    print(f"\n-> {out}  {len(geo):,}件")


if __name__ == "__main__":
    main()
