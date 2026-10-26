"""G3: quantitative sintering / degradation assessment for every catalyst option."""
from __future__ import annotations
import json, math, os
from .thermo import R_KJ

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MELT = json.load(open(os.path.join(ROOT, "data", "melting_points.json")))["K"]

# Melting temperatures, K. Two independent opened sources for Ni, Al2O3, MgAl2O4.
# NIST-JANAF (WebBook pages) and NASA TM-4513 (Cantera nasa_condensed.yaml)
# agree exactly; MgAl2O4 is additionally consistent with US7541005B2 (2135 C).
T_MELT = {
    "Ni":         {"K": 1728.0, "status": "[CONFIRMED]", "sources": ["NIST WebBook C7440020 Mask=2 (Chase 1998)", "NASA TM-4513 via Cantera nasa_condensed.yaml Ni(cr)"]},
    "NiO":        {"K": None,   "status": "[NOT CONFIRMED]", "sources": ["not found in the opened databases this session"]},
    "Al2O3_alpha":{"K": 2327.0, "status": "[CONFIRMED]", "sources": ["NIST WebBook C1344281 Mask=2 (Chase 1998)", "NASA TM-4513 AL2O3(a)"]},
    "MgAl2O4":    {"K": 2408.0, "status": "[CONFIRMED]", "sources": ["NASA TM-4513 MgAL2O4(s) upper fit bound", "US7541005B2 states 2135 C = 2408.15 K (patent, opened)"]},
    "ZrO2":       {"K": 2950.0, "status": "[PARTIAL]", "sources": ["NASA TM-4513 ZrO2(b) upper fit bound; single source"]},
    "CeO2":       {"K": None,   "status": "[NOT CONFIRMED]", "sources": ["not found in the opened databases this session"]},
    "CaAl2O4":    {"K": None,   "status": "[NOT CONFIRMED]", "sources": ["not found in the opened databases this session"]},
}

T_WALL_NORMAL = 1178.15     # 905 C, opened SMR tube-skin modelling papers
T_WALL_PEAK = 1223.15       # 950 C [ASSUMPTION] upset / hot spot
T_GAS_OUT = 1123.15         # 850 C [ASSUMPTION] base case
LIFE_H = 26280.0            # 3 years [ASSUMPTION]


def tamman(Tm): return 0.5 * Tm
def huttig(Tm): return 0.3 * Tm


def temperature_check(Tm):
    if Tm is None:
        return {"status": "[NOT CONFIRMED]", "reason": "no melting point from an opened source"}
    return {
        "T_melt_K": Tm,
        "Tamman_K": tamman(Tm), "Huttig_K": huttig(Tm),
        "T_wall_normal_K": T_WALL_NORMAL, "T_wall_peak_K": T_WALL_PEAK,
        "wall_normal_over_Tamman": T_WALL_NORMAL / tamman(Tm),
        "wall_peak_over_Tamman": T_WALL_PEAK / tamman(Tm),
        "wall_normal_over_Huttig": T_WALL_NORMAL / huttig(Tm),
        "above_Huttig": T_WALL_NORMAL > huttig(Tm),
        "above_Tamman": T_WALL_NORMAL > tamman(Tm),
    }


# --- Empirical degradation model ------------------------------------------------
# Anchor A: 7.6 wt% Ni/MgAl2O4, 7.7 -> 27.0 nm in 700 h at 773 K, 30 bar,
# steam:H2 = 10:1 v/v. Quoted in Mei et al., J. Catal. 316 (2014) 11-23,
# DOI 10.1016/j.jcat.2014.04.021 (opened abstract/introduction).
# Anchor B: 20 wt% Ni/MgAl2O4, <2 -> 6.8 nm in 1 h at 1073 K in N2.
# PNNL-23207 (2014), opened. d0 = 2.0 nm is a CONSERVATIVE reading of "<2 nm".
# Anchor C (support comparison): 20 wt% Ni/Al2O3 10.5 -> 16 nm in 20 h,
# PNNL-23207.
ANCHORS = {
    "A": {"T_K": 773.0, "t_h": 700.0, "d0_nm": 7.7, "d_nm": 27.0, "system": "7.6wt%Ni/MgAl2O4, 30 bar, steam:H2=10:1"},
    "B": {"T_K": 1073.0, "t_h": 1.0, "d0_nm": 2.0, "d_nm": 6.8, "system": "20wt%Ni/MgAl2O4, N2, 800 C"},
    "C": {"T_K": 773.0, "t_h": 20.0, "d0_nm": 10.5, "d_nm": 16.0, "system": "20wt%Ni/Al2O3, CO methanation"},
}
N_POWER = 4.0    # [PARTIAL] Sehested-type power-law exponent 4-6 at 800 C (secondary quoting); see docs/04


