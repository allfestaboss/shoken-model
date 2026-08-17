#!/usr/bin/env python3
"""空きマス台帳の閲覧ページを作る。

simulate.py が出した候補（out/candidates.json）を1枚のHTMLに埋め込む。
外部への通信は一切しない（データは埋め込み）ので、そのまま配れる。

  .venv-duck/bin/python simulate.py all 100
  python3 build_viewer.py            ->  out/viewer.html
"""
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent
OUT = ROOT / "out"

# 判定ごとの、実際の開店率（まだ店の無いマス全体を1.0としたときの倍率）。
# 全国471,024メッシュ・実際の開店1,521件で測り直した
RATES = {
    "コンビニ": (5.27, 3.05),
    "ドラッグ・薬局": (6.39, 3.61),
    "スーパー": (5.58, 1.41),
}
# 業態ごとの人口密度の上限（人/km²）。落ちるのはコンビニだけ
SCOPE = {"コンビニ": "1,500人/km²未満", "ドラッグ・薬局": "制限なし",
         "スーパー": "制限なし", "飲食": "制限なし"}

CSS = """
:root{
  color-scheme: light;
  --ground:#E9E7DF; --surface:#F2F0E9; --surface2:#E2DFD4;
  --ink:#23211C; --muted:#6E6A5E; --rule:#C9C6B8;
  --teal:#1F5C55; --rust:#8A3B2E; --sand:#B08A46;
  --ok:#2E6B4F; --warn:#9A6B1E;
  --ja:"Hiragino Kaku Gothic ProN","Hiragino Sans","Yu Gothic Medium",Meiryo,sans-serif;
  --mincho:"Hiragino Mincho ProN","Yu Mincho","Noto Serif JP",serif;
}
*{box-sizing:border-box}
body{margin:0;background:var(--ground);color:var(--ink);font-family:var(--ja);
  font-size:15px;line-height:1.8;letter-spacing:.03em;font-feature-settings:"palt" 1,"kern" 1;
  -webkit-font-smoothing:antialiased;-moz-osx-font-smoothing:grayscale}
p,li,td,th{word-break:normal;overflow-wrap:break-word;line-break:strict}
.wrap{max-width:1040px;margin:0 auto;padding:44px 20px 72px}
header{border-bottom:2px solid var(--ink);padding-bottom:20px;margin-bottom:26px}
.eyebrow{font-size:11.5px;letter-spacing:.22em;color:var(--rust);margin:0 0 10px}
h1{font-family:var(--mincho);font-size:clamp(26px,5vw,38px);line-height:1.35;margin:0 0 12px;
  font-weight:600;text-wrap:balance}
.lede{margin:0;max-width:62ch}
.stamp{font-size:12px;color:var(--muted);margin:12px 0 0;letter-spacing:.06em}

.controls{display:flex;flex-wrap:wrap;gap:20px;margin:0 0 18px;align-items:flex-end}
.group{display:flex;flex-direction:column;gap:7px}
.group>.label{font-size:11px;letter-spacing:.14em;color:var(--muted)}
.chips{display:flex;flex-wrap:wrap;gap:7px}
button.chip{font:inherit;font-size:13.5px;letter-spacing:.03em;padding:6px 15px;cursor:pointer;
  background:var(--surface);color:var(--ink);border:1px solid var(--rule);border-radius:999px;
  transition:background .12s,border-color .12s}
button.chip:hover{border-color:var(--teal)}
button.chip[aria-pressed="true"]{background:var(--teal);border-color:var(--teal);color:#F4F2EC}
button.chip:focus-visible{outline:2px solid var(--rust);outline-offset:2px}

.summary{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:12px;margin:0 0 22px}
.stat{background:var(--surface);border:1px solid var(--rule);padding:13px 16px}
.stat .k{display:block;font-size:11px;letter-spacing:.12em;color:var(--rust);margin-bottom:3px}
.stat .v{display:block;font-family:var(--mincho);font-size:25px;line-height:1.2;
  font-variant-numeric:tabular-nums}
.stat .n{display:block;font-size:12px;color:var(--muted)}

.scroll{overflow-x:auto;-webkit-overflow-scrolling:touch;border-top:1.5px solid var(--ink)}
table{border-collapse:collapse;width:100%;min-width:840px;font-size:14px;
  font-variant-numeric:tabular-nums}
th,td{padding:9px 10px;border-bottom:1px solid var(--rule);text-align:right;white-space:nowrap}
th:nth-child(2),td:nth-child(2){text-align:left;white-space:normal}
thead th{font-size:11.5px;letter-spacing:.06em;color:var(--muted);font-weight:600;
  cursor:pointer;user-select:none;background:var(--ground);position:sticky;top:0}
thead th:hover{color:var(--teal)}
thead th[aria-sort]{color:var(--teal)}
tbody tr:hover td{background:var(--surface)}
td.place{font-weight:600}
td.place .sub{display:block;font-weight:400;font-size:12px;color:var(--muted);letter-spacing:.02em}
.pill{display:inline-block;padding:1px 9px;border-radius:999px;font-size:12px;letter-spacing:.04em}
.pill.ok{background:#DCE7E3;color:var(--ok)}
.pill.warn{background:#EFE4CC;color:var(--warn)}
.pill.dead{background:var(--surface2);color:var(--muted)}
.empty{padding:26px 4px;color:var(--muted)}

.why{background:var(--surface);border-left:3px solid var(--sand);padding:16px 20px;margin-top:30px}
.why h2{font-family:var(--mincho);font-size:17px;margin:0 0 8px;font-weight:600}
.why p{margin:0 0 9px}.why p:last-child{margin-bottom:0}
.why table{min-width:420px;font-size:13.5px;margin-top:10px}
footer{margin-top:34px;padding-top:16px;border-top:1px solid var(--rule);
  font-size:12.5px;color:var(--muted)}
footer ul{margin:7px 0 0;padding-left:1.2em}
strong{font-weight:700}
"""

