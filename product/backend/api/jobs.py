"""Durable database queue and a bounded loopback adapter to the accepted runtime."""
import copy
import csv
import hashlib
import io
import json
import logging
import threading
import time
import uuid
from datetime import timedelta
from urllib.error import HTTPError, URLError
from urllib.request import Request, build_opener, ProxyHandler, HTTPRedirectHandler
from django.db import transaction, connection, close_old_connections
from django.db.models import Q
from django.utils import timezone
from .models import User, Query, InferenceJob
from .services import ApiProblem

RUNTIME_URL = 'http://127.0.0.1:8901'
LEASE_SECONDS = 90
MAX_ATTEMPTS = 3
MAX_RESPONSE = 32 * 1024 * 1024
ACCEPTED_FEATURE_VERSION = 'p1_neighbor_lot_evidence_v3_35'
ACCEPTED_SELECTION_SHA256 = '1e3fa4dbe9dc661f3288aeb24a326936a8e98b568f0fe338e3dfd88a03ca9451'
log = logging.getLogger('supply.audit')

class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        raise RuntimeFailure('ENGINE_REDIRECT', 'Локальный сервис вернул недопустимое перенаправление.', False)

class RuntimeFailure(Exception):
    def __init__(self, code, message, retryable=True):
        self.code, self.message, self.retryable = code, message, retryable


def runtime_request(path, body=None, content_type=None, timeout=2):
    headers = {'Origin': RUNTIME_URL}
    if content_type:
        headers['Content-Type'] = content_type
    request = Request(RUNTIME_URL + path, data=body, headers=headers)
    try:
        with build_opener(ProxyHandler({}), NoRedirect()).open(request, timeout=timeout) as response:
            payload = response.read(MAX_RESPONSE + 1)
            if len(payload) > MAX_RESPONSE:
                raise RuntimeFailure('ENGINE_RESPONSE_LIMIT', 'Ответ модели превысил допустимый размер.', False)
            value = json.loads(payload, parse_constant=lambda _: (_ for _ in ()).throw(ValueError('Non-finite number')))
            if not isinstance(value, dict):
                raise ValueError('Expected object')
            return value
    except HTTPError as exc:
        if exc.code == 422:
            raise RuntimeFailure('ENGINE_INPUT_REJECTED', 'Модель отклонила входные данные. Проверьте закупку и ТРУ.', False) from exc
        if exc.code == 409:
            raise RuntimeFailure('ENGINE_BUSY', 'Модель обрабатывает другой запрос. Задание будет повторено.') from exc
        raise RuntimeFailure('ENGINE_UNAVAILABLE', 'Сервис рекомендаций временно недоступен.') from exc
    except (URLError, TimeoutError, OSError) as exc:
        raise RuntimeFailure('ENGINE_UNAVAILABLE', 'Сервис рекомендаций временно недоступен.') from exc
    except (ValueError, UnicodeError) as exc:
        raise RuntimeFailure('ENGINE_INVALID_RESPONSE', 'Ответ модели не прошёл проверку структуры.', False) from exc


def engine_info():
    try:
        info = runtime_request('/info')
        return {'engineConnected': True, 'engineReady': bool(info.get('ready')), 'engineBusy': bool(info.get('busy')),
                'externalCatalog': info.get('external_catalog')}
    except RuntimeFailure:
        return {'engineConnected': True, 'engineReady': False, 'engineBusy': False, 'externalCatalog': None}


def enqueue(owner, queries):
    """Account lock serializes starts with import/quota and never locks an input after its job."""
    ids = [q.pk for q in queries]
    with transaction.atomic():
        User.objects.select_for_update().get(pk=owner.pk)
        current = list(Query.objects.filter(owner=owner, pk__in=ids).order_by('created_at', 'id'))
        if len(current) != len(ids):
            raise ApiProblem('NOT_FOUND', 'Запись не найдена.', 404)
        if any(not q.batch_id or not q.raw_notice for q in current):
            raise ApiProblem('CSV_INPUT_REQUIRED', 'Для модели загрузите два CSV: закупки и ТРУ.', 422)
        for q in current:
            job = InferenceJob.objects.select_for_update().filter(query=q).first()
            if job is None:
                InferenceJob.objects.create(query=q)
            elif job.status == 'failed':
                job.status, job.error_code, job.message = 'queued', '', 'Повторный запуск ожидает обработки.'
                job.available_at, job.finished_at = timezone.now(), None
                job.lease_token, job.lease_until = None, None
                job.save()
        return list(Query.objects.filter(owner=owner, pk__in=ids).select_related('inference_job').order_by('created_at', 'id'))


