"""Ограниченно обновлять сведения с заранее проверенных официальных страниц.

Пользовательские URL не принимаются. Домены, публичные IP, TLS, объём
и время проверяются; код страниц не исполняется. Возвращаемые байты
источников сохраняет отдельный транзакционный слой."""
import copy
import hashlib
import http.client
import ipaddress
import re
import socket
import ssl
import threading
import time
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutureTimeout
from datetime import datetime, timezone
from html.parser import HTMLParser
from urllib.parse import unquote, urljoin, urlsplit

MAX_BYTES = 2 * 1024 * 1024
MAX_PAGES = 3
PAGE_SECONDS = 12
_DNS_POOL = ThreadPoolExecutor(max_workers=2, thread_name_prefix='public-source-dns')
_DNS_SLOTS = threading.BoundedSemaphore(2)


class SourceFailure(Exception):
    """Обозначить отказ проверки адреса, транспорта или содержимого источника.

    Сообщение объясняет причину без передачи тела страницы или секретов.
    Вызывающий worker сохраняет прежний профиль и выбирает повтор проверки."""
    pass


def reviewed_url(url, official_host):
    """Проверить url относительно ранее подтверждённого official_host.

    Принимает только HTTPS с портом 443 или без порта, без учётных данных,
    управляющих символов и IP вместо домена. IDNA-домен должен совпадать
    с официальным доменом без www либо быть его поддоменом.

    Возвращает пару SplitResult и нормализованный host. Нарушения вызывают
    SourceFailure; сеть и исходный URL не изменяются."""
    if not isinstance(url, str) or len(url) > 2048 or re.search(r'[\x00-\x20\x7f]', url):
        raise SourceFailure('Недопустимый адрес источника.')
    try:
        parts = urlsplit(url)
        host = (parts.hostname or '').encode('idna').decode('ascii').lower()
        base = official_host.encode('idna').decode('ascii').lower().removeprefix('www.')
        if (parts.scheme != 'https' or not base or parts.username or parts.password or
                parts.port not in (None, 443) or not (host == base or host.endswith('.' + base))):
            raise SourceFailure('Источник вне проверенного официального HTTPS-сайта.')
    except (ValueError, UnicodeError) as exc:
        raise SourceFailure('Недопустимый адрес официального сайта.') from exc
    try:
        ipaddress.ip_address(host)
    except ValueError:
        pass
    else:
        raise SourceFailure('IP-адрес вместо официального домена не принимается.')
    return parts, host


def public_addresses(host):
    """Разрешить host через системный DNS для TCP443 и проверить все адреса.

    Возвращает уникальные пары семейства сокета и адреса. Пустой ответ или
    хотя бы один непубличный IP вызывает SourceFailure; ошибки getaddrinfo
    передаются наружу. Вызов DNS может блокироваться в ОС, поэтому worker
    использует эту функцию через bounded_addresses."""
    records = socket.getaddrinfo(host, 443, type=socket.SOCK_STREAM)
    addresses = list(dict.fromkeys((row[0], row[4]) for row in records))
    if not addresses or any(not ipaddress.ip_address(address[0]).is_global for _, address in addresses):
        raise SourceFailure('Источник использует непубличный сетевой адрес.')
    return addresses


def bounded_addresses(host):

    """Получить публичные адреса host с ожиданием результата не более 4 секунд.

    Использует общий пул и семафор на два вызова: зависший системный DNS
    не создаёт неограниченную очередь. Возвращает результат public_addresses;
    занятость пула и тайм-аут дают SourceFailure, прочие ошибки передаются.
    Уже запущенный getaddrinfo отменить нельзя; слот освобождается только
    после его завершения."""
    if not _DNS_SLOTS.acquire(blocking=False):
        raise SourceFailure('Служба определения адресов временно занята.')
    try:
        pending = _DNS_POOL.submit(public_addresses, host)
    except Exception:
        _DNS_SLOTS.release()
        raise
    pending.add_done_callback(lambda _: _DNS_SLOTS.release())
    try:
        return pending.result(timeout=4)
    except FutureTimeout as exc:

        raise SourceFailure('Служба определения адресов не ответила вовремя.') from exc


