import React, { type ReactNode } from 'react';
import type { Company, CompanyHistory, CompanyProfileField, SourceEvidence } from '../domain/types.js';
import { contactHref, verifiedContacts } from '../domain/presentation.js';
import { date, dateTime, number, plural, safeURL } from '../domain/format.js';
import { Badge, Card, Disclosure, Facts, Empty } from './ui.js';
import s from '../styles/pages.module.css';

const allSources = (c: Company): SourceEvidence[] => [...(c.currentProfile?.sources ?? []), ...(c.profileAtCalculation?.sources ?? [])].filter((source, index, list) => list.findIndex(row => row.id === source.id) === index);

/** Ссылка или название источника поля с датой получения. */
function SourceNote({ ids, company }: { ids: string[]; company: Company }) {
  const used = allSources(company).filter(source => ids.includes(source.id));
  if (!used.length) return null;
  return <>{used.map((source, i) => <React.Fragment key={source.id}>{i > 0 && '; '}{safeURL(source.url) ? <a href={safeURL(source.url)!} target="_blank" rel="noopener noreferrer">{source.title}</a> : source.title}{source.fetchedAt ? `, получено ${date(source.fetchedAt)}` : ''}</React.Fragment>)}</>;
}

/** Значение поля профиля только при подтверждённом источнике; иначе - честное «не найдено» или «не подтверждено». */
function fieldValue(field: CompanyProfileField | undefined, render: (value: string) => ReactNode = v => v): ReactNode {
  if (field?.status === 'verified' && typeof field.value === 'string' && field.value.trim()) return render(field.value.trim());
  if (field?.status === 'conflict') return <span className={s.muted}>источники противоречат друг другу</span>;
  if (field?.status === 'unverified') return <span className={s.muted}>не подтверждено</span>;
  return <span className={s.muted}>не найдено</span>;
}

/** Изменилось ли значение поля после расчёта: показывается, чтобы текущие сведения не выдавались за снимок расчёта. */
function snapshotNote(company: Company, key: string): string | null {
  const now = company.currentProfile?.fields[key], then = company.profileAtCalculation?.fields[key];
  if (!now || !then || typeof now.value !== 'string' || typeof then.value !== 'string' || now.value === then.value) return null;
  return `при расчёте: ${then.value}`;
}

/**
 * Реквизиты и деловые контакты с источником под каждым значением. Текущие сведения отделены
 * от момента расчёта рекомендаций; их обновление не меняет порядок кандидатов.
 */
