#!/usr/bin/env python3
"""開店の住所を座標にする（国土地理院・無料・キー不要）。

2,694件あるので1件1秒で45分ほどかかる。途中で止めても次回は続きから走る
（結果を都度ファイルに書き足す）。

住所には県名が入っていないので、PDFのファイル名から県名を前置する。
ここを間違えると別の県で誤ヒットして、静かに間違った座標が入る。

  python3 geocode_openings.py   ->  data/openings_all_geo.csv
"""
import csv
import json
import math
import time
import urllib.parse
import urllib.request
from pathlib import Path

from prefs import JP

ROOT = Path(__file__).resolve().parent
DATA = ROOT / "data"
SRC = DATA / "openings_all.csv"
# 旧・福岡3業態用の openings_all_geo.csv とは列が違うので別ファイルにする
OUT = DATA / "openings_national_geo.csv"
GSI = "https://msearch.gsi.go.jp/address-search/AddressSearch?q="
UA = "shoken-model/0.5 (research; boss@allfesta.com)"
FIELDS = ["pref", "pref_code", "cat", "date", "shop", "addr", "lat", "lon", "lat_i", "lon_i"]


def mesh_index(lat, lon):
    return math.floor(lat * 240), math.floor((lon - 100) * 160)


def main() -> None:
    rows = list(csv.DictReader(SRC.open(encoding="utf-8")))
    done = {}
    if OUT.exists():
        for r in csv.DictReader(OUT.open(encoding="utf-8")):
            done[(r["pref"], r["shop"], r["addr"])] = r
    print(f"対象 {len(rows):,} 件 / 既に座標あり {len(done):,}")

    f = OUT.open("a" if done else "w", newline="", encoding="utf-8")
    w = csv.DictWriter(f, fieldnames=FIELDS, extrasaction="ignore")
    if not done:
        w.writeheader()

    ok = miss = 0
    for i, r in enumerate(rows, 1):
        k = (r["pref"], r["shop"], r["addr"])
        if k in done:
            continue
        q = GSI + urllib.parse.quote(JP[r["pref"]] + r["addr"])
        try:
            req = urllib.request.Request(q, headers={"User-Agent": UA})
            with urllib.request.urlopen(req, timeout=30) as resp:
                d = json.load(resp)
            if d:
                c = d[0]["geometry"]["coordinates"]
                la, lo = mesh_index(float(c[1]), float(c[0]))
                w.writerow({**r, "lat": c[1], "lon": c[0], "lat_i": la, "lon_i": lo})
                f.flush()
                ok += 1
            else:
                miss += 1
        except Exception:  # noqa: BLE001
            miss += 1
        time.sleep(1.0)
        if i % 200 == 0:
            print(f"  {i}/{len(rows)}  座標化 {ok:,} / 取れず {miss:,}")

    f.close()
    print(f"\n-> {OUT}  新たに座標化 {ok:,} / 取れず {miss:,}")


if __name__ == "__main__":
    main()
