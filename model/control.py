"""Command-line control panel for the V2 model (user answers 2/7).

Examples:
  PYTHONPATH=. .venv/bin/python -m model.control list
  PYTHONPATH=. .venv/bin/python -m model.control show --product ft
  PYTHONPATH=. .venv/bin/python -m model.control run --product methanol \\
      --set economics.gas_USD_per_MMBtu=6 --set active.normal=15C
  PYTHONPATH=. .venv/bin/python -m model.control compare
  PYTHONPATH=. .venv/bin/python -m model.control sweep --product oxo
  PYTHONPATH=. .venv/bin/python -m model.control set active.climate middle_east
  PYTHONPATH=. .venv/bin/python -m model.control verify
"""
from __future__ import annotations
import argparse, json, os, sys
from .config import Config, load_config, DEFAULT_PATH
from .scenarios import (PRODUCTS, run_base, run_regulation_sweep, _compact,
                        run_normal_comparison, run_climate_comparison,
                        run_feed_comparison, run_eos_sensitivity)
from .products import design
from .verify_v2 import run_all as verify_all


def _parse_set(items):
    out = {}
    for it in items or []:
        if "=" not in it:
            raise SystemExit(f"--set expects key=value, got {it!r}")
        k, v = it.split("=", 1)
        try:
            out[k] = json.loads(v)
        except Exception:
            out[k] = v
    return out


def _brief(r):
    s, u, e, c = r["spec"], r["utilities"], r["economics"], r["catalyst"]
    return {
        "product": r["product"], "normal": r["normal"], "climate": r["climate"],
        "feed": r["feed"],
        "metric": s["metric"], "target": s["target"], "achieved": s["achieved"],
        "hit_target": s["within_tolerance"], "carbon_stable": s["carbon_stable"],
        "limit_checks": s["limit_checks"],
        "X_CH4": r["reformer"]["equilibrium"]["CH4_conversion"],
        "T_reformer_K": r["reformer"]["T_out_K"],
        "Z": r["eos"]["Z"],
        "fuel_Nm3_h": u["fuel_Nm3_h"], "total_CO2_t_h": u["total_CO2_t_h"],
        "cooling_water_m3_h": u["cooling_water_m3_h"],
        "O2_t_h": u["O2_t_h"], "power_MW": u["total_power_MW"],
        "Ni_inventory_t": c["total_Ni_inventory_t"],
        "catalyst_volume_m3": c["total_catalyst_volume_m3"],
        "levelised_cost": e["levelised_cost"], "cost_unit": e["unit"],
        "HYSYS": "NOT RUN - Python/DWSIM-equivalent confirmed",
        "validation_loop": "FAILED (no experimental data)",
    }


def main(argv=None):
    ap = argparse.ArgumentParser(prog="model.control")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("list", help="list products, normals, climates, feeds, knobs")
    p = sub.add_parser("show", help="show effective config")
    p.add_argument("--product", default="methanol", choices=PRODUCTS)
    p.add_argument("--set", action="append", default=[])
    p = sub.add_parser("run", help="run one product design")
    p.add_argument("--product", default="methanol", choices=PRODUCTS)
    p.add_argument("--set", action="append", default=[])
    p.add_argument("--no-tune", action="store_true")
    p.add_argument("--out", default=None, help="write full result JSON here")
    p = sub.add_parser("compare", help="run all five products + scenario matrices")
    p.add_argument("--set", action="append", default=[])
    p = sub.add_parser("sweep", help="regulation sweep for one product")
    p.add_argument("--product", default="methanol", choices=PRODUCTS)
    p = sub.add_parser("set", help="persist a dotted key into cases/config.json")
    p.add_argument("key"); p.add_argument("value")
    p = sub.add_parser("verify", help="run all five verification loops on all five designs")
    a = ap.parse_args(argv)
    if a.cmd == "list":
        cfg = Config.load()
        print("products :", list(cfg.raw["products"]))
        print("normals  :", [k for k in cfg.raw["normal_conditions"] if k != "note"])
        print("climates :", list(cfg.raw["climates"]))
        print("feeds    :", list(cfg.raw["feeds"]))
        print("eos k_ij :", cfg.raw["eos"]["kij_sensitivity"])
        print("\nknobs by product:")
        for k, v in cfg.raw["products"].items():
            print(f"  {k:10s} {v['knobs']}")
        print("\nconfigurable sections:",
              ", ".join(cfg.raw.keys()))
        return 0
    if a.cmd == "set":
        cfg = Config.load()
        try: val = json.loads(a.value)
        except Exception: val = a.value
        cfg.set(a.key, val)
        cfg.save(DEFAULT_PATH)
        print("set", a.key, "=", val, "->", DEFAULT_PATH)
        return 0
    if a.cmd == "show":
        ov = _parse_set(a.set)
        e = load_config(overrides=ov, product=a.product)
        print(json.dumps({"effective": e.describe(), "knobs": e.knobs,
                          "process": e.process, "catalyst": e.catalyst,
                          "eos": e.eos, "equipment": e.equipment,
                          "economics": e.economics}, indent=2, ensure_ascii=False))
        return 0
    if a.cmd == "run":
        ov = _parse_set(a.set)
        e = load_config(overrides=ov, product=a.product)
        r = design(e, do_tune=not a.no_tune)
        if a.out:
            from .run_v2 import dump_json
            dump_json(a.out, r)
            print("wrote", a.out)
        print(json.dumps(_brief(r), indent=2, ensure_ascii=False, default=str))
        return 0
    if a.cmd == "sweep":
        cfg = load_config(product=a.product)
        from .scenarios import run_regulation_sweep
        rows = [x for x in run_regulation_sweep() if x["product"] == a.product]
        print(json.dumps(rows, indent=2, ensure_ascii=False, default=str))
        return 0
    if a.cmd == "compare":
        ov = _parse_set(a.set)
        base = {}
        for p in PRODUCTS:
            base[p] = design(load_config(overrides=ov, product=p))
        sc = {"normal_comparison": run_normal_comparison(),
              "climate_comparison": run_climate_comparison(),
              "feed_comparison": run_feed_comparison(),
              "eos_sensitivity": run_eos_sensitivity()}
        print(json.dumps({"products": [_brief(base[p]) for p in PRODUCTS],
                          "normal_comparison": sc["normal_comparison"],
                          "climate_comparison": sc["climate_comparison"],
                          "feed_comparison": sc["feed_comparison"],
                          "eos_sensitivity": sc["eos_sensitivity"]},
                         indent=2, ensure_ascii=False, default=str))
        return 0
    if a.cmd == "verify":
        base = run_base()
        sc = {"eos_sensitivity": run_eos_sensitivity()}
        v = verify_all(base, sc)
        print(json.dumps({"summary": v["summary"],
                          "overall_passed": v["overall_passed"],
                          "hysys": v["hysys"],
                          "unchecked": v["loops"]["5_validation_falsification"]["unchecked_items"]},
                         indent=2, ensure_ascii=False, default=str))
        return 0
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
