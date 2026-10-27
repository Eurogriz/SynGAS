"""IEC 61882-style HAZOP worksheet generator + certification gap register.

STATUS: THIS IS NOT A CERTIFIED HAZOP. A certified HAZOP study requires a
multi-disciplinary team, a competent independent facilitator, reviewed P&IDs,
a signed terms of reference, action close-out and management sign-off. No such
study was performed here. This module produces a structured WORKSHEET that a
real team could use as a starting point, and explicitly records what is missing
for certification.
"""
from __future__ import annotations

GUIDEWORDS = ["NO/LOW FLOW", "HIGH FLOW", "HIGH P", "LOW P", "HIGH T",
              "LOW T", "WRONG COMPOSITION", "REVERSE FLOW", "LEAK/RUPTURE",
              "UTILITY FAILURE", "STARTUP/SHUTDOWN"]

NODES = [
    {"id": "N01", "node": "Natural-gas feed / HDS-ZnO guard", "intent": "deliver S<0.02 ppmv gas at 30 bar"},
    {"id": "N02", "node": "R-100 adiabatic pre-reformer", "intent": "remove C2+ at 600-750 K, Q=0"},
    {"id": "N03", "node": "R-101 fired tubular reformer", "intent": "1123 K, 25 bar, SN=2.05"},
    {"id": "N04", "node": "WHB / syngas cooler", "intent": "recover heat, raise 30 bar steam"},
    {"id": "N05", "node": "A-302 CO2 trim / A-301 MDEA", "intent": "CO2 to 4-8 mol% / <3 mol%"},
    {"id": "N06", "node": "E-601 cooler + knockout + dryer", "intent": "product at 40/55 C"},
    {"id": "N07", "node": "PSA / methanator", "intent": "ISO 14687 H2 / <10 ppm CO+CO2"},
    {"id": "N08", "node": "Synthesis loop + recycle compressor", "intent": "MeOH/FT/oxo/NH3 product"},
    {"id": "N09", "node": "SHUTDOWN / standby / Ni(CO)4", "intent": "CO<10 ppm before T<200 C"},
    {"id": "N10", "node": "PSV / flare / relief network", "intent": "protect against blocked outlet"},
]

# Cause/consequence/safeguard are engineering-screening statements, NOT
# certified findings. All are marked [ДОПУЩЕНИЕ] in the worksheet.
CAUSES = {
    "NO/LOW FLOW": "blocked line, pump/compressor trip, closed valve, control failure",
    "HIGH FLOW": "control valve fail-open, upstream overpressure, wrong set point",
    "HIGH P": "blocked outlet, thermal expansion, failed PCV, PSV lifted",
    "LOW P": "upstream loss, leak, excessive letdown",
    "HIGH T": "firing maldistribution, loss of quench, exothermic runaway",
    "LOW T": "loss of preheat, excessive quench, ambient cooling during shutdown",
    "WRONG COMPOSITION": "S/C or CO2/C ratio error, sulfur breakthrough, air ingress",
    "REVERSE FLOW": "check-valve failure, pressure reversal at mixer",
    "LEAK/RUPTURE": "creep, corrosion, thermal fatigue, flange failure",
    "UTILITY FAILURE": "BFW, cooling water, power, instrument air, steam loss",
    "STARTUP/SHUTDOWN": "incomplete purge, wrong sequence, CO present while cooling",
}

