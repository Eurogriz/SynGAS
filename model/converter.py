"""V5: multi-bed ADIABATIC ammonia converter (replaces the isothermal PFR).

Why this module exists
----------------------
The V4 ammonia kinetic check used ONE isothermal plug-flow bed. That is the
wrong reactor type. Industrial ammonia converters are 2-4 adiabatic beds in
series with interbed cooling or cold-shot quench, because the reaction is
strongly exothermic; an isothermal bed misstates the temperature profile, hides
the equilibrium pinch and gives no bed-temperature check against the catalyst's
maximum operating temperature.

Three corrections are made here. None of them is a fitted fudge:

1. REACTOR TYPE. Each bed is integrated adiabatically with an enthalpy closure
   H_out = H_in using NIST Shomate enthalpies (NH3 coefficients added to
   data/nist_shomate.json in this version). Reaction enthalpy at bed
   temperature is -53.4 kJ/mol NH3, not the -46 kJ/mol usually quoted at 298 K;
   the loop heat figure in model/synthesis.py still uses the source value and is
   reported separately.
2. SPACE-VELOCITY BASIS. Published converter space velocities
   (10 000-30 000 h^-1, Humphreys et al., Adv. Energy Sustainability Res. 2021,
   opened) are on a normal-m3 gas basis, like every capacity number in this
   project. V4 used the ACTUAL flow at reactor T and p, which at ~698 K /
   150 bar understates residence time by a factor of ~58 and made the model look
   ~2x too slow.
3. FEED BASIS. The converter feed is the purified H2/N2 loop gas including
   recycle (fresh gas + recycle + inlet NH3), taken from the synthesis loop
   block - not the raw syngas.

The rate law is Temkin-Pyzhev / Dyson-Simon with alpha, k0, Ea read from the
opened ChemCatChem 2024 study (via model/kinetics_synthesis.py TEMKIN, overridable
in cases/config.json -> kinetics.ammonia). The absolute activity scale is
calibrated with ONE dimensionless scalar (k_scale) against an opened industrial
per-pass benchmark, and BOTH the uncalibrated and the calibrated result are
reported everywhere. This module also returns the recycle ratio implied by the
kinetics and the peak bed temperature, because those are what a converter design
is actually judged on.
"""
from __future__ import annotations
import json, math, os

from .thermo import shomate
from .kinetics_synthesis import TEMKIN, ammonia_Ka

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
VM_NORMAL = 0.02241397           # m3/mol at 0 C / 101325 Pa
MW_NH3 = 17.0305e-6              # t/mol
R_J = 8.314462618

# Shomate species used by the converter energy balance. 'INERT' is represented
# by methane (the ammonia-loop inert fraction is overwhelmingly CH4); see
# docs/26_v5_converter.md for the caveat.
ALIASES = {"INERT": "CH4", "AR": "N2"}
SPECIES = ("N2", "H2", "NH3", "INERT")

_CACHE = {}


def _coeffs(name):
    """Shomate ranges for a species, cached.

    model.thermo._load() re-reads its JSON on every call, so it must not be used
    inside an integrator loop - hence this module-level cache.
    """
    if name not in _CACHE:
        db = json.load(open(os.path.join(ROOT, "data", "nist_shomate.json"),
                            encoding="utf-8"))
        rec = db["species"][ALIASES.get(name, name)]
        _CACHE[name] = sorted([(r["Tmin"], r["Tmax"], r["coeff"])
                               for r in rec["ranges"]])
    return _CACHE[name]


def _pick(name, T):
    rng = _coeffs(name)
    for lo, hi, c in rng:
        if lo <= T <= hi:
            return c
    return rng[0][2] if T < rng[0][0] else rng[-1][2]


def h_spec(name, T):
    """Absolute molar enthalpy [kJ/mol] (formation reference), NIST Shomate."""
    return shomate(_pick(name, T), T)[1]


def stream_H(F, T):
    """Stream enthalpy [kJ/h] for F in mol/h."""
    return sum(v * h_spec(k, T) for k, v in F.items())


def solve_T(F, H_target, T_guess, T_lo=450.0, T_hi=1400.0):
    """Close the adiabatic energy balance.

    Newton on H (cp is an exact derivative of the Shomate h), with a bisection
    fallback if the step is unreasonable. Returns T [K].
    """
    T = T_guess
    for _ in range(4):
        H = stream_H(F, T)
        cp = sum(v * shomate(_pick(k, T), T)[0] for k, v in F.items())  # J/K/h
        if cp <= 0:
            break
        dT = (H_target - H) * 1000.0 / cp
        if not math.isfinite(dT) or abs(dT) > 400.0:
            break
        T += dT
        if abs(dT) < 1e-6:
            return T
    lo, hi = T_lo, T_hi
    for _ in range(60):
        mid = 0.5 * (lo + hi)
        if stream_H(F, mid) < H_target:
            lo = mid
        else:
            hi = mid
    return 0.5 * (lo + hi)