class PinnedHTTPS(http.client.HTTPSConnection):
    """Соединять HTTPS с проверенным числовым IP при сохранении TLS-проверки host.

    Список адресов получает вызывающий код после DNS-проверки. При connect
    не выполняется повторное DNS-разрешение, поэтому адрес назначения
    не меняется между проверкой и соединением."""
    def __init__(self, host, addresses):
        """Подготовить HTTPS для host и ранее проверенного списка addresses.

        Использует стандартную проверку сертификата и тайм-аут сокета 4 секунды.
        Сеть пока не открывает; сохраняет список адресов для connect."""
        super().__init__(host, timeout=4, context=ssl.create_default_context())
        self.addresses = addresses

    def connect(self):
        """Открыть TLS к одному из первых двух проверенных адресов.

        SNI и сертификат проверяются по исходному self.host. При успехе
        устанавливает self.sock и возвращает None; неудачные сокеты закрывает.
        Если ни один адрес не доступен, передаёт последний OSError либо
        SourceFailure при пустом списке."""
        last_error = None
        for family, address in self.addresses[:2]:
            raw = socket.socket(family, socket.SOCK_STREAM)
            try:
                raw.settimeout(self.timeout)
                raw.connect(address)
                self.sock = self._context.wrap_socket(raw, server_hostname=self.host)
                return
            except OSError as exc:
                last_error = exc
                raw.close()
        raise last_error or SourceFailure('Источник недоступен.')


def fetch_page(url, official_host):
    """Загрузить одну страницу url в пределах проверенного official_host.

    Каждый из максимум трёх HTTP-переходов заново проверяет домен и DNS.
    Прокси и cookie не используются. Принимает текстовый ответ 200 без
    сжатия, до 2 МиБ; чтение ограничено PAGE_SECONDS=12 и таймером сокета.

    Возвращает URL, точные bytes, декодированный text, SHA256, MIME и время
    загрузки UTC. Нарушения адреса, HTTP, размера, времени или кодировки
    дают SourceFailure. Соединение и таймер закрываются при любом исходе.
    Это время получения, а не дата публикации или юридической актуальности."""
    started = time.monotonic()
    current = url
    for _ in range(3):
        parts, host = reviewed_url(current, official_host)
        try:
            addresses = bounded_addresses(host)
        except OSError as exc:
            raise SourceFailure('Не удалось определить адрес официального сайта.') from exc
        remaining = PAGE_SECONDS - (time.monotonic() - started)
        if remaining <= 0:
            raise SourceFailure('Источник не ответил вовремя.')
        conn = PinnedHTTPS(host, addresses)
        def abort(connection=conn):
            """Прервать чтение сокета connection по таймеру текущей страницы.

            По умолчанию захватывает именно созданное соединение conn. Ошибка
            shutdown игнорируется; соединение окончательно закрывает fetch_page.
            Возвращает None и не выполняет DNS или новый HTTP-запрос."""
            if connection.sock:
                try:
                    connection.sock.shutdown(socket.SHUT_RDWR)
                except OSError:
                    pass
        timer = threading.Timer(remaining, abort)
        timer.daemon = True
        timer.start()
        try:
            path = parts.path or '/'
            if parts.query:
                path += '?' + parts.query
            conn.request('GET', path, headers={'User-Agent': 'RLTResearch/1.2 (supplier profile verification)',
                                              'Accept': 'text/html, text/plain', 'Accept-Encoding': 'identity'})
            with conn.getresponse() as response:
                if response.status in (301, 302, 303, 307, 308):
                    current = urljoin(current, response.getheader('Location', ''))
                    reviewed_url(current, official_host)
                    continue
                if response.status != 200:
                    raise SourceFailure(f'Источник вернул HTTP {response.status}.')
                if response.getheader('Content-Encoding', 'identity').lower() != 'identity':
                    raise SourceFailure('Неподдерживаемое сжатие источника.')
                mime = response.headers.get_content_type()
                if mime not in ('text/html', 'text/plain', 'application/xhtml+xml'):
                    raise SourceFailure('Источник не является текстовой страницей.')
                length = response.getheader('Content-Length')
                if length and (not length.isdigit() or int(length) > MAX_BYTES):
                    raise SourceFailure('Страница превышает допустимый размер.')
                body = bytearray()
                while True:
                    if time.monotonic() - started > PAGE_SECONDS:
                        raise SourceFailure('Источник не ответил вовремя.')
                    block = response.read1(min(65536, MAX_BYTES + 1 - len(body)))
                    if not block:
                        break
                    body.extend(block)
                    if len(body) > MAX_BYTES:
                        raise SourceFailure('Страница превышает допустимый размер.')
                charset = response.headers.get_content_charset() or 'utf-8'
                text = bytes(body).decode(charset)
                return {'url': current, 'body': bytes(body), 'text': text,
                        'contentHash': hashlib.sha256(body).hexdigest(), 'contentType': mime,
                        'fetchedAt': datetime.now(timezone.utc).isoformat()}
        except (OSError, http.client.HTTPException, UnicodeError, LookupError) as exc:
            raise SourceFailure('Не удалось получить проверяемый текст источника.') from exc
        finally:
            timer.cancel()
            conn.close()
    raise SourceFailure('Слишком много перенаправлений источника.')


