"""Читать ограниченную историю разрешённых ИНН из неизменяемого SQLite sidecar.

История участия дополняет карточку компании, но не изменяет сохранённые
признаки модели и не доказывает исполнение договоров."""
import json
from contextlib import closing
from pathlib import Path
import sqlite3
from django.conf import settings


def history_for(inns):
    """Вернуть историю по ИНН inns, доступ к которым уже разрешён endpoint.

    Читает COMPANY_HISTORY_CATALOG либо history_summaries.sqlite рядом
    с каталогом профилей. SQLite открыт mode=ro&immutable=1; ИНН запрашиваются
    пакетами по 500. Payload свыше 128 КиБ пропускается; выдача ограничена
    10 категориями, 10 предметами и 20 примерами без произвольных полей файла.

    Возвращает словарь ИНН → сводка. Нет файла либо возникла ошибка чтения,
    JSON или SQLite - возвращает пустой словарь. Данные не изменяет, сеть
    не вызывает; доступ пользователя к ИНН проверяется до вызова."""
    path = getattr(settings, 'COMPANY_HISTORY_CATALOG', None)
    if not path:
        from .company_profiles import _path
        path = _path().parent / 'history_summaries.sqlite'
    path = Path(path)
    if not path.is_file():
        return {}
    result = {}
    values = list(dict.fromkeys(inns))
    try:
        with closing(sqlite3.connect(path.resolve().as_uri() + '?mode=ro&immutable=1', uri=True, timeout=1)) as con:
            meta = {}
            for key, value in con.execute('SELECT key,value FROM metadata'):
                try:
                    meta[key] = json.loads(value)
                except (ValueError, TypeError):
                    meta[key] = value
            for offset in range(0, len(values), 500):
                batch = values[offset:offset+500]
                rows = con.execute('SELECT inn,payload FROM supplier_history WHERE inn IN (' + ','.join('?' for _ in batch) + ')', batch)
                for inn, payload in rows:
                    if len(payload) > 128 * 1024:
                        continue
                    raw = json.loads(payload)
                    if raw.get('inn') != inn:
                        continue

                    out = {key: raw.get(key) for key in ('inn','lotCount','firstSeen','lastSeen','sourceCounts','scope','identityQuality')}
                    out['topCategories'] = raw.get('topCategories', [])[:10]
                    out['subjects'] = raw.get('subjects', [])[:10]
                    out['examples'] = raw.get('examples', [])[:20]
                    out['version'] = meta.get('version')
                    out['sourceHash'] = meta.get('sourceHash') or meta.get('source_sha256')
                    out['sourceCutoff'] = meta.get('sourceCutoff')
                    out['scope'] = 'Дополнительная история наблюдаемых участий из предоставленных данных. Не означает исполнение договоров и не подмешивается в сохранённый расчёт рекомендаций.'
                    result[inn] = out
    except (OSError, ValueError, TypeError, sqlite3.Error):
        return {}
    return result


def diligence(profile, history):
    """Собрать состояния доступных свидетельств profile и history для карточки.

    Аргументы - проверенный профиль и сводка участия либо None. Возвращает
    словарь summary/checks: имя, прямой статус ФНС и наблюдаемые участия;
    исполнение, финансы и РНП остаются unknown. Это не оценка надёжности.
    Ввод не изменяет, БД и сеть не использует; ожидает согласованную схему."""
    fields = profile.get('fields', {}) if profile else {}
    name = fields.get('name', {})
    legal = fields.get('legalStatus', {})
    return {'summary': 'Сведения помогают подготовить проверку контрагента. Оценка надёжности сделки не рассчитывается.',
            'checks': [
                {'id':'identity','title':'Реквизиты компании','status':name.get('status') if name.get('status') in ('verified','conflict') else 'unknown',
                 'value':name.get('value') if name.get('status')=='verified' else None,'sourceIds':name.get('sourceIds',[]),
                 'limitation':'Связь имени с ИНН подтверждается указанным источником; даты приведены отдельно.'},
                {'id':'registration','title':'Юридический статус','status':legal.get('status') if legal.get('status') in ('verified','conflict') else 'unknown',
                 'value':legal.get('value') if legal.get('status')=='verified' else None,'sourceIds':legal.get('sourceIds',[]),
                 'limitation':'Только прямые сведения ФНС. Лицензия и участие в закупках не подтверждают текущий юридический статус.'},
                {'id':'participation','title':'Опыт участия','status':'observed' if history and history.get('lotCount') else 'unknown',
                 'value':history.get('lotCount') if history else None,'sourceIds':[],
                 'limitation':'Количество уникальных лотов в предоставленной истории. Это не число успешно исполненных договоров.'},
                {'id':'execution','title':'Исполнение договоров','status':'unknown','value':None,'sourceIds':[],
                 'limitation':'Нет проверенных актов исполнения, просрочек или претензий. Победа не приравнивается к исполнению.'},
                {'id':'finances','title':'Финансовое состояние','status':'unknown','value':None,'sourceIds':[],
                 'limitation':'Финансовая отчётность и платёжеспособность в этой проверке не анализировались.'},
                {'id':'rnp','title':'Реестр недобросовестных поставщиков','status':'unknown','value':None,'sourceIds':[],
                 'limitation':'Прямая актуальная проверка реестра не выполнена; отсутствие данных не означает отсутствие записи.'},
            ]}
