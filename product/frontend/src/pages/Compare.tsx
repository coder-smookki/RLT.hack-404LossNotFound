import React, { useEffect, useState, type ReactNode } from 'react';
import { companyName, evidenceTags, itemCoverage, verifiedContacts, verifiedText } from '../domain/presentation.js';
import { allRecommendations, evidenceLabel, itemStatus } from '../domain/recommendations.js';
import { Link, navigate, useParams } from '../app/router.js';
import { useResource } from '../api/client.js';
import { useApp } from '../app/store.js';
import type { QueryRecord, Recommendation } from '../domain/types.js';
import { PageHeader, Card, ButtonLink, Badge, Empty, Loading, Failure, IconButton, Disclosure, Button } from '../components/ui.js';
import { Pagination } from '../components/Pagination.js';
import { compareURL } from '../components/QueryParts.js';
import { ScoreBadge } from '../components/Score.js';
import { assessCandidate, winStats } from '../domain/assessment.js';
import { number, plural, safeURL } from '../domain/format.js';
import { paginate } from '../domain/pagination.js';
import s from '../styles/pages.module.css';

const checkStatus = (r: Recommendation, id: string) => { const check = r.company.dueDiligence?.checks.find(c => c.id === id); return check?.status === 'verified' ? 'есть источник' : check?.status === 'conflict' ? 'есть противоречие' : 'не проверено'; };

