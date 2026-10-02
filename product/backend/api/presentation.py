"""Lossless runtime snapshot -> conservative user-facing evidence projections.

Rank scores are kept as scores; neither role nor complete item coverage is inferred.
"""
from urllib.parse import urlsplit


def safe_url(value):
    if not isinstance(value, str):
        return None
    try:
        parts = urlsplit(value)
        if parts.scheme in ('http', 'https') and parts.hostname and not parts.username and not parts.password:
            return value
    except ValueError:
        pass
    return None


def recommendation(candidate, index, external=False):
    inn = candidate['supplier_inn']
    company_id = 'inn:' + inn
    sources, item_evidence = {}, []
    groups = candidate.get('item_evidence', []) if external else candidate.get('external_item_evidence', [])
    for group in groups:
        for match in group.get('matches', []):
            source_id = str(match['profile_id'])
            fresh = match.get('freshness', {})
            registry = bool(match.get('registry_content_independently_verified'))
            identity_verified = match.get('identity', {}).get('status') in (
                'official_domain_identity_evidenced', 'official_registry_identity_evidenced')
            sources[source_id] = {
                'id': source_id, 'companyId': company_id,
                'title': 'Росздравнадзор: запись лицензии' if registry else 'Официальный источник компании' if identity_verified else 'Внешний источник',
                'kind': 'registry_license' if registry else 'web_page',
                'url': safe_url(match.get('source_url')), 'excerpt': match.get('source_excerpt', ''),
                'fetchedAt': fresh.get('reported_fetched_at'), 'publishedAt': fresh.get('source_published_at'),
                'updatedAt': fresh.get('source_updated_at'), 'available': bool(match.get('page_content_independently_verified') or registry),
                'identityVerified': identity_verified,
                'isExample': False, 'freshness': fresh, 'identity': match.get('identity', {}),
                'contentHash': match.get('reported_page_hash'), 'technicalComparison': match.get('technical_comparison', {}),
                'scope': ('Лицензия № ' + str((match.get('registry_evidence') or {}).get('license_number', 'не указан'))
                          + '; событие лицензии: ' + str(fresh.get('license_event_at') or 'неизвестно')
                          + '. Подтверждён вид деятельности, а не конкретный товар или исполнение новой закупки. '
                          if registry else 'Фрагмент источника; наличие товара и покрытие всей позиции не подтверждены. ')
                         + ('Статус ЕГРЮЛ и включение в МСП не проверены независимо.' if registry
                            else ' '.join(match.get('identity', {}).get('notes', []))),
                'verificationScope': ('Сохранённый официальный ZIP/XML, ИНН и поля лицензии; '
                                      + str((match.get('registry_evidence') or {}).get('source_locator', '')))
                                     if registry else 'Сохранённые байты и связь с ИНН' if match.get('page_content_independently_verified') else 'Заявление исходного каталога без независимой проверки байтов',
            }
        matches = group.get('matches', [])
        item_evidence.append({'itemId': str(group['item_index'] + 1), 'kind': 'catalog' if matches else 'none',
                              'sourceId': str(matches[0]['profile_id']) if matches else None,
                              'reason': comparison_reason([m.get('technical_comparison', {}) for m in matches]) if matches else 'Подходящего внешнего основания не найдено.',
                              'technicalStatus': technical_status([m.get('technical_comparison', {}) for m in matches]),
                              'raw': group})
    history = []
    for value in candidate.get('evidence', []):
        source_id = 'history:' + str(value['lot_id'])
        history.append({'id': source_id, 'lotId': str(value['lot_id']), 'date': value.get('publish_date', ''),
                        'subject': value.get('subject', ''), 'observedStatus': 'Наблюдаемый участник', 'url': None})
        sources[source_id] = {'id': source_id, 'companyId': company_id, 'title': 'Историческая закупка ' + str(value['lot_id']),
                             'url': None, 'excerpt': value.get('subject', ''), 'fetchedAt': None,
                             'publishedAt': value.get('publish_date'), 'available': True, 'identityVerified': False,
                             'isExample': False, 'scope': 'Участие в лоте с похожими ТРУ; исполнение и поставка каждой позиции не доказаны.'}
    for group in candidate.get('historical_item_evidence', []):
        fragments = group.get('historical_fragments', [])
        if fragments:
            item_evidence.append({'itemId': str(group['item_index'] + 1), 'kind': 'history',
                                  'sourceId': 'history:' + str(fragments[0]['lot_id']),
                                  'reason': 'Похожая позиция в истории участия. ' + comparison_reason([f.get('technical_comparison', {}) for f in fragments]),
                                  'technicalStatus': technical_status([f.get('technical_comparison', {}) for f in fragments]), 'raw': group})
    # One row per TRU: absent external evidence must not hide an existing historical fragment.
    by_item = {}
    for evidence in item_evidence:
        old = by_item.get(evidence['itemId'])
        if old is None or old['kind'] == 'none':
            by_item[evidence['itemId']] = evidence
        elif evidence['kind'] != 'none':
            old['technicalStatus'] = technical_status([{'status': old['technicalStatus']}, {'status': evidence['technicalStatus']}])
            old['reason'] += ' ' + evidence['reason']
            old['raw'] = {'external': old['raw'], 'historical': evidence['raw']}
    item_evidence = list(by_item.values())
    company = {'id': company_id, 'name': candidate.get('company_name') or 'ИНН ' + inn, 'inn': inn,
               'kpp': None, 'region': None, 'website': next((s['url'] for s in sources.values() if s['url'] and s.get('kind') != 'registry_license'), None),
               'origin': 'discovered' if external else 'history',
               'role': {'role': 'unknown', 'verified': False, 'basis': 'Роль компании не подтверждена.',
                        'scope': 'Не определяется по названию, ОКВЭД или участию.', 'sourceId': None},
               'sources': list(sources.values()), 'history': history,
               'newToFullHistory': bool(candidate.get('new_to_full_history', False)),
               'newToFrozenHistory': bool(candidate.get('cold_start', False))}
    score = candidate.get('evidence_retrieval_score') if external else candidate.get('scoring', {}).get('score')
    reason = ('В источниках компании найдены сведения, связанные с запросом.' if external
              else 'В истории участия компании есть закупки с похожими товарами или услугами.')
    neighbor_support = candidate.get('reasons', {}).get('neighbor_lot_evidence')
    if not external and type(neighbor_support) in (int, float) and 0 < neighbor_support <= 1:
        reason += ' Есть историческая поддержка по похожим закупкам с участием компании.'
    explanation = business_explanation(candidate, item_evidence, list(sources.values()), external)
    return {'company': company, 'rank': index + 1, 'score': score,
            'scoreKind': 'external_retrieval' if external else 'historical_rank',
            'reason': reason, **explanation,
            'evidence': item_evidence, 'rawEvidence': candidate}


