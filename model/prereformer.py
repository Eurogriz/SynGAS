"""G3 extension: adiabatic equilibrium pre-reformer for C2+ Russian gas.

A commercial pre-reformer converts ethane/propane (and higher hydrocarbons
lumped into C3H8 on a carbon basis, see docs/12) with steam to an equilibrium
mixture of CH4, CO, CO2, H2 and H2O at 600-750 K before the fired reformer.
This removes the coking risk of higher hydrocarbons in the hot tubes.

Model: adiabatic Gibbs minimisation (the same equilibrium solver as the main
reformer) with H_in(T_in) = H_out(T_ad). No vendor kinetics. [PARTIAL]
"""
from __future__ import annotations
from .equilibrium import equilibrate
from .thermo import stream_enthalpy


def c2plus_mol(n):
    return n.get("C2H6", 0.0) + n.get("C3H8", 0.0)


def adiabatic_prereformer(feed, p_bar, T_in, eos_kset=None, approach_K=0.0,
                          use_iapws=False):
    """Adiabatic pre-reformer: H_in(T_in) = H_out(T_ad), bracketed bisection.

    Faster than the generic adiabatic_temperature() because the physical
    bracket is 500-800 K instead of 298-3418 K. Marked [PARTIAL]: equilibrium,
    not a vendor kinetic model.
    """
    H_in = stream_enthalpy(feed, T_in)
    lo, hi = 500.0, 800.0

    def f(T):
        r = equilibrate(feed, T, p_bar, approach_K=approach_K,
                        eos_kset=eos_kset)
        return stream_enthalpy(r["n_mol"], T) - H_in, r

    flo, _ = f(lo)
    fhi, _ = f(hi)
    if flo * fhi > 0:
        return {"converged": False,
                "note": f"no sign change in 500-800 K: f(500)={flo}, f(800)={fhi}"}
    r = None
    for _ in range(38):
        mid = 0.5 * (lo + hi)
        fm, r = f(mid)
        if fm <= 0:
            lo = mid
        else:
            hi = mid
    Tad = 0.5 * (lo + hi)
    _, r = f(Tad)
    n = r["n_mol"]
    in_c2, out_c2 = c2plus_mol(feed), c2plus_mol(n)
    conv = (in_c2 - out_c2) / in_c2 if in_c2 else None
    H_in_primary = stream_enthalpy(feed, T_in, p_bar=p_bar,
                                   eos_kset=eos_kset, use_iapws_steam=use_iapws)
    H_out_primary = stream_enthalpy(n, Tad, p_bar=p_bar,
                                    eos_kset=eos_kset, use_iapws_steam=use_iapws)
    return {
        "converged": True, "T_in_K": T_in, "T_out_K": Tad,
        "T_out_C": Tad - 273.15, "p_bar": p_bar,
        "equilibrium": r, "Q_kJ_per_100mol_NG": 0.0,
        "H_in_kJ_per_100mol_NG": H_in_primary,
        "H_out_kJ_per_100mol_NG": H_out_primary,
        "H_balance_mismatch_pct": abs(H_out_primary - H_in_primary) /
                                  max(abs(H_in_primary), 1.0) * 100,
        "C2plus_in_mol": in_c2, "C2plus_out_mol": out_c2,
        "C2plus_conversion": conv,
        "CH4_equivalent_in": feed.get("CH4", 0.0) + 2 * feed.get("C2H6", 0.0) +
                             3 * feed.get("C3H8", 0.0),
        "carbon_stable": r["carbon_stable"],
        "method": "adiabatic Gibbs equilibrium, bracketed 500-800 K bisection",
        "status": "[PARTIAL] no vendor pre-reformer kinetic model; C4+ lumped into C3H8",
    }
