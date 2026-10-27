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
        "kinetic": r["synthesis"].get("kinetic") if r.get("synthesis") else None,
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


@app.get("/api/pilot")
def api_pilot():
    """External pilot-data comparison (fast, no full verification)."""
    from model.pilot_data import run_external_comparison
    try:
        return jsonify(to_jsonable(run_external_comparison(load_config())))
    except Exception as exc:
        return jsonify({"error": str(exc)}), 500


@app.post("/api/verify")
def api_verify():
    t0 = time.time()
    try:
        base = run_base()
        sc = {"eos_sensitivity": run_eos_sensitivity()}
        v = verify_all(base, sc)
    except Exception as exc:
        return jsonify({"error": str(exc)}), 500
    l5 = v["loops"]["5_validation_falsification"]
    return jsonify(to_jsonable({"summary": v["summary"],
                                "overall_passed": v["overall_passed"],
                                "hysys": v["hysys"],
                                "loop5_status": l5["status"],
                                "loop5_subchecks": l5["subchecks"],
                                "loop5_subchecks_passed": l5["subchecks_passed"],
                                "loop5_subchecks_total": l5["subchecks_total"],
                                "mean_pilot_bias": l5["external_data"]["mean_model_bias"],
                                "unchecked": l5["unchecked_items"],
                                "runtime_s": round(time.time() - t0, 1)}))


@app.get("/api/converter")
def api_converter():
    """V5 multi-bed adiabatic NH3 converter. Uses the saved run when present;
    otherwise computes it once (tens of seconds) and caches it."""
    path = os.path.join(ROOT, "results_v2", "converter_ammonia.json")
    if os.path.exists(path):
        try:
            with open(path, "r", encoding="utf-8") as fh:
                obj = json.load(fh)
            obj["from_saved_run"] = True
            return jsonify(to_jsonable(obj))
        except Exception as exc:
            return jsonify({"error": str(exc)}), 500
    if "converter" in _CACHE:
        return jsonify(to_jsonable(_CACHE["converter"]))
    from model.converter import ammonia_converter_block
    try:
        r = _run("ammonia", {}, no_tune=False)
        obj = ammonia_converter_block(load_config(product="ammonia"), r)
        obj["from_saved_run"] = False
        _CACHE["converter"] = obj
        return jsonify(to_jsonable(obj))
    except Exception as exc:
        return jsonify({"error": str(exc)}), 500


@app.get("/api/quality")
def api_quality():
    """V5.1/V5.2 model-quality pack: the model's own input-uncertainty band on
    X_CH4, the methanol adiabatic benchmark against the opened VBF worked case,
    and the catalyst-activity corridor of the ammonia converter.

    All three are read from the saved run when present; otherwise they are
    computed once (tens of seconds) and cached. None of them is a validation:
    the first shows that input uncertainty cannot explain the pilot gap, the
    second is a model-to-model reproduction of a published simulation, and the
    third only propagates a disagreement between two opened literature
    benchmarks through volume, peak temperature, duty and cost."""
    out = {"from_saved_run": True}
    files = {"uncertainty": ("model_uncertainty.json", None),
             "methanol_adiabatic": ("methanol_adiabatic_check.json", None),
             "activity_band": ("activity_uncertainty.json", None)}
    missing = []
    for key, (fn, _f) in files.items():
        path = os.path.join(ROOT, "results_v2", fn)
        if os.path.exists(path):
            try:
                with open(path, "r", encoding="utf-8") as fh:
                    out[key] = json.load(fh)
                continue
            except Exception as exc:
                return jsonify({"error": "%s: %s" % (fn, exc)}), 500
        missing.append(key)
    if missing:
        if "quality" in _CACHE:
            for k in missing:
                out[k] = _CACHE["quality"].get(k)
                out["from_saved_run"] = False
        else:
            obj = {}
            if "uncertainty" in missing:
                from model.uncertainty import run as unc_run
                obj["uncertainty"] = unc_run(include_design=False)
            if "methanol_adiabatic" in missing:
                from model.methanol_converter import build_report
                obj["methanol_adiabatic"] = build_report(n_steps=800)
            if "activity_band" in missing:
                from model.activity_uncertainty import band
                obj["activity_band"] = band()
            _CACHE["quality"] = obj
            for k in missing:
                out[k] = obj.get(k)
            out["from_saved_run"] = False
        out["note"] = ("посчитано по запросу (в кэше панели); полный прогон "
                       "пишет те же файлы в results_v2/")
    return jsonify(to_jsonable(out))



def _rfi_view():
    """RFI coverage plus the two lookups a browser wants: which item a field row
    can shade, and the short keys the JS reads. Counts come from the model, so the
    panel cannot show an item as closed that the validator did not accept."""
    from model.operator_data import rfi_coverage
    cov = rfi_coverage()
    cov["by_item"] = {str(r["item"]): r for r in cov.get("rows", [])}
    cov["unresolved"] = cov.get("unresolved_field_refs") or []
    cov["orphan_fields"] = cov.get("fields_without_item") or []
    return cov


