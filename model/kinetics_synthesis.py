"""Kinetic (not stoichiometric) synthesis-loop models.

Implements two OPENED, published rate laws and integrates them along an
isothermal PFR with an explicit space velocity. No parameter is invented:
every constant comes from the sources recorded in cases/config.json ->
kinetics.*.source. Where a scale factor is required, it is exposed as an
apparent effectiveness factor and flagged [ДОПУЩЕНИЕ].

1) Methanol: Graaf et al. (1986/1990) equilibrium constants + Vanden Bussche
   & Froment (1996) LHHW steady-state kinetics on commercial Cu/ZnO/Al2O3.
   Primary text opened: https://terpconnect.umd.edu/~nsw/chbe446/VandenBussche-syngas2MeOH.pdf
   Applicability: 180-280 C, 15-51 bar, pCO/pCO2 = 0-4.1.

2) Ammonia: Temkin-Pyzhev / Dyson-Simon rate law with the equilibrium
   constant correlation given by COMSOL and the fitted alpha/k0/Ea from
   ChemCatChem 2024 (open PDF). Applicability: 598-773 K, 90 bar, Fe catalyst.
"""
from __future__ import annotations
import math

R_J = 8.314462618          # J/(mol K)
VM_NORMAL = 0.02241397     # m3/mol at 0 C, 101325 Pa


# --------------------------------------------------------------------------
# 1. Vanden Bussche & Froment (1996) / Graaf equilibrium constants
# --------------------------------------------------------------------------
VBF = {
    # Table 2 of the primary paper: parameter = A * exp(B / (R*T)), p in bar,
    # r in mol/(kg_cat s).
    "sqrt_KH2_A": 0.499,          "sqrt_KH2_B": 17197.0,
    "KH2O_A": 6.62e-11,          "KH2O_B": 124119.0,
    "K_ratio_A": 3453.38,        # K_H2O/(K8 K9 K_H2), B = 0
    "k_meoh_A": 1.07,            "k_meoh_B": 36696.0,
    "k_rwgs_A": 1.22e10,         "k_rwgs_B": -94765.0,
    # Graaf et al. (1986), quoted in the primary paper
    "log10_K1": "3066/T - 10.592",
    "log10_invK3": "-2073/T + 2.029",
    "catalyst_density_kg_m3": 1775.0,   # primary paper Table 3
    "source": "Vanden Bussche & Froment, J. Catal. 1996 (primary PDF, opened) "
              "+ Graaf et al. 1986 equilibrium constants quoted therein",
    "status": "[ПОДТВЕРЖДЕНО] primary parameter table; pressures in bar, rates mol/kg_cat/s",
}


def vbf_parameters(T):
    Rt = R_J * T
    return {
        "sqrt_KH2": VBF["sqrt_KH2_A"] * math.exp(VBF["sqrt_KH2_B"] / Rt),
        "KH2O": VBF["KH2O_A"] * math.exp(VBF["KH2O_B"] / Rt),
        "K_ratio": VBF["K_ratio_A"],
        "k_meoh": VBF["k_meoh_A"] * math.exp(VBF["k_meoh_B"] / Rt),
        "k_rwgs": VBF["k_rwgs_A"] * math.exp(VBF["k_rwgs_B"] / Rt),
        "K1": 10.0 ** (3066.0 / T - 10.592),     # CO2 + 3H2 -> MeOH + H2O
        "K3": 10.0 ** (2073.0 / T - 2.029),      # 1/K_RWGS = K_WGS
    }


def vbf_rates(T, p_bar, F, par=None):
    """Return (r_MeOH, r_RWGS) [mol/(kg_cat s)] and beta for molar flows F.

    F = dict with CO2, CO, H2, H2O, CH3OH (+ inert), all >= 0, in mol/s.
    """
    q = par or vbf_parameters(T)
    tot = sum(max(v, 0.0) for v in F.values())
    if tot <= 0:
        return 0.0, 0.0, 0.0
    def pp(k):
        return p_bar * max(F.get(k, 0.0), 1e-30) / tot
    pCO2, pCO = pp("CO2"), pp("CO")
    pH2, pH2O, pMeOH = pp("H2"), pp("H2O"), pp("CH3OH")
    beta = 1.0 / (1.0 + q["K_ratio"] * (pH2O / pH2) +
                  q["sqrt_KH2"] * math.sqrt(pH2) + q["KH2O"] * pH2O)
    drive_meoh = 1.0 - (1.0 / q["K1"]) * (pH2O * pMeOH) / (pH2 ** 3 * pCO2)
    drive_rwgs = 1.0 - q["K3"] * (pH2O * pCO) / (pCO2 * pH2)
    r_meoh = q["k_meoh"] * pCO2 * pH2 * drive_meoh * beta ** 3
    # r_RWGS in the primary paper has beta^1 (not beta^3)
    r_rwgs = q["k_rwgs"] * pCO2 * drive_rwgs * beta
    return r_meoh, r_rwgs, beta


