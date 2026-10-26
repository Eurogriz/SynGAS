"""External pilot-data comparison for verification loop 5.

Loads data/pilot_ni_mgal2o4.json (only genuinely sourced numbers), re-runs the
model's EQUILIBRIUM solver at each reported laboratory condition, and reports
the deviation. This is deliberately a FALSIFICATION test: the lab data are in
the kinetic regime at 1-10 bar, while the model is an equilibrium model at
20-31 bar. A large positive model bias is EXPECTED and must be reported, not
hidden.
"""
from __future__ import annotations
import json, os, math
from .equilibrium import equilibrate
from .routes import feed_carbon

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PILOT = os.path.join(ROOT, "data", "pilot_ni_mgal2o4.json")
COMMERCIAL = os.path.join(ROOT, "data", "commercial_mgal2o4.json")


def load_pilot():
    return json.load(open(PILOT, encoding="utf-8"))


def load_commercial():
    return json.load(open(COMMERCIAL, encoding="utf-8"))


def lab_feed(SC=0.0, CO2C=0.0, O2C=0.0, N2_per_100C=0.0, CH4=100.0):
    """Synthetic laboratory feed per 100 mol CH4 (not the Russian pipeline gas).

    C2+ = 0 because the lab feeds were pure methane (except the natural-gas
    simulant case, which is recorded separately as a qualitative record).
    """
    f = {"CH4": CH4, "C2H6": 0.0, "C3H8": 0.0, "CO2": CO2C * CH4,
         "N2": N2_per_100C, "H2O": SC * CH4, "H2": 1e-3 * CH4}
    if O2C:
        f["O2"] = O2C * CH4
    return f


def model_X_CH4(T_K, p_bar, feed, eos_kset="base", approach_K=0.0):
    r = equilibrate(feed, T_K, p_bar, approach_K=approach_K,
                    eos_kset=eos_kset, allow_carbon=True)
    return {"X_CH4": r["CH4_conversion"],
            "carbon_stable": r["carbon_stable"],
            "max_element_imbalance_pct": r["max_element_imbalance_pct"],
            "Z": r["eos"].get("Z")}


def _measured_value(rec):
    v = rec.get("value")
    if isinstance(v, (int, float)):
        return float(v) / 100.0 if rec.get("unit") == "%" else float(v)
    if isinstance(v, list) and len(v) == 2 and all(isinstance(x, (int, float)) for x in v):
        mid = 0.5 * (v[0] + v[1])
        return mid / 100.0 if rec.get("unit") == "%" else mid
    return None


def compare_X_CH4(records, eos_kset="base"):
    """Compare every numeric X_CH4 record against the model equilibrium."""
    rows = []
    for rec in records:
        if rec.get("quantity") not in ("X_CH4", "X_CH4_Pt0"):
            continue
        meas = _measured_value(rec)
        if meas is None:
            continue
        c = rec.get("conditions", {})
        T_C = c.get("T_C")
        if T_C is None:
            continue
        T_K = T_C + 273.15
        p = c.get("p_bar")
        if p is None:
            p = 1.0 if c.get("p") == "1 atm" else 1.0
            p_assumed = True
        else:
            p_assumed = False
        SC = c.get("S_C", c.get("S/C", 0.0))
        CO2C = c.get("CO2C", 0.0)
        feed = lab_feed(SC=SC, CO2C=CO2C)
        m = model_X_CH4(T_K, p, feed, eos_kset=eos_kset)
        rows.append({
            "record_id": rec["id"], "source_id": rec["source_id"],
            "Ni_wt_pct": c.get("Ni_wt_pct"), "support": c.get("support"),
            "T_K": T_K, "p_bar": p, "p_assumed": p_assumed,
            "S_C": SC, "CO2_C": CO2C,
            "X_measured": meas, "X_model_equilibrium": m["X_CH4"],
            "delta": m["X_CH4"] - meas,
            "model_carbon_stable": m["carbon_stable"],
            "model_Z": m["Z"],
            "record_status": rec["status"],
            "applicability": "outside model design point (lab kinetic regime)"
                             if p < 20.0 else "inside model pressure range",
        })
    return rows


