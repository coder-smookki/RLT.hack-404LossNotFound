import csv
from contextlib import closing
import hashlib
import io
import json
import sqlite3
import tempfile
import unittest
from pathlib import Path
from zipfile import ZipFile

from rlt_lab.data import build_database


ITEM_HEADER = ("lot_id", "product_name", "okpd2_code")
NOTICE_HEADER = (
    "publish_date", "procedure_id", "lot_id", "start_price", "reqnum",
    "procedure_name", "subject", "is_smp", "customer_inn", "customer_kpp",
    "is_eshop_or_aisgz",
)
SUPPLIER_HEADER = ("lot_id", "supplier_inn", "supplier_kpp", "is_winner")


def csv_bytes(header, rows):
    stream = io.StringIO(newline="")
    writer = csv.writer(stream, delimiter=";")
    writer.writerow(header)
    writer.writerows(rows)
    return stream.getvalue().encode("utf-8-sig")


def notice(lot_id="1", date="2024-01-02", subject="Поставка бумаги"):
    return (date, "p1", lot_id, "120.00", "", "Закупка", subject,
            "false", "123", "456", "АИС ГЗ")


class BuildDatabaseTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.archive = self.root / "source.zip"
        self.database = self.root / "data.sqlite"
        self.audit = self.root / "audit.json"

    def tearDown(self):
        self.temp.cleanup()

    def make_archive(self, items=None, notices=None, supplier_body=b"bad;row\n", supplier_rows=None):
        if items is None:
            items = [("1", "Бумага", "17.12.14"), ("1", "Бумага", "17.12.14"),
                     ("missing-notice", "", "")]
        if notices is None:
            notices = [notice(), notice("without-items", "2025-01-03", "Без ТРУ")]
        with ZipFile(self.archive, "w") as archive:
            # Misleading member names must not select a schema.
            archive.writestr("broken-name/suppliers.csv", csv_bytes(ITEM_HEADER, items))
            archive.writestr("broken-name/tru.csv", csv_bytes(NOTICE_HEADER, notices))
            archive.writestr("broken-name/notices.csv",
                             csv_bytes(SUPPLIER_HEADER, supplier_rows) if supplier_rows is not None
                             else csv_bytes(SUPPLIER_HEADER, []) + supplier_body)

    def build(self, replace=False, include_history=False):
        return build_database(self.archive, self.database, self.audit,
                              replace=replace, include_history=include_history)

    def test_header_classification_preserves_join_audit_and_ignores_supplier_rows(self):
        self.make_archive(supplier_body=b"\xffinvalid utf-8 supplier rows;must not be read\n")
        result = self.build()
        with closing(sqlite3.connect(self.database)) as conn:
            joined = conn.execute("SELECT product_name, subject FROM items JOIN notices USING(lot_id)").fetchall()
            self.assertEqual(joined, [("Бумага", "Поставка бумаги"), ("Бумага", "Поставка бумаги")])
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM items").fetchone()[0], 3)
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM notices").fetchone()[0], 2)
            tables = {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            self.assertNotIn("suppliers", tables)
        self.assertEqual(result["items"]["missing_fields"]["product_name"], 1)
        self.assertEqual(result["items"]["missing_fields"]["okpd2_code"], 1)
        self.assertEqual(result["dates"]["year_counts"], {"2024": 1, "2025": 1})
        self.assertEqual(result["duplicate_items"]["extra_rows"], 1)
        self.assertEqual(result["relationships"]["item_rows_without_notice"], 1)
        self.assertEqual(result["relationships"]["notice_lots_without_items"], 1)
        self.assertEqual(result["category_summary"][0]["prefix"], "17")
        self.assertEqual(result["category_summary"][0]["item_count"], 2)
        self.assertEqual(result["category_summary"][0]["subject_examples"],
                         [{"subject": "Поставка бумаги", "lot_count": 1}])
        self.assertEqual(result["source"]["sha256"], hashlib.sha256(self.archive.read_bytes()).hexdigest())
        self.assertEqual([m["role"] for m in result["source"]["members"]], ["items", "notices", "suppliers_ignored"])
        self.assertEqual(json.loads(self.audit.read_text()), result)

    def test_wrong_width_aborts_without_publishing_outputs_or_leaving_temporary_files(self):
        self.make_archive(items=[("1", "Бумага")])
        with self.assertRaisesRegex(ValueError, "width|columns|fields"):
            self.build()
        self.assertFalse(self.database.exists())
        self.assertFalse(self.audit.exists())
        self.assertEqual(list(self.root.iterdir()), [self.archive])

    def test_missing_required_lot_id_rejected_in_each_input(self):
        for kind in ("items", "notices"):
            with self.subTest(kind=kind):
                self.make_archive(items=[(" ", "Бумага", "17.12")] if kind == "items" else None,
                                  notices=[notice(lot_id="")] if kind == "notices" else None)
                with self.assertRaisesRegex(ValueError, "lot_id"):
                    self.build()
                self.assertFalse(self.database.exists())

    def test_duplicate_notice_id_is_rejected_without_losing_original_database(self):
        self.make_archive()
        self.build()
        before = self.database.read_bytes()
        audit_before = self.audit.read_bytes()
        self.make_archive(notices=[notice(), notice(subject="Другая закупка")])
        with self.assertRaisesRegex(ValueError, "[Dd]uplicate|UNIQUE"):
            self.build(replace=True)
        self.assertEqual(self.database.read_bytes(), before)
        self.assertEqual(self.audit.read_bytes(), audit_before)

    def test_invalid_or_missing_publish_date_rejected(self):
        for date in ("2024-02-30", "2024-1-2", "", "2024-01-02T00:00:00"):
            with self.subTest(date=date):
                self.make_archive(notices=[notice(date=date)])
                with self.assertRaisesRegex(ValueError, "publish_date"):
                    self.build()
                self.assertFalse(self.database.exists())

    def test_existing_database_requires_explicit_replace(self):
        self.make_archive()
        self.build()
        before = self.database.read_bytes()
        with self.assertRaises(FileExistsError):
            self.build()
        self.assertEqual(self.database.read_bytes(), before)
        self.make_archive(items=[("1", "Новая бумага", "17.12")])
        self.build(replace=True)
        with closing(sqlite3.connect(self.database)) as conn:
            self.assertEqual(conn.execute("SELECT product_name FROM items").fetchall(), [("Новая бумага",)])

    def test_unknown_or_duplicate_schema_does_not_silently_build_partial_database(self):
        self.make_archive()
        with ZipFile(self.archive, "a") as archive:
            archive.writestr("extra.csv", csv_bytes(ITEM_HEADER, [("2", "Набор", "17")]))
        with self.assertRaisesRegex(ValueError, "[Dd]uplicate|multiple"):
            self.build()
        self.assertFalse(self.database.exists())

    def test_history_opt_in_preserves_raw_identifiers_duplicates_and_relationship_counts(self):
        rows = [
            ("1", "0012345678", "000001001", "true"),
            ("1", "0012345678", "000001001", "true"),
            ("without-items", "000123456789", "", "false"),
            ("orphan", "１２３４５６７８９０", "０００００１００１", "unknown"),
            ("1", "", "", ""),
        ]
        self.make_archive(supplier_rows=rows)
        result = self.build(include_history=True)
        with closing(sqlite3.connect(self.database)) as conn:
            self.assertEqual(conn.execute(
                "SELECT lot_id,supplier_inn,supplier_kpp,is_winner FROM suppliers ORDER BY row_id"
            ).fetchall(), rows)
            self.assertEqual(conn.execute(
                "SELECT COUNT(*) FROM suppliers JOIN notices USING(lot_id)"
            ).fetchone()[0], 4)
            self.assertEqual(conn.execute(
                "SELECT COUNT(*) FROM suppliers WHERE supplier_inn='0012345678'"
            ).fetchone()[0], 2)
        self.assertTrue(result["history_included"])
        self.assertEqual(result["source"]["members"][-1]["role"], "suppliers")
        self.assertEqual(result["suppliers"]["row_count"], 5)
        self.assertEqual(result["suppliers"]["distinct_lot_count"], 3)
        self.assertEqual(result["suppliers"]["distinct_nonempty_inn_count"], 3)
        self.assertEqual(result["suppliers"]["missing_fields"]["supplier_inn"], 1)
        self.assertEqual(result["suppliers"]["inn_format_warning_rows"], 1)
        self.assertEqual(result["suppliers"]["winner_value_counts"],
                         {"": 1, "false": 1, "true": 2, "unknown": 1})
        self.assertEqual(result["duplicate_suppliers"]["extra_rows"], 1)
        self.assertEqual(result["supplier_relationships"], {
            "supplier_rows_without_notice": 1, "supplier_lots_without_notice": 1,
            "supplier_rows_without_items": 2, "supplier_lots_without_items": 2,
            "notice_lots_without_suppliers": 0, "item_lots_without_suppliers": 1,
            "linked_supplier_rows": 4,
        })
        self.assertEqual(json.loads(self.audit.read_text()), result)

    def test_history_invalid_utf8_default_ignored_but_opt_in_preserves_previous_outputs(self):
        self.make_archive(supplier_body=b"\xffinvalid supplier row\n")
        result = self.build()
        self.assertFalse(result["history_included"])
        before, audit_before = self.database.read_bytes(), self.audit.read_bytes()
        with self.assertRaisesRegex(ValueError, "Invalid CSV data"):
            self.build(replace=True, include_history=True)
        self.assertEqual(self.database.read_bytes(), before)
        self.assertEqual(self.audit.read_bytes(), audit_before)
        self.assertEqual({p.name for p in self.root.iterdir()}, {"source.zip", "data.sqlite", "audit.json"})

    def test_history_bad_width_or_missing_join_key_is_rejected(self):
        for row, message in [
            (("1", "0012345678", "000001001"), "width"),
            (("", "0012345678", "000001001", "true"), "lot_id"),
            ((" 1 ", "0012345678", "000001001", "true"), "lot_id"),
        ]:
            with self.subTest(row=row):
                self.make_archive(supplier_rows=[row])
                with self.assertRaisesRegex(ValueError, message):
                    self.build(include_history=True)
                self.assertFalse(self.database.exists())
                self.assertFalse(self.audit.exists())

    def test_history_requires_exactly_one_supplier_schema(self):
        with ZipFile(self.archive, "w") as archive:
            archive.writestr("items.csv", csv_bytes(ITEM_HEADER, [("1", "Бумага", "17")]))
            archive.writestr("notices.csv", csv_bytes(NOTICE_HEADER, [notice()]))
        with self.assertRaisesRegex(ValueError, "supplier"):
            self.build(include_history=True)
        self.assertFalse(self.database.exists())
        self.make_archive(supplier_rows=[("1", "0012345678", "000001001", "true")])
        with ZipFile(self.archive, "a") as archive:
            archive.writestr("another-supplier.csv", csv_bytes(SUPPLIER_HEADER, []))
        with self.assertRaisesRegex(ValueError, "Duplicate CSV schema.*suppliers"):
            self.build(include_history=True)
        self.assertFalse(self.database.exists())


if __name__ == "__main__":
    unittest.main()
