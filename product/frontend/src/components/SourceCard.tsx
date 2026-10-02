import type { SourceEvidence } from '../domain/types.js';
import { date, dateTime, safeURL } from '../domain/format.js';
import { Disclosure } from './ui.js';
import { Icon } from './Icon.js';
import s from '../styles/pages.module.css';

/**
 * Даты источника с явным смыслом: дата публикации или выгрузки (если известна) отделена
 * от времени, когда система получила страницу. Время получения не выдаётся за дату содержания.
 */
export function sourceDates(source: SourceEvidence): string[] {
  const rows: string[] = [];
  if (source.publishedAt) rows.push(`опубликовано ${date(source.publishedAt)}`);
  else if (source.contentDate) rows.push(source.dateSemantics?.startsWith('registry_snapshot') ? `выгрузка реестра от ${date(source.contentDate)}` : `дата содержания ${date(source.contentDate)}`);
  else rows.push('дата публикации неизвестна');
  if (source.updatedAt) rows.push(`обновлено ${date(source.updatedAt)}`);
  if (source.fetchedAt) rows.push(`получено системой ${dateTime(source.fetchedAt)}`);
  return rows;
}

/** Что подтверждает источник: связь с ИНН и область подтверждения простыми словами. */
function confirms(source: SourceEvidence): string {
  if (source.id.startsWith('history:')) return 'Участие в закупке с похожими позициями. Исполнение договора не подтверждено.';
  const parts = [source.identityVerified ? 'Связь с ИНН компании подтверждена источником.' : 'Связь с ИНН компании не подтверждена независимо.'];
  if (source.scope === 'licensed_activity' || /лицензи/i.test(source.title)) parts.push('Подтверждает лицензируемый вид деятельности, а не конкретный товар.');
  else if (source.scope && source.scope.length < 400 && !/^[a-z_]+$/.test(source.scope)) parts.push(source.scope);
  return parts.join(' ');
}

/** Компактная запись источника: название, что подтверждено, даты, ссылка; фрагмент и связанные публикации раскрываются по запросу. */
export function SourceCard({ source }: { source: SourceEvidence }) {
  const url = safeURL(source.url), dated = source.freshness?.dated_activity_sources ?? [], identity = source.identity?.evidence ?? [];
  return <article className={s.sourceItem}>
    <div className={s.sourceHead}><h3>{source.title || 'Источник компании'}</h3>{url && <a href={url} target="_blank" rel="noopener noreferrer" className={s.externalLink}>Открыть<Icon name="external" size={15} /><span className={s.visuallyHidden}> (в новой вкладке)</span></a>}</div>
    <p>{confirms(source)}</p>
    <p className={s.muted}>{sourceDates(source).join(' · ')}</p>
    {(source.excerpt || dated.length > 0 || identity.length > 0) && <Disclosure summary="Фрагмент и подробности">
      {source.excerpt ? <blockquote className={s.quote}>{source.excerpt}</blockquote> : <p className={s.muted}>Текст фрагмента не сохранён.</p>}
      {source.verificationScope && <p className={s.muted}>Проверено: {source.verificationScope}</p>}
      {dated.length > 0 && <><h4 className={s.miniTitle}>Датированные публикации компании</h4><p className={s.muted}>Дата относится к публикации и не подтверждает исполненный договор или актуальность всего каталога.</p><ul className={s.plainList}>{dated.map((item, index) => <li key={index}>{date(item.published_at)}{item.excerpt ? ` - ${item.excerpt}` : ''} {safeURL(item.url) && <a href={safeURL(item.url)!} target="_blank" rel="noopener noreferrer">открыть</a>}</li>)}</ul></>}
      {identity.length > 0 && <><h4 className={s.miniTitle}>Основание связи с ИНН</h4><ul className={s.plainList}>{identity.map((item, index) => <li key={index}>{item.excerpt}{safeURL(item.url) && <> <a href={safeURL(item.url)!} target="_blank" rel="noopener noreferrer">страница</a></>}</li>)}</ul></>}
    </Disclosure>}
  </article>;
}
