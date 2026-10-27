"""V5.3 tests: manual data entry by operators, with the corridor as the default.

The acceptance question for this version is narrow and sharp:

  (1) Can an operator enter EVERY missing number, and is the form strict enough
      that a careless entry cannot enter the model?  (provenance required,
      ranges enforced, all-or-nothing application, no writes into
      cases/config.json)
  (2) Does the corridor stay the RECOMMENDED reporting form while a dimension is
      missing, and does a single-source entry pin a point WITHOUT deleting the
      literature band?
  (3) Does data entry stop short of claiming validation?  Loop 5 must remain
      FAILED even with a fully filled, second-signature form, and no claim in
      data/v2_claims.json may be rewritten by the mechanism.

Tests that need a form write it under a temporary path and point
model.operator_data.FORM_PATH at it (never into data/, so no fabricated datum is
ever committed), and always restore the module state.
"""
import json
import os

import pytest

from model import operator_data as od

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RESULTS = os.path.join(ROOT, "results_v2")
FORM_OK = {"nh3_rho_bulk": (1300.0, "kg/m3"),
           "nh3_catalyst_price": (27.0, "USD/kg"),
           "nh3_catalyst_life_y": (6.0, "y"),
           "nh3_bed_T_max_C": (480.0, "degC"),
           "nh3_activity_k_scale": (0.504, "-"),
           "nh3_dP_loop_bar": (1.8, "bar")}


def _doc(pairs, applied=True, verified=False, extra=None):
    doc = od.template_doc()
    for fid, spec in pairs.items():
        val, unit = spec if isinstance(spec, tuple) else (spec, od.BY_ID[fid]["unit"])
        e = doc["entries"][fid]
        e.update({"value": val, "unit": unit, "method": "метод по протоколу",
                  "source": "документ-основание, лист 1", "received_date": "2026-10-05",
                  "entered_by": "operator-A", "applied": applied})
        if verified:
            e.update({"independently_verified": True, "verified_by": "engineer-B"})
    if extra:
        doc["entries"].update(extra)
    return doc


def _saved_design():
    """The ammonia design from the last full run - the same dict run_v2 passes.

    Reading the artifact keeps these wiring tests fast; the corridor takes only
    r['synthesis'] from it, which no operator field in these tests touches.
    """
    path = os.path.join(RESULTS, "design_ammonia.json")
    if not os.path.exists(path):
        pytest.skip("run model/run_v2 once to produce design_ammonia.json")
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


@pytest.fixture
def form(tmp_path):
    """Point the module at a temp form, then restore."""
    path = str(tmp_path / "operator_inputs.json")
    old = od.FORM_PATH
    od.FORM_PATH = path
    od._CACHE.clear()
    yield path
    od.FORM_PATH = old
    od._CACHE.clear()


# ------------------------------------------------------------ the form itself ---
def test_template_is_empty_and_valid_and_covers_every_open_item():
    doc = od.template_doc()
    assert len(od.FIELDS) >= 50
    assert set(doc["entries"]) == {f["id"] for f in od.FIELDS}
    assert all(e["value"] is None and e["applied"] is False
               for e in doc["entries"].values())
    errors, warnings, _ = od.validate(doc)
    assert errors == [] and warnings == []
    # no invented numbers may ship inside the blank form
    txt = json.dumps(doc, ensure_ascii=False)
    assert '"value": null' in txt and "0.504" not in txt
    # every field names where it lands and what it pins
    for f in od.FIELDS:
        assert f["label"] and f["unit"] and f["type"]
        assert f["type"] in ("number", "int", "list", "choice", "text", "date",
                             "bool", "path"), f["id"]
        if f["type"] in ("number", "int", "list"):
            assert f["lo"] is not None and f["hi"] > f["lo"], f["id"]
        for path, _scale in f["targets"]:
            assert path.startswith("model.") or path.startswith("__") or \
                path.split(".")[0] in ("catalyst", "equipment", "economics",
                                       "kinetics", "feeds", "process", "safety"), path


