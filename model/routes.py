"""L0 thermodynamic screening and route comparison (G2 / G7)."""
from __future__ import annotations
import json, math
from .equilibrium import equilibrate, adiabatic_temperature, REACTIONS
from .thermo import stream_enthalpy, h0, h_liquid_water, water_psat_bar

# 100 mol of dry natural gas (ASSUMPTION, see cases/base_case.json)
# Russian (H) pipeline gas, Frontiers 2025 (opened): CH4 96.96, C2H6 1.37,
# C3H8 0.45, C4H10 0.15, C5H12 0.02, C6+ 0.01, N2 0.86, CO2 0.18 mol%.
# C4+ are lumped into C3H8 on a CARBON-equivalent basis (only C3H8 NASA7 data
# is available); this preserves the elemental C/H inventory exactly in C and
# slightly overstates H (documented in docs/12).
DRY_FEED = {"CH4": 96.96, "C2H6": 1.37, "C3H8": 0.45, "C4H10": 0.15,
            "C5H12": 0.02, "C6H14": 0.01, "CO2": 0.18, "N2": 0.86}
_CARBON_WEIGHT = {"CH4": 1, "C2H6": 2, "C3H8": 3, "C4H10": 4, "C5H12": 5, "C6H14": 6}
HC_CARBON = sum(DRY_FEED[k] * v for k, v in _CARBON_WEIGHT.items())   # 101.81 mol C / 100 mol feed
T_FEED = 773.15      # K, preheated feed [ASSUMPTION]


def feed_carbon(dry_feed=None):
    """mol C per 100 mol dry gas, from the configurable composition."""
    df = DRY_FEED if dry_feed is None else dry_feed
    return sum(df.get(k, 0.0) * v for k, v in _CARBON_WEIGHT.items())


def make_feed(SC=3.0, O2C=0.0, CO2C=0.0, h2_recycle=1.0, dry_feed=None):
    """Feed vector per 100 mol dry gas, with C4+ lumped into C3H8 on a
    CARBON-equivalent basis (documented approximation)."""
    df = DRY_FEED if dry_feed is None else dry_feed
    f = {k: v for k, v in df.items() if k in
         ("CH4", "C2H6", "C3H8", "CO2", "N2")}
    f.setdefault("CH4", 0.0); f.setdefault("C2H6", 0.0)
    f["C3H8"] = sum(df.get(k, 0.0) * _CARBON_WEIGHT[k] / 3.0
                    for k in ("C3H8", "C4H10", "C5H12", "C6H14"))
    carbon = feed_carbon(df)
    f["H2O"] = SC * carbon
    f["H2"] = h2_recycle
    f["CO2"] = f.get("CO2", 0.0) + CO2C * carbon
    if O2C:
        f["O2"] = O2C * carbon
    return f


def dry_flow(r):
    return sum(v for k, v in r["n_mol"].items() if k not in ("H2O", "C_GR"))


def isothermal_case(name, feed, T, p, approach_K=0.0, T_in=T_FEED):
    r = equilibrate(feed, T, p, approach_K=approach_K)
    H_in = stream_enthalpy(feed, T_in)
    H_out = stream_enthalpy(r["n_mol"], T)
    return {"route": name, "T_K": T, "p_bar": p,
            "feed_mol_per_100mol_NG": feed, "equilibrium": r,
            "Q_kJ_per_100mol_NG": H_out - H_in,
            "dry_mol_per_100mol_NG": dry_flow(r)}


def adiabatic_case(name, feed, p, T_in=T_FEED, approach_K=0.0):
    a = adiabatic_temperature(feed, p, T_in=T_in, approach_K=approach_K)
    if not a["converged"]:
        return {"route": name, "converged": False, "bracket": a}
    r = a["equilibrium"]
    return {"route": name, "converged": True, "T_K": a["T_ad_K"], "p_bar": p,
            "feed_mol_per_100mol_NG": feed, "equilibrium": r,
            "Q_kJ_per_100mol_NG": 0.0, "dry_mol_per_100mol_NG": dry_flow(r)}


