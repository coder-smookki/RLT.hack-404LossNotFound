from datetime import date
import tempfile
from pathlib import Path
import sqlite3
from collections import Counter
import json
import re
import unittest
import zlib

from rlt_lab.external_evidence import ExternalCatalog, NON_SUBJECT_WORDS, apply_activity_patch, file_sha256, freshness, profile_quality, verified_companies, valid_inn, identity_mentions_inn


def empty_catalog(path):
    connection = sqlite3.connect(path)
    connection.executescript("""
        CREATE TABLE companies(inn TEXT,company_name TEXT,has_s9_historical INTEGER);
        CREATE TABLE working_profiles(id INTEGER,inn TEXT,retrieval_text BLOB,source_url TEXT,source_ref TEXT,fetched_at TEXT,content_hash TEXT,identity_confidence TEXT,evidence_level TEXT,source_type TEXT);
        CREATE TABLE profile_claims(profile_id INTEGER,claim_id TEXT);
        CREATE TABLE external_claims(claim_id TEXT,claim_type TEXT,excerpt TEXT,inn TEXT,source_url TEXT,fetched_at TEXT,content_hash TEXT);
    """)
    return connection


class ExternalEvidenceTests(unittest.TestCase):
    def test_inn_identity_accepts_real_legal_formats_not_arbitrary_numbers(self):
        for inn in ("7839446247", "6950114173", "7804682148", "231004591311"):
            self.assertTrue(valid_inn(inn), inn)
        for inn in ("0000000000", "000000000000", "231004591310", "231004591301", "6950114174", "695011417", " 6950114173", "６950114173"):
            self.assertFalse(valid_inn(inn), inn)
        self.assertTrue(identity_mentions_inn("ИНН/КПП 6950114173/695001001", "6950114173"))
        self.assertTrue(identity_mentions_inn("ООО «ГК «АДСТ» ИНН 7804 682148 КПП 780401001", "7804682148"))
        self.assertTrue(identity_mentions_inn("ОГРНИП: 321237500402390 ИНН: 231004591311", "231004591311"))
        for excerpt in ("Телефон 6950114173", "ОГРН 6950114173", "ИНН: 69501141730", "ИНН: 6950114173 00", "БИНН: 6950114173"):
            self.assertFalse(identity_mentions_inn(excerpt, "6950114173"), excerpt)

    def test_activity_patch_keeps_offer_date_and_supersedes_conflicting_page_date(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            page = root / "news.html"
            page.write_text('<html><head><meta name="published" content="2026-04-19"></head><body>Шприцы. 2025-03-01</body></html>')
            event = {"url": "https://example.org/news", "payload_path": "news.html", "sha256": file_sha256(page),
                     "excerpt": "Шприцы. 2025-03-01", "published_at": None, "date_status": "conflicting_publisher_dates",
                     "date_scope": "product_news", "eligible_for_verified_dated_counter": False,
                     "date_evidence": [{"representation": "raw_html", "excerpt": '<meta name="published" content="2026-04-19">'},
                                       {"representation": "normalized_body_text", "excerpt": "2025-03-01"}]}
            companies = [{"inn": "7839446247", "official_site": "https://example.org/", "offers": [{"published_at": None}],
                          "activity_evidence": [{"url": event["url"], "excerpt": "Шприцы", "published_at": "2025-03-01"}]}]
            data = {"base_companies_sha256": "base", "companies": [{"inn": companies[0]["inn"], "official_site": companies[0]["official_site"],
                    "activity_evidence": [event], "dated_offers": []}]}
            path = root / "patch.json"
            path.write_text(json.dumps(data))
            apply_activity_patch(companies, path, file_sha256(path), "base")
            self.assertIsNone(companies[0]["offers"][0]["published_at"])
            self.assertEqual(len(companies[0]["activity_evidence"]), 1)
            self.assertIsNone(companies[0]["activity_evidence"][0]["published_at"])
            data["companies"][0]["dated_offers"] = [event]
            event["published_at"] = "2026-04-19"
            path.write_text(json.dumps(data))
            with self.assertRaisesRegex(ValueError, "ambiguous date"):
                apply_activity_patch(companies, path, file_sha256(path), "base")
            data["companies"][0]["dated_offers"] = []
            event["published_at"] = None
            event["date_evidence"][0]["excerpt"] = "invented date markup"
            path.write_text(json.dumps(data))
            with self.assertRaisesRegex(ValueError, "Date evidence is absent"):
                apply_activity_patch(companies, path, file_sha256(path), "base")

    def test_evidence_lead_requires_subject_not_generic_action_or_number(self):
        tokenize = lambda text: re.findall(r"[а-яa-z0-9]+(?:-[а-яa-z0-9]+)*", text.casefold())
        catalog = ExternalCatalog.__new__(ExternalCatalog)
        catalog.tokenize = tokenize
        catalog.non_subject_tokens = set(tokenize(NON_SUBJECT_WORDS))
        catalog.profiles = [None]
        pairs = [
            ("Оказание услуг отдых детей", "Оказание услуг ремонт котлов"),
            ("Уборка улиц 10", "Кабель 10"),
            ("Металлический стеллаж", "Металлический лоток"),
            ("ПВХ окно", "ПВХ кабель"),
            ("Испытание огнетушителей", "Испытание котлов"),
            ("Поверка манометров МП-100", "Манометров МП-100"),
            ("Поверка газоанализаторов", "Ремонт газоанализаторов"),
            ("Проверка газоанализаторов", "Поверка газоанализаторов"),
        ]
        for query, evidence in pairs:
            with self.subTest(query=query):
                profile = {"tokens": Counter(tokenize(evidence)), "retrieval_text": evidence}
                self.assertIsNone(catalog._match(query, profile))

    def test_reviewed_batch_checks_actual_bytes_excerpt_identity_and_domain(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            html = root / "page.html"
            html.write_text('<html><script>Скрытый товар</script><body>ИНН: 7839446247 <p>Шприцы 2 мл</p></body></html>')
            e = {"url": "https://example.org/about", "payload_path": "page.html", "sha256": file_sha256(html), "excerpt": "ИНН: 7839446247"}
            company = {"inn": "7839446247", "official_site": "https://example.org/", "identity_evidence": [e],
                       "offers": [dict(e, excerpt="Шприцы 2 мл")], "activity_evidence": []}
            path = root / "companies.json"
            def save():
                path.write_text(json.dumps([company], ensure_ascii=False))
                return file_sha256(path)
            self.assertEqual(len(verified_companies(path, save())), 1)
            company["offers"][0]["excerpt"] = "Скрытый товар"
            with self.assertRaisesRegex(ValueError, "absent from saved"):
                verified_companies(path, save())
            company["offers"][0]["excerpt"] = "Шприцы 2 мл"
            company["offers"][0]["url"] = "https://example.org.attacker.invalid/about"
            with self.assertRaisesRegex(ValueError, "outside"):
                verified_companies(path, save())
            company["offers"][0]["url"] = e["url"]
            e["excerpt"] = "Телефон 7839446247"
            with self.assertRaisesRegex(ValueError, "identity label"):
                verified_companies(path, save())
            e["excerpt"] = "ИНН: 7839446247"
            digest = save()
            html.write_text("Изменённый источник")
            with self.assertRaisesRegex(ValueError, "hash mismatch"):
                verified_companies(path, digest)

    def test_obvious_noise_does_not_become_offer(self):
        for text in ("OK Отмена", "Главная страница", "03.09.2025", "Контактные данные", "Опубликовано gazadmin"):
            self.assertFalse(profile_quality(text, "https://example.org/services/")["eligible_for_search"])
        self.assertFalse(profile_quality("Отчет по итогам голосования", "https://example.org/about_company/information_disclosure/")["eligible_for_search"])
        self.assertTrue(profile_quality("Поверка манометров", "https://example.org/services/")["eligible_for_search"])

    def test_additional_reviewed_batch_preserves_sources_and_rejects_duplicates(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            database = root / "catalog.sqlite"
            empty_catalog(database).close()
            batches = []
            for index, inn in enumerate(("7839446247", "6950114173")):
                folder = root / str(index)
                folder.mkdir()
                page = folder / "page.html"
                page.write_text(f"<body>ИНН: {inn} <p>Манометр МП-100</p></body>")
                identity = {"url": "https://example.org/offer", "payload_path": page.name,
                            "sha256": file_sha256(page), "excerpt": f"ИНН: {inn}"}
                company = {"inn": inn, "name": "Batch provenance fixture", "official_site": "https://example.org/",
                           "existing_in_history": False, "identity_evidence": [identity], "activity_evidence": [],
                           "offers": [dict(identity, excerpt="Манометр МП-100", retrieved_at="2026-10-02",
                                           published_at=None, updated_at=None)]}
                path = folder / "companies.json"
                path.write_text(json.dumps([company], ensure_ascii=False))
                batches.append((path, file_sha256(path)))
            def load(extra):
                return ExternalCatalog(database, str.split, expected_sha256=file_sha256(database),
                                       as_of=date(2026, 10, 2), fresh_companies_path=batches[0][0],
                                       fresh_companies_sha256=batches[0][1], reviewed_batches=extra)
            catalog = load((batches[1],))
            self.assertEqual(len(catalog.discover([{"product_name": "Манометр МП-100"}], set())), 2)
            self.assertEqual(len({p["id"] for p in catalog.profiles}), 2)
            self.assertEqual(catalog.metadata()["additional_reviewed_batches"], [{"sha256": batches[1][1], "companies": 1}])
            self.assertEqual(file_sha256(batches[0][0]), batches[0][1])
            with self.assertRaisesRegex(ValueError, "duplicates"):
                load((batches[0],))
            with self.assertRaisesRegex(ValueError, "differs from reviewed"):
                load(((batches[1][0], "incorrect"),))
            (batches[1][0].parent / "page.html").write_text("changed response")
            with self.assertRaisesRegex(ValueError, "hash mismatch"):
                load((batches[1],))

    def test_fetched_date_is_not_publication_date(self):
        result = freshness("2026-10-01T21:12:44+00:00", date(2026, 10, 2))
        self.assertEqual(result["cutoff"], "2023-10-02")
        self.assertTrue(result["fetch_within_window"])
        self.assertEqual(result["window_policy"], "advisory")
        self.assertEqual(result["content_recency"], "unknown")
        self.assertIsNone(result["source_updated_at"])
        for stamp in ("2023-10-01", "2026-10-03", "bad"):
            self.assertFalse(freshness(stamp, date(2026, 10, 2))["fetch_within_window"])

    def test_older_verified_offer_is_searchable_but_not_counted_recent(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            catalog_path = root / "catalog.sqlite"
            empty_catalog(catalog_path).close()
            html = root / "offer.html"
            html.write_text('<body>ИНН: 7839446247 <p>Манометр МП-100</p></body>')
            evidence = {"url": "https://example.org/offer", "payload_path": html.name,
                        "sha256": file_sha256(html), "excerpt": "ИНН: 7839446247"}
            offer = dict(evidence, excerpt="Манометр МП-100", retrieved_at="2021-04-02",
                         published_at="2020-01-01", updated_at=None)
            company = {"inn": "7839446247", "name": "Synthetic date-policy fixture",
                       "official_site": "https://example.org/", "existing_in_history": False,
                       "identity_evidence": [evidence], "offers": [offer], "activity_evidence": [offer]}
            batch = root / "companies.json"
            def load():
                batch.write_text(json.dumps([company], ensure_ascii=False))
                return ExternalCatalog(catalog_path, str.split, expected_sha256=file_sha256(catalog_path),
                    as_of=date(2026, 10, 2), fresh_companies_path=batch, fresh_companies_sha256=file_sha256(batch))
            catalog = load()
            found = catalog.discover([{"product_name": "Манометр МП-100"}], set())
            self.assertEqual(len(found), 1)
            stamp = found[0]["item_evidence"][0]["matches"][0]["freshness"]
            self.assertEqual(stamp["content_recency"], "publisher_dated_before_window")
            self.assertFalse(stamp["fetch_within_window"])
            self.assertEqual(catalog.metadata()["fresh_companies_with_dated_publications"], 0)
            offer["published_at"] = "2026-10-03"
            catalog = load()
            self.assertEqual(catalog.profiles, [])
            self.assertEqual(catalog.excluded[0]["quality"]["reason"], "source_date_after_as_of")
            offer["published_at"] = None
            offer["retrieved_at"] = "2026-10-03"
            self.assertEqual(load().excluded[0]["quality"]["reason"], "fetch_after_as_of")

    def test_provenance_and_separate_cold_start(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "catalog.sqlite"
            c = empty_catalog(path)
            c.execute("INSERT INTO companies VALUES(?,?,?)", ("1234567890", "Synthetic fixture", 0))
            c.execute("INSERT INTO working_profiles VALUES(?,?,?,?,?,?,?,?,?,?)", (1, "1234567890", zlib.compress("Манометр МП-100".encode()), "https://example.org/catalog/", "fixture:1", "2026-10-01", "declared-page-hash", "HIGH", "A", "external"))
            c.execute("INSERT INTO profile_claims VALUES(?,?)", (1, "claim1"))
            c.execute("INSERT INTO external_claims VALUES(?,?,?,?,?,?,?)", ("claim1", "product_offer", "Манометр МП-100", "1234567890", "https://example.org/catalog/", "2026-10-01", "declared-page-hash"))
            c.commit()
            c.close()
            tokenize = lambda text: text.casefold().split()
            with self.assertRaises(ValueError):
                ExternalCatalog(path, tokenize, expected_sha256="wrong", as_of=date(2026, 10, 2))
            catalog = ExternalCatalog(path, tokenize, expected_sha256=file_sha256(path), as_of=date(2026, 10, 2))
            items = [{"product_name": "Манометр МП-100", "okpd2_code": ""}]
            found = catalog.discover(items, set())
            self.assertEqual(len(found), 1)
            self.assertIsNone(found[0]["ranking_score"])
            match = found[0]["item_evidence"][0]["matches"][0]
            self.assertEqual(match["claim_id"], "claim1")
            self.assertEqual(match["source_excerpt"], "Манометр МП-100")
            self.assertFalse(match["page_content_independently_verified"])
            self.assertEqual(match["identity"]["status"], "reported_not_independently_verified")
            self.assertEqual(catalog.discover(items, {"1234567890"}), [])
            known_overlay = catalog.discover(items, {"1234567890"}, exclude_inns=set())
            self.assertEqual(len(known_overlay), 1)
            self.assertFalse(known_overlay[0]["cold_start"])
            self.assertEqual(catalog.discover(items, set(), exclude_inns={"1234567890"}), [])
            self.assertEqual(catalog.evidence_for("1234567890", [{"product_name": "Бумага офисная"}])[0]["matches"], [])
            # Old/unknown fetch dates do not turn documentary offers into negatives.
            for stamp in ("2020-01-01", "unknown", "2026-10-03"):
                c = sqlite3.connect(path)
                c.execute("UPDATE working_profiles SET fetched_at=?", (stamp,))
                c.execute("UPDATE external_claims SET fetched_at=?", (stamp,))
                c.commit()
                c.close()
                catalog = ExternalCatalog(path, tokenize, expected_sha256=file_sha256(path), as_of=date(2026, 10, 2))
                self.assertEqual(len(catalog.discover(items, set())), 0 if stamp == "2026-10-03" else 1)
            c = sqlite3.connect(path)
            c.execute("UPDATE external_claims SET inn='another'")
            c.commit()
            c.close()
            with self.assertRaisesRegex(ValueError, "provenance mismatch"):
                ExternalCatalog(path, tokenize, expected_sha256=file_sha256(path), as_of=date(2026, 10, 2))


if __name__ == "__main__":
    unittest.main()