class PageText(HTMLParser):
    """Собрать видимый текст и явно опубликованные контакты из HTML.

    Скрипты, стили, noscript и SVG пропускаются. Контакт считается
    опубликованным только при совпадении href mailto/tel с видимым текстом;
    принадлежность ИНН проверяет refresh_profile отдельно."""
    def __init__(self):
        """Создать парсер с декодированием HTML-сущностей и пустыми накопителями.

        parts хранит текст, contacts - контакты, skip - скрытые теги, anchor -
        текущую ссылку. Внешних запросов и изменения HTML не выполняет."""
        super().__init__(convert_charrefs=True)
        self.parts, self.contacts, self.skip, self.anchor = [], [], [], None

    def handle_starttag(self, tag, attrs):
        """Обработать открывающий tag и список attrs от HTMLParser.

        Добавляет скрытый тег в skip либо начинает накопление видимой ссылки.
        Изменяет только состояние парсера, возвращает None."""
        if tag in ('script', 'style', 'noscript', 'svg'):
            self.skip.append(tag)
        if tag == 'a' and not self.skip:
            self.anchor = [dict(attrs).get('href', ''), '']

    def handle_endtag(self, tag):
        """Закрыть tag и при завершении ссылки проверить опубликованный контакт.

        Email должен совпасть с видимым текстом, телефон - с его 10-15 цифрами.
        Неподходящие ссылки пропускаются. Валидный контакт добавляется в contacts
        как published_business_contact без обещания проверки звонком/письмом.
        Возвращает None; сеть не используется."""
        if self.skip and self.skip[-1] == tag:
            self.skip.pop()
        if tag == 'a' and self.anchor:
            href, text = self.anchor
            text = ' '.join(text.split())
            self.anchor = None
            kind = 'email' if href.lower().startswith('mailto:') else 'phone' if href.lower().startswith('tel:') else None
            if not kind:
                return
            value = unquote(href.split(':', 1)[1].split('?', 1)[0]).strip()
            if kind == 'email':
                if not re.fullmatch(r'[\w.!#$%&\x27*+/=?^`{|}~-]+@[\w.-]+\.[A-Za-z]{2,}', value) or value.casefold() not in text.casefold():
                    return
            else:
                digits = re.sub(r'\D', '', value)
                if not 10 <= len(digits) <= 15 or digits != re.sub(r'\D', '', text):
                    return
                value = text
            self.contacts.append({'kind': kind, 'value': value, 'text': text, 'scope': 'published_business_contact'})

    def handle_data(self, value):
        """Добавить видимый текст value в parts и текст текущей ссылки.

        Внутри skip данные игнорируются. Возвращает None; изменяет только
        накопители парсера."""
        if not self.skip:
            self.parts.append(value)
            if self.anchor:
                self.anchor[1] += value


