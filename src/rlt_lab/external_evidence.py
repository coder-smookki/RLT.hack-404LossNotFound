"""Read-only external claims, kept separate from frozen historical ranking.

Catalog metadata is reported, not promoted to verified company identity or
supplier suitability. A page-fetch date is never a source-publication date.
"""
from __future__ import annotations

from collections import Counter, defaultdict
from datetime import date, datetime
from hashlib import sha256
from html.parser import HTMLParser
import json
import math
from pathlib import Path
import re
import sqlite3
from urllib.parse import urlsplit
import zlib

from .evidence_matching import compare_evidence, VERSION as EVIDENCE_COMPARISON_VERSION

VERSION = "external-evidence-v7"
BOILERPLATE = re.compile(
    r"(?:ok\s+отмена|главная(?:\s+страница)?|контактные\s+данные|контактное\s+лицо|"
    r"оставить\s+(?:отзыв|претензию)|популярные\s+категории|прайс[\s-]*лист|"
    r"подробнее|заказать|обратный\s+звонок|наши\s+клиенты|все\s+права\s+защищены|"
    r"опубликовано\s+\w+|уголовная\s+ответственность|работы,?\s+которые\s+мы\s+проводим)[.!…\s]*", re.I)
DATE_ONLY = re.compile(r"\d{1,2}[./-]\d{1,2}[./-]\d{2,4}[\s.]*")
# Eligibility for a current evidence lead only. This does not alter P1 input,
# historical retrieval, model features, or the accepted historical ranking.
NON_SUBJECT_WORDS = """и в во на по для с со к ко от до из у о об а или не без при под над
оказание услуга работа проведение выполнение поставка закупка приобретение товар
заказчик исполнитель организация объект комплекс комплексный общий необходимый
требование описание технический характеристика количество единица измерение
подготовка испытание проверка поверка ремонт обслуживание монтаж наладка
металлический пластиковый медицинский новый основной различный дополнительный
шт штука мм см м км мл л кг г квт вт кв в а па кпа мпа ом ohm pro пвх
"""
SERVICE_PREFIX = re.compile(
    r"^\s*(?:\d+[.)]?\s+)?(?:оказание\s+услуг\s+(?:по\s+)?|услуг[аи]\s+(?:по\s+)?)?"
    r"(?P<kind>ремонт|поверк|проверк|испытан|техническ\w*\s+обслужив|монтаж|наладк)", re.I)
REVIEWER_NAMES = {"антон в.", "елена викторовна", "николай сергеевич", "ромашов константин"}


def file_sha256(path: Path) -> str:
    digest = sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def valid_inn(inn: str) -> bool:
    """Checksum/format only; never a claim of registration or current activity."""
    if not isinstance(inn, str) or not re.fullmatch(r"(?:[0-9]{10}|[0-9]{12})", inn) or set(inn) == {"0"}:
        return False
    digits = [int(char) for char in inn]
    def check(weights):
        return sum(digit * weight for digit, weight in zip(digits, weights)) % 11 % 10
    if len(inn) == 10:
        return check((2, 4, 10, 3, 5, 9, 4, 6, 8)) == digits[9]
    return (check((7, 2, 4, 10, 3, 5, 9, 4, 6, 8)) == digits[10]
            and check((3, 7, 2, 4, 10, 3, 5, 9, 4, 6, 8)) == digits[11])


def identity_mentions_inn(excerpt: str, inn: str) -> bool:
    """Accept literal ИНН/КПП and grouped digits without altering saved evidence."""
    pattern = r"\bИНН(?:\s+организации)?(?:\s*/\s*КПП)?\s*[:;№]?\s*([0-9](?:[0-9\s]*[0-9])?)"
    return any(re.sub(r"\s", "", match.group(1)) == inn for match in re.finditer(pattern, excerpt, re.I))


