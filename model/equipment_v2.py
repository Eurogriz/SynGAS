"""G5 extension: 1-D tube wall temperature, Ergun dP and LMP creep life.

Extends (does not replace) the v1 equipment.py. Every correlation is labelled
with its source and status. NOT a mechanical code certification.
"""
from __future__ import annotations
import math
from .equipment import ergun_dp_bar, size_whb
from .thermo import R_J, stream_enthalpy, water_dew_point
from .equilibrium import equilibrate


def tube_thermal_profile(cfg, feed, T_in, T_out, p_bar, Q_kW, eos_kset=None, n_seg=12):
    """1-D discretisation along the heated tube length.

    The gas temperature rises linearly (a common first design approximation
    when the heat flux is constant); at each segment the equilibrium
    composition is recomputed at the local T (with the configured approach),
    which gives the local enthalpy and hence the true heat-flux fraction.
    Wall temperature = T_gas + q_flux/h_i + q_flux*t/k_tube.
    """
    E = cfg.equipment
    h_i = E["h_inner_W_m2K"]; k_t = E["k_tube_W_mK"]
    t_wall = E["tube_wall_m"]; L = E["tube_heated_length_m"]
    D_i = E["tube_ID_m"]; D_o = E["tube_OD_m"]
    q_flux_W_m2 = E["heat_flux_kW_m2"] * 1000.0
    H_in = stream_enthalpy(feed, T_in, p_bar=p_bar, eos_kset=eos_kset,
                           use_iapws_steam=cfg.use_iapws)
    H_out = stream_enthalpy(equilibrate(feed, T_out, p_bar,
                                        approach_K=cfg.knobs["approach_K"],
                                        eos_kset=eos_kset)["n_mol"], T_out,
                            p_bar=p_bar, eos_kset=eos_kset,
                            use_iapws_steam=cfg.use_iapws)
    dH_tot = H_out - H_in
    prof = []
    dT_wall = q_flux_W_m2 * (1.0 / h_i + t_wall / k_t)
    for i in range(1, n_seg + 1):
        frac = i / n_seg
        Tg = T_in + (T_out - T_in) * frac
        r = equilibrate(feed, Tg, p_bar, approach_K=cfg.knobs["approach_K"],
                        eos_kset=eos_kset)
        Hg = stream_enthalpy(r["n_mol"], Tg, p_bar=p_bar, eos_kset=eos_kset,
                             use_iapws_steam=cfg.use_iapws)
        fH = (Hg - H_in) / dH_tot if dH_tot else frac
        prof.append({
            "segment": i, "length_m": round(L * frac, 3), "T_gas_K": Tg,
            "T_wall_K": Tg + dT_wall, "enthalpy_fraction_cumulative": fH,
            "X_CH4_local": r["CH4_conversion"], "Z": r["eos"].get("Z"),
        })
    return {
        "method": "1-D constant heat flux, local chemical equilibrium, film+wall conduction",
        "n_segments": n_seg, "profile": prof,
        "T_wall_max_K": max(x["T_wall_K"] for x in prof),
        "T_wall_max_C": max(x["T_wall_K"] for x in prof) - 273.15,
        "q_flux_kW_m2": E["heat_flux_kW_m2"],
        "dT_film_plus_wall_K": dT_wall,
        "note": "User assumption q=80 kW/m2; electrified-SMR study (opened) reports wall ~1000 C; "
                "this is a THERMAL estimate, not a validated tube-metal temperature.",
        "status": "[PARTIAL] film coefficient, wall conductivity and heat flux are assumptions",
    }


def lmp_allowable_stress_MPa(T_wall_K, cfg, life_h=None):
    E = cfg.equipment
    life_h = life_h or E["design_life_h"]
    lmp = T_wall_K * (E["LMP_C"] + math.log10(life_h)) / 1000.0
    log10S = math.log10(E["stress_ref_MPa"]) + E["LMP_slope_log10stress_per_LMP"] * (lmp - E["LMP_ref"])
    return {"LMP": lmp, "allowable_stress_MPa": 10 ** log10S,
            "design_life_h": life_h,
            "status": "[ASSUMPTION] master-curve slope is fitted to one opened HP-Nb point (11 MPa at LMP=35.2)"}


def required_wall_thickness_m(p_bar, D_o, S_MPa, corrosion_m):
    """API 530 style thin-cylinder equation t = P*Do/(2*S*E + P) (E=1)."""
    P = p_bar * 0.1  # bar -> MPa
    return P * D_o / (2.0 * S_MPa + P) + corrosion_m


