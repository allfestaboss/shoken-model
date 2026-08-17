#!/usr/bin/env python3
"""地形と歴史の目印をメッシュに載せる。個店の集積が何で起きているかを探るため。

チェーンの集積はドミナント出店（企業の戦略）だと分かった。個店の集積は別の現象で、
新しい個店は個店の近くに出て、チェーンを避ける。ではその個店の集まりは
どこにできているのか。門前町、駅前、港町、城下町、温泉街——
どれも「昔からそこに人が集まる理由があった場所」で、人口や道路では表せない。

OSMの地域抽出はすでに手元にあるので、追加のダウンロードなしで取り出せる:

  神社 / 寺        門前町。参道に店が並ぶ
  城跡             城下町。町割りごと残っていることが多い
  温泉             温泉街。旅館と土産物と飲食が固まる
  港               港町
  歩行者専用道路     アーケード商店街はこれで引かれていることが多い
  商業用地          OSMの landuse=retail
  学校             通学路の商店

  .venv-osm/bin/python add_historic.py   ->  data/mesh.csv に列を追加
"""
import csv
import math
from collections import defaultdict
from pathlib import Path

import osmium

from region import bbox

ROOT = Path(__file__).resolve().parent
DATA = ROOT / "data"
PBFS = sorted((DATA / "osm").glob("*-latest.osm.pbf"))
LAT_MIN, LAT_MAX, LON_MIN, LON_MAX = bbox()

COLS = ["h_shinto", "h_temple", "h_castle", "h_onsen", "h_harbour",
        "h_pedest_m", "h_retail", "h_school"]


def mesh_index(lat, lon):
    return math.floor(lat * 240), math.floor((lon - 100) * 160)


def haversine(lat1, lon1, lat2, lon2) -> float:
    dy = (lat2 - lat1) * 111_000.0
    dx = (lon2 - lon1) * 111_000.0 * math.cos(math.radians((lat1 + lat2) / 2))
    return math.hypot(dx, dy)


class Handler(osmium.SimpleHandler):
    def __init__(self):
        super().__init__()
        self.count = defaultdict(lambda: defaultdict(int))
        self.pedest = defaultdict(float)
        self.n = 0

    def _mark(self, lat, lon, tags):
        if not (LAT_MIN <= lat <= LAT_MAX and LON_MIN <= lon <= LON_MAX):
            return
        idx = mesh_index(lat, lon)
        g = self.count[idx]
        rel = tags.get("religion", "")
        if tags.get("amenity") == "place_of_worship":
            if rel == "shinto":
                g["h_shinto"] += 1
            elif rel == "buddhist":
                g["h_temple"] += 1
        if tags.get("historic") in ("castle", "ruins") or tags.get("castle_type"):
            g["h_castle"] += 1
        if (tags.get("natural") == "hot_spring" or tags.get("amenity") == "public_bath"
                or tags.get("bath:type") == "onsen"):
            g["h_onsen"] += 1
        if (tags.get("harbour") == "yes" or tags.get("landuse") == "harbour"
                or tags.get("amenity") == "ferry_terminal"):
            g["h_harbour"] += 1
        if tags.get("landuse") == "retail" or tags.get("shop") == "mall":
            g["h_retail"] += 1
        if tags.get("amenity") in ("school", "university", "college"):
            g["h_school"] += 1
        self.n += 1

    def node(self, n):
        self._mark(n.location.lat, n.location.lon, n.tags)

    def way(self, w):
        t = w.tags
        try:
            if t.get("highway") == "pedestrian":
                # アーケード商店街。長さで測る
                prev = None
                for nd in w.nodes:
                    cur = (nd.location.lat, nd.location.lon)
                    if prev:
                        d = haversine(prev[0], prev[1], cur[0], cur[1])
                        mlat, mlon = (prev[0] + cur[0]) / 2, (prev[1] + cur[1]) / 2
                        if LAT_MIN <= mlat <= LAT_MAX and LON_MIN <= mlon <= LON_MAX:
                            self.pedest[mesh_index(mlat, mlon)] += d
                    prev = cur
            if any(k in t for k in ("amenity", "historic", "landuse", "natural",
                                    "harbour", "shop", "castle_type")):
                nd = w.nodes[0]
                self._mark(nd.location.lat, nd.location.lon, t)
        except osmium.InvalidLocationError:
            pass


def main() -> None:
    h = Handler()
    for pbf in PBFS:
        print(f"{pbf.name} を読む …", flush=True)
        h.apply_file(str(pbf), locations=True, idx="flex_mem")
        print(f"  ここまで 目印のあるマス {len(h.count):,}", flush=True)

    rows = list(csv.DictReader((DATA / "mesh.csv").open(encoding="utf-8")))
    for r in rows:
        idx = (int(r["lat_i"]), int(r["lon_i"]))
        g = h.count.get(idx, {})
        for c in COLS:
            if c != "h_pedest_m":
                r[c] = g.get(c, 0)
        r["h_pedest_m"] = round(h.pedest.get(idx, 0.0))

    with (DATA / "mesh.csv").open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)

    print("\n-> data/mesh.csv")
    print(f"{'目印':<14}{'総数':>10}{'マス数':>10}")
    for c in COLS:
        v = [float(r[c]) for r in rows]
        print(f"{c:<14}{sum(v):>10,.0f}{sum(1 for x in v if x):>10,}")


if __name__ == "__main__":
    main()