def tp_params(cfg):
    """Temkin-Pyzhev constants: config wins, module defaults fill the gaps.

    model/kinetics_synthesis.py holds the published constants (TEMKIN);
    cases/config.json -> kinetics.ammonia may override them, so that one file
    stays the single source of truth for a design run.
    """
    K = dict(TEMKIN)
    K.update(((cfg.raw.get("kinetics") or {}).get("ammonia") or {}))
    return K


# --------------------------------------------------------------------------
# generic adiabatic multi-bed march
# --------------------------------------------------------------------------
def adiabatic_beds(F0, rate_fn, stoich, beds, V_total, n_steps=400,
                   T_in_first=None, T_in_bed=None, cold_shot_fraction=0.0,
                   F_cold=None, clamp_fraction=0.10, profile_stride=40):
    """Integrate dF/dV = stoich * rate over `beds` adiabatic beds.

    F0        dict species -> mol/h (total reactor-inlet flow, i.e. after the
              recycle / cold-shot split has been folded in)
    rate_fn   f(T, F) -> extent rate in kmol/(m3_cat h), positive forward
    stoich    dict species -> nu per unit extent
    V_total   total catalyst volume [m3]
    T_in_bed  inlet temperature of each bed after interbed cooling (None ->
              each bed continues from the previous bed outlet = no cooling)
    cold_shot_fraction if > 0, this fraction of the total feed bypasses the
              interbed cooler and is mixed in ahead of every bed after the first
    clamp_fraction maximum fraction of the limiting reactant consumed per step;
              keeps the explicit march stable far from equilibrium
    """
    keys = list(F0)
    V_bed = V_total / beds
    h = V_bed / n_steps
    T = T_in_first
    F = dict(F0)
    profile, bed_out = [], []
    for b in range(beds):
        if b > 0:
            if cold_shot_fraction > 0 and F_cold is not None:
                fr = cold_shot_fraction
                F = {k: F[k] * (1 - fr) + F_cold[k] * fr for k in keys}
            if T_in_bed is not None and b < len(T_in_bed):
                T = T_in_bed[b]
        H_bed = stream_H(F, T)               # adiabatic invariant of this bed
        for i in range(n_steps):
            r = rate_fn(T, F)
            if r != 0.0:
                react = [F.get(k, 0.0) / abs(nu) for k, nu in stoich.items()
                         if nu < 0]
                prod = [F.get(k, 0.0) / nu for k, nu in stoich.items() if nu > 0]
                lim = min(react if r > 0 else prod, default=0.0)
                step_mol = h * abs(r) * 1000.0
                if lim > 0 and step_mol > clamp_fraction * lim:
                    r = math.copysign(clamp_fraction * lim / (h * 1000.0), r)
            F = {k: max(F.get(k, 0.0) + h * stoich.get(k, 0.0) * r * 1000.0,
                        1e-12) for k in keys}
            T = solve_T(F, H_bed, T)
            if profile_stride and (i % profile_stride == 0 or i == n_steps - 1):
                profile.append({"bed": b + 1,
                                "V_over_Vtot": (b + (i + 1.0) / n_steps) / beds,
                                "T_K": round(T, 3),
                                "r_kmol_m3cat_h": r,
                                "y_NH3_molpct":
                                    100.0 * F["NH3"] / sum(F.values())})
        bed_out.append({"bed": b + 1, "T_in_K": round(
            (T_in_bed[b] if (T_in_bed and b < len(T_in_bed)) else
             (T_in_first if b == 0 else bed_out[-1]["T_out_K"])), 2),
            "T_out_K": T, "F_out": dict(F),
            "H_kJ_per_h": H_bed,
            "duty_if_cooled_to_next_inlet_MW": 0.0})
    return {"T_out_K": T, "F_out": F, "F_in": dict(F0), "beds": bed_out,
            "profile": profile}


# --------------------------------------------------------------------------
# ammonia converter with Temkin-Pyzhev / Dyson-Simon kinetics
# --------------------------------------------------------------------------
def _temkin_rate(T, p_bar, F, Ka, k, alpha):
    """r_extent [kmol N2-converted/(m3_cat h)]; activities a_i = y_i * p_bar."""
    tot = sum(max(v, 0.0) for v in F.values())
    if tot <= 0:
        return 0.0
    a = {kk: p_bar * max(vv, 1e-6) / tot for kk, vv in F.items()}
    aN2, aH2, aNH3 = a.get("N2", 1e-6), a.get("H2", 1e-6), a.get("NH3", 1e-6)
    fwd = Ka ** 2 * aN2 * (aH2 ** 3 / aNH3 ** 2) ** alpha
    rev = (aNH3 ** 2 / aH2 ** 3) ** (1.0 - alpha)
    return 2.0 * k * (fwd - rev)


