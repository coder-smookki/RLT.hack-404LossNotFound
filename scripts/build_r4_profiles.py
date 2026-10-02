"""Сборка SQLite-приложения к каталогу профилей компаний (supplier-profile.v1) из пакета S9 R4.

Приложение является слоем текущих сведений: оно не участвует в ранжировании и не меняет
сохранённые результаты подбора. Основной JSON-каталог остаётся главным для своих компаний;
приложение читается по ИНН только для компаний конкретной выдачи. Каждое значение ссылается на
официальную запись (реестр МСП ФНС или реестр лицензий) с SHA-256 точной строки, датой выгрузки
и адресом исходного файла.
"""
import argparse
import hashlib
import json
import os
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

REGIONS = {
    '01': 'Республика Адыгея', '02': 'Республика Башкортостан', '03': 'Республика Бурятия', '04': 'Республика Алтай', '05': 'Республика Дагестан',
    '06': 'Республика Ингушетия', '07': 'Кабардино-Балкарская Республика', '08': 'Республика Калмыкия', '09': 'Карачаево-Черкесская Республика',
    '10': 'Республика Карелия', '11': 'Республика Коми', '12': 'Республика Марий Эл', '13': 'Республика Мордовия', '14': 'Республика Саха (Якутия)',
    '15': 'Республика Северная Осетия - Алания', '16': 'Республика Татарстан', '17': 'Республика Тыва', '18': 'Удмуртская Республика',
    '19': 'Республика Хакасия', '20': 'Чеченская Республика', '21': 'Чувашская Республика', '22': 'Алтайский край', '23': 'Краснодарский край',
    '24': 'Красноярский край', '25': 'Приморский край', '26': 'Ставропольский край', '27': 'Хабаровский край', '28': 'Амурская область',
    '29': 'Архангельская область', '30': 'Астраханская область', '31': 'Белгородская область', '32': 'Брянская область', '33': 'Владимирская область',
    '34': 'Волгоградская область', '35': 'Вологодская область', '36': 'Воронежская область', '37': 'Ивановская область', '38': 'Иркутская область',
    '39': 'Калининградская область', '40': 'Калужская область', '41': 'Камчатский край', '42': 'Кемеровская область', '43': 'Кировская область',
    '44': 'Костромская область', '45': 'Курганская область', '46': 'Курская область', '47': 'Ленинградская область', '48': 'Липецкая область',
    '49': 'Магаданская область', '50': 'Московская область', '51': 'Мурманская область', '52': 'Нижегородская область', '53': 'Новгородская область',
    '54': 'Новосибирская область', '55': 'Омская область', '56': 'Оренбургская область', '57': 'Орловская область', '58': 'Пензенская область',
    '59': 'Пермский край', '60': 'Псковская область', '61': 'Ростовская область', '62': 'Рязанская область', '63': 'Самарская область',
    '64': 'Саратовская область', '65': 'Сахалинская область', '66': 'Свердловская область', '67': 'Смоленская область', '68': 'Тамбовская область',
    '69': 'Тверская область', '70': 'Томская область', '71': 'Тульская область', '72': 'Тюменская область', '73': 'Ульяновская область',
    '74': 'Челябинская область', '75': 'Забайкальский край', '76': 'Ярославская область', '77': 'Москва', '78': 'Санкт-Петербург',
    '79': 'Еврейская автономная область', '83': 'Ненецкий автономный округ', '86': 'Ханты-Мансийский автономный округ - Югра',
    '87': 'Чукотский автономный округ', '89': 'Ямало-Ненецкий автономный округ', '91': 'Республика Крым', '92': 'Севастополь',
}
LICENSE_TITLES = {'medical_service': 'Росздравнадзор: реестр лицензий на техобслуживание медизделий', 'pharma': 'Росздравнадзор: реестр фармацевтических лицензий',
                  'narcotic': 'Росздравнадзор: реестр лицензий на оборот наркотических средств', 'rospotreb': 'Роспотребнадзор: реестр лицензий',
                  'mchs_install': 'МЧС: реестр лицензий на монтаж средств пожарной безопасности', 'mchs_fire': 'МЧС: реестр лицензий на тушение пожаров',
                  'crimea': 'Росздравнадзор: реестр лицензий (Крым)'}
