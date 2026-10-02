import hashlib
import json
import logging
import mimetypes
from pathlib import Path
import time
from functools import wraps
from django.conf import settings
from django.contrib.auth import authenticate, login, logout, update_session_auth_hash
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError, RequestDataTooBig, SuspiciousOperation
from django.core.validators import validate_email
from django.db import IntegrityError, OperationalError, transaction
from django.http import HttpResponse, JsonResponse, FileResponse
from django.middleware.csrf import get_token
from django.utils.crypto import salted_hmac
from .middleware import error
from .models import User, Query, ImportBatch, AuthAttempt, ExportRecord
from .services import (ApiProblem, require_dict, text, owned, query_json, idempotent, manual_query,
                       parse_import, save_import, analytics, prepare_export, export_bytes, companies_for, MAX_FILE, MAX_LOTS, MAX_ITEMS)
from .jobs import enqueue, engine_info

log = logging.getLogger('supply.audit')

def csrf_failure(request, reason=''):
    return error('CSRF_REJECTED', 'Проверка безопасности не пройдена. Обновите страницу и повторите.', 403)

def json_data(request):
    if request.content_type != 'application/json':
        raise ApiProblem('JSON_REQUIRED', 'Ожидается JSON.', 415)
    try:
        data = json.loads(request.body)
    except (UnicodeError, json.JSONDecodeError):
        raise ApiProblem('INVALID_JSON', 'Не удалось прочитать JSON.', 400)
    if not isinstance(data, dict):
        raise ApiProblem('INVALID_JSON', 'Ожидается JSON-объект.', 400)
    return data

def api_view(fn):
    @wraps(fn)
    def wrapped(request, *args, **kwargs):
        try:
            return fn(request, *args, **kwargs)
        except ApiProblem as exc:
            return error(exc.code, exc.message, exc.status, exc.fields)
        except RequestDataTooBig:
            return error('BODY_TOO_LARGE', 'Размер запроса превышает допустимый предел.', 413)
        except SuspiciousOperation:
            return error('INVALID_REQUEST', 'Запрос отклонён.', 400)
        except OperationalError:
            return error('DATABASE_BUSY', 'Сервер занят. Повторите запрос с тем же ключом.', 503)
        except Exception as exc:
            # Only exception class is logged. No request data, emails, SQL, paths or secrets.
            log.error('api_failure type=%s', type(exc).__name__)
            return error('INTERNAL_ERROR', 'Не удалось выполнить операцию.', 500)
    return wrapped

def method(request, *allowed):
    if request.method not in allowed:
        raise ApiProblem('METHOD_NOT_ALLOWED', 'Метод не поддерживается.', 405)

def auth_required(request):
    if not request.user.is_authenticated:
        raise ApiProblem('AUTH_REQUIRED', 'Войдите в аккаунт.', 401)

def user_json(user):
    return {'id': str(user.pk), 'email': user.email, 'name': user.name}

def throttle(request, identifier):
    now = int(time.time()) // 900
    ip = request.META.get('REMOTE_ADDR', 'unknown')
    # Proxy headers are deliberately ignored on the loopback-only service.
    keys = [(f'ip:{ip}', 60), (f'identity:{ip}:{identifier}', 10)]
    with transaction.atomic():
        for raw, maximum in keys:
            key = salted_hmac('supply-auth-throttle', raw).hexdigest()
            attempt, _ = AuthAttempt.objects.get_or_create(key=key, defaults={'window': now, 'count': 0})
            attempt = AuthAttempt.objects.select_for_update().get(pk=key)
            if attempt.window != now:
                attempt.window, attempt.count = now, 0
            if attempt.count >= maximum:
                raise ApiProblem('RATE_LIMITED', 'Слишком много попыток. Повторите через 15 минут.', 429)
            attempt.count += 1
            attempt.save(update_fields=['window', 'count'])

def email_value(value):
    value = text(value, 'email', 254, blank=False).strip().lower()
    try:
        validate_email(value)
    except ValidationError:
        raise ApiProblem('INVALID_EMAIL', 'Укажите корректный адрес почты.', fields={'email': 'Некорректный адрес.'})
    return value

def validate_secret(password, user):
    password = text(password, 'password', 128, blank=False)
    try:
        validate_password(password, user)
    except ValidationError as exc:
        raise ApiProblem('WEAK_PASSWORD', ' '.join(exc.messages), fields={'password': ' '.join(exc.messages)})
    return password