def find_co2_for_SN(target=2.0, SC=3.0, T=1123.15, p=25.0, approach_K=10.0,
                    lo=0.0, hi=1.5):
    """Bisection on imported CO2/C to hit the methanol stoichiometric number."""
    def f(x):
        r = equilibrate(make_feed(SC=SC, CO2C=x), T, p, approach_K=approach_K)
        return r["stoichiometric_number_SN"] - target, r
    flo, _ = f(lo); fhi, _ = f(hi)
    if flo * fhi > 0:
        return {"converged": False, "SN_low": flo + target, "SN_high": fhi + target}
    for _ in range(45):
        mid = 0.5 * (lo + hi)
        fm, _ = f(mid)
        if fm * flo <= 0:
            hi, fhi = mid, fm
        else:
            lo, flo = mid, fm
    x = 0.5 * (lo + hi)
    _, r = f(x)
    return {"converged": True, "CO2_C_molar": x, "SN": r["stoichiometric_number_SN"],
            "equilibrium": r}


def carbon_boundary(T, p, CO2C=0.0, O2C=0.0, lo=0.15, hi=6.0):
    """Critical S/C at which graphite becomes thermodynamically stable."""
    def aff(SC):
        r = equilibrate(make_feed(SC=SC, CO2C=CO2C, O2C=O2C), T, p,
                        allow_carbon=False)
        return r["carbon_affinity_kJ_per_mol"]
    a_lo, a_hi = aff(lo), aff(hi)
    if a_lo <= 0:
        return {"T_K": T, "p_bar": p, "CO2_C": CO2C, "O2_C": O2C,
                "SC_critical": None, "note": "no carbon at SC=%.2f" % lo,
                "affinity_at_lo": a_lo}
    if a_hi > 0:
        return {"T_K": T, "p_bar": p, "CO2_C": CO2C, "O2_C": O2C,
                "SC_critical": None, "note": "carbon stable even at SC=%.2f" % hi,
                "affinity_at_hi": a_hi}
    for _ in range(26):
        mid = 0.5 * (lo + hi)
        if aff(mid) > 0:
            lo = mid
        else:
            hi = mid
    return {"T_K": T, "p_bar": p, "CO2_C": CO2C, "O2_C": O2C,
            "SC_critical": 0.5 * (lo + hi)}


def screening_tables():
    out = {"TP": [], "SC": [], "CO2": [], "O2": [], "boundary": []}
    for T in range(800, 1301, 50):
        for p in (1, 5, 10, 20, 25, 30, 40):
            r = equilibrate(make_feed(SC=3.0), float(T), float(p))
            out["TP"].append({"T_K": T, "p_bar": p, "X_CH4": r["CH4_conversion"],
                              "y_CH4": r["y_wet"]["CH4"], "y_H2": r["y_wet"]["H2"],
                              "y_CO": r["y_wet"]["CO"], "H2_CO": r["H2_CO_dry"],
                              "SN": r["stoichiometric_number_SN"],
                              "C_affinity_kJ_mol": r["carbon_affinity_kJ_per_mol"],
                              "carbon_stable": r["carbon_stable"]})
    for i in range(0, 33):
        SC = 0.5 + i * 0.1
        r = equilibrate(make_feed(SC=SC), 1123.15, 25.0)
        out["SC"].append({"SC": round(SC, 3), "X_CH4": r["CH4_conversion"],
                          "H2_CO": r["H2_CO_dry"], "SN": r["stoichiometric_number_SN"],
                          "C_affinity_kJ_mol": r["carbon_affinity_kJ_per_mol"],
                          "carbon_stable": r["carbon_stable"],
                          "y_CO": r["y_wet"]["CO"], "y_CO2": r["y_wet"]["CO2"]})
    for i in range(0, 31):
        x = i * 0.05
        r = equilibrate(make_feed(SC=3.0, CO2C=x), 1123.15, 25.0, approach_K=10.0)
        out["CO2"].append({"CO2_C": round(x, 3), "SN": r["stoichiometric_number_SN"],
                           "H2_CO": r["H2_CO_dry"], "X_CH4": r["CH4_conversion"],
                           "y_CO": r["y_wet"]["CO"], "y_CO2": r["y_wet"]["CO2"],
                           "C_affinity_kJ_mol": r["carbon_affinity_kJ_per_mol"],
                           "carbon_stable": r["carbon_stable"]})
    for i in range(0, 15):
        x = i * 0.05
        r = equilibrate(make_feed(SC=1.5, O2C=x), 1123.15, 25.0)
        out["O2"].append({"O2_C": round(x, 3), "X_CH4": r["CH4_conversion"],
                          "H2_CO": r["H2_CO_dry"], "SN": r["stoichiometric_number_SN"],
                          "C_affinity_kJ_mol": r["carbon_affinity_kJ_per_mol"],
                          "carbon_stable": r["carbon_stable"]})
    for T in (873.15, 1023.15, 1173.15):
        for p in (5, 25, 40):
            for co2 in (0.0, 1.0):
                out["boundary"].append(carbon_boundary(T, p, CO2C=co2))
    return out


