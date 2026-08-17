#!/usr/bin/env python3
"""メッシュに地価を足す。

モデルには「需要（人口・道路・駅・土地利用）」しか入っていない。費用側がまるごと無い。
店を出すかどうかは売上と費用の差で決まるので、費用の代理として地価を入れる。

  地価公示（L01・毎年1月1日時点）     918地点
  都道府県地価調査（L02・7月1日時点）  922地点
合わせて県内1,840地点。500mメッシュ11,385個に対しては疎いので、
**対数価格を逆距離加重（IDW）で内挿**する。地価は連続的に変化するので内挿が効く。
最寄り地点までの距離も列に持たせる（遠いメッシュは内挿があてにならない、という情報）。

注意: 地価は費用であると同時に「商業的な立地の良さ」の結果でもある。
係数を「費用の効果」と読んではいけない。あくまで予測のための情報として使う。

  python3 add_landprice.py   ->  data/mesh.csv に land_price / land_com / land_dist を追加
"""
import csv
import glob
import json
import math
from pathlib import Path

ROOT = Path(__file__).resolve().parent
DATA = ROOT / "data"
K = 6                      # 内挿に使う近傍地点数
POWER = 2.0                # 逆距離加重の指数


def load_points():
    """(lat, lon, 円/m2, 商業地か) を集める。"""
    pts = []
    for path, price_key, use_key, prefix in [
        (glob.glob(str(DATA / "mlit/L01/**/*.geojson"), recursive=True), "L01_008", "L01_028", "L01"),
        (glob.glob(str(DATA / "mlit/L02/**/*.geojson"), recursive=True), "L02_006", "L02_029", "L02"),
    ]:
        for p in path:
            for f in json.load(open(p, encoding="utf-8"))["features"]:
                pr = f["properties"]
                try:
                    price = float(pr.get(price_key) or 0)
                except (TypeError, ValueError):
                    continue
                if price <= 0:
                    continue
                lon, lat = f["geometry"]["coordinates"][:2]
                use = str(pr.get(use_key) or "")
                # 利用現況が「店舗」「事務所」などなら商業地とみなす
                com = any(w in use for w in ("店舗", "事務所", "営業所", "銀行", "飲食"))
                pts.append((lat, lon, price, com))
    return pts


def main() -> None:
    pts = load_points()
    com = [p for p in pts if p[3]]
    print(f"地価地点 {len(pts):,}（うち商業系 {len(com):,}）")

    rows = list(csv.DictReader((DATA / "mesh.csv").open(encoding="utf-8")))

    def idw(lat, lon, src):
        # 緯度経度をkmに直してから距離を測る（福岡の緯度で経度1度≒92km）
        best = []
        for la, lo, price, _ in src:
            dy = (la - lat) * 111.0
            dx = (lo - lon) * 92.3
            d2 = dy * dy + dx * dx
            best.append((d2, price))
        best.sort(key=lambda t: t[0])
        near = best[:K]
        num = den = 0.0
        for d2, price in near:
            w = 1.0 / max(d2, 1e-4) ** (POWER / 2)
            num += w * math.log(price)
            den += w
        return math.exp(num / den), math.sqrt(near[0][0])

    for i, r in enumerate(rows):
        lat, lon = float(r["lat"]), float(r["lon"])
        v, d = idw(lat, lon, pts)
        r["land_price"] = round(v)
        r["land_dist"] = round(d, 2)
        r["land_com"] = round(idw(lat, lon, com)[0]) if com else 0
        if i % 2000 == 0:
            print(f"  {i:,}/{len(rows):,}")

    with (DATA / "mesh.csv").open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)

    v = sorted(float(r["land_price"]) for r in rows)
    d = sorted(float(r["land_dist"]) for r in rows)
    print(f"\n-> data/mesh.csv")
    print(f"   内挿地価 円/m2   中央値 {v[len(v)//2]:>9,.0f}  "
          f"下位10% {v[len(v)//10]:>8,.0f}  上位10% {v[-len(v)//10]:>9,.0f}")
    print(f"   最寄り地点まで km 中央値 {d[len(d)//2]:>9.2f}  上位10% {d[-len(d)//10]:>9.2f}")


if __name__ == "__main__":
    main()