def _operator_placeholder_table():
    """What the model substitutes while the operator has not entered a value.

    Read LIVE from load_config() (which already applies a valid overlay) plus the
    corridor-only placeholders, so this table can never show a stale number after
    a save. Every row is labelled with its provenance: an operator-entered value
    says so and names who entered it. Nothing here is a new number.
    """
    from model.config import load_config
    from model.operator_data import runtime_overlay
    cfg = load_config(product="ammonia")
    ov = runtime_overlay() or {}
    applied = set(ov.get("_applied_ids") or [])
    prov = ov.get("_provenance") or {}
    cat, kin = cfg.catalyst, cfg.raw["kinetics"]["ammonia"]
    eq, ec = cfg.raw["equipment"], cfg.raw["economics"]
    try:
        from model.economics import PRICES
    except Exception:
        PRICES = {}

    def note(fid, value, model_key=None):
        src = "заполнитель модели [ДОПУЩЕНИЕ]"
        if value is None and model_key:
            value = ov.get(model_key)
        if fid in applied and value is not None:
            p = prov.get(fid) or {}
            src = ("введено оператором: %s, %s%s" % (p.get("entered_by") or "?",
                                                      p.get("received_date") or "?",
                                                      ", проверено независимо"
                                                      if fid in set(ov.get("_verified_ids") or [])
                                                      else " — ОДИН источник"))
        if value is None:
            return "нет данных — коридор обязателен"
        if isinstance(value, float):
            value = ("%.6g" % value)
        return "%s · %s" % (value, src)

    band = {}
    qp = os.path.join(ROOT, "results_v2", "activity_uncertainty.json")
    if os.path.exists(qp):
        try:
            band = (json.load(open(qp, encoding="utf-8")) or {}).get("activity_band", {})
        except Exception:
            band = {}
    k_lo, k_hi, fac = band.get("k_scale_lo"), band.get("k_scale_hi"), band.get("factor")
    k_show = ("коридор %s … %s (×%s)" % ("%.5f" % k_lo, "%.5f" % k_hi, "%.3f" % fac)
              if k_lo and k_hi else "нет results_v2/activity_uncertainty.json")
    out = {
        "Ni в катализаторе риформинга (Ni_wt_pct)":
            note("Ni_wt_pct", cat.get("Ni_wt_pct_metal")),
        "Плотность загрузки риформинга (loaded_density)":
            note("loaded_density", cat.get("commercial_proxy_loaded_density_kg_m3")),
        "Ресурс катализатора риформинга, лет (catalyst_life_y)":
            note("catalyst_life_y", cat.get("life_years")),
        "Цена катализатора, USD/т (config) / USD/кг (PRICES)":
            "%s / %s · %s" % (cat.get("catalyst_price_USD_per_t"),
                              PRICES.get("catalyst_USD_per_kg"),
                              ("синхронизировано вводом оператора"
                               if "catalyst_price_USD_per_kg" in applied
                               else "ДВЕ РАЗНЫЕ ЦЕНЫ — см. docs/33, поле "
                                    "catalyst_price_USD_per_kg")),
        "Потолок температуры слоя NH3, K (nh3_bed_T_max_C)":
            note("nh3_bed_T_max_C", kin.get("bed_T_max_K")),
        "GHSV конвертора NH3, 1/ч (nh3_GHSV_h1)":
            note("nh3_GHSV_h1", kin.get("GHSV_h1")),
        "Базис GHSV (nh3_GHSV_basis)":
            note("nh3_GHSV_basis", kin.get("GHSV_basis", "normal (задано моделью)")),
        "Δp контура на компрессор, бар (nh3_dP_loop_bar)":
            note("nh3_dP_loop_bar", eq.get("dP_max_bar")),
        "Полоса активности k_scale (nh3_activity_k_scale)":
            "%s · %s" % (k_show, "закреплена вводом оператора"
                         if "nh3_activity_k_scale" in applied
                         else "не закреплена — рекомендованная форма отчёта"),
        "Плотность катализатора NH3, кг/м3 (nh3_rho_bulk)":
            note("nh3_rho_bulk", None, model_key="nh3_rho_kg_m3"),
        "Ресурс катализатора NH3, лет (nh3_catalyst_life_y)":
            note("nh3_catalyst_life_y", None, model_key="nh3_catalyst_life_years"),
        "Цена газа, USD/MMBtu (gas_price)": note("gas_price", ec.get("gas_USD_per_MMBtu")),
        "Цена электричества, USD/МВт·ч (electricity_price)":
            note("electricity_price", ec.get("electricity_USD_per_MWh")),
        "Цена CO2, USD/т (CO2_price)": note("CO2_price", ec.get("CO2_USD_per_t")),
        "Пар, USD/т (steam_price)": note("steam_price", ec.get("steam_USD_per_t")),
        "Оборотная вода, USD/м3 (water_price)":
            note("water_price", ec.get("cooling_water_USD_per_m3")),
        "Никель, USD/т (Ni_price)": note("Ni_price", cat.get("Ni_price_USD_per_t")),
        "CAPEX, USD/кВт H2 (LHV) (CAPEX_per_kW)":
            note("CAPEX_per_kW", ec.get("CAPEX_USD_per_kW_H2_LHV")),
        "Часов в году (hours_per_year)": note("hours_per_year", ec.get("operating_hours_per_year")),
        "Ставка дисконтирования (discount_rate)": note("discount_rate", ec.get("discount_rate")),
        "Срок службы установки, лет (plant_life_y)": note("plant_life_y", ec.get("plant_life_years")),
    }
    pinned = ov.get("nh3_k_scale")
    if pinned is not None:
        out["Полоса активности k_scale (nh3_activity_k_scale)"] = (
            "точка оператора %s%s · для сравнения литературная полоса %s … %s"
            % ("%.5f" % float(pinned),
               " (есть вторая подпись)" if "nh3_activity_k_scale" in set(
                   ov.get("_verified_ids") or []) else " (ОДИН источник)",
               "%.5f" % k_lo if k_lo else "?", "%.5f" % k_hi if k_hi else "?"))
    if band.get("GHSV_status"):
        out["GHSV: как читает коридор"] = band["GHSV_status"]
    if band.get("source_of_band"):
        out["откуда полоса активности"] = band["source_of_band"]
    return out


@app.get("/api/operator")
def api_operator():
    """V5.3 manual data entry: the form spec, the saved document and the state.

    Nothing here invents a number: the form ships EMPTY, and every field carries
    the model's CURRENT placeholder in its label so the operator can see what is
    being replaced. While a field is empty the model keeps reporting the V5.2
    corridor (docs/32) - that is the recommendation, and it is also printed in
    `status.recommendation`."""
    from model.operator_data import (FIELDS, GROUPS, template_doc, status,
                                     recommendation, FORM_PATH, validate,
                                     rfi_questions)
    doc = None
    if os.path.exists(FORM_PATH):
        try:
            with open(FORM_PATH, encoding="utf-8") as fh:
                doc = json.load(fh)
        except Exception as exc:
            return jsonify({"error": "data/operator_inputs.json: %s" % exc}), 500
    errors, warnings, _clean = validate(doc) if doc else ([], [], {})
    spec = [{k: f[k] for k in ("id", "group", "label", "unit", "type", "lo", "hi",
                              "options", "rfi", "pins", "warn")} for f in FIELDS]
    for row in spec:                   # the vendor question itself, not a number
        row["questions"] = rfi_questions(row["id"])
    return jsonify(to_jsonable({
        "fields": spec, "groups": GROUPS,
        "doc": doc or template_doc(), "has_saved_form": bool(doc),
        "validation_errors": errors, "validation_warnings": warnings,
        "status": status(), "recommendation": recommendation(),
        "rfi": _rfi_view(),
        "placeholder_now": _operator_placeholder_table()}))


