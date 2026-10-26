# 15. Russia and Middle East site cases (user answer 8)

All climates are adjustable in `cases/config.json` (`active.climate` and the
`climates` block). Utilities follow the climate: cooling-water supply/return,
air-cooler approach, product temperature and BFW temperature.

| product | climate | product T C | air-cooler outlet C | trim cooling? | CW m3/h | cooling kW | cost | unit |
|---|---|---|---|---|---|---|---|---|
| methanol | russia | 40 | 42.0 | yes | 6550.1 | 76053 | 225.06 | USD/1000 Nm3 dry syngas |
| methanol | middle_east | 55 | 60.0 | yes | 6420.7 | 74551 | 224.97 | USD/1000 Nm3 dry syngas |
| hydrogen | russia | 40 | 42.0 | yes | 7874.8 | 91435 | 364.98 | USD/1000 Nm3 H2 |
| hydrogen | middle_east | 55 | 60.0 | yes | 7711.1 | 89535 | 364.87 | USD/1000 Nm3 H2 |
| ammonia | russia | 40 | 42.0 | yes | 9634.6 | 111868 | 600.09 | USD/t NH3 |
| ammonia | middle_east | 55 | 60.0 | yes | 9430.0 | 109493 | 599.84 | USD/t NH3 |

Russia design basis: ambient 30 C, cooling water 20->30 C, product 40 C.
Middle East: ambient 48 C, cooling water 35->45 C, product 55 C.
Sources (opened): Kasko/ACHE air-cooler design guide (Middle East design
ambient 45-50 C, Jubail 50 C case, water scarcity), IPIECA cooling systems
2022 (cooling-water return 32-45 C), Gulf-region cooling-water study (20 C
seawater in the reference case). The exact design values are engineering
choices inside those opened ranges -> [ЧАСТИЧНО].

Consequence: the hotter site raises the absorber/product temperature from 40 C
to 55 C, which changes the condensation and cooling-water duties and requires
a molecular-sieve dryer to hold the 0.5 mol% H2O product spec (dryer
regeneration duty is [NOT MODELLED]). An air-cooler-only configuration cannot
reach a 40 C product at 48 C ambient; either the product temperature is raised
or a cooling-water/chilled trim is needed. Air coolers are preferred in the
Middle East because of water scarcity (opened guide), but the 12 K approach
still leaves 60.0 C outlet air-side temperature.

The `me_rich` feed case (user answer 8 "possibly Middle East") is an
[ДОПУЩЕНИЕ] analogue composition, not a specific field assay:

| feed | dry feed Nm3/h | X_CH4 | SN | cost |
|---|---|---|---|---|
| russia_h | 25950.5 | 0.7852 | 2.0500 | 225.06 |
| me_rich | 24696.7 | 0.7946 | 2.0500 | 219.32 |
