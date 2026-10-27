"""V5.3 - manual data entry for every open item, with the corridor as the default.

Why this module exists
----------------------
Everything the project could not close from open literature is a NUMBER that a
person can supply: a catalyst datasheet value, a vendor converter ceiling, a
guaranteed activity, a measured pressure drop, a regional price, a real feed
analysis, a certified HAZOP record. Until a number is supplied the model is
obliged to report a CORRIDOR (V5.2, docs/32) rather than a point, because a
point would be an invention. This module is the operator's way out of the
corridor - and it is deliberately strict about it:

  * every applied value must carry unit + measurement method + source document
    + date + who entered it (docs/28 sec. 28.4: "numbers without units or
    without a method are not accepted and do not enter the model");
  * out-of-range or dimensionally implausible values are rejected, not clamped;
  * the overlay is stored in its OWN file (`data/operator_inputs.json`), never
    silently written into `cases/config.json`; `model/config.py` applies it as
    `adjust` entries at load time, so the whole project uses the entered value
    and `cfg.raw["operator_overlay"]` records exactly what was overridden;
  * a single-source entry is still [ЧАСТИЧНО]: it pins the corridor to a point
    for reporting, but `independently_verified` (a second signature / the
    protocol itself) is what would let a claim be upgraded, and this module
    never edits `data/v2_claims.json`;
  * loop 5 stays FAILED regardless: entering data is not validation.

Corridor recommendation
-----------------------
`recommendation()` answers, per quantity: "band (recommended)" while the datum
is missing, "pinned by operator - corridor shown for comparison" once it is
supplied from one source, and "pinned, independently verified" only when the
second confirmation exists. The ammonia corridor module
(`model/activity_uncertainty.py`) consumes `activity_overrides()` so the pinned
quantities - activity, bed-T ceiling, light-off floor, catalyst density, price,
life, loop dP, GHSV and its basis - are used everywhere they legitimately act.

Run:
    PYTHONPATH=. python -m model.operator_data --show          # current state
    PYTHONPATH=. python -m model.operator_data --template      # write the form
    PYTHONPATH=. python -m model.operator_data --validate      # check the file
    PYTHONPATH=. python -m model.operator_data --selftest      # built-in checks
"""
from __future__ import annotations
import copy, csv, json, math, os, re

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FORM_PATH = os.path.join(ROOT, "data", "operator_inputs.json")
TEMPLATE_JSON = os.path.join(ROOT, "data", "operator_inputs_TEMPLATE.json")
TEMPLATE_CSV = os.path.join(ROOT, "data", "operator_inputs_TEMPLATE.csv")
DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")

# ---------------------------------------------------------------- the fields ---
# targets: where the value goes in cases/config.json (dotted path) plus an
# optional unit transform; "model:<key>" entries are consumed by
# model/activity_uncertainty.py (they have no config home).
def _f(fid, group, label, unit, typ="number", lo=None, hi=None, targets=(),
       options=(), rfi="", pins="", step=None, warn=""):
    if isinstance(lo, (list, tuple)) or isinstance(hi, (list, tuple)):
        raise TypeError("field %s: a list belongs in targets=, not in lo/hi "
                        "(a positional list after typ= would be silently "
                        "misread as a range)" % fid)
    """One form field. `targets` maps an entered value onto config paths; the
    transform is a multiplier, or the tokens C2K / K2C for a temperature shift."""
    return {"id": fid, "group": group, "label": label, "unit": unit, "type": typ,
            "lo": lo, "hi": hi, "targets": list(targets), "options": list(options),
            "rfi": rfi, "pins": pins, "step": step, "warn": warn}


G1 = "1. Катализатор риформинга Ni/MgAl₂O₄ (даташит)"
G2 = "2. Катализатор синтеза NH₃ и конвертор (даташит поставщика)"
G3 = "3. Пилотная кампания и замеры на установке"
G4 = "4. Цены, площадка, экономика"
G5 = "5. Безопасность и HAZOP"
G6 = "6. Реальный анализ газа (кормовая смесь)"
G7 = "7. Конвертор и теплоинтеграция (топология)"
GROUPS = [G1, G2, G3, G4, G5, G6, G7]

