"""Owned inputs, immutable result snapshots and account-scoped projections."""
import csv
import hashlib
import io
import json
from pathlib import Path
import re
import sys
import tempfile
from collections import Counter
from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone
from .models import User, Query, ImportBatch, Mutation, ExportRecord, InferenceJob
from .presentation import result_projection, merge_companies
from .company_profiles import attach_company_profiles

sys.path.insert(0, str(settings.REPO / 'src'))
from rlt_lab.input import read_procurements
from rlt_lab.data import ITEM_COLUMNS, NOTICE_COLUMNS

MAX_FILE = 10 * 1024 * 1024
MAX_LOTS = 100
MAX_ITEMS = 10000
MAX_QUERIES = 1000

class ApiProblem(Exception):
    def __init__(self, code, message, status=422, fields=None):
        self.code, self.message, self.status, self.fields = code, message, status, fields

def require_dict(value, allowed, required=()):
    if not isinstance(value, dict) or set(value) - set(allowed) or set(required) - set(value):
        raise ApiProblem('INVALID_FIELDS', 'Проверьте обязательные поля и структуру запроса.')
    return value

def text(value, field, maximum=10000, blank=True):
    if not isinstance(value, str) or len(value) > maximum or '\x00' in value or (not blank and not value.strip()):
        raise ApiProblem('INVALID_FIELD', f'Проверьте поле {field}.', fields={field: 'Недопустимое значение.'})
    return value

def query_json(q, summary=False):
    try:
        job = q.inference_job
    except InferenceJob.DoesNotExist:
        job = None
    state = None if job is None else {'id': str(job.pk), 'status': job.status, 'attempts': job.attempts,
            'createdAt': job.created_at.isoformat(), 'startedAt': job.started_at.isoformat() if job.started_at else None,
            'finishedAt': job.finished_at.isoformat() if job.finished_at else None,
            'message': job.message, 'errorCode': job.error_code or None}
    projection = result_projection(q.result)
    attach_company_profiles([r['company'] for r in projection['recommendations'] + projection['externalCandidates']],
                            q.company_profiles, summary=summary)
    refresh_jobs = {r['company']['sourceRefresh']['id']: r['company']['sourceRefresh']
                    for r in projection['recommendations'] + projection['externalCandidates'] if r['company'].get('sourceRefresh')}
    refresh_counts = dict(Counter(job['status'] for job in refresh_jobs.values()))
    if summary:
        for candidate in projection['recommendations'] + projection['externalCandidates']:
            candidate.pop('rawEvidence', None)
            candidate['evidence'] = []
            candidate['company']['sources'] = []
            candidate['company']['history'] = []
    return {'id': str(q.pk), 'draftId': q.draft_id, 'importId': str(q.batch_id) if q.batch_id else None,
            'procurement': q.procurement, 'status': job.status if job else 'awaiting_engine', 'createdAt': q.created_at.isoformat(),
            'resultVersion': q.result_version, **projection, 'warnings': q.warnings,
            'saved': q.saved, 'exported': q.exported, 'rawNotice': {} if summary else q.raw_notice, 'rawItems': [] if summary else q.raw_items,
            'job': state, 'processedAt': q.completed_at.isoformat() if q.completed_at else None,
            'modelVersion': q.result.get('lots', [{}])[0].get('feature_version') if q.result else None,
            'catalogVersion': q.result.get('external_catalog', {}).get('version'), 'runtimeResult': None if summary else q.result or None,
            'isSummary': summary,
            'sourceRefresh': {'jobs': list(refresh_jobs.values()), 'counts': refresh_counts,
                              'scope': 'Обновляются только проверенные официальные сайты; подбор не пересчитывается.'},
            'message': job.message if job else 'Входные данные сохранены. Запустите подбор.'}

def owned(model, owner, pk):
    try:
        queryset = model.objects.filter(owner=owner, pk=pk)
        if model is Query:
            queryset = queryset.select_related('inference_job')
        value = queryset.first()
    except (ValueError, TypeError, ValidationError):
        value = None
    if value is None:
        raise ApiProblem('NOT_FOUND', 'Запись не найдена.', 404)
    return value

def idempotent(owner, scope, key, payload, operation):
    if not isinstance(key, str) or not re.fullmatch(r'[A-Za-z0-9_.:-]{8,128}', key):
        raise ApiProblem('IDEMPOTENCY_KEY_REQUIRED', 'Для сохранения требуется Idempotency-Key (8-128 символов).', 400)
    digest = hashlib.sha256(json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(',', ':')).encode()).hexdigest()
    # IMMEDIATE on SQLite serializes the short write transaction before reading the key.
    # The database unique constraint is the final invariant under all adapters.
    with transaction.atomic():
        User.objects.select_for_update().get(pk=owner.pk)
        prior = Mutation.objects.filter(owner=owner, scope=scope, key=key).first()
        if prior:
            if prior.digest != digest:
                raise ApiProblem('IDEMPOTENCY_CONFLICT', 'Этот ключ уже использован для другого запроса.', 409)
            return prior.response, prior.status
        response, status = operation()
        Mutation.objects.create(owner=owner, scope=scope, key=key, digest=digest, response=response, status=status)
        return response, status

