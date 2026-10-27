"""Configuration layer: single source of truth + adjustable overrides.

User answer #2/#7/#3/#8: everything is adjustable, both normal-cubic-metre
definitions and both climates are provided. Overrides use dotted paths, e.g.

    cfg = load_config()
    cfg.set("products.ft.knobs.O2C", 0.66)
    cfg.set("active.climate", "middle_east")
    cfg.set("active.normal", "15C")
    cfg.set("products.methanol.capacity", 150000)
    eff = cfg.resolve()
"""
from __future__ import annotations
import copy, json, os
from .thermo import R_J

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEFAULT_PATH = os.path.join(ROOT, "cases", "config.json")


class Config:
    def __init__(self, raw, path=DEFAULT_PATH):
        self.raw = copy.deepcopy(raw)
        self.path = path
        self.overrides = {}

    @classmethod
    def load(cls, path=DEFAULT_PATH):
        with open(path, encoding="utf-8") as fh:
            return cls(json.load(fh), path)

    def get(self, dotted, default=None):
        cur = self.raw
        for part in dotted.split("."):
            if isinstance(cur, dict) and part in cur:
                cur = cur[part]
            else:
                return default
        return cur

    def set(self, dotted, value):
        node = self.raw
        parts = dotted.split(".")
        for part in parts[:-1]:
            node = node.setdefault(part, {})
        node[parts[-1]] = value
        self.overrides[dotted] = value
        return self

    def apply(self, overrides: dict):
        for k, v in (overrides or {}).items():
            self.set(k, v)
        return self

    def save(self, path):
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(self.raw, fh, indent=2, ensure_ascii=False)

    def resolve(self, product=None):
        raw = copy.deepcopy(self.raw)
        if "adjust" in raw:
            for k, v in (raw.pop("adjust") or {}).items():
                node = raw
                parts = k.split(".")
                for p in parts[:-1]:
                    node = node.setdefault(p, {})
                node[parts[-1]] = v
        act = raw["active"]
        prod = product or act["product"]
        act["product"] = prod
        if prod not in raw["products"]:
            raise KeyError(f"unknown product {prod!r}; choose from {list(raw['products'])}")
        P = raw["products"][prod]
        # The active route follows the selected product variant.
        act["route"] = P.get("route", act["route"])
        N = raw["normal_conditions"][act["normal"]]
        C = raw["climates"][act["climate"]]
        F = raw["feeds"][act["feed"]]
        # derive normal molar volume from T,p (ideal, dry) - not just the tabulated value
        Vm = R_J * N["T_K"] / N["p_Pa"]
        return EffectiveConfig(raw, prod, P, N, C, F, Vm, act, self.overrides)


class EffectiveConfig:
    def __init__(self, raw, product, P, N, C, F, Vm, active, overrides):
        self.raw = raw
        self.product = product
        self._knobs = P["knobs"]
        self.P = P
        self.N = N
        self.C = C
        self.F = F
        self.Vm = Vm
        self.active = active
        self.overrides = overrides

    # convenience -------------------------------------------------------------
    @property
    def knobs(self): return self._knobs
    @knobs.setter
    def knobs(self, value): self._knobs = value; self.P["knobs"] = value
    @property
    def process(self): return self.raw["process"]
    @property
    def catalyst(self): return self.raw["catalyst"]
    @property
    def eos(self): return self.raw["eos"]
    @property
    def equipment(self): return self.raw["equipment"]
    @property
    def economics(self): return self.raw["economics"]
    @property
    def climate_T_product_K(self): return self.C["product_T_C"] + 273.15
    @property
    def eos_kset(self): return self.eos["kset"] if self.eos["enabled"] else None
    @property
    def use_iapws(self): return self.active.get("steam_table") == "IAPWS97"

    def capacity_in_mol_h(self, capacity=None, unit=None):
        """Convert the configured product capacity to mol/h of the requested basis."""
        cap = capacity if capacity is not None else self.P["capacity"]
        u = unit or self.P["capacity_unit"]
        if u in ("dry_syngas_Nm3_h", "H2_Nm3_h", "Nm3_h"):
            return cap / self.Vm
        if u == "NH3_t_day":
            # NH3: N2 + 3H2 -> 2NH3; 1 t NH3 needs 0.5 t N2-equivalent of
            # (H2+N2) synthesis gas. Convert via NH3 molar mass 17.0305 g/mol.
            nh3_mol_h = cap * 1000.0 / 0.0170305 / 24.0
            syngas_mol_h = 2.0 * nh3_mol_h        # 4 mol syngas -> 2 mol NH3
            return syngas_mol_h
        if u in ("kmol_h", "mol_h"):
            return cap * (1000.0 if u == "kmol_h" else 1.0)
        raise ValueError(f"unknown capacity unit {u}")

    def metric_of(self, y_dry):
        h2 = y_dry.get("H2", 0.0); co = y_dry.get("CO", 0.0)
        co2 = y_dry.get("CO2", 0.0); n2 = y_dry.get("N2", 0.0)
        m = self.P["metric"]
        if m == "SN":
            return (h2 - co2) / (co + co2) if (co + co2) else None
        if m == "H2_CO":
            return h2 / co if co else None
        if m == "H2_N2":
            return h2 / n2 if n2 else None
        if m == "H2_purity":
            return h2
        return None

    def describe(self):
        return {"product": self.product, "normal": self.active["normal"],
                "climate": self.active["climate"], "feed": self.active["feed"],
                "route": self.active["route"], "Vm_m3_per_mol": self.Vm,
                "capacity": self.P["capacity"], "capacity_unit": self.P["capacity_unit"],
                "target": self.P["target"], "metric": self.P["metric"],
                "eos_kset": self.eos_kset, "use_iapws": self.use_iapws,
                "overrides": self.overrides,
                "product_T_C": self.C["product_T_C"],
                "ambient_C": self.C["ambient_dry_bulb_C"]}


def load_config(path=DEFAULT_PATH, overrides=None, product=None):
    # Convenience: load_config({'a.b': 1}) is the same as load_config(overrides=...)
    if isinstance(path, dict):
        overrides, path = {**path, **(overrides or {})}, DEFAULT_PATH
    cfg = Config.load(path)
    # V5.3: audited operator overlay (data/operator_inputs.json). No file, no
    # change; a form that fails validation is never half-applied. See
    # model/operator_data.overlay_adjust and docs/33.
    try:
        from .operator_data import overlay_adjust
        adj, meta = overlay_adjust()
    except Exception:                                   # pragma: no cover
        adj, meta = {}, None
    if adj:
        raw = copy.deepcopy(cfg.raw)
        appr = adj.pop("__approach_K_all__", None)
        if appr is not None:            # one entry fans out to every product
            for P in (raw.get("products") or {}).values():
                P.setdefault("knobs", {})["approach_K"] = appr
        raw["adjust"] = {**(raw.get("adjust") or {}), **adj}
        cfg = Config(raw, path)
    if meta:
        cfg.raw["operator_overlay"] = meta
    if overrides:
        cfg.apply(overrides)
    return cfg.resolve(product)