FIELDS = [
    # ---- 1. reforming catalyst datasheet -----------------------------------
    _f("Ni_wt_pct", G1, "Содержание Ni (металл), после восстановления", "wt%",
       "number", 0.0, 40.0, [("catalyst.Ni_wt_pct_metal", 1.0)],
       rfi="28 п.1", pins="инвентарь Ni, масса слоя, Ni t/год"),
    _f("NiO_wt_pct", G1, "Содержание NiO (паспорт партии)", "wt%", "number",
       0.0, 60.0, [("catalyst.commercial_proxy_NiO_wt_pct", 1.0)],
       rfi="28 п.1", pins="пересчёт NiO→Ni (модель использует 0,78575)"),
    _f("loaded_density", G1, "Насыпная (загружаемая) плотность", "kg/m3",
       "number", 300.0, 2000.0, [("catalyst.commercial_proxy_loaded_density_kg_m3", 1.0)],
       rfi="28 п.2", pins="масса слоя при том же объёме; объём при той же массе"),
    _f("support_note", G1, "Фаза носителя, MgO/Al₂O₃ мольн., свободная MgO",
       "text", "text", targets=[("catalyst.support_note", 1.0)], rfi="28 п.3",
       pins="склонность к коксованию (в модели не считается — только отметка)"),
    _f("crush_N", G1, "Прочность на раздавливание, средняя", "N/табл.",
       "number", 0.0, 5000.0, [("model.reformer_crush_strength_N", 1.0)],
       rfi="28 п.4", pins="репутация Δp-расчёта (Эргун остаётся корреляцией)"),
    _f("attrition_pct", G1, "Истираемость", "%", "number", 0.0, 10.0,
       [("model.reformer_attrition_pct", 1.0)], rfi="28 п.5"),
    _f("pellet_d_eq_mm", G1, "Эквивалентный диаметр гранулы", "mm", "number",
       0.5, 50.0, [("equipment.pellet_d_m", 1e-3)], rfi="28 п.6",
       pins="Δp слоя (Эргун) и число Вейса–Пратера"),
    _f("bed_voidage", G1, "Порозность слоя", "-", "number", 0.2, 0.7,
       [("equipment.bed_voidage", 1.0)], rfi="28 п.6/7", pins="Δp и V_bed↔V_cat"),
    _f("reformer_T_max_C", G1, "Максимальная рабочая температура постели",
       "degC", "number", 400.0, 1400.0,
       [("model.reformer_bed_T_max_K", "C2K"), ("model.reformer_bed_T_max_C", 1.0)],
       rfi="28 п.8", pins="проверка T_out реформера 1123 K на допустимость"),
    _f("deactivation_pct_1000h", G1, "Гарантированная потеря активности",
       "%/1000h", "number", 0.0, 100.0,
       [("model.reformer_deactivation_pct_per_1000h", 1.0)], rfi="28 п.11",
       pins="ресурс слоя (сейчас 4 года — допущение)"),
    _f("catalyst_life_y", G1, "Гарантийный ресурс слоя", "y", "number", 0.5, 15.0,
       [("catalyst.life_years", 1.0)], rfi="28 п.11",
       pins="Ni t/год, catalyst t/год, OPEX-строка замены"),
    _f("catalyst_price_USD_per_kg", G1, "Цена катализатора риформинга", "USD/kg",
       "number", 0.5, 200.0,
       [("catalyst.catalyst_price_USD_per_t", 1000.0),
        ("model.catalyst_USD_per_kg", 1.0)], rfi="28 п.11",
       pins="CAPEX/OPEX-строка катализатора",
       warn="в проекте ДВЕ цены: config 5 USD/kg (5000 USD/t) и model/economics.py "
            "PRICES 40 USD/kg — введите ту, что по квитанции, и модель "
            "синхронизирует обе"),
    # ---- 2. ammonia catalyst + converter ----------------------------------
    _f("nh3_activity_k_scale", G2, "Гарантийная активность: множитель k₀ "
       "(относительно 6,5e13 кмоль/(м³·ч))", "-", "number", 0.02, 5.0,
       [("model.nh3_k_scale", 1.0)], rfi="28 п.15",
       pins="ВСЁ кинетическое семейство: объём слоя, выход NH₃, Q, рецикл",
       warn="это то число, из-за которого сейчас существует коридор ×2,362; "
            "введите его ТОЛЬКО если оно взято из даташита/протокола"),
    _f("nh3_activity_factor", G2, "Гарантированный разброс активности (±множитель)",
       "-", "number", 1.0, 10.0, [("model.nh3_activity_factor", 1.0)], rfi="28 п.15",
       pins="ширина коридора после фиксации центра",
       warn="без него коридор схлопывается в точку по ОДНОМУ источнику — "
            "модель в этом случае продолжает показывать коридор 2,362 рядом"),
    _f("nh3_bed_T_max_C", G2, "Максимальная температура постели конвертора",
       "degC", "number", 200.0, 800.0,
       [("kinetics.ammonia.bed_T_max_K", "C2K"), ("model.nh3_ceiling_K", "C2K")],
       rfi="28 п.12", pins="вывод EXCEEDED/OK по пику 845 K и вся мера по потолку"),
    _f("nh3_light_off_K", G2, "Минимальная температура входа (light-off)", "K",
       "number", 450.0, 800.0, [("model.nh3_inlet_T_min_K", 1.0)], rfi="28 п.13",
       pins="возможен ли рекомендуемый вход 644 K"),
    _f("nh3_GHSV_basis", G2, "Базис GHSV у поставщика", "-", "choice",
       options=("normal", "actual"),
       targets=[("kinetics.ammonia.GHSV_basis", 1.0), ("model.nh3_GHSV_basis", 1.0)],
       rfi="28 п.14", pins="пересчёт времени контакта (ошибка V4 была ×58 именно тут)"),
    _f("nh3_GHSV_h1", G2, "GHSV (в том базисе, что указан выше)", "1/h", "number",
       200.0, 200000.0, [("kinetics.ammonia.GHSV_h1", 1.0), ("model.nh3_GHSV_h1", 1.0)],
       rfi="28 п.14", pins="объём катализатора = Q/GHSV"),
    _f("nh3_volume_basis", G2, "Что поставщик называет объёмом", "-", "choice",
       options=("catalyst", "bed"), targets=[("model.nh3_volume_basis", 1.0)],
       rfi="28 п.14",
       pins="V_bed ↔ V_cat через порозность"),
    _f("nh3_rho_bulk", G2, "Насыпная плотность катализатора синтеза NH₃", "kg/m3",
       "number", 300.0, 3000.0, [("model.nh3_rho_kg_m3", 1.0)], rfi="28 п.18",
       pins="масса слоя и стоимость инвентаря (сейчас 1775 — заполнитель из VBF)"),
    _f("nh3_catalyst_price", G2, "Цена катализатора синтеза NH₃", "USD/kg",
       "number", 0.5, 200.0, [("model.nh3_catalyst_USD_per_kg", 1.0)], rfi="28 п.13/18",
       pins="инвентарь и годовая замена в коридоре"),
    _f("nh3_catalyst_life_y", G2, "Ресурс слоя конвертора", "y", "number", 0.5, 15.0,
       [("model.nh3_catalyst_life_years", 1.0)], rfi="28 п.11/15",
       pins="годовая стоимость замены (сейчас НЕ считается — нет данных)"),
    _f("nh3_dP_loop_bar", G2, "Сопротивление слоя / Δp контура рецикла", "bar",
       "number", 0.05, 20.0, [("model.dp_loop_bar", 1.0), ("equipment.dP_max_bar", 1.0)],
       rfi="28 п.17", pins="мощность рециклового компрессора и OPEX-дельта"),
    _f("nh3_impurity_limit", G2, "Предел примесей (O₂, H₂O, CO, CO₂, S) — текстом",
       "text", "text", targets=[("model.nh3_impurity_limit_note", 1.0)], rfi="28 п.16",
       pins="сверка с 5 ppm (CO+CO₂) после метанатора в модели"),
    # ---- 3. campaign / plant measurements ---------------------------------
    _f("campaign_file", G3, "Файл кампании (CSV/JSON по контракту data/pilot_schema.json)",
       "path", "path", targets=[("model.campaign_file", 1.0)], rfi="27",
       pins="контур 5: смещение модели, k₀ на наших режимах",
       warn="для кампании есть отдельный приёмник: POST /api/ingest или "
            "`python -m model.data_ingest <файл>` (49+6 полей, контракт строже формы)"),
    _f("dP_measured_bar", G3, "Измеренное Δp слоя реформера", "bar", "number",
       0.0, 20.0, [("model.reformer_dP_measured_bar", 1.0)], rfi="27 §Δp",
       pins="Эргун 2,828 бар становится сверкой, а не допущением"),
    _f("Ni_particle_nm_after", G3, "Размер частиц Ni после N часов", "nm", "number",
       0.5, 200.0, [("model.Ni_particle_nm_after", 1.0)], rfi="27 §спекание",
       pins="спекание: сейчас только 6,6 нм (свежий, лаборатория)"),
    _f("Ni_hours_after", G3, "Длительность наработки для предыдущего пункта", "h",
       "number", 1.0, 200000.0, [("model.Ni_hours_after", 1.0)], rfi="27 §спекание"),
    _f("T_wall_measured_C", G3, "Измеренная температура стенки трубы (макс.)",
       "degC", "number", 200.0, 1400.0, [("model.T_wall_measured_C", 1.0)],
       rfi="27", pins="проверка LMP/ползучести по факту, а не по расчёту"),
    # ---- 4. prices / site --------------------------------------------------
    _f("gas_price", G4, "Природный газ", "USD/MMBtu", "number", 0.2, 100.0,
       [("economics.gas_USD_per_MMBtu", 1.0)], pins="OPEX-топливо, себестоимость"),
    _f("electricity_price", G4, "Электроэнергия", "USD/MWh", "number", 1.0, 1000.0,
       [("economics.electricity_USD_per_MWh", 1.0)], pins="компрессоры, ASU, электро-СМR"),
    _f("CO2_price", G4, "CO₂ (квота/продажа)", "USD/t", "number", -100.0, 500.0,
       [("economics.CO2_USD_per_t", 1.0)], pins="стоимость выбросов"),
    _f("steam_price", G4, "Пар", "USD/t", "number", 0.0, 300.0,
       [("economics.steam_USD_per_t", 1.0)]),
    _f("water_price", G4, "Оборотная вода", "USD/m3", "number", 0.0, 5.0,
       [("economics.cooling_water_USD_per_m3", 1.0)]),
    _f("Ni_price", G4, "Никель", "USD/t", "number", 3000.0, 200000.0,
       [("catalyst.Ni_price_USD_per_t", 1.0)], pins="стоимость Ni-догрузки"),
    _f("CAPEX_per_kW", G4, "CAPEX на кВт H₂ (LHV)", "USD/kW", "number", 100.0, 5000.0,
       [("economics.CAPEX_USD_per_kW_H2_LHV", 1.0)], pins="вся масштабированная CAPEX-база"),
    _f("converter_capex_share", G4, "Доля конвертора NH₃ в CAPEX установки", "%",
       "number", 0.0, 60.0, [("model.nh3_capex_share_pct", 1.0)],
       pins="абсолютная дельта CAPEX из коридора (сейчас только множитель (V/V₀)^0,7)"),
    _f("discount_rate", G4, "Ставка дисконтирования", "-", "number", 0.0, 0.4,
       [("economics.discount_rate", 1.0)]),
    _f("plant_life_y", G4, "Срок службы установки", "y", "number", 5.0, 45.0,
       [("economics.plant_life_years", 1.0)]),
    _f("hours_per_year", G4, "Часов в году", "h/y", "number", 1000.0, 8784.0,
       [("economics.operating_hours_per_year", 1.0)], pins="тоннажи, OPEX, кВт·ч"),
    # ---- 5. safety / HAZOP -------------------------------------------------
    _f("hazop_certified", G5, "HAZOP проведена и подписана", "-", "bool",
       targets=[("model.hazop_certified", 1.0)],
       pins="последняя незакрытая строка контура 5",
       warn="true без facilitator/даты/регистрационного номера отклоняется"),
    _f("hazop_facilitator", G5, "Фасилитатор (ФИО, квалификация)", "text", "text",
       targets=[("model.hazop_facilitator", 1.0)]),
    _f("hazop_date", G5, "Дата последнего заседания", "date", "date",
       targets=[("model.hazop_date", 1.0)]),
    _f("hazop_ref", G5, "Регистрационный номер / архив отчёта", "text", "text",
       targets=[("model.hazop_ref", 1.0)]),
    _f("psv_set_factor", G5, "Коэффициент уставки ПСК (1,1 по API 520)", "-",
       "number", 1.0, 1.5, [("safety.relief.p_set_factor", 1.0)],
       warn="полный текст API 520/521 в проекте не открыт — это выбор, а не цитата"),
    _f("NiCO4_kinetics", G5, "Кинетика Ni(CO)₄ (константа скорости, ссылка)", "text",
       "text", targets=[("model.NiCO4_kinetics_note", 1.0)]),
    # ---- 6. real feed analysis --------------------------------------------
    _f("feed_CH4", G6, "CH₄ в сухом газе", "mol%", "number", 50.0, 100.0,
       [("feeds.russia_h.dry_mol_fraction.CH4", 1.0)], pins="самый сильный входной фактор"),
    _f("feed_C2H6", G6, "C₂H₆", "mol%", "number", 0.0, 20.0,
       [("feeds.russia_h.dry_mol_fraction.C2H6", 1.0)], pins="предреформер, коксование"),
    _f("feed_C3H8", G6, "C₃H₈", "mol%", "number", 0.0, 10.0,
       [("feeds.russia_h.dry_mol_fraction.C3H8", 1.0)]),
    _f("feed_CO2", G6, "CO₂", "mol%", "number", 0.0, 10.0,
       [("feeds.russia_h.dry_mol_fraction.CO2", 1.0)], pins="SN и трим CO₂ в метанол"),
    _f("feed_N2", G6, "N₂", "mol%", "number", 0.0, 10.0,
       [("feeds.russia_h.dry_mol_fraction.N2", 1.0)], pins="балласт + источник N для NH₃"),
    _f("feed_H2S", G6, "H₂S на входе", "ppmv", "number", 0.0, 50.0,
       [("feeds.russia_h.H2S_ppmv", 1.0)], pins="ZnO-ловушка, отравление Ni"),
    _f("feed_p_bar", G6, "Давление газа на площадке", "bar(a)", "number", 1.0, 120.0,
       [("feeds.russia_h.p_bar_abs", 1.0)]),
    _f("feed_T_C", G6, "Температура газа на входе", "degC", "number", -50.0, 80.0,
       [("feeds.russia_h.T_C", 1.0)]),
    # ---- 7. converter topology / heat integration --------------------------
    _f("n_beds", G7, "Число секций конвертора", "-", "int", 1, 8,
       [("kinetics.ammonia.n_beds", 1)], rfi="28 п.14", pins="профиль T и Q"),
    _f("T_in_bed_K", G7, "Температуры входа секций (список через запятую)", "K",
       "list", 450.0, 900.0, [("kinetics.ammonia.T_in_bed_K", 1.0)], rfi="28 п.13/14",
       pins="пик постели и мера по потолку"),
    _f("cold_shot", G7, "Доля холодного впрыска", "-", "number", 0.0, 0.8,
       [("kinetics.ammonia.cold_shot_fraction", 1.0)], rfi="28 п.14"),
    _f("recycle_ratio", G7, "Коэффициент рецикла контура", "-", "number", 0.0, 20.0,
       [("kinetics.ammonia.recycle_ratio", 1.0)], pins="замыкание X·(1+RR) и тоннаж"),
    _f("pinch_dT", G7, "Минимальный пч ТЭ (теплоинтеграция)", "K", "number", 5.0, 80.0,
       [("process.pinch_dT_min_K", 1.0)]),
    _f("steam_p_bar", G7, "Давление вырабатываемого пара", "bar(a)", "number", 1.0, 120.0,
       [("process.steam_p_bar_abs", 1.0)], pins="утилизации тепла (37–43 МВт)"),
    _f("approach_K", G7, "Подход к равновесию в реформере (выбор проектировщика)",
       "K", "number", 0.0, 60.0, [("__all_products_approach_K__", 1.0)],
       warn="это НЕ внешний datum: менять можно, но метка остаётся [ДОПУЩЕНИЕ]; "
            "docs/30 показывает, что это крупнейший единственный допуск проекта "
            "(±0,023 по X_CH₄)", pins="X_CH₄ и SN (через калорическую нагрузку)"),
]

