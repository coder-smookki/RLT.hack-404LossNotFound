import unittest

from rlt_lab.evidence_matching import compare_evidence, technical_attributes


class EvidenceMatchingTests(unittest.TestCase):
    def test_model_case_and_wrong_version(self):
        self.assertEqual(compare_evidence("Behringer P2", "BEHRINGER p2")["status"], "match")
        self.assertEqual(compare_evidence("Behringer P2", "Behringer P1")["status"], "conflict")
        self.assertEqual(compare_evidence("Behringer P2", "Звуковое оборудование")["status"], "unknown")

    def test_real_headphone_impedance(self):
        result = compare_evidence("DT770 250 Ohm", "DT770 80 Ohm")
        self.assertEqual(result["counts"], {"match": 1, "conflict": 1, "unknown": 0})
        self.assertEqual(result["supplier_suitability"], "unjudged")
        raw = "Наушники мониторные BEYERDYNAMIC DT770 Pro250 Ohm"
        resistance = [a for a in technical_attributes(raw) if a["family"] == "resistance"]
        self.assertEqual([a["raw"] for a in resistance], ["250 Ohm"])

    def test_decimal_and_explicit_unit_conversion(self):
        self.assertEqual(compare_evidence("Кабель 0,4 кВ", "Кабель 400 В")["status"], "match")
        self.assertEqual(compare_evidence("2000x1000x400 мм", "200x100x40 см")["status"], "match")
        self.assertEqual(compare_evidence("2000x1000x400 мм", "2000x1000x600 мм")["status"], "conflict")

    def test_no_inferred_dimension_unit(self):
        result = compare_evidence("MS HARD 2000x1000x400/ 4", "MS HARD 2000x1000x600/ 4")
        self.assertEqual(result["status"], "unknown")
        self.assertEqual(result["attributes"][0]["reason"], "different_literal_dimensions_units_unknown")
        self.assertIsNone(result["attributes"][0]["query_attribute"]["unit"])

    def test_bound_and_alternatives_are_unknown(self):
        self.assertEqual(compare_evidence("не менее 20 мм", "10 мм")["status"], "unknown")
        self.assertEqual(compare_evidence("20 мм", "10-30 мм")["status"], "unknown")
        self.assertEqual(compare_evidence("20 мм", "10 мм или 30 мм")["status"], "unknown")

    def test_si_case_is_not_destroyed(self):
        self.assertEqual(compare_evidence("1 мВт", "1 МВт")["status"], "conflict")

    def test_signed_values_and_compound_units(self):
        self.assertEqual(compare_evidence("−10 В", "10 В")["status"], "conflict")
        self.assertEqual(compare_evidence("10 мм", "10 мм ± 2 мм")["status"], "unknown")
        self.assertEqual(compare_evidence("10 мг/мл", "10 мг")["status"], "unknown")

    def test_source_spans_and_row_number(self):
        text = "6 Проверка (испытание) переносного пеногенератора ГПС-599"
        attrs = technical_attributes(text)
        self.assertEqual([a["raw"] for a in attrs], ["ГПС-599"])
        for a in attrs:
            self.assertEqual(text[a["start"]:a["end"]], a["raw"])

    def test_empty_generic_is_not_match(self):
        self.assertEqual(compare_evidence("Поставка мебели", "Мебель")["status"], "unknown")

    def test_standards_case_preserves_number(self):
        self.assertEqual(compare_evidence("ГОСТ 3262-75", "гост3262-75")["status"], "match")
        self.assertEqual(compare_evidence("ГОСТ 3262-75", "ГОСТ 3262-76")["status"], "conflict")

    def test_named_lengths_are_not_interchangeable(self):
        self.assertEqual(compare_evidence("длина 10 мм", "ширина 20 мм")["status"], "unknown")
        self.assertEqual(compare_evidence("длина 10 мм", "ширина 10 мм")["status"], "unknown")
        missing = compare_evidence("длина 10 мм; ширина 20 мм", "длина 10 мм")
        self.assertEqual(missing["counts"], {"match": 1, "conflict": 0, "unknown": 1})
        swapped = compare_evidence("длина 10 мм; ширина 20 мм", "длина 20 мм; ширина 10 мм")
        self.assertEqual(swapped["counts"], {"match": 0, "conflict": 2, "unknown": 0})

    def test_unaligned_multiple_values_do_not_claim_match_or_conflict(self):
        for query, fragment in [("10 мм; 20 мм", "10 мм"), ("10 мм; 20 мм", "20 мм; 10 мм"),
                                ("20 мм", "20 мм или 30 мм"), ("10 мм", "10 мм; 20 мм")]:
            with self.subTest(query=query, fragment=fragment):
                self.assertEqual(compare_evidence(query, fragment)["status"], "unknown")

    def test_qualified_properties_are_not_silently_aligned(self):
        for query, fragment in [("входное напряжение 12 В", "выходное напряжение 5 В"),
                                ("длина корпуса 10 мм", "ширина корпуса 10 мм"),
                                ("внутренний диаметр 10 мм", "наружный диаметр 20 мм")]:
            with self.subTest(query=query, fragment=fragment):
                self.assertEqual(compare_evidence(query, fragment)["status"], "unknown")

    def test_ranges_and_tolerances_do_not_produce_literal_endpoints(self):
        for fragment in ["10 -30 мм", "10 мм -30 мм", "10 мм – 30 мм", "10 мм ± 2 мм",
                         "10 мм +/- 2 мм", "от 10 до 30 мм", "10…30 мм", "10/30 мм"]:
            with self.subTest(fragment=fragment):
                self.assertEqual(compare_evidence("20 мм", fragment)["status"], "unknown")

    def test_bounded_candidate_does_not_turn_other_value_into_conflict(self):
        self.assertEqual(compare_evidence("20 мм", "10 мм, от 15 до 25 мм")["status"], "unknown")
        for fragment in ["не менее: 20 мм", "более 20 мм", "примерно 20 мм", "не 20 мм"]:
            with self.subTest(fragment=fragment):
                self.assertEqual(compare_evidence("20 мм", fragment)["status"], "unknown")

    def test_spaced_compound_units_and_powers_are_not_scalar_units(self):
        for fragment in ["10 мм / с", "10 мм^2", "10 мм²", "10 мм ** 2", "10 мм/с"]:
            with self.subTest(fragment=fragment):
                self.assertEqual(compare_evidence("10 мм", fragment)["status"], "unknown")

    def test_dimension_units_are_case_sensitive_and_never_inferred(self):
        self.assertEqual(compare_evidence("1x2 мм", "1x2 ММ")["status"], "unknown")
        self.assertEqual(compare_evidence("1X2 мм", "1x2 мм")["status"], "match")
        self.assertEqual(compare_evidence("1x2", "1x2")["status"], "unknown")
        self.assertEqual(compare_evidence("-10x20 мм", "10x20 мм")["status"], "conflict")

    def test_grouped_numbers_are_not_truncated_to_last_group(self):
        for text in ["1 000 В", "1\u00a0000 В", "1\u202f000 В"]:
            with self.subTest(text=text):
                result = compare_evidence("1 кВ", text)
                self.assertEqual(result["status"], "match")
                self.assertEqual(result["attributes"][0]["evidence_attributes"][0]["raw"], text)

    def test_exact_decimal_digits_are_preserved(self):
        a = "123456789012345678901234567890 В"
        b = "123456789012345678901234567891 В"
        self.assertEqual(compare_evidence(a, b)["status"], "conflict")

    def test_quantity_does_not_borrow_model_number(self):
        self.assertEqual(compare_evidence("770 Ohm", "DT770 Ohm")["status"], "unknown")
        result = compare_evidence("DT770 Pro250 Ohm", "DT770 Pro 250 Ohm")
        self.assertEqual(result["status"], "match")
        self.assertEqual(result["counts"], {"match": 2, "conflict": 0, "unknown": 0})

    def test_duplicate_equivalent_units_are_not_ambiguous(self):
        self.assertEqual(compare_evidence("400 В", "0,4 кВ; 400 В")["status"], "match")

    def test_attributes_preserve_spans_for_new_formats(self):
        text = "Ширина: 1\u202f000 мм; DT770 Pro250 Ohm, допуск 10 -30 мм"
        for attr in technical_attributes(text):
            self.assertEqual(text[attr["start"]:attr["end"]], attr["raw"])

    def test_result_is_not_complete_product_or_supplier_judgment(self):
        result = compare_evidence("Кабель 10 мм", "Крепёж 10 мм")
        self.assertEqual(result["status"], "match")
        self.assertEqual(result["complete_item_match"], "unjudged")
        self.assertEqual(result["supplier_suitability"], "unjudged")

    def test_single_explicit_volume_against_unnamed_litre_value(self):
        matching = compare_evidence("Средство, объём 5 л", "Средство Septa 200. 5 л")
        self.assertEqual(matching["status"], "match")
        self.assertEqual(matching["attributes"][0]["alignment_rule"], "single_literal_unnamed_volume")
        self.assertEqual(compare_evidence("Средство, объем 7 л", "Средство Septa 200. 5 л")["status"], "conflict")
        self.assertEqual(compare_evidence("Объём 5 л", "Канистра 5000 мл")["status"], "match")
        self.assertEqual(compare_evidence("Объём 5 л", "Объем 5000 мл")["status"], "match")
        self.assertEqual(matching["complete_item_match"], "unjudged")

    def test_volume_fallback_rejects_variants_and_multiple_values(self):
        for source in ["Канистры 5 л и 7 л", "5 л или 7 л", "Варианты: 5 л", "5 л либо другая фасовка",
                       "Объемы на выбор: 5 л", "5 л; 5000 мл", "5-7 л", "не менее 5 л", "максимальный 5 л",
                       "номинальный объём 5 л", "объём бака 5 л"]:
            with self.subTest(source=source):
                self.assertEqual(compare_evidence("Объём 5 л", source)["status"], "unknown")
        self.assertEqual(compare_evidence("Объём 5 л; объём 7 л", "Канистра 5 л")["status"], "unknown")

    def test_volume_fallback_does_not_relax_other_attribute_alignment(self):
        for query, source in [("ширина 5 мм", "5 мм"), ("высота 5 мм", "ширина 5 мм"),
                              ("напряжение 12 В", "12 В"),
                              ("входное напряжение 12 В", "выходное напряжение 12 В"),
                              ("объём 5 л", "Канистра 5 Л")]:
            with self.subTest(query=query, source=source):
                self.assertEqual(compare_evidence(query, source)["status"], "unknown")
        self.assertEqual(compare_evidence("2000x1000x300 мм", "2000x1000x400 мм")["status"], "conflict")
        self.assertEqual(compare_evidence("2000x1000x300 мм", "MS Hard 2000x1000x400 Высота, мм: 2000 Ширина, мм: 1000 Глубина, мм: 400")["status"], "unknown")

    def test_bare_l_in_stationery_does_not_become_litres(self):
        for source in ["Бумага офисная А4, 500 л.", "Альбом для рисования 40 л.",
                       "Тетрадь 12 л", "Блокнот 80 л", "Бумага а4 офисная SvetoCopy A4 Classic 80г/м2, 500 л белая"]:
            with self.subTest(source=source):
                self.assertEqual(compare_evidence("Средство, объём 5 л", source)["status"], "unknown")


if __name__ == "__main__":
    unittest.main()