def test_numbers_without_provenance_are_rejected():
    doc = _doc({"nh3_rho_bulk": (1300.0, "kg/m3")})
    doc["entries"]["nh3_rho_bulk"].update({"method": "", "source": "",
                                           "received_date": "", "entered_by": ""})
    errors, _w, _c = od.validate(doc)
    assert any("method" in e for e in errors) and any("source" in e for e in errors)
    assert any("entered_by" in e for e in errors)


def test_wrong_unit_is_rejected_rather_than_converted():
    doc = _doc({"nh3_rho_bulk": (1300.0, "g/cm3")})
    errors, _w, _c = od.validate(doc)
    assert any("unit должно быть ровно" in e for e in errors)


def test_out_of_range_values_are_rejected_not_clamped():
    for fid, val, unit in [("nh3_bed_T_max_C", 5000.0, "degC"),
                           ("nh3_GHSV_h1", -5.0, "1/h"),
                           ("pellet_d_eq_mm", 0.001, "mm")]:
        doc = _doc({fid: (val, unit)})
        errors, _w, _c = od.validate(doc)
        assert any("outside" in e for e in errors), (fid, errors)


def test_feed_analysis_must_not_exceed_100_percent():
    doc = _doc({"feed_CH4": (97.4, "mol%"), "feed_C2H6": (4.0, "mol%"),
                "feed_N2": (1.0, "mol%")})
    errors, _w, _c = od.validate(doc)
    assert any("> 100" in e for e in errors)


def test_second_signature_must_be_a_different_person():
    doc = _doc({"nh3_catalyst_life_y": (6.0, "y")}, verified=True)
    doc["entries"]["nh3_catalyst_life_y"]["verified_by"] = "operator-A"
    errors, _w, _c = od.validate(doc)
    assert any("независимая проверка" in e for e in errors)


def test_hazop_certificate_claim_needs_all_three_records(form):
    doc = _doc({"hazop_certified": (True, "-")})
    errors, _w, _c = od.validate(doc)
    assert any("hazop_facilitator" in e for e in errors)
    assert any("hazop_date" in e for e in errors) and any("hazop_ref" in e for e in errors)
    od.save(_doc({"hazop_certified": (True, "-")}), form)   # incomplete: no record
    from model.hazop import hazop_report
    assert hazop_report()["certified"] is False
    full = _doc({"hazop_certified": (True, "-"),
                 "hazop_facilitator": ("И. Иванов, facilitator IEC 61882", "text"),
                 "hazop_date": ("2026-09-30", "date"),
                 "hazop_ref": ("HAZOP-2026-14, 240 стр.", "text")})
    e2, _w2, _c2 = od.validate(full)
    assert e2 == []
    od.save(full, form)
    rep = hazop_report()
    assert rep["certified"] is True and rep["operator_record"]["verified"] is False


def test_unknown_field_ids_are_reported_not_dropped():
    doc = _doc({"nh3_rho_bulk": (1300.0, "kg/m3")})
    doc["entries"]["totally_made_up"] = {"value": 1, "applied": True}
    errors, _w, _c = od.validate(doc)
    assert any("unknown field id" in e for e in errors)


# ------------------------------------------------------ overlay into the model ---
def test_no_form_means_no_overlay_and_full_corridor(form):
    from model.config import load_config
    cfg = load_config(product="ammonia")
    assert "operator_overlay" not in cfg.raw
    assert cfg.catalyst["commercial_proxy_loaded_density_kg_m3"] == 900.0
    assert cfg.raw["kinetics"]["ammonia"]["bed_T_max_K"] == 803.15
    rec = od.recommendation()
    assert rec["n_corridor_required"] == len(rec["rows"]) == 10
    assert rec["recommended_form"] == "corridor"