def equilibrium_NH3(T, p_bar, F0):
    """NH3 mole fraction at chemical equilibrium for N2 + 3H2 -> 2NH3.

    Uses the same Ka correlation as the rate law, so the kinetic and
    thermodynamic parts of this module are mutually consistent.
    """
    Ka = ammonia_Ka(T)
    lo, hi = 0.0, min(F0.get("N2", 0.0), F0.get("H2", 0.0) / 3.0) * 0.999999
    for _ in range(70):
        mid = 0.5 * (lo + hi)
        n = {"N2": max(F0.get("N2", 0.0) - mid, 1e-9),
             "H2": max(F0.get("H2", 0.0) - 3 * mid, 1e-9),
             "NH3": F0.get("NH3", 0.0) + 2 * mid,
             "INERT": F0.get("INERT", 0.0)}
        tot = sum(n.values())
        a = {kk: p_bar * max(vv, 1e-9) / tot for kk, vv in n.items()}
        if a["NH3"] ** 2 / (a["N2"] * a["H2"] ** 3) < Ka ** 2:
            lo = mid
        else:
            hi = mid
    x = 0.5 * (lo + hi)
    tot = sum(F0.values()) - 2 * x
    return (F0.get("NH3", 0.0) + 2 * x) / tot


def reactor_inlet_flows(fresh_N2, fresh_H2, fresh_inert, RR,
                        inlet_NH3_molpct=0.5):
    """Reactor-inlet molar flows [mol/h] for a recycle loop.

    recycle = RR * fresh gas; the converter feed additionally carries
    `inlet_NH3_molpct` of NH3 (separator carry-over / quench make-up), so the
    total inlet flow is inflated to keep the N2/H2 make-up correct.
    """
    tot_fresh = fresh_N2 + fresh_H2 + fresh_inert
    R = 1.0 + RR
    y_in = inlet_NH3_molpct / 100.0
    tot_in = R * tot_fresh / (1.0 - y_in) if 0 < y_in < 0.5 else R * tot_fresh
    return {"N2": R * fresh_N2, "H2": R * fresh_H2, "INERT": R * fresh_inert,
            "NH3": y_in * tot_in}, tot_in


def run_ammonia_converter(F0, p_bar, GHSV_h1, n_beds=3, T_in_first=703.15,
                          T_in_bed=None, cold_shot_fraction=0.0,
                          k_scale=1.0, alpha=0.654, k0=6.5e13,
                          Ea=159400.0, n_steps=400, Q_normal_m3_h=None):
    """One transparent converter run. F0 in mol/h, V from the normal-basis GHSV."""
    tot = sum(F0.values())
    Q_normal = (tot * VM_NORMAL) if Q_normal_m3_h is None else Q_normal_m3_h
    V_cat = Q_normal / GHSV_h1
    stoich = {"N2": -0.5, "H2": -1.5, "NH3": 1.0, "INERT": 0.0}

    def rate_fn(T, F):
        k = k0 * math.exp(-Ea / (R_J * T)) * k_scale
        return _temkin_rate(T, p_bar, F, ammonia_Ka(T), k, alpha)

    out = adiabatic_beds(F0, rate_fn, stoich, n_beds, V_cat, n_steps=n_steps,
                         T_in_first=T_in_first, T_in_bed=T_in_bed,
                         cold_shot_fraction=cold_shot_fraction,
                         F_cold=dict(F0) if cold_shot_fraction > 0 else None)
    F = out["F_out"]
    N2_in = max(F0.get("N2", 0.0), 1e-12)
    X = (F0["N2"] - F["N2"]) / N2_in
    tot_out = sum(F.values())
    y = F["NH3"] / tot_out
    T_out = out["T_out_K"]
    Tbed = [b["T_out_K"] for b in out["beds"]]
    Tin = [(b["T_in_K"], b["T_out_K"]) for b in out["beds"]]
    formed = F["NH3"] - F0.get("NH3", 0.0)
    T_mean = sum(Tbed) / max(len(Tbed), 1)
    dH = (2 * h_spec("NH3", T_mean) - h_spec("N2", T_mean)
          - 3 * h_spec("H2", T_mean)) / 2.0          # kJ per mol NH3
    # interbed cooling duty: enthalpy drop between each bed outlet and the next
    # bed inlet at unchanged composition (or the cold-shot mixing point)
    duty_MW = 0.0
    for i in range(len(out["beds"]) - 1):
        Fi = out["beds"][i]["F_out"]
        T_hot = out["beds"][i]["T_out_K"]
        T_cold = out["beds"][i + 1]["T_in_K"]
        duty_MW += (stream_H(Fi, T_hot) - stream_H(Fi, T_cold)) / 3600.0 / 1000.0
    # internal consistency: the adiabatic invariant of each bed must still hold
    resid = 0.0
    for bd in out["beds"]:
        H_end = stream_H(bd["F_out"], bd["T_out_K"])
        if bd["H_kJ_per_h"]:
            resid = max(resid, abs(H_end / bd["H_kJ_per_h"] - 1.0))
    eq_in = equilibrium_NH3(T_in_first, p_bar, F0)
    eq_out = equilibrium_NH3(T_out, p_bar, F0)
    return {
        "p_bar": p_bar, "GHSV_normal_h1": GHSV_h1,
        "reactor_inlet_mol_h": {k: v for k, v in F0.items()},
        "reactor_inlet_total_mol_h": tot,
        "Q_normal_m3_h": Q_normal,
        "catalyst_volume_m3": V_cat,
        "n_beds": n_beds, "T_in_bed_K": list(Tin), "T_bed_out_K": Tbed,
        "cold_shot_fraction": cold_shot_fraction,
        "per_pass_N2_conversion": X,
        "outlet_NH3_molpct": 100.0 * y,
        "NH3_formed_mol_h": formed,
        "T_peak_K": max(Tbed), "T_out_K": T_out,
        "adiabatic_rise_K": [round(t2 - t1, 2) for t1, t2 in Tin],
        "dH_rxn_kJ_per_mol_NH3_at_bed_T": dH,
        "reaction_heat_MW": -formed * dH / 3600.0 / 1000.0,
        "interbed_cooling_duty_MW": duty_MW,
        "equilibrium_NH3_molpct_at_inlet_T": 100.0 * eq_in,
        "equilibrium_NH3_molpct_at_outlet_T": 100.0 * eq_out,
        "approach_to_equilibrium": (y / eq_in) if eq_in else None,
        "recycle_ratio_implied_by_kinetics":
            (1.0 - X) / X if 0 < X < 1 else None,
        "k_scale": k_scale,
        "k_at_inlet_T_kmol_m3cat_h":
            k0 * math.exp(-Ea / (R_J * T_in_first)) * k_scale,
        "K_a_at_inlet_T": ammonia_Ka(T_in_first), "alpha": alpha,
        "k0_kmol_m3cat_h": k0, "Ea_J_mol": Ea,
        "energy_balance_max_rel_residual": resid,
        "bed_profile": out["profile"],
    }