/** Одинаковые бизнес-критерии для каждой компании. Значения берутся из сохранённого результата и подтверждённых сведений. */
function criteria(q: QueryRecord): { label: string; value: (r: Recommendation) => ReactNode }[] {
  const total = q.procurement.items.length;
  return [
    { label: 'Оценка обоснованности', value: r => <ScoreBadge assessment={assessCandidate(r, q.procurement.items)} align="start" /> },
    { label: 'Раздел и место', value: r => `${r.company.origin === 'history' ? 'История закупок' : 'Внешние источники'}, № ${r.rank}` },
    { label: 'Основания', value: r => <ul className={s.tags}>{evidenceTags(r).map(t => <li key={t.label}><Badge tone={t.tone} icon={t.tone === 'warning'}>{t.label}</Badge></li>)}</ul> },
    { label: 'Позиции с основанием', value: r => { const c = itemCoverage(r, total); return `${c.withEvidence} из ${c.total}`; } },
    { label: 'Противоречия характеристик', value: r => { const n = itemCoverage(r, total).conflicts; return n ? `${n} ${plural(n, ['позиция', 'позиции', 'позиций'])}` : 'не найдены'; } },
    { label: 'Опыт участия', value: r => { const lots = r.company.historySummary?.lotCount ?? winStats(r)?.lotCount; const wins = winStats(r)?.winnerLotCount; return lots ? `${number(lots)} ${plural(lots, ['закупка', 'закупки', 'закупок'])} с участием${wins !== undefined ? `, побед: ${number(wins)}` : ''} (не договоров)` : 'нет сводных сведений'; } },
    { label: 'ОГРН', value: r => verifiedText(r.company, 'ogrn') ?? 'не подтверждён' },
    { label: 'Сайт', value: r => { const site = verifiedText(r.company, 'website'); return site && safeURL(site) ? <a href={safeURL(site)!} target="_blank" rel="noopener noreferrer">{site.replace(/^https?:\/\//, '').replace(/\/$/, '')}</a> : 'не найден'; } },
    { label: 'Контакты', value: r => { const c = verifiedContacts(r.company); return c.length ? c.map(x => x.value).join(', ') : 'не найдены'; } },
    { label: 'Юридический статус', value: r => checkStatus(r, 'registration') },
    { label: 'Исполнение договоров', value: r => checkStatus(r, 'execution') },
    { label: 'Финансы и РНП', value: r => `финансы: ${checkStatus(r, 'finances')}; РНП: ${checkStatus(r, 'rnp')}` },
  ];
}

/**
 * Сравнение 2-4 компаний одной закупки по одинаковым критериям. Выбор передаётся в адресе,
 * поэтому ссылка работает после перезагрузки. На узком экране компании показываются карточками.
 */
export function Compare() {
  const url = useParams(), id = url.pathname.split('/')[2] ?? '', app = useApp(), r = useResource<QueryRecord>(`/queries/${id}`);
  const fromURL = (url.searchParams.get('ids') ?? '').split(',').map(x => decodeURIComponent(x)).filter(Boolean);
  const [itemPage, setItemPage] = useState(1);
  const q = r.data, valid = q ? allRecommendations(q).map(x => x.company.id) : [];
  const ids = q ? (fromURL.length ? fromURL : app.selected(q)).filter(x => valid.includes(x)).slice(0, 4) : [];
  useEffect(() => { if (q && fromURL.length && ids.join() !== app.selected(q).join()) app.setSelection(q, ids); }, [q?.id, url.search]);
  if (r.loading) return <Loading text="Загружаем сравнение" />;
  if (r.error) return <Failure error={r.error} onRetry={r.reload} />;
  if (!q) return null;
  const rows = ids.map(cid => allRecommendations(q).find(x => x.company.id === cid)!).filter(Boolean), list = criteria(q);
  const remove = (cid: string) => { const next = ids.filter(x => x !== cid); app.setSelection(q, next); navigate(next.length ? compareURL(q, next) : `/queries/${q.id}/compare`, { replace: true, scroll: false }); };
  const items = paginate(q.procurement.items, itemPage, 25);
  const header = <PageHeader eyebrow={`Лот ${q.procurement.lotId}`} title="Сравнение кандидатов" subtitle={q.procurement.subject} actions={rows.length > 0 ? <ButtonLink secondary icon="download" to={`/exports?queryId=${q.id}&selection=1`}>Экспорт выбранных</ButtonLink> : undefined} />;
  if (rows.length < 2) return <>{header}<Empty icon="compare" title="Выберите хотя бы две компании" action={<ButtonLink to={`/queries/${q.id}/results`}>К кандидатам закупки</ButtonLink>}>Отметьте от двух до четырёх компаний в списке кандидатов. Сейчас выбрано: {rows.length}.</Empty></>;
  return <>
    {header}
    <p className={[s.muted, s.lead].join(' ')}>Сравниваются сведения, а не гарантии поставки. Отсутствие данных не означает непригодность компании; частичные совпадения разных компаний не складываются в исполнение лота.</p>
    <Card as="div" className={s.compareCard}>
      <div className={s.tableWrap}><table className={s.compareTable} style={{ minWidth: 220 + rows.length * 220 }}><caption className={s.visuallyHidden}>Сравнение компаний по одинаковым критериям</caption>
        <thead><tr><th scope="col" className={s.stickyCol}>Критерий</th>{rows.map(row => <th scope="col" key={row.company.id}><div className={s.compareHead}><Link to={`/companies/${encodeURIComponent(row.company.id)}?queryId=${q.id}`}>{companyName(row.company)}</Link><IconButton icon="close" label={`Убрать из сравнения: ${companyName(row.company)}`} onClick={() => remove(row.company.id)} /></div><span className={s.muted}>ИНН {row.company.inn ?? 'не указан'}</span></th>)}</tr></thead>
        <tbody>{list.map(c => <tr key={c.label}><th scope="row" className={s.stickyCol}>{c.label}</th>{rows.map(row => <td key={row.company.id}>{c.value(row)}</td>)}</tr>)}</tbody>
      </table></div>
    </Card>
    <div className={s.compareCards}>{rows.map(row => <Card key={row.company.id} className={s.padded}><div className={s.compareHead}><Link to={`/companies/${encodeURIComponent(row.company.id)}?queryId=${q.id}`} className={s.rowTitle}>{companyName(row.company)}</Link><IconButton icon="close" label={`Убрать из сравнения: ${companyName(row.company)}`} onClick={() => remove(row.company.id)} /></div><span className={s.muted}>ИНН {row.company.inn ?? 'не указан'}</span><dl className={s.cardFacts}>{list.map(c => <div key={c.label}><dt>{c.label}</dt><dd>{c.value(row)}</dd></div>)}</dl></Card>)}</div>
    <Card as="div" className={s.block}><div className={s.cardHead}><Disclosure summary={`Сравнение по позициям: ${q.procurement.items.length}`}>
      <div className={s.tableWrap}><table className={s.compareTable} style={{ minWidth: 260 + rows.length * 180 }}><thead><tr><th scope="col" className={s.stickyCol}>Позиция</th>{rows.map(row => <th scope="col" key={row.company.id}>{companyName(row.company)}</th>)}</tr></thead>
        <tbody>{items.items.map((item, i) => <tr key={item.id}><th scope="row" className={s.stickyCol}><span className={s.itemNo}>{(items.page - 1) * 25 + i + 1}</span> {item.name}</th>{rows.map(row => { const e = row.evidence.find(x => x.itemId === item.id); return <td key={row.company.id}>{e && e.kind !== 'none' ? <Link to={`/companies/${encodeURIComponent(row.company.id)}?queryId=${q.id}&tab=items&item=${encodeURIComponent(item.id)}`}>{evidenceLabel(e)}</Link> : <span className={s.muted}>нет основания</span>}{itemStatus(e) === 'conflict' && <span className={s.visuallyHidden}> (противоречие)</span>}</td>; })}</tr>)}</tbody></table></div>
      <Pagination page={items.page} pages={items.pages} total={items.total} size={25} onChange={setItemPage} label="Страницы позиций" />
    </Disclosure></div></Card>
    <div className={s.belowCard}><Button variant="ghost" icon="back" onClick={() => navigate(`/queries/${q.id}/results`)}>К кандидатам закупки</Button></div>
  </>;
}
