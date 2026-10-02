import copy
import hashlib
import socket
import ssl
import unittest
from email.message import Message
from unittest.mock import MagicMock, patch
from .source_fetch import (SourceFailure, PageText, PinnedHTTPS, fetch_page,
                           public_addresses, refresh_profile, reviewed_url, MAX_BYTES)


def profile():
    return {'inn': '7805742047', 'fields': {
        'name': {'value': 'ООО НАНОМЕД', 'status': 'verified', 'sourceIds': ['id'], 'observedAt': '2026-09-01'},
        'website': {'value': 'https://example.org', 'status': 'verified', 'sourceIds': ['id'], 'observedAt': '2026-09-01'},
        'activities': {'value': [{'text': 'Лицензия на деятельность', 'scope': 'licensed_activity', 'sourceIds': ['registry']}],
                       'status': 'verified', 'sourceIds': ['registry'], 'observedAt': '2026-09-01'}},
        'sources': [
            {'id': 'id', 'url': 'https://example.org/requisites', 'identityVerified': True, 'identityInn': '7805742047', 'scope': 'identity', 'excerpt': 'ИНН 7805742047'},
            {'id': 'offer', 'url': 'https://example.org/offer', 'identityVerified': True, 'identityInn': '7805742047', 'scope': 'commercial_offer', 'excerpt': 'Пробирки объёмом 5 мл'},
            {'id': 'registry', 'url': 'https://registry.example.org/licence', 'identityVerified': True, 'identityInn': '7805742047', 'scope': 'licensed_activity', 'excerpt': 'Лицензия'}]}


def page(url, text):
    body = text.encode()
    return {'url': url, 'text': text, 'body': body, 'contentHash': hashlib.sha256(body).hexdigest(), 'fetchedAt': '2026-10-02T12:00:00+00:00'}


