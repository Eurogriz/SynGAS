"""Real-gas Peng-Robinson EOS + fugacity/enthalpy departure for the syngas model.

Pure stdlib. Sources:
  * Tc, pc, omega: Cantera 3.2.0 critical-properties.yaml (NIST WebBook + Yaws),
    data/critical_properties.json (opened, header checked).
  * H2O Tc/pc: opened NIST WebBook water Mask=4 (647 K, 220.64 bar);
    omega_H2O = 0.344 [ASSUMPTION].
  * k_ij: opened ACS Omega 2019, 4, 13279 (CO2/alkane 0.10-0.14) and
    industrialmonitordirect PR k_ij table (CO2-CH4 0.12-0.15, CO2-C2H6
    0.08-0.12, CO2-C3H8 0.12-0.18); H2O-alkane values from the Reaktoro
    GitHub discussion (opened snippet): 0.48-0.55. All k_ij are configurable.
  * PR form: standard Peng-Robinson (R,J, kappa = 0.37464+1.54226w-0.26992w^2).

STATUS: k_ij sets are [PARTIAL] (secondary/open, not primary HYSYS databank);
a k_ij = 0 set is kept for sensitivity. Fugacity coefficients at 1123 K/25 bar
change K(R1) by ~+1.7% - quantified, not ignored.
"""
from __future__ import annotations
import json, math, os
from .thermo import SPECIES, GASES, R_J, R_KJ

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CRIT = json.load(open(os.path.join(ROOT, "data", "critical_properties.json"), encoding="utf-8"))["species"]
CRIT.setdefault("H2O", {"critical-temperature": 647.0,
                        "critical-pressure": 220.64e5,
                        "acentric-factor": 0.344})
# Names in Cantera file
_ALIAS = {"C_GR": None}
ORDER = [s for s in GASES if s in CRIT]

KIJ = {
    "zero": {},                         # all k_ij = 0
    "base": {                           # [PARTIAL] secondary literature
        ("CO2", "CH4"): 0.13,
        ("CO2", "C2H6"): 0.10,
        ("CO2", "C3H8"): 0.15,
        ("CO2", "H2O"): 0.19,
        ("H2O", "CH4"): 0.485,
        ("H2O", "C2H6"): 0.492,
        ("H2O", "C3H8"): 0.5525,
        ("H2O", "CO2"): 0.1896,
        ("H2O", "N2"): 0.4778,
        ("H2", "CH4"): 0.02,
        ("H2", "CO"): 0.02,
        ("H2", "CO2"): 0.10,
        ("CO", "CH4"): 0.02,
    },
    "high": {                           # upper bound for sensitivity
        ("CO2", "CH4"): 0.15, ("CO2", "C2H6"): 0.12, ("CO2", "C3H8"): 0.18,
        ("CO2", "H2O"): 0.25, ("H2O", "CH4"): 0.55, ("H2O", "C2H6"): 0.55,
        ("H2O", "C3H8"): 0.60, ("H2O", "N2"): 0.50, ("H2", "CO2"): 0.15,
    },
}


def _kij(a, b, kset):
    d = KIJ.get(kset, KIJ["base"])
    return d.get((a, b), d.get((b, a), 0.0))


def _ai(T, s):
    c = CRIT[s]
    Tc = float(c["critical-temperature"]); pc = float(c["critical-pressure"])
    w = float(c["acentric-factor"])
    kap = 0.37464 + 1.54226 * w - 0.26992 * w * w
    alpha = (1.0 + kap * (1.0 - math.sqrt(T / Tc))) ** 2
    return 0.45724 * R_J ** 2 * Tc ** 2 / pc * alpha


def _bi(s):
    c = CRIT[s]
    return 0.07780 * R_J * float(c["critical-temperature"]) / float(c["critical-pressure"])


