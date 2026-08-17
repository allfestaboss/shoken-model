#!/usr/bin/env python3
"""全国の酒販免許PDFから新規開店を抜き出す。

福岡3県ぶんの処理を47県に広げたもの。513本のPDFを読むので数分かかる。
結果は data/openings_all.csv に貯める（座標化はここではしない）。

屋号でチェーンを見分ける。免許の一覧には酒を扱う小売がすべて載るので、
コンビニ・ドラッグ・スーパーはここで拾える。

  python3 parse_openings.py   ->  data/openings_all.csv
"""
import csv
import re
from collections import Counter
from pathlib import Path

import pdfplumber

from prefs import CODE, JP
from validate_openings_multi import CATS

ROOT = Path(__file__).resolve().parent
DATA = ROOT / "data"


def wareki_to_date(s: str) -> str:
    m = re.search(r"令和\s*(\d+)\s*年\s*(\d+)\s*月\s*(\d+)\s*日", s or "")
    return f"{2018 + int(m.group(1))}-{int(m.group(2)):02d}-{int(m.group(3)):02d}" if m else ""


def main() -> None:
    pdfs = sorted((DATA / "nta").glob("*.pdf"))
    print(f"PDF {len(pdfs)} 本を読む …")
    rows, bad = [], 0
    for i, path in enumerate(pdfs, 1):
        pref = path.stem.split("_", 2)[2]
        if pref not in JP:
            bad += 1
            continue
        try:
            with pdfplumber.open(str(path)) as pdf:
                for page in pdf.pages:
                    for tbl in page.extract_tables() or []:
                        for r in tbl:
                            if len(r) < 8 or not r[3] or r[0] == "税務署名":
                                continue
                            if (r[7] or "").strip() != "新規":
                                continue
                            name = re.sub(r"\s+", "", r[3])
                            cat = next((c for c, (_, pat) in CATS.items()
                                        if re.search(pat, name)), None)
                            if not cat:
                                continue
                            rows.append({
                                "pref": pref, "pref_code": CODE[pref], "cat": cat,
                                "date": wareki_to_date(r[1]), "shop": name[:60],
                                "addr": re.sub(r"\s+", "", r[4] or ""),
                            })
        except Exception as e:  # noqa: BLE001
            bad += 1
            print(f"  読めず {path.name}: {type(e).__name__}")
        if i % 100 == 0:
            print(f"  {i}/{len(pdfs)}  ここまで {len(rows):,} 件")

    seen, uniq = set(), []
    for r in rows:
        k = (r["pref"], r["shop"], r["addr"])
        if k not in seen:
            seen.add(k)
            uniq.append(r)

    path = DATA / "openings_all.csv"
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(uniq[0].keys()))
        w.writeheader()
        w.writerows(uniq)

    print(f"\n-> {path}  {len(uniq):,} 件（重複前 {len(rows):,} / 読めず {bad}）")
    c = Counter(r["cat"] for r in uniq)
    for k, n in c.most_common():
        print(f"   {k:<16}{n:>7,}")
    top = Counter(JP[r["pref"]] for r in uniq).most_common(8)
    print("\n   県別の多い順:", "  ".join(f"{k}{n}" for k, n in top))


if __name__ == "__main__":
    main()