def _decode(value) -> str:
    if isinstance(value, bytes):
        decoder = zlib.decompressobj()
        value = decoder.decompress(value, 100001)
        if len(value) > 100000 or not decoder.eof:
            raise ValueError("External profile text is oversized or truncated")
        value = value.decode("utf-8")
    if not isinstance(value, str) or len(value) > 100000:
        raise ValueError("Invalid external profile text")
    return value


def profile_quality(text: str, source_url: str) -> dict:
    """Exclude only obvious non-offer fragments; other text remains unjudged."""
    canonical = " ".join(text.split()).strip()
    reason = None
    url = urlsplit(source_url)
    if url.scheme not in ("http", "https") or not url.hostname:
        reason = "invalid_source_url"
    elif DATE_ONLY.fullmatch(canonical):
        reason = "date_only"
    elif not canonical or not re.search(r"[A-Za-zА-Яа-яЁё]", canonical):
        reason = "no_textual_offer"
    elif BOILERPLATE.fullmatch(canonical):
        reason = "navigation_or_ui_fragment"
    elif canonical.casefold() in REVIEWER_NAMES:
        reason = "reviewed_person_name_without_offer"
    elif any(segment in url.path.casefold() for segment in ("/privacy", "/labor_and_safety", "/personal-data", "/politika-konf", "/information_disclosure")):
        reason = "policy_page_requires_offer_review"
    return {"eligible_for_search": reason is None, "reason": reason,
            "offer_semantics": "unjudged" if reason is None else "non_offer_or_needs_review"}


def freshness(fetched_at: str, as_of: date) -> dict:
    try:
        observed = datetime.fromisoformat(fetched_at.replace("Z", "+00:00")).date()
    except (ValueError, AttributeError):
        observed = None
    try:
        cutoff = as_of.replace(year=as_of.year - 3)
    except ValueError:
        cutoff = as_of.replace(year=as_of.year - 3, day=28)
    in_window = observed is not None and cutoff <= observed <= as_of
    return {"window_months": 36, "window_policy": "advisory", "as_of": as_of.isoformat(), "cutoff": cutoff.isoformat(),
            "reported_fetched_at": fetched_at, "fetch_within_window": in_window,
            "fetch_after_as_of": observed is not None and observed > as_of,
            "source_published_at": None, "source_updated_at": None,
            "content_recency": "unknown", "company_activity": "unverified"}


