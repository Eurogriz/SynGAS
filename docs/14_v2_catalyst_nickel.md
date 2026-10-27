# 14. Ni/MgAl2O4 catalyst volumes, life, consumption and nickel (user 10/12)

## 14.1 Chemistry basis (opened, not invented)

- **Ni/MgAl2O4, 15 wt% Ni, BET 86 m2/g, Ni particle 6.6 nm, reduction 850 C/16 h**
  - Catalysts 2019, 9(10), 801 (opened). [ПОДТВЕРЖДЕНО]
- EP1013603A1 (opened): 10-60 wt% Ni on high-surface MgAl2O4, BET 183-192 m2/g.
  Legal status Ceased; this is a technical range, NOT a patent-freedom conclusion.
- PNNL-23207 (opened): 20% Ni/MgAl2O4 gives 4.6 nm Ni vs 8.6 nm on Al2O3;
  TPR complete at 800 C; deactivation data. J Catal 2001 Sehested (opened):
  most Ni sintering occurs in the first 200 h.

## 14.2 Engineering PROXY (explicitly not MgAl2O4)

The opened Johnson Matthey KATALCO brochure gives loaded density 780-1140 kg/m3
(we use 900), NiO 16-18 wt% (= 12.6-14.1 wt% Ni metal), QUADRALOBE shapes,
>80% strength after 5 years and catalyst lives >8-10 years. Its supports are
alpha-Al2O3 / calcium aluminate, **NOT MgAl2O4**. Therefore 15 wt% Ni on MgAl2O4
is combined with the commercial bulk properties only as a clearly marked
[ЧАСТИЧНО] proxy. A vendor Ni/MgAl2O4 datasheet was NOT found.

Ni metal from NiO: 17 wt% * 58.6934/74.6924 = 13.36 wt%.

## 14.3 Results

GHSV = 2500 Nm3/(m3cat h) for the main reformer, 5000 for the pre-reformer
(opened electrified-SMR value + [ДОПУЩЕНИЕ] pre-reformer).

| product | V_reformer m3 | V_pre m3 | catalyst t | Ni inventory t | Ni t/y (4 y life) | catalyst t/y | ZnO kg | Ni inventory, kg per 1000 Nm3 of annual product |
|---|---|---|---|---|---|---|---|---|
| methanol | 52.30 | 26.15 | 70.60 | 10.590 | 2.648 | 17.65 | 65538 | 0.0132 |
| ft | 33.53 | 16.76 | 45.26 | 6.790 | 1.697 | 11.32 | 42019 | 0.0085 |
| oxo | 24.45 | 12.22 | 33.00 | 4.950 | 1.238 | 8.25 | 30635 | 0.0124 |
| hydrogen | 58.58 | 29.29 | 79.08 | 11.862 | 2.965 | 19.77 | 73407 | 0.0148 |
| ammonia | 50.27 | 25.14 | 67.87 | 10.180 | 2.545 | 16.97 | 62999 | 0.0097 |

**Unit note (V5.2 fix).** The last column and the `Ni_consumption_kg_per_1000Nm3`
field of the life sensitivity used to carry two cancelling `/1000` factors, i.e.
they returned kg per **Nm3** under a key that says kg per **1000 Nm3** - values
were 1000x low. `model/catalyst_inventory.py` now multiplies by 1000 once; the
table above is the corrected basis. `Ni_per_1000Nm3_product_kg` is an inventory
intensity (installed Ni per annual product volume), NOT a consumption rate - the
consumption rate is the `/life` version in the sensitivity below.

## 14.4 Life sensitivity (methanol example)

| life y | Ni t/y | catalyst t/y |
|---|---|---|
| 3.0 | 3.530 | 23.53 |
| 5.0 | 2.118 | 14.12 |
| 8.0 | 1.324 | 8.83 |
| 10.0 | 1.059 | 7.06 |

Nickel price 18000 USD/t is an
[ДОПУЩЕНИЕ] (no LME quote opened); annual Ni make-up cost is
Ni_t_per_y * price, and the sensitivity above scales it by 1/life.

## 14.5 Sintering / deactivation (still open)

The v1 GPLE and power-law sintering predictions differ by a factor of ~3.06;
no validated 3-year life for 15 wt% Ni/MgAl2O4 was found. V2 therefore reports
a user-adjustable life (default 4 y, sensitivity 3/5/8/10 y) rather than a
"final" life. [НЕ ПОДТВЕРЖДЕНО]
