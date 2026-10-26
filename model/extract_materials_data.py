"""Extract melting points (NASA condensed database) and critical properties
(Cantera critical-properties.yaml, sourced from NIST/WebBook & Yaws) into
version-pinned JSON files. Run with PyYAML + Cantera installed."""
import json, os, yaml
import cantera as ct
root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ctdir = os.path.dirname(ct.__file__)
doc = yaml.safe_load(open(os.path.join(ctdir,'data','nasa_condensed.yaml')))
sp = {d['name']: d for d in doc['species']}
def tmax(name):
    r = sp[name]['thermo']['temperature-ranges']
    return r[-1], r
melting = {
 "meta": {"source": os.path.join(ctdir,'data','nasa_condensed.yaml'),
          "citation": "McBride, Gordon & Reno, NASA TM-4513, October 1993; distributed with Cantera "+ct.__version__,
          "note": "Upper bound of the solid-phase NASA7 fit is taken as the melting temperature. Cross-checked against NIST-JANAF (Ni, Al2O3) and US7541005B2 (MgAl2O4).",
          "retrieved": "2026-10-26"},
 "K": {}
}
for key, solid in [("Ni","Ni(cr)"),("Al2O3","AL2O3(a)"),("MgAl2O4","MgAL2O4(s)"),
                   ("ZrO2","ZrO2(a)"),("ZrO2_b","ZrO2(b)"),("C_graphite","C(gr)")]:
    if solid in sp:
        v,r = tmax(solid)
        melting["K"][key] = {"T_upper_fit_K": v, "ranges_K": r, "species_name": solid}
json.dump(melting, open(os.path.join(root,'data','melting_points.json'),'w'), indent=2)

critdoc = yaml.safe_load(open(os.path.join(ctdir,'data','critical-properties.yaml')))
want = {"CH4","C2H6","C3H8","H2O","CO","CO2","H2","O2","N2"}
crit = {"meta": {"source": os.path.join(ctdir,'data','critical-properties.yaml'),
                 "citation": critdoc.get('source',''), "cantera_version": ct.__version__,
                 "note": "Used ONLY for the Peng-Robinson sensitivity check on the ideal-gas assumption (verification loop 4).",
                 "retrieved": "2026-10-26"}, "species": {}}
for d in critdoc.get('species', []):
    if d['name'] in want:
        c = d.get('critical-parameters', d)
        crit['species'][d['name']] = {k: c.get(k) for k in
            ('critical-temperature','critical-pressure','acentric-factor','critical-volume')}
json.dump(crit, open(os.path.join(root,'data','critical_properties.json'),'w'), indent=2)
print(json.dumps(melting['K'], indent=2))
print(json.dumps(crit['species'], indent=2)[:2000])