@app.post("/api/operator")
def api_operator_post():
    """Validate / save / clear the operator form, or recompute the corridor.

    action=validate : check only, nothing written
    action=save     : write data/operator_inputs.json (only if it validates)
    action=clear    : remove the form (model returns to pure corridor mode)
    action=recompute: run the ammonia corridor with the entered data and return it
    """
    from model.operator_data import (save, clear, status, validate,
                                     write_template, activity_overrides)
    a = request.get_json(force=True, silent=True) or {}
    action = a.get("action", "validate")
    if action == "clear":
        gone = clear()
        _CACHE.pop("quality", None)
        return jsonify({"cleared": gone, "status": status()})
    if action == "template":
        j, c, n = write_template()
        return jsonify({"template": os.path.relpath(j, ROOT), "csv": os.path.relpath(c, ROOT),
                        "n_fields": n})
    if action == "recompute":
        try:
            from model.activity_uncertainty import band
            res = band()
        except Exception as exc:
            return jsonify({"error": "коридор не пересчитан: %r" % exc}), 500
        try:
            with open(os.path.join(ROOT, "results_v2",
                                   "activity_uncertainty.json"), "w",
                      encoding="utf-8") as fh:
                json.dump(res, fh, indent=1, ensure_ascii=False, default=float)
        except Exception:
            pass
        _CACHE.pop("quality", None)
        return jsonify(to_jsonable(res))
    doc = a.get("doc")
    if not isinstance(doc, dict):
        return jsonify({"error": "тело должно содержать 'doc' - форму из "
                                 "data/operator_inputs.json"}), 400
    errors, warnings, clean = validate(doc)
    if errors:
        return jsonify({"saved": False, "validation_errors": errors,
                        "validation_warnings": warnings,
                        "note": ("ничего не записано: полуприменённый даташит "
                                 "хуже, чем его отсутствие")}), 422
    if action == "save":
        path = save(doc)
        _CACHE.pop("quality", None)
        shown = path if not path.startswith(ROOT + os.sep) else os.path.relpath(path, ROOT)
        return jsonify(to_jsonable({"saved": True, "path": shown,
                                    "n_applied": len([1 for e in clean.values()
                                                      if e.get("applied")]),
                                    "status": status(),
                                    "overrides": activity_overrides()}))
    return jsonify(to_jsonable({"saved": False, "validation_errors": [],
                                "validation_warnings": warnings,
                                "n_applied": len([1 for e in clean.values()
                                                  if e.get("applied")]),
                                "overrides": activity_overrides()}))


@app.post("/api/ingest")
def api_ingest():
    """Validate a pilot campaign file against data/pilot_schema.json and rerun
    the loop-5 pilot subchecks. Only files inside the repository are accepted."""
    a = request.get_json(force=True, silent=True) or {}
    rel = str(a.get("file", "")).strip()
    if not rel:
        return jsonify({"error": "field 'file' is required (path inside the repo)"}), 400
    cand = os.path.normpath(os.path.join(ROOT, rel))
    if not cand.startswith(ROOT + os.sep) or not os.path.exists(cand):
        return jsonify({"error": "file not found inside the repository: " + rel}), 404
    if not cand.lower().endswith((".csv", ".json")):
        return jsonify({"error": "only .csv or .json campaign files are accepted"}), 400
    from model.data_ingest import report
    try:
        return jsonify(to_jsonable(report(cand, load_config(product="ammonia"))))
    except Exception as exc:
        return jsonify({"error": str(exc)}), 500


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
<button onclick="pilot()">Пилотные данные</button>
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
<button onclick="tab('t9',this)">Безопасность</button>
<button onclick="tab('t10',this)">Кинетика / контур 5</button>
<button onclick="tab('t11',this);conv()">Конвертор NH₃ (V5)</button>
<button onclick="tab('t12',this);qual()">Качество модели (V5.1–V5.2)</button>
<button onclick="tab('t13',this);opd()">Ручной ввод данных (V5.3)</button></div>
<div id="t1"></div><div id="t2" class="hidden"></div><div id="t3" class="hidden"></div>
<div id="t4" class="hidden"></div><div id="t5" class="hidden"></div>
<div id="t6" class="hidden"></div><div id="t7" class="hidden"><pre id="raw"></pre></div>
<div id="t8" class="hidden"></div><div id="t9" class="hidden"></div>
<div id="t10" class="hidden"></div>
<div id="t11" class="hidden"></div>
<div id="t12" class="hidden"></div>
<div id="t13" class="hidden"></div>
</main></div>
<script>
let CFG=null, LAST=null;
const $=id=>document.getElementById(id);
const fmt=(x,n=3)=>x===null||x===undefined||Number.isNaN(+x)?'—':(+x).toFixed(n);
const tbl=(head,rows)=>'<table><tr>'+head.map(h=>'<th>'+h+'</th>').join('')+'</tr>'+
 rows.map(r=>'<tr>'+r.map(c=>'<td>'+c+'</td>').join('')+'</tr>').join('')+'</table>';
const say=(m,bad=false)=>{$('status').textContent=m;$('status').style.borderLeftColor=bad?'#f85149':'#d29922'};
function tab(id,btn){['t1','t2','t3','t4','t5','t6','t7','t8','t9','t10','t11','t12','t13'].forEach(x=>$(x).classList.toggle('hidden',x!==id));}
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
 const kn=b.kinetic||{}; const used=kn.used; const km=used?kn[used]:null;
 const bc=kn.benchmark_check||{};
 $('t10').innerHTML='<h2>Кинетика синтеза (не стехиометрия)</h2>'+
  (km?tbl(['параметр','значение'],
   [['модель',km.model||used],['T K',fmt(km.T_K,1)],['p бар',fmt(km.p_bar,1)],
    ['GHSV ч⁻¹',fmt(km.GHSV_h1,0)],['за проход',fmt((km.per_pass_COx_conversion||km.per_pass_N2_conversion),4)],
    ['вых. мол.%',fmt(km.outlet_MeOH_molpct||km.outlet_NH3_molpct,2)],
    ['статус',km.status||'']]) : '<div class="note">Для этого продукта кинетическая модель не реализована.</div>')+
  '<div class="note">'+(km?km.note:'')+'</div>'+
  '<h2>Внешние бенчмарки</h2>'+tbl(['GHSV','вых. мол.%','X за проход'],
    (bc.sweep||[]).map(z=>[z.GHSV_h1,fmt(z.outlet_MeOH_molpct||z.outlet_NH3_molpct,2),
      z.per_pass_N2_conversion?fmt(z.per_pass_N2_conversion,3):'—']))+
  '<h2>Контур 5</h2><div id="loop5box" class="note">Нажмите «5 циклов проверки» или «Пилотные данные».</div>';
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
async function pilot(){const j=await (await fetch('/api/pilot')).json();
 const box=$('loop5box');
 if(box) box.innerHTML='<b>Внешние пилотные данные:</b> '+j.n_records_total+' записей, '+
  j.n_numeric_X_CH4_comparable+' численных сравнений X_CH4, среднее смещение равновесной модели '+
  fmt(j.mean_model_bias,3)+' (модель равновесная, данные кинетические). Даташит Ni/MgAl2O4 катализатора: '+
  (j.commercial_datasheet.catalyst_datasheet_found?'НАЙДЕН':'НЕ НАЙДЕН')+'.';
 tab('t10');}