BY_ID = {f["id"]: f for f in FIELDS}
PROV_KEYS = ("method", "source", "received_date", "entered_by")


# ----------------------------------------------------------------- template ---
def template_doc():
    """Empty form: every field present, nothing applied, no numbers invented."""
    ent = {}
    for f in FIELDS:
        e = {"value": None, "unit": f["unit"] if f["unit"] not in
             ("text", "date", "bool", "path", "-") else "",
             "applied": False, "independently_verified": False}
        e.update({k: "" for k in PROV_KEYS})
        ent[f["id"]] = e
    return {"version": 1, "selftest": False,
            "note": ("Заполняется ЧЕЛОВЕКОМ. applied=true без unit/method/source/"
                     "received_date/entered_by отклоняется валидатором; числа "
                     "вне диапазона отклоняются, а не обрезаются. Модель при "
                     "отсутствии значения продолжает показывать коридор "
                     "(docs/32), а не точку."),
            "entries": ent}


def write_template():
    doc = template_doc()
    os.makedirs(os.path.dirname(TEMPLATE_JSON), exist_ok=True)
    with open(TEMPLATE_JSON, "w", encoding="utf-8") as fh:
        json.dump(doc, fh, ensure_ascii=False, indent=1)
    with open(TEMPLATE_CSV, "w", encoding="utf-8", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["group", "id", "label", "unit", "value", "method", "source",
                    "received_date", "entered_by", "applied", "independently_verified",
                    "rfi_item", "pins", "range_lo", "range_hi", "options", "warn"])
        for f in FIELDS:
            w.writerow([f["group"], f["id"], f["label"], f["unit"], "", "", "", "", "",
                        "false", "false", f["rfi"], f["pins"],
                        "" if f["lo"] is None else f["lo"],
                        "" if f["hi"] is None else f["hi"],
                        "|".join(f["options"]), f["warn"]])
    return TEMPLATE_JSON, TEMPLATE_CSV, len(FIELDS)