JS = """
const DATA = __DATA__;
const state = {fmt: 'コンビニ', verdict: 'すべて', sort: '順位', dir: 1};
const COLS = [
  ['順位','順位'], ['場所','場所'], ['期待店舗数','期待店舗数'],
  ['周辺人口','周辺人口'], ['周辺従業者','周辺従業者'], ['周辺の既存店','周辺の既存店'],
  ['1店あたり商圏人口','商圏人口/店'], ['判定','判定'], ['2050年比','2050年比'],
];

function rows(){
  let r = DATA.filter(d => d.業態 === state.fmt);
  if (state.verdict !== 'すべて') r = r.filter(d => d.判定 === state.verdict);
  const k = state.sort;
  return r.slice().sort((a,b) => {
    let x = k === '場所' ? a.市区町村 + a.町名 : a[k];
    let y = k === '場所' ? b.市区町村 + b.町名 : b[k];
    if (x === '—') x = Infinity;
    if (y === '—') y = Infinity;
    if (typeof x === 'string') return state.dir * String(x).localeCompare(String(y), 'ja');
    return state.dir * (x - y);
  });
}

function pill(v){
  const cls = v === '余地あり' ? 'ok' : v === '飽和ぎみ' ? 'warn' : 'dead';
  return `<span class="pill ${cls}">${v}</span>`;
}
const num = v => v === '—' ? '—' : Number(v).toLocaleString('ja-JP');

function render(){
  const r = rows();
  const yochi = r.filter(d => d.判定 === '余地あり').length;
  const q = document.getElementById('summary');
  q.innerHTML = [
    ['候補メッシュ', r.length, '500m四方・まだ1店も無い'],
    ['うち余地あり', yochi, '周辺が飽和していない'],
    ['期待店舗数の最大', r.length ? r.reduce((m,d)=>Math.max(m,d.期待店舗数),0).toFixed(2) : '—', 'モデルが見込む店舗数'],
    ['人口が増える所', r.filter(d => d['2050年比'] > 1).length, '2050年に期待が上がる'],
  ].map(([k,v,n]) => `<div class="stat"><span class="k">${k}</span>
      <span class="v">${typeof v === 'number' ? v.toLocaleString('ja-JP') : v}</span>
      <span class="n">${n}</span></div>`).join('');

  const body = r.map(d => `<tr>
    <td>${d.順位}</td>
    <td class="place">${d.市区町村}${d.町名}
      <span class="sub">${d.周辺従業者 > d.周辺人口 ? '昼の街（従業者が住民より多い）' : '住宅地より'}</span></td>
    <td>${d.期待店舗数.toFixed(2)}</td>
    <td>${num(d.周辺人口)}</td>
    <td>${num(d.周辺従業者)}</td>
    <td>${d.周辺の既存店}</td>
    <td>${num(d['1店あたり商圏人口'])}</td>
    <td>${pill(d.判定)}</td>
    <td>${d['2050年比'].toFixed(2)}</td></tr>`).join('');
  document.getElementById('tbody').innerHTML = body ||
    '<tr><td colspan="9" class="empty">この条件に当てはまる候補はありません。</td></tr>';

  document.querySelectorAll('thead th').forEach(th => {
    const k = th.dataset.k;
    if (k === state.sort) th.setAttribute('aria-sort', state.dir === 1 ? 'ascending' : 'descending');
    else th.removeAttribute('aria-sort');
  });
  document.querySelectorAll('button.chip').forEach(b => {
    b.setAttribute('aria-pressed', String(state[b.dataset.type] === b.dataset.v));
  });
}

document.addEventListener('click', e => {
  const chip = e.target.closest('button.chip');
  if (chip){ state[chip.dataset.type] = chip.dataset.v; render(); return; }
  const th = e.target.closest('thead th');
  if (th){
    const k = th.dataset.k;
    state.dir = (state.sort === k) ? -state.dir : (k === '順位' || k === '場所' ? 1 : -1);
    state.sort = k;
    render();
  }
});
document.getElementById('head').innerHTML =
  COLS.map(([k,label]) => `<th data-k="${k}" scope="col">${label}</th>`).join('');
render();
"""