def _rk4_methanol(T, p_bar, F0, W_cat_kg, n=4000):
    """Isothermal PFR: dF/dW = nu * r, W in kg_cat.

    The kinetic driving forces contain 1/p_CO2 and 1/p_NH3-type terms, so a
    reactant-depletion clamp is applied to every RK stage. Without it the
    integration can pass through a singularity and produce y_MeOH above the
    chemical-equilibrium limit.
    """
    keys = ("CO2", "CO", "H2", "H2O", "CH3OH", "INERT")
    def vec(F): return [F.get(k, 0.0) for k in keys]
    def mk(v): return dict(zip(keys, v))
    h = W_cat_kg / n

    def deriv(F):
        r1, r2, _ = vbf_rates(T, p_bar, F)
        # never consume more than 25% of the limiting reactant in one step
        cap1 = 0.10 * min(F["CO2"], F["H2"] / 3.0) / h
        cap2 = 0.10 * min(F["CO2"], F["H2"]) / h
        r1 = min(r1, cap1)
        if r2 > 0:
            r2 = min(r2, cap2)
        return {"CO2": -r1 - r2, "CO": r2, "H2": -3 * r1 - r2,
                "H2O": r1 + r2, "CH3OH": r1, "INERT": 0.0}

    F = mk([max(v, 0.0) for v in vec(F0)])
    for _ in range(n):
        d1 = deriv(F); k1 = [d1[k] for k in keys]
        F2 = mk([max(F[k] + 0.5 * h * k1[i], 1e-30) for i, k in enumerate(keys)])
        d2 = deriv(F2); k2 = [d2[k] for k in keys]
        F3 = mk([max(F[k] + 0.5 * h * k2[i], 1e-30) for i, k in enumerate(keys)])
        d3 = deriv(F3); k3 = [d3[k] for k in keys]
        F4 = mk([max(F[k] + h * k3[i], 1e-30) for i, k in enumerate(keys)])
        d4 = deriv(F4); k4 = [d4[k] for k in keys]
        F = mk([max(F[k] + h / 6 * (k1[i] + 2 * k2[i] + 2 * k3[i] + k4[i]), 1e-30)
                for i, k in enumerate(keys)])
    return F


def methanol_kinetic_pfr(r, cfg):
    """Run the VBF/Graaf kinetic PFR on the methanol design."""
    K = cfg.raw["kinetics"]["methanol"]
    T = K["T_K"]
    p = K["p_bar"]
    GHSV = K["GHSV_h1"]
    rho = K["catalyst_density_kg_m3"]
    RR = K["recycle_ratio"]
    scale = r["flows"]["scale_100mol_NG_per_h"]          # 100 mol NG / h
    n = r["downstream"]["n"]                            # mol per 100 mol NG
    fresh = {k: v * scale / 3600.0 for k, v in n.items()}   # mol/s fresh gas
    # reactor inlet = fresh + recycle (recycle has the composition of the
    # separated unreacted gas; approximated by the fresh gas for the first pass)
    F0 = {
        "CO2": fresh.get("CO2", 0.0) * (1 + RR),
        "CO": fresh.get("CO", 0.0) * (1 + RR),
        "H2": fresh.get("H2", 0.0) * (1 + RR),
        "H2O": fresh.get("H2O", 0.0) * (1 + RR),
        "CH3OH": K["inlet_MeOH_molpct"] / 100.0 * sum(fresh.values()) * (1 + RR),
        "INERT": (fresh.get("CH4", 0.0) + fresh.get("N2", 0.0) +
                  fresh.get("C2H6", 0.0) + fresh.get("C3H8", 0.0)) * (1 + RR),
    }
    ftot = sum(F0.values())
    Q_normal_m3_h = ftot * 3600.0 * VM_NORMAL
    V_cat_m3 = Q_normal_m3_h / GHSV
    W_cat_kg = V_cat_m3 * rho
    Fout = _rk4_methanol(T, p, F0, W_cat_kg)
    cox_in = F0["CO2"] + F0["CO"]
    cox_out = Fout["CO2"] + Fout["CO"]
    X_cox = (cox_in - cox_out) / cox_in if cox_in else 0.0
    y_meoh_out = Fout["CH3OH"] / sum(Fout.values())
    dH_meoh = -49.7e3     # J/mol, CO2 route (Appl. Sci. 2017)
    Q_heat_MW = (Fout["CH3OH"] - F0["CH3OH"]) * dH_meoh / 1e6
    return {
        "model": "Vanden Bussche & Froment (1996) LHHW + Graaf (1986) K_eq",
        "source": VBF["source"], "status": K["status"],
        "applicability": K["applicability"],
        "T_K": T, "p_bar": p, "GHSV_h1": GHSV,
        "catalyst_density_kg_m3": rho, "catalyst_mass_t": W_cat_kg / 1000.0,
        "recycle_ratio": RR, "inlet_MeOH_molpct": K["inlet_MeOH_molpct"],
        "per_pass_COx_conversion": X_cox,
        "outlet_MeOH_molpct": 100 * y_meoh_out,
        "heat_released_MW": -Q_heat_MW,
        "K1_eq_bar_minus2": vbf_parameters(T)["K1"],
        "K3_eq": vbf_parameters(T)["K3"],
        "note": "isothermal PFR, phi=1 (ideal). Recycle composition approximated "
                "by fresh gas => first-pass estimate. No diffusion/effectiveness factor.",
    }


