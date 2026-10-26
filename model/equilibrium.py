"""L0: ideal-gas Gibbs-energy minimisation with an explicit graphite phase.

Pure standard-library Python. No HYSYS, no Cantera, no SciPy in the solver.
Verification scripts (model/validation.py) re-solve the same problems with
independent thermochemistry and with Cantera/SciPy.

Species: CH4, C2H6, H2O, CO, CO2, H2, O2, N2 (ideal gas) + C(s, graphite).
Elements: C, H, O, N. 5 independent reaction coordinates (9 species - 4 elements).

The gas is treated as ideal (fugacity = partial pressure). This is an
EXPLICIT ASSUMPTION at 20-40 bar; its impact is quantified in docs/03.
"""
from __future__ import annotations

import math
from .thermo import (SPECIES, GASES, ELEMENTS, COMPOSITION, R_KJ, P0_BAR,
                     g0, h0, stream_enthalpy, properties)

IDX = {s: i for i, s in enumerate(SPECIES)}
NS = len(SPECIES)
NG = NS - 1                      # all but C_GR are gases

# Stoichiometric basis of the null space of the element matrix (products > 0).
REACTIONS = {
    "R1_SMR":       {"CH4": -1, "H2O": -1, "CO": +1, "H2": +3},
    "R2_WGS":       {"CO": -1, "H2O": -1, "CO2": +1, "H2": +1},
    "R3_H2OX":      {"H2": -2, "O2": -1, "H2O": +2},
    "R4_C2H6HYD":   {"C2H6": -1, "H2": -1, "CH4": +2},
    "R6_C3H8HYD":   {"C3H8": -1, "H2": -2, "CH4": +3},
    "R5_CH4CRACK":  {"CH4": -1, "H2": +2, "C_GR": +1},
}
REACTION_ORDER = list(REACTIONS)
NU = [[REACTIONS[r].get(s, 0) for s in SPECIES] for r in REACTION_ORDER]


def vec_from_dict(d):
    return [float(d.get(s, 0.0)) for s in SPECIES]


def dict_from_vec(v):
    return {s: float(v[i]) for i, s in enumerate(SPECIES)}


def element_vector(n):
    b = {e: 0.0 for e in ELEMENTS}
    for i, s in enumerate(SPECIES):
        for e, k in COMPOSITION[s].items():
            b[e] += k * n[i]
    return b


def _solve_linear(A, b):
    """Gaussian elimination with partial pivoting for a small dense system."""
    n = len(b)
    M = [list(map(float, A[i])) + [float(b[i])] for i in range(n)]
    for c in range(n):
        piv = max(range(c, n), key=lambda r: abs(M[r][c]))
        if abs(M[piv][c]) < 1e-300:
            return None
        M[c], M[piv] = M[piv], M[c]
        for r in range(c + 1, n):
            f = M[r][c] / M[c][c]
            if f:
                for k in range(c, n + 1):
                    M[r][k] -= f * M[c][k]
    x = [0.0] * n
    for r in range(n - 1, -1, -1):
        x[r] = (M[r][n] - sum(M[r][k] * x[k] for k in range(r + 1, n))) / M[r][r]
    return x


def _G(n, T, p_bar, dataset, g0s):
    gas_tot = sum(n[:NG])
    val = n[NG] * g0s[NG]
    for i in range(NG):
        if n[i] > 0:
            val += n[i] * (g0s[i] + R_KJ * T * math.log(n[i] / gas_tot * p_bar / P0_BAR))
    return val


