"""Water/steam properties: IAPWS-IF97 (primary, optional package) + NIST fallback.

For 'maximum accuracy' the IF97 formulation (iapws 1.5.5) is used when available.
If iapws is not installed, the model falls back to the NIST Shomate liquid/gas
coefficients and NIST Antoine psat - with the flag use_iapws=False so results
can be traced. IF97 is the international standard for water/steam (IAPWS 1997);
https://iapws.org/relguide/IF97-Rev.html (not opened in this session -> status
[PARTIAL] on the formulation documentation; the installed package version is
pinned in results/summary.json).
"""
from __future__ import annotations
import math
from .thermo import h0, h_liquid_water, water_psat_bar

try:
    from iapws import IAPWS97
    _HAS_IAPWS = True
except Exception:
    _HAS_IAPWS = False


def available():
    return _HAS_IAPWS


def saturation_temperature_K(p_bar):
    """Tsat [K] at p [bar(a)]."""
    if _HAS_IAPWS:
        return IAPWS97(P=p_bar / 10.0, x=1).T      # MPa
    # fallback: invert NIST Antoine by bisection
    lo, hi = 273.0, 573.0
    for _ in range(90):
        mid = 0.5 * (lo + hi)
        if water_psat_bar(mid) < p_bar:
            lo = mid
        else:
            hi = mid
    return 0.5 * (lo + hi)


def saturation_pressure_bar(T):
    """psat [bar(a)] at T [K]."""
    if _HAS_IAPWS:
        return IAPWS97(T=T, x=1).P * 10.0          # MPa -> bar
    return water_psat_bar(T)


def steam_enthalpy_kJ_per_mol(T, p_bar):
    """Superheated/saturated steam enthalpy [kJ/mol], absolute IF97 reference."""
    if _HAS_IAPWS:
        return IAPWS97(P=p_bar / 10.0, T=T).h * 0.0180153   # kJ/kg -> kJ/mol
    return h0("H2O", T)


def liquid_enthalpy_kJ_per_mol(T, p_bar=1.0):
    if _HAS_IAPWS:
        return IAPWS97(P=p_bar / 10.0, T=T).h * 0.0180153
    return h_liquid_water(T)


def vaporisation_enthalpy_kJ_per_mol(p_bar):
    if _HAS_IAPWS:
        hg = IAPWS97(P=p_bar / 10.0, x=1).h
        hf = IAPWS97(P=p_bar / 10.0, x=0).h
        return (hg - hf) * 0.0180153
    T = saturation_temperature_K(p_bar)
    return h0("H2O", T) - h_liquid_water(T)


def steam_generation_dh_kJ_per_mol(p_bar, T_steam, T_bfw):
    """Heat to turn BFW at T_bfw into steam at T_steam, p_bar."""
    return steam_enthalpy_kJ_per_mol(T_steam, p_bar) - liquid_enthalpy_kJ_per_mol(T_bfw, p_bar)