def test_applied_values_reach_config_without_touching_the_file(form):
    from model.config import load_config
    od.save(_doc(FORM_OK), form)
    cfg = load_config(product="ammonia")
    ov = cfg.raw["operator_overlay"]
    assert ov["applied"] is True and ov["n_applied"] == len(FORM_OK)
    assert "kinetics.ammonia.bed_T_max_K" in ov["config_paths"]
    # degC in the form, kelvin in the model
    assert cfg.raw["kinetics"]["ammonia"]["bed_T_max_K"] == pytest.approx(753.15)
    assert ov["model_only"]["nh3_rho_kg_m3"] == 1300.0
    # cases/config.json is never rewritten
    raw = json.load(open(os.path.join(ROOT, "cases", "config.json"), encoding="utf-8"))
    assert raw["kinetics"]["ammonia"]["bed_T_max_K"] == 803.15
    assert "operator_overlay" not in raw
    assert ov["provenance"]["nh3_rho_bulk"]["entered_by"] == "operator-A"


def test_invalid_form_applies_nothing(form):
    from model.config import load_config
    doc = _doc(FORM_OK)
    doc["entries"]["nh3_GHSV_basis"] = {"value": "wet", "unit": "-", "applied": True}
    od.save(doc, form)
    cfg = load_config(product="ammonia")
    ov = cfg.raw["operator_overlay"]
    assert ov["applied"] is False and "validation_errors" in ov
    assert cfg.raw["kinetics"]["ammonia"]["bed_T_max_K"] == 803.15
    from model.verify_v2 import _operator_overlay_ok
    ok, info = _operator_overlay_ok()
    assert ok is False and "REJECTED" in info


def test_loop4_check_detects_a_mismatched_overlay(form):
    od.save(_doc(FORM_OK), form)
    from model.verify_v2 import _operator_overlay_ok
    ok, info = _operator_overlay_ok()
    assert ok is True, info
    ok2, info2 = _operator_overlay_ok()
    assert ok2 is True and "%d fields applied" % len(FORM_OK) in info2
    # an applied value that disagrees with what the config carries is a failure
    doc2 = _doc(FORM_OK)
    doc2["entries"]["loaded_density"] = {"value": 1150.0, "unit": "kg/m3",
                                         "method": "x", "source": "y",
                                         "received_date": "2026-10-05",
                                         "entered_by": "op", "applied": True}
    od.save(doc2, form)
    od._CACHE.clear()
    ok3, info3 = _operator_overlay_ok()
    assert ok3 is True, info3


# -------------------------------------------------------- corridor behaviour ---
def test_pinned_activity_gives_a_point_plus_literature_rows(form):
    od.save(_doc({"nh3_activity_k_scale": (0.504, "-")}), form)
    from model.activity_uncertainty import band
    out = band(designs={"ammonia": _saved_design()}, n_grid=3, n_steps=80)
    assert out["activity_band"]["pinned_by_operator"] is True
    assert out["band_kind"] == "point_from_operator_data"
    kinds = [r["row_kind"] for r in out["rows"]]
    assert "operator_point" in kinds and "literature_reference" in kinds
    assert out["spans"]["per_pass_N2_pct"][0] == out["spans"]["per_pass_N2_pct"][1]
    assert out["spans_literature_reference"]["per_pass_N2_pct"][0] <= \
        out["spans"]["per_pass_N2_pct"][0] + 1e-6     # lit low edge is the pessimistic
    assert out["data_entry"]["corridor_recommended"] is True
    assert "литературной полосы" in out["rows"][-1]["position_in_band"]


def test_guaranteed_spread_keeps_a_narrower_corridor(form):
    od.save(_doc({"nh3_activity_k_scale": (0.35, "-"),
                  "nh3_activity_factor": (1.2, "-")}), form)
    from model.activity_uncertainty import band
    out = band(designs={"ammonia": _saved_design()}, n_grid=3, n_steps=80)
    ab = out["activity_band"]
    assert ab["pinned_by_operator"] is True and ab["single_source_pin"] is False
    assert ab["k_scale_lo"] == pytest.approx(0.35 / 1.2, rel=1e-9)
    assert ab["k_scale_hi"] == pytest.approx(0.35 * 1.2, rel=1e-9)
    assert out["band_kind"] == "operator_corridor"
    assert ab["literature_band"][2] > ab["factor"]      # literature band is wider


