"""Five independent verification loops (rule section 2).

Each loop returns 'passed' / 'failed' / 'not_applicable' with the evidence.
Optional third-party packages (SciPy, pint, Cantera, matplotlib) are used ONLY
here; the model core is standard-library Python.
"""
from __future__ import annotations
import csv, json, math, os
from . import thermo
from .equilibrium import (equilibrate, _seed, vec_from_dict, element_vector,
                          SPECIES, IDX, NG, NU, REACTIONS, reaction_quotient)
from .routes import make_feed, HC_CARBON

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


# ---------------- loop 1: sources ----------------
def loop1_sources():
    path = os.path.join(ROOT, "docs", "01_claims_register.csv")
    rows = []
    with open(path, newline="", encoding="utf-8") as fh:
        rows = list(csv.DictReader(fh))
    missing = [r["ID"] for r in rows if not r.get("source_ids", "").strip()
               or not r.get("status", "").strip()]
    status_count = {}
    for r in rows:
        status_count[r["status"]] = status_count.get(r["status"], 0) + 1
    src = json.load(open(os.path.join(ROOT, "data", "sources.json"), encoding="utf-8"))
    unopened = [s["id"] for s in src["sources"] if not s.get("opened")]
    return {"status": "passed" if not missing else "failed",
            "n_claims": len(rows), "status_counts": status_count,
            "claims_missing_source_or_status": missing,
            "declared_unopened_sources": unopened,
            "evidence": "docs/01_claims_register.csv + data/sources.json; every numeric input must trace to an opened primary source or an explicit [ASSUMPTION]"}


# ---------------- loop 2: arithmetic / dimensions ----------------
def loop2_arithmetic(case, fs):
    from .thermo import R_J, P0_BAR
    ref = {"SMR": 206.0, "WGS": -41.0, "DRM": 247.0, "POX": -36.0, "FULLOX": -802.0}
    st = {"SMR": {"CH4": -1, "H2O": -1, "CO": 1, "H2": 3},
          "WGS": {"CO": -1, "H2O": -1, "CO2": 1, "H2": 1},
          "DRM": {"CH4": -1, "CO2": -1, "CO": 2, "H2": 2},
          "POX": {"CH4": -1, "O2": -0.5, "CO": 1, "H2": 2},
          "FULLOX": {"CH4": -1, "O2": -2, "CO2": 1, "H2O": 2}}
    calc = {k: sum(nu * thermo.h0(s, 298.15) for s, nu in v.items()) for k, v in st.items()}
    dev = {k: abs(calc[k] - ref[k]) for k in ref}
    pint_ok, pint_msg = None, "pint not installed"
    try:
        import pint
        ureg = pint.UnitRegistry()
        Rq = 8.314462618 * ureg.J / (ureg.mol * ureg.K)
        Tq = 1123.15 * ureg.K
        pq = 25.0 * ureg.bar
        Vq = (Rq * Tq / pq).to("m**3/mol")
        pint_ok = abs(Vq.magnitude - 8.314462618 * 1123.15 / 25e5) < 1e-9
        pint_msg = f"R*T/p = {Vq:~P}; molar volume at 1123.15 K, 25 bar"
    except Exception as exc:
        pint_msg = f"pint check unavailable: {exc}"
    # molar volume at normal conditions
    Vn = 8.314462618 * 273.15 / 101325.0
    ok = (max(dev.values()) < 1.0 and abs(Vn - 0.02241397) < 1e-7
          and pint_ok is not False)
    return {"status": "passed" if ok else "failed",
            "reaction_enthalpies_kJ_mol": calc,
            "reference_values_from_rule_kJ_mol": ref,
            "max_abs_deviation_kJ_mol": max(dev.values()),
            "ideal_gas_molar_volume_Nm3_per_mol": Vn,
            "pint_dimensional_check": pint_msg,
            "LHV_CH4_kJ_mol": fs["utilities"]["LHV_CH4_kJ_per_mol_from_NIST"],
            "evidence": "independent recomputation from NIST Shomate H coefficients at 298.15 K"}


