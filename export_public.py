#!/usr/bin/env python3
"""公開用のデータを書き出す。

作業用の data/mesh.csv は120列・160MBある。中間生成物や試して効かなかった列も
入っているので、そのまま置くと「どれを見ればよいか」が分からない。
**結論を再現するのに要る列だけ**にして、gzipで固める。

生の店舗データ（Foursquare）は再配布可（Apache 2.0）だが数百万行あるので、
メッシュに集計した数だけを出す。集計の手順はスクリプトが全部残っている。

  python3 export_public.py   ->  public/
"""
import csv
import gzip
import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parent
DATA = ROOT / "data"
OUT = ROOT / "public"

# 位置と地域
BASE = ["lat_i", "lon_i", "lat", "lon", "pref", "city"]
# モデルの説明変数（mesh_model.FEATURES が使うもの）
FEAT = ["pop2020", "pop2030", "pop2040", "pop2050", "pop_r1", "pop_r2", "day_night",
        "build_share", "road_share", "trunk_m", "second_m", "local_m", "station_m",
        "workers", "workers_r1", "work_retail_r1", "work_food_r1"]
# 業種別の店舗数（30業種）
from formats import FORMATS  # noqa: E402
FMT = [c for c, _, _, _ in FORMATS]
# チェーンと個店の別
SPLIT = [f"{c}_{k}" for c in
         ["bakery", "cafe", "restaurant", "bar", "beauty", "pharmacy", "drug",
          "fashion", "gym", "elec", "laundry", "florist", "bookstore", "conv"]
         for k in ("ch", "in")]
# コンビニのチェーン別
CHAIN = ["c_seven", "c_family", "c_lawson", "c_ministop", "c_seico", "c_other"]
# 用途地域と、地形・歴史の目印
ZONE = ["z_low", "z_mid", "z_res", "z_ncom", "z_com", "z_qind", "z_ind", "z_any", "z_far"]
HIST = ["h_shinto", "h_temple", "h_castle", "h_onsen", "h_harbour",
        "h_pedest_m", "h_retail", "h_school"]

COPY = ["openings_national_geo.csv", "openings_by_format.csv", "chain_names.csv"]

# 同じ業態を数える列が2組ある。読む人が必ずつまずくので、生成物に必ず書く。
# **ここに書く。COLUMNS.md に手で足すと、次に export_public.py を走らせたとき消える。**
TWO_SETS = """## 店舗数の列が2組ある理由

同じ業態を数える列が2組ある。**誤りではなく、集計の仕方が違う。**

| 組 | 作った所 | 重複の畳み | ドラッグの扱い |
|---|---|---|---|
| `stores_fsq` `drug_fsq` `super_fsq` | `build_mesh_fsq.py` | 40m以内の同カテゴリを1件に畳む | 薬局＋ドラッグストアの合計 |
| `conv` `drug` `super` ほか30業種 | `fetch_formats.py` | 畳まない（DuckDB側で集計） | `drug`（ドラッグ）と `pharmacy`（薬局）を別列 |

全国の合計で比べると:

| 業態 | `*_fsq` | `formats`系 | 比 | 相関 |
|---|---|---|---|---|
| コンビニ | 65,085 | 67,470 | 1.04 | 0.986 |
| スーパー | 15,884 | 15,895 | 1.00 | 0.978 |
| ドラッグ | 58,111 | 29,499 | 0.51 | 0.834 |

ドラッグが半分なのは定義の違い（29,499 + 薬局31,312 = 60,811 で、畳んだ58,111とほぼ一致）。

**結論の数字はどちらでも変わらない。**同じ前向き検証を2組で回すと、
まだ1店も無いマスの上位10%捕捉は `*_fsq` 7.5倍 / `formats`系 7.5倍で一致する。

- 7.5倍などの検証（`measure_national.py`）は `*_fsq` を使う
- 30業種のAUC表は `formats` 系を使う
"""


def main() -> None:
    OUT.mkdir(exist_ok=True)
    src = list(csv.DictReader((DATA / "mesh.csv").open(encoding="utf-8")))
    cols = [c for c in BASE + FEAT + FMT + SPLIT + CHAIN + ZONE + HIST
            if c in src[0]]
    missing = [c for c in BASE + FEAT + FMT + SPLIT + CHAIN + ZONE + HIST
               if c not in src[0]]
    if missing:
        print(f"⚠ mesh.csv に無い列を飛ばした: {missing}")

    path = OUT / "mesh.csv.gz"
    with gzip.open(path, "wt", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=cols, extrasaction="ignore")
        w.writeheader()
        w.writerows(src)
    print(f"-> {path}  {len(src):,}行 x {len(cols)}列  "
          f"{path.stat().st_size/1048576:.0f}MB（元は160MB・120列）")

    for name in COPY:
        s = DATA / name
        if s.exists():
            shutil.copy(s, OUT / name)
            print(f"-> {OUT/name}  {s.stat().st_size/1024:.0f}KB")

    # 列の説明を置く。何の列か分からないデータは使えない
    doc = OUT / "COLUMNS.md"
    groups = [("位置と地域", BASE), ("モデルの説明変数", FEAT), ("業種別の店舗数", FMT),
              ("チェーンと個店の別", SPLIT), ("コンビニのチェーン別", CHAIN),
              ("用途地域", ZONE), ("地形・歴史の目印", HIST)]
    with doc.open("w", encoding="utf-8") as f:
        f.write("# mesh.csv.gz の列\n\n")
        f.write(f"全国{len(src):,}マス（500mメッシュ）。1行が1マス。\n")
        f.write("メッシュの行・列は緯度経度から直接計算できる: "
                "`lat_i = floor(緯度 x 240)`, `lon_i = floor((経度 - 100) x 160)`\n\n")
        for name, cs in groups:
            have = [c for c in cs if c in src[0]]
            f.write(f"## {name}（{len(have)}列）\n\n")
            f.write("`" + "` `".join(have) + "`\n\n")
        f.write(TWO_SETS)
    print(f"-> {doc}")


if __name__ == "__main__":
    main()