class SourceFetchTests(unittest.TestCase):
    def test_only_reviewed_https_domain(self):
        for url in ['http://example.org/', 'https://example.org.evil.test/', 'https://evil.test/?example.org',
                    'https://user:pass@example.org/', 'https://example.org:8443/', 'https://127.0.0.1/',
                    'https://example.org:bad/', 'https://example.org/\nHost:localhost', 'file:///etc/passwd']:
            with self.subTest(url=url), self.assertRaises(SourceFailure):
                reviewed_url(url, 'example.org')
        self.assertEqual(reviewed_url('https://www.example.org/contact', 'example.org')[1], 'www.example.org')

    def test_all_resolved_addresses_must_be_public(self):
        def rows(addresses):
            return [(socket.AF_INET, socket.SOCK_STREAM, 6, '', (ip, 443)) for ip in addresses]
        for addresses in [['127.0.0.1'], ['10.0.0.1'], ['169.254.169.254'], ['93.184.216.34', '192.168.1.1']]:
            with patch('api.source_fetch.socket.getaddrinfo', return_value=rows(addresses)), self.assertRaises(SourceFailure):
                public_addresses('example.org')
        with patch('api.source_fetch.socket.getaddrinfo', return_value=rows(['93.184.216.34'])):
            self.assertEqual(public_addresses('example.org')[0][1][0], '93.184.216.34')

    def test_pinned_connection_uses_ip_and_original_tls_hostname(self):
        conn = PinnedHTTPS('example.org', [(socket.AF_INET, ('93.184.216.34', 443))])
        self.assertEqual(conn._context.verify_mode, ssl.CERT_REQUIRED)
        self.assertTrue(conn._context.check_hostname)
        raw = MagicMock()
        context = MagicMock()
        conn._context = context
        with patch('api.source_fetch.socket.socket', return_value=raw), patch('api.source_fetch.socket.getaddrinfo', side_effect=AssertionError('DNS must not run again')):
            conn.connect()
        raw.connect.assert_called_once_with(('93.184.216.34', 443))
        context.wrap_socket.assert_called_once_with(raw, server_hostname='example.org')

    def test_visible_contacts_only(self):
        parser = PageText()
        parser.feed('<script>ИНН 7805742047</script><a href="mailto:info@example.org">info@example.org</a>'
                    '<a href="mailto:other@evil.test">info@example.org</a><a href="tel:+78121234567">+7 812 123-45-67</a>')
        self.assertNotIn('7805742047', ' '.join(parser.parts))
        self.assertEqual([x['kind'] for x in parser.contacts], ['email', 'phone'])

    def test_no_website_is_needs_source_without_fetch(self):
        p = profile();p['fields']['website']['status'] = 'unknown'
        result = refresh_profile(p, fetch=MagicMock(side_effect=AssertionError()))
        self.assertEqual(result['status'], 'needs_source')

    def test_other_identity_does_not_replace_saved_profile(self):
        p = profile();before = copy.deepcopy(p)
        result = refresh_profile(p, fetch=lambda url, _: page(url, 'ИНН 7714923896 Чужая компания'))
        self.assertEqual(result['status'], 'unconfirmed')
        self.assertIsNone(result['profile']);self.assertEqual(p, before)

    def test_updates_literal_facts_preserves_registry_age_and_original_input(self):
        p = profile();before = copy.deepcopy(p)
        def fetch(url, host):
            return page(url, 'ООО НАНОМЕД ИНН 7805742047 <a href="mailto:info@example.org">info@example.org</a>'
                        if url.endswith('requisites') else 'Пробирки объёмом 5 мл')
        result = refresh_profile(p, fetch=fetch)
        self.assertEqual(result['status'], 'complete');self.assertEqual(p, before)
        fields = result['profile']['fields']
        self.assertEqual(fields['name']['observedAt'], '2026-10-02T12:00:00+00:00')
        self.assertEqual(fields['activities']['observedAt'], '2026-09-01')
        self.assertEqual(fields['contacts']['value'][0]['value'], 'info@example.org')
        self.assertEqual(len(fields['activities']['value']), 2)
        self.assertTrue(all(s.get('publishedAt') is None for s in result['profile']['sources'] if s['id'].startswith('live:')))

    def test_unmatched_new_offer_is_not_invented(self):
        result = refresh_profile(profile(), fetch=lambda url, _: page(url, 'ИНН 7805742047' if url.endswith('requisites') else 'Другой товар'))
        self.assertEqual(result['status'], 'complete')
        self.assertEqual(result['profile']['fields']['activities']['value'][0]['scope'], 'licensed_activity')
        self.assertEqual(len(result['profile']['fields']['activities']['value']), 1)

    def test_requisites_require_single_identity_and_valid_ogrn(self):
        text = 'ИНН 7805742047 ОГРН 1197847022768 КПП 780501001'
        result = refresh_profile(profile(), fetch=lambda url, _: page(url, text))
        self.assertEqual(result['profile']['fields']['ogrn']['value'], '1197847022768')
        self.assertEqual(result['profile']['fields']['kpp']['value'], '780501001')
        for ambiguous in (text + ' ИНН 7714923896', text.replace('1197847022768', '1197847022769')):
            result = refresh_profile(profile(), fetch=lambda url, _: page(url, ambiguous))
            self.assertNotIn('ogrn', result['profile']['fields'])

    def test_transport_errors_do_not_fabricate_fresh_information(self):
        result = refresh_profile(profile(), fetch=MagicMock(side_effect=SourceFailure('Недоступно')))
        self.assertEqual(result['status'], 'failed')
        self.assertIsNone(result['profile'])

    def test_shared_site_with_multiple_inns_does_not_assign_ambiguous_contacts(self):
        text = 'ИНН 7805742047 ОГРН 1197847022768. ИНН 7714923896 <a href="mailto:info@example.org">info@example.org</a>'
        result = refresh_profile(profile(), fetch=lambda url, _: page(url, text))
        self.assertEqual(result['status'], 'complete')
        self.assertNotIn('contacts', result['profile']['fields'])
        self.assertNotIn('ogrn', result['profile']['fields'])

    def test_only_three_reviewed_pages_are_fetched(self):
        p = profile()
        p['sources'] += [{**p['sources'][1], 'id': f'offer{x}', 'url': f'https://example.org/offer{x}'} for x in range(10)]
        fetch = MagicMock(side_effect=lambda url, _: page(url, 'ИНН 7805742047'))
        refresh_profile(p, fetch=fetch)
        self.assertEqual(fetch.call_count, 3)

    def test_fetch_rejects_offdomain_redirect_and_oversized_content(self):
        for status, headers in [(302, {'Location': 'https://127.0.0.1/'}), (200, {'Content-Type': 'text/html', 'Content-Length': str(MAX_BYTES+1)}),
                                (200, {'Content-Type': 'text/html', 'Content-Encoding': 'gzip'})]:
            response = MagicMock(); response.status = status; response.headers = Message()
            for k, v in headers.items():response.headers[k] = v
            response.getheader.side_effect = lambda k, default=None: headers.get(k, default)
            response.__enter__.return_value = response
            conn = MagicMock();conn.getresponse.return_value = response
            with self.subTest(status=status, headers=headers), patch('api.source_fetch.public_addresses', return_value=[(socket.AF_INET, ('93.184.216.34', 443))]), patch('api.source_fetch.PinnedHTTPS', return_value=conn), self.assertRaises(SourceFailure):
                fetch_page('https://example.org/', 'example.org')