# ---------------- loop 3: conservation ----------------
def loop3_conservation(fs):
    smr = fs["SMR"]
    elem = {k: abs(smr["elements_out"][k] - smr["elements_in"][k]) /
            smr["elements_in"][k] * 100 for k in smr["elements_in"] if smr["elements_in"][k]}
    pre = fs["pre_reformer"]
    elem_pre = {k: abs(pre["elements_out"][k] - pre["elements_in"][k]) /
                pre["elements_in"][k] * 100 for k in pre["elements_in"] if pre["elements_in"][k]}
    energy = fs["plant_energy_closure_pct"]
    ok = max(elem.values()) < 0.1 and max(elem_pre.values()) < 0.1 and energy < 0.5
    return {"status": "passed" if ok else "failed",
            "SMR_element_imbalance_pct": elem,
            "pre_reformer_element_imbalance_pct": elem_pre,
            "plant_energy_closure_pct": energy,
            "tolerances": {"elements_pct": 0.1, "energy_pct": 0.5},
            "evidence": "element_vector() before/after each reactor; sum of unit duties vs stream enthalpy difference"}


# ---------------- loop 4: thermodynamic consistency ----------------
def peng_robinson_phi(y, T, p_bar):
    """Mixture fugacity coefficients (k_ij = 0 [ASSUMPTION])."""
    import json
    cp = json.load(open(os.path.join(ROOT, "data", "critical_properties.json")))["species"]
    # H2O is absent from the Cantera critical-property table; Tc/Pc from the
    # opened NIST WebBook water page, acentric factor is an ASSUMPTION.
    cp.setdefault("H2O", {"critical-temperature": 647.0,
                          "critical-pressure": 220.64e5,
                          "acentric-factor": 0.344})
    names = [k for k in y if k in cp and k != "C_GR"]
    yy = [y[k] for k in names]
    tot = sum(yy)
    yy = [v / tot for v in yy]
    R = 8.314462618
    p = p_bar * 1e5
    aa, bb, om = [], [], []
    for k in names:
        Tc = float(cp[k]["critical-temperature"])
        pc = float(cp[k]["critical-pressure"])
        w = float(cp[k]["acentric-factor"])
        kap = 0.37464 + 1.54226 * w - 0.26992 * w ** 2
        alpha = (1 + kap * (1 - math.sqrt(T / Tc))) ** 2
        aa.append(0.45724 * R ** 2 * Tc ** 2 / pc * alpha)
        bb.append(0.07780 * R * Tc / pc)
    amix = sum(yy[i] * yy[j] * math.sqrt(aa[i] * aa[j])
               for i in range(len(names)) for j in range(len(names)))
    bmix = sum(yy[i] * bb[i] for i in range(len(names)))
    Aa = amix * p / (R ** 2 * T ** 2)
    Bb = bmix * p / (R * T)
    # largest real root of the PR cubic (gas-like root)
    import numpy as np
    coeff = [1.0, -(1 - Bb), Aa - 3 * Bb ** 2 - 2 * Bb,
             -(Aa * Bb - Bb ** 2 - Bb ** 3)]
    roots = np.roots(coeff)
    real = [r.real for r in roots if abs(r.imag) < 1e-8]
    Z = max(real)
    out = {}
    for i, k in enumerate(names):
        s = sum(yy[j] * math.sqrt(aa[i] * aa[j]) for j in range(len(names)))
        lnphi = (bb[i] / bmix * (Z - 1) - math.log(Z - Bb)
                 - Aa / (2 * math.sqrt(2) * Bb) *
                 (2 * s / amix - bb[i] / bmix) *
                 math.log((Z + (1 + math.sqrt(2)) * Bb) / (Z + (1 - math.sqrt(2)) * Bb)))
        out[k] = math.exp(lnphi)
    return out, Z