CONSEQUENCES = {
    "NO/LOW FLOW": "hot tubes, carbon deposition, catalyst damage, low product rate",
    "HIGH FLOW": "high dP, insufficient residence time, off-spec product",
    "HIGH P": "relief lift, vessel/tube rupture, toxic release",
    "LOW P": "loss of synthesis equilibrium, air ingress, explosive mixture",
    "HIGH T": "tube creep rupture (LMP), Ni sintering, Ni(CO)4 decomposition",
    "LOW T": "condensation, Ni(CO)4 formation, hydrate/ice, thermal shock",
    "WRONG COMPOSITION": "SN drift, poisoning, carbon formation, runaway",
    "REVERSE FLOW": "steam into gas line, water hammer, catalyst damage",
    "LEAK/RUPTURE": "fire, toxic CO/H2/Ni(CO)4 release, escalation",
    "UTILITY FAILURE": "overheating, loss of vacuum/condensation, trip",
    "STARTUP/SHUTDOWN": "Ni(CO)4 formation, explosive mixture, residual CO",
}

SAFEGUARDS = {
    "NO/LOW FLOW": "low-low flow trip, furnace interlock, online GC, dP alarm",
    "HIGH FLOW": "flow controller with high-high trip, PSV, ESD valve",
    "HIGH P": "PCV, PSV to flare, high-high P trip, HIPPS study",
    "LOW P": "low-low P trip, N2 purge, non-return valves",
    "HIGH T": "skin thermocouples, high-high T trip, LMP-based tube life",
    "LOW T": "preheat interlock, CO purge before cooldown, tracing",
    "WRONG COMPOSITION": "online S/C, CO2/C, SN, H2S analysers; feed ratio trip",
    "REVERSE FLOW": "check valves, ESD, high-integrity pressure protection",
    "LEAK/RUPTURE": "gas detectors, fire detectors, ESD, deluge, zoning",
    "UTILITY FAILURE": "UPS, emergency generator, standby BFW pump, fail-open vents",
    "STARTUP/SHUTDOWN": "written purge procedure, CO<10 ppm permit, Ni(CO)4 monitor",
}


# V5: the generic template applied Ni(CO)4 / Ni sintering / tube-creep wording to
# EVERY node, including an amine absorber and a flare header. That is a template
# artefact: those consequences belong only to nodes that actually contain nickel
# catalyst or hot process tubes. Node-specific wording replaces the generic one in
# place, so the worksheet stays 10 nodes x 11 guidewords = 110 rows.
NODE_CONSEQUENCE_OVERRIDES = {
    "N01": {"HIGH T": ("ZnO/HDS bed sintering, sulfur slip to reformer catalyst, "
                       "guard-vessel damage",
                       "bed inlet TC high-high trip, online H2S analyser, "
                       "deactivation model for ZnO"),
            "STARTUP/SHUTDOWN": ("HDS catalyst not sulfided on first start, "
                                 "cold guard bed, sulfur breakthrough to the "
                                 "reformer, carbon formation at the Ni layer",
                                 "sulfiding procedure + permit, bed preheat "
                                 "interlock, H2S analyser before start")},
    "N02": {"STARTUP/SHUTDOWN": ("Ni(CO)4 formation while CO-rich gas cools "
                                 "below 200 C, explosive mixture during purge",
                                 "written purge procedure, CO < 10 ppm permit "
                                 "before T < 200 C, Ni(CO)4 monitoring")},
    "N03": {"STARTUP/SHUTDOWN": ("Ni(CO)4 formation while CO-rich gas cools "
                                 "below 200 C, tube overheating on firing during "
                                 "low steam flow",
                                 "written purge procedure, CO < 10 ppm permit "
                                 "before T < 200 C, S/C low-low permissive on "
                                 "light-off")},
    "N04": {"HIGH T": ("boiler tube creep rupture, steam-side overpressure, "
                        "WHB dry-out",
                        "drum level trips, skin TCs, steam relief to header"),
            "STARTUP/SHUTDOWN": ("thermal shock of boiler tubes on hot syngas "
                                 "admission, dry-out if drum level is not "
                                 "established, acid-gas condensation corrosion "
                                 "in cold syngas lines",
                                 "warm-up rate limit, drum level permissive "
                                 "before syngas admission, low-T drain points")},
    "N05": {"HIGH T": ("MDEA thermal degradation above ~120 C, reboiler fouling, "
                       "CO2 slip off-spec, water carry-over to methanation",
                       "reboiler TC high trip, lean amine flow control, "
                       "reclaimer availability"),
            "STARTUP/SHUTDOWN": ("amine solidification / freezing of lines, "
                                 "carry-over of water and CO2 into the "
                                 "methanator on restart",
                                 "trace heating, commissioning procedure, "
                                 "CO2 spec permit before methanator light-off")},
    "N06": {"HIGH T": ("molecular-sieve adsorbent damage, breakthrough of water "
                       "to the synthesis loop, catalyst poisoning",
                       "regeneration TC high trip, heater interlock, "
                       "online dew-point analyser"),
            "STARTUP/SHUTDOWN": ("wet adsorbent if regeneration is incomplete, "
                                 "ice/hydrate in cold depressurised beds, "
                                 "oxygen ingress on vacuum breaking",
                                 "regeneration completion permit, N2 blanket, "
                                 "dew-point analyser before admission to loop")},
    "N07": {"STARTUP/SHUTDOWN": ("Ni(CO)4 formation in the methanator catalyst "
                                 "during cooldown with CO present, wet "
                                 "methanator catalyst on steam-out",
                                 "CO purge sequence, cooldown rate limit, "
                                 "Ni(CO)4 monitoring at the vent")},
    "N10": {"HIGH T": ("relief line / flare tip damage, radiant heating of "
                       "adjacent equipment, flame impingement",
                       "flare tip temperature monitoring, radiation design "
                       "cases, PSV back-pressure check"),
            "STARTUP/SHUTDOWN": ("air ingress into a cold flare header, "
                                 "explosive mixture at relight, loss of "
                                 "purgery pressure",
                                 "continuous pilot + flame supervision, N2 "
                                 "purge of header, velocity/pressure interlocks")},
}