def claim_job():
    now = timezone.now()
    with transaction.atomic():
        candidates = InferenceJob.objects.filter(
            Q(status='queued', available_at__lte=now) | Q(status='running', lease_until__lt=now)
        ).order_by('created_at', 'id')
        if connection.features.has_select_for_update_skip_locked:
            candidates = candidates.select_for_update(skip_locked=True)
        else:
            candidates = candidates.select_for_update()
        job = candidates.first()
        if not job:
            return None
        if job.attempts >= MAX_ATTEMPTS and job.status == 'running':
            job.status, job.error_code = 'failed', 'WORKER_INTERRUPTED'
            job.message, job.finished_at = 'Обработка прерывалась несколько раз. Запустите подбор повторно.', now
            job.lease_token, job.lease_until = None, None
            job.save()
            return None
        job.status, job.lease_token = 'running', uuid.uuid4()
        job.lease_until = now + timedelta(seconds=LEASE_SECONDS)
        job.started_at, job.finished_at, job.available_at = now, None, now
        job.attempts += 1
        job.message, job.error_code = 'Подбор по истории и проверенным внешним источникам.', ''
        job.save()
        return job


def heartbeat(job_id, token):
    return InferenceJob.objects.filter(pk=job_id, status='running', lease_token=token).update(
        lease_until=timezone.now() + timedelta(seconds=LEASE_SECONDS)) == 1


def csv_bytes(columns, rows):
    output = io.StringIO(newline='')
    writer = csv.DictWriter(output, fieldnames=columns, delimiter=';', lineterminator='\n')
    writer.writeheader()
    for row in rows:
        writer.writerow({key: row.get(key, '') for key in columns})
    return output.getvalue().encode('utf-8')


def _verify_provenance(result, query, expected_hashes):
    """Проверяет, что результат построен принятой моделью ровно по сохранённому входу закупки.

    Raises:
        RuntimeFailure: ответ не соответствует входу, ранжировщику или принятой версии модели.
    """
    try:
        lot = result['lots'][0]
        if (result['ranker'] != 'neighbor35' or result['query_count'] != 1 or len(result['lots']) != 1
                or result['input_sha256'] != expected_hashes or lot['lot_id'] != query.raw_notice['lot_id']
                or lot['notice'] != query.raw_notice or lot['raw_items'] != query.raw_items
                or lot['method'] != 'neighbor35_nnpu_fusion'
                or lot['feature_version'] != ACCEPTED_FEATURE_VERSION
                or lot['model_selection_sha256'] != ACCEPTED_SELECTION_SHA256):
            raise ValueError('Runtime provenance mismatch')
        # Parse the whole presentation before committing a successful result.
        from .presentation import result_projection
        result_projection(result)
        return result
    except (KeyError, TypeError, IndexError, ValueError) as exc:
        raise RuntimeFailure('ENGINE_PROVENANCE_MISMATCH', 'Ответ модели не соответствует сохранённому входу или принятой версии.', False) from exc


def cached_result(query, expected_hashes):
    """Возвращает готовый расчёт такого же лота, если входные данные, модель и каталог источников не менялись.

    Совпадать должны SHA-256 обоих сформированных CSV, принятая версия признаков и модели, ранжировщик,
    версия runtime, дата среза истории и полный отпечаток внешнего каталога из текущего `/info`.
    Переиспользуется только детерминированный расчёт по публичным данным; флаги и выбор пользователя не копируются.

    Args:
        query: закупка, для которой выполняется подбор.
        expected_hashes: SHA-256 файлов notices/items, которые были бы отправлены модели.
    Returns:
        Копия результата с отметкой `cache` или None, если повторный расчёт необходим.
    """
    try:
        info = runtime_request('/info')
    except RuntimeFailure:
        return None
    catalog = info.get('external_catalog')
    if not info.get('ready') or not isinstance(catalog, dict):
        return None
    candidates = (Query.objects.filter(procurement__lotId=query.procurement.get('lotId'), completed_at__isnull=False)
                  .exclude(pk=query.pk).order_by('-completed_at').only('result', 'completed_at')[:25])
    for other in candidates:
        result = other.result or {}
        if result.get('input_sha256') != expected_hashes or result.get('external_catalog') != catalog:
            continue
        try:
            reused = _verify_provenance(copy.deepcopy(result), query, expected_hashes)
        except RuntimeFailure:
            continue
        reused['cache'] = {'reusedFromCompletedAt': other.completed_at.isoformat(),
                           'basis': 'same_input_sha256_model_and_external_catalog'}
        return reused
    return None