def check_quota(owner, additional):
    if Query.objects.filter(owner=owner).count() + additional > MAX_QUERIES:
        raise ApiProblem('ACCOUNT_LIMIT', f'Локальный предел: {MAX_QUERIES} запросов на аккаунт.', 413)

def manual_query(owner, data):
    require_dict(data, ['draft'], ['draft'])
    draft = require_dict(data['draft'], ['id', 'mode', 'text', 'codes', 'region', 'price', 'updatedAt'], ['mode'])
    if draft['mode'] not in ('text', 'codes'):
        raise ApiProblem('INVALID_MODE', 'Для файлов используйте загрузку двух CSV.')
    description = text(draft.get('text', ''), 'text').strip()
    codes = draft.get('codes', [])
    if not isinstance(codes, list) or len(codes) > 100 or any(not isinstance(c, str) or not re.fullmatch(r'\d{2}(?:\.\d{1,3}){0,3}', c) for c in codes):
        raise ApiProblem('INVALID_CODES', 'Укажите коды ОКПД2 в цифровом формате через точку.')
    if not description and not codes:
        raise ApiProblem('EMPTY_DRAFT', 'Добавьте описание или код ОКПД2.')
    region = text(draft.get('region', ''), 'region', 200)
    price = text(draft.get('price', ''), 'price', 30)
    if price and not re.fullmatch(r'\d{1,18}(?:[.,]\d{1,2})?', price):
        raise ApiProblem('INVALID_PRICE', 'Цена должна быть неотрицательным числом с максимум двумя знаками после запятой.')
    draft_id = text(draft.get('id', ''), 'id', 128) or None
    check_quota(owner, 1)
    procurement = {'lotId': '', 'subject': description or 'Ручной ввод по ОКПД2', 'source': 'Ручной ввод',
                   'publishDate': None, 'price': price or None, 'customerInn': None, 'customerName': None, 'region': region,
                   'items': [{'id': str(i + 1), 'name': description, 'okpd2': c, 'quantity': None} for i, c in enumerate(codes)]}
    if not procurement['items']:
        procurement['items'] = [{'id': '1', 'name': description, 'okpd2': None, 'quantity': None}]
    q = Query.objects.create(owner=owner, procurement=procurement, draft_id=draft_id,
                             warnings=['Ручной ввод не заменяет исходные строки CSV.'])
    return query_json(q), 201

def parse_import(data):
    require_dict(data, ['notices', 'items', 'files'], ['notices', 'items'])
    for field in ('notices', 'items'):
        text(data[field], field, MAX_FILE)
        if len(data[field].encode('utf-8')) > MAX_FILE:
            raise ApiProblem('FILE_TOO_LARGE', 'Каждый CSV должен быть не больше 10 МиБ.', 413)
    files = data.get('files', ['Закупки.csv', 'ТРУ.csv'])
    if not isinstance(files, list) or len(files) != 2:
        raise ApiProblem('INVALID_FILES', 'Загрузите два CSV: закупки и ТРУ.')
    files = [Path(text(x, 'files', 255, blank=False)).name for x in files]
    with tempfile.TemporaryDirectory(prefix='supply-csv-') as directory:
        paths = [Path(directory) / 'notices.csv', Path(directory) / 'items.csv']
        for path, field in zip(paths, ('notices', 'items')):
            path.write_text(data[field], encoding='utf-8', newline='')
        try:
            records = read_procurements(*paths)
        except ValueError as exc:
            # Parser diagnostics contain input values, never server filesystem paths.
            message = str(exc).replace(str(paths[0]), 'Закупки.csv').replace(str(paths[1]), 'ТРУ.csv')
            raise ApiProblem('INVALID_CSV', message[:1500]) from exc
    count = sum(len(r['items']) for r in records)
    if len(records) > MAX_LOTS or count > MAX_ITEMS:
        raise ApiProblem('IMPORT_LIMIT', 'Предел одного импорта: 100 закупок и 10 000 позиций ТРУ.', 413)
    issues = []
    procurements = []
    for record in records:
        n, rows = record['notice'], record['items']
        items = [{'id': str(index + 1), 'name': r['product_name'], 'okpd2': r['okpd2_code'] or None, 'quantity': None}
                 for index, r in enumerate(rows)]
        if not rows:
            issues.append({'severity': 'warning', 'code': 'NO_ITEMS', 'file': files[1], 'row': 0, 'field': 'lot_id', 'lotId': n['lot_id'], 'message': 'У закупки нет строк ТРУ.', 'action': 'Проверьте исходный файл.'})
        if any(not r['okpd2_code'] for r in rows):
            issues.append({'severity': 'warning', 'code': 'MISSING_OKPD2', 'file': files[1], 'row': 0, 'field': 'okpd2_code', 'lotId': n['lot_id'], 'message': 'Есть позиции без ОКПД2; исходные строки сохранены.', 'action': 'Уточните код, если он известен.'})
        if len({tuple(r.items()) for r in rows}) != len(rows):
            issues.append({'severity': 'warning', 'code': 'DUPLICATE_ITEMS', 'file': files[1], 'row': 0, 'field': 'product_name', 'lotId': n['lot_id'], 'message': 'Повторяющиеся строки ТРУ сохранены отдельно.', 'action': 'Проверьте, что повторы нужны.'})
        procurements.append({'lotId': n['lot_id'], 'subject': n['subject'], 'source': n['is_eshop_or_aisgz'],
                             'publishDate': n['publish_date'], 'price': n['start_price'] or None,
                             'customerInn': n['customer_inn'] or None, 'customerName': None, 'region': '', 'items': items})
    return records, {'files': files, 'procurements': procurements, 'issues': issues,
                     'rows': {'notices': len(records), 'items': count},
                     'fileHashes': {f: hashlib.sha256(data[f].encode('utf-8')).hexdigest() for f in ('notices', 'items')}}

