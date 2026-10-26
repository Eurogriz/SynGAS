"""G8 safety screening: Ni(CO)4 during shutdown, HAZOP nodes, relief sizing.

Status: [PARTIAL] / [ДОПУЩЕНИЕ]. This is an engineering screening, NOT a
certified HAZOP, API 520/521 or IEC 61511 study. The full text of API 520/521
was NOT opened in this session.
"""
from __future__ import annotations
import math
from .thermo import R_J

# Ni(s) + 4 CO(g) <=> Ni(CO)4(g)
# dH = -142.3 kJ/mol, dS = -419.2 J/mol/K  ->  log10 K = 7430/T - 21.90
# OSTI 7349456 (opened).  K = p_Ni(CO)4 / p_CO^4, pressures in bar (1 bar std).
def ni_carbonyl_K(T_K):
    return 10.0 ** (7430.0 / T_K - 21.90)


def ni_carbonyl_ppb(T_K, p_CO_bar):
    """Equilibrium Ni(CO)4 partial pressure [ppb] at T and CO partial pressure."""
    K = ni_carbonyl_K(T_K)
    p_eq = K * p_CO_bar ** 4
    # Physical cap: 4 mol CO per mol Ni(CO)4. Values near this cap mean
    # "essentially complete carbonylation" - an equilibrium upper bound,
    # not a rate (kinetics are deliberately not modelled here).
    p = min(p_eq, p_CO_bar / 4.0)
    return {"T_K": T_K, "p_CO_bar": p_CO_bar, "log10K": math.log10(K), "K": K,
            "p_NiCO4_bar": p, "p_NiCO4_bar_uncapped": p_eq,
            "limited_by_stoichiometry": p_eq > p_CO_bar / 4.0,
            "NiCO4_ppb": p * 1e9,
            "status": "[PARTIAL] equilibrium only; kinetics/Ni surface activity "
                      "can dominate below 200 C (OSTI 7349456, opened)"}


def relief_orifice_mm2(W_kg_s, p1_bar, T_K, M_kg_mol=0.020, k=1.30, Z=1.0):
    """Choked ideal-gas mass flux -> required orifice area [mm2].

    G = p1*sqrt(k*M/(R*T)*(2/(k+1))^((k+1)/(k-1)))
    A = W/G.  [ДОПУЩЕНИЕ] API 520/521 full text NOT opened.
    """
    p1 = p1_bar * 1e5
    crit = (2.0 / (k + 1.0)) ** ((k + 1.0) / (k - 1.0))
    G = p1 * math.sqrt(k * M_kg_mol / (R_J * T_K) * crit / Z)
    A = W_kg_s / G if G else 0.0
    return {"relief_load_kg_s": W_kg_s, "p_set_bar": p1_bar,
            "T_K": T_K, "M_kg_mol": M_kg_mol, "k": k, "Z": Z,
            "choked_mass_flux_kg_m2_s": G, "orifice_area_mm2": A * 1e6,
            "orifice_diameter_mm": 2 * math.sqrt(A / math.pi) * 1000,
            "status": "[ДОПУЩЕНИЕ] screening choked-flow estimate, not a certified PSV size"}


HAZOP_NODES = [
    {"node": "Feed desulfurization / ZnO guard",
     "deviation": "High H2S", "cause": "guard bed exhausted / breakthrough",
     "consequence": "Ni/MgAl2O4 poisoning, reformer hot bands, carbon",
     "safeguard": "lead-lag ZnO + online H2S analyser; <0.02 ppmv after guard [ЧАСТИЧНО]"},
    {"node": "R-100 pre-reformer",
     "deviation": "Low S/C / low T", "cause": "steam flow failure",
     "consequence": "C2+ cracking, graphite, bed plugging",
     "safeguard": "S/C low-low trip, high Δp trip, carbon boundary check in model"},
    {"node": "R-101 fired reformer tubes",
     "deviation": "High tube-wall T", "cause": "firing maldistribution / low flow",
     "consequence": "creep rupture (LMP), Ni sintering",
     "safeguard": "T_wall monitoring, 100000 h LMP design, Δp<=3 bar, "
                  "skin thermocouples [ЧАСТИЧНО]"},
    {"node": "WHB / syngas cooler",
     "deviation": "Low level / high T", "cause": "BFW pump failure",
     "consequence": "tube rupture, steam/water into gas",
     "safeguard": "low-low level trip, PSV, IF97 dew-point margin"},
    {"node": "CO2 trim / MDEA",
     "deviation": "High CO2 slip", "cause": "lean-amine flow loss",
     "consequence": "methanol SN out of 2.05, oxo/FT ratio drift",
     "safeguard": "online SN analyser, reboiler steam ratio control"},
    {"node": "PSA / H2 product",
     "deviation": "CO/CO2 breakthrough", "cause": "adsorbent saturation",
     "consequence": "ISO 14687:2025 grade D violation",
     "safeguard": "product GC, automatic product diversion"},
    {"node": "R-401 methanator (ammonia)",
     "deviation": "High T runaway", "cause": "CO2 breakthrough from absorber",
     "consequence": "catalyst damage, >10 ppm poisons to NH3 loop",
     "safeguard": "high-high T trip, feed analyser, <10 ppm spec"},
    {"node": "Synthesis loop (all products)",
     "deviation": "Inert accumulation", "cause": "purge closed",
     "consequence": "low partial pressures, runaway exotherm",
     "safeguard": "purge ratio control, recycle compressor trip"},
    {"node": "SHUTDOWN / standby",
     "deviation": "Low T + CO present", "cause": "cooling before CO purge",
     "consequence": "Ni(CO)4 formation (extremely toxic)",
     "safeguard": "keep T>200 C until CO<10 ppm; N2 purge; "
                  "Ni(CO)4 monitoring [ПОДТВЕРЖДЕНО] per Becht guidance"},
]


