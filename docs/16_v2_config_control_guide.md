# 16. Configuration and control guide (user answers 2, 7, 11)

## 16.1 Three ways to regulate the model

1. **Edit `cases/config.json`** - the single source of truth. Section map:
   `active` (product/normal/climate/feed/eos), `normal_conditions`,
   `climates`, `feeds`, `products.*.knobs`, `process`, `catalyst`, `eos`,
   `equipment`, `economics`, `adjust`.
2. **Dotted overrides** in Python:
   ```python
   from model.config import load_config
   from model.products import design
   r = design(load_config({"active.climate":"middle_east",
                           "active.normal":"15C",
                           "products.methanol.knobs.SC":3.5,
                           "economics.gas_USD_per_MMBtu":6.0}))
   ```
3. **CLI** `model/control.py` and **live control panel** `web/app.py` (Flask).

## 16.2 CLI

```
PYTHONPATH=. .venv/bin/python -m model.control list
PYTHONPATH=. .venv/bin/python -m model.control show --product ft
PYTHONPATH=. .venv/bin/python -m model.control run --product methanol --set economics.gas_USD_per_MMBtu=6
PYTHONPATH=. .venv/bin/python -m model.control compare
PYTHONPATH=. .venv/bin/python -m model.control sweep --product oxo
PYTHONPATH=. .venv/bin/python -m model.control set active.climate middle_east
```

`set` writes into `cases/config.json`. `run`/`compare` never mutate the file
unless `--save` is passed.

## 16.3 Live control panel

```
PYTHONPATH=. .venv/bin/python -m web.app
```
opens on 0.0.0.0:5000 and is proxied as the Arena live preview. Sliders and
selects change product, normal standard, climate, feed, EOS k_ij set, IAPWS
switch, capacity, S/C, CO2/C, O2/C, T, p, approach, catalyst life, Ni wt%,
GHSV, Ni price and energy prices. "Run model" recomputes; "Compare all 5
products" runs the full matrix. All responses are JSON from `/api/*`.

## 16.4 Utilities are adjustable (user answer 7)

`climates.*` sets cooling water ΔT and air-cooler approach;
`process.steam_p_bar_abs`, `steam_T_K`, `furnace_efficiency_LHV` and
`pinch_dT_min_K` set the steam system; `economics.*` sets gas, power, CO2,
steam and cooling-water prices; `equipment.O2_power_kWh_per_t` (via
`equipment.asu_power` in v1) / `economics.O2_power_kWh_per_t` set ASU power.
Both air cooling and water cooling are reported with a feasibility flag.

## 16.5 HYSYS equivalence (user answer 11)

HYSYS is NOT installed. Confirmed equivalent = this reproducible Python model
(Gibbs minimisation + Peng-Robinson + IF97 + 1-D equipment) plus
`docs/HYSYS_case_spec.md`, which lists the exact HYSYS property package,
reactor blocks and convergence settings needed to reproduce it. No `.hsc`
file was produced and no HYSYS run is claimed.
