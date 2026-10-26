"""Thermodynamic property layer. Pure Python standard library only.

Two INDEPENDENT datasets are provided:
  * 'shomate' : NIST Chemistry WebBook Shomate coefficients (NIST-JANAF, Chase 1998)
                for CH4, H2O(g), CO, CO2, H2, O2, N2; plus NASA7 for C2H6
                (GRI-Mech 3.0) and graphite (NASA SP-273 / TM-4513).
  * 'nasa'    : NASA7 coefficients for the same nine species from Cantera's
                GRI-Mech 3.0 + graphite data files.

The second dataset exists ONLY to make verification loop 4 (independent
Gibbs-energy minimisation with independent thermochemistry) possible.

Units: T [K], h [kJ/mol], s [J/mol/K], g [kJ/mol], cp [J/mol/K].
Standard-state pressure p0 = 1 bar for both datasets.
"""
from __future__ import annotations

import json
import math
import os
from functools import lru_cache

R_KJ = 8.31446261815324e-3   # kJ/(mol K), CODATA-derived; see docs/01 C-002
R_J = 8.31446261815324       # J/(mol K)
P0_BAR = 1.0
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# Fixed species order. C_GR = solid graphite (activity = 1, no mixing term).
SPECIES = ("CH4", "C2H6", "C3H8", "H2O", "CO", "CO2", "H2", "O2", "N2", "C_GR")
GASES = SPECIES[:-1]
ELEMENTS = ("C", "H", "O", "N")

COMPOSITION = {
    "CH4":  {"C": 1, "H": 4},
    "C2H6": {"C": 2, "H": 6},
    "C3H8": {"C": 3, "H": 8},
    "H2O":  {"H": 2, "O": 1},
    "CO":   {"C": 1, "O": 1},
    "CO2":  {"C": 1, "O": 2},
    "H2":   {"H": 2},
    "O2":   {"O": 2},
    "N2":   {"N": 2},
    "C_GR": {"C": 1},
}

# NIST WebBook Antoine coefficients for water, log10(P/bar) = A - B/(T[K] + C).
# Source: https://webbook.nist.gov/cgi/cbook.cgi?ID=C7732185&Units=SI&Mask=4
ANTOINE_WATER = [
    (273.0, 303.0, 5.40221, 1838.675, -31.737),   # Bridgeman & Aldrich 1964
    (304.0, 333.0, 5.20389, 1733.926, -39.485),
    (334.0, 363.0, 5.0768, 1659.793, -45.854),
    (344.0, 373.0, 5.08354, 1663.125, -45.622),
    (379.0, 573.0, 3.55959, 643.748, -198.043),   # Liu & Lindsay 1970
    (255.9, 373.0, 4.6543, 1435.264, -64.848),    # Stull 1947
]


@lru_cache(maxsize=None)
def _load(path):
    with open(os.path.join(ROOT, path), "r", encoding="utf-8") as fh:
        return json.load(fh)


def shomate(coeff, T):
    """Return (cp[J/mol/K], h[kJ/mol] absolute, s[J/mol/K], g[kJ/mol])."""
    A, B, C, D, E, F, G, H = coeff
    t = T / 1000.0
    cp = A + B * t + C * t ** 2 + D * t ** 3 + E / t ** 2
    h_inc = A * t + B * t ** 2 / 2 + C * t ** 3 / 3 + D * t ** 4 / 4 - E / t + F - H
    s = A * math.log(t) + B * t + C * t ** 2 / 2 + D * t ** 3 / 3 - E / (2 * t ** 2) + G
    h = H + h_inc
    return cp, h, s, h - T * s / 1000.0


def nasa7(coeff, T):
    """Return (cp[J/mol/K], h[kJ/mol], s[J/mol/K], g[kJ/mol]) from NASA7 a[0..6]."""
    a1, a2, a3, a4, a5, a6, a7 = coeff
    cp = R_J * (a1 + a2 * T + a3 * T ** 2 + a4 * T ** 3 + a5 * T ** 4)
    h = R_KJ * T * (a1 + a2 * T / 2 + a3 * T ** 2 / 3 + a4 * T ** 3 / 4
                    + a5 * T ** 4 / 5 + a6 / T)
    s = R_J * (a1 * math.log(T) + a2 * T + a3 * T ** 2 / 2
               + a4 * T ** 3 / 3 + a5 * T ** 4 / 4 + a7)
    return cp, h, s, h - T * s / 1000.0


def properties(name: str, T: float, dataset: str = "shomate", extrapolate=False):
    """(cp, h, s, g) for a species at T. Range violations raise unless extrapolate."""
    db = _load("data/nist_shomate.json")
    if dataset == "shomate" and name in db.get("liquid", {}):
        rec = db["liquid"][name]
        ranges = rec["ranges"]
        chosen = next((r for r in ranges if r["Tmin"] <= T <= r["Tmax"]), None)
        if chosen is None:
            if not extrapolate:
                raise ValueError(f"{name}: T={T} K outside NIST liquid Shomate range")
            chosen = ranges[0] if T < ranges[0]["Tmin"] else ranges[-1]
        return shomate(chosen["coeff"], T)
    if dataset == "shomate" and name in db["species"]:
        rec = db["species"][name]
        ranges = rec["ranges"]
        chosen = None
        for r in ranges:
            if r["Tmin"] <= T <= r["Tmax"]:
                chosen = r
                break
        if chosen is None:
            if not extrapolate:
                raise ValueError(f"{name}: T={T} K outside NIST Shomate ranges")
            chosen = ranges[0] if T < ranges[0]["Tmin"] else ranges[-1]
        return shomate(chosen["coeff"], T)
    rec = _load("data/gri30_nasa7.json")["species"].get(name)
    if rec is None:
        raise KeyError(f"no thermo data for {name} in dataset {dataset}")
    ranges = rec["temperature_ranges"]
    data = rec["data"]          # len(data) == len(ranges) - 1 (one polynomial per interval)
    if T > ranges[-1] or T < ranges[0]:
        if not extrapolate:
            raise ValueError(f"{name}: T={T} K outside NASA7 ranges {ranges}")
        coeff = data[0] if T < ranges[0] else data[-1]
    else:
        k = 0
        for i in range(len(data)):
            if T <= ranges[i + 1]:
                k = i
                break
        coeff = data[k]
    return nasa7(coeff, T)


