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


def build_worksheet():
    rows = []
    for node in NODES:
        for gw in GUIDEWORDS:
            s, l = severity(gw, node), likelihood(gw)
            rows.append({
                "node_id": node["id"], "node": node["node"],
                "design_intent": node["intent"],
                "guideword": gw,
                "deviation": f"{gw} at {node['node']}",
                "cause": CAUSES[gw],
                "consequence": CONSEQUENCES[gw],
                "safeguards": SAFEGUARDS[gw],
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
    return {
        "standard_basis": "IEC 61882:2016 Hazard and operability (HAZOP) studies - application guide (structure only; full text NOT opened)",
        "certified": False,
        "certification_status": "[НЕ ПОДТВЕРЖДЕНО] NOT A CERTIFIED HAZOP",
        "worksheet_rows": len(rows),
        "nodes": len(NODES), "guidewords": len(GUIDEWORDS),
        "high_risk_rows": len(high),
        "high_risk_examples": [{"node": r["node"], "guideword": r["guideword"],
                                "risk_score": r["risk_score"]} for r in high[:12]],
        "worksheet": rows,
        "certification_gaps": CERTIFICATION_GAPS,
        "disclaimer": "This is an automatically generated WORKSHEET TEMPLATE for a "
                      "future certified study. It must NOT be used as a safety case, "
                      "as a basis for construction, or as evidence of compliance.",
    }