def _cubic_roots(coeff):
    # Newton from gas-like initial guess; returns largest real root
    f = lambda z: ((z + coeff[1]) * z + coeff[2]) * z + coeff[3]
    df = lambda z: (3 * z + 2 * coeff[1]) * z + coeff[2]
    z = 1.0
    for _ in range(80):
        v = f(z)
        if abs(v) < 1e-14:
            break
        d = df(z)
        if abs(d) < 1e-30:
            z += 0.1
            continue
        z -= v / d
    return z if z > 0 else 1.0


def peng_robinson(y: dict, T: float, p_bar: float, kset="base"):
    """Return (Z, {species: ln_phi}, H_residual_J_per_mol_mixture).

    y: gas mole fractions (C_GR excluded). p_bar ABSOLUTE.
    H_residual is the mixture enthalpy departure h - h_ideal_gas [J/mol].
    """
    names = [s for s in ORDER if y.get(s, 0.0) > 0]
    yy = [y[s] for s in names]
    tot = sum(yy)
    yy = [v / tot for v in yy]
    p = p_bar * 1e5
    a = [_ai(T, s) for s in names]
    b = [_bi(s) for s in names]
    amix = 0.0
    da_dT = 0.0
    # numerical derivative of a_mix w.r.t T (for enthalpy departure)
    def amix_at(TT):
        aa = []
        for s in names:
            c = CRIT[s]; Tc = float(c["critical-temperature"]); pc = float(c["critical-pressure"])
            w = float(c["acentric-factor"])
            kap = 0.37464 + 1.54226 * w - 0.26992 * w * w
            al = (1.0 + kap * (1.0 - math.sqrt(TT / Tc))) ** 2
            aa.append(0.45724 * R_J ** 2 * Tc ** 2 / pc * al)
        return sum(yy[i] * yy[j] * math.sqrt(aa[i] * aa[j]) *
                   (1 - _kij(names[i], names[j], kset))
                   for i in range(len(names)) for j in range(len(names)))
    eps = 0.05
    amix = amix_at(T)
    damix_dT = (amix_at(T + eps) - amix_at(T - eps)) / (2 * eps)
    bmix = sum(yy[i] * b[i] for i in range(len(names)))
    A = amix * p / (R_J ** 2 * T ** 2)
    B = bmix * p / (R_J * T)
    coeff = [1.0, -(1 - B), A - 3 * B ** 2 - 2 * B,
             -(A * B - B ** 2 - B ** 3)]
    Z = _cubic_roots(coeff)
    if Z <= B:
        Z = B + 1e-6
    sq2 = math.sqrt(2.0)
    L = math.log((Z + (1 + sq2) * B) / (Z + (1 - sq2) * B))
    lnphi = {}
    for i, s in enumerate(names):
        sa = sum(yy[j] * math.sqrt(a[i] * a[j]) * (1 - _kij(s, names[j], kset))
                 for j in range(len(names)))
        lnphi[s] = (b[i] / bmix * (Z - 1) - math.log(Z - B)
                    - A / (2 * sq2 * B) * (2 * sa / amix - b[i] / bmix) * L)
    Hres = R_J * T * (Z - 1) + (T * damix_dT - amix) / (2 * sq2 * bmix) * L
    return Z, lnphi, Hres


def lnphi_vector(y: dict, T: float, p_bar: float, kset="base"):
    _, lp, _ = peng_robinson(y, T, p_bar, kset)
    return lp


def residual_enthalpy_kj_per_mol(y: dict, T: float, p_bar: float, kset="base"):
    return peng_robinson(y, T, p_bar, kset)[2] / 1000.0


def gas_density_kg_m3(y: dict, T: float, p_bar: float, kset="base"):
    Z = peng_robinson(y, T, p_bar, kset)[0]
    MW = {"CH4": 0.0160425, "C2H6": 0.030069, "C3H8": 0.044096,
          "H2O": 0.0180153, "CO": 0.0280101, "CO2": 0.0440095,
          "H2": 0.00201588, "O2": 0.0319988, "N2": 0.0280134}
    mw = sum(y.get(k, 0.0) * MW.get(k, 0.0) for k in y if k != "C_GR")
    return (p_bar * 1e5) * mw / (Z * R_J * T)