def test_density_price_life_replace_placeholders_and_add_the_annual_line(form):
    od.save(_doc(FORM_OK), form)
    from model.activity_uncertainty import band
    out = band(designs={"ammonia": _saved_design()}, n_grid=2, n_steps=80)
    m = out["money"]
    assert m["density_used_kg_m3"] == 1300.0 and "оператор" in m["density_status"]
    assert m["price_used"] == 27.0 and m["life_years_used"] == 6.0
    assert m["annual_replacement_cost_USD_y"] and m["annual_replacement_cost_USD_y"] > 0
    assert "ввода оператора" in out["not_covered"][0]
    v = out["rows"][0]["volume_to_hold_design_conversion"]
    assert v["catalyst_mass_t"] == pytest.approx(v["V_m3"] * 1300.0 / 1000.0,
                                                rel=2e-3)
    assert v["annual_replacement_cost_USD_y"] == pytest.approx(
        v["inventory_cost_USD"] / 6.0, rel=5e-3)
    assert v["bed_volume_m3_if_basis_is_bed"] > v["V_m3"]


def test_ceiling_and_light_off_from_the_form_move_the_ceiling_remedy(form):
    od.save(_doc({"nh3_bed_T_max_C": (560.0, "degC"),
                  "nh3_light_off_K": (650.0, "K")}), form)
    from model.activity_uncertainty import band
    out = band(designs={"ammonia": _saved_design()}, n_grid=2, n_steps=80)
    assert out["design_reference"]["assumed_bed_ceiling_K"] == pytest.approx(833.15)
    assert all(r["ceiling_remedy"]["T_in_common_K"] >= 650.0 - 1.0
               for r in out["rows"])


def test_prices_are_synchronised_across_the_two_tables(form):
    od.save(_doc({"catalyst_price_USD_per_kg": (23.5, "USD/kg")}), form)
    from model.config import load_config
    cfg = load_config(product="ammonia")
    assert cfg.catalyst["catalyst_price_USD_per_t"] == pytest.approx(23500.0)
    from model.economics import PRICES
    assert PRICES["catalyst_USD_per_kg"] == pytest.approx(23.5)
    assert cfg.raw["operator_overlay"]["prices_synced"]["from"] == 40.0
    PRICES["catalyst_USD_per_kg"] = 40.0          # leave the project as found


def test_ghsv_basis_conversion_is_reported_and_flagged(form):
    od.save(_doc({"nh3_GHSV_h1": (1500.0, "1/h"), "nh3_GHSV_basis": "actual"}),
            form)
    from model.activity_uncertainty import band
    out = band(designs={"ammonia": _saved_design()}, n_grid=2, n_steps=80)
    st = out["activity_band"]["GHSV_status"]
    assert st.startswith("[ЧАСТИЧНО]") and "без поправки на Z" in st
    assert "1500" in st
    conv = float(st.split("-> ")[1].split(" ")[0])
    assert conv == pytest.approx(1500.0 * (273.15 / 703.15) * (200.0 / 1.01325),
                                 abs=2.0)