def route_comparison(co2c_for_SN=None):
    """Seven routes on a common basis of 100 mol dry natural gas."""
    routes = []
    routes.append(isothermal_case("SMR (no pre-reformer)", make_feed(SC=3.0),
                                  1123.15, 25.0, approach_K=10.0))
    # Pre-reformer route: feed first passes an ADIABATIC equilibrium
    # pre-reformer; its effluent (not the raw feed) enters the SMR.
    from .equilibrium import adiabatic_temperature
    pr_feed = make_feed(SC=3.0)
    ad = adiabatic_temperature(pr_feed, 25.0, T_in=773.15)
    if ad["converged"]:
        pr_out = {k: v for k, v in ad["equilibrium"]["n_mol"].items() if k != "C_GR"}
        r_pre = isothermal_case("SMR + pre-reformer", pr_out, 1123.15, 25.0,
                                approach_K=10.0, T_in=ad["T_ad_K"])
        r_pre["pre_reformer_T_out_K"] = ad["T_ad_K"]
        routes.append(r_pre)
    else:
        routes.append({"route": "SMR + pre-reformer", "converged": False})
    routes.append(adiabatic_case("ATR (O2-blown)", make_feed(SC=1.5, O2C=0.55), 25.0))
    routes.append(adiabatic_case("POX (non-catalytic)", make_feed(SC=0.05, O2C=0.60), 25.0))
    routes.append(isothermal_case("DRM", make_feed(SC=0.0, CO2C=1.0), 1123.15, 25.0))
    routes.append(isothermal_case("Bi-reforming (SN-tuned)",
                                  make_feed(SC=3.0, CO2C=co2c_for_SN or 0.4),
                                  1123.15, 25.0, approach_K=10.0))
    routes.append(isothermal_case("SMR + ATR (secondary)",
                                  make_feed(SC=2.0, O2C=0.20), 1123.15, 25.0,
                                  approach_K=10.0))
    elec = isothermal_case("Electrically heated SMR", make_feed(SC=3.0),
                           1123.15, 25.0, approach_K=10.0)
    elec["note"] = ("Thermodynamically identical to SMR; only the heat supply changes. "
                    "WO2019228797A1 (opened) describes resistance-heated structured catalyst "
                    "and states a maximum SMR tube wall temperature of ca. 1000 C. "
                    "TRL/commercial maturity is [NOT CONFIRMED] - no licence/vendor data opened.")
    routes.append(elec)
    # Normalise a few derived indicators
    for r in routes:
        if not r.get("converged", True):
            continue
        e = r["equilibrium"]
        n = e["n_mol"]
        r["H2_CO_dry"] = e["H2_CO_dry"]
        r["SN"] = e["stoichiometric_number_SN"]
        r["X_CH4"] = e["CH4_conversion"]
        r["carbon_affinity_kJ_mol"] = e["carbon_affinity_kJ_per_mol"]
        r["carbon_stable"] = e["carbon_stable"]
        r["O2_mol"] = r["feed_mol_per_100mol_NG"].get("O2", 0.0)
        r["CO2_feed_mol"] = r["feed_mol_per_100mol_NG"].get("CO2", 0.0)
        r["CO2_product_mol"] = n["CO2"]
        r["CO_C_product_mol"] = n["CO"] + n["CO2"] + n.get("C_GR", 0.0)
    return routes
