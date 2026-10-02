"""Offline, deterministic report over an immutable owned result snapshot.

No network calls or generated company claims. The full machine-readable
snapshot remains available as JSON when a human-readable section is bounded.
"""
import io
from pathlib import Path
from urllib.parse import urlsplit
from xml.sax.saxutils import escape

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, HRFlowable


FONTS = Path(__file__).resolve().parents[1] / 'fonts'
pdfmetrics.registerFont(TTFont('Supply', str(FONTS / 'LiberationSans-Regular.ttf')))
pdfmetrics.registerFont(TTFont('SupplyBold', str(FONTS / 'LiberationSans-Bold.ttf')))
pdfmetrics.registerFontFamily('Supply', normal='Supply', bold='SupplyBold')
INK = colors.HexColor('#222344')
MUTED = colors.HexColor('#62657B')


def plain(value):
    value = str(value if value is not None else 'Не указано')
    # No user-supplied markup, remote images, or control characters in a PDF.
    value = ''.join(c for c in value if ord(c) >= 32 or c in '\n\t')
    return escape(value).replace('\n', '<br/>')


def build_pdf(query, options=None):
    options = options or {}
    selected = set(options.get('companyIds') or [])
    business = options.get('reportVersion') == 'business-v2'
    body = ParagraphStyle('body', fontName='Supply', fontSize=9.5, leading=14,
                          textColor=INK, spaceAfter=7, splitLongWords=True)
    small = ParagraphStyle('small', parent=body, fontSize=8, leading=11.5, textColor=MUTED)
    heading = ParagraphStyle('heading', parent=body, fontName='SupplyBold', fontSize=15,
                             leading=19, spaceBefore=16, spaceAfter=10, keepWithNext=True)
    sub = ParagraphStyle('sub', parent=body, fontName='SupplyBold', fontSize=11,
                         leading=15, spaceBefore=11, keepWithNext=True)
    title = ParagraphStyle('title', parent=heading, fontSize=25, leading=29, spaceBefore=8)
    story = []
    def p(value, style=body):
        story.append(Paragraph(plain(value), style))
    def rule():
        story.append(HRFlowable(width='100%', thickness=0.5, color=colors.HexColor('#DDD9EF')))
    p('ПОДБОР КОНТРАГЕНТОВ', small)
    p('Отчёт по закупке', title)
    procurement = query.get('procurement') or {}
    p(procurement.get('subject') or 'Предмет не указан', sub)
    p(f"Лот: {procurement.get('lotId') or 'Не указан'} | Запрос: {query['id']}", small)
    p(f"Сформирован: {options.get('generatedAt') or query.get('processedAt') or query.get('createdAt') or 'Не указано'}", small)
    if not business:
        p(f"Версия результата: {query.get('resultVersion') or 'Не указана'}", small)
    rule()

    historical = [r for r in query.get('recommendations', [])
                  if not selected or r['company']['id'] in selected]
    external = [r for r in query.get('externalCandidates', [])
                if not selected or r['company']['id'] in selected]
    p('Результат и его границы', heading)
    p(f'В отчёте: {len(historical)} исторических рекомендаций и {len(external)} внешних кандидатов.')
    p('История показывает наблюдаемое участие в закупках. Оно не подтверждает ассортимент каждой позиции. '
      'Внешние источники дают основания для проверки компании, но не гарантируют полное соответствие лоту. '
      + ('Порядок списка помогает выбрать, с кем связаться сначала. Условия и соответствие нужно уточнить у компании.' if business
         else 'Оценки двух списков имеют разный смысл и не являются вероятностями успешной поставки.'))
    if not historical and not external:
        p(query.get('message') or 'Для этой версии запроса сохранённых рекомендаций нет.')
    for warning in query.get('warnings', [])[:30]:
        p('Примечание: ' + str(warning), small)

    p('Исходные позиции ТРУ', heading)
    items = query.get('rawItems') or procurement.get('items') or []
    p(f'Всего исходных строк: {len(items)}. Повторы сохранены.', small)
    for index, item in enumerate(items[:100], 1):
        p(f"{index}. {item.get('product_name', item.get('name', ''))}")
        p(f"ОКПД2: {item.get('okpd2_code', item.get('okpd2')) or 'Не указан'}", small)
    if len(items) > 100:
        p((f'В PDF показаны первые 100 из {len(items)} строк. Полный состав доступен в экспорте JSON.' if business else
           f'В PDF показаны первые 100 из {len(items)} строк. Полный состав доступен в экспорте JSON и CSV.'), small)

    for label, recommendations in [('Исторические рекомендации', historical), ('Внешние кандидаты', external)]:
        p(label, heading)
        if not recommendations:
            p('В этой подборке отсутствуют.', small)
            continue
        for rec in recommendations[:100]:
            company = rec['company']
            display_name = company.get('displayName') if business else None
            p(f"{rec.get('rank', '')}. {display_name or company.get('name') or company.get('inn') or 'Компания'}", sub)
            p(f"ИНН: {company.get('inn') or 'Не указан'} | Роль: "
              + ('подтверждение приведено в источнике' if (company.get('role') or {}).get('verified') else 'не подтверждена'), small)
            if company.get('newToFullHistory') is not None:
                p('В полной исходной истории: ' + ('не встречается' if company['newToFullHistory'] else 'встречается'), small)
            score = rec.get('score')
            if not business and isinstance(score, (int, float)):
                p(f"Балл: {score:.6g}. Тип оценки: {rec.get('scoreKind') or 'ранжирование'}; не вероятность.", small)
            p((rec.get('explanationSummary') if business else rec.get('reason')) or 'Основания приведены ниже; пригодность требует проверки.')
            if business:
                for criterion in rec.get('explanationCriteria', []):
                    p(str(criterion.get('label') or '') + '. ' + str(criterion.get('basis') or ''), small)
                for note in rec.get('explanationNotes', []):
                    p('Уточнить: ' + str(note), small)
                profile = company.get('currentProfile') or company.get('profileAtCalculation') or {}
                fields = profile.get('fields', {})
                for field_name, field_label in [('description', 'О компании'), ('ogrn', 'ОГРН'), ('kpp', 'КПП'), ('region', 'Регион'), ('website', 'Сайт'), ('legalStatus', 'Сведения ФНС о статусе')]:
                    field = fields.get(field_name, {})
                    if field.get('status') == 'verified' and field.get('value'):
                        p(field_label + ': ' + str(field['value']), small)
                if profile.get('updatedAt'):
                    p('Сведения о компании из доступного каталога на момент экспорта. Обновление каталога: ' + str(profile['updatedAt']) + '. Порядок рекомендаций сохранён из исходного расчёта.', small)
                history = company.get('historySummary') or {}
                if history.get('lotCount'):
                    p('Опыт участия: ' + str(history['lotCount']) + ' уникальных закупок в предоставленной истории; период ' + str(history.get('firstSeen') or 'неизвестно') + ' - ' + str(history.get('lastSeen') or 'неизвестно') + '. Успешное исполнение не подтверждено.', small)
                    for example in history.get('examples', [])[:3]:
                        p('Пример участия: ' + str(example.get('date') or '') + ', лот ' + str(example.get('lotId') or '') + '. ' + str(example.get('subject') or ''), small)
                for check in (company.get('dueDiligence') or {}).get('checks', []):
                    if check.get('status') == 'unknown':
                        p('Перед сделкой - ' + str(check.get('title') or '') + ': ' + str(check.get('limitation') or 'сведения не проверены'), small)
                if not any(v.get('status') == 'verified' for v in fields.values()):
                    p('Дополнительные сведения о компании пока не подтверждены.', small)
            evidence = rec.get('evidence') or []
            for row in evidence[:30]:
                p(f"Позиция {row.get('itemId', '')}: {row.get('reason') or 'Соответствие не установлено'}", small)
            if len(evidence) > 30:
                p(f'В PDF показаны 30 из {len(evidence)} пояснений; полный список доступен в JSON.', small)
            sources = list(company.get('sources') or [])
            if business:
                profile_sources = profile.get('sources', [])
                unique = {source['id']: source for source in sources + profile_sources}
                sources = list(unique.values())
            for n, source in enumerate(sources[:6], 1):
                p(f"Источник {n}. {source.get('title') or 'Документальное основание'}", small)
                if source.get('excerpt'):
                    p(source['excerpt'], small)
                if source.get('scope'):
                    p('Границы основания: ' + str(source['scope']), small)
                url = source.get('url')
                if isinstance(url, str) and urlsplit(url).scheme in ('https', 'http') and urlsplit(url).hostname:
                    p(url, small)
                p(f"Получен: {source.get('fetchedAt') or 'неизвестно'}; публикация: {source.get('publishedAt') or 'неизвестно'}. "
                  'Дата получения не доказывает актуальность содержания.', small)
                if source.get('contentDate') and business:
                    p('Дата исходного документа: ' + str(source['contentDate']) + '. Статус компании отдельно не установлен.', small)
                if not business and source.get('contentHash'):
                    p('SHA-256 источника: ' + str(source['contentHash']), small)
            if len(sources) > 6:
                p(f'Показаны 6 из {len(sources)} источников. Все источники сохранены в JSON.', small)
            if not sources:
                p('Публичный источник с предметным предложением в этой версии не подтверждён.', small)
            story.append(Spacer(1, 6))
            rule()

    p('Как читать отчёт', heading)
    p('ОКПД2 помогает искать кандидатов, но не заменяет описание ТРУ. Для смешанного лота следует '
      'проверять каждую позицию, обязательные размеры, модели, материалы и вид услуги. '
      'Сведения старше 36 месяцев не удаляются автоматически; возраст и отсутствие даты раскрываются отдельно. '
      'Неизвестная роль или характеристика не превращается в подтверждённый факт.')
    p('Отчёт составлен локально из сохранённых данных системой 404: Loss not found. '
      'Текст объяснений основан на правилах и источниках; генеративная модель не дописывает факты.', small)
    if not business:
        p(f"Модель: {query.get('modelVersion') or 'не указана'}; каталог: {query.get('catalogVersion') or 'не указан'}", small)
    else:
        p('Исходные данные, версии расчёта и полные основания доступны в экспорте JSON.', small)

    output = io.BytesIO()
    doc = SimpleDocTemplate(output, pagesize=A4, leftMargin=44, rightMargin=44,
                            topMargin=42, bottomMargin=44, title='Подбор контрагентов - отчёт',
                            author='404: Loss not found', pageCompression=1, invariant=1)
    def footer(canvas, document):
        canvas.saveState()
        canvas.setFillColor(MUTED)
        canvas.setFont('Supply', 8)
        canvas.drawString(44, 25, '404: Loss not found | Подбор контрагентов')
        canvas.drawRightString(A4[0]-44, 25, str(document.page))
        canvas.restoreState()
    doc.build(story, onFirstPage=footer, onLaterPages=footer)
    return output.getvalue()