async function conv(){
 say('конвертор NH3: расчёт (может занять ~20 с, если нет сохранённого прогона) ...');
 const c=await (await fetch('/api/converter')).json();
 if(c.error){$('t11').innerHTML='<h2>Конвертор NH3</h2><div class="note">ошибка: '+c.error+'</div>';say(c.error,true);return;}
 const d=c.design||{},k=c.calibration||{},b=c.benchmark_validation||{},rm=c.peak_temperature_remedy||{},eq=c.equilibrium_check||{},rc=d.recycle_closure||{},bc=c.benchmark_consistency||{};
 const st=x=>'<span class="'+(x==='OK'?'pass':'fail')+'">'+(x==='OK'?'в пределах':'ПРЕВЫШЕН')+'</span>';
 $('t11').innerHTML='<h2>Многосекционный адиабатический конвертор NH3 (V5)</h2>'+
  '<div class="note">3 адиабатические секции с промежуточным охлаждением; закон Темкина–Пызева; '+
  'тепловой баланс по NIST Shomate; GHSV в <b>нормальных</b> м3/м3_кат·ч. '+
  (c.from_saved_run?'Числа из сохранённого прогона `results_v2/converter_ammonia.json`.':'Рассчитано по запросу (в кэше панели).')+'</div>'+
  tbl(['параметр','значение','комментарий'],[
   ['давление / GHSV',fmt(d.p_bar,0)+' бар / '+fmt(d.GHSV_normal_h1,0)+' ч-1','нормальный базис (V5)'],
   ['X N2 за проход (калибр.)',fmt(100*d.per_pass_N2_conversion,2)+' %','открытый коридор 15–20 % (150 бар)'],
   ['X N2 за проход (k0 из статьи)',fmt(100*d.per_pass_N2_conversion_uncalibrated,2)+' %','без подгонки'],
   ['выход NH3',fmt(d.outlet_NH3_molpct,2)+' мол.%','бенчмарк 13 мол.%'],
   ['объём / масса катализатора',fmt(d.catalyst_volume_m3,1)+' м3 / '+fmt(d.catalyst_mass_t_at_1775kgm3,1)+' т','плотность 1775 кг/м3 — из VBF, не от поставщика'],
   ['T секций (вход→выход)',JSON.stringify(d.T_bed_in_out_K),'подъём '+JSON.stringify(d.adiabatic_rise_K)+' K'],
   ['пик постели / потолок',fmt(d.T_peak_K,1)+' K / '+fmt(d.catalyst_T_max_assumed_K,1)+' K',st(d.peak_T_check)],
   ['ΔH при T постели',fmt(d.dH_rxn_at_bed_T_kJ_per_mol_NH3,2)+' кДж/моль NH3','не -45,9 при 298 K'],
   ['теплота / промежуточное охлаждение',fmt(d.reaction_heat_MW,1)+' / '+fmt(d.interbed_cooling_duty_MW,1)+' МВт','утилизация не просчитана'],
   ['рецикл по кинетике',fmt(d.recycle_ratio_implied_by_kinetics,2)+' (в конфиге '+fmt(d.recycle_ratio_configured,2)+')','X*(1+RR)='+fmt(rc.fraction_of_fresh_N2_converted,3)],
   ['NH3: аппарат против контура',fmt(d.NH3_formed_in_converter_t_h,2)+' / '+fmt(d.net_NH3_from_loop_t_h,2)+' т/ч','отношение '+fmt(d.converter_vs_loop_NH3_ratio,3)],
   ['невязка теплового баланса',(d.energy_balance_max_rel_residual||0).toExponential(2),'H=const по каждой секции'],
  ])+
  '<h2>Калибровка k0: один скаляр, открыто</h2>'+
  tbl(['величина','значение','метка'],[
   ['k_scale',fmt(k.k_scale,4),'бисекция по log10, только этот параметр'],
   ['k0 опубликовано → эффективно',(k.k0_published_kmol_m3cat_h||0).toExponential(3)+' → '+(k.k0_effective_kmol_m3cat_h||0).toExponential(3),'кмоль/(м3кат·ч)'],
   ['до калибровки',fmt(100*((k.uncalibrated||{}).per_pass_N2_conversion||0),2)+' %','отклонение от цели '+fmt(k.deviation_before_pct,1)+' %'],
   ['после калибровки',fmt(100*((k.calibrated||{}).per_pass_N2_conversion||0),2)+' %','верно по построению: это проверка процедуры, не аппарата'],
   ['расхождение двух открытых бенчмарков','×'+fmt(k.k0_uncertainty_factor,2),'17,5 % за проход против 13 мол.% NH3 (это про кривую, см. две строки ниже)'],
   ['13 мол.% на выходе — это сколько за проход?', bc.computed? fmt(bc.B_per_pass_pct,2)+' % X(N2)' : 'нет данных (пересобрать прогон)', bc.computed? ('открытый узкий коридор 15–20 %: '+(bc.inside_opened_band?'попадает':'мимо')+'; широкий 15–25 %: '+(bc.inside_wider_opened_band?'попадает':'мимо')) : 'нужен results_v2/converter_ammonia.json'],
   ['наклон «активность → результат»', bc.computed? fmt(bc.sensitivity_per_pass_pp_per_decade,1)+' п.п. X на декаду k_scale' : '—', bc.computed? ('×'+fmt(bc.activity_disagreement_factor,2)+' = '+fmt(bc.activity_disagreement_decades,3)+' декады → '+fmt(bc.per_pass_gap_predicted_from_sensitivity_pp,1)+' п.п. против фактических '+fmt(bc.per_pass_gap_pp,1)+' п.п.') : '—'],
   ['согласованность ориентиров на общей базе', bc.computed? (bc.mutually_consistent_on_a_common_basis?'ЕСТЬ':'НЕТ') : '—', 'правило зафиксировано до прогона (коридор + наклон в пределах 50 %); это сравнение двух литературных чисел, не валидация модели, и подпроверка контура 5 про ×2,36 остаётся проваленной'],
  ])+
  '<div class="note">'+(k.what_this_is||'')+'</div>'+
  '<h2>Сетка на открытой бенчмарк-точке (150 бар, 698 K, без подгонки)</h2>'+
  tbl(['случай','GHSV ч-1','X за проход','NH3 мол.%','равновесие мол.%','T пик K'],
   (b.rows||[]).map(r=>[r.case,fmt(r.GHSV_normal_h1,0),fmt(100*r.per_pass_N2_conversion,2)+' %',fmt(r.outlet_NH3_molpct,2),fmt(r.equilibrium_NH3_molpct_at_inlet_T,1),fmt(r.T_peak_K,0)]))+
  '<p>строк внутри открытого коридора: '+fmt(b.n_rows_in_band,0)+' из '+fmt(b.n_rows,0)+'</p>'+
  '<h2>Проверка K_a против энергий Гиббса NIST Shomate</h2>'+
  '<p>максимальное отклонение '+fmt(eq.max_abs_deviation_pct,2)+' % → '+
   '<span class="'+(eq.passed_within_15pct?'pass':'fail')+'">'+(eq.passed_within_15pct?'ПРОЙДЕНА':'ПРОВАЛЕНА')+'</span> '+
   '(добавлено в цикл 4)</p>'+
  '<h2>Мера по пиковой температуре</h2>'+
  '<p>общий вход в секции '+fmt(rm.recommended_common_bed_inlet_K,1)+' K → пик '+fmt(rm.achieved_peak_T_K,1)+' K, '+
   'X за проход '+fmt(100*(rm.per_pass_N2_conversion_at_that_inlet||0),2)+' %, выход NH3 '+fmt(rm.outlet_NH3_molpct_at_that_inlet,2)+' мол.%</p>'+
  '<div class="note">'+(rm.caveat||'')+'</div>'+
  '<h2>Поиск компоновки: число секций × холодный вброс</h2>'+
  tbl(['секций','вброс, %','T вход, K','T пик, K','X за проход, %','выход NH3, мол.%','в коридоре 15-20 %','Q охл., МВт'],
   ((c.layout_scan||{}).rows||[]).map(r=>[r.n_beds,fmt(100*r.cold_shot_fraction,0),fmt(r.common_bed_inlet_K,1),fmt(r.T_peak_K,1),fmt(r.per_pass_N2_pct,2),fmt(r.outlet_NH3_molpct,2),r.inside_opened_per_pass_band?'да':'нет',fmt(r.interbed_cooling_duty_MW,1)]))+
  '<p>укладываются в потолок '+fmt((c.layout_scan||{}).layouts_meeting_ceiling||0,0)+' из '+fmt((c.layout_scan||{}).layouts_total||0,0)+
   '; вместе с открытым коридором захода N2 — '+fmt((c.layout_scan||{}).layouts_meeting_ceiling_AND_opened_band||0,0)+'</p>'+
  '<div class="note">'+((c.layout_scan||{}).finding||'')+'</div>'+
  '<div class="note">'+((c.layout_scan||{}).status||'')+'</div>'+
  '<img src="/plot/13_converter_profile.png">'+
  '<h2>Приём данных пилотной кампании</h2>'+
  '<p>Контракт данных: <code>data/pilot_schema.json</code> (см. <code>docs/27</code>). Положите файл кампании в репозиторий и укажите путь — валидация + сравнение + авто-перезапуск подпроверок контура 5.</p>'+
  '<div class="row"><input id="ingfile" size="34" placeholder="data/my_campaign.csv"><button onclick="ing()">Проверить и перезапустить контур 5</button></div><pre id="ingout"></pre>'+
  '<div class="note">Контур 5 остаётся НЕ ПРОЙДЕННЫМ: ни пилотной кампании в расчётной точке, ни даташита катализатора, ни сертифицированной HAZOP нет. Калибровка по чужому промышленному бенчмарку валидацией не считается.</div>';
 say('конвертор NH3: готово');}
