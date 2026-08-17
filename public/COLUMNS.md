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

