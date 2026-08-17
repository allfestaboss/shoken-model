#!/usr/bin/env python3
"""候補地が「本物の余地」か「OSMの欠測」かを、現地のOSM密度で仕分ける。

前提: 北九州の候補地を見に行ったら、800m以内に shop 0件・建物32件だった。
      3x3に21,916人いるのに店ゼロなのではなく、**その一帯が描かれていない**だけ。
      一方、福岡市の候補地は建物5,872件が描かれた上でコンビニ1件だった。

だから候補ごとに「その場所がどれだけ描かれているか」を測る:
  - 建物の数（半径500m）
  - shop タグの数（半径500m）
建物がほとんど無ければ、店の不在は欠測であって余地ではない。

  python3 check_candidates.py [件数]   ->  data/candidates.csv
"""
import csv
import json
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path

DATA = Path(__file__).resolve().parent / "data"
ENDPOINT = "https://overpass-api.de/api/interpreter"
TOP_N = int(sys.argv[1]) if len(sys.argv) > 1 else 120

# 1候補につき1リクエストを投げるとレート制限に当たる（実際に35件目で止まった）。
# Overpass は1クエリに複数の out count を書けるので、**まとめて1回**にする。
BLOCK = """( node(around:500,{lat},{lon})["building"]; way(around:500,{lat},{lon})["building"]; ); out count;
( node(around:500,{lat},{lon})["shop"]; way(around:500,{lat},{lon})["shop"]; ); out count;
"""
CHUNK = 25          # 1リクエストあたりの候補数


def overpass(q: str) -> list:
    data = urllib.parse.urlencode({"data": q}).encode()
    for attempt in range(6):
        try:
            req = urllib.request.Request(ENDPOINT, data=data,
                                         headers={"User-Agent": "shoken-model/0.3 (research)"})
            with urllib.request.urlopen(req, timeout=600) as r:
                d = json.load(r)
            return [int(e["tags"]["total"]) for e in d.get("elements", [])
                    if e.get("type") == "count"]
        except Exception as e:  # noqa: BLE001
            if attempt == 5:
                print(f"    あきらめ: {e}")
                return []
            wait = 20 * (attempt + 1)
            print(f"    retry {attempt+1} in {wait}s: {e}")
            time.sleep(wait)
    return []


def main() -> None:
    rows = list(csv.DictReader((DATA / "mesh_pred.csv").open(encoding="utf-8")))
    cand = [r for r in rows if int(r["stores"]) == 0]
    cand.sort(key=lambda r: -float(r["deficit_r1"]))
    cand = cand[:TOP_N]
    print(f"上位 {len(cand)} 候補を現地照合する\n")

    out = []
    for start in range(0, len(cand), CHUNK):
        chunk = cand[start:start + CHUNK]
        q = "[out:json][timeout:600];\n" + "".join(
            BLOCK.format(lat=r["lat"], lon=r["lon"]) for r in chunk)
        counts = overpass(q)
        if len(counts) < 2 * len(chunk):
            print(f"  {start+1}-{start+len(chunk)}: 取得できず（{len(counts)}個しか返らず）")
            continue
        for j, r in enumerate(chunk):
            buildings, shops = counts[2 * j], counts[2 * j + 1]
            pop_r1 = float(r["pop_r1"])
            # 建物が少ない＝そもそも描かれていない。人口がいるのに建物が無いのは決定的
            mapped = buildings >= 200 or (buildings >= 50 and pop_r1 < 5000)
            out.append({**{k: r[k] for k in ("lat", "lon", "city", "pop2020", "pop_r1",
                                             "build_share", "exp_r1", "deficit_r1")},
                        "osm_buildings": buildings, "osm_shops": shops,
                        "mapped": int(mapped)})
            print(f"  {start+j+1:3}/{len(cand)} {r['lat']},{r['lon']} 建物{buildings:>5} "
                  f"店{shops:>3} 3x3人口{pop_r1:>7.0f} 不足{float(r['deficit_r1']):.1f}  "
                  f"{'本物候補' if mapped else '欠測の疑い'}")
        time.sleep(8)     # まとめた分、間隔は長めに取る

    path = DATA / "candidates.csv"
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(out[0].keys()))
        w.writeheader()
        w.writerows(out)

    real = [r for r in out if r["mapped"]]
    print(f"\n-> {path}")
    print(f"   本物候補 {len(real)} / 欠測の疑い {len(out)-len(real)}")
    print("\n■ 篩ったあとの上位10（描かれている場所だけ）")
    for r in sorted(real, key=lambda r: -float(r["deficit_r1"]))[:10]:
        print(f"   {r['lat']},{r['lon']}  市町村{r['city']}  "
              f"3x3人口 {float(r['pop_r1']):>7.0f}  建物 {r['osm_buildings']:>5}  "
              f"店 {r['osm_shops']:>3}  不足 {float(r['deficit_r1']):.1f}")


if __name__ == "__main__":
    main()
