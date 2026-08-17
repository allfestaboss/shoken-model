#!/usr/bin/env python3
"""47都道府県の対応表を1か所に置く。

酒販免許のPDFはローマ字のファイル名で、国土数値情報とe-Statは2桁のコード、
ジオコーディングには日本語の県名が要る。3つの表記を行き来する場所が
散らばると、どこかで1県だけ抜けても気づけない（実際に群馬 gumma で踏んだ）。

  ROMAJI  … 酒販免許PDFのファイル名。北海道だけ局名の sapporo、群馬は旧式の gumma
  CODE    … 2桁。国土数値情報 500m_mesh_suikei_2018_shape_<CODE>.zip など
  JP      … 国土地理院のジオコーディングに前置する県名
"""

# (2桁コード, 酒販免許のファイル名, 県名)
PREFS = [
    ("01", "sapporo", "北海道"),      # 局が1県だけなので局名。hokkaido.pdf は404
    ("02", "aomori", "青森県"), ("03", "iwate", "岩手県"), ("04", "miyagi", "宮城県"),
    ("05", "akita", "秋田県"), ("06", "yamagata", "山形県"), ("07", "fukushima", "福島県"),
    ("08", "ibaraki", "茨城県"), ("09", "tochigi", "栃木県"),
    ("10", "gumma", "群馬県"),        # 旧ヘボン式。gunma.pdf は404
    ("11", "saitama", "埼玉県"), ("12", "chiba", "千葉県"), ("13", "tokyo", "東京都"),
    ("14", "kanagawa", "神奈川県"), ("15", "niigata", "新潟県"), ("16", "toyama", "富山県"),
    ("17", "ishikawa", "石川県"), ("18", "fukui", "福井県"), ("19", "yamanashi", "山梨県"),
    ("20", "nagano", "長野県"), ("21", "gifu", "岐阜県"), ("22", "shizuoka", "静岡県"),
    ("23", "aichi", "愛知県"), ("24", "mie", "三重県"), ("25", "shiga", "滋賀県"),
    ("26", "kyoto", "京都府"), ("27", "osaka", "大阪府"), ("28", "hyogo", "兵庫県"),
    ("29", "nara", "奈良県"), ("30", "wakayama", "和歌山県"), ("31", "tottori", "鳥取県"),
    ("32", "shimane", "島根県"), ("33", "okayama", "岡山県"), ("34", "hiroshima", "広島県"),
    ("35", "yamaguchi", "山口県"), ("36", "tokushima", "徳島県"), ("37", "kagawa", "香川県"),
    ("38", "ehime", "愛媛県"), ("39", "kochi", "高知県"), ("40", "fukuoka", "福岡県"),
    ("41", "saga", "佐賀県"), ("42", "nagasaki", "長崎県"), ("43", "kumamoto", "熊本県"),
    ("44", "oita", "大分県"), ("45", "miyazaki", "宮崎県"), ("46", "kagoshima", "鹿児島県"),
    ("47", "okinawa", "沖縄県"),
]

CODE = {r: c for c, r, _ in PREFS}          # ローマ字 -> 2桁コード
JP = {r: j for c, r, j in PREFS}            # ローマ字 -> 県名
NAME = {c: j for c, r, j in PREFS}          # 2桁コード -> 県名
ROMAJI = {c: r for c, r, _ in PREFS}        # 2桁コード -> ローマ字

assert len(PREFS) == 47, len(PREFS)

if __name__ == "__main__":
    print(f"{len(PREFS)} 県")
    for c, r, j in PREFS:
        print(f"  {c}  {r:<12}{j}")
