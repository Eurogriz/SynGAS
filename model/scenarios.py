"""V2 scenario matrix: normals, climates, feeds, EOS k_ij, regulation sweeps."""
from __future__ import annotations
import copy, math
from .config import load_config
from .products import design, _evaluate, tune
from .routes import make_feed
from .equilibrium import equilibrate

PRODUCTS = ["methanol", "ft", "oxo", "hydrogen", "ammonia"]


def _compact(r):
    """Small serialisable row for CSV/reporting."""
    s, u, f, e, c, eq = (r["spec"], r["utilities"], r["flows"],
                         r["economics"], r["catalyst"], r["equipment"])
    return {
        "product": r["product"], "normal": r["normal"], "climate": r["climate"],
        "feed": r["feed"], "Vm_m3_per_mol": r["Vm_m3_per_mol"],
        "metric": s["metric"], "target": s["target"], "achieved": s["achieved"],
        "within_tolerance": s["within_tolerance"], "carbon_stable": s["carbon_stable"],
        "CO2_molpct": s["CO2_molpct"], "CH4_molpct": s["CH4_molpct"],
        "N2_molpct": s["N2_molpct"], "H2O_molpct": s["H2O_molpct"],
        "H2_molpct": s["H2_purity_molpct"],
        "CO_ppm": s["CO_ppm"], "CO2_ppm": s["CO2_ppm"],
        "X_CH4": r["reformer"]["equilibrium"]["CH4_conversion"],
        "T_reformer_K": r["reformer"]["T_out_K"],
        "p_bar": r["reformer"]["p_bar"],
        "Z": r["eos"]["Z"], "SC": r["knobs"]["SC"], "CO2C": r["knobs"]["CO2C"],
        "O2C": r["knobs"]["O2C"], "air_ratio": r["knobs"].get("air_ratio"),
        "Q_reformer_kW": float(u["Q_reformer_kW"]),
        "fuel_Nm3_h": float(u["fuel_Nm3_h"]),
        "CO2_total_t_h": float(u["total_CO2_t_h"]),
        "CO2_net_t_h": float(u["CO2_net_t_h"]),
        "CO2_captured_t_h": float(u["CO2_captured_t_h"]),
        "CO2_import_t_h": float(u["CO2_import_t_h"]),
        "steam_net_export_t_h": float(u["steam_net_export_t_h"]),
        "cooling_duty_kW": float(u["cooling_duty_kW"]),
        "cooling_water_m3_h": float(u["cooling_water_m3_h"]),
        "product_T_C": r["config"].get("product_T_C"),
        "ambient_C": r["config"].get("ambient_C"),
        "air_cooler_outlet_C": u["air_cooler_outlet_C"],
        "trim_cooling_required": u["trim_cooling_required"],
        "O2_t_h": u["O2_t_h"], "ASU_power_MW": u["ASU_power_MW"],
        "total_power_MW": u["total_power_MW"],
        "dry_feed_Nm3_h": f["dry_feed_Nm3_h"],
        "product_Nm3_h": f["product_Nm3_h"],
        "Ni_inventory_t": c["total_Ni_inventory_t"],
        "Ni_t_per_y": c["Ni_consumption_t_per_y"],
        "catalyst_volume_m3": c["total_catalyst_volume_m3"],
        "tubes_installed": eq["tubes_installed"],
        "T_wall_max_K": eq["T_wall_max_K"],
        "dP_bar": eq["Ergun_dP_bar"],
        "tubes_for_heat": eq["tubes_for_heat"],
        "tubes_for_dp": eq["tubes_for_dp"],
        "pre_reformer_T_out_K": r["reformer"].get("prereformer", {}).get("T_out_K")
                                 if r["reformer"].get("prereformer") else None,
        "C2plus_conversion": r["reformer"].get("prereformer", {}).get("C2plus_conversion")
                             if r["reformer"].get("prereformer") else None,
        "saleable_product_t_h": r["synthesis"].get("methanol_t_h") or
                                r["synthesis"].get("C5plus_t_h") or
                                r["synthesis"].get("aldehyde_t_h") or
                                r["synthesis"].get("H2_t_h") or
                                r["synthesis"].get("NH3_t_h"),
        "synthesis_heat_MW": r["synthesis"].get("heat_released_MW"),
        "synthesis_compression_MW": r["synthesis"].get("compression_power_MW"),
        "NiCO4_normal_ppb": r["safety"]["Ni_CO_4"]["normal_operation"]["NiCO4_ppb"],
        "CAPEX_USD": e["CAPEX_USD"], "OPEX_USD_y": e["total_OPEX_USD_y"],
        "levelised_cost": e["levelised_cost"], "cost_unit": e["unit"],
        "limit_checks_pass": all(v["pass"] for v in s["limit_checks"].values()),
    }


