#!/usr/bin/env python3
"""分析する業種の一覧。ここに1行足せば業種が増える。

Foursquare の分類ラベル（`fsq_category_labels[1]`）に含まれる文字列で振り分ける。
順番に見て**最初に当たったものだけ**に数えるので、細かいものを先に置く
（例: Drugstore を Pharmacy より先に置かないと薬局に吸われる）。

「店」と呼べるものだけを入れる。公園・橋・道路・寺社・役所は、
数は多いが出店の意思決定とは関係ないので入れない。

検証の段階が業種で違う。ここを混ぜて語らないために印を付ける:
  A … 実際の開店データで検証済み（酒販免許・食品衛生申請等システム）
  B … 分布の再現だけ検証（県を丸ごと隠して当てられるか）。開店データが無い

  python3 formats.py   -> 一覧を表示
"""

# (列名, 表示名, FSQラベルに含まれる文字列, 検証の段階)
FORMATS = [
    # --- A: 開店データで検証済み ---
    ("conv",      "コンビニ",      "Convenience Store",              "A"),
    ("drug",      "ドラッグ",      "Drugstore",                      "A"),
    ("pharmacy",  "薬局",          "Pharmacy",                       "A"),
    ("super",     "スーパー",      "Supermarket",                    "A"),
    ("bar",       "居酒屋・バー",  "> Bar",                          "A"),
    ("cafe",      "カフェ",        "Cafe, Coffee, and Tea House",    "A"),
    ("bakery",    "パン屋",        "> Bakery",                       "A"),
    ("restaurant", "レストラン",   "> Restaurant",                   "A"),

    # --- B: 分布の再現のみ ---
    ("beauty",    "美容・理容",    "Health and Beauty Service",      "B"),
    ("fashion",   "衣料品",        "Fashion Retail",                 "B"),
    ("lodging",   "宿泊",          "> Lodging",                      "B"),
    ("fuel",      "ガソリンスタンド", "Fuel Station",                "B"),
    ("autoserv",  "自動車整備",    "Automotive Service",             "B"),
    ("autoretail", "自動車販売",   "Automotive Retail",              "B"),
    ("elec",      "家電・PC",      "Computers and Electronics Retail", "B"),
    ("furniture", "家具・生活雑貨", "Furniture and Home Store",      "B"),
    ("physician", "診療所",        "> Physician",                    "B"),
    ("dentist",   "歯科",          "> Dentist",                      "B"),
    ("hospital",  "病院",          "> Hospital",                     "B"),
    ("vet",       "動物病院",      "Veterinarian",                   "B"),
    ("school",    "学校・教育",    "Community and Government > Education", "B"),
    ("gym",       "ジム",          "Gym and Studio",                 "B"),
    ("bank",      "金融",          "Financial Service",              "B"),
    ("parking",   "駐車場",        "> Parking",                      "B"),
    ("laundry",   "クリーニング",  "Laundry Service",                "B"),
    ("bookstore", "書店",          "Bookstore",                      "B"),
    ("florist",   "花屋",          "Flower Store",                   "B"),
    ("hardware",  "ホームセンター", "Hardware Store",                "B"),
    ("sports",    "スポーツ用品",  "Sporting Goods Retail",          "B"),
    ("depart",    "百貨店",        "Department Store",               "B"),
]

COL = {c: (name, pat, tier) for c, name, pat, tier in FORMATS}
NAME = {c: name for c, name, _, _ in FORMATS}
TIER = {c: tier for c, _, _, tier in FORMATS}

if __name__ == "__main__":
    for tier in ("A", "B"):
        rows = [f for f in FORMATS if f[3] == tier]
        label = "開店データで検証済み" if tier == "A" else "分布の再現のみ"
        print(f"\n■ {tier}: {label}（{len(rows)}業種）")
        for c, name, pat, _ in rows:
            print(f"   {c:<12}{name:<14}{pat}")


# --- 業種固有の構造について（2026-08-17に測った） ---
#
# 一般条件（人口・従業者・道路・駅・土地利用）はどの業種にも同じ向きに効くので、
# 「このマスに何が出るか」は当てられない（業種ごとのAUC平均 0.508）。
#
# ただし**向きを逆にすると効く**。周辺3x3の「実際の店舗数 ÷ モデルの見込み」で
# 比べると平均 0.577 まで上がる:
#   居酒屋・バー 0.651 / スーパー 0.638 / ドラッグ 0.588 / コンビニ 0.586 /
#   カフェ 0.570 / パン屋 0.519 / レストラン 0.488（唯一の例外）
# つまり「足りない所に増える」のではなく「既に多い所にさらに増える」。
#
# その偏りはばらつきではなく構造。残差の空間相関を、同じ見込みから作った
# ポアソン乱数と比べると21業種すべてで実際のほうが高い（平均 +0.148）:
#   宿泊 +0.348 / 駐車場 +0.311 / 衣料品 +0.269 / 美容・理容 +0.268 /
#   カフェ +0.259 / 学校 +0.240 … ガソリンスタンド +0.067 / ジム +0.074
# 隣り合うマスが同じ向きにずれている＝一般条件では説明できない業種固有の何かがある。
#
# 次に試す候補: 国土数値情報の用途地域 A29（無料・県別）。
#   https://nlftp.mlit.go.jp/ksj/gml/data/A29/A29-19/A29-19_<県>_GML.zip
# 商業地域・近隣商業地域・工業地域・第一種低層住居専用地域などで、
# 建てられる業種が法で決まっている。業種ごとに違う情報の筆頭。