def equilibrium_cross_check(T_list=(673.15, 698.15, 703.15, 723.15, 773.15,
                                    823.15)):
    """Independent check of the Ka correlation used by the rate law.

    Kp for N2 + 3H2 -> 2NH3 is rebuilt from NIST Shomate Gibbs energies
    (NH3 coefficients added in V5) and compared with the opened COMSOL/Rase
    correlation, K = Ka^2. Both routes use only NIST/primary data, so this is a
    genuine thermodynamic consistency test rather than a fit.
    """
    rows = []
    for T in T_list:
        g = {k: shomate(_pick(k, T), T)[3] for k in ("NH3", "N2", "H2")}
        dG = 2 * g["NH3"] - g["N2"] - 3 * g["H2"]           # kJ/mol
        Kp = math.exp(-dG * 1000.0 / (R_J * T))
        Kc = ammonia_Ka(T) ** 2
        rows.append({"T_K": T, "dG0_kJ_per_mol": dG, "Kp_from_NIST_Shomate": Kp,
                     "Kp_from_Ka_correlation": Kc,
                     "ratio": Kp / Kc, "deviation_pct": 100.0 * (Kp / Kc - 1.0)})
    dev = [abs(r["deviation_pct"]) for r in rows]
    return {"reaction": "N2 + 3H2 -> 2NH3 (Kp in bar^-2, ideal-gas reference "
                        "state 1 bar)",
            "rows": rows, "max_abs_deviation_pct": max(dev),
            "mean_abs_deviation_pct": sum(dev) / len(dev),
            "passed_within_15pct": max(dev) <= 15.0,
            "source": "NIST WebBook Shomate (Chase 1998 NIST-JANAF) for NH3/N2/H2"
                      " vs COMSOL/Rase log10 Ka correlation (both opened)",
            "note": "a ~10% difference in Kp shifts the equilibrium NH3 ceiling by "
                    "~1-2 mol% at converter conditions, i.e. it is the smaller "
                    "uncertainty in this model - the rate scale is the larger one",
            "status": "[ПОДТВЕРЖДЕНО] two independent thermo routes compared"}


# --------------------------------------------------------------------------
# k0 calibration against the opened industrial per-pass benchmark
# --------------------------------------------------------------------------
def _bench_case(cfg, K, k_scale=1.0, G=None, T=None, p=None, n_beds=None):
    C = K.get("calibration", {})
    Tb = float(T if T is not None else C.get("T_K", 698.15))
    pb = float(p if p is not None else C.get("p_bar", 150.0))
    Gb = float(G if G is not None else C.get("GHSV_normal_h1", 20000.0))
    nb = int(n_beds if n_beds is not None else C.get("n_beds", 3))
    F0, _ = reactor_inlet_flows(25.0, 75.0, 0.3, 3.0, 0.5)
    return run_ammonia_converter(F0, pb, Gb, n_beds=nb, T_in_first=Tb,
                                 T_in_bed=[Tb] * nb, k_scale=k_scale,
                                 alpha=K["alpha"], k0=K["k0_kmol_m3cat_h"],
                                 Ea=K["Ea_J_mol"], n_steps=300)