def safety_report(r, cfg):
    S = cfg.raw.get("safety", {})
    nc = S.get("Ni_CO_4", {})
    y = r["downstream"]["y_dry"]
    p = r["reformer"]["p_bar"]
    p_CO = y.get("CO", 0.0) * p
    T_op = r["reformer"]["T_out_K"]
    normal = ni_carbonyl_ppb(T_op, p_CO)
    co_purge_bar = nc.get("CO_purge_ppm", 10.0) * 1e-6 * p
    scenarios = []
    Tset = sorted({float(T) for T in
                   nc.get("T_range_K", [300, 500]) +
                   [323.15, 348.15, 373.15, 398.15, 423.15, 473.15]})
    for T in Tset:
        scenarios.append({
            "T_K": T, "T_C": T - 273.15,
            "unpurged_CO_bar": p_CO,
            "NiCO4_ppb_unpurged": ni_carbonyl_ppb(T, p_CO)["NiCO4_ppb"],
            "purged_CO_bar": co_purge_bar,
            "NiCO4_ppb_after_purge": ni_carbonyl_ppb(T, co_purge_bar)["NiCO4_ppb"],
        })
    # blocked-outlet relief on the reformer feed line
    feed_mol_h = r["flows"]["total_feed_Nm3_h"] / r["Vm_m3_per_mol"]
    mw = 0.021  # kg/mol, steam-rich feed [ASSUMPTION]
    W = feed_mol_h * mw / 3600.0
    rel = relief_orifice_mm2(W, S.get("relief", {}).get("p_set_factor", 1.10) * p,
                             T_op, M_kg_mol=mw)
    return {
        "status": "screening only; NOT a certified HAZOP / API 520 study",
        "Ni_CO_4": {
            "correlation": nc.get("log10K"), "source": nc.get("source"),
            "normal_operation": normal,
            "CO_purge_ppm": nc.get("CO_purge_ppm", 10.0),
            "safe_temperature_C": nc.get("safe_T_C", 200.0),
            "shutdown_scenarios": scenarios,
            "conclusion": ("Normal operation at %.0f K gives negligible Ni(CO)4; "
                           "during shutdown below %.0f C with unpurged CO the equilibrium "
                           "predicts significant Ni(CO)4. Purging CO below %.0f ppm before "
                           "cooling below %.0f C keeps Ni(CO)4 below 1 ppb."
                           % (T_op, nc.get("safe_T_C", 200.0),
                              nc.get("CO_purge_ppm", 10.0),
                              nc.get("safe_T_C", 200.0))),
        },
        "relief": rel,
        "sulfur_guard": {"H2S_in_ppmv": S.get("sulfur", {}).get("H2S_in_ppmv"),
                         "H2S_after_guard_ppmv": S.get("sulfur", {}).get("H2S_after_guard_ppmv"),
                         "ZnO_mass_kg": r["catalyst"]["ZnO_guard_mass_kg"]},
        "HAZOP_nodes": HAZOP_NODES,
        "unchecked": ["certified HAZOP / LOPA", "API 520/521 PSV full text",
                      "Ni(CO)4 kinetic rate on 15 wt% Ni/MgAl2O4",
                      "toxic gas dispersion and detector layout",
                      "ATEX/IECEx zoning", "SIS SIL verification"],
    }
