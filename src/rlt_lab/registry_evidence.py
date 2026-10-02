"""Verified official-license evidence, distinct from website product offers.

The caller pins the immutable batch hash. Its saved primary ZIP hashes and all
company/record hashes are checked locally; no registry data is sent over a network.
"""
from __future__ import annotations
from collections import Counter
from datetime import date
import hashlib
import json
from pathlib import Path
import re
from urllib.parse import urlsplit

SCHEMA = 'rlt.registry-license-batch.v1'
LIMITATIONS = [
    'Лицензия подтверждает только перечисленные виды деятельности; конкретный товар, модель, наличие, цена и сроки не подтверждены.',
    'Отсутствие записи о приостановке или прекращении в выгрузке не является проверкой действующего юридического статуса по ЕГРЮЛ.',
    'Адрес лицензируемой деятельности не доказывает доставку или обслуживание по адресу новой закупки.',
    'Второе подтверждение ФНС МСП заявлено коллегой и не воспроизведено в этом импорте.',
]

def _digest(path):
    digest=hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda:stream.read(1048576),b''): digest.update(block)
    return digest.hexdigest()

def load_registry_batch(path: Path, expected_sha256: str, tokenize, as_of: date) -> tuple[list[dict], dict]:
    """Return profiles plus registry-only counters, compatible with ExternalCatalog.

    Duplicate company INNs across website/registry sources are allowed and must
    be merged by INN by the caller. Profile IDs are registry-specific. Registry
    profiles never supply historical OKPD features or a calibrated ranking score.
    """
    from .external_evidence import freshness, profile_quality, valid_inn
    path=Path(path).resolve()
    if _digest(path)!=expected_sha256: raise ValueError('Registry batch hash mismatch')
    batch=json.loads(path.read_text(encoding='utf-8'))
    if batch.get('schema')!=SCHEMA: raise ValueError('Unsupported registry batch schema')
    if len(batch['companies'])>10000: raise ValueError('Registry batch limit exceeded')
    source_by_hash={s['sha256']:s for s in batch['sources']}
    checked=set();profiles=[];seen=set();future_count=0
    for company in batch['companies']:
        inn=company['inn'];record=company['record']
        if not valid_inn(inn) or inn in seen or inn!=record['inn']: raise ValueError('Invalid or duplicate registry identity')
        seen.add(inn)
        source_sha=company['source_file_sha256']
        source=source_by_hash.get(source_sha)
        if not source or company['source_url']!=source['url']: raise ValueError('Registry source link mismatch')
        url=urlsplit(company['source_url'])
        if url.scheme!='https' or url.hostname!='www.roszdravnadzor.gov.ru' or not url.path.startswith('/opendata/'): raise ValueError('Unexpected registry authority')
        payload=(path.parent/company['source_payload_path']).resolve()
        if not payload.is_relative_to(path.parent) or payload.stat().st_size>100*1024*1024: raise ValueError('Unsafe registry evidence path')
        if source_sha not in checked:
            if _digest(payload)!=source_sha: raise ValueError('Official ZIP hash mismatch')
            checked.add(source_sha)
        if hashlib.sha256(record['raw_xml_reserialized'].encode()).hexdigest()!=record['record_xml_sha256']: raise ValueError('Registry XML element hash mismatch')
        if any(record['status_fields'].values()): raise ValueError('Registry record has adverse license fields')
        if any(' '.join(fragment.split()) not in record['works'] for fragment in company['scope'].split('; ')): raise ValueError('Unsupported registry scope')
        if not re.fullmatch(r'licenses\[[1-9]\d*\]',company['source_locator']) or company['source_record_index_base']!=1: raise ValueError('Registry source locator must be one based')
        text=company['scope']
        stamp=freshness(company['source_fetched_at'],as_of)
        event_day=date.fromisoformat(record['event_date'])
        stamp.update({'source_published_at':None,'source_updated_at':None,
            'license_event_at':record['event_date'], 'license_event_xml_fields':record['event_date_xml_fields'],
            'source_date_scope':'license_event_not_product_offer_or_contract',
            'source_date_status':'official_xml_license_event',
            'content_recency':'license_event_within_window' if date.fromisoformat(stamp['cutoff'])<=event_day<=as_of else 'license_event_before_window',
            'company_activity':'licensed_activity_in_official_snapshot_not_live_legal_status',
            'activity_definition':'Дата лицензии/изменения лицензии, не дата исполнения контракта и не публикация товарного каталога'})
        quality=profile_quality(text,company['source_url'])
        quality['offer_semantics']='licensed_category_capability'
        if event_day>as_of or stamp['fetch_after_as_of']:
            quality={'eligible_for_search':False,'reason':'registry_evidence_after_as_of','offer_semantics':'licensed_category_capability'}
            stamp['content_recency']='source_date_after_as_of';future_count+=1
        identity_evidence=[{'url':company['source_url'],'retrieved_at':company['source_fetched_at'],'sha256':source_sha,
            'hash_scope':'Official ZIP response body; exact license element pinned separately',
            'excerpt':f"full_name_licensee={record['name']}; inn={inn}; ogrn={record['ogrn']}",
            'excerpt_representation':'XML field projection, not a verbatim website quote',
            'source_locator':company['source_locator'],'source_record_index_base':1,
            'record_xml_sha256':record['record_xml_sha256'],'license_number':record['license_number']}]
        profiles.append({'id':f"registry:{company['source_kind']}:{inn}",'inn':inn,'retrieval_text':text,'excerpt':text,
            'source_url':company['source_url'],'source_ref':'official_registry_license_xml','fetched_at':company['source_fetched_at'],
            'content_hash':source_sha,'identity_confidence':'official_registry_identity_evidenced',
            'evidence_level':'saved_primary_registry_xml','company_name':record['short_name'] or record['name'],
            'has_s9_historical':company['existing_in_history'],'claim_id':f"registry:{company['source_kind']}:{inn}",
            'claim_type':'licensed_category_capability','quality':quality,'freshness':stamp,'tokens':Counter(tokenize(text)),
            'verified_page':False,'verified_registry':True,'identity_evidence':identity_evidence,
            'identity_notes':LIMITATIONS,'company_role':company['role'],
            'registry_evidence':{'license_number':record['license_number'],'source_locator':company['source_locator'],
                'source_record_index_base':1,'record_xml_sha256':record['record_xml_sha256'],'licensed_workplaces':record['licensed_workplaces'],
                'status_fields':record['status_fields'],'legal_status':'not_independently_egrul_verified','validated_okpd':[],
                'msp_match_independently_verified':False,'license_event_at':record['event_date'],'capability_scope':text},
        })
    metadata={'schema':SCHEMA,'batch_sha256':expected_sha256,'companies_with_license_evidence':len(seen),
        'registry_profiles':len(profiles),'searchable_registry_profiles':sum(p['quality']['eligible_for_search'] for p in profiles),
        'quarantined_registry_profiles':sum(not p['quality']['eligible_for_search'] for p in profiles),
        'companies_new_to_full_history':sum(not c['existing_in_history'] for c in batch['companies']),
        'companies_already_in_previous_external_catalog':sum(c['existing_in_external_catalog'] for c in batch['companies']),
        'license_event_within_36_months':sum(p['freshness']['content_recency']=='license_event_within_window' for p in profiles),
        'source_counts':dict(Counter(c['source_kind'] for c in batch['companies'])),
        'sources':[{'url':s['url'],'sha256':s['sha256'],'fetched_at':s['fetched_at']} for s in batch['sources']],
        'validated_okpd_entries':0,'independent_msp_confirmations':0,'recency_window_policy':'advisory',
        'historical_features_changed':False,'limitations':LIMITATIONS}
    return profiles,metadata