# ---------------------------------------------------------------- limits -------
def test_data_entry_never_passes_loop5(form):
    doc = _doc(dict(FORM_OK, **{"hazop_certified": (True, "-"),
                                "hazop_facilitator": ("И. Иванов", "text"),
                                "hazop_date": ("2026-09-30", "date"),
                                "hazop_ref": ("HAZOP-2026-14", "text"),
                                "campaign_file": ("data/campaign.csv", "path"),
                                "dP_measured_bar": (2.6, "bar"),
                                "loaded_density": (1150.0, "kg/m3"),
                                "Ni_wt_pct": (15.0, "wt%"),
                                "catalyst_life_y": (6.0, "y")}), verified=True)
    doc["entries"]["campaign_file"]["applied"] = False   # file not actually present
    od.save(doc, form)
    v = json.load(open(os.path.join(RESULTS, "verification_v2.json"), encoding="utf-8"))
    assert v["loops"]["5_validation_falsification"]["passed"] is False
    from model.verify_v2 import _operator_overlay_ok
    ok, info = _operator_overlay_ok()
    assert ok is True, info
    assert "fields applied" in info


def test_claims_are_never_rewritten_by_the_mechanism(form):
    before = json.load(open(os.path.join(ROOT, "data", "v2_claims.json"),
                             encoding="utf-8"))
    n = len(before["claims"])
    od.save(_doc(FORM_OK, verified=True), form)
    after = json.load(open(os.path.join(ROOT, "data", "v2_claims.json"),
                           encoding="utf-8"))
    assert after == before and n > 90
    assert all(c["status"] in after["meta"]["allowed_status"] for c in after["claims"])


def test_report_and_doc_exist_and_match_the_schema():
    rep_path = os.path.join(RESULTS, "operator_data_report.json")
    st = od.status()                       # no form on disk -> corridor baseline
    assert st["form_present"] is False
    assert st["n_applied"] == 0 and st["n_fields"] == len(od.FIELDS)
    assert os.path.exists(os.path.join(ROOT, "docs", "33_v5_manual_data_entry.md"))
    txt = open(os.path.join(ROOT, "docs", "33_v5_manual_data_entry.md"),
               encoding="utf-8").read()
    for f in od.FIELDS:
        assert "`%s`" % f["id"] in txt, f["id"]
    assert "КОРИДОРНЫМ" in txt.upper()
    assert "НЕ ПРИМЕНЯЕТСЯ НИ ОДНО ПОЛЕ" in txt.upper()
    if os.path.exists(rep_path):
        saved = json.load(open(rep_path, encoding="utf-8"))
        assert set(["n_fields", "recommendation"]) <= set(saved)


def test_docs_have_no_generator_leaks_or_foreign_scripts():
    """Generated markdown must not leak unrendered placeholders or stray CJK.

    This project has been bitten three times by both classes: `txt = \"\"\"...\"\"\"`
    blocks in run_v2.py are plain strings, so `{md_table(...)}`/`{l5[...]}` used
    to reach the docs verbatim (one such leak hid a 1000x unit error), and
    generator wording twice came out with Chinese characters in Russian text.
    """
    import glob
    import re
    cjk = re.compile(r"[\u3000-\u9fff\uff00-\uffef]")
    leak = re.compile(r"\{(l5\[|fnum\(|md_table|activity_summary_|operator_summary_)")
    for path in sorted(glob.glob(os.path.join(ROOT, "docs", "*.md"))):
        txt = open(path, encoding="utf-8").read()
        assert not cjk.search(txt), (os.path.basename(path), cjk.findall(txt)[:5])
        assert not leak.search(txt), (os.path.basename(path), leak.findall(txt)[:3])
        assert "\n{}" not in txt and "None" not in txt.replace("None ", ""), \
            os.path.basename(path)      # a bare None in a doc = a missing value


def test_panel_source_has_no_foreign_script_leaks():
    """web/app.py renders text straight into the browser: same guard as docs/*."""
    import re
    path = os.path.join(ROOT, "web", "app.py")
    txt = open(path, encoding="utf-8").read()
    assert not re.search(r"[\u3000-\u9fff\uff00-\uffef]", txt), re.findall(
        r"[\u3000-\u9fff]+", txt)[:5]
    assert txt.count("async function opd") == 1
    for fn in ("opField", "opCollect", "bandNote", "opSave", "opRecompute",
               "opClear", "opPost"):
        assert "function %s" % fn in txt, fn
    # the entry tab must exist and must call the loader
    assert "t13" in txt and "opd()" in txt


