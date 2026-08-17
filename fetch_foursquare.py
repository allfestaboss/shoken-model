#!/usr/bin/env python3
"""Foursquare OS Places（3ソース目）から福岡県の店舗を取る。

Places Portal で発行したトークンで Iceberg カタログに接続する。
  ENDPOINT: https://catalog.h3-hub.foursquare.com/iceberg
  テーブル : places.datasets.places_os

■ Overture より優れている点
  **date_closed（閉店日）を持っている。** Overture のコンビニは公表値の1.36倍あり、
  閉店跡が混ざっている疑いがあった。ここで営業中だけに絞れる。

トークンは ~/.config/foursquare/token（600）から読む。コードにも出力にも出さない。

  .venv-duck/bin/python fetch_foursquare.py   ->  data/fsq_places.csv
"""
import csv
import math
from pathlib import Path

import duckdb

from region import bboxes

ROOT = Path(__file__).resolve().parent
DATA = ROOT / "data"
TOKEN = Path.home().joinpath(".config/foursquare/token").read_text().strip()

# 範囲は data/mesh.csv から作る（県を足したときの直し忘れを防ぐ）
BOXES = bboxes()

# FSQ のカテゴリラベルは "Retail > Convenience Store" のような階層文字列
WANTED = {
    "convenience_store": "Convenience Store",
    "pharmacy": "Pharmacy",
    "drugstore": "Drugstore",
    "supermarket": "Supermarket",
}


def mesh_index(lat: float, lon: float) -> tuple:
    return math.floor(lat * 240), math.floor((lon - 100) * 160)


def connect() -> duckdb.DuckDBPyConnection:
    con = duckdb.connect()
    con.execute("INSTALL httpfs; LOAD httpfs; INSTALL iceberg; LOAD iceberg;")
    con.execute(f"CREATE SECRET iceberg_secret (TYPE ICEBERG, TOKEN '{TOKEN}');")
    con.execute("""ATTACH 'places' AS places (TYPE iceberg, SECRET iceberg_secret,
                   ENDPOINT 'https://catalog.h3-hub.foursquare.com/iceberg');""")
    return con


def main() -> None:
    con = connect()
    like = " OR ".join(
        f"list_contains(fsq_category_labels, '{v}') "
        f"OR array_to_string(fsq_category_labels, '|') ILIKE '%{v}%'"
        for v in WANTED.values())
    q = """
    SELECT fsq_place_id, name, latitude AS lat, longitude AS lon,
           locality, region, date_created, date_refreshed, date_closed,
           array_to_string(fsq_category_labels, ' | ') AS cats
    FROM places.datasets.places_os
    WHERE latitude BETWEEN {la0} AND {la1}
      AND longitude BETWEEN {lo0} AND {lo1}
      AND ({like})
    """
    rows, cols = [], None
    for pref, (la0, la1, lo0, lo1) in BOXES.items():
        print(f"Foursquare から {pref} を抜く …")
        cur = con.execute(q.format(la0=la0, la1=la1, lo0=lo0, lo1=lo1, like=like))
        got = cur.fetchall()
        cols = [d[0] for d in cur.description]
        rows += got
        print(f"  {len(got):,} 件")
    # 県ごとの箱は隣県と重なるので、同じ店が複数回returnされる。
    # IDで一意化しないと重複が店舗数に化ける（福岡が3,589→4,499に膨らんだ）
    idcol = cols.index("fsq_place_id")
    seen, uniq = set(), []
    for r in rows:
        if r[idcol] in seen:
            continue
        seen.add(r[idcol])
        uniq.append(r)
    print(f"  合計 {len(rows):,} 件 -> 重複を除いて {len(uniq):,} 件")
    rows = uniq

    mesh = {(int(r["lat_i"]), int(r["lon_i"]))
            for r in csv.DictReader((DATA / "mesh.csv").open(encoding="utf-8"))}

    out = []
    for r in rows:
        d = dict(zip(cols, r))
        idx = mesh_index(d["lat"], d["lon"])
        if idx not in mesh:
            continue
        cats = (d["cats"] or "")
        for key, label in WANTED.items():
            if label.lower() in cats.lower():
                d["category"] = key
                break
        else:
            continue
        d["lat_i"], d["lon_i"] = idx
        d["closed"] = 1 if d["date_closed"] else 0
        out.append(d)

    path = DATA / "fsq_places.csv"
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(out[0].keys()))
        w.writeheader()
        w.writerows(out)

    from collections import Counter
    live = [d for d in out if not d["closed"]]
    c_all, c_live = Counter(d["category"] for d in out), Counter(d["category"] for d in live)
    print(f"\n-> {path}  福岡県のメッシュ内 {len(out):,} 件（うち営業中 {len(live):,}）")
    print(f"{'業態':<20}{'全部':>8}{'営業中':>8}{'閉店':>8}")
    for k in WANTED:
        print(f"{k:<20}{c_all.get(k,0):>8,}{c_live.get(k,0):>8,}{c_all.get(k,0)-c_live.get(k,0):>8,}")
    print("\n出典: Foursquare OS Places (Apache License 2.0)")


if __name__ == "__main__":
    main()
