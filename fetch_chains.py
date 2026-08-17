#!/usr/bin/env python3
"""チェーン別の店舗数をメッシュに載せる。

「なぜそこに建てたか」の残差は、用途地域では6%しか説明できなかった。
残りは集積の履歴らしい。ではその集積は**同じチェーンの集まり（ドミナント出店）**なのか、
**別々の店が寄り集まったもの（集積）**なのか。これは意味がまったく違う。

  自社の店の近くに出る … ドミナント。物流と知名度の戦略で、外からは真似できない
  他社の店の近くに出る … 集積。その場所自体に理由がある

Foursquareにブランド列は無いが `website` がある。同じチェーンは同じドメインを使うので、
名前を解析するより確実に見分けられる（コンビニは83%にwebsiteがあり、
sej.co.jp 22,577件 = セブン-イレブン のようにきれいに分かれる）。

  .venv-duck/bin/python fetch_chains.py   ->  data/mesh.csv にチェーン別の列を追加
"""
import csv
from collections import defaultdict
from pathlib import Path

import duckdb

from region import bboxes

ROOT = Path(__file__).resolve().parent
DATA = ROOT / "data"
TOKEN = Path.home().joinpath(".config/foursquare/token").read_text().strip()

# 列名 -> (分類ラベルに含まれる文字列, ドメインに含まれる文字列のリスト)
# None は「そのカテゴリのうち、上のどれにも当たらないもの」
CHAINS = {
    "c_seven": ("Convenience Store", ["sej.co.jp"]),
    "c_family": ("Convenience Store", ["family.co.jp"]),
    "c_lawson": ("Convenience Store", ["lawson.co.jp", "lawson.jp"]),
    "c_ministop": ("Convenience Store", ["ministop.co.jp"]),
    "c_seico": ("Convenience Store", ["seicomart.co.jp"]),
    "c_other": ("Convenience Store", None),
}
DOMAIN = "regexp_extract(website, 'https?://(?:www\\.)?([^/]+)', 1)"


def main() -> None:
    con = duckdb.connect()
    con.execute("INSTALL httpfs; LOAD httpfs; INSTALL iceberg; LOAD iceberg;")
    con.execute(f"CREATE SECRET s (TYPE ICEBERG, TOKEN '{TOKEN}');")
    con.execute("""ATTACH 'places' AS places (TYPE iceberg, SECRET s,
                   ENDPOINT 'https://catalog.h3-hub.foursquare.com/iceberg');""")

    named = {k: v for k, v in CHAINS.items() if v[1]}
    parts = []
    for col, (_, doms) in named.items():
        cond = " OR ".join("dom ILIKE '%" + d + "%'" for d in doms)
        parts.append("WHEN " + cond + " THEN '" + col + "'")
    when = " ".join(parts)
    q = f"""
    SELECT floor(latitude * 240)::INT AS lat_i,
           floor((longitude - 100) * 160)::INT AS lon_i,
           CASE {when} ELSE 'c_other' END AS chain,
           count(DISTINCT fsq_place_id) AS n
    FROM (SELECT *, {DOMAIN} AS dom FROM places.datasets.places_os
          WHERE latitude BETWEEN {{la0}} AND {{la1}}
            AND longitude BETWEEN {{lo0}} AND {{lo1}}
            AND date_closed IS NULL
            AND fsq_category_labels[1] ILIKE '%Convenience Store%')
    GROUP BY 1, 2, 3
    """

    grid = defaultdict(lambda: defaultdict(int))
    for pref, (la0, la1, lo0, lo1) in bboxes().items():
        got = con.execute(q.format(la0=la0, la1=la1, lo0=lo0, lo1=lo1)).fetchall()
        for la, lo, chain, n in got:
            g = grid[(la, lo)]
            g[chain] = max(g[chain], n)     # 隣県の箱と重なるので大きいほうを採る
        print(f"  {pref}: {len(got):,} 行")

    rows = list(csv.DictReader((DATA / "mesh.csv").open(encoding="utf-8")))
    for r in rows:
        g = grid.get((int(r["lat_i"]), int(r["lon_i"])), {})
        for col in CHAINS:
            r[col] = g.get(col, 0)

    with (DATA / "mesh.csv").open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)

    print("\n-> data/mesh.csv")
    print(f"{'チェーン':<12}{'店舗数':>9}{'マス数':>9}")
    for col in CHAINS:
        v = [int(r[col]) for r in rows]
        print(f"{col:<12}{sum(v):>9,}{sum(1 for x in v if x):>9,}")


if __name__ == "__main__":
    main()