def main() -> None:
    data = json.loads((OUT / "candidates.json").read_text(encoding="utf-8"))
    fmts = []
    for d in data:
        if d["業態"] not in fmts:
            fmts.append(d["業態"])

    chips = "".join(
        f'<button class="chip" type="button" data-type="fmt" data-v="{f}">{f}</button>'
        for f in fmts)
    vchips = "".join(
        f'<button class="chip" type="button" data-type="verdict" data-v="{v}">{v}</button>'
        for v in ("すべて", "余地あり", "飽和ぎみ"))

    rate_rows = "".join(
        f"<tr><td>{k}</td><td>{a:.2f}倍</td><td>{b:.2f}倍</td>"
        f"<td>{SCOPE.get(k, '制限なし')}</td></tr>"
        for k, (a, b) in RATES.items())

    html = f"""<title>空きマス台帳</title>
<style>{CSS}</style>
<div class="wrap">
<header>
  <p class="eyebrow">全国 500mメッシュ / 出店候補</p>
  <h1>まだ1店も無い場所を、見込み順に並べる</h1>
  <p class="lede">「どこに店があるか」を当てるのはモデルの仕事ではない。地図を見ればいい。モデルが唯一答えられるのは<strong>まだ1店も無いマスの順位づけ</strong>で、そこでは既存店舗数で並べる対抗馬は全マスが0で並ぶため原理的に順位をつけられない。全国の新規開店1,521件で測ると7.5〜8.4倍（コンビニの95%区間 7.3〜7.7）。</p>
  <p class="stamp">候補{len(data)}件 ／ 全国47都道府県 471,024メッシュのうち店舗数0のマス ／ 周りにも1店も無い「空白地帯」と、コンビニについては人口密度1,500人/km²以上を除外</p>
</header>

<div class="controls">
  <div class="group"><span class="label">業態</span><div class="chips">{chips}</div></div>
  <div class="group"><span class="label">周辺の混み具合</span><div class="chips">{vchips}</div></div>
</div>

<div class="summary" id="summary"></div>

<div class="scroll">
  <table>
    <thead><tr id="head"></tr></thead>
    <tbody id="tbody"></tbody>
  </table>
</div>

<div class="why">
  <h2>判定の読み方</h2>
  <p><strong>商圏人口/店</strong>は、周辺3×3マスの商圏人口を既存店の数で割った値。
  商圏人口は<strong>居住人口＋従業者数</strong>で、住民が少なく昼間人口が多い工業団地のような
  場所を「飽和」と誤判定しないため。閾値は2,200人。</p>
  <p>この判定は決めつけではなく、全国の新規開店1,521件で検定してある。
  まだ店の無いマス全体の開店率を1.00倍としたときの、判定別の開店率は次のとおり。</p>
  <div class="scroll" style="border:0">
  <table>
    <thead><tr><th scope="col">業態</th><th scope="col">余地あり</th>
      <th scope="col">飽和ぎみ</th><th scope="col">対象にする密度</th></tr></thead>
    <tbody>{rate_rows}</tbody>
  </table>
  </div>
  <p style="margin-top:10px"><strong>密集地を対象にするかどうかは業態で違う。</strong>
  周辺人口密度を上げていくと、コンビニの倍率は 5.7倍（500人/km²未満）から
  2.3倍（6,000人/km²以上）まで落ちるが、スーパーは 5.8倍から 4.7倍にしか落ちない。
  店の数が少ない業態は、都心でも立地が地理で決まるため。だから一律に大都市圏を外すのではなく、
  落ちる業態だけ、落ちる密度から外している。</p>
  <p>なお密集地だけで学習し直しても直らない（−0.6／−0.3／+0.4）。
  情報の側の問題で、密集地の空きマスは条件がどれも似ている
  （期待店舗数の四分位の開きが、全体では14.8倍あるのに密集帯では2.9倍しかない）。</p>
  <p><strong>2050年比</strong>は、将来推計人口だけを差し替えて期待店舗数を計算し直した比。
  従業者数の将来推計は存在しないので据え置いてある。ここは仮定であり、検証していない。</p>
</div>

<footer>
  <p>データ源（すべて再配布可）</p>
  <ul>
    <li>店舗 ── Foursquare OS Places（営業中のみ）</li>
    <li>人口 ── 国土数値情報 500mメッシュ別将来推計人口（2020／2050）</li>
    <li>従業者数 ── e-Stat 統計GIS 経済センサス活動調査 500mメッシュ（T000918・平成28年）</li>
    <li>開店実績 ── 国税庁 酒類販売業免許の新規取得者名等一覧 ／
      厚生労働省 食品衛生申請等システム オープンデータ</li>
    <li>地名 ── 国土地理院 逆ジオコーディング</li>
  </ul>
</footer>
</div>
<script>{JS.replace("__DATA__", json.dumps(data, ensure_ascii=False))}</script>
"""
    path = OUT / "viewer.html"
    path.write_text(html, encoding="utf-8")
    print(f"-> {path}  {len(html)/1024:.0f}KB  候補{len(data)}件")


if __name__ == "__main__":
    main()