# ---------------------------------------------------------------- validation ---
def _num(f, v):
    """Coerce + range-check one numeric/list value. Returns (value, error)."""
    if f["type"] == "list":
        try:
            parts = [float(x) for x in re.split(r"[,; ]+", str(v).strip()) if x]
        except ValueError:
            return None, "list of numbers expected"
        if not parts:
            return None, "empty list"
        for x in parts:
            if not (f["lo"] <= x <= f["hi"]):
                return None, "%g outside [%g, %g] %s" % (x, f["lo"], f["hi"], f["unit"])
        return parts, None
    try:
        x = float(v)
    except (TypeError, ValueError):
        return None, "not a number"
    if not math.isfinite(x):
        return None, "not finite"
    if f["type"] == "int" and abs(x - round(x)) > 1e-9:
        return None, "integer expected, got %r" % (v,)
    if not (f["lo"] <= x <= f["hi"]):
        return None, "%g outside [%g, %g] %s" % (x, f["lo"], f["hi"], f["unit"])
    return (int(round(x)) if f["type"] == "int" else x), None


def validate(doc):
    """Strict validator. Returns (errors, warnings, cleaned_entries)."""
    errors, warnings, clean = [], [], {}
    if not isinstance(doc, dict) or not isinstance(doc.get("entries"), dict):
        return ["root must be an object with an 'entries' object"], [], {}
    unknown = [k for k in doc["entries"] if k not in BY_ID]
    for k in unknown:
        errors.append("unknown field id %r (form fields are fixed - see docs/33)" % k)
    for f in FIELDS:
        e = doc["entries"].get(f["id"])
        if e is None:
            continue
        if not isinstance(e, dict):
            errors.append("%s: entry must be an object" % f["id"])
            continue
        f_e = copy.deepcopy(e)
        applied = bool(e.get("applied"))
        v = e.get("value")
        empty = v is None or (isinstance(v, str) and not v.strip())
        if empty:
            if applied:
                errors.append("%s: applied=true без значения" % f["id"])
            clean[f["id"]] = f_e
            continue
        if f["type"] in ("number", "int", "list"):
            val, err = _num(f, v)
            if err:
                errors.append("%s: %s" % (f["id"], err))
            else:
                f_e["value"] = val
        elif f["type"] == "choice":
            if str(v).strip() not in f["options"]:
                errors.append("%s: value %r not in %s" % (f["id"], v, list(f["options"])))
            else:
                f_e["value"] = str(v).strip()
        elif f["type"] == "bool":
            if isinstance(v, bool):
                f_e["value"] = v
            elif str(v).strip().lower() in ("true", "1", "да", "yes"):
                f_e["value"] = True
            elif str(v).strip().lower() in ("false", "0", "нет", "no"):
                f_e["value"] = False
            else:
                errors.append("%s: not a boolean" % f["id"])
        elif f["type"] == "date":
            if not DATE_RE.match(str(v).strip()):
                errors.append("%s: date must be YYYY-MM-DD, got %r" % (f["id"], v))
            else:
                f_e["value"] = str(v).strip()
        else:                                    # text / path
            f_e["value"] = str(v).strip()
            if f["type"] == "path" and applied:
                p = f_e["value"]
                full = p if os.path.isabs(p) else os.path.join(ROOT, p)
                if not os.path.exists(full):
                    errors.append("%s: файл не найден (%s)" % (f["id"], p))
        if applied:
            u = f["unit"]
            if u not in ("text", "date", "bool", "path", "-"):
                if str(f_e.get("unit") or "").strip() != u:
                    errors.append("%s: unit должно быть ровно %r (числа без единиц "
                                  "или с другой единицей в модель не попадают)"
                                  % (f["id"], u))
            for k in PROV_KEYS:
                if not str(f_e.get(k) or "").strip():
                    errors.append("%s: applied=true требует заполненное поле %r"
                                  % (f["id"], k))
            rd = str(f_e.get("received_date") or "").strip()
            if rd and not DATE_RE.match(rd):
                errors.append("%s: received_date должно быть YYYY-MM-DD" % f["id"])
            if f_e.get("independently_verified"):
                ver = str(f_e.get("verified_by") or "").strip()
                if not ver:
                    errors.append("%s: independently_verified=true требует "
                                  "'verified_by' (вторая подпись / протокол)" % f["id"])
                elif ver == str(f_e.get("entered_by") or "").strip():
                    errors.append("%s: independently_verified=true, но verified_by "
                                  "совпадает с entered_by - это не независимая "
                                  "проверка" % f["id"])
            if f["warn"]:
                warnings.append("%s: %s" % (f["id"], f["warn"]))
        clean[f["id"]] = f_e
    # cross-field rules
    tot = 0.0
    for fid in ("feed_CH4", "feed_C2H6", "feed_C3H8", "feed_CO2", "feed_N2"):
        e = clean.get(fid) or {}
        if e.get("applied") and isinstance(e.get("value"), (int, float)):
            tot += e["value"]
    if tot > 0.0:
        if tot > 100.0 + 1e-6:
            errors.append("feed_*: сумма введённых mol%% = %.3f > 100" % tot)
        elif tot < 99.0:
            warnings.append("feed_*: сумма введённых mol%% = %.3f (остальное — "
                            "неучтённые компоненты; модель их не изобретает)" % tot)
    if (clean.get("hazop_certified") or {}).get("value") is True and \
            (clean.get("hazop_certified") or {}).get("applied"):
        for need in ("hazop_facilitator", "hazop_date", "hazop_ref"):
            e = clean.get(need) or {}
            if not e.get("applied") or not str(e.get("value") or "").strip():
                errors.append("hazop_certified=true требует заполненное %s" % need)
    if (clean.get("nh3_activity_k_scale") or {}).get("applied") and \
            not (clean.get("nh3_activity_factor") or {}).get("applied"):
        warnings.append("nh3_activity_k_scale введено без nh3_activity_factor: "
                        "коридор схлопнут в точку по одному источнику; модель "
                        "продолжает показывать рекомендованный коридор ×2,362 "
                        "рядом с точкой")
    return errors, warnings, clean