RISK_MATRIX = {"S": {"L": 1, "M": 2, "H": 3},
               "M": {"L": 2, "M": 4, "H": 6},
               "H": {"L": 3, "M": 6, "H": 9}}


def severity(guide, node):
    if guide in ("HIGH P", "LEAK/RUPTURE", "STARTUP/SHUTDOWN", "HIGH T"):
        return "H"
    if guide in ("WRONG COMPOSITION", "REVERSE FLOW", "UTILITY FAILURE"):
        return "M"
    return "S" if guide in ("LOW T", "HIGH FLOW") else "M"


def likelihood(guide):
    # Screening priors, [ДОПУЩЕНИЕ]; a real HAZOP team must re-rank these.
    return {"NO/LOW FLOW": "M", "HIGH P": "L", "LOW P": "M",
            "HIGH T": "M", "LOW T": "M", "HIGH FLOW": "L",
            "WRONG COMPOSITION": "M", "REVERSE FLOW": "L",
            "LEAK/RUPTURE": "L", "UTILITY FAILURE": "M",
            "STARTUP/SHUTDOWN": "M"}.get(guide, "M")


# Nodes whose equipment actually contains reduced nickel - only there is a
# nickel-carbonyl scenario credible. Everywhere else the phrase is stripped from
# the generic template text (V5 correction of a template artefact).
NI_BEARING_NODES = {"N02", "N03", "N07", "N08", "N09"}
_FRAGS = ("Ni(CO)4 formation, ", ", Ni(CO)4 formation", "Ni(CO)4 formation",
          "Ni(CO)4 decomposition, ", ", Ni(CO)4 decomposition",
          "Ni(CO)4 decomposition", "/Ni(CO)4 release", ", Ni(CO)4 release",
          "Ni(CO)4 release", "Ni(CO)4 monitor", ", Ni(CO)4")