def size_reformer(cfg, Q_kW, feed_mol_h, T_avg, p_bar, eos_kset=None,
                  feed_for_dp=None):
    E = cfg.equipment
    q = E["heat_flux_kW_m2"]
    atr = Q_kW <= 0.0
    area = 0.0 if atr else Q_kW / q
    tubes = 0.0 if atr else area / (math.pi * E["tube_OD_m"] * E["tube_heated_length_m"])
    Vm = cfg.Vm
    # Actual volumetric flow at reactor T,p (ideal, corrected by Z from PR)
    Z = 1.0
    if eos_kset:
        from .eos import gas_density_kg_m3
        Z = 1.0  # conservative ideal-gas volume for velocity
    Q_act_m3_s = feed_mol_h * R_J * T_avg / (p_bar * 1e5) / 3600.0
    area_free = math.pi * E["tube_ID_m"] ** 2 / 4.0
    n_tubes_real = 0 if atr else max(1.0, math.ceil(tubes))
    tubes_for_heat = n_tubes_real
    if atr:
        # refractory-lined ATR vessel: size from volumetric flow at 1.5 m/s
        v = 1.5
        D_vessel = math.sqrt(4.0 * Q_act_m3_s / (math.pi * v))
        A_vessel = math.pi * D_vessel ** 2 / 4.0
        n_tubes_real = 1
        area_free = A_vessel
    else:
        v = Q_act_m3_s / (n_tubes_real * area_free * E["bed_voidage"])
    # mean molecular weight of the (mostly steam) feed
    MM = {k: v for k, v in {"H2O": 18.015, "CH4": 16.043, "CO": 28.010,
                            "CO2": 44.010, "H2": 2.016, "N2": 28.014,
                            "C2H6": 30.070, "C3H8": 44.097, "O2": 31.998}.items()}
    f = feed_for_dp or {"H2O": 1.0}
    ftot = sum(f.values())
    mw = sum(MM.get(k, 28.0) * val for k, val in f.items()) / ftot / 1000.0
    rho = mw * p_bar * 1e5 / (R_J * T_avg)
    L_bed = 3.0 * D_vessel if atr else E["tube_heated_length_m"]

    def dp_at(n_tubes, vel):
        raw = ergun_dp_bar(L_bed, E["pellet_d_m"], E["bed_voidage"],
                           E["pellet_d_m"], E["gas_viscosity_Pa_s"], rho, vel)
        return raw / 1e5       # ergun_dp_bar returns Pa despite its name

    dp = dp_at(n_tubes_real, v)
    # Size by BOTH heat flux and allowable pressure drop (Ergun). Increasing
    # the installed tube count lowers velocity and hence dP ~ 1/n^2.
    tubes_for_dp = n_tubes_real
    if not atr and dp > E["dP_max_bar"]:
        for _ in range(30):
            factor = math.sqrt(dp / E["dP_max_bar"]) * 1.03
            n_tubes_real = max(n_tubes_real + 1, math.ceil(n_tubes_real * factor))
            v = Q_act_m3_s / (n_tubes_real * area_free * E["bed_voidage"])
            dp = dp_at(n_tubes_real, v)
            if dp <= E["dP_max_bar"]:
                break
        tubes_for_dp = n_tubes_real
    prof = None
    if not atr and feed_for_dp:
        prof = tube_thermal_profile(cfg, feed_for_dp, cfg.process["T_feed_preheat_K"] + 100.0,
                                    T_avg, p_bar, Q_kW, eos_kset=eos_kset)
    Tw = prof["T_wall_max_K"] if prof else (T_avg if atr else T_avg + 100.0)
    lmp = lmp_allowable_stress_MPa(Tw, cfg)
    t_req = required_wall_thickness_m(p_bar, E["tube_OD_m"],
                                      lmp["allowable_stress_MPa"],
                                      E["corrosion_allowance_m"])
    return {
        "reactor_type": "adiabatic ATR/POX vessel (refractory lined)" if atr else "fired tubular reformer",
        "heat_flux_kW_m2": q if not atr else None,
        "vessel_diameter_m": D_vessel if atr else None,
        "vessel_length_m": L_bed if atr else None,
        "required_area_m2": area, "tubes_calculated": tubes,
        "tubes_for_heat": tubes_for_heat, "tubes_for_dp": tubes_for_dp,
        "tubes_installed": n_tubes_real,
        "superficial_velocity_m_s": v, "gas_density_kg_m3": rho,
        "Ergun_dP_bar": dp, "dP_within_limit": dp <= E["dP_max_bar"],
        "dP_limit_bar": E["dP_max_bar"],
        "tube_thermal_profile": prof,
        "T_wall_max_K": Tw,
        "creep": {**lmp, "required_wall_thickness_m": None if atr else t_req,
                  "specified_wall_thickness_m": None if atr else E["tube_wall_m"],
                  "applicable": not atr,
                  "wall_adequate": None if atr else t_req <= E["tube_wall_m"],
                  "note": "LMP from opened Eur. J. Materials 2021 (C=22.4, 11 MPa at LMP 35.2), "
                          "t equation from opened API 530 1996 excerpt"},
        "status": "[PARTIAL] screening sizing, NOT an API 530 / ASME code calculation",
    }