def g0(name, T, dataset="shomate"):
    return properties(name, T, dataset)[3]


def h0(name, T, dataset="shomate"):
    return properties(name, T, dataset)[1]


def h_liquid_water(T, dataset="shomate"):
    """Liquid water enthalpy [kJ/mol] from NIST liquid Shomate (Chase 1998)."""
    if dataset == "shomate":
        return properties("H2O_L", T, "shomate")[1]
    # NASA dataset has no condensed phase; use gas enthalpy minus the
    # 298.15 K formation-enthalpy difference (44.004 kJ/mol, NIST CODATA values
    # -241.8264 gas / -285.8304 liquid). Explicit simplification.
    return h0("H2O", T, dataset) - 44.004


def stream_enthalpy(n: dict, T: float, dataset="shomate", liquid_water_mol=0.0,
                    p_bar=None, eos_kset=None, use_iapws_steam=False):
    """Total stream enthalpy [kJ] for molar amounts n at T.

    p_bar + eos_kset -> add Peng-Robinson mixture enthalpy departure.
    use_iapws_steam -> use IF97 for gas/liquid water enthalpy instead of NIST
    Shomate (maximum-accuracy mode). Both are OPTIONAL; default stays the
    verified NIST-based ideal-gas enthalpy used in the first model version.
    """
    gas = {k: v for k, v in n.items() if k in GASES}
    n_gas = sum(gas.values())
    tot = 0.0
    for sp, q in gas.items():
        if not q:
            continue
        if use_iapws_steam and sp == "H2O" and p_bar:
            from .steam import steam_enthalpy_kJ_per_mol as _hst
            # IF97 enthalpy is on a different reference; shift by its 298.15 K
            # gas value so that the reaction enthalpies stay on the NIST baseline.
            from .steam import steam_enthalpy_kJ_per_mol as _h
            ref = _h(298.15, 1.0) - h0("H2O", 298.15, dataset)
            tot += q * (_h(T, p_bar) - ref)
        else:
            tot += q * h0(sp, T, dataset)
    if n.get("C_GR", 0.0):
        tot += n["C_GR"] * h0("C_GR", T, dataset)
    if p_bar and eos_kset and n_gas > 0:
        from .eos import residual_enthalpy_kj_per_mol
        y = {k: v / n_gas for k, v in gas.items()}
        tot += n_gas * residual_enthalpy_kj_per_mol(y, T, p_bar, eos_kset)
    if liquid_water_mol:
        if use_iapws_steam and p_bar:
            from .steam import liquid_enthalpy_kJ_per_mol as _hl
            ref = _hl(298.15, 1.0) - h_liquid_water(298.15, dataset)
            tot += liquid_water_mol * (_hl(T, p_bar) - ref)
        else:
            tot += liquid_water_mol * h_liquid_water(T, dataset)
    return tot


def water_psat_bar(T):
    """Saturation pressure of water [bar] from NIST Antoine sets."""
    cands = [r for r in ANTOINE_WATER if r[0] <= T <= r[1]]
    if not cands:
        cands = [min(ANTOINE_WATER, key=lambda r: min(abs(T - r[0]), abs(T - r[1])))]
        print(f"WARNING: water_psat_bar extrapolated outside NIST Antoine ranges at T={T} K")
    # Prefer the narrowest applicable range (most local fit).
    _, _, A, B, C = min(cands, key=lambda r: r[1] - r[0])
    return 10.0 ** (A - B / (T + C))


def water_dew_point(p_total_bar, y_h2o, use_iapws=None):
    """Dew point [K] solving p_H2O = y_H2O*p = p_sat(T).

    use_iapws=True -> IF97 saturation pressure (maximum accuracy);
    None -> auto (IF97 if installed). False -> NIST Antoine (original model).
    """
    target = y_h2o * p_total_bar
    if target <= 0:
        return None
    if use_iapws is None:
        try:
            from .steam import available
            use_iapws = available()
        except Exception:
            use_iapws = False
    def psat(T):
        if use_iapws:
            from .steam import saturation_pressure_bar
            return saturation_pressure_bar(T)
        return water_psat_bar(T)
    lo, hi = (273.16, 640.0) if use_iapws else (273.0, 573.0)
    for _ in range(200):
        mid = 0.5 * (lo + hi)
        try:
            val = psat(mid)
        except Exception:
            # IF97 saturation is undefined outside 273.16-647.096 K; fall back
            # to NIST Antoine for that trial temperature.
            val = water_psat_bar(mid)
        if val < target:
            lo = mid
        else:
            hi = mid
    return 0.5 * (lo + hi)


def reaction_g0(stoich: dict, T, dataset="shomate"):
    """Standard Gibbs energy of reaction [kJ/mol] for {species: nu}."""
    return sum(nu * g0(sp, T, dataset) for sp, nu in stoich.items())


def equilibrium_constant(stoich: dict, T, dataset="shomate"):
    """Dimensionless K = exp(-dG0/(R T)) with p0 = 1 bar."""
    return math.exp(-reaction_g0(stoich, T, dataset) / (R_KJ * T))
