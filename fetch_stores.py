#!/usr/bin/env python3
"""福岡県の市区町村別コンビニ店舗数を OpenStreetMap（Overpass API）から数える。

キー不要。ただし **OSM の網羅率は業態によって全く違う**。試した範囲では
コンビニ（shop=convenience）はよく整備されているが、スーパー・ドラッグストアは
ほぼ入っていない（宇美町で supermarket 0 件）。だから v0 はコンビニ1業種に絞る。

網羅率そのものは、県計を外部の公表値と突き合わせて測る（check_coverage.py）。

  python3 fetch_stores.py   ->  data/stores_convenience.csv
"""
import csv
import json
import time
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent
DATA = ROOT / "data"
ENDPOINT = "https://overpass-api.de/api/interpreter"
PREF = "福岡県"

QUERY = """
[out:json][timeout:180];
area["name"="{pref}"]["admin_level"="4"]->.pref;
area["name"="{name}"]["admin_level"="7"](area.pref)->.m;
( node(area.m)["shop"="convenience"]; way(area.m)["shop"="convenience"]; ); out count;
"""


def overpass(query: str) -> dict:
    data = urllib.parse.urlencode({"data": query}).encode()
    for attempt in range(5):
        try:
            req = urllib.request.Request(ENDPOINT, data=data,
                                         headers={"User-Agent": "shoken-model/0.1 (research)"})
            with urllib.request.urlopen(req, timeout=180) as r:
                return json.load(r)
        except Exception as e:  # noqa: BLE001
            if attempt == 4:
                raise
            wait = 5 * (attempt + 1)
            print(f"    retry {attempt+1} in {wait}s: {e}")
            time.sleep(wait)
    return {}


def main() -> None:
    muni = list(csv.DictReader((DATA / "population.csv").open(encoding="utf-8")))
    rows, missing = [], []

    for i, m in enumerate(muni, 1):
        d = overpass(QUERY.format(pref=PREF, name=m["name"]))
        counts = [e for e in d.get("elements", []) if e.get("type") == "count"]
        if not counts:
            missing.append(m["name"])
            print(f"  {i:2}/60 {m['name']:8} 取得できず")
            continue
        n = int(counts[0]["tags"]["total"])
        rows.append({"code": m["code"], "name": m["name"], "kind": m["kind"],
                     "pop": int(m["pop"]), "stores": n})
        print(f"  {i:2}/60 {m['name']:8} 人口 {int(m['pop']):>9,}  店 {n:>4}")
        time.sleep(1.2)          # Overpass への礼儀

    path = DATA / "stores_convenience.csv"
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=["code", "name", "kind", "pop", "stores"])
        w.writeheader()
        w.writerows(rows)

    tot_p = sum(r["pop"] for r in rows)
    tot_s = sum(r["stores"] for r in rows)
    print(f"\n-> {path}  {len(rows)}件")
    print(f"   人口 {tot_p:,} / 店舗 {tot_s:,} = 1店あたり {tot_p/tot_s:,.0f} 人")
    if missing:
        print(f"   !! 名前が一致しなかった: {'、'.join(missing)}")


if __name__ == "__main__":
    main()
