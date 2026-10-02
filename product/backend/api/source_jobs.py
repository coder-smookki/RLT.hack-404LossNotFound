"""Сохранять задания обновления публичных профилей и точные доказательства в БД.

HTTP только ставит в очередь ИНН из разрешённого результата. Сеть вызывается
отдельным worker; аренда и токен защищают от записи устаревшим процессом."""
import hashlib
import logging
import threading
import uuid
from datetime import timedelta
from django.db import transaction, connection, close_old_connections
from django.db.models import Q
from django.utils import timezone
from .models import SourceRefreshJob, LiveSupplierProfile, SourceEvidenceBlob, SourceEvidenceBudget
from .company_profiles import canonical_inn, offline_profiles, validate_profile

LEASE_SECONDS=90
MAX_ATTEMPTS=3
MAX_PAGE_BYTES=2*1024*1024
MAX_STORED_BYTES=256*1024*1024
log=logging.getLogger('supply.audit')


def candidate_inns(query):
    """Извлечь уникальные ИНН из неизменяемого результата query.

    Ожидает Query с проверенной схемой result и supplier_inn в обеих выдачах.
    Возвращает список в порядке первого появления; БД и результат не меняет.
    Проверку принадлежности query пользователю выполняет вызывающий endpoint."""
    return list(dict.fromkeys(c['supplier_inn'] for lot in query.result.get('lots', [])
            for key in ('recommendations','new_supplier_candidates') for c in lot.get(key,[])))


def job_json(job):
    """Представить SourceRefreshJob в публичном JSON-совместимом словаре.

    Даты преобразуются в ISO8601 либо None. Для needs_source дата относится
    к сверке каталога, а не загрузке сайта. Функция не обращается к сети
    и не меняет задание; доступ к job ограничивает вызывающий endpoint."""
    return {'id':str(job.pk),'inn':job.inn,'status':job.status,'message':job.message,
            'checkedAt':job.checked_at.isoformat() if job.checked_at else None,
            'nextAllowedAt':job.next_allowed_at.isoformat() if job.next_allowed_at else None,
            'checkKind':'catalog_lookup' if job.status=='needs_source' else 'official_site'}


def enqueue_inns(inns, force=False):
    """Создать или переиспользовать задания для набора canonical ИНН inns.

    Без force действует интервал 24 часа, с force=True - 15 минут для того же
    снимка профиля. Изменившийся contentHash разрешает новую проверку. Running
    не прерывается, повторный queued с тем же снимком не дублируется.

    Каждый ИНН изменяется под блокировкой строки БД. Подтверждённый сайт даёт
    queued, отсутствие сайта - needs_source без сетевого запроса. Возвращает
    список job_json; ошибки БД передаются вызывающему коду."""
    profiles=offline_profiles(inns)
    output=[];now=timezone.now()
    for inn,profile in profiles.items():
        website=profile['fields']['website']
        eligible=website['status']=='verified' and bool(website['value'])
        with transaction.atomic():
            SourceRefreshJob.objects.get_or_create(inn=inn)
            job=SourceRefreshJob.objects.select_for_update().get(inn=inn)
            if job.status=='running':
                output.append(job_json(job));continue

            if job.input_hash==profile['contentHash']:
                if job.status=='queued':
                    output.append(job_json(job));continue
                interval=timedelta(minutes=15) if force else timedelta(hours=24)
                if job.checked_at and job.checked_at+interval>now:
                    output.append(job_json(job));continue
            job.input_hash=profile['contentHash'];job.attempts=0
            job.lease_token=job.lease_until=None
            job.status='queued' if eligible else 'needs_source'
            job.available_at=now
            job.message=('Проверка официального сайта ожидает обработки.' if eligible else
                         'Проверенного официального сайта пока нет. Доступные сведения сохранены с датами источников.')
            if not eligible:
                job.checked_at=now;job.next_allowed_at=now+timedelta(hours=24)
            else:job.next_allowed_at=None
            job.save();output.append(job_json(job))
    return output


def auto_enqueue(query_id):
    """Запланировать обновление кандидатов Query по query_id после commit.

    Функция предназначена для callback успешного расчёта. Любую ошибку поиска
    или очереди записывает в журнал по типу, чтобы необязательное обогащение
    не отменяло завершённую рекомендацию. Возвращает None; данные расчёта
    не изменяет и сама сеть не вызывает."""
    from .models import Query
    try:
        query=Query.objects.get(pk=query_id)
        enqueue_inns(candidate_inns(query))
    except Exception as exc:

        log.warning('source_autoqueue_failed type=%s',type(exc).__name__)


def claim():
    """Атомарно взять одно доступное либо просроченное задание.

    Возвращает SourceRefreshJob с новой арендой на 90 секунд и уникальным
    токеном либо None, если работы нет или выбранное задание исчерпало
    три попытки. Поддерживаемый адаптер использует skip_locked; иначе -
    обычную блокировку строки. Изменяет состояние и счётчик попыток в БД.
    Ошибки транзакции не скрываются."""
    now=timezone.now()
    with transaction.atomic():
        jobs=SourceRefreshJob.objects.filter(Q(status='queued',available_at__lte=now)|Q(status='running',lease_until__lt=now)).order_by('available_at','id')
        jobs=jobs.select_for_update(skip_locked=True) if connection.features.has_select_for_update_skip_locked else jobs.select_for_update()
        job=jobs.first()
        if not job:return None
        if job.attempts>=MAX_ATTEMPTS:
            job.status='failed';job.message='Обновление прерывалось. Прежние сведения сохранены.';job.checked_at=now
            job.lease_token=job.lease_until=None;job.next_allowed_at=now+timedelta(hours=24);job.save();return None
        job.status='running';job.attempts+=1;job.lease_token=uuid.uuid4();job.lease_until=now+timedelta(seconds=LEASE_SECONDS)
        job.message='Проверяем реквизиты и опубликованные сведения на официальном сайте.';job.save();return job


