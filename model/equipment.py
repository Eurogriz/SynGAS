"""G6: conceptual sizing. Every correlation and every non-sourced number is flagged."""
from __future__ import annotations
import math
from .thermo import h0, h_liquid_water

# [ASSUMPTION] design parameters (not vendor data). See docs/06.
A = {
    "heat_flux_kW_m2": 80.0,
    "tube_ID_m": 0.10,
    "tube_heated_length_m": 12.0,
    "tube_wall_thickness_m": 0.012,
    "GHSV_Nm3_per_m3cat_h": 5000.0,
    "bed_voidage": 0.40,
    "pellet_d_m": 0.010,
    "gas_viscosity_Pa_s": 3.0e-5,
    "U_WHB_W_m2K": 60.0,
    "ZnO_capacity_kgS_per_kg": 0.25,
    "ZnO_bulk_density_kg_m3": 1000.0,
    "ZnO_L_over_D": 3.0,
    "polytropic_efficiency": 0.75,
    "ASU_kWh_per_t_O2": 245.0,   # IEAGHG/Linde 2009 presentation, 99.5% O2
}


def ergun_dp_bar(L, D, eps, dp, mu, rho, v):
    """Ergun equation, pressure drop [Pa]."""
    term1 = 150.0 * (1 - eps) ** 2 / eps ** 3 * mu * v / dp ** 2
    term2 = 1.75 * (1 - eps) / eps ** 3 * rho * v ** 2 / dp
    return (term1 + term2) * L


def size_smr(Q_kW, flow_Nm3_h, molar_mass_kg_kmol=18.0, T=1123.15, p_bar=25.0):
    q = A["heat_flux_kW_m2"]
    area_tube = math.pi * A["tube_ID_m"] * A["tube_heated_length_m"]
    n_tubes = Q_kW / (q * area_tube)
    V_cat = flow_Nm3_h / A["GHSV_Nm3_per_m3cat_h"]
    V_tubes = n_tubes * math.pi * (A["tube_ID_m"] / 2) ** 2 * A["tube_heated_length_m"]
    # gas density at tube conditions (ideal gas, ASSUMPTION)
    rho = p_bar * 1e5 * (molar_mass_kg_kmol / 1000.0) / (8.314462618 * T)
    v_sup = (flow_Nm3_h * (T / 273.15) * (1.01325 / p_bar) / 3600.0) / (
        n_tubes * math.pi * (A["tube_ID_m"] / 2) ** 2)
    dp = ergun_dp_bar(A["tube_heated_length_m"], A["tube_ID_m"], A["bed_voidage"],
                      A["pellet_d_m"], A["gas_viscosity_Pa_s"], rho, v_sup)
    # Alternative: larger pellets + higher voidage + 1.5x tubes to reduce dP
    dp_alt = ergun_dp_bar(A["tube_heated_length_m"], A["tube_ID_m"], 0.50,
                          0.016, A["gas_viscosity_Pa_s"], rho, v_sup / 1.5) / 1e5
    return {"Q_kW": Q_kW, "assumed_heat_flux_kW_m2": q,
            "dP_criterion_bar": 3.0,
            "dP_criterion_met_by_base_case": (dp / 1e5) <= 3.0,
            "alternative_low_dP": {"n_tubes_factor": 1.5, "pellet_d_m": 0.016,
                                   "voidage": 0.50, "ergun_dP_bar": dp_alt,
                                   "status": "[ASSUMPTION] parametric alternative, not a vendor pellet"},
            "tube_ID_m": A["tube_ID_m"], "tube_heated_length_m": A["tube_heated_length_m"],
            "tube_wall_thickness_m": A["tube_wall_thickness_m"],
            "area_per_tube_m2": area_tube, "number_of_tubes": n_tubes,
            "catalyst_volume_m3_at_GHSV": V_cat,
            "geometric_tube_volume_m3": V_tubes,
            "superficial_velocity_m_s": v_sup, "gas_density_kg_m3": rho,
            "ergun_dP_bar": dp / 1e5,
            "alternatives": [
                {"type": "A: conventional top-fired radiant box", "pro": "mature, high TRL, easy catalyst replacement",
                 "con": "large footprint, NOx, 50% furnace efficiency", "n_tubes": n_tubes},
                {"type": "B: side-fired / terrace-wall", "pro": "flatter heat-flux profile, lower peak TWT",
                 "con": "more burners, more piping, higher maintenance",
                 "n_tubes": Q_kW / (0.85 * q * area_tube)},
                {"type": "C: gas-heated / heat-exchange reformer", "pro": "no fired NOx, compact",
                 "con": "needs a hot secondary reformer stream; lower TRL for this duty",
                 "n_tubes": None, "status": "[NOT CONFIRMED] no vendor data opened"},
            ],
            "status": "[ASSUMPTION] heat flux, tube size, GHSV, pellet size, voidage; final selection requires vendor + API 530/560 creep check"}


