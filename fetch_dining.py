#!/usr/bin/env python3
"""飲食店を「昼の店」と「夜の店」に分けてメッシュに載せる。

飲食は、これまでの3業態（コンビニ・ドラッグ・スーパー）と需要の出どころが違うはず。
居酒屋の客は住民でも昼間の従業者でもなく、**夜そこにいる人**。
そこで一括りにせず、営業時間帯で分けて別々にモデルを当てる。

  bar        … Bar / Sake Bar（居酒屋）。夜
  restaurant … Restaurant 系。昼と夜の両方
  cafe       … Cafe / Coffee / Dessert。昼
  dining     … 上記すべての合計

分けること自体が仮説の検定になる。同じ場所の条件で当たり方が変わるなら、
「飲食」でひとくくりにする粒度が粗すぎたということ。

  .venv-duck/bin/python fetch_dining.py   ->  data/mesh.csv に列を追加
"""
import csv
import math
from collections import defaultdict
from pathlib import Path

import duckdb

from region import bboxes

ROOT = Path(__file__).resolve().parent
DATA = ROOT / "data"
TOKEN = Path.home().joinpath(".config/foursquare/token").read_text().strip()
BOXES = bboxes()


def kind(cat: str) -> str:
    """FSQ の分類ラベルを、営業時間帯の近い3つに振り分ける。"""
    if "> Bar" in cat:
        return "bar"
    if "Cafe, Coffee, and Tea House" in cat or "Dessert Shop" in cat:
        return "cafe"
    if "> Restaurant" in cat:
        return "restaurant"
    return ""


def mesh_index(lat, lon):
    return math.floor(lat * 240), math.floor((lon - 100) * 160)


def main() -> None:
    con = duckdb.connect()
    con.execute("INSTALL httpfs; LOAD httpfs; INSTALL iceberg; LOAD iceberg;")
    con.execute(f"CREATE SECRET s (TYPE ICEBERG, TOKEN '{TOKEN}');")
    con.execute("""ATTACH 'places' AS places (TYPE iceberg, SECRET s,
                   ENDPOINT 'https://catalog.h3-hub.foursquare.com/iceberg');""")

    q = """
        SELECT id, lat, lon, cat FROM (
          SELECT fsq_place_id AS id, latitude AS lat, longitude AS lon,
                 fsq_category_labels[1] AS cat
          FROM places.datasets.places_os
          WHERE latitude BETWEEN {la0} AND {la1}
            AND longitude BETWEEN {lo0} AND {lo1}
            AND date_closed IS NULL AND fsq_category_labels IS NOT NULL)
        WHERE cat ILIKE 'Dining and Drinking%'
    """
    seen, rows = set(), []
    for pref, (la0, la1, lo0, lo1) in BOXES.items():
        print(f"Foursquare から {pref} の飲食店を取得中 …")
        got = con.execute(q.format(la0=la0, la1=la1, lo0=lo0, lo1=lo1)).fetchall()
        # 県ごとの箱は隣県と重なるので、IDで一意化してから数える
        new = [g for g in got if g[0] not in seen]
        seen.update(g[0] for g in got)
        rows += [(g[1], g[2], g[3]) for g in new]
        print(f"  {len(got):,} 件（新規 {len(new):,}）")
    print(f"  合計 {len(rows):,} 件")

    grids = defaultdict(lambda: defaultdict(int))
    for lat, lon, cat in rows:
        k = kind(cat or "")
        if not k:
            continue
        idx = mesh_index(lat, lon)
        grids[k][idx] += 1
        grids["dining"][idx] += 1

    mesh = list(csv.DictReader((DATA / "mesh.csv").open(encoding="utf-8")))
    for r in mesh:
        idx = (int(r["lat_i"]), int(r["lon_i"]))
        for k in ("bar", "restaurant", "cafe", "dining"):
            r[k] = grids[k].get(idx, 0)

    with (DATA / "mesh.csv").open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(mesh[0].keys()))
        w.writeheader()
        w.writerows(mesh)

    print(f"\n-> data/mesh.csv")
    print(f"{'区分':<12}{'店舗数':>9}{'メッシュ数':>10}{'最大/メッシュ':>12}")
    for k in ("bar", "restaurant", "cafe", "dining"):
        n = sum(int(r[k]) for r in mesh)
        m = sum(1 for r in mesh if int(r[k]) > 0)
        mx = max(int(r[k]) for r in mesh)
        print(f"{k:<12}{n:>9,}{m:>10,}{mx:>12,}")


if __name__ == "__main__":
    main()