def technical_status(comparisons):
    statuses = [x.get('status', 'unknown') for x in comparisons]
    # A conflict is never hidden by a different matching fragment.
    if 'conflict' in statuses:
        return 'conflict'
    if statuses and all(value == 'match' for value in statuses):
        return 'match'
    return 'unknown'


def comparison_reason(comparisons):
    conflicts = [a.get('query_attribute', {}).get('raw', '') for c in comparisons for a in c.get('attributes', []) if a.get('status') == 'conflict']
    if conflicts:
        return 'Обнаружены противоречия в характеристиках: ' + ', '.join(dict.fromkeys(conflicts)) + '. Полное соответствие не подтверждено.'
    if technical_status(comparisons) == 'match':
        return 'Есть совпадения явно указанных характеристик. Соответствие всей позиции и наличие не подтверждены.'
    return 'Есть связанное основание, но данных недостаточно для подтверждения всех характеристик.'


def result_projection(result):
    if not result:
        return {'recommendations': [], 'externalCandidates': []}
    lot = result['lots'][0]
    return {'recommendations': [recommendation(c, i) for i, c in enumerate(lot.get('recommendations', []))],
            'externalCandidates': [recommendation(c, i, True) for i, c in enumerate(lot.get('new_supplier_candidates', []))]}


