"""Public supplier facts, independently versioned from ranking and owned snapshots.

Only a local collector writes this file. HTTP never fetches arbitrary URLs and no
public catalog lookup bypasses owned query/company membership in services.py.
"""
import copy
import hashlib
import json
import logging
import re
import threading
from pathlib import Path
from django.conf import settings
from .presentation import safe_url

FIELDS = ('name', 'description', 'ogrn', 'kpp', 'region', 'website', 'contacts', 'activities', 'legalStatus')
MAX_CATALOG_BYTES = 48 * 1024 * 1024
MAX_PROFILES = 60000
_LOCK = threading.Lock()
_CACHE = {}
log = logging.getLogger('supply.audit')


def canonical_inn(value):
    value = value.strip() if isinstance(value, str) else ''
    return value if re.fullmatch(r'(?:[0-9]{10}|[0-9]{12})', value) else None


def empty_field():
    return {'value': None, 'status': 'unknown', 'sourceIds': [], 'observedAt': None}


def _string(value, limit=2000):
    return value[:limit] if isinstance(value, str) and '\x00' not in value else None


def _source(value, inn):
    if not isinstance(value, dict) or not _string(value.get('id'), 256):
        return None
    digest = value.get('contentHash')
    hashed = isinstance(digest, str) and bool(re.fullmatch('[a-fA-F0-9]{64}', digest))
    identity = value.get('identityVerified') is True and canonical_inn(value.get('identityInn')) == inn and hashed
    return {'id': _string(value['id'], 256), 'url': safe_url(value.get('url')),
            'title': _string(value.get('title'), 400) or 'Источник сведений о компании',
            'excerpt': _string(value.get('excerpt'), 6000) or '',
            'fetchedAt': _string(value.get('fetchedAt'), 64), 'publishedAt': _string(value.get('publishedAt'), 64),
            'contentDate': _string(value.get('contentDate'), 64), 'dateSemantics': _string(value.get('dateSemantics'), 300),
            'contentHash': digest.lower() if hashed else None,
            'hashScope': _string(value.get('hashScope'), 300), 'sourceArchiveHash': _string(value.get('sourceArchiveHash'), 64),
            'identityVerified': identity,
            'identityInn': inn if identity else None, 'scope': _string(value.get('scope'), 2500) or '',
            'locator': _string(value.get('locator') or value.get('jsonLocator'), 500), 'kind': _string(value.get('kind'), 80),
            'identityBasisSourceIds': [v[:256] for v in value.get('identityBasisSourceIds', []) if isinstance(v, str)][:10]
                if isinstance(value.get('identityBasisSourceIds', []), list) else []}


def _value(name, value):
    if name in ('contacts', 'activities'):
        if not isinstance(value, list) or len(value) > 100:
            return None
        clean = []
        for item in value:
            if isinstance(item, str):
                clean.append(_string(item, 1500))
            elif isinstance(item, dict):
                # No arbitrary nested objects, HTML interpretation, or executable URL schemes.
                permitted = ('kind', 'value', 'text', 'scope', 'sourceIds')
                row = {k: (_string(item[k], 1500) if k != 'sourceIds' else
                           [v[:256] for v in item[k] if isinstance(v, str)][:50])
                       for k in permitted if k in item and (k != 'sourceIds' or isinstance(item[k], list))}
                if row:
                    clean.append(row)
        return clean or None
    if name == 'website':
        return safe_url(value)
    if name in ('ogrn', 'kpp'):
        value = _string(value, 32)
        pattern = r'(?:[0-9]{13}|[0-9]{15})' if name == 'ogrn' else r'[0-9]{9}'
        return value if value and re.fullmatch(pattern, value) else None
    value = _string(value, 5000 if name == 'description' else 500)
    return value.strip() if value and value.strip() else None


