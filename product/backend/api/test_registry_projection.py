"""Registry identity evidence must not become a product/website assertion."""
from unittest import TestCase
from .presentation import recommendation


class RegistryProjectionTests(TestCase):
    def test_verified_license_keeps_its_scope_and_unknown_product(self):
        match = {'profile_id': 'registry:pharma:123', 'source_url': 'https://www.roszdravnadzor.gov.ru/opendata/example.zip',
                 'source_excerpt': 'Оптовая торговля лекарственными средствами',
                 'freshness': {'reported_fetched_at': '2026-10-02', 'source_published_at': None,
                               'license_event_at': '2026-09-01'},
                 'identity': {'status': 'official_registry_identity_evidenced',
                              'notes': ['Наличие конкретного товара не подтверждено.']},
                 'page_content_independently_verified': False, 'registry_content_independently_verified': True,
                 'registry_evidence': {'license_number': 'TEST-1', 'source_locator': 'licenses[7]'},
                 'technical_comparison': {'status': 'unknown'}}
        value = recommendation({'supplier_inn': '123', 'new_to_full_history': True,
                                'item_evidence': [{'item_index': 0, 'matches': [match]}]}, 0, True)
        company = value['company']; source = company['sources'][0]
        self.assertIsNone(company['website'])
        self.assertTrue(source['identityVerified'])
        self.assertTrue(source['available'])
        self.assertEqual(source['kind'], 'registry_license')
        self.assertIsNone(source['publishedAt'])
        self.assertIn('TEST-1', source['scope'])
        self.assertIn('2026-09-01', source['scope'])
        self.assertIn('licenses[7]', source['verificationScope'])
        self.assertEqual(value['evidence'][0]['technicalStatus'], 'unknown')
        self.assertFalse(company['role']['verified'])