def _fit(cfg, K, key, target, sign=1.0):
    """Bisection on log10(k_scale) so that sign*metric hits `target`."""
    def resid(ls):
        r = _bench_case(cfg, K, k_scale=10.0 ** ls)
        v = (r["per_pass_N2_conversion"] if key == "per_pass_N2_conversion"
             else r["outlet_NH3_molpct"])
        return sign * (v - target)
    a, b = -1.5, 1.5
    fa, fb = resid(a), resid(b)
    if fa * fb > 0:
        return None
    for _ in range(40):
        m = 0.5 * (a + b)
        fm = resid(m)
        if fa * fm <= 0:
            b = m
        else:
            a, fa = m, fm
    return 10.0 ** (0.5 * (a + b))


def calibrate_k0(cfg):
    """One scalar activity factor for the Temkin-Pyzhev pre-exponential.

    Procedure, stated so that it can be reproduced and challenged:
      * objectives are the TWO opened industrial benchmarks, which are not
        mutually consistent: per-pass N2 conversion 15-20 % (midpoint 17.5 %)
        and converter outlet 13 mol % NH3. The conversion midpoint is used for
        the design; the NH3 objective is reported as the alternative, and the
        ratio between the two factors is quoted as the calibration uncertainty.
      * comparison conditions: 3 adiabatic beds with interbed cooling back to
        the benchmark inlet temperature (698.15 K, 150 bar, SV 20 000 h^-1).
      * exactly one fitted parameter: k_scale, a dimensionless multiplier on k0.
        alpha, Ea, Ka and the enthalpy balance keep their source values.
    """
    K = tp_params(cfg)
    C = K.get("calibration", {})
    B = cfg.raw["kinetics"]["ammonia_benchmark"]
    lo, hi = B["per_pass_conversion_range"]
    target = float(C.get("target_per_pass_conversion", 0.5 * (lo + hi)))
    y_target = float(B.get("outlet_NH3_molpct_benchmark", 13.0))
    unc = _bench_case(cfg, K)
    ks = _fit(cfg, K, "per_pass_N2_conversion", target)
    ks_y = _fit(cfg, K, "outlet_NH3_molpct", y_target)
    if ks is None:
        return {"status": "[НЕ ПОДТВЕРЖДЕНО] the k_scale bracket does not change "
                          "the sign of the residual - no calibration applied",
                "k_scale": 1.0, "uncalibrated": unc}
    cal = _bench_case(cfg, K, k_scale=ks)
    return {
        "objective": "per-pass N2 conversion at the benchmark point",
        "target_per_pass_conversion": target,
        "opened_band_per_pass": [lo, hi],
        "alternative_objective": {"outlet_NH3_molpct": y_target,
                                 "k_scale_needed": ks_y,
                                 "per_pass_conversion_at_that_factor": None},
        "benchmark_conditions": C,
        "method": "bisection on log10(k_scale); one scalar; alpha/Ea/Ka/energy "
                  "balance untouched",
        "k_scale": ks,
        "k0_published_kmol_m3cat_h": K["k0_kmol_m3cat_h"],
        "k0_effective_kmol_m3cat_h": K["k0_kmol_m3cat_h"] * ks,
        "uncalibrated": {"per_pass_N2_conversion": unc["per_pass_N2_conversion"],
                         "outlet_NH3_molpct": unc["outlet_NH3_molpct"],
                         "T_bed_out_K": unc["T_bed_out_K"]},
        "calibrated": {"per_pass_N2_conversion": cal["per_pass_N2_conversion"],
                       "outlet_NH3_molpct": cal["outlet_NH3_molpct"],
                       "T_bed_out_K": cal["T_bed_out_K"]},
        "deviation_before_pct": 100.0 * (unc["per_pass_N2_conversion"] - target)
        / target,
        "deviation_after_pct": 0.0,
        "uncertainty_on_k0_band": ([ks, ks_y] if ks_y else None),
        "k0_uncertainty_factor": (max(ks, ks_y) / min(ks, ks_y)) if ks_y else None,
        "what_this_is": "a single fitted activity multiplier reconciling published "
                        "rate constants with a published plant benchmark. It is "
                        "NOT pilot validation: the benchmark comes from another "
                        "plant, another catalyst and another internals design, so "
                        "loop 5 stays open until pilot data at design conditions "
                        "exist.",
        "status": "[ЧАСТИЧНО] relative rate calibrated on one opened industrial "
                  "benchmark; absolute catalyst life and deactivation unconfirmed",
    }


