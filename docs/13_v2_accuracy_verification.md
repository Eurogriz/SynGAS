# 13. V2 maximum-accuracy verification (five loops, G8)

HYSYS status: **NOT RUN**. User answer 11 = "otherwise confirm" -> the
Python/DWSIM-equivalent plus `docs/HYSYS_case_spec.md` is CONFIRMED as the
accepted equivalent. No claim of a HYSYS run is made.

## 13.1 Loop summary

| loop | passed | key number |
|---|---|---|
| 1_sources | YES | 33 claims |
| 2_arithmetic | YES | max rel error 1.79e-16 |
| 3_conservation | YES | max error 1.96e-12% |
| 4_thermo | YES | Q*Kphi/K dev 8.46e-12% |
| 5_validation_falsification | NO | FAILED (honestly reported) |

Overall: **FAIL (loop 5 open by design)**.

## 13.2 Loop 1 - sources and claims

33 registered claims: {'[ПОДТВЕРЖДЕНО]': 8, '[ЧАСТИЧНО]': 17, '[ДОПУЩЕНИЕ]': 6, '[НЕ ПОДТВЕРЖДЕНО]': 2}.
Problems: []. Full registry: `data/v2_claims.json`,
`docs/v2_claims_register.md`.

## 13.3 Loop 2 - arithmetic

40 independent recomputations, worst relative
error 1.79e-16
({'product': 'ammonia', 'name': 'Ni_inventory'}).

## 13.4 Loop 3 - conservation

Worst element/enthalpy imbalance 1.96e-12%.
The full-flowsheet check explicitly includes condensed water, MDEA CO2 product,
PSA tail gas and dryer water.

## 13.5 Loop 4 - thermodynamic consistency

- Real-gas equilibrium: worst |Q*Kphi/K - 1| = 8.46e-12%.
- Compressibility factors by product:
| product | Z | Kphi_R1 | Q1/K1 (real) |
|---|---|---|---|
| methanol | 1.00295 | 1.01628 | 1.00000000 |
| ft | 1.00339 | 1.00701 | 1.00000000 |
| oxo | 1.00386 | 1.00857 | 1.00000000 |
| hydrogen | 1.00288 | 1.01626 | 1.00000000 |
| ammonia | 1.00434 | 1.01560 | 1.00000000 |
- Shomate vs NASA7 reaction enthalpies at 1123 K:
| reaction | Shomate kJ/mol | NASA7 kJ/mol | difference |
|---|---|---|---|
| SMR | 226.785 | 225.787 | 0.997 |
| WGS | -33.565 | -33.556 | -0.009 |
| DRM | 260.349 | 259.343 | 1.006 |
| H2OX | -248.590 | -248.585 | -0.004 |
- IAPWS-IF97: h(30 bar, 673.15 K) = 3231.571 kJ/kg
  (reference 3231.571), Tsat(30 bar) = 507.008 K
  (reference 507.008). Status [ЧАСТИЧНО]: the IF97 revision guide was NOT opened;
  the installed package version is pinned.
- Dew point IF97 313.15 K vs NIST Antoine
  313.17 K; difference
  0.02 K. This is why IF97 is the primary
  water/steam property source in V2.
- PR vs ideal X_CH4: 0.80884 -> 0.80730 (delta -0.00155); k_ij spread in X_CH4 = 0.001850.

## 13.6 Loop 5 - validation / falsification

**FAILED (honestly reported)**.
No independent experimental or commercial-licensor validation of the V2 product variants. HYSYS was not run. All five product targets are matched by the model's own equilibrium solver, which is a self-check, not an external validation.

Unchecked items:
1. HYSYS / DWSIM / COCO steady-state run (not installed; user answer 11 confirms Python equivalent)
2. Experimental pilot campaign for Ni/MgAl2O4 conversion, pressure drop and catalyst life
3. Vendor Ni/MgAl2O4 catalyst datasheet: bulk density, Ni loading, crush strength, life
4. Validated Xu-Froment kinetic parameter set (full primary text not opened; secondary set fails self-consistency)
5. Sintering model discrimination: GPLE vs power-law life differ by factor ~3.06 (v1 finding)
6. PSA vendor impurity-breakthrough curve (slip weights are calibrated assumptions)
7. MDEA vendor reboiler duty and CO2 recovery guarantee
8. API 530 / ASME certified tube creep calculation (LMP slope is an assumption)
9. Regional gas/electricity/CO2 price quotes for Russia and the Middle East
10. GOST 5542:2022 full standard text (only a status page was opened)
11. Ammonia-loop compression and synthesis duty, methanol/FT/oxo downstream synthesis loops
12. Safety study: HAZOP, Ni(CO)4 formation during shutdown, relief sizing

## 13.7 Equipment accuracy upgrades

- 1-D tube thermal profile with local equilibrium composition;
  T_wall,max for methanol = 1271.2 K
  (998.0 C),
  consistent with the ~1000 C wall reported in the opened electrified-SMR study.
- LMP creep: C = 22.4, one opened HP-Nb point (11 MPa at LMP 35.2),
  API 530 thin-cylinder equation t = P*Do/(2S+P) + corrosion allowance.
  Required thickness 0.01427 m
  vs specified 0.01500 m
  -> PASS.
  The master-curve slope is an [ДОПУЩЕНИЕ]; this is NOT an API 530 certification.
- Ergun dP for the packed tubes: 1266880.215 bar
  (limit 3.00 bar).