def scipy_independent_minimisation(feed, T, p_bar, dataset="nasa"):
    """Independent SLSQP optimiser + independent NASA7 thermochemistry."""
    try:
        import numpy as np
        from scipy.optimize import minimize
    except Exception as exc:
        return {"available": False, "reason": str(exc)}
    f = vec_from_dict(feed)
    b = element_vector(f)
    Amat = []
    for e in ("C", "H", "O", "N"):
        Amat.append([thermo.COMPOSITION[s].get(e, 0) for s in SPECIES])
    Amat = np.array(Amat, dtype=float)
    bvec = np.array([b[e] for e in ("C", "H", "O", "N")], dtype=float)
    g0s = np.array([thermo.g0(s, T, dataset) for s in SPECIES])
    Rt = thermo.R_KJ * T

    def mu(n):
        ng = n[:NG].sum()
        m = np.array(g0s, dtype=float)
        m[:NG] += Rt * np.log(np.maximum(n[:NG], 1e-300) / ng * p_bar / thermo.P0_BAR)
        return m
    def G(n):
        return float(np.dot(n, mu(n)))
    cons = [{"type": "eq", "fun": lambda n: Amat @ n - bvec,
             "jac": lambda n: Amat}]
    x0 = np.array(_seed(f, 1e-9 * max(sum(f), 1.0)), dtype=float)
    res = minimize(G, x0, method="SLSQP", jac=lambda n: mu(n),
                   bounds=[(1e-12, None)] * NG + [(0.0, None)],
                   constraints=cons, options={"ftol": 1e-10, "maxiter": 800})
    return {"available": True, "success": bool(res.success), "message": str(res.message),
            "n": {s: float(res.x[i]) for i, s in enumerate(SPECIES)},
            "y_wet": {SPECIES[i]: float(res.x[i] / res.x[:NG].sum()) for i in range(NG)}}


def loop4_thermo(case, fs):
    feed = make_feed(SC=3.0)
    conds = [(900.0, 25.0), (1123.15, 25.0), (1300.0, 25.0), (1123.15, 5.0)]
    cross = []
    for T, p in conds:
        a = equilibrate(feed, T, p, dataset="shomate")
        b = equilibrate(feed, T, p, dataset="nasa")
        dmax = max(abs(a["y_wet"][k] - b["y_wet"][k]) for k in a["y_wet"])
        cross.append({"T_K": T, "p_bar": p, "max_abs_y_difference": dmax,
                      "X_CH4_shomate": a["CH4_conversion"], "X_CH4_nasa": b["CH4_conversion"],
                      "Q1_over_K1_shomate": a["Q1_over_K1"], "Q2_over_K2_shomate": a["Q2_over_K2"]})
    sp = scipy_independent_minimisation(feed, 1123.15, 25.0)
    ref = equilibrate(feed, 1123.15, 25.0, dataset="nasa")
    dopt = None
    if sp.get("available") and "y_wet" in sp:
        dopt = max(abs(sp["y_wet"][k] - ref["y_wet"][k]) for k in ref["y_wet"])
        bdict = element_vector(vec_from_dict(feed))
        sp["element_constraint_max_residual"] = max(
            abs(sum(thermo.COMPOSITION[SPECIES[i]].get(e, 0) * sp["n"][SPECIES[i]]
                    for i in range(len(SPECIES))) - bdict[e]) for e in bdict)
    # Cantera: fully independent equilibrium engine (GRI-Mech 3.0, all species)
    cantera = {"available": False}
    try:
        import cantera as ct
        gas = ct.Solution("gri30.yaml")
        X = {k: v for k, v in feed.items() if k in gas.species_names}
        gas.TPX = 1123.15, 25.0 * 1e5, X
        gas.equilibrate("TP")
        cm = {k: float(gas[k].X[0]) for k in ("CH4", "H2O", "CO", "CO2", "H2")}
        cantera = {"available": True, "version": ct.__version__,
                   "major_species_mole_fraction": cm,
                   "max_abs_y_difference_vs_model": max(abs(cm[k] - ref["y_wet"][k]) for k in cm),
                   "note": "GRI-Mech 3.0 contains radicals/oxygenates; totals of the 5 major species differ from the restricted-species model."}
    except Exception as exc:
        cantera = {"available": False, "reason": str(exc)}
    # Peng-Robinson sensitivity on the ideal-gas assumption
    pr, phi, Z = {}, {}, None
    try:
        y = ref["y_wet"]
        phi, Z = peng_robinson_phi(y, 1123.15, 25.0)
        for name, st in (("R1_SMR", REACTIONS["R1_SMR"]), ("R2_WGS", REACTIONS["R2_WGS"])):
            lnKphi = sum(nu * math.log(phi.get(s, 1.0)) for s, nu in st.items() if s != "C_GR")
            pr[name] = {"K_phi": math.exp(lnKphi), "deviation_pct": (math.exp(lnKphi) - 1) * 100}
    except Exception as exc:
        pr = {"error": str(exc), "status": "PR check unavailable (numpy required)"}
    # dew point / phase checks
    dew = thermo.water_dew_point(25.0, ref["y_wet"]["H2O"])
    whb = fs["units"][3]["Q_kW"]
    checks = {
        "shomate_vs_nasa_max_abs_y_difference": max(x["max_abs_y_difference"] for x in cross),
        "scipy_vs_code_max_abs_y_difference": dopt,
        "Q_over_K_all": [x["Q1_over_K1_shomate"] for x in cross] + [x["Q2_over_K2_shomate"] for x in cross],
        "PR_Kphi_deviation_pct": {k: v["deviation_pct"] for k, v in pr.items()},
        "PR_Z": Z,
        "dew_point_K": dew,
        "no_condensation_in_WHB": fs["no_condensation_in_WHB"],
        "WHB_no_temperature_cross": not fs["WHB_no_temperature_cross"] if "WHB_no_temperature_cross" in fs else True,
    }
    if cantera.get("available"):
        checks["cantera_max_abs_y_difference"] = cantera["max_abs_y_difference_vs_model"]
    ok = (checks["shomate_vs_nasa_max_abs_y_difference"] < 0.01
          and (dopt is None or dopt < 0.02)
          and (not cantera.get("available") or cantera["max_abs_y_difference_vs_model"] < 0.02)
          and max(abs(x - 1) for x in checks["Q_over_K_all"]) < 1e-6
          and fs["no_condensation_in_WHB"])
    return {"status": "passed" if ok else "failed", "checks": checks,
            "cross_dataset_table": cross, "scipy": {k: v for k, v in sp.items() if k != "n"},
            "cantera": cantera, "peng_robinson": {"phi": phi, "reactions": pr},
            "tolerances": "Shomate vs NASA7 |dy| < 0.01; SLSQP vs code |dy| < 0.02; Q/K = 1 +/- 1e-6"}