def _strip_ni(text):
    for f in _FRAGS:
        text = text.replace(f, "")
    text = text.replace("toxic CO/H2/ release", "toxic CO/H2 release")
    text = text.replace("CO purge before cooldown, ", "CO purge before cooldown")
    while ", ," in text or text.endswith(", "):
        text = text.replace(", ,", ",").replace(", ", ", ").rstrip(", ")
        text = text.replace("  ", " ")
    return text.strip(", ").strip()


def _node_text(node, gw, table, which):
    ov = NODE_CONSEQUENCE_OVERRIDES.get(node["id"], {}).get(gw)
    base = (ov[0] if which == "consequence" else ov[1]) if ov else table[gw]
    if node["id"] in NI_BEARING_NODES or ov:
        return base
    return _strip_ni(base)


def build_worksheet():
    rows = []
    for node in NODES:
        for gw in GUIDEWORDS:
            s, l = severity(gw, node), likelihood(gw)
            cons = _node_text(node, gw, CONSEQUENCES, "consequence")
            generic = (gw not in NODE_CONSEQUENCE_OVERRIDES.get(node["id"], {})
                       and cons == CONSEQUENCES[gw])
            rows.append({
                "node_id": node["id"], "node": node["node"],
                "template_generic": generic,
                "design_intent": node["intent"],
                "guideword": gw,
                "deviation": f"{gw} at {node['node']}",
                "cause": CAUSES[gw],
                "consequence": _node_text(node, gw, CONSEQUENCES, "consequence"),
                "safeguards": _node_text(node, gw, SAFEGUARDS, "safeguards"),
                "severity": s, "likelihood": l,
                "risk_score": RISK_MATRIX[s][l],
                "recommendation": ("SIL verification / independent protection layer"
                                   if RISK_MATRIX[s][l] >= 6 else
                                   "confirm existing safeguard in P&ID review"),
                "action_owner": "TBD by HAZOP team",
                "status": "[ДОПУЩЕНИЕ] screening entry - not a team finding",
            })
    return rows


CERTIFICATION_GAPS = [
    "No chartered multi-disciplinary HAZOP team was convened (IEC 61882 requires a team).",
    "No independent competent facilitator / scribe was appointed.",
    "No reviewed and frozen P&IDs, cause-and-effect matrix or safeguard list existed.",
    "No signed terms of reference, scope, node definition by a responsible engineer.",
    "No LOPA / SIL verification (IEC 61508 / IEC 61511) of the proposed safeguards.",
    "No action close-out, management sign-off or re-HAZOP after design change.",
    "No consequence modelling (dispersion, fire, explosion, toxic Ni(CO)4 plume).",
    "No ATEX/IECEx hazardous-area classification or detector layout study.",
    "No MOC (management of change) record for the V2/V3 design modifications.",
]


