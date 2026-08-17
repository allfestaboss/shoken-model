#!/usr/bin/env python3
"""対象地域を1か所で決める。

福岡固定だったころは各スクリプトに緯度経度の定数が散らばっていた。
県を足すたびに全部直すことになり、直し忘れると**取りこぼしに気づけない**
（範囲外の店は静かに0件になるだけで、エラーにならない）。
そこで data/mesh.csv の実データから範囲を作る。メッシュを作り直せば範囲も自動で追随する。

  from region import bbox, primary_meshes
"""
import csv
from pathlib import Path

DATA = Path(__file__).resolve().parent / "data"
MESH = DATA / "mesh.csv"
MARGIN = 0.02          # メッシュ中心の座標なので、端の半メッシュ分を足す


def _rows():
    return list(csv.DictReader(MESH.open(encoding="utf-8")))


def bbox() -> tuple:
    """(lat_min, lat_max, lon_min, lon_max)"""
    rows = _rows()
    lat = [float(r["lat"]) for r in rows]
    lon = [float(r["lon"]) for r in rows]
    return (min(lat) - MARGIN, max(lat) + MARGIN,
            min(lon) - MARGIN, max(lon) + MARGIN)


def bboxes() -> dict:
    """県ごとの範囲。全県を1つの箱で囲うと、九州と東北を足した時点で
    日本列島がまるごと入ってしまい、店舗データを無駄に大量に引くことになる。
    県ごとに引いて足し合わせる。"""
    out = {}
    for r in _rows():
        p = r.get("pref") or r["city"][:2]
        lat, lon = float(r["lat"]), float(r["lon"])
        b = out.setdefault(p, [lat, lat, lon, lon])
        b[0] = min(b[0], lat); b[1] = max(b[1], lat)
        b[2] = min(b[2], lon); b[3] = max(b[3], lon)
    return {p: (b[0] - MARGIN, b[1] + MARGIN, b[2] - MARGIN, b[3] + MARGIN)
            for p, b in sorted(out.items())}


def primary_meshes() -> list:
    """対象範囲をおおう1次メッシュ（4桁）。e-Statや国土数値情報のタイル取得に使う。"""
    codes = set()
    for r in _rows():
        codes.add(f"{int(float(r['lat']) * 1.5):02d}{int(float(r['lon'])) - 100:02d}")
    return sorted(codes)


def prefs() -> list:
    return sorted({r["pref"] for r in _rows() if r.get("pref")})


if __name__ == "__main__":
    la0, la1, lo0, lo1 = bbox()
    print(f"緯度 {la0:.3f} 〜 {la1:.3f}")
    print(f"経度 {lo0:.3f} 〜 {lo1:.3f}")
    print(f"県     {prefs()}")
    print(f"1次メッシュ {primary_meshes()}")