MSP = 'fns_msp_20241210'


def record_lines(root, export):
    """Возвращает точные байты строк JSONL-выгрузки записей по номеру строки (с 1)."""
    path = root / export
    with path.open('rb') as handle:
        return {n: line.rstrip(b'\n') for n, line in enumerate(handle, 1)}


def ddmmyyyy(value):
    """Дата ГГГГ-ММ-ДД в формате ДД.ММ.ГГГГ; пустое значение остаётся пустым."""
    return f'{value[8:10]}.{value[5:7]}.{value[:4]}' if value and len(value) >= 10 else ''


def field(value, source_ids, observed):
    return {'value': value, 'status': 'verified', 'sourceIds': source_ids, 'observedAt': observed}


def r4_profile(inn, card, msp, licenses, exports, r4_root, generated):
    """Профиль одной компании только из официальных записей R4 и исторической сводки участий.

    Returns:
        Профиль в формате supplier-profile.v1 (с полем historyStats) или None, если сведений нет.
    """
    lots, wins = card.get('historical_lot_count') or 0, card.get('historical_winner_lot_count') or 0
    if not msp and not licenses and not lots:
        return None
    read = lambda export, line: (exports[export] if export in exports else exports.setdefault(export, record_lines(r4_root, export)))[line]
    fields, sources, activities = {}, [], []
    if msp:
        _, _, _, url, locator, date, fetched, archive_sha, export, line = msp
        raw = read(export, line); record = json.loads(raw)['record']; sid = f'msp:{inn}'
        region = REGIONS.get(str(record.get('region') or ''))
        sources.append({'id': sid, 'url': url, 'title': 'ФНС: реестр субъектов МСП, выгрузка 10.12.2024',
                        'excerpt': '; '.join(filter(None, [f'ИНН {inn}', record.get('company_name'), f"ОГРН {record['ogrn']}" if record.get('ogrn') else '',
                                                           f'регион {region}' if region else '', f"в реестре МСП с {ddmmyyyy(record.get('msp_inclusion_date'))}" if record.get('msp_inclusion_date') else ''])),
                        'fetchedAt': fetched or None, 'contentDate': date, 'dateSemantics': 'registry_snapshot_date_from_source_filename',
                        'contentHash': hashlib.sha256(raw).hexdigest(), 'hashScope': 'exact_S9_R4_jsonl_record_line', 'sourceArchiveHash': archive_sha,
                        'identityVerified': True, 'identityInn': inn, 'scope': 'historical_tax_registry_identity', 'locator': locator, 'kind': 'registry_msp'})
        observed = f'{date}T00:00:00+00:00'
        for name, value in (('name', record.get('company_name')), ('ogrn', record.get('ogrn')), ('region', region)):
            if value:
                fields[name] = field(value, [sid], observed)
        activities += [{'text': f"ОКВЭД {o.get('КодОКВЭД', '')} - {o.get('НаимОКВЭД', '')}", 'scope': 'declared_okved', 'sourceIds': [sid]} for o in record.get('okved', [])[:3]]
    for index, (_, _, source_id, url, locator, date, fetched, archive_sha, export, line) in enumerate(licenses):
        raw = read(export, line); sid = f'lic:{source_id}:{index}'
        rows = [a.get('activity', '') for a in card.get('licensed_activity', []) if a.get('source') == source_id and a.get('activity')]
        sources.append({'id': sid, 'url': url, 'title': LICENSE_TITLES[source_id], 'excerpt': (f'ИНН {inn}; ' + '; '.join(rows))[:600],
                        'fetchedAt': fetched or None, 'contentDate': date or None, 'dateSemantics': 'license_event_date',
                        'contentHash': hashlib.sha256(raw).hexdigest(), 'hashScope': 'exact_S9_R4_jsonl_record_line', 'sourceArchiveHash': archive_sha,
                        'identityVerified': True, 'identityInn': inn, 'scope': 'licensed_activity', 'locator': locator, 'kind': 'registry_license'})
        activities = [{'text': text, 'scope': 'licensed_activity', 'sourceIds': [sid]} for text in dict.fromkeys(rows)] + activities
    if activities:
        fields['activities'] = field(activities[:20], list(dict.fromkeys(i for a in activities[:20] for i in a['sourceIds'])), generated)
    profile = {'inn': inn, 'fields': fields, 'sources': sources}
    if lots:
        profile['historyStats'] = {'lotCount': int(lots), 'winnerLotCount': int(wins), 'period': '2024-2025', 'source': 'Исходные данные закупок 24-25 (S9 R4)'}
    return profile


