#!/usr/bin/env python3
"""業種ごとに、店舗をチェーンと個店に分けてメッシュに載せる。

コンビニで分かったのは「集積の正体はドミナント出店」だった。全チェーンが自社の近くに
出しており、自社シェアで新店を見分けられる（ミニストップ0.934〜セブン0.569）。
ならば「やたらとパン屋が多い」も、1社の面取りなのか、個店が寄り集まったのかで
意味がまるで違う。**個店だけに絞れば、土地そのものに理由がある集積が取り出せる**はず。

チェーンの見分けは `website` のドメイン。同じチェーンは同じドメインを使う。
その業種の中で同じドメインが SNIP 件以上あればチェーンとみなす。
websiteが無い店は個店として扱う（チェーンの支店は本部サイトを持つことが多い）。

  .venv-duck/bin/python fetch_chain_split.py
     ->  data/mesh.csv に <業種>_ch（チェーン）と <業種>_in（個店）を追加
     ->  data/chain_names.csv（開店データを分類するためのチェーン名の一覧）
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
MIN_CHAIN = 20                # 同じドメインがこれ以上あればチェーン
TARGETS = ["bakery", "cafe", "restaurant", "bar", "beauty", "pharmacy", "drug",
           "fashion", "gym", "elec", "laundry", "florist", "bookstore", "conv"]
DOMAIN = "regexp_extract(website, 'https?://(?:www\\.)?([^/]+)', 1)"
PAT = {c: p for c, _, p, _ in FORMATS}


def main() -> None:
    con = duckdb.connect()
    con.execute("INSTALL httpfs; LOAD httpfs; INSTALL iceberg; LOAD iceberg;")
    con.execute(f"CREATE SECRET s (TYPE ICEBERG, TOKEN '{TOKEN}');")
    con.execute("""ATTACH 'places' AS places (TYPE iceberg, SECRET s,
                   ENDPOINT 'https://catalog.h3-hub.foursquare.com/iceberg');""")

    # 1) 業種ごとに、どのドメインがチェーンかを決める（全国で数える）
    chains, names = {}, []
    for col in TARGETS:
        q = f"""
        SELECT dom, count(DISTINCT fsq_place_id) n, any_value(name) AS sample_name
        FROM (SELECT *, {DOMAIN} AS dom FROM places.datasets.places_os
              WHERE latitude BETWEEN 24 AND 46 AND longitude BETWEEN 122 AND 146
                AND date_closed IS NULL
                AND fsq_category_labels[1] ILIKE '%{PAT[col]}%'
                AND website IS NOT NULL)
        WHERE dom <> '' GROUP BY 1 HAVING n >= {MIN_CHAIN} ORDER BY n DESC
        """
        rows = con.execute(q).fetchall()
        chains[col] = {d for d, _, _ in rows}
        for d, n, sample_name in rows:
            names.append({"format": col, "domain": d, "n": n, "name": sample_name})
        print(f"  {col:<12}チェーンとみなすドメイン {len(rows):>4} 種 "
              f"/ そのうち最大 {rows[0][1]:,}件 {rows[0][2][:20] if rows else ''}")

    # 2) メッシュごとに、チェーンと個店を数える
    grid = defaultdict(lambda: defaultdict(int))
    for col in TARGETS:
        doms = chains[col]
        inlist = ", ".join("'" + d.replace("'", "''") + "'" for d in doms) or "''"
        q = f"""
        SELECT floor(latitude * 240)::INT lat_i,
               floor((longitude - 100) * 160)::INT lon_i,
               CASE WHEN dom IN ({inlist}) THEN 'ch' ELSE 'in' END kind,
               count(DISTINCT fsq_place_id) n
        FROM (SELECT *, {DOMAIN} AS dom FROM places.datasets.places_os
              WHERE latitude BETWEEN {{la0}} AND {{la1}}
                AND longitude BETWEEN {{lo0}} AND {{lo1}}
                AND date_closed IS NULL
                AND fsq_category_labels[1] ILIKE '%{PAT[col]}%')
        GROUP BY 1, 2, 3
        """
        for _, (la0, la1, lo0, lo1) in bboxes().items():
            for la, lo, kind, n in con.execute(
                    q.format(la0=la0, la1=la1, lo0=lo0, lo1=lo1)).fetchall():
                g = grid[(la, lo)]
                key = f"{col}_{kind}"
                g[key] = max(g[key], n)
        print(f"  {col:<12}メッシュ集計おわり")

    rows = list(csv.DictReader((DATA / "mesh.csv").open(encoding="utf-8")))
    cols = [f"{c}_{k}" for c in TARGETS for k in ("ch", "in")]
    for r in rows:
        g = grid.get((int(r["lat_i"]), int(r["lon_i"])), {})
        for c in cols:
            r[c] = g.get(c, 0)

    with (DATA / "mesh.csv").open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)

    with (DATA / "chain_names.csv").open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=["format", "domain", "n", "name"])
        w.writeheader()
        w.writerows(sorted(names, key=lambda r: (r["format"], -r["n"])))

    print("\n-> data/mesh.csv, data/chain_names.csv")
    print(f"{'業種':<12}{'チェーン':>10}{'個店':>10}{'個店の割合':>11}")
    for c in TARGETS:
        ch = sum(int(r[f"{c}_ch"]) for r in rows)
        ind = sum(int(r[f"{c}_in"]) for r in rows)
        print(f"{c:<12}{ch:>10,}{ind:>10,}{ind/max(ch+ind,1):>11.1%}")


if __name__ == "__main__":
    main()
