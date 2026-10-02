"""Conservative technical comparison of one item and one source fragment.

The result describes explicit attributes, never supplier capability. Missing
values, inequalities, and ambiguous alternatives remain unknown. Original text
and spans survive; no inferred units, model substitutions, or code correction.
"""
from __future__ import annotations

from decimal import Decimal
from functools import lru_cache
import re
import unicodedata

VERSION = "explicit-evidence-v3"
NUMBER = r"(?:\d{1,3}(?:[ \u00a0\u202f]\d{3})+|\d+)(?:[.,]\d+)?"
SIGNED_NUMBER = rf"[-+−]?{NUMBER}"
# Case matters in SI prefixes: мВт is milliwatt, МВт is megawatt.
UNITS = {
    "мм": ("length", "0.001"), "mm": ("length", "0.001"),
    "см": ("length", "0.01"), "cm": ("length", "0.01"),
    "м": ("length", "1"), "m": ("length", "1"),
    "Ом": ("resistance", "1"), "ом": ("resistance", "1"),
    "Ohm": ("resistance", "1"), "ohm": ("resistance", "1"),
    "Ω": ("resistance", "1"), "кОм": ("resistance", "1000"),
    "В": ("voltage", "1"), "V": ("voltage", "1"),
    "кВ": ("voltage", "1000"), "kV": ("voltage", "1000"),
    "мВ": ("voltage", "0.001"), "mV": ("voltage", "0.001"),
    "Вт": ("power", "1"), "W": ("power", "1"),
    "кВт": ("power", "1000"), "kW": ("power", "1000"),
    "мВт": ("power", "0.001"), "mW": ("power", "0.001"),
    "МВт": ("power", "1000000"), "MW": ("power", "1000000"),
    "мл": ("volume", "0.001"), "ml": ("volume", "0.001"),
    "л": ("volume", "1"), "l": ("volume", "1"),
    "мг": ("mass", "0.001"), "mg": ("mass", "0.001"),
    "г": ("mass", "1"), "g": ("mass", "1"),
    "кг": ("mass", "1000"), "kg": ("mass", "1000"),
    "ГБ": ("decimal_storage", "1000000000"), "GB": ("decimal_storage", "1000000000"),
    "МБ": ("decimal_storage", "1000000"), "MB": ("decimal_storage", "1000000"),
}
UNIT_PATTERN = "|".join(re.escape(x) for x in sorted(UNITS, key=len, reverse=True))
DIMENSION = re.compile(rf"(?<![\w.,]){SIGNED_NUMBER}\s*[xXхХ×]\s*{SIGNED_NUMBER}(?:\s*[xXхХ×]\s*{SIGNED_NUMBER})?(?:\s*(?:мм|см|mm|cm|м|m))?(?![\w.,])")
# An explicit unit can follow a joined word: the raw data contains Pro250 Ohm.
QUANTITY = re.compile(rf"(?:(?<![\w.,])|(?<=(?i:pro)))({SIGNED_NUMBER})\s*({UNIT_PATTERN})(?![\w/])")
STANDARD = re.compile(r"(?<!\w)(?:ГОСТ|ISO|DIN|ТУ)\s*(?:Р\s*)?\d[\d./-]*(?!\w)", re.I)
MODEL = re.compile(r"(?<!\w)(?=[A-Za-zА-Яа-яЁё\d./-]*[A-Za-zА-Яа-яЁё])(?=[A-Za-zА-Яа-яЁё\d./-]*\d)[A-Za-zА-Яа-яЁё\d]+(?:[-/.][A-Za-zА-Яа-яЁё\d]+)*(?!\w)")
BOUND = re.compile(r"(?:[<>≤≥≈±~]|(?<!\w)(?:не\s+(?:менее|более)|от|до|около|свыше|менее|более|примерно|приблизительно|не|без|мин\.?|макс\.?))\s*[:=]?\s*$", re.I)
RANGE_BEFORE = re.compile(rf"{NUMBER}\s*[-–—…]\s*$")
RANGE_AFTER = re.compile(rf"^\s*[-–—…±]\s*{NUMBER}")
# Mark both endpoints, including an endpoint whose minus sign is attached.
NUMERIC_RANGE = re.compile(
    rf"(?<![\w.,]){SIGNED_NUMBER}\s*(?:{UNIT_PATTERN})?\s*"
    rf"(?:\+/-|[-–—…±/]|(?i:до|или))\s*{SIGNED_NUMBER}\s*(?:{UNIT_PATTERN})?"
)
COMPOUND_SUFFIX = re.compile(r"^\s*(?:/|\^|\*\*|[²³·⋅])")
# Only an immediately named, unqualified property is aligned, without NLP.
PROPERTY_WORD = r"длина|ширина|высота|глубина|диаметр|толщина|сечение|напряжение|мощность|сопротивление|импеданс|объем|объём|масса|вес"
PROPERTY = re.compile(rf"(?<!\w)({PROPERTY_WORD})\s*[:=]?\s*$", re.I)
PROPERTY_MENTION = re.compile(rf"(?<!\w)(?:{PROPERTY_WORD})(?!\w)", re.I)
PROPERTY_QUALIFIER = re.compile(r"(?<!\w)(?:вход\w*|выход\w*|номинальн\w*|максимальн\w*|минимальн\w*|наружн\w*|внутренн\w*|внешн\w*)\s*$", re.I)
VOLUME_ALTERNATIVE = re.compile(r"(?<!\w)(?:или|либо|вариант\w*|ассортимент\w*|на\s+выбор)(?!\w)", re.I)
SHEET_COUNT_CONTEXT = re.compile(r"(?<!\w)(?:бумаг\w*|альбом\w*|тетрад\w*|блокнот\w*|ежедневник\w*|лист\w*)(?!\w)", re.I)


