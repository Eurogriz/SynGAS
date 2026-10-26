"""Live control panel for the SynGAS V2 model (user answers 2/7).

Run:  PYTHONPATH=. .venv/bin/python -m web.app
Binds 0.0.0.0:5000 so the Arena preview proxy can reach it. The browser calls
relative /api/* URLs only - never localhost.
"""
from __future__ import annotations
import json, os, threading, time
from flask import Flask, jsonify, request, send_from_directory, Response

from model.config import Config, load_config, DEFAULT_PATH
from model.products import design
from model.scenarios import (PRODUCTS, run_base, run_regulation_sweep,
                             run_normal_comparison, run_eos_sensitivity, _compact)
from model.run_v2 import to_jsonable, dump_json
from model.verify_v2 import run_all as verify_all

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "results_v2")
app = Flask(__name__)
_LOCK = threading.Lock()
_CACHE = {}


def _cfg_raw():
    return Config.load().raw


def _run(product, overrides, no_tune=False):
    key = json.dumps([product, overrides, no_tune], sort_keys=True, default=str)
    with _LOCK:
        if key in _CACHE:
            return _CACHE[key]
    e = load_config(overrides=overrides, product=product)
    r = design(e, do_tune=not no_tune)
    with _LOCK:
        _CACHE[key] = r
        if len(_CACHE) > 40:
            _CACHE.pop(next(iter(_CACHE)))
    return r


def _brief(r):
    s, u, f, e, c, eq = (r["spec"], r["utilities"], r["flows"], r["economics"],
                         r["catalyst"], r["equipment"])
    return {
        "product": r["product"], "normal": r["normal"], "climate": r["climate"],
        "feed": r["feed"], "Vm_m3_per_mol": r["Vm_m3_per_mol"],
        "metric": s["metric"], "target": s["target"], "achieved": s["achieved"],
        "hit_target": s["within_tolerance"], "carbon_stable": s["carbon_stable"],
        "limit_checks": s["limit_checks"],
        "composition": {"H2_molpct": s["H2_purity_molpct"],
                        "CO2_molpct": s["CO2_molpct"],
                        "CH4_molpct": s["CH4_molpct"],
                        "N2_molpct": s["N2_molpct"],
                        "H2O_molpct": s["H2O_molpct"],
                        "CO_ppm": s["CO_ppm"], "CO2_ppm": s["CO2_ppm"]},
        "knobs": r["knobs"], "tuning": r["tuning"],
        "X_CH4": r["reformer"]["equilibrium"]["CH4_conversion"],
        "T_reformer_K": r["reformer"]["T_out_K"],
        "p_bar": r["reformer"]["p_bar"], "Z": r["eos"]["Z"],
        "flows": f,
        "utilities": u,
        "catalyst": {k: c[k] for k in
                     ("total_catalyst_volume_m3", "total_catalyst_mass_t",
                      "total_Ni_inventory_t", "Ni_consumption_t_per_y",
                      "catalyst_consumption_t_per_y", "ZnO_guard_mass_kg",
                      "design_life_years", "life_sensitivity")},
        "equipment": {k: eq[k] for k in
                      ("reactor_type", "tubes_installed", "T_wall_max_K",
                       "Ergun_dP_bar", "creep", "vessel_diameter_m")},
        "economics": e,
        "eos": r["eos"], "steam": r["steam"], "status": r["status"],
        "synthesis": r.get("synthesis"), "safety": r.get("safety"),
        "prereformer": r["reformer"].get("prereformer"),
    }


@app.get("/")
def index():
    return Response(HTML, mimetype="text/html")


@app.get("/api/health")
def health():
    return jsonify({"ok": True, "hysys": "NOT RUN - Python/DWSIM-equivalent",
                    "products": PRODUCTS, "cache": len(_CACHE)})