def run_base():
    return {p: design(load_config(product=p)) for p in PRODUCTS}


def run_variant(overrides, product="methanol"):
    return design(load_config(overrides=overrides, product=product))


def run_normal_comparison():
    rows = []
    for n in ("0C", "15C"):
        r = run_variant({"active.normal": n})
        rows.append(_compact(r))
    return rows


def run_climate_comparison():
    rows = []
    for prod in ("methanol", "hydrogen", "ammonia"):
        for cl in ("russia", "middle_east"):
            rows.append(_compact(run_variant({"active.climate": cl}, product=prod)))
    return rows


def run_feed_comparison():
    rows = []
    for feed in ("russia_h", "me_rich"):
        rows.append(_compact(run_variant({"active.feed": feed})))
    return rows


def run_eos_sensitivity():
    rows = []
    for kset in ("zero", "base", "high"):
        r = run_variant({"eos.kset": kset})
        row = _compact(r); row["kij_set"] = kset; rows.append(row)
    r = run_variant({"eos.enabled": False})
    row = _compact(r); row["kij_set"] = "ideal_gas_disabled"; rows.append(row)
    return rows


def run_regulation_sweep():
    """1-D knob sweeps around each tuned set-point (no re-costing, fast)."""
    rows = []
    for prod in PRODUCTS:
        cfg = load_config(product=prod)
        t = tune(cfg)
        k0 = copy.deepcopy(t["knobs"])
        air = k0.get("air_ratio", 0.0)
        if prod in ("methanol", "oxo"):
            knob, centre, step = "CO2C", k0["CO2C"], 0.06
        elif prod == "ft":
            knob, centre, step = "O2C", k0["O2C"], 0.04
        elif prod == "hydrogen":
            knob, centre, step = "SC", k0["SC"], 0.40
        else:
            knob, centre, step = "air_ratio", k0["air_ratio"], 0.10
        for i in range(-3, 4):
            k = copy.deepcopy(k0)
            k[knob] = max(0.0, centre + i * step)
            ev = _evaluate(cfg, k, air=k.get("air_ratio", 0.0))
            if ev is None:
                continue
            rows.append({"product": prod, "knob": knob,
                         "value": k[knob], "metric": cfg.P["metric"],
                         "achieved": ev["metric"], "target": cfg.P["target"],
                         "carbon_stable": ev["carbon_stable"],
                         "X_CH4": ev["rx"]["equilibrium"]["CH4_conversion"],
                         "T_reformer_K": ev["rx"]["T_out_K"],
                         "y_H2": ev["ds"]["y_dry"].get("H2"),
                         "y_CO": ev["ds"]["y_dry"].get("CO"),
                         "y_CO2": ev["ds"]["y_dry"].get("CO2"),
                         "y_N2": ev["ds"]["y_dry"].get("N2")})
    return rows


