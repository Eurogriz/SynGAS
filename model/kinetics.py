"""L2 (PARTIAL): Xu-Froment LHHW kinetics, isothermal PFR.

STATUS: [PARTIAL] / [NOT VALIDATED FOR DESIGN]

Parameter set and rate equations were transcribed from an OPENED open-access
secondary source:
  Fernandes F.A.N. & Soares Jr. A.B., "Modeling of Methane Steam Reforming
  in a Palladium Membrane Reactor", Latin American Applied Research 36
  (2006) 155-161, https://www.scielo.org.ar/pdf/laar/v36n3/v36n3a04.pdf
  (Table 1 = kinetic parameters, Table 2 = equilibrium constants,
   Table 3 = operating conditions, Eqs. 4-7 = rate expressions).

NOT the primary Xu & Froment (1989) article: its full text was NOT accessible
in this session (Crossref record + abstract only). Therefore:
  * the numbers below are a secondary reproduction, not primary data;
  * the source's Table 1 header says "Ea or dH [J/mol]" but the printed values
    (240.1, 67.13, 243.9) are clearly kJ/mol - this unit inconsistency is
    documented, kJ/mol is used;
  * Table 3 gives catalyst density as 2355.2 g_cat/m3; 2355.2 kg/m3 is the
    physically plausible reading and is used with an explicit [ASSUMPTION];
  * original Xu-Froment kinetics were obtained at 773-848 K, 3-10 bar on
    Ni/MgAl2O4. The design case is 1123 K, 25 bar -> OUTSIDE the range.
    NO design decision in this package relies on this module.
"""
from __future__ import annotations
import math

R_J = 8.314462618
R_KJ = 8.314462618e-3

# Table 1 (Fernandes & Soares 2006), pre-exponentials in mol atm^0.5/(g_cat h)
# or mol/(g_cat h); Ea in kJ/mol (source header misleading, see docstring).
K0 = {"k1": 4.2248e15, "k2": 1.955e6, "k3": 1.0202e15}
EA_KJ = {"k1": 240.1, "k2": 67.13, "k3": 243.9}
ADS_K0 = {"CH4": 6.65e-4, "H2O": 1.77e5, "H2": 6.12e-9, "CO": 8.23e-5}
ADS_DH_J = {"CH4": -38280.0, "H2O": 88680.0, "H2": -82900.0, "CO": -70650.0}
# Table 2: K_j = A_j exp(-dH_j/(R T))
EQ_A = {"K1": 7.846e12, "K2": 1.412e-2, "K3": 1.11e11}
EQ_DH_J = {"K1": 220200.0, "K2": -37720.0, "K3": 182400.0}

# Table 3 operating conditions (conventional reactor, no membrane)
FERNANDES = {"F_CH4_0_mol_h": 5200.0, "H2O_CH4": 3.358, "CO2_CH4": 0.056,
             "H2_CH4": 0.122, "N2_CH4": 0.164, "p_atm": 29.0,
             "rho_cat_kg_m3": 2355.2, "L_m": 20.0, "r_tube_m": 0.1016}


def coefficients(T):
    k = {j: K0[j] * math.exp(-EA_KJ[j] / (R_KJ * T)) for j in K0}
    Keq = {j: EQ_A[j] * math.exp(-EQ_DH_J[j] / (R_J * T)) for j in EQ_A}
    Kads = {i: ADS_K0[i] * math.exp(-ADS_DH_J[i] / (R_J * T)) for i in ADS_K0}
    return k, Keq, Kads


def rates(F, T, p_atm, coeffs=None, eps_h2=1e-6):
    """F: dict of molar flows [mol/h]; returns R1,R2,R3 [mol/(g_cat h)]."""
    k, Keq, Kads = coeffs or coefficients(T)
    tot = sum(F.values())
    p = {s: max(F.get(s, 0.0), 0.0) / tot * p_atm for s in
         ("CH4", "H2O", "CO", "CO2", "H2", "N2")}
    ph2 = max(p["H2"], eps_h2)
    den = (1.0 + Kads["CO"] * p["CO"] + Kads["H2"] * p["H2"]
           + Kads["CH4"] * p["CH4"] + Kads["H2O"] * p["H2O"] / ph2)
    D2 = den * den
    R1 = (k["k1"] / ph2 ** 2.5 *
          (p["CH4"] * p["H2O"] - p["H2"] ** 3 * p["CO"] / Keq["K1"])) / D2
    R2 = (k["k2"] / ph2 *
          (p["CO"] * p["H2O"] - p["H2"] * p["CO2"] / Keq["K2"])) / D2
    R3 = (k["k3"] / ph2 ** 3.5 *
          (p["CH4"] * p["H2O"] ** 2 - p["H2"] ** 4 * p["CO2"] / Keq["K3"])) / D2
    return R1, R2, R3


def dFdW(F, T, p_atm, coeffs):
    R1, R2, R3 = rates(F, T, p_atm, coeffs)
    return {"CH4": -(R1 + R3), "H2O": -(R1 + R2 + 2 * R3),
            "H2": 3 * R1 + R2 + 4 * R3, "CO": R1 - R2,
            "CO2": R2 + R3, "N2": 0.0}


