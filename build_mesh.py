#!/usr/bin/env python3
"""500mメッシュのデータセットを作る（市町村単位をやめて、商圏の大きさに単位を合わせる）。

市町村は現象の単位より2〜3桁大きい（福岡市343km²に対し、コンビニ商圏は半径500m）。
だから残差が「不足」を意味しようがなかった。単位をメッシュに落とす。

  需要側: 国土数値情報「500mメッシュ別将来推計人口」（2015〜2050年、平成27年国調ベース）
  供給側: OSM のコンビニ点データ（緯度経度）

**メッシュIDは緯度経度から直接計算できる**ので、境界データもポリゴン判定も要らない:
  lat_idx = floor(緯度 × 240) / lon_idx = floor((経度-100) × 160)
  これは4次メッシュ（500m）の行・列そのもの。

  python3 build_mesh.py   ->  data/mesh.csv, data/stores_points.json
"""
import csv
import json
import math
import urllib.parse
import urllib.request
from collections import defaultdict
from pathlib import Path

from fetch_postoffices import read_dbf

ROOT = Path(__file__).resolve().parent
DATA = ROOT / "data"
MESH_DBF = DATA / "mlit" / "500m_mesh_2018_40.dbf"
ENDPOINT = "https://overpass-api.de/api/interpreter"

QUERY = """
[out:json][timeout:300];
area["name"="福岡県"]["admin_level"="4"]->.pref;
( node(area.pref)["shop"="convenience"]; way(area.pref)["shop"="convenience"]; );
out center tags;
"""


def mesh_index(lat: float, lon: float) -> tuple:
    """緯度経度 -> 4次メッシュ（500m）の行・列。"""
    return math.floor(lat * 240), math.floor((lon - 100) * 160)


def mesh_id_to_index(mesh_id: str) -> tuple:
    p, u = int(mesh_id[0:2]), int(mesh_id[2:4])
    q, v = int(mesh_id[4]), int(mesh_id[5])
    r, w = int(mesh_id[6]), int(mesh_id[7])
    m = int(mesh_id[8])
    lat_i = ((p * 8 + q) * 10 + r) * 2 + (1 if m in (3, 4) else 0)
    lon_i = ((u * 8 + v) * 10 + w) * 2 + (1 if m in (2, 4) else 0)
    return lat_i, lon_i


def mesh_center(lat_i: int, lon_i: int) -> tuple:
    return (lat_i + .5) / 240, 100 + (lon_i + .5) / 160


def fetch_stores() -> list:
    cache = DATA / "stores_points.json"
    if cache.exists():
        return json.loads(cache.read_text(encoding="utf-8"))
    data = urllib.parse.urlencode({"data": QUERY}).encode()
    req = urllib.request.Request(ENDPOINT, data=data,
                                 headers={"User-Agent": "shoken-model/0.2 (research)"})
    with urllib.request.urlopen(req, timeout=300) as r:
        els = json.load(r)["elements"]
    pts = []
    for e in els:
        lat = e.get("lat") or (e.get("center") or {}).get("lat")
        lon = e.get("lon") or (e.get("center") or {}).get("lon")
        if lat is None or lon is None:
            continue
        t = e.get("tags", {})
        pts.append({"lat": lat, "lon": lon,
                    "brand": t.get("brand") or t.get("name") or ""})
    cache.write_text(json.dumps(pts, ensure_ascii=False), encoding="utf-8")
    return pts


def main() -> None:
    print("メッシュ人口を読む")
    rows = read_dbf(MESH_DBF)
    pop = {}
    shicode = {}
    for r in rows:
        idx = mesh_id_to_index(r["MESH_ID"])
        pop[idx] = {y: float(r.get(f"PTN_{y}") or 0)
                    for y in ("2020", "2030", "2040", "2050")}
        shicode[idx] = r["SHICODE"]
    print(f"  {len(pop):,} メッシュ / 2020年人口 {sum(v['2020'] for v in pop.values()):,.0f}人")

    print("店舗の点データを取る")
    stores = fetch_stores()
    counts = defaultdict(int)
    outside = 0
    for s in stores:
        idx = mesh_index(s["lat"], s["lon"])
        if idx in pop:
            counts[idx] += 1
        else:
            outside += 1              # 人口0で推計対象外のメッシュ（海上・山林）に落ちた店
    print(f"  {len(stores):,} 店 / メッシュに載った {sum(counts.values()):,} / "
          f"人口メッシュ外 {outside}")

    ctx = {r["code"]: r for r in csv.DictReader((DATA / "context.csv").open(encoding="utf-8"))}

    # 近傍の人口（店は隣のメッシュからも客を集める）
    def ring_sum(idx, rad):
        la, lo = idx
        return sum(pop.get((la + i, lo + j), {}).get("2020", 0)
                   for i in range(-rad, rad + 1) for j in range(-rad, rad + 1))

    out = []
    for idx, p in pop.items():
        la, lo = idx
        lat, lon = mesh_center(la, lo)
        s = shicode.get(idx, "")
        # 政令市の区コード -> 市コード（context.csv は市単位）。
        # 福岡市の区は 4013x なので、401x を先に見ると北九州市に化ける。順序が命。
        if s.startswith("4013"):
            city = "40130"            # 福岡市（40131-40137）
        elif s.startswith("401"):
            city = "40100"            # 北九州市（40101-40109）
        else:
            city = s
        c = ctx.get(city, {})
        r1 = ring_sum(idx, 1)
        r2 = ring_sum(idx, 2)
        out.append({
            "lat_i": la, "lon_i": lo, "lat": round(lat, 6), "lon": round(lon, 6),
            "shicode": s, "city": city,
            "pop2020": round(p["2020"], 1), "pop2030": round(p["2030"], 1),
            "pop2040": round(p["2040"], 1), "pop2050": round(p["2050"], 1),
            "pop_r1": round(r1, 1),          # 3x3（およそ1.5km四方）
            "pop_r2": round(r2, 1),          # 5x5（およそ2.5km四方）
            "day_night": float(c.get("day_night_ratio") or 100),
            "stores": counts.get(idx, 0),
        })

    path = DATA / "mesh.csv"
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(out[0].keys()))
        w.writeheader()
        w.writerows(out)

    withs = sum(1 for r in out if r["stores"] > 0)
    print(f"\n-> {path}")
    print(f"   店のあるメッシュ {withs:,} / {len(out):,}（{withs/len(out):.1%}）")
    print(f"   人口>0のメッシュ {sum(1 for r in out if r['pop2020']>0):,}")


if __name__ == "__main__":
    main()