function actab(ab){
 if(!ab) return '<div class="note">коридор активности не рассчитан (нет results_v2/activity_uncertainty.json).</div>';
 const ab0=ab.activity_band||{}, rows=ab.rows||[], sp=ab.spans||{}, dr=ab.design_reference||{}, mo=ab.money||{};
 const h='<h2>Коридор активности катализатора: множитель ×'+fmt(ab0.factor,3)+'</h2>'+
  '<div class="note">k_scale '+fmt(ab0.k_scale_lo,4)+' … '+fmt(ab0.k_scale_hi,4)+
  ' — это не подгонка, а противоречие двух открытых ориентиров (середина коридора захода N₂ за проход против 13 мол.% NH₃ на выходе). '+
  'Проект стоит на НИЖНЕМ крае полосы, поэтому 52,91 м³ — консервативная оценка объёма, а 845 K — пессимистичный пик.</div>'+
  tbl(['k_scale','позиция','X за проход, %','выход NH₃, мол.%','T пик, K','выше потолка, K','Q межсекц., МВт','RR по кинетике','замыкание X·(1+RR)'],
   rows.map(r=>{const f=r.at_fixed_geometry||{};return [fmt(r.k_scale,4),r.position_in_band,fmt(f.per_pass_N2_pct,2),
     fmt(f.outlet_NH3_molpct,2),fmt(f.T_peak_K,1),fmt(f.peak_over_assumed_ceiling_K,1),fmt(f.interbed_cooling_duty_MW,1),
     fmt(f.recycle_ratio_implied,3),fmt(f.loop_closure_X_times_1pRR,3)];}))+
  '<p><span class="pass">T пик почти не зависит от активности: '+fmt(sp.T_peak_K[0],2)+'…'+fmt(sp.T_peak_K[1],2)+' K</span> — секции упираются в равновесие, '+
  'превышение потолка задаётся температурой входа, а не катализатором.</p>'+
  '<h2>Объём, если держать проектную конверсию ('+fmt(dr.per_pass_N2_pct,2)+' %)</h2>'+
  tbl(['k_scale','V нужно, м³','ΔV, %','GHSV, ч⁻¹','масса, т','инвентарь, USD','множитель корпуса (V/V₀)^0,7','сходимость'],
   rows.map(r=>{const v=r.volume_to_hold_design_conversion||{};return [fmt(r.k_scale,4),fmt(v.V_m3,2),fmt(v.delta_V_pct,1),
     fmt(v.GHSV_normal_h1,0),fmt(v.catalyst_mass_t,1),(v.inventory_cost_USD==null?'—':fmt(v.inventory_cost_USD/1e6,2)+' M'),
     fmt(v.vessel_scale_factor_capex_exponent_0p7,3),v.converged?'да':'НЕТ'];}))+
  '<h2>Мера по потолку при каждой активности</h2>'+
  tbl(['k_scale','общий вход секций, K','T пик, K','X за проход, %','выход NH₃, мол.%','RR по кинетике'],
   rows.map(r=>{const c=r.ceiling_remedy||{};return [fmt(r.k_scale,4),fmt(c.T_in_common_K,1),fmt(c.T_peak_K,1),
     fmt(c.per_pass_N2_pct,2),fmt(c.outlet_NH3_molpct,2),fmt(c.recycle_ratio_implied,3)];}))+
  '<p>тоннаж NH₃ по всему коридору: '+fmt((ab.production_is_not_activity_limited||{}).NH3_design_t_h,2)+
  ' т/ч (без изменений) — активность меняет требуемый рецикл, а не стехиометрический предел.</p>'+
  tbl(['канал','коридор','статус'],
   (mo.recycle_compressor&&mo.recycle_compressor.power_by_loop_dP||[]).map(x=>['рецикловый компрессор, Δp контура '+fmt(x.dP_loop_bar,0)+' бар',
     fmt(x.power_MW_min,2)+'…'+fmt(x.power_MW_max,2)+' МВт (Δ '+fmt(x.delta_cost_USD_y,0)+' USD/год)','[ЧАСТИЧНО] политропная оценка'])
   .concat([['инвентарь катализатора',fmt(Math.min.apply(null,mo.catalyst_inventory_corridor_USD||[0])/1e6,2)+'…'+
      fmt(Math.max.apply(null,mo.catalyst_inventory_corridor_USD||[0])/1e6,2)+' M USD','[ДОПУЩЕНИЕ] цена 40 USD/kg — скрининг для Ni/MgAl₂O₄'],
     ['перевод объём→масса','×'+fmt(mo.density_used_kg_m3,0)+' кг/м³','[ЧАСТИЧНО] заполнитель из кейса VBF; плотность аммиачного катализатора — docs/28 п.12']]))+
  '<div class="note">Охват: '+(ab.not_covered||[]).join('; ')+'</div>'+
  '<div class="note"><b>'+((ab.how_to_use||'')+'')+'</b> Коридор не является заводской валидацией.</div>';
 return h;}