@api_view
def auth(request, action):
    if action == 'csrf':
        method(request, 'GET')
        return JsonResponse({'csrfToken': get_token(request)})
    if action == 'me':
        method(request, 'GET')
        auth_required(request)
        return JsonResponse({'user': user_json(request.user)})
    if action in ('register', 'login'):
        method(request, 'POST')
        data = json_data(request)
        require_dict(data, ['email', 'password', 'name'] if action == 'register' else ['email', 'password'], ['email', 'password'])
        email = email_value(data['email'])
        password = text(data['password'], 'password', 128, blank=False)
        throttle(request, email)
        if action == 'register':
            name = text(data.get('name'), 'name', 100, blank=False).strip()
            user = User(email=email, name=name)
            validate_secret(password, user)
            user.set_password(password)
            try:
                with transaction.atomic():
                    user.save()
            except IntegrityError:
                raise ApiProblem('ACCOUNT_EXISTS', 'Аккаунт с таким адресом уже существует.', 409)
            login(request, user)
            log.info('auth_event=register user_id=%s', user.pk)
            return JsonResponse({'user': user_json(user)}, status=201)
        user = authenticate(request, username=email, password=password)
        if user is None:
            log.info('auth_event=login_failed')
            raise ApiProblem('INVALID_CREDENTIALS', 'Неверная почта или пароль.', 401)
        login(request, user)
        log.info('auth_event=login user_id=%s', user.pk)
        return JsonResponse({'user': user_json(user)})
    if action == 'logout':
        method(request, 'POST')
        user_id = request.user.pk
        logout(request)
        log.info('auth_event=logout user_id=%s', user_id)
        return JsonResponse({'ok': True})
    auth_required(request)
    if action == 'profile':
        method(request, 'PATCH')
        data = require_dict(json_data(request), ['name'], ['name'])
        request.user.name = text(data['name'], 'name', 100, blank=False).strip()
        request.user.save(update_fields=['name'])
        return JsonResponse({'user': user_json(request.user)})
    if action == 'password':
        method(request, 'POST')
        data = require_dict(json_data(request), ['currentPassword', 'newPassword'], ['currentPassword', 'newPassword'])
        current = text(data['currentPassword'], 'currentPassword', 128, blank=False)
        throttle(request, request.user.email)
        with transaction.atomic():
            user = User.objects.select_for_update().get(pk=request.user.pk)
            if not user.check_password(current):
                raise ApiProblem('INVALID_PASSWORD', 'Текущий пароль неверен.', 422)
            new = validate_secret(data['newPassword'], user)
            if new == current:
                raise ApiProblem('PASSWORD_UNCHANGED', 'Новый пароль должен отличаться от текущего.')
            user.set_password(new)
            user.save(update_fields=['password'])
        update_session_auth_hash(request, user)
        request.user = user
        log.info('auth_event=password_changed user_id=%s', request.user.pk)
        return JsonResponse({'ok': True})
    raise ApiProblem('NOT_FOUND', 'Операция не найдена.', 404)