class _VisibleText(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts, self.skip = [], []

    def handle_starttag(self, tag, attrs):
        if tag in ("script", "style", "noscript"):
            self.skip.append(tag)

    def handle_endtag(self, tag):
        if self.skip and self.skip[-1] == tag:
            self.skip.pop()

    def handle_data(self, data):
        if not self.skip:
            self.parts.append(data)


def _verify_source(evidence: dict, directory: Path, official: str, pages: dict) -> tuple[str, str]:
    url = urlsplit(evidence["url"])
    host = (url.hostname or "").removeprefix("www.")
    if url.scheme not in ("http", "https") or not (host == official or host.endswith("." + official)):
        raise ValueError("Evidence is outside the reviewed official domain")
    payload = (directory / evidence["payload_path"]).resolve()
    if not payload.is_relative_to(directory) or payload.stat().st_size > 20 * 1024 * 1024:
        raise ValueError("Unsafe or oversized saved evidence path")
    key = (str(payload), evidence["sha256"])
    if key not in pages:
        body = payload.read_bytes()
        if sha256(body).hexdigest() != evidence["sha256"]:
            raise ValueError("Saved source payload hash mismatch")
        raw_html = body.decode("utf-8")
        parser = _VisibleText()
        parser.feed(raw_html)
        pages[key] = (" ".join(" ".join(parser.parts).split()), raw_html)
    visible, raw_html = pages[key]
    excerpt = " ".join(evidence["excerpt"].split())
    if not excerpt or excerpt not in visible:
        raise ValueError("Evidence excerpt is absent from saved page text")
    if evidence.get("commercial_link_excerpt") and " ".join(evidence["commercial_link_excerpt"].split()) not in visible:
        raise ValueError("Commercial statement absent from saved page text")
    return visible, raw_html


def verified_companies(path: Path, expected_sha256: str) -> list[dict]:
    """Verify a reviewed batch against saved official-site response bytes."""
    path = Path(path).resolve()
    if file_sha256(path) != expected_sha256:
        raise ValueError("Fresh company batch differs from reviewed snapshot")
    companies = json.loads(path.read_text(encoding="utf-8"))
    seen, pages = set(), {}
    for company in companies:
        inn = company["inn"]
        if not valid_inn(inn) or inn in seen:
            raise ValueError("Invalid or duplicate reviewed company INN")
        seen.add(inn)
        official = (urlsplit(company["official_site"]).hostname or "").removeprefix("www.")
        if not official or not company["identity_evidence"] or not company["offers"]:
            raise ValueError("Company lacks official identity or product evidence")
        if not any(identity_mentions_inn(e["excerpt"], inn) for e in company["identity_evidence"]):
            raise ValueError("Company INN must follow its literal identity label")
        for evidence in company["identity_evidence"] + company["offers"] + company["activity_evidence"]:
            _verify_source(evidence, path.parent, official, pages)
    return companies


def apply_activity_patch(companies: list[dict], path: Path, expected_sha256: str, base_sha256: str) -> dict:
    """Merge only reviewed facts; original offers retain their original dates."""
    path = Path(path).resolve()
    if file_sha256(path) != expected_sha256:
        raise ValueError("Activity patch differs from reviewed snapshot")
    patch = json.loads(path.read_text(encoding="utf-8"))
    if patch["base_companies_sha256"] != base_sha256:
        raise ValueError("Activity patch has a different base identity catalog")
    known, pages, seen = {c["inn"]: c for c in companies}, {}, set()
    for update in patch["companies"]:
        inn = update["inn"]
        if inn not in known or inn in seen or update["official_site"] != known[inn]["official_site"]:
            raise ValueError("Activity patch has an unknown or duplicate company/domain")
        seen.add(inn)
        official = urlsplit(update["official_site"]).hostname.removeprefix("www.")
        for evidence in update["activity_evidence"] + update["dated_offers"]:
            visible, raw_html = _verify_source(evidence, path.parent, official, pages)
            if not evidence.get("date_scope") or not evidence.get("date_evidence"):
                raise ValueError("Dated evidence needs a specific date source and scope")
            for proof in evidence["date_evidence"]:
                if proof["representation"] == "raw_html":
                    found = proof["excerpt"] in raw_html
                elif proof["representation"] == "normalized_body_text":
                    found = " ".join(proof["excerpt"].split()) in visible
                else:
                    raise ValueError("Unsupported date evidence representation")
                if not found:
                    raise ValueError("Date evidence is absent from saved page")
        # Unambiguous dated offers are additional, source-specific fragments.
        # An article date never overwrites the previous undated catalog page.
        for offer in update["dated_offers"]:
            unambiguous = bool(offer.get("published_at")) and offer.get("date_status") == "unambiguous_publisher_date"
            unresolved = (offer.get("published_at") is None and offer.get("date_status") == "conflicting_publisher_dates"
                          and offer.get("eligible_for_verified_dated_counter") is False)
            if not (unambiguous or unresolved):
                raise ValueError("An ambiguous date cannot label a dated offer")
        updated_urls = {e["url"] for e in update["activity_evidence"]}
        # A newly discovered date conflict supersedes the older single-date
        # interpretation of that page; the immutable base file remains intact.
        known[inn]["activity_evidence"] = [e for e in known[inn]["activity_evidence"] if e["url"] not in updated_urls] + update["activity_evidence"]
        known[inn]["offers"].extend(update["dated_offers"])
    return {"sha256": expected_sha256, "companies": len(seen),
            "added_offer_claims": sum(len(c["dated_offers"]) for c in patch["companies"]),
            "unambiguous_dated_offers": sum(bool(o.get("published_at")) for c in patch["companies"] for o in c["dated_offers"])}


class ExternalCatalog:
    def __init__(self, path: Path, tokenize, *, expected_sha256: str, as_of: date,
                 fresh_companies_path: Path | None = None, fresh_companies_sha256: str | None = None,
                 activity_patch_path: Path | None = None, activity_patch_sha256: str | None = None,
                 reviewed_batches: tuple[tuple[Path, str], ...] = (),
                 registry_batches: tuple[tuple[Path, str], ...] = ()):
        self.path = Path(path).resolve()
        self.sha256 = file_sha256(self.path)
        if self.sha256 != expected_sha256:
            raise ValueError("External catalog differs from its reviewed snapshot")
        self.tokenize, self.as_of = tokenize, as_of
        self.non_subject_tokens = set(tokenize(NON_SUBJECT_WORDS))
        self.profiles = []
        self.by_inn = defaultdict(list)
        self.excluded = []
        con = sqlite3.connect(self.path.as_uri() + "?mode=ro", uri=True)
        con.row_factory = sqlite3.Row
        try:
            con.execute("PRAGMA query_only=ON")
            rows = con.execute("""
                SELECT w.id,w.inn,w.retrieval_text,w.source_url,w.source_ref,
                       w.fetched_at,w.content_hash,w.identity_confidence,w.evidence_level,
                       c.company_name,c.has_s9_historical,p.claim_id,e.claim_type,e.excerpt,
                       e.inn claim_inn,e.source_url claim_url,e.fetched_at claim_fetched_at,
                       e.content_hash claim_hash
                FROM working_profiles w JOIN companies c USING(inn)
                LEFT JOIN profile_claims p ON p.profile_id=w.id
                LEFT JOIN external_claims e ON e.claim_id=p.claim_id
                WHERE w.source_type='external' ORDER BY w.id,p.claim_id
            """)
            seen = set()
            for row in rows:
                profile = dict(row)
                if profile["id"] in seen:
                    raise ValueError("This adapter requires one claim per external profile")
                seen.add(profile["id"])
                if not profile["claim_id"] or any(profile[a] != profile[b] for a, b in (
                    ("inn", "claim_inn"), ("source_url", "claim_url"),
                    ("fetched_at", "claim_fetched_at"), ("content_hash", "claim_hash"))):
                    raise ValueError("External profile/claim provenance mismatch")
                profile["retrieval_text"] = _decode(profile["retrieval_text"])
                profile["excerpt"] = _decode(profile["excerpt"])
                profile["quality"] = profile_quality(profile["retrieval_text"], profile["source_url"])
                profile["freshness"] = freshness(profile["fetched_at"], as_of)
                if profile["freshness"]["fetch_after_as_of"]:
                    profile["quality"] = {"eligible_for_search": False, "reason": "fetch_after_as_of", "offer_semantics": "unjudged"}
                profile["tokens"] = Counter(tokenize(profile["retrieval_text"]))
                if profile["quality"]["eligible_for_search"]:
                    self.profiles.append(profile)
                    self.by_inn[profile["inn"]].append(profile)
                else:
                    self.excluded.append(profile)
            total = con.execute("SELECT count(*) FROM working_profiles WHERE source_type='external'").fetchone()[0]
            if len(seen) != total:
                raise ValueError("Missing company identities or duplicate profile links")
        finally:
            con.close()
        self.legacy_profile_count = len(self.profiles) + len(self.excluded)
        self.fresh_companies = []
        self.fresh_sha256 = fresh_companies_sha256
        self.activity_patch = None
        self.reviewed_batches = []
        if fresh_companies_path is not None:
            self.fresh_companies = verified_companies(fresh_companies_path, fresh_companies_sha256)
            if activity_patch_path is not None:
                self.activity_patch = apply_activity_patch(self.fresh_companies, activity_patch_path, activity_patch_sha256, fresh_companies_sha256)
        seen_companies = {p["inn"] for p in self.profiles + self.excluded}
        seen_companies.update(c["inn"] for c in self.fresh_companies)
        for batch_path, batch_sha256 in reviewed_batches:
            companies = verified_companies(batch_path, batch_sha256)
            if seen_companies.intersection(c["inn"] for c in companies):
                raise ValueError("Additional reviewed batch duplicates an external company")
            seen_companies.update(c["inn"] for c in companies)
            self.fresh_companies.extend(companies)
            self.reviewed_batches.append({"sha256": batch_sha256, "companies": len(companies)})
        if self.fresh_companies:
            for company in self.fresh_companies:
                for index, offer in enumerate(company["offers"]):
                    # Only literal source wording is indexed; a researcher-written
                    # title is not substituted for documentary evidence.
                    text = offer["excerpt"]
                    quality = profile_quality(text, offer["url"])
                    stamp = freshness(offer["retrieved_at"], as_of)
                    stamp["source_published_at"] = offer["published_at"]
                    stamp["source_updated_at"] = offer["updated_at"]
                    stamp["source_date_scope"] = offer.get("date_scope")
                    stamp["source_date_status"] = offer.get("date_status", "unknown")
                    stamp["source_date_candidates"] = offer.get("date_candidates", [])
                    stamp["source_date_evidence"] = offer.get("date_evidence", [])
                    if offer.get("date_status") == "conflicting_publisher_dates":
                        stamp["content_recency"] = "conflicting_publication_dates"
                    if offer["published_at"]:
                        published = date.fromisoformat(offer["published_at"])
                        in_window = date.fromisoformat(stamp["cutoff"]) <= published <= as_of
                        stamp["content_recency"] = "publisher_dated_within_window" if in_window else "publisher_dated_before_window"
                        # Age is evidence to review, not automatic unsuitability.
                        # Future facts still cannot substantiate an as-of result.
                        if published > as_of:
                            stamp["content_recency"] = "source_date_after_as_of"
                            quality = {"eligible_for_search": False, "reason": "source_date_after_as_of", "offer_semantics": "unjudged"}
                    stamp["dated_activity_sources"] = company["activity_evidence"]
                    stamp["activity_definition"] = "Dated official-site publication, not proof of fulfilled contracts"
                    if stamp["fetch_after_as_of"]:
                        quality = {"eligible_for_search": False, "reason": "fetch_after_as_of", "offer_semantics": "unjudged"}
                    profile = {"id": f"fresh:{company['inn']}:{index}", "inn": company["inn"],
                               "retrieval_text": text, "excerpt": text, "source_url": offer["url"],
                               "source_ref": "official_site_response", "fetched_at": offer["retrieved_at"],
                               "content_hash": offer["sha256"], "identity_confidence": "official_domain_identity_evidenced",
                               "evidence_level": "saved_primary_source", "company_name": company["name"],
                               "has_s9_historical": company["existing_in_history"],
                               "claim_id": f"fresh:{company['inn']}:{index}", "claim_type": offer.get("claim_type", "category_offer"),
                               "quality": quality, "freshness": stamp, "tokens": Counter(tokenize(text)),
                               "verified_page": True, "identity_evidence": company["identity_evidence"],
                               "commercial_link_excerpt": offer.get("commercial_link_excerpt"),
                               "identity_notes": company.get("identity_notes", [])}
                    if quality["eligible_for_search"]:
                        self.profiles.append(profile)
                        self.by_inn[company["inn"]].append(profile)
                    else:
                        self.excluded.append(profile)
        self.registry_batches = []
        if registry_batches:
            from .registry_evidence import load_registry_batch
            profile_ids = {p["id"] for p in self.profiles + self.excluded}
            for batch_path, batch_sha256 in registry_batches:
                profiles, metadata = load_registry_batch(batch_path, batch_sha256, tokenize, as_of)
                for profile in profiles:
                    if profile["id"] in profile_ids:
                        raise ValueError("Duplicate registry evidence profile")
                    profile_ids.add(profile["id"])
                    if profile["quality"]["eligible_for_search"]:
                        self.profiles.append(profile)
                        self.by_inn[profile["inn"]].append(profile)
                    else:
                        self.excluded.append(profile)
                self.registry_batches.append(metadata)
        self.df = Counter(t for p in self.profiles for t in p["tokens"])
        self.average_length = sum(sum(p["tokens"].values()) for p in self.profiles) / max(1, len(self.profiles))

    def _match(self, query: str, profile: dict) -> dict | None:
        query_tokens = {t for t in self.tokenize(query)
                        if t not in self.non_subject_tokens and len(t) > 2
                        and any(ch.isalpha() for ch in t)}
        overlap = query_tokens & profile["tokens"].keys()
        # Generic actions, materials and bare numbers cannot establish the
        # object of a service or supply. This conservative eligibility gate
        # sacrifices broad catalog recall; candidates remain unjudged leads.
        coverage = len(overlap) / max(1, len(query_tokens))
        if len(overlap) < min(2, len(query_tokens)) or not overlap or coverage < 0.4:
            return None
        query_service = SERVICE_PREFIX.search(query)
        if query_service:
            source_service = SERVICE_PREFIX.search(profile["retrieval_text"])
            if not source_service:
                return None
            family = lambda m: "maintenance" if m.group("kind").casefold().startswith("техническ") else m.group("kind").casefold()
            if family(query_service) != family(source_service):
                return None
        idf = lambda t: math.log(1 + (len(self.profiles) - self.df[t] + 0.5) / (self.df[t] + 0.5))
        length = sum(profile["tokens"].values())
        score = sum(idf(t) * profile["tokens"][t] * 2.2 /
                    (profile["tokens"][t] + 1.2 * (0.25 + 0.75 * length / max(1, self.average_length))) for t in overlap)
        return {"profile_id": profile["id"], "claim_id": profile["claim_id"],
                "claim_type": profile["claim_type"], "source_ref": profile["source_ref"],
                "source_url": profile["source_url"], "source_excerpt": profile["excerpt"],
                "profile_text": profile["retrieval_text"], "matched_tokens": sorted(overlap),
                "commercial_link_excerpt": profile.get("commercial_link_excerpt"),
                "subject_token_coverage": coverage, "eligibility_rule": "specific_subject_overlap_v1",
                "lexical_score": score, "technical_comparison": (
                    {"status": "unknown", "reason": "license_scope_does_not_confirm_specific_product", "attributes": []}
                    if profile.get("verified_registry") else compare_evidence(query, profile["retrieval_text"])),
                "freshness": profile["freshness"], "reported_page_hash": profile["content_hash"],
                "excerpt_sha256": sha256(profile["excerpt"].encode()).hexdigest(),
                "claim_link_verified": True, "page_content_independently_verified": profile.get("verified_page", False),
                "registry_content_independently_verified": profile.get("verified_registry", False),
                "registry_evidence": profile.get("registry_evidence"),
                "identity": {"status": ("official_registry_identity_evidenced" if profile.get("verified_registry") else
                                         "official_domain_identity_evidenced" if profile.get("verified_page") else "reported_not_independently_verified"),
                             "reported_confidence": profile["identity_confidence"],
                             "evidence": profile.get("identity_evidence", []), "notes": profile.get("identity_notes", [])},
                "reported_evidence_level": profile["evidence_level"], "product_suitability": "unjudged"}

    def evidence_for(self, inn: str, items: list[dict], *, per_item: int = 2) -> list[dict]:
        result = []
        for index, item in enumerate(items):
            matches = [m for p in self.by_inn.get(inn, ()) if (m := self._match(item["product_name"], p))]
            matches.sort(key=lambda m: (-m["lexical_score"], str(m["profile_id"])))
            result.append({"item_index": index, "raw_item": item, "matches": matches[:per_item],
                           "coverage": "unjudged" if matches else "no_matching_external_evidence"})
        return result

    def discover(self, items: list[dict], frozen_inns: set[str], *, limit: int = 10,
                 exclude_inns: set[str] | None = None) -> list[dict]:
        # The legacy discovery call only retrieves cold-start companies. The
        # product overlay excludes shown historical recommendations instead:
        # a known company with useful external evidence must not disappear
        # merely because historical retrieval placed it below the shown TOP K.
        excluded = frozen_inns if exclude_inns is None else exclude_inns
        found = []
        for inn in sorted(self.by_inn):
            if inn in excluded:
                continue
            evidence = self.evidence_for(inn, items)
            scores = [max((m["lexical_score"] for m in e["matches"]), default=0.) for e in evidence]
            if not any(scores):
                continue
            meta = self.by_inn[inn][0]
            found.append({"supplier_inn": inn, "company_name": meta["company_name"] or inn,
                          "ranking_score": None, "evidence_retrieval_score": sum(scores) / max(1, len(scores)),
                          "cold_start": inn not in frozen_inns, "has_working_historical_profile": bool(meta["has_s9_historical"]),
                          "company_role": "unverified", "supplier_suitability": "unjudged",
                          "item_evidence": evidence})
        found.sort(key=lambda x: (-x["evidence_retrieval_score"], x["supplier_inn"]))
        return found[:limit]

    def metadata(self) -> dict:
        cutoff = freshness("", self.as_of)["cutoff"]
        def dated_publication(e):
            stamp = e.get("published_at")
            return bool(stamp and e.get("eligible_for_verified_dated_counter", True)
                        and cutoff <= stamp[:10] <= self.as_of.isoformat())
        return {"version": VERSION, "technical_comparison_version": EVIDENCE_COMPARISON_VERSION, "snapshot_sha256": self.sha256,
                "legacy_external_profiles": self.legacy_profile_count,
                "fresh_companies_sha256": self.fresh_sha256, "fresh_unique_companies": len(self.fresh_companies),
                "additional_reviewed_batches": self.reviewed_batches,
                "registry_batches": self.registry_batches,
                "companies_with_license_evidence": len({p["inn"] for p in self.profiles if p.get("verified_registry")}),
                "external_companies_new_to_full_history": sum(not any(p["has_s9_historical"] for p in profiles) for profiles in self.by_inn.values()),
                "activity_patch": self.activity_patch,
                "fresh_companies_new_to_history": sum(not c["existing_in_history"] for c in self.fresh_companies),
                "fresh_companies_with_dated_publications": sum(any(dated_publication(e) for e in c["activity_evidence"]) for c in self.fresh_companies),
                "fresh_companies_with_self_reported_event_ranges": sum(any(
                    e.get("eligible_for_verified_dated_counter") and e.get("activity_date_range")
                    and cutoff <= e["activity_date_range"]["start"] <= e["activity_date_range"]["end"] <= self.as_of.isoformat()
                    for e in c["activity_evidence"]) for c in self.fresh_companies),
                "external_profiles": len(self.profiles) + len(self.excluded),
                "searchable_profiles": len(self.profiles), "quarantined_profiles": len(self.excluded),
                "quarantine_reasons": dict(Counter(p["quality"]["reason"] for p in self.excluded)),
                "companies_with_searchable_evidence": len(self.by_inn),
                "recency_window_months": 36, "recency_window_policy": "advisory",
                "source_publication_dates_available": any(p["freshness"]["source_published_at"] for p in self.profiles),
                "limitations": ["Historical rank is unchanged", "Legacy S9 identity and page content have not been independently verified",
                                "The 36-month window is advisory; older evidence remains searchable, not presumed current",
                                "Recent fetch does not prove recent source content or ongoing company activity",
                                "Text matching is an evidence lead, not complete lot coverage"]}