@app.get("/api/config")
def api_config():
    raw = _cfg_raw()
    return jsonify({"raw": raw, "products": PRODUCTS,
                    "normals": [k for k in raw["normal_conditions"] if k != "note"],
                    "climates": list(raw["climates"]),
                    "feeds": list(raw["feeds"]),
                    "kij_sets": raw["eos"]["kij_sensitivity"]})


@app.post("/api/config")
def api_config_save():
    body = request.get_json(force=True) or {}
    overrides = body.get("overrides") or {}
    save = bool(body.get("save"))
    cfg = Config.load()
    cfg.apply(overrides)
    if save:
        cfg.save(DEFAULT_PATH)
    e = cfg.resolve(body.get("product") or cfg.raw["active"]["product"])
    return jsonify({"saved": save, "effective": to_jsonable(e.describe()),
                    "knobs": e.knobs})


@app.post("/api/run")
def api_run():
    body = request.get_json(force=True) or {}
    product = body.get("product") or "methanol"
    if product not in PRODUCTS:
        return jsonify({"error": f"unknown product {product}"}), 400
    ov = body.get("overrides") or {}
    t0 = time.time()
    try:
        r = _run(product, ov, bool(body.get("no_tune")))
    except Exception as exc:
        import traceback
        return jsonify({"error": str(exc), "trace": traceback.format_exc()}), 500
    return jsonify(to_jsonable({"brief": _brief(r),
                                "runtime_s": round(time.time() - t0, 2)}))


@app.post("/api/compare")
def api_compare():
    body = request.get_json(force=True) or {}
    ov = body.get("overrides") or {}
    t0 = time.time()
    try:
        rows, full = [], {}
        for p in PRODUCTS:
            r = _run(p, ov)
            rows.append(_compact(r))
            full[p] = _brief(r)
    except Exception as exc:
        import traceback
        return jsonify({"error": str(exc), "trace": traceback.format_exc()}), 500
    return jsonify(to_jsonable({"rows": rows, "full": full,
                                "runtime_s": round(time.time() - t0, 2),
                                "plot": "/plot/01_product_comparison.png"}))


@app.post("/api/sweep")
def api_sweep():
    body = request.get_json(force=True) or {}
    product = body.get("product") or "methanol"
    try:
        rows = [x for x in run_regulation_sweep() if x["product"] == product]
    except Exception as exc:
        return jsonify({"error": str(exc)}), 500
    return jsonify(to_jsonable({"product": product, "rows": rows,
                                "plot": "/plot/05_regulation_sweep.png"}))


@app.post("/api/verify")
def api_verify():
    t0 = time.time()
    try:
        base = run_base()
        sc = {"eos_sensitivity": run_eos_sensitivity()}
        v = verify_all(base, sc)
    except Exception as exc:
        return jsonify({"error": str(exc)}), 500
    return jsonify(to_jsonable({"summary": v["summary"],
                                "overall_passed": v["overall_passed"],
                                "hysys": v["hysys"],
                                "unchecked": v["loops"]["5_validation_falsification"]["unchecked_items"],
                                "runtime_s": round(time.time() - t0, 1)}))


@app.get("/plot/<path:name>")
def plot(name):
    if not name.endswith(".png") or "/" in name or ".." in name:
        return "", 404
    return send_from_directory(OUT, name)


@app.get("/report/<path:name>")
def report(name):
    if "/" in name or ".." in name or not name.endswith(".md"):
        return "", 404
    p = os.path.join(ROOT, "docs", name)
    if not os.path.exists(p):
        return "", 404
    return Response(open(p, encoding="utf-8").read(), mimetype="text/plain; charset=utf-8")