def _minimise(n0, dir_idx, T, p_bar, dataset, max_iter=300, tol=1e-11,
              g0_correction=None):
    g0s = [g0(s, T, dataset) for s in SPECIES]
    if g0_correction:
        for i, sp in enumerate(SPECIES):
            g0s[i] += g0_correction.get(sp, 0.0)
    nd = len(dir_idx)
    N = [[NU[j][i] for j in dir_idx] for i in range(NS)]
    n = list(map(float, n0))
    history = []
    for it in range(max_iter):
        gas_tot = sum(n[:NG])
        mu = [0.0] * NS
        for i in range(NG):
            if n[i] <= 0:
                mu[i] = g0s[i] + R_KJ * T * math.log(1e-300)
            else:
                mu[i] = g0s[i] + R_KJ * T * math.log(n[i] / gas_tot * p_bar / P0_BAR)
        mu[NG] = g0s[NG]
        grad = [sum(N[i][j] * mu[i] for i in range(NS)) for j in range(nd)]
        gmax = max(abs(x) for x in grad)
        vtot = [sum(N[i][j] for i in range(NG)) for j in range(nd)]
        H = [[0.0] * nd for _ in range(nd)]
        for j in range(nd):
            for k in range(nd):
                s = sum(N[i][j] * N[i][k] / n[i] for i in range(NG) if n[i] > 0)
                H[j][k] = R_KJ * T * (s - vtot[j] * vtot[k] / gas_tot)
                if j == k:
                    H[j][k] += 1e-10
        d = _solve_linear(H, [-x for x in grad])
        if d is None:
            break
        dn = [sum(N[i][j] * d[j] for j in range(nd)) for i in range(NS)]
        slope = sum(grad[j] * d[j] for j in range(nd))
        alpha = 1.0
        for i in range(NG):
            if dn[i] < 0:
                alpha = min(alpha, 0.995 * n[i] / (-dn[i]))
        if dn[NG] < 0:
            alpha = min(alpha, 0.995 * n[NG] / (-dn[NG]) if n[NG] > 0 else 0.0)
        alpha = max(alpha, 1e-16)
        G0 = _G(n, T, p_bar, dataset, g0s)
        ok = False
        for _ in range(60):
            trial = [max(n[i] + alpha * dn[i], 1e-300) for i in range(NS)]
            # restore element balance that could be lost by the max() clipping
            if _G(trial, T, p_bar, dataset, g0s) <= G0 + 1e-4 * alpha * slope:
                n = trial
                ok = True
                break
            alpha *= 0.5
        history.append({"iter": it, "grad_max_kJ_per_mol": gmax, "alpha": alpha})
        if not ok or gmax < tol or max(abs(alpha * x) for x in dn) < 1e-14:
            break
    return n, history, g0s


def _seed(feed, eps):
    """Feasible strictly-positive gas composition with EXACTLY the feed's elements."""
    n = list(map(float, feed))
    # Add a tiny amount of every absent gas species using reaction directions
    # that only consume species currently present in comfortable excess.
    for i in range(NG):
        if n[i] >= eps:
            continue
        best = None
        for j in (0, 1, 2, 3, 4):         # gas reactions only; never seed solid carbon
            for sign in (1.0, -1.0):      # both reaction directions are allowed
                nu = [sign * x for x in NU[j]]
                if nu[i] <= 0:
                    continue
                step = (eps - n[i]) / nu[i]
                if all(n[k] + step * nu[k] > eps * 0.1 for k in range(NG) if nu[k] < 0):
                    best = (nu, step)
                    break
            if best is not None:
                break
        if best is not None:
            nu, step = best
            for k in range(NG):
                n[k] += step * nu[k]
    return n


def carbon_affinity(n, T, p_bar, dataset="shomate"):
    """Delta_mu_C = mu(CH4) - 2 mu(H2) - g(graphite) [kJ/mol].

    > 0 means the gas is supersaturated w.r.t. graphite: forming carbon
    lowers G. At full gas-phase equilibrium all three classic carbon-forming
    reactions give the same value (they are linearly dependent).
    """
    gas_tot = sum(n[:NG])
    def mu(i):
        return g0(SPECIES[i], T, dataset) + R_KJ * T * math.log(max(n[i], 1e-300) / gas_tot * p_bar / P0_BAR)
    return mu(IDX["CH4"]) - 2 * mu(IDX["H2"]) - g0("C_GR", T, dataset)


def reaction_quotient(n, stoich, p_bar):
    """Q = prod (y_i p/p0)^nu over GAS species only (solids have a=1)."""
    gas_tot = sum(n[:NG])
    q = 0.0
    for s, nu in stoich.items():
        if s == "C_GR":
            continue
        q += nu * math.log(max(n[IDX[s]], 1e-300) / gas_tot * p_bar / P0_BAR)
    return math.exp(q)