def size_whb(Q_kW, T_hot_in, T_hot_out, T_cold_in=373.15, T_cold_out=673.15):
    dT1 = T_hot_in - T_cold_out
    dT2 = T_hot_out - T_cold_in
    lmtd = (dT1 - dT2) / math.log(dT1 / dT2) if dT1 > 0 and dT2 > 0 and abs(dT1 - dT2) > 1e-6 else dT1
    area = abs(Q_kW) * 1000.0 / (A["U_WHB_W_m2K"] * lmtd)
    return {"Q_kW": Q_kW, "LMTD_K": lmtd, "U_W_m2K": A["U_WHB_W_m2K"], "area_m2": area,
            "dT_hot_in_minus_cold_out_K": dT1, "dT_hot_out_minus_cold_in_K": dT2,
            "temperature_cross": (dT1 <= 0 or dT2 <= 0),
            "alternatives": [
                {"type": "A: fire-tube waste-heat boiler + steam drum", "pro": "mature for syngas, handles high T",
                 "con": "metal dusting / tube-sheet thermal stress"},
                {"type": "B: water-tube WHB", "pro": "better for very high pressure steam",
                 "con": "more complex, higher cost, fouling"},
            ],
            "status": "[ASSUMPTION] U and temperatures; TEMA/ASME VIII check not performed (standards not opened)"}


def size_zno(sulfur_ppmv, feed_kmol_h, life_years=2.0):
    s_kmol_h = feed_kmol_h * sulfur_ppmv * 1e-6
    s_kg_h = s_kmol_h * 32.065
    total_kg = s_kg_h * life_years * 8760 / A["ZnO_capacity_kgS_per_kg"]
    volume = total_kg / A["ZnO_bulk_density_kg_m3"]
    D = (4 * volume / (math.pi * A["ZnO_L_over_D"])) ** (1 / 3)
    return {"S_in_kg_h": s_kg_h, "ZnO_mass_kg": total_kg, "bed_volume_m3": volume,
            "bed_diameter_m": D, "bed_length_m": A["ZnO_L_over_D"] * D,
            "design_life_years": life_years,
            "capacity_kgS_per_kg_ZnO": A["ZnO_capacity_kgS_per_kg"],
            "alternatives": [
                {"type": "A: single ZnO vessel (lead-lag)", "pro": "simple", "con": "sulfur breakthrough risk"},
                {"type": "B: two vessels in lead-lag + ultra-purification", "pro": "<10 ppbv slip (JM webinar, opened)",
                 "con": "extra vessel and adsorbent cost"},
            ],
            "status": "[ASSUMPTION] capacity/bulk density/life; vendor ZnO spec not opened"}


def compressor_power(kmol_h, T_in, p_in, p_out, k=1.30, MW=20.0):
    """Polytropic compression power [kW]; ideal-gas, ASSUMPTION."""
    n_kmol_s = kmol_h / 3600.0
    R = 8.314462618          # kJ/(kmol K)
    eta = A["polytropic_efficiency"]
    expo = (k - 1) / (k * eta)
    W = n_kmol_s * (k / (k - 1)) * R * T_in * ((p_out / p_in) ** ((k - 1) / k) - 1) / eta
    return {"power_kW": W, "p_in_bar": p_in, "p_out_bar": p_out,
            "T_out_K": T_in * (p_out / p_in) ** expo,
            "alternatives": [
                {"type": "A: centrifugal (API 617)", "pro": "high flow, reliable", "con": "surge control needed"},
                {"type": "B: reciprocating (API 618)", "pro": "flexible at low flow / high ratio", "con": "pulsation, maintenance"},
            ],
            "status": "[ASSUMPTION] k, eta; catalogue curves not opened"}


def asu_power(o2_kmol_h):
    t_h = o2_kmol_h * 31.9988 / 1000.0
    return {"O2_t_h": t_h, "specific_power_kWh_per_t": A["ASU_kWh_per_t_O2"],
            "power_MW": t_h * A["ASU_kWh_per_t_O2"] / 1000.0,
            "source": "IEAGHG/Linde, Enhanced Cryogenic Air Separation (2009), opened PDF: 0.35 kWh/Nm3 O2, 245 kWh/t for >99.5% O2",
            "status": "[PARTIAL] presentation value, delivery pressure effects not included"}


def equipment_report(case, fs):
    u = {x["unit"]: x["Q_kW"] for x in fs["units"]}
    u_smr = next(v for k, v in u.items() if k.startswith("R-201"))
    u_whb = next(v for k, v in u.items() if k.startswith("E-201"))
    u_cond = next(v for k, v in u.items() if k.startswith("E-202"))
    dry_kmol_h = fs["dry_syngas_Nm3_h"] / 22.41397
    feed_kmol_h = dry_kmol_h * 0.6     # [ASSUMPTION] rough feed/syngas molar ratio
    flow_Nm3_h = dry_kmol_h * 22.41397 / (fs["SMR"]["y_wet"]["H2"] + 0.3)
    return {
        "smr": size_smr(u_smr, flow_Nm3_h),
        "whb": size_whb(u_whb, case["process"]["SMR_T_out_K"], case["process"]["WHB_T_out_K"]),
        "condenser": {"Q_kW": u_cond, "alternatives": [
            {"type": "A: shell-and-tube trim cooler + separator (TEMA)", "pro": "mature, high pressure"},
            {"type": "B: air cooler (API 661) + trim cooler", "pro": "less cooling water", "con": "large plot area, climate sensitivity"}],
            "status": "[ASSUMPTION] no thermal rating performed"},
        "zno": size_zno(case["feed"]["H2S_ppmv"], feed_kmol_h),
        "compressor": compressor_power(feed_kmol_h, 298.15, 20.0, 30.0),
        "asu": asu_power(0.0),
        "assumptions": A,
        "standards_status": "API 530/560/617/618/661/941, TEMA, ASME VIII, ASTM A608 were NOT opened (paywalled). Their applicability and formulas are therefore [NOT CONFIRMED]; no code compliance is claimed.",
    }