# --------------------------------------------------------------------- I/O ----
def load(path=None):
    path = path or FORM_PATH
    if not os.path.exists(path):
        return None
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


def validate_csv_rows(rows):
    """Accept a spreadsheet edit of the CSV template -> JSON form document."""
    doc = template_doc()
    for r in rows:
        fid = (r.get("id") or "").strip()
        if fid not in BY_ID:
            # keep it so validate() reports the typo instead of dropping data
            doc["entries"][fid] = {"value": r.get("value"), "applied": True,
                                   "unit": r.get("unit") or "", "method": "",
                                   "source": "", "received_date": "", "entered_by": ""}
            continue
        e = doc["entries"][fid]
        for k in ("unit", "method", "source", "received_date", "entered_by",
                  "verified_by"):
            if r.get(k):
                e[k] = str(r[k]).strip()
        for k in ("applied", "independently_verified"):
            if str(r.get(k) or "").strip().lower() in ("true", "1", "да", "yes"):
                e[k] = True
        v = r.get("value")
        if v is not None and str(v).strip() != "":
            e["value"] = str(v).strip()
    return doc


def save(doc, path=None):
    path = path or FORM_PATH
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(doc, fh, ensure_ascii=False, indent=1)
    return path


def clear(path=None):
    path = path or FORM_PATH
    if os.path.exists(path):
        os.remove(path)
        return True
    return False


# ------------------------------------------------------------ config overlay ---
def adjust_map(clean):
    """Dotted-path overrides for cases/config.json + model-only entries."""
    adj, model_over = {}, {}
    for fid, e in clean.items():
        if not e.get("applied") or e.get("value") is None:
            continue
        f = BY_ID[fid]
        for path, scale in f["targets"]:
            v = e["value"]
            if isinstance(v, bool) or f["type"] in ("text", "date", "path",
                                                     "choice", "bool"):
                out = v
            elif isinstance(v, list):
                out = v
            elif scale == "C2K":
                out = v + 273.15
            elif scale == "K2C":
                out = v - 273.15
            else:
                out = v * scale if scale != 1.0 else v
            if path == "__all_products_approach_K__":
                adj["__approach_K_all__"] = out
            elif path.startswith("model."):
                model_over[path.split(".", 1)[1]] = out
            else:
                adj[path] = out
        if e.get("independently_verified"):
            model_over.setdefault("_verified", {})[fid] = True
    return adj, model_over