def equilibrate(feed, T, p_bar, dataset="shomate", allow_carbon=True,
                approach_K=0.0, max_iter=300, eos_kset=None, eos_iter=6):
    """Minimise G at fixed T,p and fixed element inventory.

    feed          : {species: mol} (same basis as all results)
    T             : K
    p_bar         : ABSOLUTE pressure, bar
    dataset       : 'shomate' (primary) or 'nasa' (independent cross-check)
    allow_carbon  : if True, include graphite as a separate phase
    approach_K    : [ASSUMPTION] equilibrium is evaluated at T - approach_K;
                    this is the 'temperature approach to equilibrium' proxy.
    returns dict with composition, affinities, K/Q checks, balances.
    """
    Teff = T - approach_K
    f = vec_from_dict(feed)
    b = element_vector(f)
    total = sum(f) or 1.0
    eps = max(1e-12, 1e-9 * total)
    seed = _seed(f, eps)
    # Optional Peng-Robinson real-gas outer loop. ln(phi) is added to g0
    # (mu = g0 + RT ln(y p/p0) + RT ln(phi)); composition dependence of phi is
    # converged by fixed-point iteration. Hessian stays the ideal-gas one,
    # which is an accurate approximation because phi is a weak function of y.
    corr = {}
    eos_info = {"used": bool(eos_kset), "kset": eos_kset, "iterations": 0,
                "Z": None, "lnphi_last": {}, "Kphi_R1": None, "Kphi_R2": None}
    n_prev = None
    for it in range(eos_iter if eos_kset else 1):
        n_gas, hist1, _ = _minimise(seed, [0, 1, 2, 3, 4], Teff, p_bar,
                                    dataset, max_iter, g0_correction=corr)
        aff = carbon_affinity(n_gas, Teff, p_bar, dataset)
        # (carbon affinity uses ideal mu; PR correction to it is <0.02 kJ/mol
        #  at 25 bar and is included in eos_info.Kphi diagnostics)
        carbon_stable = bool(allow_carbon and aff > 1e-8)
        n = n_gas
        hist = list(hist1)
        if carbon_stable:
            c_seed = eps
            n2 = list(n_gas)
            for i in range(NS):
                n2[i] += c_seed * NU[5][i]
            n, hist2, _ = _minimise(n2, [0, 1, 2, 3, 4, 5], Teff, p_bar,
                                    dataset, max_iter, g0_correction=corr)
            hist = hist + hist2
        if not eos_kset:
            break
        from .eos import peng_robinson
        gt = sum(n[:NG])
        y = {SPECIES[i]: n[i] / gt for i in range(NG)}
        Z, lnphi, _ = peng_robinson(y, Teff, p_bar, eos_kset)
        eos_info.update({"iterations": it + 1, "Z": Z, "lnphi_last": lnphi})
        new_corr = {sp: R_KJ * Teff * lnphi.get(sp, 0.0) for sp in SPECIES[:NG]}
        delta = float("inf") if n_prev is None else max(
            abs(n[i] - n_prev[i]) / max(n[i], 1e-12) for i in range(NG))
        n_prev = list(n)
        corr = new_corr
        if delta < 1e-9:
            break
    if eos_kset:
        from .eos import peng_robinson
        gt = sum(n[:NG]); y = {SPECIES[i]: n[i] / gt for i in range(NG)}
        Z, lnphi, _ = peng_robinson(y, Teff, p_bar, eos_kset)
        for name, st in (("R1", REACTIONS["R1_SMR"]), ("R2", REACTIONS["R2_WGS"])):
            eos_info["Kphi_" + name] = math.exp(sum(
                nu * lnphi.get(sp, 0.0) for sp, nu in st.items() if sp != "C_GR"))
        eos_info["Z"] = Z; eos_info["lnphi_last"] = lnphi
    gas_tot = sum(n[:NG])
    y_wet = {SPECIES[i]: n[i] / gas_tot for i in range(NG)}
    dry_tot = gas_tot - n[IDX["H2O"]]
    y_dry = {SPECIES[i]: n[i] / dry_tot for i in range(NG) if SPECIES[i] != "H2O"} if dry_tot > 0 else {}
    ch4_in = f[IDX["CH4"]] + 2 * f[IDX["C2H6"]] + 3 * f[IDX["C3H8"]]
    ch4_out = n[IDX["CH4"]] + 2 * n[IDX["C2H6"]] + 3 * n[IDX["C3H8"]]
    h2 = y_dry.get("H2", 0.0)
    co = y_dry.get("CO", 0.0)
    co2 = y_dry.get("CO2", 0.0)
    from .thermo import equilibrium_constant
    K1 = equilibrium_constant(REACTIONS["R1_SMR"], Teff, dataset)
    K2 = equilibrium_constant(REACTIONS["R2_WGS"], Teff, dataset)
    Q1 = reaction_quotient(n, REACTIONS["R1_SMR"], p_bar)
    Q2 = reaction_quotient(n, REACTIONS["R2_WGS"], p_bar)
    if eos_kset and eos_info.get("Kphi_R1"):
        eos_info["Q1_over_K1_real"] = (Q1 / K1) * eos_info["Kphi_R1"]
        eos_info["Q2_over_K2_real"] = (Q2 / K2) * eos_info["Kphi_R2"]
    b_out = element_vector(n)
    return {
        "T_K": T, "T_equilibrium_K": Teff, "p_bar": p_bar, "dataset": dataset,
        "approach_K": approach_K,
        "n_mol": dict_from_vec(n),
        "y_wet": y_wet, "y_dry": y_dry,
        "gas_total_mol": gas_tot, "carbon_solid_mol": n[NG],
        "carbon_stable": carbon_stable,
        "carbon_affinity_kJ_per_mol": aff,
        "CH4_conversion": (ch4_in - ch4_out) / ch4_in if ch4_in else None,
        "H2_CO_dry": h2 / co if co else None,
        "stoichiometric_number_SN": (h2 - co2) / (co + co2) if (co + co2) else None,
        "K1": K1, "Q1": Q1, "Q1_over_K1": Q1 / K1,
        "K2": K2, "Q2": Q2, "Q2_over_K2": Q2 / K2,
        "elements_in": b, "elements_out": b_out,
        "max_element_imbalance_pct": max(
            (abs(b_out[e] - b[e]) / b[e] * 100 if b[e] else 0.0) for e in ELEMENTS),
        "residual_gradient_kJ_per_mol": hist[-1]["grad_max_kJ_per_mol"] if hist else None,
        "iterations": len(hist), "eos": eos_info,
    }