def save_import(owner, parsed):
    records, data = parsed
    check_quota(owner, len(records))
    batch = ImportBatch.objects.create(owner=owner, data=data)
    query_ids = []
    for record, procurement in zip(records, data['procurements']):
        q = Query.objects.create(owner=owner, batch=batch, procurement=procurement, raw_notice=record['notice'], raw_items=record['items'],
                                 warnings=[x['message'] for x in data['issues'] if x['lotId'] == procurement['lotId']])
        query_ids.append(str(q.pk))
    data = dict(data, id=str(batch.pk), queryIds=query_ids)
    batch.data = data
    batch.save(update_fields=['data'])
    return data, 201

def analytics(owner):
    queries = list(Query.objects.filter(owner=owner))
    items = [i for q in queries for i in q.procurement['items']]
    categories = Counter(i['okpd2'] for i in items if i['okpd2'])
    sources = Counter(q.procurement['source'] or 'Не указан' for q in queries)
    years = Counter(q.procurement['publishDate'][:4] for q in queries if q.procurement['publishDate'])
    dates = sorted(q.procurement['publishDate'] for q in queries if q.procurement['publishDate'])
    suppliers = {c['supplier_inn'] for q in queries for lot in q.result.get('lots', [])
                 for c in lot.get('recommendations', []) + lot.get('new_supplier_candidates', [])}
    completed = [q for q in queries if q.completed_at]
    with_suppliers = sum(any(lot.get('recommendations') or lot.get('new_supplier_candidates') for lot in q.result.get('lots', [])) for q in queries)
    return {'period': f'{dates[0]} - {dates[-1]}' if dates else 'Нет опубликованных дат', 'notices': len(queries), 'items': len(items),
            'inn': len(suppliers), 'codes': len(categories), 'withSuppliers': with_suppliers, 'withoutSuppliers': len(queries) - with_suppliers,
            'completed': len(completed),
            'categories': [{'code': c, 'rows': n} for c, n in categories.most_common()],
            'sources': [{'name': s, 'lots': n} for s, n in sources.items()], 'years': [{'year': y, 'lots': n} for y, n in sorted(years.items())],
            'queries': len(queries), 'imports': ImportBatch.objects.filter(owner=owner).count(), 'saved': sum(q.saved for q in queries),
            'exports': ExportRecord.objects.filter(owner=owner).count(),
            'sourceNote': 'Только ваши сохранённые запросы и результаты. Повторные импорты считаются отдельно. Счётчик компаний включает уникальные ИНН обеих выдач; это не оценка точности.'}

def prepare_export(owner, data):
    require_dict(data, ['queryId', 'companyIds', 'resultVersion', 'format'], ['queryId', 'resultVersion', 'format'])
    q = owned(Query, owner, data['queryId'])
    if data['resultVersion'] != q.result_version:
        raise ApiProblem('VERSION_CONFLICT', 'Версия запроса изменилась.', 409)
    projection = result_projection(q.result)
    allowed = {r['company']['id'] for r in projection['recommendations'] + projection['externalCandidates']}
    selected = data.get('companyIds', [])
    if not isinstance(selected, list) or len(selected) > 20 or any(not isinstance(x, str) or x not in allowed for x in selected) or len(set(selected)) != len(selected):
        raise ApiProblem('INVALID_SELECTION', 'Выберите компании из сохранённого результата этого запроса.', 422)
    if data['format'] not in ('csv', 'json', 'pdf'):
        raise ApiProblem('UNSUPPORTED_FORMAT', 'Доступны CSV, JSON и PDF.')
    q.exported = True
    q.save(update_fields=['exported'])
    export = ExportRecord.objects.create(owner=owner, query=q, format=data['format'])
    return {'id': str(export.pk), 'query': query_json(q), 'companyIds': selected, 'format': export.format, 'generatedAt': export.created_at.isoformat(), 'reportVersion': 'business-v2'}, 200

