import type { Company, CompanyHistory, SourceEvidence } from '../domain/types.js';
import { verifiedText } from '../domain/presentation.js';
import { date, safeURL } from '../domain/format.js';
import { Alert, Badge, Card, Empty } from './ui.js';
import s from '../styles/pages.module.css';

function SourceLinks({ ids, sources }: { ids: string[]; sources: SourceEvidence[] }) {
  return <>{sources.filter(source => ids.includes(source.id)).map(source => <p className={s.dossierSource} key={source.id}>{safeURL(source.url) ? <a href={safeURL(source.url)!} target="_blank" rel="noopener noreferrer">{source.title || 'Подтверждающий источник'}</a> : source.title}{source.fetchedAt && <span> · получен {date(source.fetchedAt)}</span>}</p>)}</>;
}

export function CompanyExperience({ history }: { history?: CompanyHistory | null }) {
  return <Card className={s.padded}><h2>Опыт в закупках</h2>{history?.lotCount ? <><div className={s.experienceFacts}><div><strong>{history.lotCount.toLocaleString('ru-RU')}</strong><span>уникальных закупок с участием</span></div><div><strong>{date(history.firstSeen)} - {date(history.lastSeen)}</strong><span>период доступных наблюдений</span></div></div><p className={s.muted}>Это записи об участии, а не подтверждение исполненных договоров.</p>{history.subjects.length > 0 && <><h3>Какие закупки встречались</h3><ul className={s.experienceList}>{history.subjects.slice(0, 4).map((subject, index) => <li key={index}><span>{subject.text}</span><small>{subject.lotCount} закупок</small></li>)}</ul></>}{history.topCategories.length > 0 && <details className={s.sourceDetails}><summary>Категории ОКПД2 в истории</summary><ul className={s.experienceList}>{history.topCategories.map(category => <li key={category.code}><span>{category.code}</span><small>{category.lotCount} закупок</small></li>)}</ul><p className={s.muted}>Одна закупка может относиться к нескольким категориям.</p></details>}{history.scope && <p className={s.muted}>{history.scope}</p>}</> : <p className={s.muted}>Сводная история пока не найдена. Это не означает, что компания не участвовала в закупках.</p>}</Card>;
}

export function CompanyChecks({ company }: { company: Company }) {
  const checks = company.dueDiligence?.checks ?? [];
  const sources = [...(company.currentProfile?.sources ?? []), ...(company.profileAtCalculation?.sources ?? [])].filter((source, index, list) => list.findIndex(row => row.id === source.id) === index);
  const labels = { verified: 'Есть источник', observed: 'Есть наблюдения', unknown: 'Не проверено', unverified: 'Не подтверждено', conflict: 'Есть противоречие' } as const;
  return <Card className={s.padded}><h2>Проверка перед сделкой</h2><p className={s.muted}>Показаны доступные факты и пробелы. Они не гарантируют надёжность будущей сделки.</p>{checks.length ? <ul className={s.diligenceList}>{checks.map(check => <li key={check.id}><div className={s.cardHeading}><h3>{check.title}</h3><Badge tone={check.status === 'verified' || check.status === 'observed' ? 'info' : check.status === 'conflict' ? 'warning' : 'neutral'} icon={false}>{labels[check.status]}</Badge></div>{(check.status === 'verified' || check.status === 'observed') && (typeof check.value === 'string' || typeof check.value === 'number') && <p className={s.diligenceValue}>{check.id === 'participation' && typeof check.value === 'number' ? `${check.value.toLocaleString('ru-RU')} уникальных закупок` : check.value}</p>}<p className={s.muted}>{check.limitation}</p><SourceLinks ids={check.sourceIds} sources={sources}/></li>)}</ul> : <Alert title="Проверка ещё не выполнена">Юридический статус, исполнение договоров, финансовое состояние и сведения реестра недобросовестных поставщиков пока не подтверждены.</Alert>}</Card>;
}

export function CompanyCompleteness({ company }: { company: Company }) {
  const fields = [['name', 'Название и ИНН'], ['description', 'Описание деятельности'], ['contacts', 'Деловые контакты'], ['website', 'Официальный сайт'], ['legalStatus', 'Юридический статус']] as const;
  return <Card className={s.padded}><h2>Достаточность сведений</h2><ul className={s.completenessList}>{fields.map(([key, label]) => { const field = company.currentProfile?.fields[key] ?? company.profileAtCalculation?.fields[key]; const known = key === 'contacts' ? field?.status === 'verified' && Array.isArray(field.value) && field.value.length > 0 : Boolean(verifiedText(company, key)); return <li key={key}><span>{label}</span><Badge tone={known ? 'info' : 'neutral'} icon={false}>{known ? 'Есть источник' : 'Нужно уточнить'}</Badge></li>; })}</ul><p className={s.muted}>Полнота карточки не подтверждает наличие товаров, сроки поставки и возможность выполнить все позиции закупки.</p></Card>;
}

export function CompanyHistoryTable({ company }: { company: Company }) {
  const history = company.historySummary;
  const rows = history?.examples.length ? history.examples.map(row => ({ key: `${row.source}-${row.lotId}`, lotId: row.lotId, date: row.date, subject: row.subject, status: 'Наблюдалось участие', source: row.source })) : company.history.map(row => ({ key: row.id, lotId: row.lotId, date: row.date, subject: row.subject, status: row.observedStatus, source: '' }));
  return <div className={s.verticalCards}><CompanyExperience history={history}/>{rows.length ? <Card><div className={s.padded}><h2>{history?.examples.length ? 'Примеры из истории' : 'Сохранённые фрагменты истории'}</h2><p className={s.muted}>Показаны {rows.length} записей. Это не полный перечень договоров компании.</p></div><div className={s.tableScroll}><table><thead><tr><th>Закупка</th><th>Дата</th><th>Что известно</th></tr></thead><tbody>{rows.map(row => <tr key={row.key}><td><strong>{row.lotId}</strong><p>{row.subject}</p></td><td className={s.dateCell}>{date(row.date)}</td><td>{row.status}{row.source && <p className={s.muted}>{row.source}</p>}</td></tr>)}</tbody></table></div><div className={s.padded}><Alert title="Участие не подтверждает исполнение">Проверьте, какие товары или услуги компания действительно может поставить сейчас.</Alert></div></Card> : <Empty icon="clock" title="Записи участия не найдены">Возможности компании нужно проверить по другим источникам.</Empty>}</div>;
}
