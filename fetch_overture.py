#!/usr/bin/env python3
"""Overture Maps の Places から、福岡県の店舗を取る。

■ なぜこれを使うか
  チェーン公式サイトは3社とも自動取得を技術的に拒否している（WAF / reCAPTCHA）。
  OSMは小売の1〜2割しか拾えていない。
  Overture Maps は Meta・Microsoft 等が出資する財団が公開する POI データで、
  **CDLA-Permissive-2.0**（再配布・商用利用可、帰属表示のみ）。S3から直接クエリできる。
  スクレイピングにあたらず、規約上も明快。

■ 効き方
  DuckDB の httpfs で S3 上の GeoParquet を直接読む。bbox で絞れば数秒で返る
  （全球のPOIから福岡県ぶんだけを、ダウンロードせずに抜ける）。

  .venv-duck/bin/python fetch_overture.py   ->  data/overture_places.csv
"""
import csv
import math
from pathlib import Path

import duckdb

ROOT = Path(__file__).resolve().parent
DATA = ROOT / "data"
RELEASE = "2026-07-22.0"
BASE = f"s3://overturemaps-us-west-2/release/{RELEASE}/theme=places/type=place/*"

LAT_MIN, LAT_MAX = 32.95, 34.05
LON_MIN, LON_MAX = 129.85, 131.30

# 取りたい業態（Overture のカテゴリ名）
CATEGORIES = ["convenience_store", "pharmacy", "drugstore", "grocery_store",
              "supermarket", "fast_food_restaurant"]


def mesh_index(lat: float, lon: float) -> tuple:
    return math.floor(lat * 240), math.floor((lon - 100) * 160)


def main() -> None:
    con = duckdb.connect()
    con.execute("INSTALL httpfs; LOAD httpfs; SET s3_region='us-west-2';")
    cats = ", ".join(f"'{c}'" for c in CATEGORIES)
    q = f"""
    SELECT
      names.primary                AS name,
      categories.primary           AS category,
      brand.names.primary          AS brand,
      bbox.ymin                    AS lat,
      bbox.xmin                    AS lon,
      addresses[1].region          AS region,
      addresses[1].locality        AS locality,
      confidence
    FROM read_parquet('{BASE}', hive_partitioning=1)
    WHERE bbox.xmin BETWEEN {LON_MIN} AND {LON_MAX}
      AND bbox.ymin BETWEEN {LAT_MIN} AND {LAT_MAX}
      AND categories.primary IN ({cats})
    """
    print(f"Overture {RELEASE} から福岡県周辺の店舗を抜く …")
    rows = con.execute(q).fetchall()
    cols = [d[0] for d in con.description]
    print(f"  {len(rows):,} 件")

    # 福岡県の500mメッシュ集合に載るものだけを残す（bboxには隣県が混ざるため）
    mesh = {(int(r["lat_i"]), int(r["lon_i"]))
            for r in csv.DictReader((DATA / "mesh.csv").open(encoding="utf-8"))}

    out = []
    for r in rows:
        d = dict(zip(cols, r))
        idx = mesh_index(d["lat"], d["lon"])
        if idx not in mesh:
            continue
        d["lat_i"], d["lon_i"] = idx
        out.append(d)

    path = DATA / "overture_places.csv"
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(out[0].keys()))
        w.writeheader()
        w.writerows(out)

    from collections import Counter
    c = Counter(d["category"] for d in out)
    print(f"\n-> {path}  福岡県のメッシュ内 {len(out):,} 件")
    for k, v in c.most_common():
        print(f"   {k:<26}{v:>7,}")

    conv = [d for d in out if d["category"] == "convenience_store"]
    b = Counter((d["brand"] or "(ブランド不明)") for d in conv)
    print(f"\nコンビニ {len(conv):,} 件のブランド内訳 上位8")
    for k, v in b.most_common(8):
        print(f"   {str(k):<26}{v:>7,}")
    print("\n出典表示（CDLA-Permissive-2.0）: © Overture Maps Foundation")


if __name__ == "__main__":
    main()
