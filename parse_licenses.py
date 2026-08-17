#!/usr/bin/env python3
"""酒販免許の新規取得者一覧（国税庁PDF）から、コンビニの新規開店を取り出す。

■ なぜこれが開店日になるか
  コンビニはほぼ全店が酒類を扱うので、開店直前に酒販免許を取る。
  国税庁が毎月公表するこの一覧には **免許年月日・屋号・所在地・処理区分** が載る。
  屋号がそのまま入っている（例:「ローソン福岡六本松四丁目店」）。

■ 取れる範囲
  公表は直近12か月ぶんのみ。過去分は削除済みで、Waybackにも無い（このパスは未アーカイブ）。
  つまり **2025年7月〜2026年6月の開店** が対象。数は少ないが、
  「モデルが高く評価した場所に、実際の新店が落ちるか」を確かめるには足りる。

■ 実装メモ
  PDFのテキストをそのまま読むとセルが行ごとにバラけて、日付と店名が繋がらない。
  罫線があるので pdfplumber の表抽出（extract_table）で読む。

  .venv-duck/bin/python parse_licenses.py   ->  data/openings.csv
"""
import csv
import re
from pathlib import Path

import pdfplumber

ROOT = Path(__file__).resolve().parent
DATA = ROOT / "data"

CHAINS = [("セブン-イレブン", r"セブン[－\-ー–ｰ]?イレブン"),
          ("ファミリーマート", r"ファミリーマート"),
          ("ローソン", r"ローソン"),
          ("ミニストップ", r"ミニストップ"),
          ("デイリーヤマザキ", r"デイリーヤマザキ|ヤマザキショップ"),
          ("ポプラ", r"ポプラ")]


def to_date(s: str):
    m = re.search(r"令和\s*(\d+)\s*年\s*(\d+)\s*月\s*(\d+)\s*日", s or "")
    return f"{2018 + int(m.group(1))}-{int(m.group(2)):02d}-{int(m.group(3)):02d}" if m else ""


def chain_of(text: str):
    for name, pat in CHAINS:
        if re.search(pat, text or ""):
            return name
    return None


def shop_name(cell: str) -> str:
    """『法人番号… / 法人名 / 屋号』が改行で入るので、チェーン名を含む行を屋号として拾う。"""
    for line in (cell or "").split("\n"):
        if chain_of(line):
            return re.sub(r"\s+", "", line)
    return re.sub(r"\s+", "", (cell or "").split("\n")[-1])


def main() -> None:
    rows = []
    for pdf_path in sorted((DATA / "nta").glob("*.pdf")):
        with pdfplumber.open(str(pdf_path)) as pdf:
            for page in pdf.pages:
                for tbl in page.extract_tables() or []:
                    for r in tbl:
                        if len(r) < 8 or not r[3]:
                            continue
                        name_cell = r[3]
                        if not chain_of(name_cell):
                            continue
                        rows.append({
                            "month": pdf_path.stem.replace("_fukuoka", ""),
                            "office": (r[0] or "").strip(),
                            "date": to_date(r[1]),
                            "chain": chain_of(name_cell),
                            "shop": shop_name(name_cell),
                            "addr": re.sub(r"\s+", "", (r[4] or "")),
                            "kind": (r[7] or "").strip(),
                        })

    # 同じ店が複数月に出ることは無いはずだが、念のため重複を落とす
    seen, uniq = set(), []
    for r in rows:
        k = (r["shop"], r["addr"])
        if k in seen:
            continue
        seen.add(k)
        uniq.append(r)

    path = DATA / "openings.csv"
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(uniq[0].keys()))
        w.writeheader()
        w.writerows(sorted(uniq, key=lambda r: r["date"]))

    from collections import Counter
    print(f"コンビニの免許 {len(uniq):,} 件（12か月ぶん）")
    print("  チェーン別:", dict(Counter(r["chain"] for r in uniq)))
    print("  処理区分  :", dict(Counter(r["kind"] or "(空)" for r in uniq)))
    print(f"  日付あり {sum(1 for r in uniq if r['date']):,} / 住所あり {sum(1 for r in uniq if r['addr']):,}")
    print(f"\n-> {path}")
    print("\n■ 新規のみ（＝新しく開いた店）")
    new = [r for r in uniq if r["kind"] == "新規"]
    for r in new[:12]:
        print(f"   {r['date']}  {r['shop'][:26]:<28}{r['addr'][:30]}")
    print(f"   … 計 {len(new)} 件")


if __name__ == "__main__":
    main()