def k_from_anchor(a, n=N_POWER):
    return (a["d_nm"] ** n - a["d0_nm"] ** n) / a["t_h"]


def fit_model(n=N_POWER):
    kA = k_from_anchor(ANCHORS["A"], n)
    kB = k_from_anchor(ANCHORS["B"], n)
    TA, TB = ANCHORS["A"]["T_K"], ANCHORS["B"]["T_K"]
    # k(T) = k_ref exp(-Ea/R (1/T - 1/T_ref))
    Ea = R_KJ * math.log(kB / kA) / (1 / TA - 1 / TB)   # kJ/mol
    k_ref, T_ref = kA, TA
    return {"n": n, "k_ref": k_ref, "T_ref_K": T_ref, "Ea_kJ_per_mol": Ea,
            "k_A": kA, "k_B": kB,
            "warning": "Ea is fitted from TWO DIFFERENT catalysts/atmospheres; this is an [ASSUMPTION], not a measured activation energy."}


def predict_diameter(model, T, t_h, d0=6.6):
    k = model["k_ref"] * math.exp(-model["Ea_kJ_per_mol"] / R_KJ *
                                  (1 / T - 1 / model["T_ref_K"]))
    return (d0 ** model["n"] + k * t_h) ** (1 / model["n"]), k


# --- GPLE-style bounded model (rule 6.2c) ---------------------------------------
# Sehested et al., "Sintering of Nickel Steam-Reforming Catalysts on MgAl2O4
# Spinel Supports", J. Catal. 2001 (DOI to be verified in docs/02): most
# sintering occurs in the first 200 h and the Ni particle size tends to a
# limiting value. We therefore ALSO fit a first-order GPLE in dispersion:
#     d(t) = d_lim - (d_lim - d0) exp(-k(T) t)
D_LIM_NM = 30.0          # [ASSUMPTION] consistent with 27.0 nm at 700 h in anchor A
EA_GPLE_KJ_MOL = 100.0   # [ASSUMPTION] no measured Ni sintering Ea was opened


def gple_predict(T, t_h, d0=6.6, ea=EA_GPLE_KJ_MOL, d_lim=D_LIM_NM):
    a = ANCHORS["A"]
    k_ref = -math.log((d_lim - a["d_nm"]) / (d_lim - a["d0_nm"])) / a["t_h"]
    k = k_ref * math.exp(-ea / R_KJ * (1 / T - 1 / a["T_K"]))
    d = d_lim - (d_lim - d0) * math.exp(-k * t_h)
    return {"T_K": T, "k_ref_per_h": k_ref, "k_per_h": k, "d_lim_nm": d_lim,
            "d_EOR_nm": d, "activity_A_EOR": d0 / d,
            "loss_of_active_surface_pct": (1 - d0 / d) * 100}