HTML = r"""<!doctype html>
<html lang="ru"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>SynGAS V2 — control panel</title>
<style>
:root{--bg:#0d1117;--pan:#161b22;--line:#30363d;--txt:#e6edf3;--mut:#8b949e;
--ok:#3fb950;--bad:#f85149;--acc:#58a6ff;--warn:#d29922}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--txt);
font:14px/1.5 -apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,sans-serif}
header{padding:14px 20px;border-bottom:1px solid var(--line);display:flex;
justify-content:space-between;align-items:center;background:var(--pan)}
header h1{font-size:17px;margin:0}header .tag{font-size:12px;color:var(--mut)}
.wrap{display:grid;grid-template-columns:340px 1fr;min-height:calc(100vh - 56px)}
aside{border-right:1px solid var(--line);padding:16px;overflow:auto;max-height:calc(100vh - 56px)}
main{padding:18px 22px;overflow:auto;max-height:calc(100vh - 56px)}
h2{font-size:13px;text-transform:uppercase;letter-spacing:.08em;color:var(--mut);
margin:18px 0 8px;border-bottom:1px solid var(--line);padding-bottom:5px}
h2:first-child{margin-top:0}
label{display:block;font-size:12px;color:var(--mut);margin:8px 0 3px}
input,select{width:100%;padding:6px 8px;background:#0d1117;color:var(--txt);
border:1px solid var(--line);border-radius:5px;font-size:13px}
.grid2{display:grid;grid-template-columns:1fr 1fr;gap:8px}
.grid3{display:grid;grid-template-columns:1fr 1fr 1fr;gap:8px}
button{cursor:pointer;border:1px solid var(--line);background:#21262d;color:var(--txt);
padding:9px 12px;border-radius:6px;font-size:13px;margin:6px 6px 0 0}
button.primary{background:#1f6feb;border-color:#1f6feb;color:#fff;font-weight:600}
button:hover{filter:brightness(1.18)}
.cards{display:grid;grid-template-columns:repeat(auto-fit,minmax(160px,1fr));gap:10px;margin-bottom:16px}
.card{background:var(--pan);border:1px solid var(--line);border-radius:8px;padding:11px}
.card .k{font-size:11px;color:var(--mut);text-transform:uppercase;letter-spacing:.05em}
.card .v{font-size:21px;font-weight:650;margin-top:3px}
.card .u{font-size:11px;color:var(--mut)}
table{border-collapse:collapse;width:100%;margin:8px 0 16px;font-size:12.5px}
th,td{border:1px solid var(--line);padding:5px 8px;text-align:left}
th{background:var(--pan);color:var(--mut);font-weight:600}
.pass{color:var(--ok);font-weight:600}.fail{color:var(--bad);font-weight:600}
.warn{color:var(--warn)}
.note{background:#161b22;border-left:3px solid var(--warn);padding:9px 12px;
font-size:12.5px;margin:10px 0;color:var(--mut)}
pre{background:#0d1117;border:1px solid var(--line);padding:10px;overflow:auto;
font-size:11.5px;border-radius:6px;max-height:260px}
img{max-width:100%;border:1px solid var(--line);border-radius:6px;margin-top:8px}
.tabs{display:flex;gap:4px;margin:12px 0 8px;flex-wrap:wrap}
.tabs button{margin:0}
.hidden{display:none}
a{color:var(--acc)}
</style></head><body>
<header><h1>SynGAS V2 · Ni/MgAl₂O₄ · контрольная панель</h1>
<span class="tag">HYSYS не запускался · Python/DWSIM-эквивалент подтверждён · цикл 5 открыт</span></header>
<div class="wrap"><aside>
<h2>Вариант продукта</h2>
<label>Целевой продукт</label><select id="product"></select>
<label>Нормальный м³</label><select id="normal"></select>
<label>Площадка</label><select id="climate"></select>
<label>Сырьё (газ)</label><select id="feed"></select>
<label>Peng–Robinson k<sub>ij</sub></label><select id="kij"></select>
<label>Par IAPWS-IF97</label><select id="steam_table"><option value="IAPWS97">IAPWS-IF97 (max accuracy)</option>
<option value="NIST">NIST Shomate/Antoine fallback</option></select>
<h2>Регулировка процесса</h2>
<div class="grid2">
<div><label>Мощность</label><input id="capacity" type="number" step="1000"></div>
<div><label>S/C</label><input id="SC" type="number" step="0.05"></div>
<div><label>CO₂/C</label><input id="CO2C" type="number" step="0.01"></div>
<div><label>O₂/C</label><input id="O2C" type="number" step="0.01"></div>
<div><label>T, K</label><input id="T_K" type="number" step="5"></div>
<div><label>p, bar(a)</label><input id="p_bar" type="number" step="0.5"></div>
<div><label>Approach, K</label><input id="approach_K" type="number" step="1"></div>
<div><label>КПД печи</label><input id="furnace_eff" type="number" step="0.01"></div>
</div>
<h2>Катализатор / Ni</h2>
<div class="grid2">
<div><label>Ni, мас.%</label><input id="ni_wt" type="number" step="0.5"></div>
<div><label>Срок, лет</label><input id="life" type="number" step="0.5"></div>
<div><label>GHSV, 1/ч</label><input id="ghsv" type="number" step="100"></div>
<div><label>Плотность, кг/м³</label><input id="rho" type="number" step="10"></div>
<div><label>Ni, USD/т</label><input id="ni_price" type="number" step="500"></div>
</div>
<h2>Утилиты и цены</h2>
<div class="grid2">
<div><label>Газ, USD/MMBtu</label><input id="gas" type="number" step="0.5"></div>
<div><label>Эл-во, USD/MWh</label><input id="power_price" type="number" step="5"></div>
<div><label>CO₂, USD/т</label><input id="co2_price" type="number" step="5"></div>
<div><label>Пар, USD/т</label><input id="steam_price" type="number" step="1"></div>
<div><label>Пар p, bar</label><input id="steam_p" type="number" step="1"></div>
<div><label>Пар T, K</label><input id="steam_T" type="number" step="5"></div>
</div>
<label style="margin-top:12px">Дополнительные переопределения (JSON, точечные ключи)</label>
<textarea id="extra_ov" rows="3" placeholder='{"products.hydrogen.knobs.PSA_H2_recovery":0.90,"process.prereformer_enabled":false}' style="width:100%;background:#0d1117;color:#e6edf3;border:1px solid #30363d;border-radius:5px;font:12px monospace;padding:6px"></textarea>
<div style="margin-top:14px">
<button class="primary" onclick="runOne()">▶ Рассчитать</button>
<button onclick="compare()">Сравнить 5 продуктов</button>
<button onclick="sweep()">Регулировочная кривая</button>
<button onclick="verify()">5 циклов проверки</button>
<button onclick="reset()">Сброс</button>
<button onclick="download()">Скачать config</button>
</div>
<div class="note" id="status">Готово. Изменения не записываются в cases/config.json — только в расчёт.</div>
</aside><main>
<div class="cards" id="cards"></div>
<div class="tabs"><button onclick="tab('t1',this)">Спецификация</button>
<button onclick="tab('t2',this)">Утилиты</button>
<button onclick="tab('t3',this)">Катализатор / Ni</button>
<button onclick="tab('t4',this)">Оборудование</button>
<button onclick="tab('t5',this)">Экономика</button>
<button onclick="tab('t6',this)">Сравнение / графики</button>
<button onclick="tab('t7',this)">JSON</button>
<button onclick="tab('t8',this)">Синтез</button>
<button onclick="tab('t9',this)">Безопасность</button></div>
<div id="t1"></div><div id="t2" class="hidden"></div><div id="t3" class="hidden"></div>
<div id="t4" class="hidden"></div><div id="t5" class="hidden"></div>
<div id="t6" class="hidden"></div><div id="t7" class="hidden"><pre id="raw"></pre></div>
<div id="t8" class="hidden"></div><div id="t9" class="hidden"></div>
</main></div>
<script>
let CFG=null, LAST=null;
const $=id=>document.getElementById(id);
const fmt=(x,n=3)=>x===null||x===undefined||Number.isNaN(+x)?'—':(+x).toFixed(n);
const tbl=(head,rows)=>'<table><tr>'+head.map(h=>'<th>'+h+'</th>').join('')+'</tr>'+
 rows.map(r=>'<tr>'+r.map(c=>'<td>'+c+'</td>').join('')+'</tr>').join('')+'</table>';
const say=(m,bad=false)=>{$('status').textContent=m;$('status').style.borderLeftColor=bad?'#f85149':'#d29922'};
function tab(id,btn){['t1','t2','t3','t4','t5','t6','t7','t8','t9'].forEach(x=>$(x).classList.toggle('hidden',x!==id));}
async function init(){CFG=(await (await fetch('/api/config')).json());
 const P=CFG.raw.products, A=CFG.raw.active, C=CFG.raw.catalyst, E=CFG.raw.economics, PR=CFG.raw.process;
 const fill=(id,arr,val)=>{$(id).innerHTML=arr.map(x=>`<option ${x===val?'selected':''}>${x}</option>`).join('')};
 fill('product',CFG.products,A.product);fill('normal',CFG.normals,A.normal);
 fill('climate',CFG.climates,A.climate);fill('feed',CFG.feeds,A.feed);
 fill('kij',CFG.kij_sets,CFG.raw.eos.kset);$('steam_table').value=A.steam_table;
 const setK=p=>{const k=P[p].knobs;$('capacity').value=P[p].capacity;$('SC').value=k.SC;
  $('CO2C').value=k.CO2C;$('O2C').value=k.O2C;$('T_K').value=k.T_K;
  $('p_bar').value=k.p_bar;$('approach_K').value=k.approach_K;};
 setK(A.product);$('product').onchange=()=>setK($('product').value);
 $('furnace_eff').value=PR.furnace_efficiency_LHV;
 $('ni_wt').value=C.Ni_wt_pct_metal;$('life').value=C.life_years;
 $('ghsv').value=C.GHSV_reformer_Nm3_per_m3cat_h;$('rho').value=C.commercial_proxy_loaded_density_kg_m3;
 $('ni_price').value=C.Ni_price_USD_per_t;
 $('gas').value=E.gas_USD_per_MMBtu;$('power_price').value=E.electricity_USD_per_MWh;
 $('co2_price').value=E.CO2_USD_per_t;$('steam_price').value=E.steam_USD_per_t;
 $('steam_p').value=PR.steam_p_bar_abs;$('steam_T').value=PR.steam_T_K;
 say('Конфигурация загружена. Нажмите «Рассчитать».');}
function reset(){init();}
function overrides(){
 const p=$('product').value, k='products.'+p+'.knobs.', o={};
 o['active.product']=p; o['active.normal']=$('normal').value;
 o['active.climate']=$('climate').value; o['active.feed']=$('feed').value;
 o['eos.kset']=$('kij').value; o['active.steam_table']=$('steam_table').value;
 o['products.'+p+'.capacity']=+$('capacity').value;
 o[k+'SC']=+$('SC').value; o[k+'CO2C']=+$('CO2C').value;
 o[k+'O2C']=+$('O2C').value; o[k+'T_K']=+$('T_K').value;
 o[k+'p_bar']=+$('p_bar').value; o[k+'approach_K']=+$('approach_K').value;
 o['process.furnace_efficiency_LHV']=+$('furnace_eff').value;
 o['catalyst.Ni_wt_pct_metal']=+$('ni_wt').value;
 o['catalyst.life_years']=+$('life').value;
 o['catalyst.GHSV_reformer_Nm3_per_m3cat_h']=+$('ghsv').value;
 o['catalyst.commercial_proxy_loaded_density_kg_m3']=+$('rho').value;
 o['catalyst.Ni_price_USD_per_t']=+$('ni_price').value;
 o['economics.gas_USD_per_MMBtu']=+$('gas').value;
 o['economics.electricity_USD_per_MWh']=+$('power_price').value;
 o['economics.CO2_USD_per_t']=+$('co2_price').value;
 o['economics.steam_USD_per_t']=+$('steam_price').value;
 o['process.steam_p_bar_abs']=+$('steam_p').value;
 o['process.steam_T_K']=+$('steam_T').value;
 try{Object.assign(o,JSON.parse($('extra_ov').value||'{}'));}
 catch(e){say('Ошибка JSON в доп. переопределениях: '+e.message,true);throw e;}
 return o;
}
function cards(b){$('cards').innerHTML=[
 ['Метрика',fmt(b.achieved,4),b.metric+' · цель '+fmt(b.target,3)],
 ['Попадание','<span class="'+(b.hit_target?'pass':'fail')+'">'+(b.hit_target?'ДА':'НЕТ')+'</span>','лимиты: '+(Object.values(b.limit_checks).every(x=>x.pass)?'<span class="pass">все</span>':'<span class="fail">есть нарушения</span>')],
 ['X_CH4',fmt(b.X_CH4,4),'T '+fmt(b.T_reformer_K,0)+' K · Z '+fmt(b.Z,5)],
 ['Ni инвентарь',fmt(b.catalyst.total_Ni_inventory_t,2),'т · '+fmt(b.catalyst.total_catalyst_volume_m3,1)+' м³'],
 ['Стоимость',fmt(b.economics.levelised_cost,2),b.economics.unit],
 ['CO₂ нетто',fmt(b.utilities.CO2_net_t_h,2),'т/ч'],
 ['Продукт',fmt((b.synthesis||{}).methanol_t_h||(b.synthesis||{}).C5plus_t_h||(b.synthesis||{}).aldehyde_t_h||(b.synthesis||{}).H2_t_h||(b.synthesis||{}).NH3_t_h,2),'т/ч'],
].map(x=>'<div class="card"><div class="k">'+x[0]+'</div><div class="v">'+x[1]+'</div><div class="u">'+x[2]+'</div></div>').join('');}
function render(b){cards(b);
 const lc=Object.entries(b.limit_checks).map(([k,v])=>[k,fmt(v.limit,4),fmt(v.value,4),
  '<span class="'+(v.pass?'pass':'fail')+'">'+(v.pass?'PASS':'FAIL')+'</span>']);
 $('t1').innerHTML='<h2>Качество продукта</h2>'+tbl(['параметр','лимит','значение','статус'],lc)
 +'<h2>Состав сухого газа</h2>'+tbl(['компонент','значение'],Object.entries(b.composition).map(([k,v])=>
  [k,fmt(v,4)+(k.includes('ppm')?' ppm':' мол.%')]))
 +'<h2>Настроенные параметры</h2>'+tbl(['параметр','значение'],Object.entries(b.knobs).map(([k,v])=>[k,fmt(v,5)]))
 +'<div class="note">'+b.status.hysys+' · '+b.status.validation+'</div>';
 const u=b.utilities;$('t2').innerHTML='<h2>Утилиты</h2>'+tbl(['показатель','значение','ед.'],
 [['Тепло реформера',fmt(u.Q_reformer_kW,0),'кВт'],['Топливо',fmt(u.fuel_Nm3_h,0),'Нм³/ч'],
 ['CO₂ от топлива',fmt(u.CO2_from_fuel_t_h,2),'т/ч'],['CO₂ уловленный',fmt(u.CO2_captured_t_h,2),'т/ч'],
 ['Пар нетто-экспорт',fmt(u.steam_net_export_t_h,2),'т/ч'],['Охлаждение',fmt(u.cooling_duty_kW,0),'кВт'],
 ['Оборотная вода',fmt(u.cooling_water_m3_h,0),'м³/ч'],
 ['Воздух на выходе АВО',fmt(u.air_cooler_outlet_C,1),'°C'],
 ['Нужен доводчик',u.trim_cooling_required?'ДА':'нет','—'],
 ['O₂ (ASU)',fmt(u.O2_t_h,2),'т/ч'],['Мощность ASU',fmt(u.ASU_power_MW,2),'МВт'],
 ['Всего мощность',fmt(u.total_power_MW,2),'МВт']]);
 const c=b.catalyst;$('t3').innerHTML='<h2>Катализатор Ni/MgAl₂O₄</h2>'+tbl(['показатель','значение','ед.'],
 [['Объём',fmt(c.total_catalyst_volume_m3,2),'м³'],['Масса',fmt(c.total_catalyst_mass_t,2),'т'],
 ['Ni инвентарь',fmt(c.total_Ni_inventory_t,3),'т'],['Срок службы',fmt(c.design_life_years,1),'лет'],
 ['Расход катализатора',fmt(c.catalyst_consumption_t_per_y,2),'т/год'],
 ['Подпитка Ni',fmt(c.Ni_consumption_t_per_y,3),'т/год'],['ZnO',fmt(c.ZnO_guard_mass_kg,0),'кг']])
 +'<h2>Чувствительность к сроку службы</h2>'+tbl(['лет','Ni т/год','кат. т/год'],
  c.life_sensitivity.map(x=>[x.life_years,fmt(x.Ni_consumption_t_per_y,3),fmt(x.catalyst_consumption_t_per_y,2)]));
 const eq=b.equipment,cr=eq.creep||{};$('t4').innerHTML='<h2>Оборудование</h2>'+tbl(['показатель','значение'],
 [['Тип реактора',eq.reactor_type],['Трубы',fmt(eq.tubes_installed,0)],
 ['T стенки макс.',fmt(eq.T_wall_max_K,1)+' K'],['Δp (Ergun)',fmt(eq.Ergun_dP_bar,3)+' bar'],
 ['LMP',fmt(cr.LMP,3)],['Допуск напряжение',fmt(cr.allowable_stress_MPa,2)+' МПа'],
 ['Требуемая толщина',cr.required_wall_thickness_m?fmt(cr.required_wall_thickness_m,5)+' м':'n/a (ATR)'],
 ['Принятая толщина',cr.specified_wall_thickness_m?fmt(cr.specified_wall_thickness_m,5)+' м':'n/a (ATR)']]);
 const e=b.economics;$('t5').innerHTML='<h2>Экономика (класс 5, ±50%)</h2>'+tbl(['статья','USD/год'],
 [['Газ',fmt(e.gas_cost_USD_y,0)],['CO₂',fmt(e.CO2_cost_USD_y,0)],['Электроэнергия',fmt(e.power_cost_USD_y,0)],
 ['Охлаждающая вода',fmt(e.cooling_water_cost_USD_y,0)],['Катализатор',fmt(e.catalyst_cost_USD_y,0)],
 ['Кредит за пар',fmt(-e.steam_credit_USD_y,0)],['Fixed OPEX',fmt(e.fixed_OPEX_USD_y,0)],
 ['Всего OPEX',fmt(e.total_OPEX_USD_y,0)],['CAPEX',fmt(e.CAPEX_USD,0)],
 ['Аннуитет CAPEX',fmt(e.annualised_CAPEX_USD_y,0)]])
 +'<div class="note">Удельная стоимость: <b>'+fmt(e.levelised_cost,2)+' '+e.unit+'</b>. '
 +e.status+'</div>';
 const sy=b.synthesis||{}, saf=b.safety||{};
 $('t8').innerHTML='<h2>Контур синтеза (стехиометрия, не кинетика)</h2>'+tbl(['параметр','значение'],
  Object.entries(sy).filter(([k,v])=>typeof v!=='object'&&v!==null&&k!=='source'&&k!=='note')
   .map(([k,v])=>[k,(typeof v==='number'?fmt(v,3):String(v))]))
  +'<div class="note">'+(sy.status||'')+' '+(sy.note||'')+'</div>';
 const sc=(saf.Ni_CO_4||{}).shutdown_scenarios||[];
 $('t9').innerHTML='<h2>Ni(CO)₄ при остановке</h2>'+tbl(['T C','без продувки ppb','после продувки ppb'],
  sc.map(x=>[fmt(x.T_C,0),x.NiCO4_ppb_unpurged.toExponential(2),x.NiCO4_ppb_after_purge.toExponential(2)]))
  +'<h2>Предохранительный клапан (скрининг)</h2>'+tbl(['параметр','значение'],
   [['отверстие, мм',fmt((saf.relief||{}).orifice_diameter_mm,1)],
    ['p уст., бар',fmt((saf.relief||{}).p_set_bar,1)],
    ['нагрузка, кг/с',fmt((saf.relief||{}).relief_load_kg_s,2)]])
  +'<div class="note">'+((saf.Ni_CO_4||{}).conclusion||'')+'</div>'
  +'<h2>HAZOP (скрининг)</h2>'+tbl(['узел','отклонение','защита'],
   (saf.HAZOP_nodes||[]).map(h=>[h.node,h.deviation,h.safeguard]));
 $('raw').textContent=JSON.stringify(b,null,2);}
async function call(url,body){say('Расчёт…');const t=Date.now();
 const res=await fetch(url,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body||{})});
 const j=await res.json();say('Готово за '+((Date.now()-t)/1000).toFixed(1)+' с'+
  (j.runtime_s?' (модель '+j.runtime_s+' с)':'')+(j.error?' ОШИБКА: '+j.error:''),!!j.error);return j;}
async function runOne(){const j=await call('/api/run',{product:$('product').value,overrides:overrides()});
 if(j.brief){LAST=j.brief;render(LAST);tab('t1');}}
async function compare(){const j=await call('/api/compare',{overrides:overrides()});
 if(j.rows){$('t6').innerHTML='<h2>Сравнение пяти продуктов</h2>'+tbl(
 ['продукт','метрика','цель','достигнуто','CO₂ мол.%','Ni т','стоимость','ед.'],
 j.rows.map(r=>[r.product,r.metric,fmt(r.target,3),fmt(r.achieved,4),fmt(r.CO2_molpct,2),
 fmt(r.Ni_inventory_t,2),fmt(r.levelised_cost,2),r.cost_unit]))
 +'<h2>Оба определения нормального м³</h2><img src="/plot/02_normal_comparison.png">'
 +'<h2>Диаграммы</h2><img src="/plot/01_product_comparison.png">'
 +'<img src="/plot/07_nickel_inventory.png">';tab('t6');}}
async function sweep(){const j=await call('/api/sweep',{product:$('product').value});
 if(j.rows){$('t6').innerHTML='<h2>Регулировка: '+j.product+'</h2>'+tbl(['параметр','значение','метрика','цель','X_CH4','T K'],
  j.rows.map(r=>[r.knob,fmt(r.value,4),fmt(r.achieved,4),fmt(r.target,3),fmt(r.X_CH4,4),fmt(r.T_reformer_K,1)]))
 +'<img src="/plot/05_regulation_sweep.png">';tab('t6');}}
async function verify(){const j=await call('/api/verify',{});
 if(j.summary){$('t6').innerHTML='<h2>Пять циклов проверки</h2>'+tbl(['цикл','статус'],
  Object.entries(j.summary).map(([k,v])=>[k,'<span class="'+(v?'pass':'fail')+'">'+(v?'PASS':'FAIL')+'</span>']))
 +'<div class="note">'+j.hysys+'</div><h2>Не проверено</h2><ol>'+
  j.unchecked.map(x=>'<li>'+x+'</li>').join('')+'</ol>';tab('t6');}}
function download(){const blob=new Blob([JSON.stringify({overrides:overrides(),raw:CFG.raw},null,2)],
 {type:'application/json'});const a=document.createElement('a');a.href=URL.createObjectURL(blob);
 a.download='syngas_config.json';a.click();}
init();
</script></body></html>"""


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "5000")),
            debug=False, threaded=True)
