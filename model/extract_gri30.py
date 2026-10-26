import json, os, re, sys, datetime
import yaml
ct = os.path.dirname(__import__('cantera').__file__)
out = {
  "meta": {
    "dataset": "NASA7 polynomials distributed with Cantera 3.2.0 (gri30.yaml = GRI-Mech 3.0, 1999; graphite.yaml = NASA SP-273 (Gordon & McBride, 1971) and NASA TM-4513 (McBride, Gordon & Reno, 1993))",
    "source_files": [
      os.path.join(ct, "data", "gri30.yaml"),
      os.path.join(ct, "data", "graphite.yaml")
    ],
    "generated": "2026-10-26",
    "cantera_version": __import__('cantera').__version__,
    "units": "NASA7: cp/R, h/(RT), s/R with T in K; a[0..6]",
    "note": "Second, independent thermochemical dataset used ONLY for cross-checking (verification loop 4). GRI-Mech 3.0 header states: 'GRI-Mech Version 3.0 7/30/99 CHEMKIN-II format ... http://combustion.berkeley.edu/gri-mech/version30/text30.html'. The upstream URL returned 404 at retrieval time; the coefficients were read from the installed, version-pinned Cantera data files."
  },
  "species": {}
}
def load(path):
    with open(path) as f: return yaml.safe_load(f)
g = load(os.path.join(ct,'data','gri30.yaml'))
gr = load(os.path.join(ct,'data','graphite.yaml'))
mapping = {"H2":"H2","H2O":"H2O","CO":"CO","CO2":"CO2","CH4":"CH4","C2H6":"C2H6","C3H8":"C3H8","O2":"O2","N2":"N2"}
for doc, m in ((g, mapping), (gr, {"C(gr)":"C_GR"})):
    for sp in doc['species']:
        if sp['name'] in m:
            th = sp['thermo']
            out['species'][m[sp['name']]] = {
                "source_name": sp['name'],
                "source_file": ("graphite.yaml" if sp["name"]=="C(gr)" else "gri30.yaml"),
                "model": th['model'],
                "temperature_ranges": th['temperature-ranges'],
                "data": th['data'],
                "elements": sp['composition']
            }
with open('data/gri30_nasa7.json','w') as f: json.dump(out,f,indent=2)
print(json.dumps({k: v['temperature_ranges'] for k,v in out['species'].items()}, indent=2))