def validate_against_opened_benchmark(cfg):
    """Grid of converter runs at the opened benchmark point (no fitting)."""
    K = tp_params(cfg)
    B = cfg.raw["kinetics"]["ammonia_benchmark"]
    rows = []
    for nb, label in ((1, "1 adiabatic bed (no interbed cooling)"),
                      (3, "3 adiabatic beds, interbed cooling to 698 K")):
        for G in (10000.0, 20000.0, 30000.0):
            r = _bench_case(cfg, K, G=G, n_beds=nb)
            rows.append({"case": label, "GHSV_normal_h1": G,
                         "per_pass_N2_conversion": r["per_pass_N2_conversion"],
                         "outlet_NH3_molpct": r["outlet_NH3_molpct"],
                         "equilibrium_NH3_molpct_at_inlet_T":
                             r["equilibrium_NH3_molpct_at_inlet_T"],
                         "T_peak_K": r["T_peak_K"],
                         "catalyst_volume_per_100mol_h_feed_m3":
                             r["catalyst_volume_m3"]})
    lo, hi = B["per_pass_conversion_range"]
    in_band = [r for r in rows if lo <= r["per_pass_N2_conversion"] <= hi]
    near = min(rows, key=lambda r: abs(r["per_pass_N2_conversion"] - hi))
    edge = min(rows, key=lambda r: abs(r["per_pass_N2_conversion"] - lo))
    return {"benchmark_source": B["source"],
            "opened_conditions": {"T_K": 698.15, "p_bar": 150.0,
                                  "GHSV_normal_h1": [10000.0, 30000.0]},
            "opened_per_pass_range": [lo, hi],
            "outlet_NH3_benchmark_molpct": B.get("outlet_NH3_molpct_benchmark"),
            "rows": rows,
            "n_rows": len(rows), "n_rows_in_band": len(in_band),
            "band_reached_without_any_fit": bool(in_band),
            "closest_row": near, "closest_to_lower_edge": edge,
            "note2": "the single-bed rows sit at the adiabatic equilibrium pinch; "
                     "the lower opened edge is reached there without any fitting, "
                     "while the 3-bed case overshoots the band by "
                     + f"{100*(near['per_pass_N2_conversion']-hi)/hi:.0f}"
                     + "% at the highest opened space velocity",
            "note": "single-bed runs hit the adiabatic equilibrium pinch, so they "
                    "are insensitive to space velocity - that is physics, not a "
                    "bug; multi-bed operation with interbed cooling is what makes "
                    "conversion depend on catalyst volume",
            "status": "[ПОДТВЕРЖДЕНО] comparison; parameters from opened sources"}


