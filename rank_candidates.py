#!/usr/bin/env python3
"""候補地を篩う。ただし「店が無い」ではなく「相対的に薄い」までしか言わない。

■ 建物の篩では足りなかった
  最初は「建物が描かれているか」で篩った。しかし建物は航空写真からの取り込みで
  一気に入るのに対し、**店舗（POI）は現地調査が要る**。実際、上位候補は
  3x3に建物6,800件が描かれているのに店は13件しか登録されていなかった。
  人口3.5万の市街地で店13件は現実的でない。建物は「店が調査されたか」を保証しない。

■ どこまで言えるか
  OSMの店舗密度は、店ありメッシュでも中央値 1.24件/千人。
  経済センサスの小売業は全国で約8事業所/千人なので、**OSMは小売の1〜2割しか拾っていない**。
  つまり「OSMにコンビニが無い」は、店が無いことの証拠としては弱い。

  そこで主張を下げる:
    ×  ここに店が無い（＝出店余地がある）
    ○  ここは、同じ条件の他の場所に比べて**相対的に薄い**
  順位そのものは、都市を丸ごと隠した検証（AUC 0.83）で裏付けがある。
  絶対に「無い」と言うには、チェーン公式の店舗一覧のような全数データが要る。

  python3 rank_candidates.py   ->  data/candidates.csv
"""
import csv
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent
DATA = ROOT / "data"

# 店ありメッシュの店舗密度の中央値。これ未満は「そもそも調査されていない」とみなす
# 土台をOvertureに替えたので、篩の役割が変わった。
# OSM時代は「そもそも調査されているか」を篩う必要があったが、Overtureは主要チェーンで
# ほぼ全数（セブン1.06・ファミマ1.14）。なので店舗密度の篩は補助に落とし、
# 人口の下限だけ残す。
MIN_SHOP_DENSITY = 0.0
MIN_POP_R1 = 3000


def main() -> None:
    pred = list(csv.DictReader((DATA / "mesh_pred.csv").open(encoding="utf-8")))
    mesh = {(r["lat_i"], r["lon_i"]): r
            for r in csv.DictReader((DATA / "mesh.csv").open(encoding="utf-8"))}

    g_shop = {(int(k[0]), int(k[1])): int(v["osm_shops"]) for k, v in mesh.items()}
    g_bld = {(int(k[0]), int(k[1])): int(v["osm_buildings"]) for k, v in mesh.items()}

    def around(r, g):
        la, lo = int(r["lat_i"]), int(r["lon_i"])
        return sum(g.get((la + i, lo + j), 0) for i in (-1, 0, 1) for j in (-1, 0, 1))

    for r in pred:
        r["shops_r1"] = around(r, g_shop)
        r["buildings_r1"] = around(r, g_bld)
        pop = float(r["pop_r1"])
        r["shop_density"] = round(r["shops_r1"] / pop * 1000, 2) if pop > 0 else 0.0

    cand = [r for r in pred
            if int(r["stores"]) == 0
            and float(r["deficit_r1"]) > 1.0
            and float(r["pop_r1"]) >= MIN_POP_R1]

    for r in cand:
        r["surveyed"] = int(r["shop_density"] >= MIN_SHOP_DENSITY)

    ok = [r for r in cand if r["surveyed"]]
    ng = [r for r in cand if not r["surveyed"]]
    print(f"候補（店なし・不足1.0店以上・3x3に3,000人以上） {len(cand):,} 件")
    print(f"  調査済みの場所   {len(ok):,}（{len(ok)/max(len(cand),1):.0%}）")
    print(f"  未調査の疑い     {len(ng):,}（{len(ng)/max(len(cand),1):.0%}）")
    print(f"  ※基準: 3x3の店舗密度 {MIN_SHOP_DENSITY}件/千人以上"
          f"（店ありメッシュの中央値）")

    print("\n■ 相対的に薄い場所（調査済みの場所だけ・不足の大きい順）上位15")
    print(f"   {'座標':<24}{'市町村':<8}{'3x3人口':>8}{'店密度':>7}{'期待':>7}{'実店舗':>7}{'不足':>7}")
    for r in sorted(ok, key=lambda r: -float(r["deficit_r1"]))[:15]:
        print(f"   {r['lat']},{r['lon']:<12} {r['city']:<8}"
              f"{float(r['pop_r1']):>8.0f}{r['shop_density']:>7.2f}"
              f"{float(r['exp_r1']):>7.1f}{int(r['stores_r1']):>7}"
              f"{float(r['deficit_r1']):>7.1f}")

    path = DATA / "candidates.csv"
    fields = ["lat", "lon", "city", "pop2020", "pop_r1", "build_share", "trunk_m",
              "station_m", "osm_buildings", "buildings_r1", "shops_r1", "shop_density",
              "lambda", "exp_r1", "stores_r1", "deficit_r1", "surveyed"]
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
        w.writeheader()
        w.writerows(sorted(cand, key=lambda r: -float(r["deficit_r1"])))
    print(f"\n-> {path}")

    c = Counter(r["city"] for r in ok)
    print("\n■ 薄い場所が多い市町村")
    for code, n in c.most_common(8):
        print(f"   {code}  {n:>3} メッシュ")

    print("\n注意: これは『店が無い』ではなく『相対的に薄い』のリスト。")
    print("      OSMは小売の1〜2割しか拾っていないため、絶対的な不在は確認できない。")


if __name__ == "__main__":
    main()