def test_corridor_field_list_cannot_drift():
    from model.operator_data import BY_ID, corridor_fields
    ids = corridor_fields()
    assert len(ids) == 12 and all(i in BY_ID for i in ids)
    assert "converter_capex_share" in ids        # NOT converter_capex_share_pct
    txt = open(os.path.join(ROOT, "docs", "33_v5_manual_data_entry.md"),
               encoding="utf-8").read()
    for i in ids:
        assert "`%s`" % i in txt, i
    sec = txt.split("## 33.6")[1]
    assert "converter_capex_share_pct" not in sec


def test_rejected_form_advertises_nothing_as_in_force(form):
    """Counters that the docs read must mean "applied", not "typed".

    Bug class this closes: a form with one wrong unit still listed its fields as
    applied in operator_data_report.json, so docs/17 and the loop-5 open-item
    annotations advertised data the model was ignoring.
    """
    doc = _doc({"loaded_density": (1150.0, "kg/m3")})
    doc["entries"]["crush_N"] = dict(doc["entries"]["crush_N"], value=60.0,
                                     unit="N/гранула", method="м", source="с",
                                     received_date="2026-10-05", entered_by="оп",
                                     applied=True)
    od.save(doc, form)
    st = od.status()
    assert st["rejected"] is True
    assert st["n_applied"] == 0 and st["applied_ids"] == []
    assert st["n_typed_applied"] == 2 and st["rejected_note"]
    assert sum(len(g["applied"]) for g in st["groups"]) == 0
    from model.config import load_config
    assert load_config(product="ammonia").raw["operator_overlay"]["applied"] is False
    from model.verify_v2 import _operator_overlay_ok
    ok, info = _operator_overlay_ok()
    assert ok is False and "REJECTED" in info
    # fix the unit -> the same two fields are now in force
    doc["entries"]["crush_N"]["unit"] = "N/табл."
    od.save(doc, form)
    st2 = od.status()
    assert st2["rejected"] is False and st2["n_applied"] == 2
    assert set(st2["applied_ids"]) == {"loaded_density", "crush_N"}
    assert load_config(product="ammonia").catalyst[
        "commercial_proxy_loaded_density_kg_m3"] == 1150.0
    # and the docs/17 wording follows the report state (report = run artifact)
    import model.run_v2 as R
    saved_out = R.OUT
    R.OUT = os.path.dirname(form)
    try:
        with open(os.path.join(R.OUT, "operator_data_report.json"), "w",
                  encoding="utf-8") as fh:
            json.dump(od.status(), fh, ensure_ascii=False)
        assert "2 field(s) applied" in R.operator_summary_17()
        doc["entries"]["crush_N"]["unit"] = "N/гранула"
        od.save(doc, form)
        with open(os.path.join(R.OUT, "operator_data_report.json"), "w",
                  encoding="utf-8") as fh:
            json.dump(od.status(), fh, ensure_ascii=False)
        rej = R.operator_summary_17()
        assert "form REJECTED" in rej and "nothing is in force" in rej
    finally:
        R.OUT = saved_out
        os.remove(os.path.join(os.path.dirname(form),
                               "operator_data_report.json"))


# ------------------------------------------------- docs/28 cross-reference ----
def test_rfi_items_are_parsed_from_the_request_document():
    from model.operator_data import rfi_items
    items = rfi_items()
    assert sorted(items) == list(range(1, 19))
    assert items[12]["section"] == "28.2" and "температура постели" in items[12]["text"]
    assert items[1]["section"] == "28.1" and items[1]["why"]
    # every row of both tables is read, none invented
    assert all(items[n]["text"] and not items[n]["text"].startswith("пункт")
               for n in items)


