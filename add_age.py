#!/usr/bin/env python3
"""メッシュに年齢別人口を足す。

これまで総人口しか使っていなかったが、業種によって効く人口が違う。
学習塾なら学齢人口、病院・薬局なら高齢人口で、総数では測れない。
国土数値情報の500mメッシュ人口には5歳階級（PT1〜PT19）が最初から入っていた。

  PT1〜PT3   = 0-14歳（年少）      … PTA と一致することを確認済み
  PT2〜PT4   = 5-19歳（学齢）      … 学習塾の需要
  PT4〜PT13  = 15-64歳（生産年齢）  … PTB
  PT14〜PT19 = 65歳以上（高齢）     … PTC
  PT16〜PT19 = 75歳以上（後期高齢）  … PTD。通院・訪問の需要はここが効くはず

  python3 add_age.py   ->  data/mesh.csv に年齢別の列を追加
"""
import csv
from pathlib import Path

from build_mesh import mesh_id_to_index
from fetch_postoffices import read_dbf

ROOT = Path(__file__).resolve().parent
DATA = ROOT / "data"
MESH_DBF = DATA / "mlit" / "500m_mesh_2018_40.dbf"

BANDS = {
    "young": (1, 3),      # 0-14歳
    "school": (2, 4),     # 5-19歳
    "working": (4, 13),   # 15-64歳
    "senior": (14, 19),   # 65歳以上
    "old75": (16, 19),    # 75歳以上
}


def main() -> None:
    src = {}
    for r in read_dbf(MESH_DBF):
        idx = mesh_id_to_index(r["MESH_ID"])
        g = lambda k: float(r.get(k) or 0)          # noqa: E731
        src[idx] = {name: sum(g(f"PT{i}_2020") for i in range(lo, hi + 1))
                    for name, (lo, hi) in BANDS.items()}
        # 2050年の高齢人口も持っておく（将来シナリオ用）
        src[idx]["senior_2050"] = sum(g(f"PT{i}_2050") for i in range(14, 20))

    rows = list(csv.DictReader((DATA / "mesh.csv").open(encoding="utf-8")))
    grid = {(int(r["lat_i"]), int(r["lon_i"])): src.get((int(r["lat_i"]), int(r["lon_i"])), {})
            for r in rows}

    def around(idx, key):
        la, lo = idx
        return sum(grid.get((la + i, lo + j), {}).get(key, 0)
                   for i in (-1, 0, 1) for j in (-1, 0, 1))

    for r in rows:
        idx = (int(r["lat_i"]), int(r["lon_i"]))
        v = grid.get(idx, {})
        pop = float(r["pop2020"]) or 1
        for name in BANDS:
            r[name] = round(v.get(name, 0), 1)
            r[f"{name}_r1"] = round(around(idx, name), 1)
            r[f"{name}_share"] = round(v.get(name, 0) / pop, 4)
        r["senior_2050"] = round(v.get("senior_2050", 0), 1)

    with (DATA / "mesh.csv").open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)

    tot = sum(float(r["pop2020"]) for r in rows)
    print(f"-> data/mesh.csv に年齢別を追加（{len(rows):,}メッシュ）")
    print(f"{'区分':<12}{'人数':>12}{'県全体に占める割合':>16}")
    for name in BANDS:
        s = sum(float(r[name]) for r in rows)
        print(f"{name:<12}{s:>12,.0f}{s/tot:>16.1%}")


if __name__ == "__main__":
    main()