def runtime_overlay():
    """Applied values from the saved form, as a plain dict for the corridor and
    for the two price tables. Returns {} when there is no form."""
    doc = load()
    if not doc:
        return {}
    errors, warnings, clean = validate(doc)
    if errors:
        # all-or-nothing, everywhere: a form with any error is not a data source
        # for the corridor, HAZOP or the price tables either - see docs/33.
        return {"_errors": errors, "_warnings": warnings, "_applied_ids": [],
                "_verified_ids": [], "_provenance": {}, "_clean": {},
                "_rejected": True}
    _adj, over = adjust_map(clean)
    over["_clean"] = clean
    over["_errors"] = errors
    over["_warnings"] = warnings
    over["_applied_ids"] = sorted(fid for fid, e in clean.items() if e.get("applied"))
    over["_verified_ids"] = sorted(fid for fid, e in clean.items()
                                   if e.get("applied") and e.get("independently_verified"))
    over["_provenance"] = {fid: {k: clean[fid].get(k) for k in
                                PROV_KEYS + ("independently_verified", "verified_by")}
                           for fid in over["_applied_ids"]}
    return over


def sync_prices():
    """Keep model/economics.py PRICES and config catalyst price in step with an
    applied catalyst price. Returns a note for the report (None if nothing to do)."""
    over = runtime_overlay()
    price = over.get("catalyst_USD_per_kg")
    if price is None:
        return None
    from .economics import PRICES
    old = PRICES.get("catalyst_USD_per_kg")
    PRICES["catalyst_USD_per_kg"] = float(price)
    return {"from": old, "to": float(price),
            "note": ("PRICES['catalyst_USD_per_kg'] переопределён вводом оператора; "
                     "конфликт двух цен в проекте (config 5 USD/kg против PRICES 40 "
                     "USD/kg) решён в пользу квитанции поставщика")}


def apply_to_config(cfg):
    """Apply the operator overlay onto a Config object (used by model/config.py).

    Returns the list of dotted paths actually written, so `cfg` can carry the
    provenance record `operator_overlay` and nothing is invisible.
    """
    over = runtime_overlay()
    if not over:
        return []
    adj, model_over = adjust_map(over["_clean"])
    applied = []
    raw = cfg.raw
    for path, v in adj.items():
        if path == "__approach_K_all__":
            for p in (raw.get("products") or {}).values():
                p["approach_K"] = v
            applied.append("products.*.approach_K")
            continue
        node = raw
        parts = path.split(".")
        for part in parts[:-1]:
            node = node.setdefault(part, {})
        node[parts[-1]] = v
        applied.append(path)
    raw["operator_overlay"] = {
        "file": os.path.relpath(FORM_PATH, ROOT),
        "applied_config_paths": sorted(applied),
        "model_only": {k: v for k, v in model_over.items() if not k.startswith("_")},
        "n_applied": len(over.get("_applied_ids", [])),
        "n_verified": len(over.get("_verified_ids", [])),
        "provenance": over.get("_provenance", {}),
        "validation_errors": over.get("_errors", []),
        "validation_warnings": over.get("_warnings", []),
    }
    return sorted(applied)


# --------------------------------------------------------- config hook -------
_CACHE = {}          # (path, mtime_ns, size) -> (adjust, meta)


def overlay_adjust(path=None):
    """The operator overlay as (dotted_adjust_map, meta) - cached on file stat.

    Called by model/config.py on every load_config(), so an entered value is used
    by the whole project without editing cases/config.json by hand (docs/28
    sec. 28.4 keeps config as the single source, this overlay is the audited
    exception to that rule). Returns ({}, None) when no form exists or it does
    not validate - a broken form must never half-apply.

    Side effect, recorded in `meta`: if a catalyst price was entered, the
    screening price in model/economics.py (PRICES) is synchronised to it, so the
    two conflicting project prices agree.
    """
    path = path or FORM_PATH
    if not os.path.exists(path):
        return {}, None
    st = os.stat(path)
    key = (path, st.st_mtime_ns, st.st_size)
    if key in _CACHE:
        return _CACHE[key]
    with open(path, encoding="utf-8") as fh:
        doc = json.load(fh)
    errors, warnings, clean = validate(doc)
    if errors:
        out = ({}, {"file": os.path.relpath(path, ROOT), "applied": False,
                    "reason": "форма не прошла валидацию - ничего не применяется",
                    "validation_errors": errors, "validation_warnings": warnings})
        _CACHE.clear()
        _CACHE[key] = out
        return out
    adj, model_over = adjust_map(clean)
    # keep the two project price tables consistent when a price was entered
    price = model_over.get("catalyst_USD_per_kg")
    prices_synced = None
    if price is not None:
        try:
            from .economics import PRICES
            prices_synced = {"from": PRICES.get("catalyst_USD_per_kg"),
                             "to": float(price)}
            PRICES["catalyst_USD_per_kg"] = float(price)
        except Exception as exc:                        # pragma: no cover
            prices_synced = {"error": repr(exc)}
    meta = {"file": os.path.relpath(path, ROOT), "applied": True,
            "n_applied": sum(1 for e in clean.values() if e.get("applied")),
            "n_verified": sum(1 for e in clean.values()
                              if e.get("applied") and e.get("independently_verified")),
            "config_paths": sorted(adj),
            "model_only": {k: v for k, v in model_over.items()},
            "provenance": {fid: {k: clean[fid].get(k) for k in
                                 PROV_KEYS + ("independently_verified", "verified_by")}
                           for fid, e in clean.items() if e.get("applied")},
            "validation_warnings": warnings,
            "prices_synced": prices_synced,
            "selftest": bool(doc.get("selftest"))}
    _CACHE.clear()
    _CACHE[key] = (adj, meta)
    return adj, meta


# ------------------------------------------------------- corridor interface ---
CORRIDOR_DIMS = (
    ("nh3_activity_k_scale", "центр полосы активности k_scale",
     "коридор 0,2134…0,5040 (×2,362)"),
    ("nh3_activity_factor", "ширина полосы активности", "×2,362 от двух источников"),
    ("nh3_bed_T_max_C", "потолок T постели конвертора", "803,15 K [ДОПУЩЕНИЕ]"),
    ("nh3_light_off_K", "минимум входа секции (light-off)", "600 K в бисекции"),
    ("nh3_rho_bulk", "плотность катализатора NH₃", "1775 кг/м³ (заполнитель VBF)"),
    ("nh3_catalyst_price", "цена катализатора NH₃", "40 USD/kg (скрининг Ni/MgAl₂O₄)"),
    ("nh3_catalyst_life_y", "ресурс слоя конвертора", "нет — годовая замена не считается"),
    ("nh3_dP_loop_bar", "Δp контура рецикла", "1 / 2 / 3 бар (предположение)"),
    ("nh3_GHSV_h1", "GHSV (объём слоя)", "10 000 ч⁻¹ (проект)"),
    ("nh3_GHSV_basis", "базис GHSV", "normal (проект)"),
)