export function RequisitesCard({ company, processedAt }: { company: Company; processedAt?: string | null }) {
  const f = (key: string) => company.currentProfile?.fields[key] ?? company.profileAtCalculation?.fields[key];
  const row = (label: string, key: string, render?: (v: string) => ReactNode) => ({ label, value: <>{fieldValue(f(key), render)}{snapshotNote(company, key) && <span className={s.factSnapshot}>{snapshotNote(company, key)}</span>}</>, source: f(key)?.status === 'verified' ? <SourceNote ids={f(key)!.sourceIds} company={company} /> : undefined });
  const contacts = verifiedContacts(company), rawActivities = Array.isArray(f('activities')?.value) && f('activities')?.status === 'verified' ? f('activities')!.value as { text?: string; scope?: string }[] : [];
  const activities = rawActivities.filter(a => a.text && a.scope !== 'declared_okved').map(a => a.text!), okved = rawActivities.filter(a => a.text && a.scope === 'declared_okved').map(a => a.text!);
  const updated = company.currentProfile?.updatedAt;
  return <Card className={s.padded}>
    <h2>Реквизиты и контакты</h2>
    <Facts rows={[
      row('Полное название', 'name'),
      { label: 'ИНН', value: company.inn ?? <span className={s.muted}>не указан</span> },
      row('ОГРН', 'ogrn'), row('КПП', 'kpp'), row('Регион', 'region'),
      row('Сайт', 'website', v => safeURL(v) ? <a href={safeURL(v)!} target="_blank" rel="noopener noreferrer">{v.replace(/^https?:\/\//, '').replace(/\/$/, '')}</a> : v),
      { label: 'Контакты', value: contacts.length ? <ul className={s.plainList}>{contacts.map((c, i) => <li key={i}>{contactHref(c) ? <a href={contactHref(c)}>{c.value}</a> : c.value}</li>)}</ul> : <span className={s.muted}>не найдены в подтверждённых источниках</span>, source: contacts.length ? <SourceNote ids={contacts.flatMap(c => c.sourceIds)} company={company} /> : undefined },
    ]} />
    {activities.length > 0 && <Disclosure summary={`Лицензируемые виды деятельности: ${activities.length}`}><ul className={s.plainList}>{activities.map((a, i) => <li key={i}>{a}</li>)}</ul><p className={s.muted}>Лицензия подтверждает разрешённый вид деятельности, а не наличие конкретного товара.</p></Disclosure>}
    {okved.length > 0 && <Disclosure summary={`Заявленные виды деятельности (ОКВЭД): ${okved.length}`}><ul className={s.plainList}>{okved.map((a, i) => <li key={i}>{a}</li>)}</ul><p className={s.muted}>ОКВЭД из реестра МСП на 10.12.2024 - заявленная деятельность, а не подтверждение поставок.</p></Disclosure>}
    <p className={s.muted}>{updated ? `Сведения о компании обновлены ${dateTime(updated)}.` : 'Сведения о компании ещё не обновлялись.'}{processedAt ? ` Порядок кандидатов рассчитан ${dateTime(processedAt)} и при обновлении сведений не меняется.` : ''}{contacts.length ? ' Доступность контактов не проверялась.' : ''}</p>
  </Card>;
}

const checkLabel = { verified: 'Есть источник', observed: 'Есть наблюдения', unknown: 'Не проверено', unverified: 'Не подтверждено', conflict: 'Есть противоречие' } as const;
/** Проверки перед сделкой: что подтверждено источником, а что остаётся непроверенным. Итоговой оценки надёжности нет. */
export function ChecksCard({ company }: { company: Company }) {
  const checks = company.dueDiligence?.checks ?? [];
  return <Card className={s.padded}>
    <h2>Проверки перед сделкой</h2>
    <p className={s.muted}>Система не оценивает надёжность. Непроверенное нужно проверить самостоятельно.</p>
    {checks.length ? <ul className={s.checkList}>{checks.map(check => <li key={check.id}>
      <div className={s.checkHead}><strong>{check.title}</strong><Badge tone={check.status === 'conflict' ? 'warning' : check.status === 'verified' || check.status === 'observed' ? 'info' : 'neutral'} icon={check.status === 'conflict'}>{checkLabel[check.status]}</Badge></div>
      {check.id === 'participation' && typeof check.value === 'number' ? <span>{number(check.value)} {plural(check.value, ['закупка', 'закупки', 'закупок'])} с участием</span> : null}
      <span className={s.muted}>{check.limitation}</span>
    </li>)}</ul> : <p>Юридический статус, исполнение договоров, финансовое состояние и реестр недобросовестных поставщиков не проверены.</p>}
  </Card>;
}

/** Опыт участия по предоставленной истории: число закупок с участием (не договоров), период, предметы и категории. */
export function ExperienceCard({ history, onOpen }: { history?: CompanyHistory | null; onOpen?: () => void }) {
  return <Card className={s.padded}>
    <h2>Опыт участия в закупках</h2>
    {history?.lotCount ? <>
      <div className={s.miniStats}><div><strong>{number(history.lotCount)}</strong><span>{plural(history.lotCount, ['закупка', 'закупки', 'закупок'])} с участием</span></div><div><strong>{date(history.firstSeen)} - {date(history.lastSeen)}</strong><span>период наблюдений</span></div></div>
      <p className={s.muted}>Это участие, а не исполненные договоры.{Object.keys(history.sourceCounts ?? {}).length ? ` Площадки: ${Object.entries(history.sourceCounts).map(([k, v]) => `${k} - ${v}`).join(', ')}.` : ''}</p>
      {history.subjects.length > 0 && <><h3 className={s.miniTitle}>Частые предметы закупок</h3><ul className={s.countList}>{history.subjects.slice(0, 5).map((subject, i) => <li key={i}><span>{subject.text}</span><span className={s.muted}>{subject.lotCount}</span></li>)}</ul></>}
      {history.topCategories.length > 0 && <Disclosure summary={`Категории ОКПД2: ${history.topCategories.length}`}><ul className={s.countList}>{history.topCategories.map(category => <li key={category.code}><code>{category.code}</code><span className={s.muted}>{category.lotCount}</span></li>)}</ul><p className={s.muted}>Одна закупка может относиться к нескольким категориям.</p></Disclosure>}
      {onOpen && <button type="button" className={s.linkButton} onClick={onOpen}>Примеры закупок</button>}
    </> : <p className={s.muted}>Сводная история участия не найдена. Это не значит, что компания не участвовала в закупках.</p>}
  </Card>;
}

/** Примеры участия из истории; если сводки нет - сохранённые в расчёте фрагменты. */
export function CompanyHistoryTable({ company }: { company: Company }) {
  const history = company.historySummary;
  const rows = history?.examples?.length ? history.examples.map(row => ({ key: `${row.source}-${row.lotId}`, lotId: row.lotId, date: row.date, subject: row.subject, source: row.source })) : company.history.map(row => ({ key: row.id, lotId: row.lotId, date: row.date, subject: row.subject, source: '' }));
  return <div className={s.stack}>
    <ExperienceCard history={history} />
    {rows.length ? <Card as="div"><div className={s.cardHead}><h2>{history?.examples?.length ? 'Примеры закупок с участием' : 'Закупки из расчёта'}</h2><p className={s.muted}>Показано {rows.length}. Это не полный перечень и не договоры.</p></div><div className={s.tableWrap}><table className={s.queryTable}><thead><tr><th scope="col">Закупка</th><th scope="col">Дата</th><th scope="col">Площадка</th></tr></thead><tbody>{rows.map(row => <tr key={row.key}><td data-label="Закупка"><span className={s.rowTitle}>{row.subject || 'Предмет не указан'}</span><span className={s.muted}>Лот {row.lotId}</span></td><td data-label="Дата">{date(row.date)}</td><td data-label="Площадка">{row.source || <span className={s.muted}>не указана</span>}</td></tr>)}</tbody></table></div></Card>
      : <Empty icon="clock" title="Записей участия нет">Возможности компании нужно проверить по другим источникам.</Empty>}
  </div>;
}