def validate_profile(value, version, catalog_hash, generated_at):
    if not isinstance(value, dict) or not (inn := canonical_inn(value.get('inn'))):
        return None
    raw_sources = value.get('sources', [])
    if not isinstance(raw_sources, list) or len(raw_sources) > 100:
        return None
    sources = [source for item in raw_sources if (source := _source(item, inn))]
    if len({s['id'] for s in sources}) != len(sources):
        return None
    by_id = {s['id']: s for s in sources}
    raw_fields = value.get('fields', {})
    if not isinstance(raw_fields, dict):
        return None
    fields = {}
    for name in FIELDS:
        raw = raw_fields.get(name, {})
        if not isinstance(raw, dict):
            raw = {}
        field = empty_field()
        field['value'] = _value(name, raw.get('value'))
        references = raw.get('sourceIds', [])
        if isinstance(references, list):
            field['sourceIds'] = list(dict.fromkeys(v for v in references if isinstance(v, str) and v in by_id))[:50]
        status = raw.get('status', 'unknown')
        field['status'] = status if status in ('verified', 'unverified', 'unknown', 'conflict') else 'unknown'
        field['observedAt'] = _string(raw.get('observedAt'), 64)
        if field['value'] is None:
            field = empty_field()
        elif field['status'] == 'verified' and (not field['sourceIds'] or
                not all(by_id[key]['identityVerified'] for key in field['sourceIds'])):
            field['status'] = 'unverified'
        if name == 'legalStatus' and field['status'] == 'verified':
            from urllib.parse import urlsplit
            if not all(by_id[key].get('scope') == 'official_tax_registry_identity'
                       and urlsplit(by_id[key].get('url') or '').hostname == 'pb.nalog.ru' for key in field['sourceIds']):
                field = empty_field()
        fields[name] = field
    verified = [name for name, field in fields.items() if field['status'] == 'verified']
    content = {'inn': inn, 'fields': fields, 'sources': sources}
    digest = hashlib.sha256(json.dumps(content, sort_keys=True, ensure_ascii=False, separators=(',', ':')).encode()).hexdigest()
    return {**content, 'version': version, 'contentHash': digest, 'catalogHash': catalog_hash,
            'updatedAt': generated_at, 'profileStatus': 'verified_identity' if 'name' in verified else 'partial' if verified else 'pending',
            'completeness': {'verifiedFields': len(verified), 'totalFields': len(FIELDS),
                             'missingFields': [name for name in FIELDS if name not in verified]},
            'scope': 'Сведения о компании. Не меняют порядок рекомендаций и не подтверждают исполнение закупки.',
            'legalStatus': {**fields['legalStatus'], 'reason': 'Статус воспроизводится только по прямому первичному свидетельству ФНС; лицензия или дата загрузки его не определяют.'}}


def _path():
    configured = getattr(settings, 'COMPANY_PROFILE_CATALOG', None)
    if configured is None:
        import os
        configured = os.environ.get('SUPPLY_COMPANY_PROFILE_CATALOG')
    return Path(configured) if configured else settings.REPO / 'local/enrichment-all-suppliers-2026-10-02/supplier_profiles.json'


def catalog():
    """Atomic replacement + mtime cache; a broken new batch never becomes verified data."""
    path = _path()
    try:
        stat = path.stat()
        key = (str(path), stat.st_ino, stat.st_mtime_ns, stat.st_size)
    except OSError:
        return {'status': 'unavailable', 'version': None, 'profiles': {}, 'hash': None, 'generatedAt': None}
    with _LOCK:
        if _CACHE.get('key') == key:
            return _CACHE['value']
        try:
            if stat.st_size > MAX_CATALOG_BYTES:
                raise ValueError('Catalog exceeds bound')
            with path.open('rb') as handle:
                raw = handle.read(MAX_CATALOG_BYTES + 1)
            if len(raw) > MAX_CATALOG_BYTES:
                raise ValueError('Catalog exceeds bound')
            doc = json.loads(raw, parse_constant=lambda _: (_ for _ in ()).throw(ValueError('Non-finite JSON')))
            if doc.get('schemaVersion') != 'supplier-profile.v1' or not isinstance(doc.get('profiles'), list) or len(doc['profiles']) > MAX_PROFILES:
                raise ValueError('Invalid schema')
            version = _string(doc.get('version'), 200)
            if not version:
                raise ValueError('Missing version')
            digest = hashlib.sha256(raw).hexdigest()
            generated = _string(doc.get('generatedAt'), 64)
            profiles = {}
            for record in doc['profiles']:
                profile = validate_profile(record, version, digest, generated)
                if profile is None or profile['inn'] in profiles:
                    raise ValueError('Invalid/duplicate identity')
                profiles[profile['inn']] = profile
            value = {'status': 'available', 'version': version, 'profiles': profiles, 'hash': digest, 'generatedAt': generated}
        except (OSError, ValueError, TypeError, AttributeError, RecursionError) as exc:
            log.warning('company_profile_catalog_unavailable type=%s', type(exc).__name__)
            value = {'status': 'invalid', 'version': None, 'profiles': {}, 'hash': None, 'generatedAt': None}
        _CACHE.clear()
        _CACHE.update(key=key, value=value)
        return value


def offline_profiles(inns):
    source = catalog()
    profiles = {}
    for raw_inn in inns:
        inn = canonical_inn(raw_inn)
        if not inn:
            continue
        known = source['profiles'].get(inn)
        if known:
            profile = copy.deepcopy(known)
        else:
            profile = validate_profile({'inn': inn, 'fields': {}, 'sources': []}, source['version'], source['hash'], source['generatedAt'])
        profile['catalogStatus'] = source['status']
        profiles[inn] = profile
    return profiles




def _observed_date(value):
    from datetime import datetime, timezone
    try:
        parsed = datetime.fromisoformat(value.replace('Z', '+00:00'))
        return parsed.replace(tzinfo=timezone.utc) if parsed.tzinfo is None else parsed
    except (ValueError, AttributeError, TypeError):
        return None