def degradation_report(case):
    cat = case["catalyst"]
    d0 = cat["Ni_particle_nm"]
    life = cat["design_life_h"]
    model = fit_model()
    out = {"melting_points": T_MELT,
           "temperature_checks": {k: temperature_check(v["K"]) for k, v in T_MELT.items()},
           "empirical_model": model, "anchors": ANCHORS,
           "T_wall_normal_K": T_WALL_NORMAL, "T_wall_peak_K": T_WALL_PEAK,
           "design_life_h": life, "d0_nm": d0,
           "predictions": {}, "sensitivity": []}
    for label, T in (("gas_outlet", T_GAS_OUT), ("wall_normal", T_WALL_NORMAL),
                     ("wall_peak", T_WALL_PEAK)):
        d, k = predict_diameter(model, T, life, d0)
        out["predictions"][label] = {
            "T_K": T, "k_nm4_per_h": k, "d_EOR_nm": d,
            "dispersion_ratio": d0 / d, "activity_A_EOR": d0 / d,
            "loss_of_active_surface_pct": (1 - d0 / d) * 100}
    # Sensitivity: n, Ea, T_wall, life
    for n in (2.0, 3.0, 4.0, 6.0, 13.0):
        m = fit_model(n)
        d, _ = predict_diameter(m, T_WALL_NORMAL, life, d0)
        out["sensitivity"].append({"case": f"n={n}", "A_EOR": d0 / d})
    for fac in (0.5, 0.75, 1.0, 1.25, 1.5):
        m = dict(model); m["Ea_kJ_per_mol"] = model["Ea_kJ_per_mol"] * fac
        d, _ = predict_diameter(m, T_WALL_NORMAL, life, d0)
        out["sensitivity"].append({"case": f"Ea x{fac}", "A_EOR": d0 / d})
    for dT in (-50, 0, 50):
        d, _ = predict_diameter(model, T_WALL_NORMAL + dT, life, d0)
        out["sensitivity"].append({"case": f"T_wall {dT:+} K", "A_EOR": d0 / d})
    # Independent bounded (GPLE) model and its own sensitivity
    out["gple_model"] = {"Ea_kJ_per_mol": EA_GPLE_KJ_MOL, "D_lim_nm": D_LIM_NM,
                         "status": "[ASSUMPTION] both parameters; only the QUALITATIVE asymptotic behaviour is sourced",
                         "predictions": {}}
    for label, T in (("gas_outlet", T_GAS_OUT), ("wall_normal", T_WALL_NORMAL),
                     ("wall_peak", T_WALL_PEAK)):
        out["gple_model"]["predictions"][label] = gple_predict(T, life, d0)
    out["gple_model"]["sensitivity"] = [
        {"case": f"Ea={ea} kJ/mol", **gple_predict(T_WALL_NORMAL, life, d0, ea=ea)}
        for ea in (50.0, 100.0, 150.0, 200.0)]
    # Design consequence: catalyst reserve required to keep initial activity
    A_power = out["predictions"]["wall_normal"]["activity_A_EOR"]
    A_gple = out["gple_model"]["predictions"]["wall_normal"]["activity_A_EOR"]
    out["catalyst_reserve_factor"] = 1 / A_gple if A_gple > 0 else None
    out["catalyst_reserve_range"] = {"power_law": 1 / A_power if A_power else None,
                                      "gple_bounded": 1 / A_gple if A_gple else None}
    out["model_disagreement_factor"] = A_gple / A_power
    out["note"] = ("A(t) proportional to Ni dispersion (1/d). The unbounded power law "
                   "and the bounded GPLE disagree by a large factor; NEITHER was fitted "
                   "to ageing data at the design temperature. Therefore the 3-year "
                   "life, the catalyst reserve and the admissible wall temperature are "
                   "NOT VALIDATED. Vendor ageing data at 850-950 C in steam/H2 at 25 bar "
                   "are a hard blocker for G3/G6. Coke, sulfur and NiAl2O4 formation are "
                   "listed separately as risks.")
    return out