def pressure_trend_check(rows):
    """Does the model reproduce the opened pressure trend of 15 wt% Ni/MgAl2O4?

    Opened data: X_CH4 ~50% at 1 bar -> ~40% at 10 bar (Katheria/Jaiswar,
    reported in Catalysts 2020 10,352 and Appl. Catal. A 2018).
    """
    by_p = {}
    for x in rows:
        if x["Ni_wt_pct"] == 15.0 and x["T_K"] and abs(x["T_K"] - 873.15) < 1.0:
            by_p.setdefault(x["p_bar"], []).append(x)
    ps = sorted(by_p)
    trend = None
    if len(ps) >= 2:
        a, b = by_p[ps[0]][0], by_p[ps[-1]][0]
        trend = {
            "p_low_bar": ps[0], "p_high_bar": ps[-1],
            "measured_low": a["X_measured"], "measured_high": b["X_measured"],
            "model_low": a["X_model_equilibrium"], "model_high": b["X_model_equilibrium"],
            "measured_decrease": a["X_measured"] - b["X_measured"],
            "model_decrease": a["X_model_equilibrium"] - b["X_model_equilibrium"],
        }
        trend["trend_reproduced"] = (trend["measured_decrease"] > 0 and
                                     trend["model_decrease"] > 0)
    return trend


def deactivation_check(records, cfg):
    """Compare the model's assumed catalyst life with the opened 100 h point."""
    d = [r for r in records if r["id"] == "P11"]
    if not d:
        return {"available": False}
    rec = d[0]
    retained = rec["value"]
    tos_h = rec["conditions"]["TOS_h"]
    # exponential extrapolation of the measured deactivation to 50% activity
    k_dec = -math.log(retained) / tos_h
    t50_h = math.log(2.0) / k_dec
    design_life_y = cfg.catalyst["life_years"]
    design_life_h = design_life_y * cfg.economics["operating_hours_per_year"]
    return {
        "available": True, "source_id": rec["source_id"],
        "measured_activity_retained": retained, "TOS_h": tos_h,
        "conditions": rec["conditions"],
        "extrapolated_t50_h": t50_h,
        "design_life_y": design_life_y, "design_life_h": design_life_h,
        "ratio_design_to_extrapolated": design_life_h / t50_h,
        "note": "The measured 100 h deactivation is COKING from C2+ at S/C=1.5, "
                "NOT sintering at the model S/C=3. Extrapolation is therefore a "
                "worst-case lower bound, not a validated life. The same paper "
                "reports 500 h stability for Rh/MgAl2O4 at 750 C.",
        "status": "[НЕ ПОДТВЕРЖДЕНО] no 200-1000 h sintering series for 15 wt% Ni/MgAl2O4",
    }


def commercial_datasheet_check(cfg):
    com = load_commercial()
    proxy = cfg.catalyst["commercial_proxy_loaded_density_kg_m3"]
    powders = [s for s in com["support_powder_datasheets"]
               if "bulk_density_g_L" in s.get("properties", {})]
    return {
        "catalyst_datasheet_found": False,
        "supports_found": len(com["support_powder_datasheets"]),
        "powder_bulk_density_kg_m3": [s["properties"]["bulk_density_g_L"]
                                      for s in powders],
        "proxy_loaded_pellet_density_kg_m3": proxy,
        "comparable": False,
        "note": "Powder bulk density (300 kg/m3) is NOT a loaded-pellet density; "
                "the alpha-Al2O3/Ca-aluminate KATALCO proxy remains necessary.",
        "status": com["meta"]["status"],
    }


def run_external_comparison(cfg, eos_kset="base"):
    pilot = load_pilot()
    rows = compare_X_CH4(pilot["records"], eos_kset=eos_kset)
    deltas = [r["delta"] for r in rows]
    trend = pressure_trend_check(rows)
    return {
        "n_records_total": len(pilot["records"]),
        "n_numeric_X_CH4_comparable": len(rows),
        "n_records_qualitative": sum(1 for r in pilot["records"]
                                     if r.get("value") is None),
        "mean_model_bias": sum(deltas) / len(deltas) if deltas else None,
        "max_model_bias": max(deltas) if deltas else None,
        "min_model_bias": min(deltas) if deltas else None,
        "comparisons": rows,
        "pressure_trend": trend,
        "deactivation": deactivation_check(pilot["records"], cfg),
        "commercial_datasheet": commercial_datasheet_check(cfg),
        "gaps": pilot["gaps"],
        "interpretation": "A positive bias is EXPECTED: the model solves chemical "
                          "EQUILIBRIUM, whereas the lab data are KINETIC (short "
                          "contact time, 1-10 bar). This comparison FALSIFIES the "
                          "use of the equilibrium model as a kinetic predictor; "
                          "it does not validate the design-point equilibrium.",
    }
