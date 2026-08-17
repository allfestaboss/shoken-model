#!/usr/bin/env python3
"""Foursquare の店舗をメッシュに載せる（stores_fsq / drug_fsq / super_fsq）。

Foursquare を選んだ決め手は **date_closed を持っていること**で、
「今も営業しているか」で絞れる。OSM も Overture も閉店跡を区別できず、
ローソンが公表値の1.75倍に膨らんでいた。営業中で絞ると5チェーンとも
公表値の1.05倍前後に収まる。

近接重複は Overture と同じ40mで畳む。Foursquare には confidence が無いので、
畳むときは先に来たものを残す（座標の丸めで並びは決まるので再現性はある）。

  .venv-duck/bin/python fetch_foursquare.py    # data/fsq_places.csv を作る
  python3 build_mesh_fsq.py                    # -> data/mesh.csv に列を追加
"""
import csv
import math
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent
DATA = ROOT / "data"
DEDUP_M = 40.0

# fsq_places.csv の category -> mesh.csv の列
GROUPS = {"stores_fsq": ("convenience_store",),
          "drug_fsq": ("pharmacy", "drugstore"),
          "super_fsq": ("supermarket",)}


def dedupe(rows: list) -> list:
    cell = defaultdict(list)
    for r in rows:
        cell[(round(float(r["lat"]) * 400), round(float(r["lon"]) * 400))].append(r)
    kept = []
    for _, items in sorted(cell.items()):
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
    places = [r for r in csv.DictReader((DATA / "fsq_places.csv").open(encoding="utf-8"))
              if not int(r["closed"] or 0)]           # 営業中だけ
    by_cat = defaultdict(list)
    for r in places:
        by_cat[r["category"]].append(r)

    grids = {}
    print(f"{'業態':<22}{'営業中':>8}{'重複を畳んだ後':>14}")
    for col, cats in GROUPS.items():
        items = []
        for c in cats:
            before = by_cat.get(c, [])
            after = dedupe(before)
            items += after
            print(f"{c:<22}{len(before):>8,}{len(after):>14,}")
        g = defaultdict(int)
        for r in items:
            g[(int(r["lat_i"]), int(r["lon_i"]))] += 1
        grids[col] = g

    rows = list(csv.DictReader((DATA / "mesh.csv").open(encoding="utf-8")))
    for r in rows:
        idx = (int(r["lat_i"]), int(r["lon_i"]))
        for col in GROUPS:
            r[col] = grids[col].get(idx, 0)

    with (DATA / "mesh.csv").open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)

    print(f"\n-> data/mesh.csv")
    print(f"{'県':<6}{'コンビニ':>9}{'ドラッグ・薬局':>14}{'スーパー':>9}{'人口/コンビニ':>14}")
    for pref in sorted({r.get("pref", "") for r in rows if r.get("pref")}):
        s = [r for r in rows if r.get("pref") == pref]
        n = lambda k: sum(int(r[k]) for r in s)                       # noqa: E731
        pop = sum(float(r["pop2020"]) for r in s)
        print(f"{pref:<6}{n('stores_fsq'):>9,}{n('drug_fsq'):>14,}"
              f"{n('super_fsq'):>9,}{pop/max(n('stores_fsq'),1):>14,.0f}")


if __name__ == "__main__":
    main()