def infer(query):
    from rlt_lab.data import NOTICE_COLUMNS, ITEM_COLUMNS
    files = {'notices': csv_bytes(NOTICE_COLUMNS, [query.raw_notice]), 'items': csv_bytes(ITEM_COLUMNS, query.raw_items)}
    expected_hashes = {key: hashlib.sha256(value).hexdigest() for key, value in files.items()}
    reused = cached_result(query, expected_hashes)
    if reused is not None:
        return reused
    boundary = 'rlt-' + uuid.uuid4().hex
    body = bytearray()
    for field, payload in files.items():
        body.extend((f'--{boundary}\r\nContent-Disposition: form-data; name="{field}"; filename="{field}.csv"\r\nContent-Type: text/csv\r\n\r\n').encode())
        body.extend(payload)
        body.extend(b'\r\n')
    body.extend(f'--{boundary}--\r\n'.encode())
    result = runtime_request('/recommend', bytes(body), 'multipart/form-data; boundary=' + boundary, timeout=300)
    return _verify_provenance(result, query, expected_hashes)


def finish(job_id, token, result=None, failure=None):
    # Public profile metadata is captured once, separately from the immutable ML result.
    from .company_profiles import snapshot_for_result
    profiles = snapshot_for_result(result) if failure is None and result is not None else {}
    with transaction.atomic():
        job = InferenceJob.objects.select_for_update().get(pk=job_id)
        if job.status != 'running' or job.lease_token != token:
            return False
        now = timezone.now()
        if failure:
            retry = failure.retryable and job.attempts < MAX_ATTEMPTS
            job.status = 'queued' if retry else 'failed'
            job.available_at = now + timedelta(seconds=min(30, 5 * job.attempts))
            job.error_code, job.message = failure.code, failure.message
            job.finished_at = None if retry else now
        else:
            Query.objects.filter(pk=job.query_id, result_version='input-v1').update(
                result=result, company_profiles=profiles, result_version='result-' + str(job.pk), completed_at=now)
            job.status, job.finished_at = 'complete', now
            job.message = ('Результат взят из предыдущего расчёта такого же лота: входные данные, модель и каталог источников не менялись.'
                           if result.get('cache') else 'Подбор завершён. Проверьте основания и характеристики.')
            job.error_code = ''
            from .source_jobs import auto_enqueue
            transaction.on_commit(lambda query_id=job.query_id: auto_enqueue(query_id))
        job.lease_token, job.lease_until = None, None
        job.save()
        return True


def run_one():
    job = claim_job()
    if job is None:
        return False
    stop = threading.Event()
    def renew():
        close_old_connections()
        try:
            while not stop.wait(20):
                try:
                    if not heartbeat(job.pk, job.lease_token):
                        return
                except Exception as exc:
                    log.warning('job_heartbeat_failure type=%s', type(exc).__name__)
                    close_old_connections()
        finally:
            close_old_connections()
    keeper = threading.Thread(target=renew, daemon=True, name='inference-lease')
    keeper.start()
    try:
        result = infer(Query.objects.get(pk=job.query_id))
        finish(job.pk, job.lease_token, result=result)
        log.info('job_event=complete job_id=%s', job.pk)
    except RuntimeFailure as exc:
        finish(job.pk, job.lease_token, failure=exc)
        log.warning('job_event=failed job_id=%s code=%s', job.pk, exc.code)
    except Exception as exc:
        finish(job.pk, job.lease_token, failure=RuntimeFailure('INFERENCE_FAILED', 'Обработка прервалась. Повторите подбор.', False))
        log.error('job_event=failed job_id=%s type=%s', job.pk, type(exc).__name__)
    finally:
        stop.set()
        keeper.join(timeout=2)
        close_old_connections()
    return True