def _number(value: str) -> Decimal:
    return Decimal(re.sub(r"[ \u00a0\u202f]", "", value).replace(",", ".").replace("−", "-"))


def _converted(value: str, multiplier: str) -> str:
    # All supported conversions are powers of ten. Adjusting the exponent
    # preserves every input digit, unlike context-rounded Decimal multiply.
    parts = _number(value).as_tuple()
    shift = Decimal(multiplier).adjusted()
    return str(Decimal((parts.sign, parts.digits, parts.exponent + shift)))


def _key(value: str) -> str:
    return re.sub(r"\s+", "", unicodedata.normalize("NFC", value)).casefold()


def _relation(text: str, start: int, end: int) -> str:
    before, after = text[max(0, start - 24):start], text[end:end + 24]
    return "bounded_or_range" if BOUND.search(before) or RANGE_BEFORE.search(before) or RANGE_AFTER.search(after) else "literal"


@lru_cache(maxsize=50000)
def _attributes(text: str) -> tuple:
    found = []
    occupied = []
    ranges = [m.span() for m in NUMERIC_RANGE.finditer(text)]
    for kind, pattern in (("standard", STANDARD), ("dimension", DIMENSION), ("quantity", QUANTITY), ("model", MODEL)):
        for match in pattern.finditer(text):
            start, end = match.span()
            if any(start < b and end > a for a, b in occupied):
                continue
            raw = match.group()
            relation = _relation(text, start, end)
            property_name = None
            unit = None
            if kind == "quantity":
                unit = match.group(2)
                family, multiplier = UNITS[unit]
                values = (_converted(match.group(1), multiplier),)
                prefix = re.search(r"[A-Za-zА-Яа-яЁё]+$", text[:start])
                # The supplied DT770 Pro250 Ohm joins the word Pro to the
                # impedance. Other model-number attachments are ambiguous.
                if prefix and prefix.group().casefold() != "pro":
                    relation = "ambiguous_model_number_attachment"
                context = re.split(r"[;,\n]", text[max(0, start - 48):start])[-1]
                prop = PROPERTY.search(context)
                property_name = _key(prop.group(1)) if prop else None
                if (prop and PROPERTY_QUALIFIER.search(context[:prop.start()])) or (not prop and PROPERTY_MENTION.search(context)):
                    relation = "ambiguous_property_alignment"
            elif kind == "dimension":
                unit_match = re.search(r"(мм|см|mm|cm|м|m)$", raw)
                unit = unit_match.group() if unit_match else None
                family = "length" if unit else "unit_unspecified"
                multiplier = UNITS[unit][1] if unit else "1"
                values = tuple(_converted(v, multiplier) for v in re.findall(SIGNED_NUMBER, raw))
            else:
                values = (_key(raw),)
                family = re.sub(r"[^a-zа-яё]", "", _key(raw))
            if kind in ("quantity", "dimension"):
                if any(start < b and end > a for a, b in ranges):
                    relation = "bounded_or_range"
                elif unit is not None and COMPOUND_SUFFIX.search(text[end:end + 12]):
                    relation = "unsupported_compound_unit"
            found.append((kind, raw, start, end, family, values, unit, relation, property_name))
            occupied.append((start, end))
    return tuple(sorted(found, key=lambda a: a[2]))


