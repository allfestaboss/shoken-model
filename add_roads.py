#!/usr/bin/env python3
"""道路と駅を500mメッシュに足す（OSM抽出データから。API呼び出しなし）。

岡垣町（昼夜間比80のベッドタウンなのに店が2.65倍）が示していたのは
「通過需要」で、これは人口にも昼夜間比にも表れない。国道沿いかどうかが効くはず。

  幹線道路の延長  = motorway / trunk / primary（＋二次幹線 secondary）
  生活道路の延長  = residential など
  交差点らしさ    = 幹線どうしが交わる回数の代理として、幹線ノードの数
  駅              = railway=station までの距離

道路の長さは、連続する2ノードごとに距離を出し、その中点が属するメッシュに足す。
（1本の道路が複数メッシュに跨っても、ちゃんと分割されて配分される）

  .venv-osm/bin/python add_roads.py   ->  data/mesh.csv を更新
"""
import csv
import math
from collections import defaultdict
from pathlib import Path

import osmium

from region import bbox

ROOT = Path(__file__).resolve().parent
DATA = ROOT / "data"
# data/osm にある地域抽出をすべて読む。県を足したら pbf を足すだけでよい
PBFS = sorted((DATA / "osm").glob("*-latest.osm.pbf"))

# 範囲は data/mesh.csv から作る（県を足したときの直し忘れを防ぐ）
LAT_MIN, LAT_MAX, LON_MIN, LON_MAX = bbox()

TRUNK = {"motorway", "trunk", "primary", "motorway_link", "trunk_link", "primary_link"}
SECOND = {"secondary", "tertiary", "secondary_link", "tertiary_link"}
LOCAL = {"residential", "unclassified", "living_street"}


def mesh_index(lat: float, lon: float) -> tuple:
    return math.floor(lat * 240), math.floor((lon - 100) * 160)


def haversine(lat1, lon1, lat2, lon2) -> float:
    r = 6371000.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = p2 - p1
    dl = math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


class RoadHandler(osmium.SimpleHandler):
    def __init__(self):
        super().__init__()
        self.trunk_m = defaultdict(float)
        self.second_m = defaultdict(float)
        self.local_m = defaultdict(float)
        self.stations = []          # (lat, lon)
        self.ways = 0

    def node(self, n):
        if n.tags.get("railway") == "station" and n.location.valid():
            lat, lon = n.location.lat, n.location.lon
            if LAT_MIN <= lat <= LAT_MAX and LON_MIN <= lon <= LON_MAX:
                self.stations.append((lat, lon))

    def way(self, w):
        hw = w.tags.get("highway")
        if hw is None:
            return
        if hw in TRUNK:
            bucket = self.trunk_m
        elif hw in SECOND:
            bucket = self.second_m
        elif hw in LOCAL:
            bucket = self.local_m
        else:
            return
        self.ways += 1
        try:
            pts = [(n.location.lat, n.location.lon) for n in w.nodes if n.location.valid()]
        except osmium.InvalidLocationError:
            return
        for (la1, lo1), (la2, lo2) in zip(pts, pts[1:]):
            mlat, mlon = (la1 + la2) / 2, (lo1 + lo2) / 2
            if not (LAT_MIN <= mlat <= LAT_MAX and LON_MIN <= mlon <= LON_MAX):
                continue
            bucket[mesh_index(mlat, mlon)] += haversine(la1, lo1, la2, lo2)


def main() -> None:
    h = RoadHandler()
    for pbf in PBFS:
        print(f"{pbf.name} から道路と駅を読む …")
        h.apply_file(str(pbf), locations=True, idx="flex_mem")
        print(f"  ここまで 道路 {h.ways:,} 本 / 駅 {len(h.stations):,}")
    print(f"  幹線 {sum(h.trunk_m.values())/1000:,.0f}km / "
          f"二次幹線 {sum(h.second_m.values())/1000:,.0f}km / "
          f"生活道路 {sum(h.local_m.values())/1000:,.0f}km")

    # 最寄り駅までの距離。福岡だけなら 645駅 x 11,385メッシュ = 730万回で
    # 総当たりでよかったが、全国は 9,100駅 x 471,024メッシュ = 43億回になり
    # Pythonのループでは数時間かかる。numpyで1,000メッシュずつまとめて計算する
    stations = h.stations
    rows = list(csv.DictReader((DATA / "mesh.csv").open(encoding="utf-8")))
    for r in rows:
        idx = (int(r["lat_i"]), int(r["lon_i"]))
        r["trunk_m"] = round(h.trunk_m.get(idx, 0.0))
        r["second_m"] = round(h.second_m.get(idx, 0.0))
        r["local_m"] = round(h.local_m.get(idx, 0.0))

    if stations:
        import numpy as np
        slat = np.array([s[0] for s in stations], dtype=float)
        slon = np.array([s[1] for s in stations], dtype=float)
        mlat = np.array([float(r["lat"]) for r in rows], dtype=float)
        mlon = np.array([float(r["lon"]) for r in rows], dtype=float)
        best = np.empty(len(rows))
        STEP = 1000
        for i in range(0, len(rows), STEP):
            la = mlat[i:i + STEP, None]
            lo = mlon[i:i + STEP, None]
            # 緯度1度=111km、経度1度=111km*cos(緯度)。日本の緯度範囲では平面近似で足りる
            dy = (slat[None, :] - la) * 111_000.0
            dx = (slon[None, :] - lo) * 111_000.0 * np.cos(np.radians(la))
            best[i:i + STEP] = np.sqrt(dy * dy + dx * dx).min(axis=1)
            if i % 50000 == 0:
                print(f"  最寄り駅 {i:,}/{len(rows):,}")
        for r, d in zip(rows, best):
            r["station_m"] = round(float(d))
    else:
        for r in rows:
            r["station_m"] = ""

    with (DATA / "mesh.csv").open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)

    # 店舗列の名前は環境で変わる（OSM時代は stores、いまは stores_fsq）。
    # 表示のためだけなので、無ければ集計を飛ばす
    key = next((k for k in ("stores_fsq", "stores") if rows and k in rows[0]), None)
    withstore = [r for r in rows if key and int(r[key] or 0) > 0]
    nostore = [r for r in rows if key and int(r[key] or 0) == 0]
    avg = lambda xs, k: sum(float(x[k]) for x in xs) / max(len(xs), 1)
    print(f"\n-> data/mesh.csv")
    print(f"   幹線道路の延長 平均: 店あり {avg(withstore,'trunk_m'):,.0f}m / "
          f"店なし {avg(nostore,'trunk_m'):,.0f}m")
    print(f"   最寄り駅まで   平均: 店あり {avg(withstore,'station_m'):,.0f}m / "
          f"店なし {avg(nostore,'station_m'):,.0f}m")


if __name__ == "__main__":
    main()