def adiabatic_temperature(feed, p_bar, dataset="shomate", T_guess=1200.0,
                          T_in=298.15, allow_carbon=True, approach_K=0.0,
                          eos_kset=None):
    """Solve H_in(T_in) = H_out(T_ad) for an adiabatic equilibrium reactor.

    Bisection on T; each evaluation is a full Gibbs minimisation.
    """
    H_in = stream_enthalpy(feed, T_in, dataset)
    def f(T):
        r = equilibrate(feed, T, p_bar, dataset=dataset, allow_carbon=allow_carbon,
                        approach_K=approach_K, eos_kset=eos_kset)
        return stream_enthalpy(r["n_mol"], T, dataset) - H_in
    # Scan for a sign change: endothermic (SMR-like) and exothermic (POX/ATR)
    # reactors bracket the root from opposite sides, so do not assume a sign.
    grid = [298.15 + i * 80.0 for i in range(0, 40)]   # 298 .. 3418 K
    vals = [f(t) for t in grid]
    bracket = None
    for i in range(len(grid) - 1):
        if vals[i] == 0.0 or vals[i] * vals[i + 1] < 0:
            bracket = (grid[i], grid[i + 1], vals[i])
            break
    if bracket is None:
        return {"converged": False, "H_in_kJ": H_in,
                "f_low": min(vals), "f_high": max(vals),
                "note": "no sign change in H_out(T)-H_in on 298-3458 K"}
    lo, hi, flo = bracket
    for _ in range(48):
        mid = 0.5 * (lo + hi)
        fm = f(mid)
        if fm * flo <= 0:
            hi = mid
        else:
            lo, flo = mid, fm
    Tad = 0.5 * (lo + hi)
    res = equilibrate(feed, Tad, p_bar, dataset=dataset, allow_carbon=allow_carbon,
                      approach_K=approach_K, eos_kset=eos_kset)
    return {"converged": True, "T_ad_K": Tad, "T_ad_C": Tad - 273.15,
            "H_in_kJ": H_in,
            "H_out_kJ": stream_enthalpy(res["n_mol"], Tad, dataset),
            "equilibrium": res}