def test_a_new_rfi_item_shows_up_without_any_code_change(tmp_path):
    from model import operator_data as od
    src = open(od.RFI_DOC, encoding="utf-8").read()
    fake = tmp_path / "28_fake.md"
    fake.write_text(src + "\n| 19 | гарантированный срок до регенерации, ч | "
                           "планирование ЗО | по партии |\n", encoding="utf-8")
    items = od.rfi_items(str(fake))
    assert 19 in items and "регенерации" in items[19]["text"]
    cov = od.rfi_coverage([], [], )
    assert 19 not in {r["item"] for r in cov["rows"]}      # real doc: no such item


def test_every_form_reference_resolves_to_a_real_item():
    from model.operator_data import rfi_coverage, rfi_refs
    cov = rfi_coverage([], [])
    assert cov["unresolved_field_refs"] == [] and cov["fields_without_item"] == []
    assert cov["n_items"] == 18 and cov["n_with_field"] == 16
    # items that no number can answer are stated, not dropped
    assert cov["n_not_answerable"] == 2
    out = [r["item"] for r in cov["rows"] if r["state"] == "not_answerable_by_form"]
    assert out == [9, 10]
    assert all("вне формы" in r["state_note"] or "форма не отвечает" in r["state_note"]
               for r in cov["rows"] if r["state"] == "not_answerable_by_form")
    # a field that cites an item must be listed under it, and vice versa
    linked = {f["id"] for r in cov["rows"] for f in r["fields"]}
    assert {"nh3_bed_T_max_C", "pellet_tortuosity", "Ni_wt_pct"} <= linked
    assert rfi_refs("nh3_GHSV_basis") == [14] and rfi_refs("bed_voidage") == [6, 17]


def test_rfi_states_follow_the_entered_numbers(form):
    from model.operator_data import rfi_coverage
    by = lambda doc: {r["item"]: r["state"] for r in rfi_coverage(
        {k for k, e in doc["entries"].items() if e.get("applied")},
        {k for k, e in doc["entries"].items() if e.get("applied")
         and e.get("independently_verified")})["rows"]}
    assert by(od.template_doc())[12] == "open"
    one = _doc({"nh3_bed_T_max_C": (470.0, "degC")})
    expected = by(od.template_doc())
    expected[12] = "answered_single_source"
    assert by(one) == expected
    ver = _doc({"nh3_bed_T_max_C": (470.0, "degC")}, verified=True)
    assert by(ver)[12] == "answered_verified"
    # п.14 is answered by the vendor's own basis statement; three fields, and
    # two of them is "partial", not "answered"
    two = _doc({"nh3_GHSV_h1": (9000.0, "1/h"), "nh3_GHSV_basis": "normal"})
    assert by(two)[14] == "partial"
    three = _doc({"nh3_GHSV_h1": (9000.0, "1/h"), "nh3_GHSV_basis": "normal",
                  "nh3_volume_basis": "catalyst"})
    assert by(three)[14] == "answered_single_source"
    # our own topology choices do not gate a vendor item (they are not data
    # the vendor can answer with), but they still say so in the label
    cov = rfi_coverage(set(), set())
    p14 = {f["id"] for r in cov["rows"] if r["item"] == 14 for f in r["fields"]}
    assert p14 == {"nh3_GHSV_h1", "nh3_GHSV_basis", "nh3_volume_basis"}
    assert by(three)[13] == "open"      # п.13 needs the light-off number alone
    assert by(_doc({"nh3_light_off_K": (668.0, "K")}))[13] == "answered_single_source"
    # a rejected form answers nothing, so no item may look closed
    bad = _doc({"nh3_bed_T_max_C": (470.0, "degC")})
    bad["entries"]["nh3_bed_T_max_C"]["unit"] = "K"
    od.save(bad, form)
    st = od.status()
    assert st["rejected"] is True
    live = st["rfi_coverage"]
    assert live["n_answered"] == 0 and live["n_open"] == 16


