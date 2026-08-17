#!/usr/bin/env python3
"""年齢が効くはずの業種を取って、メッシュに載せる。

3業態（コンビニ・ドラッグ・スーパー）では年齢構成を足しても精度が動かなかった。
全世代が使う店だから当然で、**年齢が効くかどうかは業種を選ばないと分からない**。
そこで両極端を取る:

  保育園・幼稚園  … 需要は 0-4歳。これで効かなければ年齢は使えない
  学習塾         … 5-19歳
  病院・歯科      … 高齢
  パン屋         … 対照（特に年齢依存が無さそうな業種）

  .venv-duck/bin/python fetch_more_types.py   ->  data/mesh.csv に列を追加
"""
import csv
import math
from collections import defaultdict
from pathlib import Path

import duckdb

ROOT = Path(__file__).resolve().parent
DATA = ROOT / "data"
TOKEN = Path.home().joinpath(".config/foursquare/token").read_text().strip()

# 列名 -> FSQ のカテゴリラベルに含まれる文字列
TYPES = {
    "nursery": "Nursery School",
    "preschool": "Preschool",
    "juku": "Tutoring Service",
    "hospital": "Hospital",
    "dentist": "Dentist",
    "clinic": "Doctor's Office",
    "bakery": "Bakery",
}


def mesh_index(lat, lon):
    return math.floor(lat * 240), math.floor((lon - 100) * 160)


def main() -> None:
    con = duckdb.connect()
    con.execute("INSTALL httpfs; LOAD httpfs; INSTALL iceberg; LOAD iceberg;")
    con.execute(f"CREATE SECRET s (TYPE ICEBERG, TOKEN '{TOKEN}');")
    con.execute("""ATTACH 'places' AS places (TYPE iceberg, SECRET s,
                   ENDPOINT 'https://catalog.h3-hub.foursquare.com/iceberg');""")

    # ラベルにアポストロフィが入るもの（Doctor's Office）があるのでエスケープする
    cond = " OR ".join(f"cat ILIKE '%{v.replace(chr(39), chr(39)*2)}%'" for v in TYPES.values())
    q = f"""
    SELECT lat, lon, cat FROM (
      SELECT latitude AS lat, longitude AS lon,
             array_to_string(fsq_category_labels,' | ') AS cat
      FROM places.datasets.places_os
      WHERE latitude BETWEEN 32.95 AND 34.05 AND longitude BETWEEN 129.85 AND 131.30
        AND date_closed IS NULL)
    WHERE {cond}
    """
    print("Foursquare から取得中 …")
    rows = con.execute(q).fetchall()
    print(f"  {len(rows):,} 件")

    grids = {k: defaultdict(int) for k in TYPES}
    for lat, lon, cat in rows:
        idx = mesh_index(lat, lon)
        for key, label in TYPES.items():
            if label.lower() in (cat or "").lower():
                grids[key][idx] += 1
                break            # 最初に当たった分類だけに数える（重複計上を避ける）

    mesh = list(csv.DictReader((DATA / "mesh.csv").open(encoding="utf-8")))
    for r in mesh:
        idx = (int(r["lat_i"]), int(r["lon_i"]))
        for key in TYPES:
            r[key] = grids[key].get(idx, 0)
    # 保育園と幼稚園は同じ需要（就学前）なのでまとめた列も持たせる
    for r in mesh:
        r["childcare"] = int(r["nursery"]) + int(r["preschool"])

    with (DATA / "mesh.csv").open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(mesh[0].keys()))
        w.writeheader()
        w.writerows(mesh)

    print(f"\n-> data/mesh.csv")
    print(f"{'業種':<12}{'店舗数':>8}{'メッシュ数':>10}")
    for key in list(TYPES) + ["childcare"]:
        n = sum(int(r[key]) for r in mesh)
        m = sum(1 for r in mesh if int(r[key]) > 0)
        print(f"{key:<12}{n:>8,}{m:>10,}")


if __name__ == "__main__":
    main()
