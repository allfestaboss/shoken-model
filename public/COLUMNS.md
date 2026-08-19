# mesh.csv.gz の列

全国471,024マス（500mメッシュ）。1行が1マス。
メッシュの行・列は緯度経度から直接計算できる: `lat_i = floor(緯度 x 240)`, `lon_i = floor((経度 - 100) x 160)`

## 位置と地域（6列）

`lat_i` `lon_i` `lat` `lon` `pref` `city`

## モデルの説明変数（17列）

`pop2020` `pop2030` `pop2040` `pop2050` `pop_r1` `pop_r2` `day_night` `build_share` `road_share` `trunk_m` `second_m` `local_m` `station_m` `workers` `workers_r1` `work_retail_r1` `work_food_r1`

## 業種別の店舗数（30列）

`conv` `drug` `pharmacy` `super` `bar` `cafe` `bakery` `restaurant` `beauty` `fashion` `lodging` `fuel` `autoserv` `autoretail` `elec` `furniture` `physician` `dentist` `hospital` `vet` `school` `gym` `bank` `parking` `laundry` `bookstore` `florist` `hardware` `sports` `depart`

## チェーンと個店の別（28列）

`bakery_ch` `bakery_in` `cafe_ch` `cafe_in` `restaurant_ch` `restaurant_in` `bar_ch` `bar_in` `beauty_ch` `beauty_in` `pharmacy_ch` `pharmacy_in` `drug_ch` `drug_in` `fashion_ch` `fashion_in` `gym_ch` `gym_in` `elec_ch` `elec_in` `laundry_ch` `laundry_in` `florist_ch` `florist_in` `bookstore_ch` `bookstore_in` `conv_ch` `conv_in`

## コンビニのチェーン別（6列）

`c_seven` `c_family` `c_lawson` `c_ministop` `c_seico` `c_other`

## 用途地域（9列）

`z_low` `z_mid` `z_res` `z_ncom` `z_com` `z_qind` `z_ind` `z_any` `z_far`

## 地形・歴史の目印（8列）

`h_shinto` `h_temple` `h_castle` `h_onsen` `h_harbour` `h_pedest_m` `h_retail` `h_school`

## 店舗数の列が2組ある理由

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
