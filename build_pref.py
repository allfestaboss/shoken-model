#!/usr/bin/env python3
"""複数県ぶんの500mメッシュ基盤を作る（福岡固定をやめる）。

福岡だけで学習も検証もしていたので、モデルが他県に移るかを一度も試していない。
県内ですら北九州（車社会）は道路が効き、福岡市（鉄道）は駅が効くので、
県をまたげば係数が変わる可能性は高い。それを測るための土台。

**3県をまとめて1つのファイルにする**のが肝で、別々に作ると県境のメッシュで
近傍3x3・5x5の人口が切れてしまう。学習と検証の切り分けは県コードで後からやる。

  人口: 国土数値情報 500mメッシュ別将来推計人口（H30国政局推計）
        https://nlftp.mlit.go.jp/ksj/gml/data/m500h30/m500h30-18/500m_mesh_suikei_2018_shape_{県}.zip
  昼夜間比: data/context.csv（統計ダッシュボード。市町村単位）

  python3 build_pref.py 40 41 42   ->  data/mesh.csv
"""
import csv
import io
import os
import sys
import time
import urllib.request
import zipfile
from pathlib import Path

from build_mesh import mesh_center, mesh_id_to_index
from fetch_postoffices import read_dbf

ROOT = Path(__file__).resolve().parent
DATA = ROOT / "data"
MLIT = DATA / "mlit"
URL = ("https://nlftp.mlit.go.jp/ksj/gml/data/m500h30/m500h30-18/"
       "500m_mesh_suikei_2018_shape_{}.zip")
UA = "shoken-model/0.5 (research; boss@allfesta.com)"

# 5歳階級。PT1〜PT19 が5歳刻みで入っている
BANDS = {"young": (1, 3), "school": (2, 4), "working": (4, 13),
         "senior": (14, 19), "old75": (16, 19)}


def fetch(pref: str) -> Path:
    dbf = MLIT / f"500m_mesh_2018_{pref}.dbf"
    if dbf.exists():
        return dbf
    print(f"  {pref} を取得 …")
    req = urllib.request.Request(URL.format(pref), headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=300) as r:
        body = r.read()
    with zipfile.ZipFile(io.BytesIO(body)) as z:
        for name in z.namelist():
            (MLIT / Path(name).name).write_bytes(z.read(name))
    time.sleep(1.5)
    return dbf


def known_cities() -> set:
    return {r["code"] for r in
            csv.DictReader((DATA / "population.csv").open(encoding="utf-8"))}


def city_of(shicode: str, known: set) -> str:
    """政令市の区コード -> 市コード。

    区は市町村一覧に載らないので、載っているコードのうち**最も長く前方一致する**
    ものに畳む。福岡市(40130)の区は4013x、北九州市(40100)の区は401xx なので、
    単に「下2桁を00にする」だと福岡市の区が北九州市に化ける。名古屋市(23100)の
    区は231xx で、これは下2桁00で正しい。長い一致を優先すれば両方とも当たる。
    """
    if shicode in known:
        return shicode
    cands = [c for c in known if c[:2] == shicode[:2]]
    best, best_len = shicode, 0
    for c in cands:
        n = len(os.path.commonprefix([c, shicode]))
        if n > best_len:
            best, best_len = c, n
    return best if best_len >= 3 else shicode


def main() -> None:
    prefs = sys.argv[1:] or ["40"]
    if prefs == ["all"]:
        from prefs import PREFS as _P
        prefs = [c for c, _, _ in _P]
    MLIT.mkdir(parents=True, exist_ok=True)

    pop, shicode, ages = {}, {}, {}
    for pref in prefs:
        dbf = fetch(pref)
        n0 = len(pop)
        for r in read_dbf(dbf):
            idx = mesh_id_to_index(r["MESH_ID"])
            # SHICODE は数値として格納されており、秋田(05xxx)などは先頭の0が落ちる
            r["SHICODE"] = str(r["SHICODE"]).strip().zfill(5)
            g = lambda k: float(r.get(k) or 0)                      # noqa: E731
            pop[idx] = {y: g(f"PTN_{y}") for y in ("2020", "2030", "2040", "2050")}
            shicode[idx] = r["SHICODE"]
            ages[idx] = {name: sum(g(f"PT{i}_2020") for i in range(lo, hi + 1))
                         for name, (lo, hi) in BANDS.items()}
        print(f"  {pref}: {len(pop)-n0:,} メッシュ / "
              f"2020年人口 {sum(pop[i]['2020'] for i in list(pop)[n0:]):,.0f}人")

    ctx = {r["code"]: r for r in csv.DictReader((DATA / "context.csv").open(encoding="utf-8"))}
    known = known_cities()

    def ring(idx, rad, key="2020"):
        la, lo = idx
        return sum(pop.get((la + i, lo + j), {}).get(key, 0)
                   for i in range(-rad, rad + 1) for j in range(-rad, rad + 1))

    out = []
    missing = set()
    for idx, p in pop.items():
        la, lo = idx
        lat, lon = mesh_center(la, lo)
        city = city_of(shicode.get(idx, ""), known)
        c = ctx.get(city)
        if c is None:
            missing.add(city)
        row = {"lat_i": la, "lon_i": lo, "lat": round(lat, 6), "lon": round(lon, 6),
               "shicode": shicode.get(idx, ""), "city": city, "pref": city[:2],
               "pop2020": p["2020"], "pop2030": p["2030"],
               "pop2040": p["2040"], "pop2050": p["2050"],
               "pop_r1": round(ring(idx, 1), 1), "pop_r2": round(ring(idx, 2), 1),
               "day_night": float(c["day_night_ratio"]) if c and c.get("day_night_ratio") else 100.0}
        for name in BANDS:
            row[name] = round(ages[idx].get(name, 0), 1)
        out.append(row)

    if missing:
        print(f"  ⚠ context.csv に無い市町村コード {sorted(missing)[:6]}"
              f"（昼夜間比は100として扱う）")

    path = DATA / "mesh.csv"
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(out[0].keys()))
        w.writeheader()
        w.writerows(out)

    lat = [r["lat"] for r in out]
    lon = [r["lon"] for r in out]
    print(f"\n-> {path}  {len(out):,} メッシュ")
    print(f"   緯度 {min(lat):.2f}〜{max(lat):.2f} / 経度 {min(lon):.2f}〜{max(lon):.2f}")
    for pref in prefs:
        sub = [r for r in out if r["pref"] == pref]
        print(f"   {pref}: {len(sub):>7,}メッシュ  "
              f"人口 {sum(r['pop2020'] for r in sub):>10,.0f}人")


if __name__ == "__main__":
    main()
