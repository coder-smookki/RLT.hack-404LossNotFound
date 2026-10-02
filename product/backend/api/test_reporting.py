import io
import unittest
from unittest.mock import patch
from pypdf import PdfReader
from .reporting import build_pdf


class PdfReportTests(unittest.TestCase):
    def query(self):
        def candidate(inn, name):
            return {'rank': 1, 'score': 0.125, 'scoreKind': 'historical_rrf',
                    'reason': 'Наблюдалось участие; ассортимент не подтверждён.', 'evidence': [],
                    'company': {'id': 'inn:'+inn, 'inn': inn, 'name': name, 'sources': [
                        {'title': 'Исходная цитата', 'excerpt': '<img src="https://invalid.test/pixel"> & текст',
                         'url': 'javascript:alert(1)', 'scope': 'Цвет не подтверждён', 'fetchedAt': '2026-10-02'}]}}
        return {'id': 'pdf-isolated-fixture', 'resultVersion': 'test-v1', 'createdAt': '2026-10-02T08:00:00Z',
                'status': 'complete', 'procurement': {'subject': 'Проверка кириллицы', 'lotId': '001'},
                'rawItems': [{'product_name': 'Исходная позиция', 'okpd2_code': '01.01'}],
                'recommendations': [candidate('1', 'Историческая компания')],
                'externalCandidates': [candidate('2', 'Внешняя компания')]}

    def text(self, pdf):
        return '\n'.join(p.extract_text() for p in PdfReader(io.BytesIO(pdf)).pages)

    def test_owned_selection_and_source_limits_are_visible(self):
        q = self.query()
        with patch('socket.create_connection', side_effect=AssertionError('PDF must stay offline')):
            pdf = build_pdf(q, {'companyIds': ['inn:2']})
        text = self.text(pdf)
        self.assertIn('Внешняя компания', text)
        self.assertNotIn('Историческая компания', text)
        self.assertIn('Цвет не подтверждён', text)
        self.assertIn('<img src=', text)
        self.assertNotIn('javascript:', text)
        self.assertIn('не являются вероятностями', text)

    def test_export_of_same_snapshot_is_byte_reproducible(self):
        q = self.query()
        options = {'generatedAt': '2026-10-02T08:01:00Z'}
        self.assertEqual(build_pdf(q, options), build_pdf(q, options))

    def test_long_input_is_paginated_with_explicit_bound(self):
        q = self.query()
        q['rawItems'] = [{'product_name': f'Строка {i}: '+('Описание материала ' * 20)} for i in range(103)]
        pdf = build_pdf(q)
        reader = PdfReader(io.BytesIO(pdf))
        self.assertGreater(len(reader.pages), 2)
        text = self.text(pdf)
        self.assertIn('100 из 103', text)
        self.assertIn('Как читать отчёт', text)