def _rk4_step(F, h, T, p_atm, coeffs):
    k1 = dFdW(F, T, p_atm, coeffs)
    F2 = {s: F[s] + 0.5 * h * k1[s] for s in F}
    k2 = dFdW(F2, T, p_atm, coeffs)
    F3 = {s: F[s] + 0.5 * h * k2[s] for s in F}
    k3 = dFdW(F3, T, p_atm, coeffs)
    F4 = {s: F[s] + h * k3[s] for s in F}
    k4 = dFdW(F4, T, p_atm, coeffs)
    out = {s: F[s] + h / 6 * (k1[s] + 2 * k2[s] + 2 * k3[s] + k4[s]) for s in F}
    return out


def pfr(T, p_atm=29.0, W_g=None, cond=None, n_steps=4000, density_factor=1.0,
        max_rel_change=0.02):
    """Isothermal PFR with an ADAPTIVE step (rates are stiff).

    density_factor=1.0 uses the source's printed 2355.2 g_cat/m3;
    density_factor=1000.0 uses the physically plausible 2355.2 kg_cat/m3.
    Both are reported; the ambiguity is a documented unit inconsistency.
    """
    c = dict(cond or FERNANDES)
    f0 = c["F_CH4_0_mol_h"]
    if W_g is None:
        area = math.pi * c["r_tube_m"] ** 2
        W_g = c["rho_cat_kg_m3"] * density_factor * area * c["L_m"]
    F = {"CH4": f0, "H2O": f0 * c["H2O_CH4"], "CO": 0.0,
         "CO2": f0 * c["CO2_CH4"], "H2": f0 * c["H2_CH4"],
         "N2": f0 * c["N2_CH4"]}
    coeffs = coefficients(T)
    W = 0.0
    h = W_g / n_steps
    profiles = [{"W_g": 0.0, "X_CH4": 0.0, "y_H2": F["H2"] / sum(F.values())}]
    accepted = 0
    while W < W_g and accepted < 200000:
        h = min(h, W_g - W)
        Fn = _rk4_step(F, h, T, p_atm, coeffs)
        rel = max(abs(Fn[s] - F[s]) / max(abs(F[s]), 1e-9) for s in F)
        if any(v <= 0 for v in Fn.values() if v > 0) or rel > max_rel_change or h < 1e-14:
            h *= 0.5
            if h < 1e-18:
                break
            continue
        F = {s: max(Fn[s], 1e-12) for s in Fn}
        W += h
        accepted += 1
        h *= 1.4
        if accepted % 20 == 0:
            profiles.append({"W_g": W, "X_CH4": 1 - F["CH4"] / f0,
                             "y_H2": F["H2"] / sum(F.values())})
    profiles.append({"W_g": W, "X_CH4": 1 - F["CH4"] / f0,
                     "y_H2": F["H2"] / sum(F.values())})
    return {"T_K": T, "p_atm": p_atm, "W_g": W_g, "W_integrated_g": W,
            "steps": accepted, "X_CH4": 1 - F["CH4"] / f0,
            "F_out_mol_h": F, "profiles": profiles,
            "status": "[PARTIAL] secondary Xu-Froment parameters; outside the original T/p range at design conditions"}


# Fig. 5a of Fernandes & Soares (2006): conventional reactor, 29 atm, 20 m.
# Digitised from the table printed in the opened PDF (not from the image).
PUBLISHED_CONVERSION = {750.0: 0.18, 800.0: 0.38, 850.0: 0.55,
                        900.0: 0.73, 950.0: 0.88, 1000.0: 0.97}


def validate_against_published_model():
    rows = []
    for T, X in PUBLISHED_CONVERSION.items():
        a = pfr(T, 29.0, density_factor=1.0)
        b = pfr(T, 29.0, density_factor=1000.0)
        rows.append({"T_K": T, "X_published": X,
                     "X_density_as_printed_g_m3": a["X_CH4"],
                     "X_density_as_kg_m3": b["X_CH4"],
                     "abs_deviation_printed": abs(a["X_CH4"] - X),
                     "abs_deviation_kg_m3": abs(b["X_CH4"] - X)})
    best = "printed_g_m3" if sum(r["abs_deviation_printed"] for r in rows) < sum(r["abs_deviation_kg_m3"] for r in rows) else "kg_m3"
    dev = [r["abs_deviation_printed"] if best == "printed_g_m3" else r["abs_deviation_kg_m3"] for r in rows]
    return {
        "density_unit_interpretation_that_best_matches_published_curve": best,
        "calibration_note": "The source's Table 3 unit for catalyst density is ambiguous; both readings were RUN, not assumed. This is a documented fitting/interpretation choice (rule 1.5).",
        "status": "code verification against a published INDEPENDENT MODEL IMPLEMENTATION, not against experiment",
        "source": "Fernandes & Soares, Latin Am. Appl. Res. 36 (2006) 155-161, Fig. 5a, 29 atm conventional reactor (opened PDF)",
        "rows": rows,
        "max_abs_deviation": max(dev),
        "mean_abs_deviation": sum(dev) / len(dev),
        "warning": "Reproducing another model's curve does NOT validate the kinetics for the Ni/MgAl2O4 design catalyst at 1123 K / 25 bar.",
    }
