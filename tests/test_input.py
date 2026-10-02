import csv
from pathlib import Path
import tempfile
import unittest

from rlt_lab.data import ITEM_COLUMNS, NOTICE_COLUMNS
from rlt_lab.input import read_procurements


class InputTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.notices = self.root / "notices.csv"
        self.items = self.root / "items.csv"

    def write(self, path, columns, rows, delimiter=";", bom=False):
        with path.open("w", encoding="utf-8-sig" if bom else "utf-8", newline="") as stream:
            writer = csv.DictWriter(stream, fieldnames=columns, delimiter=delimiter)
            writer.writeheader()
            writer.writerows(rows)

    def pair(self, item_lot="0002", date="2026-10-01"):
        notice = dict.fromkeys(NOTICE_COLUMNS, "")
        notice.update(lot_id="0002", publish_date=date, customer_inn="0012345678", subject="Новый лот")
        item = dict(lot_id=item_lot, product_name='Стул; "офисный"', okpd2_code="31.01.11.150")
        self.write(self.notices, tuple(reversed(NOTICE_COLUMNS)), [notice], ",", True)
        self.write(self.items, ITEM_COLUMNS, [item, item])

    def test_new_lot_preserves_ids_raw_repeats_and_quoted_text(self):
        self.pair()
        lots = read_procurements(self.notices, self.items)
        self.assertEqual(lots[0]["notice"]["lot_id"], "0002")
        self.assertEqual(lots[0]["notice"]["customer_inn"], "0012345678")
        self.assertEqual(len(lots[0]["items"]), 2)
        self.assertEqual(lots[0]["items"][0]["product_name"], 'Стул; "офисный"')

    def test_orphan_items_are_not_silently_attached(self):
        self.pair(item_lot="2")
        with self.assertRaisesRegex(ValueError, "no matching procurement"):
            read_procurements(self.notices, self.items)

    def test_invalid_calendar_date(self):
        self.pair(date="2026-02-30")
        with self.assertRaisesRegex(ValueError, "Invalid publish_date"):
            read_procurements(self.notices, self.items)

    def test_missing_field_cannot_be_guessed(self):
        self.pair()
        self.items.write_text("lot_id;name;okpd2_code\n0002;Стул;31\n", encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "Unsupported CSV schema"):
            read_procurements(self.notices, self.items)

    def test_truncated_row_rejected(self):
        self.pair()
        self.items.write_text("lot_id;product_name;okpd2_code\n0002;Стул\n", encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "Wrong CSV width"):
            read_procurements(self.notices, self.items)

    def test_duplicate_procurement_rejected(self):
        self.pair()
        contents = self.notices.read_text(encoding="utf-8-sig")
        self.notices.write_text(contents + contents.splitlines()[1] + "\n", encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "Duplicate procurement"):
            read_procurements(self.notices, self.items)

    def test_procurement_without_items_retained(self):
        self.pair()
        self.write(self.items, ITEM_COLUMNS, [])
        lots = read_procurements(self.notices, self.items)
        self.assertEqual(lots[0]["items"], [])


if __name__ == "__main__":
    unittest.main()