def build(r4_root, output_path):
    """Собирает SQLite-приложение профилей R4 и атомарно заменяет файл.

    Args:
        r4_root: папка распакованного S9 R4 (dataset.sqlite и sources/records).
        output_path: путь итогового supplier_profiles_r4.sqlite.
    Returns:
        Счётчики и SHA-256 содержимого для журнала проверки.
    """
    db = sqlite3.connect(r4_root / 'dataset.sqlite')
    links = {}
    for row in db.execute('select inn, evidence_id, source_id, source_url, source_locator, evidence_date, fetched_at, source_file_sha256, record_export, record_line from supplier_evidence_links where source_id in (%s) order by evidence_id' % ','.join('?' * (len(LICENSE_TITLES) + 1)), [MSP, *LICENSE_TITLES]):
        links.setdefault(row[0], []).append(row)
    exports, generated, digest = {}, datetime.now(timezone.utc).isoformat(), hashlib.sha256()
    stats = {'profiles': 0, 'mspIdentity': 0, 'licensed': 0, 'historyStats': 0}
    output_path.parent.mkdir(parents=True, exist_ok=True)
    tmp = output_path.with_suffix('.tmp')
    tmp.unlink(missing_ok=True)
    out = sqlite3.connect(tmp)
    out.execute('create table profiles(inn text primary key not null, payload text not null) without rowid')
    out.execute('create table metadata(key text primary key not null, value text not null) without rowid')
    for inn, body in db.execute('select inn, body from suppliers order by inn'):
        own = links.get(inn, [])
        msp = next((row for row in own if row[2] == MSP), None)
        profile = r4_profile(inn, json.loads(body), msp, [row for row in own if row[2] in LICENSE_TITLES], exports, r4_root, generated)
        if not profile:
            continue
        payload = json.dumps(profile, ensure_ascii=False, separators=(',', ':'), sort_keys=True)
        digest.update(payload.encode())
        out.execute('insert into profiles values (?, ?)', (inn, payload))
        stats['profiles'] += 1; stats['mspIdentity'] += bool(msp); stats['licensed'] += any(s['kind'] == 'registry_license' for s in profile['sources']); stats['historyStats'] += 'historyStats' in profile
    meta = {'schemaVersion': 'supplier-profile-sidecar.v1', 'version': 'S9-R4-20261002', 'generatedAt': generated, 'contentSha256': digest.hexdigest(),
            'limitations': 'Реестр МСП - историческая идентификация на 10.12.2024; ОКВЭД и лицензии описывают заявленную или разрешённую деятельность; победа не означает исполнение договора.'}
    out.executemany('insert into metadata values (?, ?)', list(meta.items()))
    out.commit(); out.close()
    os.replace(tmp, output_path)
    return {**stats, 'contentSha256': meta['contentSha256'], 'bytes': output_path.stat().st_size}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--r4', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(build(args.r4, args.output), ensure_ascii=False, indent=1))