def export_bytes(record):
    q, fmt = record['query'], record['format']
    if fmt == 'json':
        return json.dumps(record, ensure_ascii=False, indent=2, sort_keys=True).encode('utf-8'), 'application/json; charset=utf-8'
    if fmt == 'pdf':
        from .reporting import build_pdf
        return build_pdf(q, {'companyIds': record.get('companyIds', []), 'generatedAt': record['generatedAt'], 'exportId': record['id'], 'reportVersion': record.get('reportVersion')}), 'application/pdf'
    if q['resultVersion'] != 'input-v1':
        return result_csv(record), 'text/csv; charset=utf-8'
    output = io.StringIO(newline='')
    writer = csv.writer(output, delimiter=';', lineterminator='\r\n')
    writer.writerow(['record_type', *NOTICE_COLUMNS, 'product_name', 'okpd2_code', 'status'])
    def safe(value):
        value = str(value or '')
        return "'" + value if value.lstrip().startswith(('=', '+', '-', '@', '\t', '\r', '\n')) else value
    notice = q['rawNotice'] or {'lot_id': q['procurement']['lotId'], 'subject': q['procurement']['subject'], 'start_price': q['procurement']['price']}
    rows = q['rawItems'] or [{'product_name': i['name'], 'okpd2_code': i['okpd2']} for i in q['procurement']['items']]
    for item in rows or [{}]:
        writer.writerow([safe(v) for v in ['input', *[notice.get(k, '') for k in NOTICE_COLUMNS], item.get('product_name', ''), item.get('okpd2_code', ''), q['status']]])
    return ('\ufeff' + output.getvalue()).encode('utf-8'), 'text/csv; charset=utf-8'


def result_csv(record):
    output = io.StringIO(newline='')
    writer = csv.writer(output, delimiter=';', lineterminator='\r\n')
    business = record.get('reportVersion') == 'business-v2'
    if business:
        writer.writerow(['Закупка', 'Группа', 'Место', 'ИНН', 'Компания', 'Почему в списке', 'Что уточнить', 'Источники', 'Сведения о компании обновлены'])
    else:
        writer.writerow(['query_id', 'result_version', 'lot_id', 'channel', 'rank', 'supplier_inn', 'company_name', 'score', 'score_kind', 'reason', 'source_urls', 'new_to_full_history'])
    selected = set(record.get('companyIds', []))
    q = record['query']
    def safe(value):
        value = str(value if value is not None else '')
        return "'" + value if value.lstrip().startswith(('=', '+', '-', '@', '\t', '\r', '\n')) else value
    for channel, candidates in [('historical', q['recommendations']), ('external', q['externalCandidates'])]:
        for value in candidates:
            c = value['company']
            if selected and c['id'] not in selected:
                continue
            if business:
                current = c.get('currentProfile') or c.get('profileAtCalculation') or {}
                sources = c.get('sources', []) + current.get('sources', [])
                writer.writerow([safe(v) for v in [q['procurement']['lotId'],
                    'По истории участия' if channel == 'historical' else 'По внешним источникам',
                    value['rank'], c['inn'], c.get('displayName') or c['name'],
                    value.get('explanationSummary') or 'Основания приведены в источниках.',
                    ' '.join(value.get('explanationNotes', [])),
                    ' | '.join(dict.fromkeys(s['url'] for s in sources if s.get('url'))), current.get('updatedAt')]])
                continue
            writer.writerow([safe(v) for v in [q['id'], q['resultVersion'], q['procurement']['lotId'], channel,
                value['rank'], c['inn'], c['name'], value['score'], value['scoreKind'], value['reason'],
                ' | '.join(s['url'] for s in c['sources'] if s['url']), c['newToFullHistory']]])
    return ('\ufeff' + output.getvalue()).encode('utf-8')


def companies_for(owner, query_id=None):
    queries = [owned(Query, owner, query_id)] if query_id else Query.objects.filter(owner=owner, completed_at__isnull=False)
    candidates = []
    for q in queries:
        projection = result_projection(q.result)
        candidates.extend(attach_company_profiles([r['company'] for r in projection['recommendations'] + projection['externalCandidates']], q.company_profiles))
    return merge_companies(candidates)