async function qual(){
 say('качество модели: полоса входа + адиабатический бенчмарк метанола + коридор активности ...');
 const q=await (await fetch('/api/quality')).json();
 if(q.error){$('t12').innerHTML='<h2>Качество модели</h2><div class="note">ошибка: '+q.error+'</div>';say(q.error,true);return;}
 const u=q.uncertainty||{}, ma=q.methanol_adiabatic||{}, tm=ma.this_model||{}, cm=ma.comparison||{};
 $('t12').innerHTML='<h2>Качество модели V5.1–V5.2: полоса неопределённости входа, адиабатический бенчмарк метанола, коридор активности</h2>'+
  '<div class="note">'+(q.from_saved_run?'Числа из сохранённого прогона `results_v2/`.':'Рассчитано по запросу (в кэше панели).')+' '+
   'Ни один из этих расчётов не является валидацией: они показывают, чего НЕ может быть объяснено исходными данными, и сверяют реализацию с опубликованной моделью.</div>'+
  '<h2>Полоса неопределённости X_CH4 (OFAT)</h2>'+
  '<p>средняя полуширина огибающей '+fmt(u.mean_envelope_half_width,4)+'; квадратура '+fmt(u.mean_quadrature_half_width,4)+
   '; точек внутри полосы модели: <span class="fail">'+fmt(u.pilot_points_inside_model_band,0)+' из '+fmt(u.pilot_points_total,0)+'</span></p>'+
  tbl(['точка','T K','p бар','X базы','огибающая','±полуширина','X измерения','зазор/полуширина','крупнейший фактор'],
   (u.points||[]).map(r=>[r.record_id,fmt(r.T_K,1),fmt(r.p_bar,1),fmt(r.X_base,4),fmt(r.envelope_min,3)+'–'+fmt(r.envelope_max,3),
     fmt(r.envelope_half_width,4),r.X_measured==null?'—':fmt(r.X_measured,3),
     r.gap_over_envelope_half_width==null?'—':fmt(r.gap_over_envelope_half_width,1)+'×',
     (r.largest_single_effect||{}).perturbation+' ('+fmt((r.largest_single_effect||{}).delta,4)+')']))+
  '<div class="note">'+(u.verdict||'')+'</div>'+
  '<h2>Адиабатический метанольный реактор против открытого кейса VBF</h2>'+
  tbl(['показатель','эта модель','опубликовано','отклонение'],
   [['T на выходе, K',fmt(tm.T_out_K,2),fmt((cm.T_out_K||{}).published,1),fmt((cm.T_out_K||{}).dev_K,2)],
    ['CO2, мол.%',fmt((tm.y_out_molpct||{}).CO2,3),'2,1',fmt((cm.CO2_molpct||{}).dev_pp,3)],
    ['CO, мол.%',fmt((tm.y_out_molpct||{}).CO,3),'2,9',fmt((cm.CO_molpct||{}).dev_pp,3)],
    ['CH3OH, мол.%',fmt((tm.y_out_molpct||{}).CH3OH,3),'2,4',fmt((cm.MeOH_molpct||{}).dev_pp,3)],
    ['H2O, мол.%',fmt((tm.y_out_molpct||{}).H2O,3),'1,1',fmt((cm.H2O_molpct||{}).dev_pp,3)]])+
  '<p>пороги зафиксированы до сравнения: '+fmt((ma.criteria||{}).composition_within_pp,2)+' мол.% и '+fmt((ma.criteria||{}).T_within_K,0)+' K → '+
   '<span class="'+(ma.reproduced?'pass':'fail')+'">'+(ma.reproduced?'ВОСПРОИЗВЕДЕНО':'НЕ ВОСПРОИЗВЕДЕНО')+'</span>; '+
   'углерод '+((tm.carbon_closure_rel||0).toExponential(1))+', невязка энтальпии '+((tm.enthalpy_residual_rel||0).toExponential(1))+'</p>'+
  tbl(['вариант входных допущений','T на выходе, K','MeOH, мол.%','CO2, мол.%'],
   ((ma.sensitivity)||[]).map(v=>[v.variant,fmt(v.T_out_K,2),fmt(v.MeOH_molpct,3),fmt(v.CO2_molpct,3)]))+
  '<div class="note">'+(ma.status||'')+'</div>'+actab(q.activity_band)+
  '<div class="note">Подробнее: docs/30 (полоса неопределённости входа), docs/31 (адиабатический кейс VBF), docs/32 (коридор активности).</div>';
 say('качество модели: готово');}
async function ing(){const f=$('ingfile').value;say('ингестирование '+f+' ...');
 const r=await fetch('/api/ingest',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({file:f})});
 const j=await r.json();
 if(j.error){$('ingout').textContent=j.error;say(j.error,true);return;}
 $('ingout').textContent=JSON.stringify(j,null,1).slice(0,8000);
 say('пригодных записей: '+(j.n_records_usable||0)+' из '+(j.n_records_read||0)+
  '; ошибок контракта: '+(j.n_errors||0)+'; подпроверок контура 5 закрыто этими данными: '+
  (j.loop5_subchecks_passed_from_this_data||0)+'/3', (j.n_errors||0)>0);}

