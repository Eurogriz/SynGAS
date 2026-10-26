"""Single entry point: reproduce the whole L0/L1 study from zero.

    python3 -m model.run            # pure standard library is enough for the model
    .venv/bin/python -m model.run   # adds SciPy/pint/Cantera/matplotlib checks
"""
from __future__ import annotations
import csv, json, os, platform, sys, time, traceback

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RES = os.path.join(ROOT, "results")
os.makedirs(RES, exist_ok=True)


def jdump(name, obj):
    def conv(o):
        try:
            return float(o)
        except Exception:
            return str(o)
    with open(os.path.join(RES, name), "w", encoding="utf-8") as fh:
        json.dump(obj, fh, indent=2, ensure_ascii=False, default=conv)


def cdump(name, rows):
    if not rows:
        return
    keys = []
    for r in rows:
        for k in r:
            if k not in keys:
                keys.append(k)
    with open(os.path.join(RES, name), "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=keys, extrasaction="ignore")
        w.writeheader()
        for r in rows:
            w.writerow({k: ("" if r.get(k) is None else r.get(k)) for k in keys})


def versions():
    v = {"python": platform.python_version(), "platform": platform.platform()}
    for m in ("numpy", "scipy", "pandas", "matplotlib", "pint", "cantera", "yaml", "pytest"):
        try:
            mod = __import__(m)
            v[m] = getattr(mod, "__version__", "installed")
        except Exception:
            v[m] = "NOT INSTALLED (optional verification only)"
    return v


def main():
    t0 = time.time()
    from .build_registry import build
    build()
    from . import thermo, routes, flowsheet, sintering, equipment, economics, validation, plots, kinetics
    case = json.load(open(os.path.join(ROOT, "cases", "base_case.json"), encoding="utf-8"))
    log = []

    def step(msg, fn):
        t = time.time()
        log.append(f"START {msg}")
        out = fn()
        log.append(f"DONE  {msg} in {time.time()-t:.2f} s")
        print(log[-1], flush=True)
        return out

    scr = step("L0 thermodynamic screening maps", routes.screening_tables)
    cdump("equilibrium_map.csv", scr["TP"])
    cdump("sc_sweep.csv", scr["SC"])
    cdump("co2_sweep.csv", scr["CO2"])
    cdump("o2_sweep.csv", scr["O2"])
    cdump("carbon_boundary.csv", scr["boundary"])

    tuned = step("SN tuning (find CO2/C)", lambda: routes.find_co2_for_SN(
        case["target"]["SN_target"], SC=case["process"]["S_C_molar_per_hydrocarbon_C"],
        T=case["process"]["SMR_T_out_K"], p=case["process"]["SMR_p_out_bar_abs"],
        approach_K=case["process"]["SMR_approach_to_equilibrium_K"]))
    jdump("sn_tuning.json", tuned if "equilibrium" not in tuned else
          {k: v for k, v in tuned.items() if k != "equilibrium"})

    rt = step("route comparison (7+1 routes)", lambda: routes.route_comparison(
        tuned.get("CO2_C_molar")))
    jdump("routes.json", rt)
    cdump("routes_summary.csv", [{
        "route": r["route"], "converged": r.get("converged", True),
        "T_K": r.get("T_K"), "p_bar": r.get("p_bar"),
        "X_CH4": r.get("X_CH4"), "H2_CO_dry": r.get("H2_CO"),
        "SN": r.get("SN"), "carbon_affinity_kJ_mol": r.get("carbon_affinity_kJ_mol"),
        "carbon_stable": r.get("carbon_stable"),
        "Q_kJ_per_100mol_NG": r.get("Q_kJ_per_100mol_NG"),
        "O2_mol": r.get("O2_mol"), "dry_mol": r.get("dry_mol_per_100mol_NG")}
        for r in rt])

    fs = step("L1 plant material and heat balance", lambda: flowsheet.build_base_case(case))
    jdump("base_case.json", fs)
    cdump("base_case_streams.csv", fs["streams"])
    cdump("base_case_units.csv", fs["units"])
    cdump("pinch_cascade.csv", fs["pinch"]["cascade"])
    jdump("pinch_summary.json", {k: v for k, v in fs["pinch"].items() if k != "cascade"})

    kin = step("L2 kinetic PFR diagnostic (blocked)", lambda: kinetics.validate_against_published_model())
    jdump("kinetics_L2.json", kin)
    cdump("kinetics_validation.csv", kin["rows"])

    sin = step("G3 catalyst sintering / degradation", lambda: sintering.degradation_report(case))
    jdump("sintering.json", sin)
    mat = sintering.score_matrix()
    jdump("catalyst_matrix.json", mat)
    cdump("catalyst_matrix.csv", mat["rows"])

    eq = step("G6 equipment sizing", lambda: equipment.equipment_report(case, fs))
    jdump("equipment.json", eq)
    eco = step("G7 economics", lambda: economics.economics_report(case, fs))
    jdump("economics.json", eco)
    cdump("economics_sensitivity.csv", eco["sensitivity"])

    ver = step("five verification loops", lambda: validation.run_all_loops(case, fs, rt))
    jdump("verification.json", ver)
    cdump("verification_loops.csv", [{"loop": k, "status": v.get("status")}
                                     for k, v in ver.items()])
    pl = step("plots (optional)", plots.make_plots)

    # reaction thermochemistry table
    rx = {}
    for name, st in (("SMR", {"CH4":-1,"H2O":-1,"CO":1,"H2":3}),
                     ("WGS", {"CO":-1,"H2O":-1,"CO2":1,"H2":1}),
                     ("SMR_to_CO2", {"CH4":-1,"H2O":-2,"CO2":1,"H2":4}),
                     ("DRM", {"CH4":-1,"CO2":-1,"CO":2,"H2":2}),
                     ("POX", {"CH4":-1,"O2":-0.5,"CO":1,"H2":2}),
                     ("FULL_OX_GAS", {"CH4":-1,"O2":-2,"CO2":1,"H2O":2}),
                     ("CH4_CRACK", {"CH4":-1,"C_GR":1,"H2":2}),
                     ("BOUDOUARD", {"CO":-2,"C_GR":1,"CO2":1}),
                     ("CO_REDUCTION", {"CO":-1,"H2":-1,"C_GR":1,"H2O":1})):
        rx[name] = {"dH298_kJ_mol": sum(nu*thermo.h0(s,298.15) for s,nu in st.items()),
                    "K_1123": thermo.equilibrium_constant(st,1123.15),
                    "stoichiometry": st}
    jdump("reaction_thermochemistry.json", rx)
    cdump("reaction_thermochemistry.csv", [{"reaction":k, **{kk:vv for kk,vv in v.items() if kk!="stoichiometry"}} for k,v in rx.items()])

    summary = {
        "generated": "2026-10-26",
        "software": versions(),
        "runtime_s": round(time.time()-t0, 2),
        "log": log,
        "plots": pl,
        "verification_loop_status": {k: v.get("status") for k, v in ver.items()},
        "key_results": {
            "SN_target": fs["SN_target"], "SN_achieved": fs["SN_achieved"],
            "CO2_C_used": fs["CO2_C_molar"],
            "dry_syngas_Nm3_h": fs["dry_syngas_Nm3_h"],
            "SMR_CH4_conversion": fs["SMR"]["CH4_conversion"],
            "plant_energy_closure_pct": fs["plant_energy_closure_pct"],
            "max_element_imbalance_pct": fs["element_balance_SMR_max_pct"],
            "activity_EOR_power_law": sin["predictions"]["wall_normal"]["activity_A_EOR"],
            "activity_EOR_gple_bounded": sin["gple_model"]["predictions"]["wall_normal"]["activity_A_EOR"],
            "model_disagreement_factor": sin["model_disagreement_factor"],
            "catalyst_reserve_range": sin["catalyst_reserve_range"],
            "kinetics_L2_validation_mean_abs_deviation": kin["mean_abs_deviation"],
            "fuel_Nm3_h": fs["utilities"]["fuel_Nm3_h"],
            "CO2_from_fuel_t_h": fs["utilities"]["CO2_from_fuel_t_h"],
            "levelised_cost_USD_per_1000Nm3": eco["levelised_cost_USD_per_1000Nm3_dry_syngas"],
        },
        "disclaimer": "No Aspen HYSYS run was performed. This is a front-end (G0-G4 partial, G5-G8 blocked) model. See docs/09 and docs/10.",
    }
    jdump("summary.json", summary)
    print("\n=== VERIFICATION ===")
    for k, v in ver.items():
        print(f"  {k}: {v.get('status')}")
    print("\n=== KEY RESULTS ===")
    for k, v in summary["key_results"].items():
        print(f"  {k}: {v}")
    print(f"\nTotal runtime {summary['runtime_s']} s. Results in results/.")
    return summary


if __name__ == "__main__":
    try:
        main()
    except Exception:
        traceback.print_exc()
        sys.exit(1)