def _primary_tax_fact(profile, field):
    from urllib.parse import urlsplit
    ids = field.get('sourceIds', [])
    sources = {s['id']: s for s in profile.get('sources', [])}
    return bool(ids) and all(sources.get(key, {}).get('scope') == 'official_tax_registry_identity'
        and sources[key].get('identityVerified')
        and urlsplit(sources[key].get('url') or '').hostname == 'pb.nalog.ru' for key in ids)

def current_profiles(inns):
    profiles = offline_profiles(inns)
    from .models import LiveSupplierProfile, SourceRefreshJob
    for saved in LiveSupplierProfile.objects.filter(inn__in=profiles):
        base, live = profiles[saved.inn], saved.profile
        live_sources = [s for s in live.get('sources', []) if s['id'].startswith('live:')]
        live_ids = {s['id'] for s in live_sources}
        # Older registry/name assertions from a live copy cannot overwrite a newer catalog.
        fields = copy.deepcopy(base['fields'])
        for name, field in live.get('fields', {}).items():
            ids = set(field.get('sourceIds', []))
            if name in FIELDS and fields[name]['status'] != 'conflict' and field.get('status') == 'verified' and ids and ids <= live_ids:
                previous = fields[name]
                if name in ('name', 'ogrn', 'kpp', 'legalStatus') and previous['status'] == 'verified' and _primary_tax_fact(base, previous):
                    continue
                before, after = _observed_date(previous.get('observedAt')), _observed_date(field.get('observedAt'))
                if previous['status'] == 'verified' and before and after and before > after:
                    continue
                fields[name] = copy.deepcopy(field)
        fresh_activities = [v for v in live.get('fields', {}).get('activities', {}).get('value', []) or []
                            if isinstance(v, dict) and v.get('sourceIds') and set(v['sourceIds']) <= live_ids]
        if fresh_activities and fields['activities']['status'] != 'conflict':
            previous = base['fields']['activities']
            retained = previous.get('value') or []
            values = list({json.dumps(v, sort_keys=True, ensure_ascii=False): v for v in retained + fresh_activities}.values())
            ids = list(dict.fromkeys(previous.get('sourceIds', []) + [sid for v in fresh_activities for sid in v['sourceIds']]))
            fields['activities'] = {'value': values, 'status': 'verified', 'sourceIds': ids, 'observedAt': previous.get('observedAt')}
        if live_sources:
            combined = {'inn': saved.inn, 'fields': fields, 'sources': base['sources'] + live_sources}
            profile = validate_profile(combined, live['version'], base['catalogHash'], saved.checked_at.isoformat())
            if profile:
                profile['catalogStatus'] = base['catalogStatus']
                profile['offlineCatalogVersion'] = base['version']
                profile['liveCheckedAt'] = saved.checked_at.isoformat()
                profiles[saved.inn] = profile
    for job in SourceRefreshJob.objects.filter(inn__in=profiles):
        profiles[job.inn]['refresh'] = {'id': str(job.pk), 'status': job.status, 'message': job.message,
            'checkedAt': job.checked_at.isoformat() if job.checked_at else None,
            'nextAllowedAt': job.next_allowed_at.isoformat() if job.next_allowed_at else None,
            'checkKind': 'catalog_lookup' if job.status == 'needs_source' else 'official_site'}
    return profiles

def snapshot_for_result(result):
    inns = [c.get('supplier_inn') for lot in result.get('lots', [])
            for key in ('recommendations', 'new_supplier_candidates') for c in lot.get(key, [])]
    profiles = current_profiles(inns)
    return {'schemaVersion': 'supplier-profile-snapshot.v1', 'profiles': profiles}


def attach_company_profiles(companies, saved=None, live=True, summary=False):
    saved = (saved or {}).get('profiles', {})
    latest = current_profiles([c['inn'] for c in companies]) if live else {}
    from .company_history import history_for, diligence
    histories = history_for([c['inn'] for c in companies])
    for company in companies:
        inn = company['inn']
        frozen = copy.deepcopy(saved.get(inn))
        current = latest.get(inn)
        company['profileAtCalculation'] = frozen
        company['currentProfile'] = current
        company['sourceRefresh'] = current.get('refresh') if current else None
        company['historySummary'] = histories.get(inn)
        company['dueDiligence'] = diligence(current or frozen, histories.get(inn))
        company['displayName'] = company['name']
        company['displayNameSource'] = 'result_snapshot'
        for label, profile in [('calculation_profile', frozen), ('current_profile', current)]:
            field = profile.get('fields', {}).get('name', {}) if profile else {}
            if field.get('status') == 'verified' and field.get('value'):
                company['displayName'], company['displayNameSource'] = field['value'], label
        if summary:
            for profile in (frozen, current):
                if profile:
                    profile['sources'] = []
    return companies