let OP=null;
const opid=(f,k)=>'op_'+f+'__'+k;
function opField(f,e){
 const id=opid(f.id,'v');
 let inp;
 if(f.type==='choice'){inp='<select id="'+id+'"><option value="">—</option>'+
   f.options.map(o=>'<option '+(o===e.value?'selected':'')+'>'+o+'</option>').join('')+'</select>';}
 else if(f.type==='bool'){inp='<select id="'+id+'"><option value="">—</option>'+
   ['true','false'].map(o=>'<option value="'+o+'" '+((e.value===true&&o==='true')||(e.value===false&&o==='false')?'selected':'')+'>'+o+'</option>').join('')+'</select>';}
 else if(f.type==='list'){inp='<input id="'+id+'" size="22" value="'+(Array.isArray(e.value)?e.value.join(', '):'')+'" placeholder="через запятую">';}
 else {inp='<input id="'+id+'" type="text" value="'+(e.value==null?'':e.value)+'"'+
   (f.lo!=null?' placeholder="'+f.lo+' … '+f.hi+'"':'')+'>';}
 const range=f.type==='number'||f.type==='int'||f.type==='list'?('допустимо '+f.lo+' … '+f.hi):(f.type==='choice'?('одно из: '+f.options.join(' / ')):'текст');
 return '<tr><td><b>'+f.label+'</b><br><span class="u">'+f.id+' · '+range+rfiAsk(f)+
  (f.pins?'<br>закрепляет: '+f.pins:'')+(f.warn?'<br><span class="warn">⚠ '+f.warn+'</span>':'')+
  '</span></td><td>'+inp+'</td>'+
  '<td><input id="'+opid(f.id,'unit')+'" value="'+(e.unit||'')+'" placeholder="'+(f.unit||'')+'"></td>'+
  '<td><input id="'+opid(f.id,'method')+'" value="'+(e.method||'')+'" placeholder="метод измерения"></td>'+
  '<td><input id="'+opid(f.id,'source')+'" value="'+(e.source||'')+'" placeholder="документ/письмо/протокол"></td>'+
  '<td><input id="'+opid(f.id,'date')+'" value="'+(e.received_date||'')+'" placeholder="2026-10-05"></td>'+
  '<td><input id="'+opid(f.id,'by')+'" value="'+(e.entered_by||'')+'" placeholder="ФИО"></td>'+
  '<td style="text-align:center"><input type="checkbox" id="'+opid(f.id,'applied')+'" '+(e.applied?'checked':'')+' style="width:auto"></td>'+
  '<td style="text-align:center"><input type="checkbox" id="'+opid(f.id,'ver')+'" '+(e.independently_verified?'checked':'')+' style="width:auto"></td></tr>';
}
function opCollect(){
 const doc={version:1,selftest:false,note:'внесено через панель',entries:{}};
 OP.fields.forEach(f=>{const g={};const v=$(opid(f.id,'v'));
  g.value=v.value.trim()===''?null:v.value.trim();
  ['unit','method','source','date','by'].forEach(k=>{g[k]=$(opid(f.id,k)).value.trim();});
  g.received_date=g.date; delete g.date; g.entered_by=g.by; delete g.by;
  g.applied=$(opid(f.id,'applied')).checked; g.independently_verified=$(opid(f.id,'ver')).checked;
  if(g.independently_verified){g.verified_by=($('op_verified_by')||{value:''}).value.trim();}
  doc.entries[f.id]=g;});
 return doc;
}
async function opPost(body,txt){say(txt||'оператор: запрос …');
 const r=await fetch('/api/operator',{method:'POST',headers:{'Content-Type':'application/json'},
  body:JSON.stringify(body)});
 const j=await r.json(); if(j.error){say(j.error,true);return j;} say('готово'); return j;}
