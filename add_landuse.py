#!/usr/bin/env python3
"""土地利用（建物用地率）を500mメッシュに足す。

国土数値情報「土地利用細分メッシュ」L03-b は100mメッシュ単位。
500mメッシュ1個は100mメッシュ5×5＝25個に対応するので、そのうち
「建物用地(0700)」が何個かを数えれば、建物用地率になる。

これが効く理由は2つ。
  1. モデルの説明変数として: 人口が同じでも、市街地か農地かで店の立ち方が違う
  2. 候補地の篩として: 建物用地率がほぼ0のメッシュは「余地」ではない

  python3 add_landuse.py   ->  data/mesh.csv を更新（列を追加）
"""
import csv
from collections import Counter
from pathlib import Path

from fetch_postoffices import read_dbf

ROOT = Path(__file__).resolve().parent
DATA = ROOT / "data"
LANDUSE_DIR = DATA / "mlit" / "landuse"

# L03-b-u（詳細版）の土地利用種コード。
# 詳細版では建物用地が 0701〜0704 に細分されるので、"07" で始まるものをまとめて建物用地とする
# （0700 決め打ちだと全部ゼロになる。実際に一度踏んだ）。
BUILDING_PREFIX = "07"
ROAD = "0901"
PADDY, FIELD, FOREST = "0100", "0200", "0500"


def mesh100_to_500(code: str) -> tuple:
    """100mメッシュコード(10桁) -> 500mメッシュの行・列。"""
    p, u = int(code[0:2]), int(code[2:4])
    q, v = int(code[4]), int(code[5])
    r, w = int(code[6]), int(code[7])
    row100, col100 = int(code[8]), int(code[9])
    lat_1km = (p * 8 + q) * 10 + r
    lon_1km = (u * 8 + v) * 10 + w
    return lat_1km * 2 + (1 if row100 >= 5 else 0), lon_1km * 2 + (1 if col100 >= 5 else 0)


def main() -> None:
    files = sorted(LANDUSE_DIR.glob("L03-b-u-16_*.dbf"))
    if not files:
        raise SystemExit("土地利用データが無い。data/mlit/landuse/ を確認")

    tally = {}
    total = 0
    for f in files:
        rows = read_dbf(f)
        total += len(rows)
        for r in rows:
            code = r.get("メッシュ", "")
            use = r.get("土地利用種", "")
            if len(code) != 10 or not code.isdigit():
                continue
            idx = mesh100_to_500(code)
            t = tally.setdefault(idx, Counter())
            t[use] += 1
            t["_n"] += 1
        print(f"  {f.name}: {len(rows):,} 件")
    print(f"100mメッシュ 合計 {total:,} 件 -> 500mメッシュ {len(tally):,} 個に集約")

    mesh_path = DATA / "mesh.csv"
    rows = list(csv.DictReader(mesh_path.open(encoding="utf-8")))
    hit = 0
    for r in rows:
        idx = (int(r["lat_i"]), int(r["lon_i"]))
        t = tally.get(idx)
        if t:
            hit += 1
            n = max(t["_n"], 1)
            build = sum(v for k, v in t.items() if k.startswith(BUILDING_PREFIX))
            r["build_share"] = round(build / n, 3)
            r["road_share"] = round(t[ROAD] / n, 3)
            r["green_share"] = round((t[PADDY] + t[FIELD] + t[FOREST]) / n, 3)
            r["lu_cells"] = t["_n"]
        else:
            r["build_share"] = ""
            r["road_share"] = ""
            r["green_share"] = ""
            r["lu_cells"] = 0

    fields = list(rows[0].keys())
    with mesh_path.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        w.writerows(rows)

    have = [r for r in rows if r["build_share"] != ""]
    avg = lambda xs: sum(float(x["build_share"]) for x in xs) / max(len(xs), 1)  # noqa: E731
    print(f"\n-> {mesh_path}  土地利用が付いたメッシュ {hit:,}/{len(rows):,}")
    # 店舗列はこの時点ではまだ無いことがある（基盤を作り直した直後など）
    if rows and "stores" in rows[0]:
        withstore = [r for r in have if int(r["stores"] or 0) > 0]
        nostore = [r for r in have if int(r["stores"] or 0) == 0]
        print(f"   建物用地率 平均: 店ありメッシュ {avg(withstore):.1%} / 店なし {avg(nostore):.1%}")
        zero = sum(1 for r in nostore if float(r["build_share"]) < .05)
        print(f"   店なしのうち建物用地率5%未満（＝そもそも市街地でない）: {zero:,}")
    else:
        print(f"   建物用地率 平均 {avg(have):.1%}")


if __name__ == "__main__":
    main()