def recommendation():
    """Per quantity: is the corridor still required, or pinned by an operator?

    This is the single answer to 'what should I put in the report': the corridor
    is ALWAYS the recommended form until a datum arrives WITH provenance; a
    single-source entry pins the point but the corridor is kept beside it.
    """
    over = runtime_overlay()
    rows = []
    for fid, what, current in CORRIDOR_DIMS:
        v = over.get({"nh3_activity_k_scale": "nh3_k_scale",
                      "nh3_activity_factor": "nh3_activity_factor",
                      "nh3_bed_T_max_C": "nh3_ceiling_K",
                      "nh3_light_off_K": "nh3_inlet_T_min_K",
                      "nh3_rho_bulk": "nh3_rho_kg_m3",
                      "nh3_catalyst_price": "nh3_catalyst_USD_per_kg",
                      "nh3_catalyst_life_y": "nh3_catalyst_life_years",
                      "nh3_dP_loop_bar": "dp_loop_bar",
                      "nh3_GHSV_h1": "nh3_GHSV_h1",
                      "nh3_GHSV_basis": "nh3_GHSV_basis"}[fid])
        verified = fid in over.get("_verified_ids", [])
        rows.append({"field": fid, "quantity": what,
                     "model_value_now": current,
                     "operator_value": v,
                     "state": ("pinned_and_verified" if verified else
                               "pinned_single_source" if v is not None else
                               "corridor_required"),
                     "report_as": ("точка (проверена независимо)" if verified else
                                   "точка + коридор рядом (один источник — "
                                   "рекомендуется коридор)" if v is not None else
                                   "ТОЛЬКО коридор (рекомендуется)")})
    n_open = sum(1 for r in rows if r["state"] == "corridor_required")
    return {"rows": rows, "n_corridor_required": n_open, "n_pinned": len(rows) - n_open,
            "recommended_form": ("corridor" if n_open else "point_with_corridor"),
            "note": ("пока хотя бы один размер не введён с провенансом, отчёт "
                     "обязан быть коридорным; введённое по одному источнику "
                     "фиксирует точку, но коридор остаётся в скобках")}


# model.* keys that model/activity_uncertainty.py consumes directly (corridor):
_CORRIDOR_MODEL_KEYS = ("nh3_k_scale", "nh3_activity_factor", "nh3_rho_kg_m3",
                        "nh3_catalyst_USD_per_kg", "nh3_catalyst_life_years",
                        "nh3_ceiling_K", "nh3_inlet_T_min_K", "nh3_GHSV_h1",
                        "nh3_GHSV_basis", "nh3_volume_basis", "nh3_capex_share_pct",
                        "dp_loop_bar")


def corridor_fields():
    """Field ids whose entered value the ammonia corridor reads directly.

    Derived from the fields' own `model.*` targets, so docs/33 cannot name an id
    that does not exist (it happened once with `converter_capex_share_pct`).
    """
    ids = []
    for f in FIELDS:
        for path, _scale in f["targets"]:
            if path.startswith("model.") and \
                    path.split(".", 1)[1] in _CORRIDOR_MODEL_KEYS:
                ids.append(f["id"])
                break
    return ids


def activity_overrides():
    """What model/activity_uncertainty.py must use instead of its placeholders."""
    over = runtime_overlay()
    out = {}
    k = over.get("nh3_k_scale")
    fac = over.get("nh3_activity_factor")
    if k is not None:
        out["k_center"] = float(k)
        out["k_factor"] = float(fac) if fac else 1.0
    for src, dst in (("nh3_rho_kg_m3", "rho_kg_m3"),
                     ("nh3_catalyst_USD_per_kg", "price_USD_per_kg"),
                     ("nh3_catalyst_life_years", "life_years"),
                     ("nh3_ceiling_K", "ceiling_K"),
                     ("nh3_inlet_T_min_K", "inlet_T_min_K"),
                     ("nh3_GHSV_h1", "GHSV_h1"),
                     ("nh3_GHSV_basis", "GHSV_basis"),
                     ("nh3_volume_basis", "volume_basis"),
                     ("nh3_capex_share_pct", "capex_share_pct")):
        if over.get(src) is not None:
            out[dst] = over[src]
    dp = over.get("dp_loop_bar")
    if dp is not None:
        out["dp_loop_bar"] = [float(dp)]
    out["provenance"] = {fid: over["_provenance"][fid] for fid in
                         over.get("_applied_ids", []) if fid in over.get("_provenance", {})}
    out["verified_ids"] = over.get("_verified_ids", [])
    return out


# ---------------------------------------------------------------- report ------
def status():
    """Full status of manual data entry: coverage per group + what it pins."""
    doc = load()
    if not doc:
        return {"form_present": False, "n_fields": len(FIELDS),
                "n_applied": 0, "n_verified": 0, "groups": [],
                "applied_ids": [], "verified_ids": [],
                "validation_errors": [], "validation_warnings": [],
                "how_to_start": ("скопируйте data/operator_inputs_TEMPLATE.json в "
                                 "data/operator_inputs.json и заполните "
                                 "значения+провенанс, либо введите через панель "
                                 "(вкладка «Ручной ввод данных»); до этого модель "
                                 "обязана показывать коридор (docs/32)"),
                "recommendation": recommendation()}
    errors, warnings, clean = validate(doc)
    groups = []
    for g in GROUPS:
        ids = [f["id"] for f in FIELDS if f["group"] == g]
        applied = [i for i in ids if (clean.get(i) or {}).get("applied")]
        groups.append({"group": g, "n_fields": len(ids),
                       "n_applied": len(applied if not errors else []),
                       "n_typed": len(applied),
                       "applied": (applied if not errors else []),
                       "open": [i for i in ids if i not in applied]})
    adj, model_over = adjust_map(clean)
    rec = recommendation()
    # A form with ANY error is not applied anywhere (all-or-nothing), so the
    # counters that mean "in force" must read zero - otherwise docs/17, docs/32
    # and the loop-5 annotations would advertise entered data that the model is
    # in fact ignoring.  What the operator typed stays under n_typed_*.
    typed_applied = sorted(fid for fid in clean if clean[fid].get("applied"))
    typed_verified = sorted(fid for fid in clean
                            if clean[fid].get("applied")
                            and clean[fid].get("independently_verified"))
    in_force = [] if errors else typed_applied
    in_force_verified = [] if errors else typed_verified
    rep = {"form_present": True, "selftest": bool(doc.get("selftest")),
           "n_fields": len(FIELDS), "n_applied": len(in_force),
           "n_verified": len(in_force_verified),
           "n_typed_applied": len(typed_applied),
           "n_typed_verified": len(typed_verified),
           "rejected": bool(errors),
           "rejected_note": ("форма отклонена валидатором — ни одно поле не "
                             "применено; см. validation_errors" if errors else ""),
           "groups": groups, "validation_errors": errors,
           "validation_warnings": warnings,
           "applied_ids": in_force, "verified_ids": in_force_verified,
           "config_paths_written": [("__approach_K_all__" if p == "__approach_K_all__"
                                     else p) for p in sorted(adj)],
           "model_only": {k: v for k, v in model_over.items()
                          if not str(k).startswith("_")},
           "recommendation": rec,
           "loop5_note": ("ввод данных оператором НЕ закрывает контур 5: он "
                          "закрывает отдельные подпроверки только при полном "
                          "провенансе, а overall остаётся FAILED, потому что "
                          "независимой валидации модели по-прежнему нет")}
    return rep