def technical_attributes(text: str) -> list[dict]:
    if not isinstance(text, str):
        raise TypeError("Evidence text must be a string")
    if len(text) > 100000:
        raise ValueError("Evidence text exceeds 100000 characters")
    names = ("kind", "raw", "start", "end", "family", "values", "unit", "relation", "property")
    return [dict(zip(names, attr)) for attr in _attributes(text)]


def _value_key(attr: dict) -> tuple:
    if attr["kind"] in ("quantity", "dimension"):
        return tuple(Decimal(value) for value in attr["values"])
    return attr["values"]


def _alignment_key(attr: dict) -> tuple:
    property_name = "объем" if attr["property"] == "объём" else attr["property"]
    return attr["kind"], attr["family"], len(attr["values"]), property_name


def _single_unnamed_volume(attr: dict, required: list[dict], available: list[dict],
                           query_text: str, evidence_text: str) -> list[dict]:
    """Align an explicit volume requirement to one unqualified litre value.

    This narrow fallback never applies to axes, electrical properties, ranges,
    variant lists, or multiple quantities, even duplicate/equivalent values.
    It establishes a volume value in this fragment, not a product's identity.
    """
    if (attr["kind"] != "quantity" or attr["family"] != "volume"
            or attr["property"] not in ("объем", "объём") or attr["relation"] != "literal"):
        return []
    query_volumes = [a for a in required if a["family"] == "volume"]
    source_volumes = [a for a in available if a["family"] == "volume"]
    if len(query_volumes) != 1 or len(source_volumes) != 1:
        return []
    source = source_volumes[0]
    if source["kind"] != "quantity" or source["property"] is not None or source["relation"] != "literal":
        return []
    if VOLUME_ALTERNATIVE.search(query_text) or VOLUME_ALTERNATIVE.search(evidence_text):
        return []
    # In Russian stationery descriptions "500 л." denotes sheets. A bare л
    # in this context cannot substantiate an explicit litre requirement.
    if source["unit"] == "л" and SHEET_COUNT_CONTEXT.search(evidence_text):
        return []
    if PROPERTY_QUALIFIER.search(evidence_text[max(0, source["start"] - 48):source["start"]]):
        return []
    return [source]


def compare_evidence(query_text: str, evidence_text: str) -> dict:
    """Compare explicit attributes; conflicts apply to this fragment only.

    Unknown dimension units, named-property mismatches, and multiple distinct
    unaligned values do not establish either equality or a contradiction.
    """
    required, available = technical_attributes(query_text), technical_attributes(evidence_text)
    results = []
    for attr in required:
        candidates = [a for a in available if _alignment_key(a) == _alignment_key(attr)]
        volume_fallback = False
        if not candidates:
            candidates = _single_unnamed_volume(attr, required, available, query_text, evidence_text)
            volume_fallback = bool(candidates)
        query_values = {_value_key(a) for a in required if _alignment_key(a) == _alignment_key(attr)}
        candidate_values = {_value_key(a) for a in candidates}
        status, reason, matched = "unknown", "attribute_missing_or_incomparable", []
        if attr["relation"] != "literal":
            reason = "nonliteral_attribute_needs_interpretation"
        elif attr["family"] == "unit_unspecified":
            reason = "different_literal_dimensions_units_unknown" if candidates and _value_key(attr) not in candidate_values else "literal_dimensions_units_unknown"
        elif len(query_values) > 1 or len(candidate_values) > 1:
            reason = "multiple_values_without_attribute_alignment"
        elif any(a["relation"] != "literal" for a in candidates):
            reason = "nonliteral_evidence_needs_interpretation"
        elif _value_key(attr) in candidate_values:
            status, reason = "match", "explicit_value_present"
            matched = candidates
        elif candidates:
            status, reason = "conflict", "different_explicit_value_in_fragment"
        result = {"query_attribute": attr, "status": status, "reason": reason,
                  "evidence_attributes": matched or candidates}
        if volume_fallback:
            result["alignment_rule"] = "single_literal_unnamed_volume"
        results.append(result)
    counts = {key: sum(r["status"] == key for r in results) for key in ("match", "conflict", "unknown")}
    status = "conflict" if counts["conflict"] else "match" if results and counts["match"] == len(results) else "unknown"
    return {"version": VERSION, "status": status, "counts": counts, "attributes": results,
            "scope": "explicit_attributes_of_one_fragment_only",
            "supplier_suitability": "unjudged", "complete_item_match": "unjudged"}