def heartbeat(job_id,token):
    """Продлить аренду job_id на 90 секунд, если token ещё принадлежит worker.

    Выполняет условный UPDATE только для running. Возвращает True при одном
    изменённом задании, иначе False. Токен не меняет; после перехвата
    задания другим worker прежний токен больше не продлевает аренду.
    Ошибки БД передаются вызывающему коду."""
    return SourceRefreshJob.objects.filter(pk=job_id,status='running',lease_token=token).update(lease_until=timezone.now()+timedelta(seconds=LEASE_SECONDS))==1


def finish(job_id,token,result):
    """Сохранить результат refresh_profile при действующем job_id и token.

    result содержит статус, профиль и не более трёх страниц bytes до 2 МиБ
    каждая. SHA256 проверяется до записи. Общий бюджет доказательств 256 МиБ
    защищён блокировкой, одинаковые тела дедуплицируются по SHA. Новый профиль
    сохраняется только с совпавшим ИНН и уже записанными live-доказательствами.

    Возвращает False для устаревшего токена, True после завершения записи.
    ValueError означает нарушение схемы, SHA или связи профиля с источником;
    ошибки внутри транзакции откатывают её. Failed повторяется с задержкой
    в пределах трёх попыток. Прежний результат ML и снимки не изменяются."""
    pages=result.get('pages',[])
    if not isinstance(pages,list) or len(pages)>3:raise ValueError('Invalid page count')
    for page in pages:
        body=page.get('body')
        if not isinstance(body,bytes) or len(body)>MAX_PAGE_BYTES or hashlib.sha256(body).hexdigest()!=page.get('contentHash'):
            raise ValueError('Evidence body/hash mismatch')
    now=timezone.now()
    with transaction.atomic():
        job=SourceRefreshJob.objects.select_for_update().get(pk=job_id)
        if job.status!='running' or job.lease_token!=token:return False
        status=result.get('status')
        if status not in ('complete','needs_source','unconfirmed','failed'):raise ValueError('Invalid source outcome')
        SourceEvidenceBudget.objects.get_or_create(pk=1)
        budget=SourceEvidenceBudget.objects.select_for_update().get(pk=1)
        unseen={p['contentHash']:p for p in pages if not SourceEvidenceBlob.objects.filter(pk=p['contentHash']).exists()}
        added=sum(len(p['body']) for p in unseen.values())
        if budget.used_bytes+added>MAX_STORED_BYTES:
            status='failed';result={**result,'message':'Хранилище источников заполнено. Прежние сведения сохранены.'};pages=[];unseen={};added=0
        for digest,page in unseen.items():
            SourceEvidenceBlob.objects.create(content_hash=digest,body=page['body'],size=len(page['body']),url=page['url'],fetched_at=page['fetchedAt'])
        budget.used_bytes+=added;budget.save(update_fields=['used_bytes'])
        if status=='complete':
            raw=result.get('profile')
            base=offline_profiles([job.inn]).get(job.inn)
            profile=validate_profile(raw,'live:'+str(job.pk)+':'+now.isoformat(),base['catalogHash'] if base else None,now.isoformat())
            if not profile or profile['inn']!=job.inn:raise ValueError('Refreshed identity mismatch')

            for source in profile['sources']:
                if source['id'].startswith('live:') and not SourceEvidenceBlob.objects.filter(pk=source['contentHash']).exists():
                    raise ValueError('Missing live evidence')
            LiveSupplierProfile.objects.update_or_create(inn=job.inn,defaults={'profile':profile,'checked_at':now})
        retry=status=='failed' and job.attempts<MAX_ATTEMPTS
        job.status='queued' if retry else status
        job.message=str(result.get('message') or 'Обновление завершено.')[:500]
        job.available_at=now+timedelta(seconds=min(120,15*job.attempts)) if retry else now
        job.checked_at=None if retry else now
        job.next_allowed_at=None if retry else now+timedelta(hours=24)
        job.lease_token=job.lease_until=None;job.save();return True


def run_one():
    """Обработать не более одного задания очереди с отдельным heartbeat.

    Возвращает False при отсутствии работы и True после попытки обработки.
    Загружает только проверенные страницы каталога через refresh_profile,
    фиксирует результат в БД и закрывает использованные соединения. Ошибку
    получения или сохранения пытается перевести в failed/retry; ошибка
    повторного сохранения передаётся supervisor через завершение worker."""
    from .source_fetch import refresh_profile
    job=claim()
    if not job:return False
    stop=threading.Event()
    def renew():
        """Продлевать аренду захваченного job каждые 20 секунд до stop.

        Использует отдельные соединения БД потока и закрывает их при выходе.
        Потеря токена прекращает продление; возвращаемого значения нет."""
        close_old_connections()
        try:
            while not stop.wait(20):
                if not heartbeat(job.pk,job.lease_token):return
        finally:close_old_connections()
    keeper=threading.Thread(target=renew,daemon=True,name='source-lease');keeper.start()
    try:
        profile=offline_profiles([job.inn])[job.inn]
        finish(job.pk,job.lease_token,refresh_profile(profile))
    except Exception as exc:
        log.warning('source_refresh_failed inn=%s type=%s',job.inn,type(exc).__name__)
        finish(job.pk,job.lease_token,{'status':'failed','profile':None,'pages':[], 'message':'Источник временно недоступен. Прежние сведения сохранены.'})
    finally:
        stop.set();keeper.join(timeout=2);close_old_connections()
    return True