# --------------------------------------------------------------------------
# 2. Temkin-Pyzhev / Dyson-Simon ammonia kinetics
# --------------------------------------------------------------------------
TEMKIN = {
    "alpha": 0.654,               # fitted, ChemCatChem 2024 (R2 = 0.989)
    "k0_kmol_m3cat_h": 6.5e13,
    "Ea_J_mol": 159400.0,
    "source": "Temkin & Pyzhev (1940) / Dyson & Simon (1968) rate law; "
              "rate equation and K_a correlation from COMSOL blog (opened); "
              "alpha, k0, Ea from ChemCatChem 2024 'Ammonia Synthesis Rate Over "
              "a Wide Operating Range' (open PDF, pure.mpg.de)",
    "status": "[ЧАСТИЧНО] published parameters, but k0 units are volumetric "
              "(kmol/m3_cat/h); an apparent effectiveness factor eta is required",
}


def ammonia_Ka(T):
    """log10 K_a = -2.691122 log10 T - 5.051925e-5 T + 1.848863e-7 T^2
                   + 2001.6/T + 2.689   (COMSOL, opened)."""
    return 10.0 ** (-2.691122 * math.log10(T) - 5.051925e-5 * T +
                    1.848863e-7 * T ** 2 + 2001.6 / T + 2.689)


def temkin_rate(T, p_bar, F, eta=1.0):
    """r_NH3 [kmol/(m3_cat h)] with F in kmol/h (activities a_i = y_i*p_bar)."""
    tot = sum(max(v, 0.0) for v in F.values())
    if tot <= 0:
        return 0.0
    def a(k): return p_bar * max(F.get(k, 0.0), 1e-12) / tot
    aN2, aH2, aNH3 = a("N2"), a("H2"), a("NH3")
    Ka = ammonia_Ka(T)
    k = TEMKIN["k0_kmol_m3cat_h"] * math.exp(-TEMKIN["Ea_J_mol"] / (R_J * T))
    al = TEMKIN["alpha"]
    term1 = Ka ** 2 * aN2 * (aH2 ** 3 / aNH3 ** 2) ** al
    term2 = (aNH3 ** 2 / aH2 ** 3) ** (1.0 - al)
    return eta * 2.0 * k * (term1 - term2)


def _rk4_ammonia(T, p_bar, F0, V_cat, eta, n=240):
    keys = ("N2", "H2", "NH3", "INERT")
    def vec(F): return [F.get(k, 0.0) for k in keys]
    def mk(v): return dict(zip(keys, v))
    def deriv(F):
        r = temkin_rate(T, p_bar, F, eta)
        return {"N2": -0.5 * r, "H2": -1.5 * r, "NH3": r, "INERT": 0.0}
    h = V_cat / n
    F = mk([max(v, 0.0) for v in vec(F0)])
    for _ in range(n):
        d1 = deriv(F); k1 = [d1[k] for k in keys]
        F2 = mk([max(F[k] + 0.5 * h * k1[i], 1e-14) for i, k in enumerate(keys)])
        d2 = deriv(F2); k2 = [d2[k] for k in keys]
        F3 = mk([max(F[k] + 0.5 * h * k2[i], 1e-14) for i, k in enumerate(keys)])
        d3 = deriv(F3); k3 = [d3[k] for k in keys]
        F4 = mk([max(F[k] + h * k3[i], 1e-14) for i, k in enumerate(keys)])
        d4 = deriv(F4); k4 = [d4[k] for k in keys]
        F = mk([max(F[k] + h / 6 * (k1[i] + 2 * k2[i] + 2 * k3[i] + k4[i]), 1e-14)
                for i, k in enumerate(keys)])
    return F


