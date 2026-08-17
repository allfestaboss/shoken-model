#!/usr/bin/env python3
"""店舗レイヤをOSMからOvertureに差し替える（重複を掃除してメッシュに載せる）。

OSMは主要6チェーン2,313店に対し1,653店＝71%しか拾えていなかった。
Overtureは同じ基準で3,157件と、むしろ多い。ブランド別に見ると:

  セブン   1,124 / 公表1,063 = 1.06   ← OSMが最も取りこぼしていたチェーン
  ファミマ   619 /      543 = 1.14
  ローソン   932 /      534 = 1.75   ← 過大。ストア100や閉店跡、重複を含むとみられる
  ミニストップ 155 /      111 = 1.40
  デイリー    55 /       62 = 0.89

過大ぶんを減らすため、**40m以内の同カテゴリは1件に畳む**（同じ店の重複レコード）。
それでも公表値より多い分は、個人商店や非主要チェーン、閉店跡が混ざっているためで、
完全な正解ではない。ここは正直に「OSMより遥かに良いが、上振れがある」と扱う。

  python3 build_mesh_overture.py   ->  data/mesh.csv に stores_ov 列を追加
"""
import csv
import math
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent
DATA = ROOT / "data"
DEDUP_M = 40.0            # これ以内の同カテゴリは同一店とみなす
MIN_CONFIDENCE = 0.5


def dedupe(rows: list) -> list:
    """近接重複を畳む。confidence の高いほうを残す。"""
    cell = defaultdict(list)
    for r in rows:
        lat, lon = float(r["lat"]), float(r["lon"])
        cell[(round(lat * 400), round(lon * 400))].append(r)

    kept = []
    for _, items in cell.items():
        items.sort(key=lambda r: -float(r["confidence"] or 0))
        chosen = []
        for r in items:
            lat, lon = float(r["lat"]), float(r["lon"])
            if any(math.hypot((lat - float(k["lat"])) * 111000,
                              (lon - float(k["lon"])) * 93000) < DEDUP_M for k in chosen):
                continue
            chosen.append(r)
        kept.extend(chosen)
    return kept


def main() -> None:
    places = [r for r in csv.DictReader((DATA / "overture_places.csv").open(encoding="utf-8"))
              if float(r["confidence"] or 0) >= MIN_CONFIDENCE]

    by_cat = defaultdict(list)
    for r in places:
        by_cat[r["category"]].append(r)

    counts = {}
    for cat in ("convenience_store", "pharmacy", "drugstore", "supermarket"):
        before = by_cat.get(cat, [])
        after = dedupe(before)
        counts[cat] = after
        print(f"{cat:<20} {len(before):>6,} -> {len(after):>6,}（重複 {len(before)-len(after):,} 件を畳んだ）")

    rows = list(csv.DictReader((DATA / "mesh.csv").open(encoding="utf-8")))
    grids = {}
    for cat, items in counts.items():
        g = defaultdict(int)
        for r in items:
            g[(int(r["lat_i"]), int(r["lon_i"]))] += 1
        grids[cat] = g

    for r in rows:
        idx = (int(r["lat_i"]), int(r["lon_i"]))
        r["stores_ov"] = grids["convenience_store"].get(idx, 0)
        r["drug_ov"] = grids["pharmacy"].get(idx, 0) + grids["drugstore"].get(idx, 0)
        r["super_ov"] = grids["supermarket"].get(idx, 0)

    with (DATA / "mesh.csv").open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)

    osm = sum(int(r["stores"]) for r in rows)
    ov = sum(int(r["stores_ov"]) for r in rows)
    both = sum(1 for r in rows if int(r["stores"]) > 0 and int(r["stores_ov"]) > 0)
    only_osm = sum(1 for r in rows if int(r["stores"]) > 0 and int(r["stores_ov"]) == 0)
    only_ov = sum(1 for r in rows if int(r["stores"]) == 0 and int(r["stores_ov"]) > 0)
    print(f"\nメッシュ上の店舗: OSM {osm:,} / Overture {ov:,}")
    print(f"  両方にある {both:,} / OSMだけ {only_osm:,} / Overtureだけ {only_ov:,}")
    print(f"  ドラッグ・薬局 {sum(int(r['drug_ov']) for r in rows):,} / "
          f"スーパー {sum(int(r['super_ov']) for r in rows):,}"
          "  ← OSMでは事実上ゼロだった業態")
    print("\n-> data/mesh.csv（stores_ov / drug_ov / super_ov を追加）")


if __name__ == "__main__":
    main()
