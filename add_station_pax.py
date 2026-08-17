#!/usr/bin/env python3
"""メッシュに駅の乗降客数を足す。

これまで駅は「最寄り駅までの距離」しか入れていなかった。つまり博多駅も無人駅も
同じ扱いだった。実際には駅の大きさで人流が2桁違う（博多 253,252人/日 に対し
小さな駅は数百人）。飲食店のように人流で決まる業種では、この差が本質になるはず。

出所: 国土数値情報 S12 駅別乗降客数（全国10,482駅）
      https://nlftp.mlit.go.jp/ksj/gml/data/S12/S12-22/S12-22_GML.zip
      年次は S12_041 = 2019年（平常時）を使う。最新の S12_049 は令和3年で
      コロナの影響が大きく（博多 253,252 -> 93,823）、平常の駅の大きさを表さない。

  pax_near … 最寄り駅の乗降客数
  pax_grav … Σ 乗降客数 / 距離^2（3km以内）。そこに届く鉄道人流の総量
  pax_r2   … 1km以内の駅の乗降客数の合計

  python3 add_station_pax.py   ->  data/mesh.csv に列を追加
"""
import csv
import json
import math
from pathlib import Path

ROOT = Path(__file__).resolve().parent
DATA = ROOT / "data"
SRC = DATA / "mlit" / "S12" / "UTF-8" / "S12-22_NumberOfPassengers.geojson"
YEAR_FIELD = "S12_041"          # 2019年（平常時）
RADIUS_KM = 3.0
FLOOR_KM = 0.15                 # 駅の真上で発散しないための下限


def load_stations() -> list:
    out = []
    for f in json.load(SRC.open(encoding="utf-8"))["features"]:
        p = f["properties"]
        s = str(p.get(YEAR_FIELD) or "").strip()
        if not s.isdigit() or int(s) <= 0:
            continue
        coords = f["geometry"]["coordinates"]
        if f["geometry"]["type"] == "LineString":
            lon = sum(c[0] for c in coords) / len(coords)
            lat = sum(c[1] for c in coords) / len(coords)
        else:
            lon, lat = coords[0], coords[1]
        if not (32.9 <= lat <= 34.1 and 129.8 <= lon <= 131.4):
            continue
        out.append((lat, lon, int(s), p.get("S12_001", "")))
    return out


def main() -> None:
    st = load_stations()
    print(f"福岡県周辺の駅 {len(st):,}（乗降客数あり・事業者ごとに1件）")
    top = sorted(st, key=lambda t: -t[2])[:5]
    for la, lo, v, name in top:
        print(f"   {name:<14}{v:>9,} 人/日")

    rows = list(csv.DictReader((DATA / "mesh.csv").open(encoding="utf-8")))
    for r in rows:
        lat, lon = float(r["lat"]), float(r["lon"])
        near_d, near_v, grav, r2 = 9e9, 0, 0.0, 0
        for la, lo, v, _ in st:
            dy = (la - lat) * 111.0
            dx = (lo - lon) * 92.3
            d = math.hypot(dy, dx)
            if d > RADIUS_KM:
                continue
            grav += v / max(d, FLOOR_KM) ** 2
            if d <= 1.0:
                r2 += v
            if d < near_d:
                near_d, near_v = d, v
        r["pax_near"] = near_v
        r["pax_grav"] = round(grav)
        r["pax_r2"] = r2

    with (DATA / "mesh.csv").open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)

    has = sum(1 for r in rows if int(r["pax_grav"]) > 0)
    print(f"\n-> data/mesh.csv （3km以内に駅があるメッシュ {has:,}/{len(rows):,}）")


if __name__ == "__main__":
    main()