def ammonia_kinetic_pfr(r, cfg):
    K = cfg.raw["kinetics"]["ammonia"]
    T, p = K["T_K"], K["p_bar"]
    GHSV, eta = K["GHSV_h1"], K["effectiveness_eta"]
    scale = r["flows"]["scale_100mol_NG_per_h"]
    n = r["downstream"]["n"]
    # mol/s -> kmol/h
    conv = scale / 1000.0 * 3600.0 / 3600.0   # (mol per 100mol NG)*scale = mol/h -> kmol/h
    Ffresh = {k: v * scale / 1000.0 for k, v in n.items()}   # kmol/h
    RR = K["recycle_ratio"]
    F0 = {
        "N2": Ffresh.get("N2", 0.0) * (1 + RR),
        "H2": Ffresh.get("H2", 0.0) * (1 + RR),
        "NH3": K["inlet_NH3_molpct"] / 100.0 *
               sum(Ffresh.values()) * (1 + RR),
        "INERT": (Ffresh.get("CH4", 0.0) + Ffresh.get("H2O", 0.0) +
                  Ffresh.get("CO", 0.0) + Ffresh.get("CO2", 0.0)) * (1 + RR),
    }
    ftot_kmol_h = sum(F0.values())
    # actual volumetric flow at reactor T,p (ideal gas, m3/h)
    Q_actual = ftot_kmol_h * 8.314462618 * T / (p * 100.0)   # kmol/h * kPa*m3/(kmol K)*K/kPa
    V_cat = Q_actual / GHSV
    Fout = _rk4_ammonia(T, p, F0, V_cat, eta)
    X_N2 = (F0["N2"] - Fout["N2"]) / F0["N2"] if F0["N2"] else 0.0
    y_nh3 = Fout["NH3"] / sum(Fout.values())
    # uncalibrated reference (eta = 1)
    Fout1 = _rk4_ammonia(T, p, F0, V_cat, 1.0)
    X_N2_uncal = (F0["N2"] - Fout1["N2"]) / F0["N2"] if F0["N2"] else 0.0
    return {
        "model": "Temkin-Pyzhev / Dyson-Simon",
        "source": TEMKIN["source"], "status": K["status"],
        "applicability": K["applicability"],
        "T_K": T, "p_bar": p, "GHSV_h1": GHSV,
        "alpha": TEMKIN["alpha"], "Ea_kJ_mol": TEMKIN["Ea_J_mol"] / 1000.0,
        "k0_kmol_m3cat_h": TEMKIN["k0_kmol_m3cat_h"],
        "K_a": ammonia_Ka(T),
        "effectiveness_eta": eta,
        "catalyst_volume_m3": V_cat,
        "per_pass_N2_conversion": X_N2,
        "per_pass_N2_conversion_eta1": X_N2_uncal,
        "outlet_NH3_molpct": 100 * y_nh3,
        "heat_released_MW": (Fout["NH3"] - F0["NH3"]) * 1000.0 * 46.0 / 3600.0 / 1000.0,
        "note": "isothermal PFR, ideal-gas activities (phi=1). eta is an APPARENT "
                "effectiveness/activity factor calibrated to the opened 15-20% "
                "industrial per-pass conversion; eta=1 result is reported for "
                "transparency. This is NOT an independently validated rate constant.",
    }