# ---------------- loop 5: validation / falsification ----------------
def loop5_validation(case, fs, routes):
    # (a) independent literature anchors
    anchors = {
        "SMR_outlet_850C_25bar_SC3_X_CH4": {"model": fs["SMR"]["CH4_conversion"],
            "target_range": [0.6, 0.9],
            "source": "rule section 8 orientation + Energy 2025 316:134540 (open access review): industrial SMR up to 850 C, 25 bar, S/C 2-4"},
        "H2_CO_SMR_at_850C": {"model": fs["SMR"]["H2_CO_dry"],
            "target_range": [3.0, 7.0],
            "source": "Catalysts 2019, 9, 801 (opened): H2/CO ~>=5 at high conversion, WGS-controlled"},
    }
    # (b) sensitivity and falsification attempts
    sens = []
    for T in (1073.15, 1098.15, 1123.15, 1148.15, 1173.15):
        r = equilibrate(make_feed(SC=3.0, CO2C=fs["CO2_C_molar"]), T, 25.0, approach_K=10.0)
        sens.append({"case": "T", "value": T, "X_CH4": r["CH4_conversion"],
                     "SN": r["stoichiometric_number_SN"],
                     "C_affinity": r["carbon_affinity_kJ_per_mol"]})
    for p in (10.0, 20.0, 25.0, 30.0, 40.0):
        r = equilibrate(make_feed(SC=3.0, CO2C=fs["CO2_C_molar"]), 1123.15, p, approach_K=10.0)
        sens.append({"case": "p", "value": p, "X_CH4": r["CH4_conversion"],
                     "SN": r["stoichiometric_number_SN"],
                     "C_affinity": r["carbon_affinity_kJ_per_mol"]})
    for SC in (2.0, 2.5, 3.0, 3.5, 4.0):
        r = equilibrate(make_feed(SC=SC, CO2C=fs["CO2_C_molar"]), 1123.15, 25.0, approach_K=10.0)
        sens.append({"case": "S/C", "value": SC, "X_CH4": r["CH4_conversion"],
                     "SN": r["stoichiometric_number_SN"],
                     "C_affinity": r["carbon_affinity_kJ_per_mol"]})
    for ap in (0.0, 10.0, 20.0, 30.0):
        r = equilibrate(make_feed(SC=3.0, CO2C=fs["CO2_C_molar"]), 1123.15, 25.0, approach_K=ap)
        sens.append({"case": "approach_K", "value": ap, "X_CH4": r["CH4_conversion"],
                     "SN": r["stoichiometric_number_SN"],
                     "C_affinity": r["carbon_affinity_kJ_per_mol"]})
    kinetics_diag = None
    try:
        from . import kinetics
        kinetics_diag = kinetics.validate_against_published_model()
        k_tab = []
        for T in (750.0, 800.0, 850.0, 900.0, 950.0, 1000.0):
            _, Keq, _ = kinetics.coefficients(T)
            k_tab.append({"T_K": T,
                          "K1_secondary_source": Keq["K1"],
                          "K1_NIST_this_model": thermo.equilibrium_constant(REACTIONS["R1_SMR"], T),
                          "K2_secondary_source": Keq["K2"],
                          "K2_NIST_this_model": thermo.equilibrium_constant(REACTIONS["R2_WGS"], T)})
        kinetics_diag["equilibrium_constant_comparison"] = k_tab
        kinetics_diag["conclusion"] = (
            "Equilibrium constants in the secondary source agree with NIST-JANAF within ~8%, "
            "but the published conversion-vs-temperature curve of that same source cannot be "
            "reproduced from its printed kinetic/reactor parameters (max deviation ~0.5 absolute). "
            "The L2 kinetic model is therefore NOT VALIDATED and is not used for design.")
    except Exception as exc:
        kinetics_diag = {"error": str(exc)}
    falsification = [
        {"hypothesis": "The 25 bar ideal-gas assumption is wrong.",
         "test": "Peng-Robinson fugacity correction K_phi for R1/R2 at 1123 K, 25 bar (loop 4)",
         "result": "quantified in loop 4; if |deviation| > 5% the equilibrium map must be recomputed with PR/SRK in HYSYS"},
        {"hypothesis": "Full equilibrium overpredicts conversion; kinetics/diffusion limit it.",
         "test": "approach_K sensitivity 0/10/20/30 K above",
         "result": "X_CH4 and SN sensitivity reported; L2 kinetic validation is BLOCKED (see docs/09)"},
        {"hypothesis": "10 K approach-to-equilibrium is unjustified.",
         "test": "explicit sensitivity; no primary source for this number was opened",
         "result": "value remains [ASSUMPTION], must be replaced by catalyst vendor data"},
        {"hypothesis": "SMR alone can meet SN=2.",
         "test": "CO2/C sweep in results/co2_sweep.csv",
         "result": "SN at S/C=3, 850 C, 25 bar is >2.8; CO2 import or ATR is required"},
    ]
    anchor_ok = all(a["target_range"][0] <= a["model"] <= a["target_range"][1] for a in anchors.values())
    # Rule 2/11: a literature order-of-magnitude check is NOT a validation.
    # No experimental/industrial dataset was reproduced -> loop 5 is NOT passed.
    return {"status": "failed", "anchor_checks_passed": anchor_ok,
            "validation_status": "PARTIALLY VALIDATED - no industrial/pilot dataset was reproduced; only order-of-magnitude literature anchors",
            "anchors": anchors, "sensitivity": sens, "falsification_attempts": falsification,
            "kinetics_L2_diagnostic": kinetics_diag,
            "unvalidated": ["L2 Xu-Froment kinetics (primary full text not opened; secondary parameter set fails reproduction)",
                            "reformer tube wall / catalyst temperature profile (L3 not built)",
                            "commercial catalyst lifetime",
                            "PSA/CO2-removal unit performance"]}


def run_all_loops(case, fs, routes):
    return {"loop_1_sources": loop1_sources(),
            "loop_2_arithmetic_dimensions": loop2_arithmetic(case, fs),
            "loop_3_conservation": loop3_conservation(fs),
            "loop_4_thermodynamic_consistency": loop4_thermo(case, fs),
            "loop_5_validation_falsification": loop5_validation(case, fs, routes)}