def main(argv=None):
    import argparse
    ap = argparse.ArgumentParser(description="manual data entry for open items")
    ap.add_argument("--show", action="store_true", help="print the status report")
    ap.add_argument("--template", action="store_true", help="write empty form")
    ap.add_argument("--validate", action="store_true", help="validate the saved form")
    ap.add_argument("--clear", action="store_true", help="remove the saved form")
    ap.add_argument("--selftest", action="store_true", help="run built-in checks")
    a = ap.parse_args(argv)
    if a.template:
        j, c, n = write_template()
        print("template written: %s + %s for %d fields"
              % (os.path.relpath(j, ROOT), os.path.relpath(c, ROOT), n))
    if a.clear:
        print("removed" if clear() else "nothing to remove")
    if a.selftest:
        print(json.dumps(selftest(), ensure_ascii=False, indent=1))
    if a.validate or a.show:
        rep = status()
        print(json.dumps(rep, ensure_ascii=False, indent=1))
        return 1 if rep.get("validation_errors") else 0
    return 0


# ----------------------------------------------------------------- selftest ---
def selftest():
    """Round-trip the validator without touching data/ or inventing "real" data.

    Deliberately uses values that are obviously test material (selftest flag,
    out-of-band ranges) and only ever writes to a temporary file.
    """
    import tempfile
    out = {}
    doc = template_doc()
    err, warn, clean = validate(doc)
    out["empty_template_errors"] = err
    out["empty_template_ok"] = (err == [] and len(clean) == len(FIELDS))
    bad = copy.deepcopy(doc)
    bad["entries"]["loaded_density"] = {"value": 1e9, "unit": "kg/m3",
                                        "method": "x", "source": "y",
                                        "received_date": "2026-01-01",
                                        "entered_by": "op", "applied": True}
    bad["entries"]["nh3_GHSV_basis"] = {"value": "wet", "unit": "-", "applied": True}
    bad["entries"]["nh3_activity_k_scale"] = {"value": 0.504, "unit": "1/h",
                                              "method": "", "source": "",
                                              "received_date": "01.2026",
                                              "entered_by": "", "applied": True}
    bad["entries"]["nonexistent_field"] = {"value": 1, "applied": True}
    e1, w1, _c1 = validate(bad)
    out["bad_form_catches"] = len(e1)
    out["bad_form_expected_min"] = 6
    out["bad_form_ok"] = len(e1) >= 6
    good = copy.deepcopy(doc)
    good["selftest"] = True
    good["entries"]["nh3_rho_bulk"] = {"value": 1300, "unit": "kg/m3",
                                       "method": "ISO 6787 по партии",
                                       "source": "письмо поставщика 2026-10-01, лист 3",
                                       "received_date": "2026-10-01",
                                       "entered_by": "operator-A", "applied": True}
    good["entries"]["nh3_catalyst_life_y"] = {"value": 6, "unit": "y",
                                              "method": "гарантия",
                                              "source": "контракт 44-2026",
                                              "received_date": "2026-10-02",
                                              "entered_by": "operator-A",
                                              "independently_verified": True,
                                              "verified_by": "operator-A",
                                              "applied": True}
    e2, w2, c2 = validate(good)
    out["second_signature_rule_caught"] = any("независимая проверка" in x for x in e2)
    good["entries"]["nh3_catalyst_life_y"]["verified_by"] = "engineer-B"
    e3, w3, c3 = validate(good)
    out["clean_after_fix"] = e3
    adj, over = adjust_map(c3)
    out["adjust_map"] = adj
    out["model_only"] = {k: v for k, v in over.items() if not str(k).startswith("_")}
    fd, tmp = tempfile.mkstemp(suffix=".json")
    os.close(fd)
    try:
        save(good, tmp)
        rt = load(tmp)
        out["round_trip"] = (rt["entries"]["nh3_rho_bulk"]["value"] == 1300)
    finally:
        os.remove(tmp)
    # CSV round-trip through the spreadsheet path
    rows = [{"id": "loaded_density", "value": "1150", "unit": "kg/m3",
             "method": "ISO 6787", "source": "партия 2026-07",
             "received_date": "2026-10-05", "entered_by": "op-B", "applied": "true"},
            {"id": "junk", "value": "1"}]
    dcsv = validate_csv_rows(rows)
    e4, w4, c4 = validate(dcsv)
    out["csv_unknown_id_rejected"] = any("unknown field id" in x for x in e4)
    out["csv_adjust"] = {k: v for k, v in adjust_map(c4)[0].items()}
    out["template_files_exist"] = (os.path.exists(TEMPLATE_JSON)
                                   and os.path.exists(TEMPLATE_CSV))
    out["recommendation_all_corridors"] = all(
        r["state"] == "corridor_required" for r in recommendation()["rows"]) \
        if not load() else "form present - see status()"
    out["fields"] = len(FIELDS)
    return out


if __name__ == "__main__":
    raise SystemExit(main())