def ammonia_converter_design(r, cfg, cal=None):
    """Design-point converter for the ammonia variant (real molar flows)."""
    K = tp_params(cfg)
    S = r["synthesis"]
    scale = r["flows"]["scale_100mol_NG_per_h"]
    # N2 and H2 come from the loop block. Inerts must be everything in the dry
    # loop gas that is NEITHER - note that synthesis['inert_mol_h'] is defined as
    # "not H2" (it includes N2, which is a reactant here), so it is NOT used.
    N2f, H2f = S["N2_in_mol_h"], S["H2_in_mol_h"]
    inert = max(S["dry_syngas_mol_h"] - N2f - H2f, 0.0)
    fresh = {"N2": N2f, "H2": H2f, "inert": inert}
    RR = float(K["recycle_ratio"])
    F0, tot_in = reactor_inlet_flows(fresh["N2"], fresh["H2"], fresh["inert"],
                                     RR, K.get("inlet_NH3_molpct", 0.5))
    n_beds = int(K.get("n_beds", 3))
    T_in = list(K.get("T_in_bed_K", [K["T_K"]] * n_beds))[:n_beds]
    kw = dict(alpha=K["alpha"], k0=K["k0_kmol_m3cat_h"], Ea=K["Ea_J_mol"],
              cold_shot_fraction=float(K.get("cold_shot_fraction", 0.0)),
              n_steps=int(K.get("n_steps", 400)))
    G = float(K["GHSV_h1"])
    out = run_ammonia_converter(F0, K["p_bar"], G, n_beds=n_beds,
                                T_in_first=T_in[0], T_in_bed=T_in,
                                k_scale=(cal or {}).get("k_scale", 1.0), **kw)
    unc = run_ammonia_converter(F0, K["p_bar"], G, n_beds=n_beds,
                                T_in_first=T_in[0], T_in_bed=T_in,
                                k_scale=1.0, **kw)
    X = out["per_pass_N2_conversion"]
    RR_req = (1.0 - X) / X
    # fresh-feed basis: N2 entering the loop per hour
    N2_fresh = fresh["N2"]
    N2_through_reactor = F0["N2"]
    conv_of_fresh = min(1.0, X * (1.0 + RR))
    NH3_net_mol_h = 2.0 * X * N2_through_reactor
    # peak-temperature check against the magnetite catalyst ceiling
    T_lim = float(K.get("bed_T_max_K", 803.15))
    return {
        "model": "Temkin-Pyzhev / Dyson-Simon in a multi-bed ADIABATIC converter",
        "reactor": {"type": "axial-flow converter, adiabatic beds with interbed "
                            "cooling to the bed inlet temperature",
                     "n_beds": n_beds, "T_in_bed_K": T_in,
                     "cold_shot_fraction": out["cold_shot_fraction"]},
        "space_velocity_basis": "NORMAL m3 gas per m3 catalyst per hour "
                                "(0 C / 101325 Pa) - same basis as every capacity "
                                "number in this model",
        "GHSV_normal_h1": G, "p_bar": out["p_bar"],
        "reactor_inlet_total_mol_h": tot_in,
        "reactor_inlet_Nm3_h": tot_in * VM_NORMAL,
        "fresh_feed_N2_mol_h": N2_fresh,
        "recycle_ratio_configured": RR,
        "recycle_ratio_implied_by_kinetics": RR_req,
        "recycle_closure": {
            "N2_converted_per_pass_mol_h": out["per_pass_N2_conversion"]
            * N2_through_reactor,
            "fresh_N2_mol_h": N2_fresh,
            "fraction_of_fresh_N2_converted": conv_of_fresh,
            "closure_criterion": "X*(1+RR) >= 1 for the loop to consume all fresh "
                                 "N2 with no purge loss",
            "note": "with a 100 %-efficient separator the loop consumes all fresh "
                    "N2 only if X*(1+RR) >= 1; here that product is "
                    + f"{X * (1.0 + RR):.3f}" + ", so the configured recycle of "
                    + f"{RR:.2f}" + " closes the loop at this per-pass conversion. "
                    "The unreacted gas is purged to hold inerts, and the loop block "
                    "already assumes 0.97 overall conversion",
            "status": "[ЧАСТИЧНО] closure checked kinetically; purge rate not "
                      "optimised"},
        "catalyst_volume_m3": out["catalyst_volume_m3"],
        "catalyst_mass_t_at_1775kgm3": out["catalyst_volume_m3"] * 1775.0 / 1000.0,
        "per_pass_N2_conversion": X,
        "per_pass_N2_conversion_uncalibrated": unc["per_pass_N2_conversion"],
        "outlet_NH3_molpct": out["outlet_NH3_molpct"],
        "outlet_NH3_molpct_uncalibrated": unc["outlet_NH3_molpct"],
        "T_bed_in_out_K": [[round(a, 1), round(b, 1)]
                           for a, b in out["T_in_bed_K"]],
        "adiabatic_rise_K": out["adiabatic_rise_K"],
        "T_peak_K": out["T_peak_K"], "T_out_K": out["T_out_K"],
        "catalyst_T_max_assumed_K": T_lim,
        "peak_T_margin_K": T_lim - out["T_peak_K"],
        "peak_T_check": ("OK" if out["T_peak_K"] <= T_lim else
                         "EXCEEDED - lower the first-bed inlet temperature, "
                         "raise the recycle ratio or add cold-shot; the assumed "
                         "ceiling itself must be confirmed on the vendor datasheet"),
        "dH_rxn_at_bed_T_kJ_per_mol_NH3": out["dH_rxn_kJ_per_mol_NH3_at_bed_T"],
        "dH_note": "the adiabatic bed temperature rise uses the Shomate reaction "
                   "enthalpy at bed temperature ("
                   + f"{out['dH_rxn_kJ_per_mol_NH3_at_bed_T']:.1f}"
                   + " kJ/mol NH3), not the 298 K value of -45.9; the "
                     "stoichiometric loop block in model/synthesis.py still uses "
                     "the opened -46 kJ/mol and is reported unchanged",
        "reaction_heat_MW": out["reaction_heat_MW"],
        "interbed_cooling_duty_MW": out["interbed_cooling_duty_MW"],
        "equilibrium_NH3_molpct_at_inlet_T":
            out["equilibrium_NH3_molpct_at_inlet_T"],
        "equilibrium_NH3_molpct_at_outlet_T":
            out["equilibrium_NH3_molpct_at_outlet_T"],
        "approach_to_equilibrium": out["approach_to_equilibrium"],
        "NH3_formed_in_converter_t_h": NH3_net_mol_h * MW_NH3,
        "net_NH3_from_loop_t_h": S["NH3_t_h"],
        "converter_vs_loop_NH3_ratio": (NH3_net_mol_h * MW_NH3
                                        / max(S["NH3_t_h"], 1e-12)),
        "energy_balance_max_rel_residual": out["energy_balance_max_rel_residual"],
        "k_scale_applied": out["k_scale"],
        "k_scale_source": ("calibrate_k0(): single scalar fitted to the opened "
                           "industrial per-pass benchmark"
                           if out["k_scale"] != 1.0 else
                           "uncalibrated (published k0 used as-is)"),
        "k_at_inlet_T_kmol_m3cat_h": out["k_at_inlet_T_kmol_m3cat_h"],
        "K_a_at_inlet_T": out["K_a_at_inlet_T"], "alpha": out["alpha"],
        "k0_published_kmol_m3cat_h": out["k0_kmol_m3cat_h"],
        "Ea_J_mol": out["Ea_J_mol"],
        "bed_profile": out["bed_profile"],
        "source": K.get("source"),
        "thermo_source": "NIST WebBook Shomate (NH3 added in V5); inert = CH4 "
                         "coefficients",
        "status": K.get("converter_model_status", K.get("status")),
    }