CATALYST_MATRIX = [
    # name, support Tm key, activity, sintering, coke, steam, S, strength, reducibility, cost, TRL, status
    {"option": "Ni/MgAl2O4 (basis)", "Tm_K": 2408.0, "activity": 3, "sintering": 4, "coke": 3,
     "steam": 4, "sulfur": 2, "strength": 4, "reducibility": 2, "cost": 5, "TRL": 5,
     "status": "[CONFIRMED]", "basis": "Catalysts 2019,9,801; EP1013603A1; PNNL-23207; J.Catal. 2014,316,11-23"},
    {"option": "Ni/alpha-Al2O3", "Tm_K": 2327.0, "activity": 3, "sintering": 3, "coke": 2,
     "steam": 3, "sulfur": 2, "strength": 4, "reducibility": 3, "cost": 5, "TRL": 5,
     "status": "[PARTIAL]", "basis": "NIST-JANAF Al2O3 Tm; PNNL-23207 Ni/Al2O3 data; no vendor spec"},
    {"option": "Ni/gamma-Al2O3 (unstabilised)", "Tm_K": 2327.0, "activity": 4, "sintering": 1, "coke": 2,
     "steam": 1, "sulfur": 2, "strength": 2, "reducibility": 3, "cost": 5, "TRL": 3,
     "status": "[NOT CONFIRMED] REJECTED", "basis": "theta->alpha transition 1050-1200 C and >80% area loss (opened ceramics papers); quantitative life at 850 C not available"},
    {"option": "Ni/Ca-aluminate", "Tm_K": None, "activity": 3, "sintering": 3, "coke": 3,
     "steam": 3, "sulfur": 2, "strength": 4, "reducibility": 3, "cost": 4, "TRL": 5,
     "status": "[NOT CONFIRMED]", "basis": "EP0279389A1 (2-20 wt% Ni) opened; Tm not found"},
    {"option": "Ni/ZrO2", "Tm_K": 2950.0, "activity": 3, "sintering": 4, "coke": 4,
     "steam": 3, "sulfur": 3, "strength": 3, "reducibility": 3, "cost": 2, "TRL": 2,
     "status": "[NOT CONFIRMED]", "basis": "NASA TM-4513 ZrO2 Tm only; no ageing data on Ni/ZrO2 opened"},
    {"option": "Ni/CeO2-ZrO2", "Tm_K": None, "activity": 4, "sintering": 3, "coke": 5,
     "steam": 3, "sulfur": 3, "strength": 3, "reducibility": 3, "cost": 2, "TRL": 2,
     "status": "[NOT CONFIRMED]", "basis": "no quantitative Tm / ageing data opened"},
    {"option": "Ni-Co, Ni-noble bimetal", "Tm_K": 1728.0, "activity": 4, "sintering": 3, "coke": 4,
     "steam": 3, "sulfur": 2, "strength": 3, "reducibility": 3, "cost": 2, "TRL": 2,
     "status": "[NOT CONFIRMED]", "basis": "US9393552B2 (2-16 wt% Ni + 0.01-0.5 wt% Rh/Ir) opened; no sintering kinetics"},
    {"option": "Rh/Ir on MgAl2O4", "Tm_K": 2408.0, "activity": 5, "sintering": 5, "coke": 4,
     "steam": 4, "sulfur": 3, "strength": 4, "reducibility": 5, "cost": 1, "TRL": 2,
     "status": "[PARTIAL]", "basis": "J.Catal. 2014,316,11-23 + Catalysts 2019,9,801 (1-2 nm stable at 1123 K in steam); cost not quantified"},
    {"option": "structured monolith/foam", "Tm_K": 2408.0, "activity": 3, "sintering": 3, "coke": 3,
     "steam": 3, "sulfur": 2, "strength": 4, "reducibility": 3, "cost": 2, "TRL": 2,
     "status": "[NOT CONFIRMED]", "basis": "no pressure-drop/crush-strength data opened"},
]

# Equal weights declared BEFORE scoring, to avoid fitting the answer (rule 6.3).
WEIGHTS = {"activity": 0.12, "sintering": 0.18, "coke": 0.14, "steam": 0.12,
           "sulfur": 0.08, "strength": 0.08, "reducibility": 0.08,
           "cost": 0.10, "TRL": 0.10}


def score_matrix():
    rows = []
    for c in CATALYST_MATRIX:
        score = sum(WEIGHTS[k] * c[k] for k in WEIGHTS)
        rows.append({**c, "weighted_score": round(score, 3),
                     "temperature_check": temperature_check(c["Tm_K"])})
    return {"weights": WEIGHTS, "rows": rows}
