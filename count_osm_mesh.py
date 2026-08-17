#!/usr/bin/env python3
"""OSMの抽出データ（九州）から、500mメッシュごとの建物数・店舗数を数える。

Overpass API に候補ごとの問い合わせを投げ続けたところ、fair use を超えて
IPをブロックされた。OSM側の案内どおり、**大量処理は抽出データを落として手元で回す**。
こちらのほうが結果も上位互換で、候補100件どころか全メッシュぶんが一度に出る。
APIへの問い合わせはゼロになる。

  データ: https://download.geofabrik.de/asia/japan/kyushu-latest.osm.pbf（約300MB）
  用途:
    building 数 -> その場所が「地図に描かれているか」の指標（欠測の検出）
    shop 数     -> 商業集積の指標（モデルの説明変数にもなる）
    convenience -> 以前 Overpass で数えた店舗数の答え合わせ

  .venv-osm/bin/python count_osm_mesh.py   ->  data/osm_mesh.csv
"""
import csv
import math
from collections import defaultdict
from pathlib import Path

import osmium

from region import bbox

ROOT = Path(__file__).resolve().parent
DATA = ROOT / "data"
PBF = DATA / "osm" / "kyushu-latest.osm.pbf"

# 福岡県のおおよその範囲（九州全体を読むので、ここで絞る）
# 範囲は data/mesh.csv から作る（県を足したときの直し忘れを防ぐ）
LAT_MIN, LAT_MAX, LON_MIN, LON_MAX = bbox()


def mesh_index(lat: float, lon: float) -> tuple:
    return math.floor(lat * 240), math.floor((lon - 100) * 160)


class MeshCounter(osmium.SimpleHandler):
    def __init__(self):
        super().__init__()
        self.buildings = defaultdict(int)
        self.shops = defaultdict(int)
        self.convenience = defaultdict(int)
        self.seen = 0

    def _tally(self, tags, lat, lon):
        if not (LAT_MIN <= lat <= LAT_MAX and LON_MIN <= lon <= LON_MAX):
            return
        idx = mesh_index(lat, lon)
        if "building" in tags:
            self.buildings[idx] += 1
        shop = tags.get("shop")
        if shop:
            self.shops[idx] += 1
            if shop == "convenience":
                self.convenience[idx] += 1
        self.seen += 1

    def node(self, n):
        if n.location.valid() and n.tags:
            self._tally(n.tags, n.location.lat, n.location.lon)

    def way(self, w):
        if not w.tags or len(w.nodes) == 0:
            return
        try:
            loc = w.nodes[0].location          # locations=True で解決済み
            if loc.valid():
                self._tally(w.tags, loc.lat, loc.lon)
        except osmium.InvalidLocationError:
            pass


def main() -> None:
    if not PBF.exists():
        raise SystemExit(f"{PBF} が無い。Geofabrik から落としてから実行")

    print(f"{PBF.name}（{PBF.stat().st_size/1e6:.0f}MB）を読む …")
    h = MeshCounter()
    h.apply_file(str(PBF), locations=True, idx="flex_mem")
    print(f"  タグ付き要素 {h.seen:,} 件を福岡県の範囲で集計")
    print(f"  建物 {sum(h.buildings.values()):,} / 店 {sum(h.shops.values()):,} / "
          f"コンビニ {sum(h.convenience.values()):,}")

    mesh_path = DATA / "mesh.csv"
    rows = list(csv.DictReader(mesh_path.open(encoding="utf-8")))
    for r in rows:
        idx = (int(r["lat_i"]), int(r["lon_i"]))
        r["osm_buildings"] = h.buildings.get(idx, 0)
        r["osm_shops"] = h.shops.get(idx, 0)
        r["osm_conv"] = h.convenience.get(idx, 0)

    with mesh_path.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)

    # 以前 Overpass の area クエリで数えた店舗数との答え合わせ
    a = sum(int(r["stores"]) for r in rows)
    b = sum(int(r["osm_conv"]) for r in rows)
    same = sum(1 for r in rows if int(r["stores"]) == int(r["osm_conv"]))
    print(f"\n答え合わせ: Overpass経由 {a:,} 店 / 抽出データ {b:,} 店 "
          f"（メッシュ単位で一致 {same:,}/{len(rows):,}）")

    nb = [r for r in rows if int(r["osm_buildings"]) < 50 and float(r["pop_r1"]) > 3000]
    print(f"人口3,000人超なのに建物50件未満のメッシュ: {len(nb):,}（＝地図の穴）")
    print(f"-> {mesh_path}")


if __name__ == "__main__":
    main()