def methanol_benchmark_check(cfg):
    """External check: reproduce the opened Arzew CP1Z industrial reactor.

    Inlet composition (mol%) from the opened HYSYS study, first catalyst bed:
    CO 7.5, CO2 6.0, H2 73.7, H2O 0.13, MeOH 0, inert 12.67.
    Published outlet after 4 quench beds at 52 bar / 210-270 C:
    MeOH 3.41 mol% (plant 3.4), CO 5.4, CO2 7.6, H2 69.35.
    Our lumped single isothermal PFR is swept over GHSV; no hidden fit.
    """
    K = cfg.raw["kinetics"]["methanol"]
    T, p = 523.15, 52.0
    F0 = {"CO2": 6.0, "CO": 7.5, "H2": 73.7, "H2O": 0.13,
          "CH3OH": 0.001, "INERT": 12.669}
    rows = []
    for G in K["GHSV_benchmark_sweep_h1"]:
        W = sum(F0.values()) * 3600.0 * VM_NORMAL / G * K["catalyst_density_kg_m3"]
        F = _rk4_methanol(T, p, F0, W, n=2000)
        tot = sum(F.values())
        rows.append({"GHSV_h1": G,
                     "outlet_MeOH_molpct": 100 * F["CH3OH"] / tot,
                     "outlet_CO_molpct": 100 * F["CO"] / tot,
                     "outlet_CO2_molpct": 100 * F["CO2"] / tot,
                     "outlet_H2_molpct": 100 * F["H2"] / tot})
    best = min(rows, key=lambda x: abs(x["outlet_MeOH_molpct"] - 3.41))
    return {
        "benchmark": cfg.raw["kinetics"]["methanol_benchmark"],
        "inlet_molpct": F0, "p_bar": p, "T_K": T,
        "sweep": rows, "best": best,
        "deviation_pct": (best["outlet_MeOH_molpct"] / 3.41 - 1.0) * 100.0,
        "status": "[ЧАСТИЧНО] single isothermal PFR vs 4-bed adiabatic quench "
                  "reactor; agreement depends on the effective space velocity",
    }


def ammonia_benchmark_check(r, cfg):
    """External check against opened industrial per-pass conversion benchmarks."""
    K = cfg.raw["kinetics"]["ammonia"]
    B = cfg.raw["kinetics"]["ammonia_benchmark"]
    T, p = K["T_K"], K["p_bar"]
    RR = K["recycle_ratio"]
    scale = r["flows"]["scale_100mol_NG_per_h"]
    n = r["downstream"]["n"]
    Ff = {k: v * scale / 1000.0 for k, v in n.items()}     # kmol/h
    F0 = {"N2": Ff.get("N2", 0.0) * (1 + RR),
          "H2": Ff.get("H2", 0.0) * (1 + RR),
          "NH3": K["inlet_NH3_molpct"] / 100.0 * sum(Ff.values()) * (1 + RR),
          "INERT": (Ff.get("CH4", 0.0) + Ff.get("H2O", 0.0) +
                    Ff.get("CO", 0.0) + Ff.get("CO2", 0.0)) * (1 + RR)}
    Q = sum(F0.values()) * 8.314462618 * T / (p * 100.0)
    rows = []
    for G in K["GHSV_benchmark_sweep_h1"]:
        V = Q / G
        F = _rk4_ammonia(T, p, F0, V, 1.0, n=1000)
        rows.append({"GHSV_h1": G,
                     "per_pass_N2_conversion": (F0["N2"] - F["N2"]) / F0["N2"],
                     "outlet_NH3_molpct": 100 * F["NH3"] / sum(F.values())})
    best = min(rows, key=lambda x: abs(x["outlet_NH3_molpct"] -
                                       B["outlet_NH3_molpct_benchmark"]))
    return {
        "benchmark": B, "sweep": rows, "best_for_NH3_outlet": best,
        "reference_case": rows[0],
        "opened_GHSV_range_h1": [10000.0, 30000.0],
        "gap": "the isothermal single-bed PFR needs an effective GHSV well below "
               "the opened 10000-30000 1/h range to reproduce the industrial "
               "13 mol% NH3 outlet; this is an unresolved scale-up gap",
        "status": "[НЕ ПОДТВЕРЖДЕНО] absolute rate scale",
    }


def kinetic_synthesis_report(r, cfg):
    prod = r["product"]
    out = {"product": prod, "models_available": ["methanol_vbf", "ammonia_temkin"]}
    if prod == "methanol":
        out["methanol_vbf"] = methanol_kinetic_pfr(r, cfg)
        out["benchmark_check"] = methanol_benchmark_check(cfg)
        out["used"] = "methanol_vbf"
    elif prod == "ammonia":
        out["ammonia_temkin"] = ammonia_kinetic_pfr(r, cfg)
        out["benchmark_check"] = ammonia_benchmark_check(r, cfg)
        out["used"] = "ammonia_temkin"
    else:
        out["used"] = None
        out["note"] = ("no opened kinetic rate law implemented for this product in "
                       "this session; stoichiometric balance retained")
    return out