def refresh_profile(profile, fetch=fetch_page):
    """Обновить проверенный профиль profile и вернуть точные доказательства.

    profile приходит из валидированного каталога, а не HTTP-ввода. fetch
    по умолчанию равен fetch_page; тесты могут передать совместимую функцию.
    Обходятся не более трёх заранее проверенных страниц того же сайта.

    Возвращает status, profile либо None, pages с bytes, message и иногда
    errors. Без сайта/страницы реквизитов status=needs_source; без точного
    ИНН - unconfirmed либо failed. Несколько ИНН на странице не позволяют
    присвоить её контакты, ОГРН и КПП одной компании. ОГРН проверяется по
    длине и контрольной цифре; предложения повторно подтверждаются только
    буквальными фрагментами. Старые реестровые факты и их даты сохраняются.

    Исходный профиль не меняется; БД не используется. SourceFailure и
    ValueError отдельных страниц собираются в errors, неожиданные ошибки
    передаются worker. Время загрузки не выдаётся за публикацию или
    действующий юридический статус."""
    base = copy.deepcopy(profile)
    website = base.get('fields', {}).get('website', {})
    if website.get('status') != 'verified' or not website.get('value'):
        return {'status': 'needs_source', 'profile': None, 'pages': [],
                'message': 'Проверенного официального сайта пока нет. Сохранённые сведения доступны с датами источников.'}
    official = urlsplit(website['value']).hostname or ''
    inn = base['inn']
    sources = base.get('sources', [])
    identity_ids = set(website.get('sourceIds', []))
    identity_sources = [s for s in sources if s['id'] in identity_ids and s.get('identityVerified') and s.get('identityInn') == inn]
    offers = [s for s in sources if s.get('scope') == 'commercial_offer' and s.get('identityVerified')]
    chosen = []
    for source in identity_sources + offers:
        if source.get('url') and source['url'] not in [s['url'] for s in chosen]:
            chosen.append(source)
    if not chosen:
        return {'status': 'needs_source', 'profile': None, 'pages': [], 'message': 'Нет проверенной страницы реквизитов компании.'}
    pages, errors = [], []
    for source in chosen[:MAX_PAGES]:
        try:
            page = fetch(source['url'], official)
            parser = PageText()
            parser.feed(page['text'])
            visible = ' '.join(' '.join(parser.parts).split())
            identity_pattern = r'\bИНН(?:\s+организации)?(?:\s*/\s*КПП)?\s*[:;№]?\s*([0-9](?:[0-9\s]*[0-9])?)'
            mentioned_inns = {re.sub(r'\s', '', m.group(1)) for m in re.finditer(identity_pattern, visible, re.I)}
            identity = inn in mentioned_inns
            requisites = {}
            if mentioned_inns == {inn}:
                for key, pattern in [('ogrn', r'\bОГРН(?:ИП)?\s*[:№]?\s*([0-9]{13}(?:[0-9]{2})?)(?![0-9])'),
                                     ('kpp', r'\bКПП\s*[:№]?\s*([0-9]{9})(?![0-9])')]:
                    matches = list(re.finditer(pattern, visible, re.I))
                    values = {m.group(1) for m in matches}
                    if len(values) == 1:
                        value = next(iter(values))
                        if key == 'ogrn' and len(value) != (13 if len(inn) == 10 else 15):
                            continue
                        if key == 'ogrn' and int(value[:-1]) % (11 if len(value) == 13 else 13) % 10 != int(value[-1]):
                            continue
                        if key == 'kpp' and len(inn) != 10:
                            continue
                        requisites[key] = {'value': value, 'text': matches[0].group(0)}
            pages.append({**page, 'requestedUrl': source['url'], 'visible': visible,
                          'contacts': parser.contacts if mentioned_inns == {inn} else [], 'identityVerified': identity,
                          'requisites': requisites, 'sourceId': 'live:' + hashlib.sha256(page['url'].encode()).hexdigest()[:24]})
        except (SourceFailure, ValueError) as exc:
            errors.append(str(exc))
    identity_pages = [p for p in pages if p['identityVerified']]
    if not identity_pages:
        return {'status': 'unconfirmed' if pages else 'failed', 'profile': None, 'pages': pages,
                'message': 'При обновлении не удалось подтвердить ИНН на официальной странице. Прежние сведения сохранены.', 'errors': errors}
    at = max(p['fetchedAt'] for p in pages)

    base['sources'] = [s for s in sources if not s['id'].startswith('live:')]
    contacts, seen = [], set()
    for page in identity_pages:
        for contact in page['contacts']:
            normalized = re.sub(r'\D', '', contact['value']) if contact['kind'] == 'phone' else contact['value'].casefold()
            if contact['kind'] == 'phone' and len(normalized) == 11 and normalized.startswith('8'):
                normalized = '7' + normalized[1:]
            key = (contact['kind'], normalized)
            if key not in seen:
                seen.add(key)
                contacts.append({**contact, 'sourceIds': [page['sourceId']]})
    matched_offers = []
    for page in pages:
        excerpts = [s.get('excerpt', '') for s in offers if s['url'] in (page['url'], page['requestedUrl'])]
        for excerpt in excerpts:
            if excerpt and ' '.join(excerpt.split()) in page['visible']:
                matched_offers.append({'text': excerpt, 'scope': 'commercial_offer', 'sourceIds': [page['sourceId']]})
        excerpt = next((s.get('excerpt', '') for s in identity_sources if s.get('excerpt') and ' '.join(s['excerpt'].split()) in page['visible']), '')
        if not excerpt and page['identityVerified']:
            match = re.search(r'\bИНН\b', page['visible'], re.I)
            excerpt = page['visible'][max(0, match.start()-100):match.end()+200] if match else ''
        contact_text = ' '.join(c['text'] for c in page['contacts']) if page['identityVerified'] else ''
        quote = ' '.join(x for x in (excerpt, contact_text, *[r['text'] for r in page['requisites'].values()],
                                     *[x['text'] for x in matched_offers if page['sourceId'] in x['sourceIds']]) if x)
        base['sources'].append({'id': page['sourceId'], 'url': page['url'], 'title': 'Официальный сайт: проверено при подборе',
                                'excerpt': quote[:6000], 'fetchedAt': page['fetchedAt'], 'publishedAt': None, 'contentDate': None,
                                'dateSemantics': 'retrieval_time_only', 'contentHash': page['contentHash'], 'hashScope': 'exact_http_body',
                                'identityVerified': True, 'identityInn': inn, 'scope': 'fresh_official_page',
                                'identityBasisSourceIds': [p['sourceId'] for p in identity_pages]})
    def field(value, ids):
        """Собрать подтверждённое поле из value, source IDs ids и времени at.

        Используется только после проверки страниц; возвращает новый словарь
        value/status/sourceIds/observedAt и не меняет внешнее состояние."""
        return {'value': value, 'status': 'verified', 'sourceIds': ids, 'observedAt': at}
    base['fields']['website'] = field(website['value'], [p['sourceId'] for p in identity_pages])
    if contacts:
        base['fields']['contacts'] = field(contacts[:100], list(dict.fromkeys(s for c in contacts for s in c['sourceIds'])))
    for key in ('ogrn', 'kpp'):
        matches = [(p['requisites'][key]['value'], p['sourceId']) for p in identity_pages if key in p['requisites']]
        if len({v for v, _ in matches}) == 1:
            base['fields'][key] = field(matches[0][0], [sid for _, sid in matches])
    name = base['fields'].get('name', {})
    if name.get('status') == 'verified' and name.get('value'):
        matches = [p['sourceId'] for p in identity_pages if name['value'] in p['visible']]
        if matches:
            base['fields']['name'] = field(name['value'], matches)
    if matched_offers:
        previous = base['fields'].get('activities', {})
        retained = [a for a in previous.get('value', []) or [] if isinstance(a, dict) and a.get('scope') != 'commercial_offer']
        values = (retained + matched_offers)[:100]
        ids = list(dict.fromkeys(s for a in values for s in a.get('sourceIds', [])))
        base['fields']['activities'] = field(values, ids)
        if retained:

            base['fields']['activities']['observedAt'] = previous.get('observedAt')
    base['updatedAt'] = at
    return {'status': 'complete', 'profile': base, 'pages': pages, 'errors': errors,
            'message': 'Официальный сайт проверен. Даты и источники сохранены; наличие товара уточните у компании.'}