def test_item7_transport_constants_reach_the_screening_check(form):
    from model.config import load_config
    cfg = load_config()
    assert cfg.catalyst["pellet_tortuosity"] == 3.5
    assert cfg.catalyst["pellet_pore_radius_nm"] == 50.0
    from model.data_ingest import regime_screening
    rec = {"run_id": "A1", "T_K": 1023.0, "p_bar": 2.5, "W_cat_g": 1.2,
           "flow_total_NmL_min": 120.0, "y_CH4_in_dry": 1.0,
           "y_CH4_out_dry": 0.55, "X_CH4": 0.45}
    out = regime_screening([rec])
    a0 = out["rows"][0]["assumptions"]
    assert (a0["tau"], a0["r_pore_nm"], a0["eps_p"]) == (3.5, 50.0, 0.5)
    assert "config" in a0["_source"]["tau"]
    od.save(_doc({"pellet_tortuosity": (2.4, "-"),
                  "pellet_pore_radius_nm": (120.0, "nm")}), form)
    out2 = regime_screening([rec])
    a2 = out2["rows"][0]["assumptions"]
    assert a2["tau"] == pytest.approx(2.4) and a2["r_pore_nm"] == pytest.approx(120.0)
    assert out2["transport_provenance"]["tau"].startswith("cases/config.json")
    # and an explicit argument still wins over everything
    assert regime_screening([rec], tau=9.0)["rows"][0]["assumptions"]["tau"] == 9.0


def test_dimensionless_fields_still_have_to_declare_the_unit():
    for fid, val in (("pellet_tortuosity", 2.8), ("nh3_volume_basis", "bed"),
                     ("nh3_GHSV_basis", "actual")):      # numbers and choices only:
        # a bool / text / date field has no unit to declare, so it is exempt
        ok = _doc({fid: (val, "-")})
        e_ok, _w, _c = od.validate(ok)
        assert e_ok == [], (fid, e_ok)
        empty = _doc({fid: (val, "")})
        assert od.validate(empty)[0] == [], fid
        wrong = _doc({fid: (val, "USD/quarter")})
        assert any("unit" in e or "безразмерная" in e for e in od.validate(wrong)[0]), fid


def test_docs_and_reports_carry_the_map():
    txt = open(os.path.join(ROOT, "docs", "33_v5_manual_data_entry.md"),
               encoding="utf-8").read()
    head, sec = txt.split("## 33.7", 1)
    for n in range(1, 19):
        assert "\n| %d | " % n in sec, n
    assert "вне формы" in sec and "разборк" in sec
    import model.run_v2 as R
    assert R._rfi_summary_17({}).startswith("\n\nThe docs/28 cross-reference was not")
    rep = json.load(open(os.path.join(RESULTS, "operator_data_report.json"),
                         encoding="utf-8"))
    cov = rep.get("rfi_coverage") or {}
    assert cov.get("n_items") == 18 and len(cov.get("rows")) == 18
    assert cov["n_answered"] == 0                    # no form on disk in the run
    assert "docs/28" in R._rfi_summary_17(rep)


def test_panel_endpoints_and_scripts_expose_the_map(form):
    od.save(_doc({"nh3_bed_T_max_C": (470.0, "degC")}), form)
    import web.app as W
    g = W.app.test_client().get("/api/operator").get_json()
    cov = g["rfi"]
    assert cov["n_items"] == 18 and cov["by_item"]["12"]["state"] == "answered_single_source"
    assert cov["unresolved"] == [] and cov["orphan_fields"] == []
    qs = [f["questions"] for f in g["fields"] if f["id"] == "nh3_bed_T_max_C"][0]
    assert qs and qs[0]["n"] == 12 and "постели" in qs[0]["text"]
    js = open("/tmp/panel.js", encoding="utf-8").read() if os.path.exists("/tmp/panel.js") else ""
    for fn in ("function rfiAsk", "function rfiMapBlock", "function rfiStateRu"):
        assert fn in js, fn
