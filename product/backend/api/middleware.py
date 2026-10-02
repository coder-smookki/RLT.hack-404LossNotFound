import logging
from django.conf import settings
from django.core.exceptions import DisallowedHost, RequestDataTooBig, TooManyFieldsSent, TooManyFilesSent
from django.http import JsonResponse

log = logging.getLogger('supply.audit')

def error(code, message, status=400, fields=None):
    body = {'code': code, 'message': message}
    if fields:
        body['fields'] = fields
    return JsonResponse({'error': body}, status=status)

class BoundaryMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response
    def __call__(self, request):
        try:
            request.get_host()
            length = request.META.get('CONTENT_LENGTH', '')
            if length and (not length.isdigit() or int(length) > settings.DATA_UPLOAD_MAX_MEMORY_SIZE):
                return error('BODY_TOO_LARGE', 'Размер запроса превышает допустимый предел.', 413)
            response = self.get_response(request)
        except (DisallowedHost, RequestDataTooBig, TooManyFieldsSent, TooManyFilesSent):
            response = error('INVALID_REQUEST', 'Запрос отклонён.', 400)
        response['Content-Security-Policy'] = "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; font-src 'self'; connect-src 'self'; frame-ancestors 'none'; base-uri 'self'; form-action 'self'"
        response['X-Content-Type-Options'] = 'nosniff'
        response['X-Frame-Options'] = 'DENY'
        response['Referrer-Policy'] = 'same-origin'
        response['Permissions-Policy'] = 'camera=(), microphone=(), geolocation=()'
        response['X-Robots-Tag'] = 'noindex, nofollow'
        if request.path.startswith('/api/'):
            response['Cache-Control'] = 'no-store'
        return response
