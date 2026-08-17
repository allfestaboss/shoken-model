#!/usr/bin/env python3
"""OSM と Overture を突き合わせ、標識再捕獲法で「本当は何店あるか」を推定する。

2つの独立したデータソースが同じ母集団を別々に「捕獲」していると見なせば、
両方に写っている店（再捕獲）の数から、**どちらにも写っていない店を含む総数**が推定できる。

  Lincoln-Petersen（Chapman補正）
      N ≈ (n1+1)(n2+1)/(m+1) − 1
  n1 = OSMの店舗数 / n2 = Overtureの店舗数 / m = 両方にある数

■ 推定法そのものを検証できる
  セブン-イレブンだけは公表値（福岡県1,063店）という正解がある。
  セブンで推定して1,063に近ければ、この方法は信用できる。合わなければ
  「独立性の仮定」が崩れている（＝両ソースが同じ店を落としている）ことになる。

  python3 crosscheck.py   ->  data/crosscheck.csv
"""
import csv
import json
import math
import re
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent
DATA = ROOT / "data"
MATCH_M = 70.0        # これ以内で同ブランドなら同じ店とみなす

BRANDS = [("セブン", r"セブン|7[\s\-]?eleven|セブンイレブン"),
          ("ファミマ", r"ファミリーマート|family\s?mart|famima"),
          ("ローソン", r"ローソン|lawson"),
          ("ミニストップ", r"ミニストップ|ministop"),
          ("デイリー", r"デイリーヤマザキ|daily\s?yamazaki")]
PUBLISHED = {"セブン": 1063, "ファミマ": 543, "ローソン": 534,
             "ミニストップ": 111, "デイリー": 62}


def brand_of(text: str) -> str:
    s = (text or "").lower()
    for name, pat in BRANDS:
        if re.search(pat, s):
            return name
    return "その他"


def dist_m(a, b) -> float:
    return math.hypot((a[0] - b[0]) * 111000, (a[1] - b[1]) * 93000)


def match(src1: list, src2: list) -> int:
    """近い順に1対1で対応づけ、対応がついた数を返す。"""
    grid = defaultdict(list)
    for i, p in enumerate(src2):
        grid[(round(p[0] * 400), round(p[1] * 400))].append(i)
    used = set()
    m = 0
    for p in src1:
        best, bd = None, MATCH_M
        c = (round(p[0] * 400), round(p[1] * 400))
        for di in (-1, 0, 1):
            for dj in (-1, 0, 1):
                for j in grid.get((c[0] + di, c[1] + dj), []):
                    if j in used:
                        continue
                    d = dist_m(p, src2[j])
                    if d < bd:
                        best, bd = j, d
        if best is not None:
            used.add(best)
            m += 1
    return m


def chapman(n1: int, n2: int, m: int) -> tuple:
    """Chapman補正つき推定量と、その標準誤差。"""
    n = (n1 + 1) * (n2 + 1) / (m + 1) - 1
    var = ((n1 + 1) * (n2 + 1) * (n1 - m) * (n2 - m)) / ((m + 1) ** 2 * (m + 2))
    return n, math.sqrt(max(var, 0))


def main() -> None:
    osm = [(p["lat"], p["lon"], brand_of(p.get("brand", "")))
           for p in json.loads((DATA / "stores_points.json").read_text(encoding="utf-8"))]
    ov = [(float(r["lat"]), float(r["lon"]),
           brand_of((r.get("brand") or "") + " " + (r.get("name") or "")))
          for r in csv.DictReader((DATA / "overture_places.csv").open(encoding="utf-8"))
          if r["category"] == "convenience_store"]
    print(f"OSM {len(osm):,} 点 / Overture {len(ov):,} 点\n")

    rows = []
    print(f"{'チェーン':<10}{'OSM':>7}{'Overture':>10}{'両方':>7}{'推定総数':>10}"
          f"{'±':>8}{'公表':>8}{'推定/公表':>10}")
    for name in list(PUBLISHED) + ["その他", "合計"]:
        if name == "合計":
            a = [(p[0], p[1]) for p in osm]
            b = [(p[0], p[1]) for p in ov]
            pub = sum(PUBLISHED.values())
        else:
            a = [(p[0], p[1]) for p in osm if p[2] == name]
            b = [(p[0], p[1]) for p in ov if p[2] == name]
            pub = PUBLISHED.get(name, 0)
        if not a or not b:
            continue
        m = match(a, b)
        est, se = chapman(len(a), len(b), m)
        ratio = f"{est/pub:.2f}" if pub else "—"
        print(f"{name:<10}{len(a):>7,}{len(b):>10,}{m:>7,}{est:>10,.0f}{se:>8,.0f}"
              f"{(pub or 0):>8,}{ratio:>10}")
        rows.append({"brand": name, "osm": len(a), "overture": len(b), "matched": m,
                     "estimated": round(est), "se": round(se), "published": pub,
                     "osm_coverage": round(len(a) / est, 3) if est else "",
                     "overture_coverage": round(len(b) / est, 3) if est else ""})

    with (DATA / "crosscheck.csv").open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)

    print("\n各ソースの網羅率（推定総数に対する割合）")
    for r in rows:
        if r["published"]:
            print(f"   {r['brand']:<10} OSM {r['osm_coverage']:>5.0%} / "
                  f"Overture {r['overture_coverage']:>5.0%}")
    print(f"\n-> {DATA/'crosscheck.csv'}")
    print("\n注: 両ソースが同じ店を落としていると（独立でないと）推定は過小になる。"
          "\n    セブンの推定が公表1,063に近いかどうかが、その検算になる。")


if __name__ == "__main__":
    main()