def merge_companies(companies):
    """Deduplicate identities within owned results without fabricating attributes."""
    by_id = {}
    for value in companies:
        if value['id'] not in by_id:
            by_id[value['id']] = dict(value, sources=list(value['sources']), history=list(value['history']))
            continue
        previous = by_id[value['id']]
        for key in ('sources', 'history'):
            items = {item['id']: item for item in previous[key]}
            items.update({item['id']: item for item in value[key]})
            previous[key] = list(items.values())
        if previous['name'].startswith('ИНН ') and not value['name'].startswith('ИНН '):
            previous['name'] = value['name']
        previous['website'] = previous['website'] or value['website']
    return list(by_id.values())


def business_explanation(candidate, evidence, sources, external=False):
    """Describe observed ranking signals, never calibrated confidence or a full match."""
    reasons = candidate.get('reasons') or {}
    criteria = []
    def positive(key):
        value = reasons.get(key)
        return type(value) in (int, float) and 0 < value <= 1
    def add(code, label, basis, source_ids=(), status='support'):
        criteria.append({'code': code, 'label': label, 'basis': basis,
                         'sourceIds': list(dict.fromkeys(source_ids)), 'status': status})
    historical_ids = [s['id'] for s in sources if s['id'].startswith('history:')]
    if not external:
        if positive('text_association') or any(e['kind'] == 'history' for e in evidence):
            add('similar_items', 'Похожие товары или услуги в истории участия',
                'Описание закупки сопоставлено с наименованиями в прошлых закупках компании.', historical_ids)
        if positive('okpd2_association'):
            add('related_category', 'Связь с категорией ОКПД2',
                'Категория помогает найти кандидата; сама по себе не подтверждает нужный товар или услугу.')
        if positive('technical_token_overlap'):
            add('shared_designations', 'Общие обозначения в описаниях',
                'В текстах найдены общие технические обозначения. Точные характеристики проверяются отдельно.')
        if positive('neighbor_lot_evidence'):
            add('similar_procurements', 'Участие в похожих закупках',
                'Есть историческая поддержка по похожим закупкам с участием компании.', historical_ids)
    else:
        licenses = [s['id'] for s in sources if s.get('kind') == 'registry_license']
        pages = [s['id'] for s in sources if s.get('kind') == 'web_page']
        if pages:
            add('external_information', 'Связанные сведения во внешних источниках',
                'Найдены связанные фрагменты сайта или каталога. Наличие товара и условия поставки требуют уточнения.', pages)
        if licenses:
            add('licensed_activity', 'Подтверждён лицензируемый вид деятельности',
                'Лицензия подтверждает указанный вид деятельности, но не предложение конкретного товара.', licenses)
    conflicts = [e for e in evidence if e.get('technicalStatus') == 'conflict']
    if conflicts:
        add('technical_conflict', 'Есть противоречия в характеристиках',
            'Проверьте отмеченные позиции до обращения к компании.',
            [e['sourceId'] for e in conflicts if e.get('sourceId')], 'conflict')
    if not criteria:
        add('needs_review', 'Основания требуют уточнения',
            'Недостаточно раскрытых сведений для подтверждения соответствия закупке.', status='unknown')
    summary = ('Кандидат найден по сведениям внешних источников.' if external else
               'Кандидат найден по похожим товарам, услугам и закупкам в истории участия.')
    if conflicts:
        summary += ' В характеристиках есть противоречия.'
    notes = ['Уточните наличие, условия поставки и соответствие каждой позиции закупки.',
             'Место в списке показывает порядок проверки кандидатов; это не вероятность успешной поставки.']
    if external and any(s.get('kind') == 'registry_license' for s in sources):
        notes.append('Лицензия не подтверждает ассортимент и юридический статус компании.')
    return {'explanationSummary': summary, 'explanationCriteria': criteria, 'explanationNotes': notes}