def hazop_report():
    rows = build_worksheet()
    high = [r for r in rows if r["risk_score"] >= 6]
    # V5.3: a real HAZOP is a human act; the operator form is how its RECORD
    # enters this project. Nothing here certifies anything by itself - the flag
    # only flips when facilitator + date + report reference were all entered, and
    # the provenance is printed next to it.
    rec = {"certified": False, "source": "no operator record", "verified": False}
    try:
        from .operator_data import runtime_overlay
        ov = runtime_overlay() or {}
        if ov.get("hazop_certified"):
            rec = {"certified": True,
                   "source": {"facilitator": ov.get("hazop_facilitator"),
                              "date": ov.get("hazop_date"),
                              "report_ref": ov.get("hazop_ref")},
                   "verified": "hazop_certified" in (ov.get("_verified_ids") or []),
                   "provenance": (ov.get("_provenance") or {}).get("hazop_certified")}
    except Exception as exc:                            # pragma: no cover
        rec = {"certified": False, "source": "operator overlay unreadable (%r)" % exc,
               "verified": False}
    return {
        "operator_record": rec,
        "standard_basis": "IEC 61882:2016 Hazard and operability (HAZOP) studies - application guide (structure only; full text NOT opened)",
        "certified": bool(rec["certified"]),
        "certification_status": (
            "[ЧАСТИЧНО] запись внесена оператором (facilitator/дата/номер отчёта "
            "есть), независимой проверки документа в модели нет"
            if rec["certified"] else
            "[НЕ ПОДТВЕРЖДЕНО] NOT A CERTIFIED HAZOP"),
        "certification_record": rec,
        "worksheet_rows": len(rows),
        "nodes": len(NODES), "guidewords": len(GUIDEWORDS),
        "high_risk_rows": len(high),
        "high_risk_examples": [{"node": r["node"], "guideword": r["guideword"],
                                "risk_score": r["risk_score"]} for r in high[:12]],
        "n_generic_template_rows": sum(1 for r in rows if r["template_generic"]),
        "worksheet": rows,
        "certification_gaps": CERTIFICATION_GAPS,
        "v5_note": ("node-specific consequences added in V5: the earlier template "
                    "attributed Ni(CO)4 and tube-creep wording to every node, "
                    "which is wrong for the amine unit, the dryer and the flare "
                    "header; 20 high-risk rows are no longer 10 copies of the "
                    "same two entries"),
        "model_generated_inputs": MODEL_GENERATED_INPUTS,
        "disclaimer": "This is an automatically generated WORKSHEET TEMPLATE for a "
                      "future certified study. It must NOT be used as a safety case, "
                      "as a basis for construction, or as evidence of compliance.",
    }


# Model findings that a real HAZOP team must be GIVEN as inputs. These are
# computed by this project, so they are legitimate agenda items; they are NOT
# safety conclusions.
MODEL_GENERATED_INPUTS = [
    {"item": "Ammonia converter peak bed temperature 845.3 K vs an ASSUMED "
             "catalyst ceiling of 803.15 K (530 C)",
     "source": "results_v2/converter_ammonia.json -> design.T_peak_K",
     "hazop_question": "what protects the tubes/vessel if the bed runs hotter "
                       "than the vendor ceiling, and is the ceiling itself "
                       "guaranteed? (docs/28 item 12)"},
    {"item": "Reformer bed pressure drop 2.83 bar against a 3.0 bar design limit, "
             "from an Ergun correlation that has never been checked against a "
             "measured bed",
     "source": "results_v2/design_*.json -> equipment",
     "hazop_question": "flow maldistribution and hot tubes on partial blockage; "
                       "dP transmitter location and trip philosophy "
                       "(docs/27 section 4)"},
    {"item": "Equilibrium model overpredicts measured lab conversion by +0.287 "
             "in X_CH4 at 1-10 bar",
     "source": "results_v2/pilot_comparison.csv",
     "hazop_question": "if the real unit is kinetically limited, the S/C margin "
                       "for carbon formation at part load is NOT what the design "
                       "says - check low-load turndown case"},
    {"item": "Extrapolated Ni-sintering t50 of 109 h against a 32 000 h design "
             "life (from coking data at S/C=1.5, not sintering)",
     "source": "results_v2/pilot_data_summary.json -> deactivation",
     "hazop_question": "hot-spot and tube-rupture scenarios in a late-changeout "
                       "state; changeout interval is a safety-relevant parameter, "
                       "not only an economic one"},
    {"item": "Ni(CO)4 formation window during cooldown with CO present "
             "(log K = 7430/T - 21.90, OSTI 7349456, opened)",
     "source": "docs/24 (Larsson), docs/19",
     "hazop_question": "permit-to-work boundary: CO < 10 ppm before T < 200 C - "
                       "who measures, where, and what stops the cooldown?"},
    {"item": "Middle East case: cooling-water temperature raises the MDEA "
             "absorber and final-cooler approach; water dew point moves",
     "source": "results_v2/full_matrix.csv",
     "hazop_question": "site-specific: does the absorber overheat in the design "
                       "ambient, and is amine carry-over to the methanator a "
                       "credible scenario?"},
]