async function opd(){
 say('ручной ввод: форма …');
 OP=await (await fetch('/api/operator')).json();
 if(OP.error){$('t13').innerHTML='<h2>Ручной ввод</h2><div class="fail">'+OP.error+'</div>';return;}
 const doc=OP.doc, st=OP.status||{}, rec=OP.recommendation||{};
 let h='<h2>Ручной ввод недостающих данных (V5.3)</h2>'+
  '<div class="note"><b>Правило:</b> пока поле не введено с полным провенансом (единицы, метод, документ, дата, кто внёс), '+
  'отчёт обязан оставаться <b>коридорным</b> (docs/32). Введённое по одному источнику фиксирует точку, но коридор печатается рядом; '+
  'вторая подпись (<i>независимо проверено</i>) снимает коридор только по своему полю; по остальным открытым размерам отчёт остаётся коридорным. Форму не принимают частично: при любой ошибке не применяется ни одного поля. '+
  'Контур 5 от ввода данных не проходит.</div>'+
  '<div class="cards"><div class="card"><div class="k">полей введено</div><div class="v">'+(st.n_applied||0)+
   '</div><div class="u">из '+st.n_fields+'</div></div>'+
   '<div class="card"><div class="k">независимо проверено</div><div class="v">'+(st.n_verified||0)+'</div><div class="u">вторая подпись</div></div>'+
   '<div class="card"><div class="k">ошибок валидации</div><div class="v '+(st.validation_errors&&st.validation_errors.length?'fail':'ok')+'">'+
    ((st.validation_errors||[]).length)+'</div><div class="u">'+(OP.has_saved_form?'сохранённая форма':'формы ещё нет')+'</div></div>'+
   '<div class="card"><div class="k">размеров требуют коридора</div><div class="v warn">'+rec.n_corridor_required+'</div>'+
    '<div class="u">рекомендовано: '+rec.recommended_form+'</div></div></div>'+
  '<div class="row"><button class="primary" onclick="opSave()">Проверить и сохранить</button>'+
   '<button onclick="opSave(true)">Только проверить</button>'+
   '<button onclick="opRecompute()">Пересчитать коридор по введённому</button>'+
   '<button onclick="opClear()">Удалить форму (вернуться к коридору)</button>'+
   '<input id="op_verified_by" size="18" placeholder="проверил (вторая подпись)"></div>'+
  '<pre id="opout"></pre>';
 OP.groups.forEach(gp=>{
  h+='<h2>'+gp+'</h2><table><tr><th style="width:26%">поле</th><th>значение</th><th>единица</th>'+
     '<th>метод</th><th>документ/источник</th><th>дата получения</th><th>внёс</th><th>применено</th><th>независимо</th></tr>';
  OP.fields.filter(f=>f.group===gp).forEach(f=>{h+=opField(f,(doc.entries||{})[f.id]||{});});
  h+='</table>';});
 h+='<h2>Что сейчас подставляют модель (пока данных нет)</h2>'+
    tbl(['ключ','текущее значение (метка)'],Object.entries(OP.placeholder_now).map(([k,v])=>[k,String(v)]))+
    '<h2>Состояние по размерам</h2>'+
    tbl(['размер','в модели','введено оператором','состояние','как докладывать'],
      (rec.rows||[]).map(r=>[r.quantity,r.model_value_now,r.operator_value==null?'—':r.operator_value,
       '<span class="'+(r.state==='corridor_required'?'warn':'pass')+'">'+r.state+'</span>',r.report_as]))+
    '<div class="note">'+(rec.note||'')+'</div>'+
    '<h2>Карта покрытия запроса поставщику</h2>'+rfiMapBlock()+
    '<h2>Провенанс сохранённой формы</h2><pre id="opprov">'+
     ((st.groups||[]).length?JSON.stringify(st.groups.map(g=>({group:g.group,внесено:g.n_applied,открыто:g.open.length})),null,1).slice(0,4000):'формы ещё нет - бланк data/operator_inputs_TEMPLATE.json')+
    '</pre><div id="opcorr"></div>';
 $('t13').innerHTML=h;
 say('ручной ввод: '+((st.n_applied||0)+' полей введено, '+(st.validation_errors||[]).length+' ошибок'));
}
async function opSave(validateOnly){
 const doc=opCollect();
 const j=await opPost(validateOnly?{action:'validate',doc:doc}:{action:'save',doc:doc},
   validateOnly?'проверка формы …':'сохранение формы …');
 const err=j.validation_errors||[];
 $('opout').innerHTML=err.length?('<span class="fail">ОТКЛАНЕНО ('+err.length+'):</span><ul><li>'+err.join('</li><li>')+'</li></ul>'):
  ('<span class="pass">ПРИНЯТО</span>; применено полей: '+(j.n_applied!=null?j.n_applied:'—')+
   (j.saved?'; записано в '+j.path:' (не сохранено)')+
   ((j.validation_warnings||[]).length?'; предупреждения:<ul><li>'+j.validation_warnings.join('</li><li>')+'</li></ul>':''));
 if(j.status){$('opprov').textContent=JSON.stringify((j.status.groups||[]).map(g=>({group:g.group,внесено:g.n_applied,открыто:g.open.length})),null,1);}
 if(j.saved){await opd();
  $('opout').innerHTML='<span class="pass">ПРИНЯТО</span>: форма сохранена, счётчики и карта RFI пересчитаны; кнопка «Пересчитать коридор» обновит полосу.';}
}
function rfiAsk(f){
 let out='';
 const bi=(OP&&OP.rfi)?OP.rfi.by_item:{};
 (f.questions||[]).forEach(q=>{
  out+='<br>RFI '+q.section+' п.'+q.n+': '+q.text;
  const st=bi[q.n]; if(st){out+=' <b>['+rfiStateRu(st)+']</b>';}
 });
 return out;
}
function rfiStateRu(r){
 const m={open:'открыт', partial:'частично', answered_single_source:'точка+коридор',
  answered_verified:'закрыт с 2-й подписью', not_answerable_by_form:'вне формы'};
 return m[r.state]||r.state;
}
function rfiMapBlock(){
 const rf=(OP&&OP.rfi)||null;
 if(!rf||!rf.rows){return '<div class="fail">карта RFI не прочитана</div>';}
 const cards='<div class="cards">'
  +'<div class="card"><div class="k">пунктов в запросе</div><div class="v">'+rf.n_items+'</div><div class="u">'+rf.source+'</div></div>'
  +'<div class="card"><div class="k">с полем формы</div><div class="v">'+rf.n_with_field+'</div><div class="u">остальные — документ или кривая</div></div>'
  +'<div class="card"><div class="k">закрыто вводом</div><div class="v '+(rf.n_answered?'pass':'warn')+'">'+rf.n_answered+'</div><div class="u">с 2-й подписью '+rf.n_answered_verified+'</div></div>'
  +'<div class="card"><div class="k">открыто</div><div class="v warn">'+rf.n_open+'</div><div class="u">ждут числа с провенансом</div></div></div>';
 const rows=rf.rows.map(r=>{
  const flds=(r.fields||[]).map(f=>{
   let cls='u'; if(f.in_force){cls=f.verified?'pass':'warn';}
   return '<span class="'+cls+'">'+f.id+(f.in_force?' ✓':'')+'</span>';}).join(', ')||'—';
  return ['<b>п.'+r.item+'</b> '+r.section, r.text, flds, rfiStateRu(r),
    r.state_note, r.model_uses_it_for||'—'];});
 let tail='';
 if((rf.unresolved||[]).length||(rf.orphan_fields||[]).length){
  tail='<div class="fail">Ссылки не разрешились: '+JSON.stringify(rf.unresolved)
      +' ; поля без пункта: '+JSON.stringify(rf.orphan_fields)+'</div>';
 } else {
  tail='<div class="note">Все ссылки «поле → пункт RFI» разрешились: это отдельная '
      +'подпроверка контура 5, она не зависит от того, заполнена ли форма.</div>';
 }
 if((rf.other_sources||[]).length){
  tail+='<div class="note">Отдельные ссылки формы ведут на программу кампании (`'
      +rf.other_sources.join('`, `')+'`): их закрывает не ввод числа, а '
      +'`model/data_ingest.py` по контракту `data/pilot_schema.json`.</div>';
 }
 return '<h2>Карта: какое число закрывает какой пункт запроса (docs/28)</h2>'+cards
  +'<div class="note">'+(rf.note||'')+'</div>'
  +tbl(['пункт','что запрошено у поставщика','поля формы','состояние','что это значит','зачем модели'],rows)
  +tail;
}
function bandNote(ab){
 if(ab.pinned_by_operator){
  let s='полоса активности закреплена вводом оператора: центр '+fmt(ab.k_center_entered,4);
  if(ab.guaranteed_factor_entered!=null){s+=', гарантированный разброс ×'+fmt(ab.guaranteed_factor_entered,3);}
  if(ab.single_source_pin){s+=' — ОДИН источник: литературная полоса печатается рядом (таблица ниже)';}
  return s;
 }
 return 'полоса активности не закреплена — рекомендованная форма отчёта: КОРИДОР k_scale '+
        fmt(ab.k_scale_lo,4)+' … '+fmt(ab.k_scale_hi,4)+' (×'+fmt(ab.factor,3)+')';
}
async function opRecompute(){
 say('пересчёт коридора: полный прогон дизайна NH3, 2-5 минут …');
 const j=await opPost({action:'recompute'},'пересчёт коридора …');
 if(j.error){$('opcorr').innerHTML='<div class="fail">'+j.error+'</div>';return;}
 const ab=j.activity_band||{}, rows=j.rows||[], sp=j.spans||{};
 $('opcorr').innerHTML='<h2>Коридор после ввода: '+(j.band_kind||'')+'</h2>'+
  '<div class="note">'+bandNote(ab)+'</div>'+
  tbl(['k_scale','тип строки','положение','X за проход','выход NH3','T пик','V под проектную X','масса','инвентарь USD'],
   rows.map(r=>{const f=r.at_fixed_geometry||{},v=r.volume_to_hold_design_conversion||{};
    return [fmt(r.k_scale,4),r.row_kind,r.position_in_band,fmt(f.per_pass_N2_pct,2)+' %',fmt(f.outlet_NH3_molpct,2)+' мол.%',
      fmt(f.T_peak_K,1)+' K',fmt(v.V_m3,2)+' м³',fmt(v.catalyst_mass_t,1)+' т',v.inventory_cost_USD==null?'—':fmt(v.inventory_cost_USD/1e6,2)+' M'];}))+
  ((j.literature_reference_rows||[]).length?'<h2>Рядом: литературная полоса V5.2 (не данные оператора)</h2>'+
   tbl(['k_scale','X за проход','выход NH3','T пик','V под проектную X'],
     j.literature_reference_rows.map(r=>[fmt(r.k_scale,4),fmt(r.per_pass_N2_pct,2)+' %',fmt(r.outlet_NH3_molpct,2)+' мол.%',
      fmt(r.T_peak_K,1)+' K',fmt(r.V_to_hold_design_m3,2)+' м³'])):'')+
  '<div class="note">эконом-блок: '+JSON.stringify({price_used:j.money.price_used,density:j.money.density_used_kg_m3,
    life:j.money.life_years_used,annual:j.money.annual_replacement_cost_USD_y,capex_delta:j.money.converter_CAPEX_delta_USD})+
   '<br>провенанс: '+JSON.stringify((j.data_entry||{}).provenance||{}).slice(0,1200)+'</div>';
 say('коридор пересчитан: строк '+rows.length);
}
async function opClear(){say('удаление формы …');
 const j=await opPost({action:'clear'},'удаление …');
 await opd();
 $('opout').textContent=j.cleared?'форма удалена — модель снова отчитывается коридором':'формы не было';}
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
