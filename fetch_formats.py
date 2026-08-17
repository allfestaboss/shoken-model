#!/usr/bin/env python3
"""多業種の店舗数をメッシュに載せる。

これまでは業態を1つずつ取っていたが、業種を増やすとその都度200万行を
持ってくることになる。**集計をDuckDB側でやる**ようにした。
メッシュの行・列は緯度経度から計算できるので、SQLの中で floor するだけでよく、
返ってくるのは (行, 列, 業種, 件数) に畳んだあとのものになる。

業種の一覧は formats.py にある。増やしたければあちらに1行足す。

  .venv-duck/bin/python fetch_formats.py   ->  data/mesh.csv に業種ごとの列を追加
"""
import csv
from collections import defaultdict
from pathlib import Path

import duckdb

from formats import FORMATS
from region import bboxes

ROOT = Path(__file__).resolve().parent
DATA = ROOT / "data"
TOKEN = Path.home().joinpath(".config/foursquare/token").read_text().strip()


LABEL = "fsq_category_labels[1]"


def case_expr() -> str:
    """ラベル -> 業種の振り分け。上から順に見て最初に当たったものにする。"""
    parts = [f"WHEN {LABEL} ILIKE '%{pat}%' THEN '{col}'"
             for col, _, pat, _ in FORMATS]
    return "CASE " + " ".join(parts) + " ELSE NULL END"


def main() -> None:
    con = duckdb.connect()
    con.execute("INSTALL httpfs; LOAD httpfs; INSTALL iceberg; LOAD iceberg;")
    con.execute(f"CREATE SECRET s (TYPE ICEBERG, TOKEN '{TOKEN}');")
    con.execute("""ATTACH 'places' AS places (TYPE iceberg, SECRET s,
                   ENDPOINT 'https://catalog.h3-hub.foursquare.com/iceberg');""")

    q = f"""
    SELECT floor(latitude * 240)::INT       AS lat_i,
           floor((longitude - 100) * 160)::INT AS lon_i,
           {case_expr()}                    AS fmt,
           count(DISTINCT fsq_place_id)     AS n
    FROM places.datasets.places_os
    WHERE latitude BETWEEN {{la0}} AND {{la1}}
      AND longitude BETWEEN {{lo0}} AND {{lo1}}
      AND date_closed IS NULL
      AND fsq_category_labels IS NOT NULL
    GROUP BY 1, 2, 3
    HAVING fmt IS NOT NULL
    """

    grid = defaultdict(lambda: defaultdict(int))
    for pref, (la0, la1, lo0, lo1) in bboxes().items():
        got = con.execute(q.format(la0=la0, la1=la1, lo0=lo0, lo1=lo1)).fetchall()
        for la, lo, fmt, n in got:
            # 県ごとの箱は隣県と重なる。同じマスに複数回来たら大きいほうを採る
            # （DISTINCTで数えているので、重なった側は同じか少ない値になる）
            g = grid[(la, lo)]
            g[fmt] = max(g[fmt], n)
        print(f"  {pref}: {len(got):,} 行")

    rows = list(csv.DictReader((DATA / "mesh.csv").open(encoding="utf-8")))
    cols = [c for c, _, _, _ in FORMATS]
    for r in rows:
        g = grid.get((int(r["lat_i"]), int(r["lon_i"])), {})
        for c in cols:
            r[c] = g.get(c, 0)

    with (DATA / "mesh.csv").open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)

    print(f"\n-> data/mesh.csv")
    print(f"{'業種':<14}{'店舗数':>10}{'マス数':>10}{'最大/マス':>10}")
    for c, name, _, _ in FORMATS:
        v = [int(r[c]) for r in rows]
        print(f"{name:<14}{sum(v):>10,}{sum(1 for x in v if x):>10,}{max(v):>10,}")


if __name__ == "__main__":
    main()
