import { useParams, updateParams } from '../app/router.js';
import { useResource } from '../api/client.js';
import type { Analytics as AnalyticsType } from '../domain/types.js';
import { PageHeader, Card, Tabs, Input, Loading, Failure, Empty, ButtonLink, Stat } from '../components/ui.js';
import { Pagination } from '../components/Pagination.js';
import { number, plural } from '../domain/format.js';
import { paginate } from '../domain/pagination.js';
import s from '../styles/pages.module.css';

/** Статистика только по данным аккаунта: загруженные закупки, позиции, наличие кандидатов, категории, площадки и годы. */
export function Analytics() {
  const params = useParams().searchParams, tab = params.get('tab') ?? 'categories', search = params.get('code') ?? '', r = useResource<AnalyticsType>('/analytics');
  if (r.loading) return <Loading text="Считаем статистику" />;
  if (r.error) return <Failure error={r.error} onRetry={r.reload} back={{ to: '/', label: 'На главную' }} />;
  if (!r.data) return null;
  const a = r.data;
  if (!a.notices) return <><PageHeader title="Статистика" subtitle="Только ваши загруженные закупки и результаты." /><Empty title="Пока нечего считать" icon="chart" action={<ButtonLink to="/search" icon="upload">Загрузить файлы</ButtonLink>}>Статистика появится после первой загрузки закупок. Мы не показываем примерных или демонстрационных чисел.</Empty></>;
  const categories = a.categories.filter(c => c.code.includes(search.trim())), maxRows = Math.max(1, ...a.categories.map(c => c.rows)), page = paginate(categories, params.get('page'), 25);
  return <>
    <PageHeader title="Статистика" subtitle={`Только ваши данные. Даты публикации закупок: ${a.period}.`} />
    <div className={s.statsRow}>
      <Stat value={number(a.notices)} label={plural(a.notices, ['закупка', 'закупки', 'закупок'])} />
      <Stat value={number(a.items)} label="позиций ТРУ" />
      <Stat value={number(a.withSuppliers)} label="закупок с кандидатами" />
      <Stat value={number(a.withoutSuppliers)} label="без кандидатов или ещё без подбора" />
      <Stat value={number(a.inn)} label="компаний в результатах" />
      <Stat value={number(a.codes)} label="кодов ОКПД2" />
    </div>
    <Tabs label="Разрезы статистики" value={tab} onChange={v => updateParams({ tab: v === 'categories' ? undefined : v, code: undefined, page: undefined })} items={[{ id: 'categories', label: 'Категории ОКПД2', count: a.categories.length }, { id: 'sources', label: 'Площадки и годы' }]} />
    {tab === 'sources' ? <div className={s.twoColumns}>
      <Card as="div"><div className={s.cardHead}><h2>Площадки</h2></div><table className={s.statTable}><thead><tr><th scope="col">Площадка</th><th scope="col" className={s.numCol}>Закупок</th></tr></thead><tbody>{a.sources.map(x => <tr key={x.name}><td>{x.name || 'не указана'}</td><td className={s.numCol}>{number(x.lots)}</td></tr>)}</tbody></table></Card>
      <Card as="div"><div className={s.cardHead}><h2>Годы публикации</h2></div>{a.years.length ? <table className={s.statTable}><thead><tr><th scope="col">Год</th><th scope="col" className={s.numCol}>Закупок</th></tr></thead><tbody>{a.years.map(x => <tr key={x.year}><td>{x.year}</td><td className={s.numCol}>{number(x.lots)}</td></tr>)}</tbody></table> : <p className={s.emptyInline}>Даты публикации не указаны.</p>}</Card>
    </div> : <Card as="div">
      <div className={s.cardHead}><h2>Позиции по кодам ОКПД2</h2><Input label="Найти код" hideLabel type="search" icon="search" placeholder="Например, 33.13" value={search} onChange={value => updateParams({ code: value || undefined, page: undefined })} /></div>
      {categories.length ? <table className={s.statTable}><thead><tr><th scope="col">Код ОКПД2</th><th scope="col">Доля от самой частой категории</th><th scope="col" className={s.numCol}>Позиций</th></tr></thead><tbody>{page.items.map(c => <tr key={c.code}><td className={s.codeCell}>{c.code}</td><td><span className={s.bar} aria-hidden="true"><span style={{ width: `${Math.max(2, c.rows / maxRows * 100)}%` }} /></span></td><td className={s.numCol}>{number(c.rows)}</td></tr>)}</tbody></table> : <p className={s.emptyInline}>{search ? 'Такого кода в ваших позициях нет.' : 'В позициях нет кодов ОКПД2.'}</p>}
      <Pagination page={page.page} pages={page.pages} total={page.total} size={25} onChange={n => updateParams({ page: String(n) })} />
    </Card>}
    <p className={s.belowCard}>{a.sourceNote}</p>
  </>;
}
