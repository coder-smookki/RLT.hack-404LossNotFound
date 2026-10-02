import React, { useMemo } from 'react';
import { Link, useParams, updateParams } from '../app/router.js';
import { useResource } from '../api/client.js';
import type { QueryRecord } from '../domain/types.js';
import { QueryTabs, LotFacts } from '../components/QueryParts.js';
import { PageHeader, Card, Input, Loading, Failure, Disclosure } from '../components/ui.js';
import { Pagination } from '../components/Pagination.js';
import { allRecommendations } from '../domain/recommendations.js';
import { companyLabel } from '../domain/presentation.js';
import { plural } from '../domain/format.js';
import { paginate } from '../domain/pagination.js';
import s from '../styles/pages.module.css';

const PAGE = 50;
const OKPD2_TITLE = 'Общероссийский классификатор продукции по видам экономической деятельности';

/** Уровни кода ОКПД2 без выдуманных названий: раздел, класс, подкласс, группа, вид. */
export function okpdLevels(code: string | null): string {
  if (!code) return 'Код не указан во входном файле.';
  const parts = code.split('.'), names = ['класс', 'подкласс', 'группа', 'подгруппа', 'вид'];
  return parts.map((_, i) => `${names[i] ?? 'уровень'} ${parts.slice(0, i + 1).join('.')}`).join(', ');
}

/**
 * Состав закупки: все позиции без обрезки текста, поиск, страницы по 50 строк и для каждой позиции -
 * сколько кандидатов имеют по ней основание со ссылкой на карточку первого из них в сохранённом порядке.
 */
export function Lot() {
  const url = useParams(), id = url.pathname.split('/')[2] ?? '', search = url.searchParams.get('q') ?? '';
  const r = useResource<QueryRecord>(`/queries/${id}`);
  const q = r.data, rows = useMemo(() => {
    if (!q) return [];
    const recs = allRecommendations(q);
    return q.procurement.items.map((item, index) => { const withEvidence = recs.filter(rec => rec.evidence.some(e => e.itemId === item.id && e.kind !== 'none')); return { item, index, withEvidence }; });
  }, [q]);
  if (r.loading) return <Loading text="Загружаем позиции закупки" />;
  if (r.error) return <Failure error={r.error} onRetry={r.reload} />;
  if (!q) return null;
  const p = q.procurement, needle = search.trim().toLowerCase();
  const filtered = needle ? rows.filter(row => `${row.item.name} ${row.item.okpd2 ?? ''}`.toLowerCase().includes(needle)) : rows;
  const page = paginate(filtered, url.searchParams.get('page'), PAGE);
  const duplicates = new Set(p.items.map(i => `${i.name}|${i.okpd2}`)).size !== p.items.length;
  return <>
    <PageHeader eyebrow={`Лот ${p.lotId} · ${p.items.length} ${plural(p.items.length, ['позиция', 'позиции', 'позиций'])}`} title={p.subject || 'Закупка без описания'} />
    <LotFacts query={q} />
    <QueryTabs query={q} value="items" />
    <div className={s.filters}>
      <Input label="Поиск по наименованию или коду" hideLabel type="search" icon="search" placeholder="Наименование или код ОКПД2" value={search} onChange={v => updateParams({ q: v || undefined, page: undefined })} />
      <p className={s.muted}>{needle ? `Найдено ${filtered.length} из ${p.items.length}` : `Все ${p.items.length} позиций в исходном порядке${duplicates ? ', повторы сохранены' : ''}`}</p>
    </div>
    <Disclosure className={s.spacedDisclosure} summary={<span>Что такое <abbr title={OKPD2_TITLE}>ОКПД2</abbr></span>}><p className={s.muted}>Код классификатора продукции из входного файла. Первые две цифры - класс, каждая следующая часть уточняет группу. Код помогает найти кандидатов, но сам по себе не подтверждает нужный товар или услугу.</p></Disclosure>
    <Card as="div">
      <div className={s.tableWrap}><table className={s.itemsTable}><caption className={s.visuallyHidden}>Позиции закупки</caption><thead><tr><th scope="col" className={s.numCol}>№</th><th scope="col">Наименование и характеристики</th><th scope="col"><abbr title={OKPD2_TITLE}>ОКПД2</abbr></th><th scope="col">Кандидаты с основанием</th></tr></thead>
        <tbody>{page.items.map(({ item, index, withEvidence }) => <tr key={item.id}>
          <td className={s.numCol} data-label="№">{index + 1}</td>
          <td data-label="Наименование" className={s.itemName}>{item.name}</td>
          <td data-label="ОКПД2" className={s.codeCell}>{item.okpd2 ? <span title={okpdLevels(item.okpd2)}>{item.okpd2}</span> : <span className={s.muted}>не указан</span>}</td>
          <td data-label="Основания">{withEvidence.length ? <Link to={`/companies/${encodeURIComponent(withEvidence[0]!.company.id)}?queryId=${q.id}&tab=items&item=${encodeURIComponent(item.id)}`} title={`Первый в списке: ${companyLabel(withEvidence[0]!.company)}`}>{withEvidence.length} {plural(withEvidence.length, ['компания', 'компании', 'компаний'])}</Link> : <span className={s.muted}>нет оснований</span>}</td>
        </tr>)}</tbody></table></div>
      {!filtered.length && <p className={s.emptyInline}>По запросу «{search}» позиций нет.</p>}
      <Pagination page={page.page} pages={page.pages} total={page.total} size={PAGE} onChange={n => updateParams({ page: String(n) })} label="Страницы позиций" />
    </Card>
    <p className={s.belowCard}>Количество и условия поставки во входных данных не указаны - их нужно уточнить у компаний.</p>
  </>;
}