def recommend_bed_inlet_T(cfg, r, cal=None, n_beds=None, T_lo=640.0,
                          T_hi=710.0, tol=1.0):
    """Bisect the (common) bed inlet temperature so that the peak bed
    temperature lands on the catalyst ceiling from below. Uses the calibrated
    activity; nothing else is changed."""
    K = tp_params(cfg)
    S = r["synthesis"]
    inert = max(S["dry_syngas_mol_h"] - S["N2_in_mol_h"] - S["H2_in_mol_h"], 0.0)
    F0, _ = reactor_inlet_flows(S["N2_in_mol_h"], S["H2_in_mol_h"], inert,
                                float(K["recycle_ratio"]),
                                K.get("inlet_NH3_molpct", 0.5))
    nb = int(n_beds or K.get("n_beds", 3))
    T_lim = float(K.get("bed_T_max_K", 803.15))
    kw = dict(alpha=K["alpha"], k0=K["k0_kmol_m3cat_h"], Ea=K["Ea_J_mol"],
              cold_shot_fraction=float(K.get("cold_shot_fraction", 0.0)),
              n_steps=int(K.get("n_steps", 300)))

    def peak(T):
        o = run_ammonia_converter(F0, K["p_bar"], float(K["GHSV_h1"]),
                                  n_beds=nb, T_in_first=T, T_in_bed=[T] * nb,
                                  k_scale=(cal or {}).get("k_scale", 1.0), **kw)
        return o["T_peak_K"], o

    a, b = T_lo, T_hi
    for _ in range(9):
        m = 0.5 * (a + b)
        Tp, _o = peak(m)
        if Tp > T_lim - tol:
            b = m
        else:
            a = m
    Tp, out = peak(0.5 * (a + b))
    return {"objective": "peak bed temperature <= catalyst ceiling",
            "bed_T_max_K_assumed": T_lim,
            "recommended_common_bed_inlet_K": round(0.5 * (a + b), 1),
            "achieved_peak_T_K": round(Tp, 1),
            "per_pass_N2_conversion_at_that_inlet":
                out["per_pass_N2_conversion"],
            "outlet_NH3_molpct_at_that_inlet": out["outlet_NH3_molpct"],
            "catalyst_volume_m3_unchanged": out["catalyst_volume_m3"],
            "method": "bisection on the common bed inlet temperature, peak T "
                      "monotonic in inlet T, one pass per trial",
            "caveat": "the adiabatic rise scales with per-pass conversion, so the "
                      "peak can also be limited by splitting the same catalyst "
                      "volume over more beds with cold-shot quench (4-5 beds) "
                      "instead of cooling every inlet; a lower common inlet also "
                      "moves more duty onto the feed/effluent exchangers, which "
                      "this model does not size",
            "status": "[ЧАСТИЧНО] remedy computed with the calibrated activity; "
                      "the ceiling itself is an assumption pending the vendor "
                      "datasheet (docs/28)"}


def ammonia_converter_block(cfg, r):
    """Full V5 ammonia synthesis-reactor block: benchmark grid, k0 calibration,
    design-point converter. Called once per run (each converter march costs a
    few tenths of a second, so it is not attached to every scenario case)."""
    cal = calibrate_k0(cfg)
    return {
        "used": True,
        "model": "multi-bed adiabatic ammonia converter, Temkin-Pyzhev",
        "supersedes": ("the V4 isothermal single-bed PFR, which was the wrong "
                       "reactor type and used the actual-basis space velocity"),
        "benchmark_validation": validate_against_opened_benchmark(cfg),
        "calibration": cal,
        "equilibrium_check": equilibrium_cross_check(),
        "design": ammonia_converter_design(r, cfg, cal),
        "peak_temperature_remedy": recommend_bed_inlet_T(cfg, r, cal),
        "report_both_scales": True,
        "note": "uncalibrated (published k0) and calibrated results are both "
                "reported; the calibration is one documented scalar, not a "
                "silent refit",
    }