def run_ni_life_sensitivity(base):
    rows = []
    for prod, r in base.items():
        for s in r["catalyst"]["life_sensitivity"]:
            rows.append({"product": prod, "life_years": s["life_years"],
                         "catalyst_consumption_t_per_y": s["catalyst_consumption_t_per_y"],
                         "Ni_consumption_t_per_y": s["Ni_consumption_t_per_y"],
                         "Ni_kg_per_1000Nm3": s["Ni_consumption_kg_per_1000Nm3"],
                         "Ni_inventory_t": r["catalyst"]["total_Ni_inventory_t"],
                         "catalyst_volume_m3": r["catalyst"]["total_catalyst_volume_m3"]})
    return rows


def run_full_matrix(base):
    """All 5 products x (base, ISO 15C, Middle East) - 15 compact rows.

    Re-uses the TUNED knobs from the base designs and re-runs the model with
    do_tune=False, so each extra case costs one equilibrium evaluation.
    """
    rows = []
    for prod, rb in base.items():
        tuned = rb["knobs"]
        knob_ov = {f"products.{prod}.knobs.{k}": v for k, v in tuned.items()}
        cases = [("0C_russia", {}),
                 ("15C_russia", {"active.normal": "15C"}),
                 ("0C_middle_east", {"active.climate": "middle_east"})]
        for label, ov in cases:
            if label == "0C_russia":
                r = rb
            else:
                cfg = load_config(overrides={**knob_ov, **ov}, product=prod)
                r = design(cfg, do_tune=False)
            row = _compact(r); row["case"] = label
            rows.append(row)
    return rows


def run_synthesis_summary(base):
    rows = []
    for prod, r in base.items():
        sy = r["synthesis"]
        rows.append({"product": prod, "p_synthesis_bar": sy.get("p_synthesis_bar"),
                     "T_synthesis_C": sy.get("T_synthesis_C"),
                     "key_conversion": sy.get("overall_C_conversion") or
                                       sy.get("CO_conversion") or
                                       sy.get("olefin_conversion") or
                                       sy.get("per_pass_conversion") or
                                       sy.get("overall_conversion"),
                     "saleable_t_h": sy.get("methanol_t_h") or sy.get("C5plus_t_h") or
                                     sy.get("aldehyde_t_h") or sy.get("H2_t_h") or
                                     sy.get("NH3_t_h"),
                     "saleable_t_y": sy.get("methanol_t_y") or sy.get("C5plus_t_y") or
                                     sy.get("aldehyde_t_y") or sy.get("NH3_t_y"),
                     "heat_released_MW": sy.get("heat_released_MW"),
                     "compression_power_MW": sy.get("compression_power_MW"),
                     "status": sy.get("status"), "note": sy.get("note")})
    return rows


def run_safety_summary(base):
    rows = []
    for prod, r in base.items():
        sa = r["safety"]
        rows.append({"product": prod,
                     "NiCO4_normal_ppb": sa["Ni_CO_4"]["normal_operation"]["NiCO4_ppb"],
                     "CO_purge_ppm": sa["Ni_CO_4"]["CO_purge_ppm"],
                     "safe_T_C": sa["Ni_CO_4"]["safe_temperature_C"],
                     "ZnO_kg": sa["sulfur_guard"]["ZnO_mass_kg"],
                     "PSV_orifice_mm": sa["relief"]["orifice_diameter_mm"],
                     "HAZOP_nodes": len(sa["HAZOP_nodes"])})
    return rows


def run_all():
    base = run_base()
    scenarios = {
        "normal_comparison": run_normal_comparison(),
        "climate_comparison": run_climate_comparison(),
        "feed_comparison": run_feed_comparison(),
        "eos_sensitivity": run_eos_sensitivity(),
        "regulation_sweep": run_regulation_sweep(),
        "ni_life_sensitivity": run_ni_life_sensitivity(base),
        "full_matrix": run_full_matrix(base),
        "synthesis_summary": run_synthesis_summary(base),
        "safety_summary": run_safety_summary(base),
    }
    return base, scenarios