@api_view
def resource(request, path=''):
    path = path.rstrip('/')
    if path in ('health', 'config'):
        method(request, 'GET')
        if path == 'health':
            return JsonResponse({'ok': True, **engine_info()})
        return JsonResponse({**engine_info(), 'maxFileBytes': MAX_FILE, 'maxLots': MAX_LOTS, 'maxItems': MAX_ITEMS, 'formats': ['csv', 'json', 'pdf']})
    auth_required(request)
    parts = path.split('/')
    root = parts[0]
    if root == 'queries':
        if len(parts) == 1:
            method(request, 'GET', 'POST')
            if request.method == 'GET':
                return JsonResponse([query_json(q, summary=True) for q in Query.objects.filter(owner=request.user).select_related('inference_job').iterator(chunk_size=100)], safe=False)
            data = json_data(request)
            result, status = idempotent(request.user, 'query', request.headers.get('Idempotency-Key'), data,
                                        lambda: manual_query(request.user, data))
            return JsonResponse(result, status=status)
        q = owned(Query, request.user, parts[1])
        if len(parts) == 2:
            method(request, 'GET')
            return JsonResponse(query_json(q))
        if len(parts) == 3 and parts[2] == 'saved':
            method(request, 'PATCH')
            data = require_dict(json_data(request), ['saved'], ['saved'])
            if type(data['saved']) is not bool:
                raise ApiProblem('INVALID_SAVED', 'saved должен быть boolean.')
            q.saved = data['saved']
            q.save(update_fields=['saved'])
            return JsonResponse(query_json(q))
        if len(parts) == 3 and parts[2] == 'start':
            method(request, 'POST')
            require_dict(json_data(request), [])
            current = enqueue(request.user, [q])[0]
            return JsonResponse(query_json(current), status=200 if current.completed_at else 202)
    if root == 'imports':
        if len(parts) == 1:
            method(request, 'POST')
            if request.content_type == 'multipart/form-data':
                if set(request.FILES) != {'notices', 'items'} or request.POST:
                    raise ApiProblem('INVALID_FILES', 'Требуются только файлы notices и items.')
                data = {'files': []}
                for field in ('notices', 'items'):
                    if len(request.FILES.getlist(field)) != 1:
                        raise ApiProblem('INVALID_FILES', 'Требуются ровно два файла.')
                    upload = request.FILES[field]
                    if upload.size > MAX_FILE:
                        raise ApiProblem('FILE_TOO_LARGE', 'Каждый CSV должен быть не больше 10 МиБ.', 413)
                    try:
                        data[field] = upload.read().decode('utf-8')
                    except UnicodeError:
                        raise ApiProblem('INVALID_ENCODING', 'CSV должен быть в UTF-8.')
                    data['files'].append(upload.name)
            else:
                data = json_data(request)
            parsed = parse_import(data)
            result, status = idempotent(request.user, 'import', request.headers.get('Idempotency-Key'), data,
                                        lambda: save_import(request.user, parsed))
            return JsonResponse(result, status=status)
        batch = owned(ImportBatch, request.user, parts[1])
        if len(parts) == 2:
            method(request, 'GET')
            return JsonResponse(batch.data)
        if len(parts) == 3 and parts[2] == 'start':
            method(request, 'POST')
            require_dict(json_data(request), [])
            current = enqueue(request.user, list(batch.queries.all()))
            return JsonResponse({'queryIds': [str(q.pk) for q in current], 'queries': [query_json(q, summary=True) for q in current],
                                 'message': 'Закупки поставлены в очередь. Результаты сохраняются отдельно для каждого лота.'}, status=202)
    if path == 'analytics':
        method(request, 'GET')
        return JsonResponse(analytics(request.user))
    if path == 'companies':
        method(request, 'GET')
        return JsonResponse(companies_for(request.user, request.GET.get('queryId')), safe=False)
    if root == 'companies' and len(parts) == 2:
        method(request, 'GET')
        companies = companies_for(request.user, request.GET.get('queryId'))
        value = next((c for c in companies if c['id'] == parts[1]), None)
        if value is None:
            raise ApiProblem('NOT_FOUND', 'Компания не найдена в ваших результатах.', 404)
        return JsonResponse(value)
    if path == 'source-jobs':
        method(request, 'GET', 'POST')
        from .source_jobs import candidate_inns, enqueue_inns, job_json
        from .models import SourceRefreshJob
        if request.method == 'GET':
            q = owned(Query, request.user, request.GET.get('queryId'))
            return JsonResponse({'jobs': [job_json(j) for j in SourceRefreshJob.objects.filter(inn__in=candidate_inns(q))]})
        data = require_dict(json_data(request), ['queryId', 'force'], ['queryId'])
        if type(data.get('force', False)) is not bool:
            raise ApiProblem('INVALID_FIELD', 'Проверьте параметр обновления.')
        q = owned(Query, request.user, data['queryId'])
        if not q.completed_at:
            raise ApiProblem('RESULT_REQUIRED', 'Сначала дождитесь результата подбора.', 409)
        return JsonResponse({'jobs': enqueue_inns(candidate_inns(q), force=data.get('force', False)),
                             'message': 'Проверяем известные официальные сайты. Для остальных компаний источник требуется уточнить.'}, status=202)
    if path == 'exports':
        method(request, 'POST')
        data = json_data(request)
        record, status = idempotent(request.user, 'export', request.headers.get('Idempotency-Key'), data,
                                    lambda: prepare_export(request.user, data))
        payload, mime = export_bytes(record)
        response = HttpResponse(payload, content_type=mime, status=status)
        response['Content-Disposition'] = f'attachment; filename="rlt-result-{record["query"]["id"]}.{record["format"]}"'
        return response
    if path == 'exports/confirm':
        method(request, 'POST')
        data = require_dict(json_data(request), ['queryId', 'format'], ['queryId', 'format'])
        q = owned(Query, request.user, data['queryId'])
        if not ExportRecord.objects.filter(owner=request.user, query=q, format=data['format']).exists():
            raise ApiProblem('EXPORT_NOT_CREATED', 'Сначала сформируйте экспорт.', 409)
        return JsonResponse({'ok': True})
    raise ApiProblem('NOT_FOUND', 'Операция не найдена.', 404)

@api_view
def frontend(request, path=''):
    method(request, 'GET', 'HEAD')
    root = settings.FRONTEND_DIST.resolve()
    target = (root / path).resolve()
    if not target.is_relative_to(root):
        raise ApiProblem('NOT_FOUND', 'Файл не найден.', 404)
    if path and target.is_file():
        mime = mimetypes.guess_type(target.name)[0] or 'application/octet-stream'
        return FileResponse(target.open('rb'), content_type=mime)
    if path and '.' in Path(path).name:
        raise ApiProblem('NOT_FOUND', 'Файл не найден.', 404)
    index = root / 'index.html'
    if not index.is_file():
        return error('FRONTEND_NOT_BUILT', 'Интерфейс ещё не собран.', 503)
    return HttpResponse(index.read_bytes(), content_type='text/html; charset=utf-8')

def bad_request(request, exception=None):
    return error('INVALID_REQUEST', 'Запрос отклонён.', 400)

def not_found(request, exception=None):
    return error('NOT_FOUND', 'Операция не найдена.', 404)

def server_error(request):
    return error('INTERNAL_ERROR', 'Не удалось выполнить операцию.', 500)
